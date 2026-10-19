> This is the design specification for the target system. What is implemented today is
> listed in the README; where they differ, the README is the truth.

================================================================================
URGE CORE ENGINE - DESIGN SPECIFICATION
================================================================================
Status: Portfolio project (backend engineering and cloud architecture).
Baseline: legacy Flask app, preserved at git tag `legacy-flask-baseline`.
Target: asynchronous FastAPI core engine.
This is a SIMULATION. It moves no real money and integrates with no payment
provider. There is no KYC.

--------------------------------------------------------------------------------
1. MISSION AND ARCHITECTURE
--------------------------------------------------------------------------------
Urge is an asynchronous financial micro-engine built on FastAPI. It separates
personal spending guardrails from peer-to-peer social credit across two domain
boundaries.

DOMAIN A: PRIVATE SPENDING FRICTION ENGINE
  Lets users intercept impulse purchases using per-category friction tiers
  (Relaxed, Medium, Strict). Friction configs are served from a Redis cache
  with Postgres fallback. Domain A has no connection to credit scores or the
  public lending tables. The only shared resource is the user's wallet
  balance, and it is only accessed through the ledger service.

DOMAIN B: PUBLIC SOCIAL LENDING AND GROUP CROWDFUNDING ENGINE
  Peer-to-peer funding campaigns with lender yield bids, a Volume-Weighted
  Average Rate (VWAR), row-level locking to prevent write races, and an
  event-driven settlement window that refunds lenders automatically if the
  borrower does not accept in time.
  It also supports direct 1-on-1 social loans between accepted friends (the
  lineage from the Flask prototype): a lender accepts one specific request
  and the money moves atomically through the ledger under ordered row locks.
  Both flows share one ledger and one lock hierarchy (D12).

CROSS-CUTTING
  JWT auth, idempotency keys, correlation IDs, RFC 9457 (formerly 7807)
  problem-details errors, structured JSON logging, Prometheus metrics, health
  probes, containerisation, OpenAPI docs, automated tests in CI.

DESIGN PRINCIPLES
  P1. Postgres is the source of truth. Redis is an accelerator (cache,
      idempotency, expiry timers), never the only record of anything.
  P2. Every money movement writes a ledger entry in the same DB transaction.
  P3. Every background job is idempotent: safe to run twice, and safe to miss
      once because a sweep catches it.
  P4. Every claim in the README is backed by a test or a measurement.

--------------------------------------------------------------------------------
2. TECH STACK
--------------------------------------------------------------------------------
TIER 1 (MVP, must ship)
- FastAPI on Python 3.11+, async throughout
- Pydantic v2 (contracts, settings via pydantic-settings)
- PostgreSQL 15+ with SQLAlchemy 2.0 async and asyncpg
- Alembic migrations (async env)
- Redis 7 with notify-keyspace-events KEA
- JWT access tokens (PyJWT), argon2 password hashing
- Redis-backed X-Idempotency-Key (24 h TTL)
- RFC 9457 problem details (application/problem+json)
- Circuit breaker around Redis (custom, or aiobreaker); tenacity is used only
  for retry/backoff, since it is not a circuit breaker
- /health/liveness and /health/readiness (readiness checks DB and Redis)
- Tests: pytest, pytest-asyncio, httpx, testcontainers-python
- Quality: ruff, pre-commit
- CI: GitHub Actions (lint, tests with real Postgres/Redis, image build)
- docker-compose (Postgres + Redis + app), multi-stage Dockerfile
- Security baseline (section 4.7)
- Race-condition demo test (unsafe vs locked) and an architecture diagram in
  the README

TIER 2 (strong extras)
- Locust load test with post-run invariant checks
- Prometheus /metrics plus Grafana dashboard in compose
- Kubernetes manifests (Deployment, Service, ConfigMap, Secret, probes)
  verified on kind or minikube
- CI publishes the image to GitHub Container Registry
- mypy on the services layer
- Bruno API collection committed in the repo
- Rate limiting on login and money-moving routes; pip-audit, Dependabot and
  gitleaks in CI
- Outbox relay + Redis TTL settlement fast path + expiry listener (the
  reconciler alone already makes settlement correct; see D10)
- Basic live deployment: app + Postgres + Redis via docker-compose on one
  free-tier VM or container host, with a public /docs URL

TIER 3 (the "10/10" items): see section 8.

--------------------------------------------------------------------------------
3. SCHEMA
--------------------------------------------------------------------------------
Money uses Python Decimal and Numeric(12,2). Never floats. DB-level CHECK
constraints make invalid states impossible.

CORE
- User (users): id; username (String(80), unique, indexed); password_hash;
  balance (Numeric(12,2), default 100.00, CHECK >= 0); internal_credit_score
  (Integer, default 600; only modified by the repayment feature in Tier 3);
  verification_tier (String(20), default 'Basic'); created_at.
- LedgerEntry (ledger_entries): id (BigInteger); user_id (FK, indexed);
  amount (Numeric(12,2), signed); entry_type ('SPEND', 'ESCROW_HOLD',
  'ESCROW_REFUND', 'PAYOUT', 'P2P_LOAN_DEBIT', 'P2P_LOAN_CREDIT',
  'P2P_REPAY_DEBIT', 'P2P_REPAY_CREDIT'); reference_type; reference_id;
  created_at. (The four P2P_* types are added in Tier 1B; see D11.)
  INVARIANT I1 (tested): for every user, balance == starting balance +
  SUM(ledger amounts). Balances change ONLY through ledger_service.
  INVARIANT I2 (tested): money is conserved. SUM of every user's balance +
  SUM of contributions still 'held' == starting balance * number of users.
  For a finished social loan or campaign, the ledger entries of that
  reference sum to 0.

DOMAIN A
- FrictionConfig (friction_configs): id; user_id (FK); category (String(50));
  tier_level ('Relaxed', 'Medium', 'Strict'); consecutive_overrides (default
  0); UNIQUE (user_id, category).
- SpendingLedger (spending_ledger): id; user_id (FK); amount (CHECK > 0);
  vendor (String(100)); category (String(50)); timestamp; status
  ('Pending_Friction', 'Approved', 'Cancelled_By_User');
  friction_unlock_time (nullable; set for Medium and Strict).

DOMAIN B
- CrowdfundCampaign (crowdfund_campaigns): id; creator_id (FK); title
  (String(120)); target_amount (CHECK > 0); current_raised (CHECK between 0
  and target_amount); weighted_yield_sum (Numeric(18,4), running
  SUM(amount * bid)); target_interest_rate (Numeric(5,2), the borrower's
  maximum rate); final_settled_rate (nullable); status; settlement_deadline
  (nullable).
  STATE MACHINE: active -> pending_settlement -> funded;
  pending_settlement -> expired (refunded). All other transitions rejected.
- CrowdfundContribution (crowdfund_contributions): id; campaign_id (FK,
  indexed); user_id (FK); amount (CHECK > 0); lender_yield_bid (Numeric(5,2));
  timestamp; status ('held', 'released', 'refunded').
- OutboxEvent (outbox_events): id (UUID); event_type; payload (JSONB);
  processed; attempts; created_at; processed_at.

DOMAIN B, PART 2: DIRECT SOCIAL LOANS (Tier 1B, restored in v3.1)
- Friendship (friendships): id; requester_id (FK users); addressee_id (FK
  users); status ('pending', 'accepted'); created_at. CHECK requester_id <>
  addressee_id. UNIQUE index on (LEAST(requester_id, addressee_id),
  GREATEST(requester_id, addressee_id)) so a pair can exist once, in either
  direction. (The Flask prototype checked this in Python, which can race.)
- SocialLoanMemo (social_loan_memos): id; borrower_id (FK users); lender_id
  (FK users); principal (Numeric(12,2), CHECK > 0); interest_rate
  (Numeric(5,2), CHECK between 0 and 100; a flat percentage of principal
  agreed up front, as in the prototype; not an APR); amount_due
  (Numeric(12,2), CHECK >= principal; fixed at request time as principal +
  ROUND_HALF_UP(principal * rate / 100, 2)); due_date (Date); status;
  created_at; accepted_at (nullable); repaid_at (nullable). CHECK
  borrower_id <> lender_id. Indexes on (lender_id, status) and
  (borrower_id, status).
  STATE MACHINE: pending -> active -> repaid; pending -> rejected. All other
  transitions rejected.

STILL DEFERRED (Tier 3 only, no migrations until built)
- Counter-offers on social loans (the prototype had them), interest accrual
  over time, late fees, and credit-score updates from repayment (E1, D7).

--------------------------------------------------------------------------------
4. FUNCTIONAL REQUIREMENTS
--------------------------------------------------------------------------------
4.1 AUTH AND ACCOUNT
- POST /api/v1/auth/register, POST /api/v1/auth/login (JWT)
- GET  /api/v1/me (profile and balance)
- GET  /api/v1/me/ledger (cursor-paginated ledger entries)
- All other routes require a Bearer token. Identity comes from the token,
  never from the request body.

4.2 DOMAIN A
- PUT  /api/v1/spend/friction-config  (write-through to Redis cache with TTL)
- GET  /api/v1/spend                  (history, paginated)
- POST /api/v1/spend/initiate
  * Config from Redis, falling back to Postgres on miss or open breaker. No
    config for the category means 'Relaxed'.
  * Insufficient funds -> 422 problem details.
  * Relaxed: debit via ledger, 'Approved', HTTP 200.
  * Medium: 'Pending_Friction', friction_unlock_time = now + 3 s.
  * Strict: 'Pending_Friction', friction_unlock_time = now + 5 min.
  * Funds are debited at approval, not initiation; balance is re-checked then.
- POST /api/v1/spend/{id}/force-approve
  * 409 problem details (with seconds remaining) before friction_unlock_time.
    After unlock: debit, 'Approved', consecutive_overrides += 1.
- POST /api/v1/spend/{id}/abort
  * 'Cancelled_By_User', consecutive_overrides reset to 0.

4.3 DOMAIN B
- POST /api/v1/crowdfund                 create campaign
- GET  /api/v1/crowdfund                 list active campaigns (paginated)
- GET  /api/v1/crowdfund/{id}            state including current VWAR
- POST /api/v1/crowdfund/contribute
  * One transaction. First statement: SELECT ... FOR UPDATE on the campaign
    row. Then lock the lender's user row. Lock order is ALWAYS campaign
    then user, which prevents deadlocks.
  * Validate: campaign 'active'; bid <= campaign target_interest_rate;
    contributor is not the creator.
  * Partial fill: accept only the remaining capacity and return the accepted
    amount.
  * Debit lender (ESCROW_HOLD), insert contribution ('held'), update
    current_raised and weighted_yield_sum.
  * VWAR = weighted_yield_sum / current_raised; rounded half-up to 2 dp only
    when stored or displayed.
  * When current_raised == target_amount: status 'pending_settlement',
    settlement_deadline = now + SETTLEMENT_WINDOW (default 2 h, configurable
    so tests can use seconds), and an OutboxEvent is inserted in the SAME
    transaction.
- POST /api/v1/crowdfund/{id}/accept     (creator only)
  * Lock campaign. Must be 'pending_settlement' and before the deadline.
    Credit borrower (PAYOUT), contributions -> 'released', final_settled_rate
    = VWAR, status 'funded'.

4.3A DIRECT SOCIAL LOANS (1-on-1)  [Tier 1B]
Friends (prerequisite for a loan, as in the prototype):
- POST /api/v1/friends/requests               {username}; not yourself; the
  unique index rejects a duplicate pair in either direction (409).
- POST /api/v1/friends/requests/{id}/accept   addressee only.
- POST /api/v1/friends/requests/{id}/decline  addressee only; deletes the row.
- GET  /api/v1/friends                        the caller's accepted friends.
Loans:
- POST /api/v1/loans    borrower = the caller (from the token, never the body).
  Body: lender_id, principal, interest_rate, due_date (in the future).
  Requires an accepted friendship with the lender. Status 'pending'.
  amount_due is computed here with Decimal and stored.
- GET  /api/v1/loans    loans where the caller is borrower or lender
  (paginated), and nobody else's.
- POST /api/v1/loans/{id}/accept   lender only; the money moves now.
- POST /api/v1/loans/{id}/reject   lender or borrower, while 'pending'.
- POST /api/v1/loans/{id}/repay    borrower only.
Authorization is part of the query: each loan lookup filters on the caller's
role in the WHERE clause (for example id = :id AND lender_id = :caller). A
stranger's request matches zero rows, gets 404 (existence is not leaked) and
never takes a lock.

ACCEPT: one transaction, exact order
  1. SELECT ... FROM social_loan_memos WHERE id = :id AND lender_id = :caller
     FOR UPDATE.  No row -> 404.
  2. status must be 'pending', else 409.
  3. Lock the two user rows, one statement each, in ASCENDING user_id:
       for uid in sorted({lender_id, borrower_id}):
           SELECT ... FROM users WHERE id = :uid FOR UPDATE
     Use populate_existing so the ORM cannot hand back a stale balance (D16).
  4. lender.balance >= principal, else 422; nothing has been written yet.
  5. ledger_service posts two entries, both with reference
     ('social_loan_memo', id):
       lender   -principal   P2P_LOAN_DEBIT
       borrower +principal   P2P_LOAN_CREDIT
  6. status 'active', accepted_at = now(); commit.
REPAY: one transaction, same shape
  1. Lock the loan row WHERE id = :id AND borrower_id = :caller FOR UPDATE.
  2. status must be 'active', else 409 (a second repay sees 'repaid').
  3. Lock both user rows in ascending user_id, as above.
  4. borrower.balance >= amount_due, else 422.
  5. borrower -amount_due P2P_REPAY_DEBIT; lender +amount_due
     P2P_REPAY_CREDIT. The interest is a transfer between two users; no
     money is created.
  6. status 'repaid', repaid_at = now(); commit.
REJECT: lock the loan row (WHERE id = :id AND (lender_id = :caller OR
  borrower_id = :caller)), status must be 'pending', set 'rejected'. No user
  locks and no ledger entries.
Why it cannot deadlock: D12. Two opposite loans (A lends to B while B lends
to A) both lock the lower user_id first, so neither waits on the other in a
cycle.
Idempotency (4.5) applies to accept and repay. Until that middleware exists,
the state machine already prevents double application: a retry gets 409,
never a second transfer.

4.4 SETTLEMENT KILL-SWITCH (event-driven with a safety net)
  Three cooperating, idempotent pieces:
  (a) Outbox relay: polls unprocessed rows with SELECT ... FOR UPDATE SKIP
      LOCKED, sets Redis key settle:{campaign_id} with the window as TTL,
      marks the row processed. At-least-once delivery.
  (b) Expiry listener: subscribes to expired-key events and calls
      settle_expired(campaign_id).
  (c) Reconciler: every 60 s, finds campaigns with status
      'pending_settlement' and settlement_deadline < now() (SKIP LOCKED) and
      calls settle_expired.
  Why (c) exists: keyspace notifications use pub/sub and are lost if the
  listener is down or disconnected. Without the reconciler, funds could stay
  in escrow forever.
  settle_expired: lock campaign; if status is not 'pending_settlement',
  return (already handled); refund every 'held' contribution (ESCROW_REFUND,
  status 'refunded') in ascending user_id order; status 'expired'. One
  transaction.

4.5 IDEMPOTENCY
- Applies to all money-moving POSTs. Scope (user_id, key). Stores request
  fingerprint (method, path, body hash), state, and response. TTL 24 h.
- Same key, same fingerprint, completed: replay the stored response.
- Same key while in progress: 409. Same key, different fingerprint: 422.
- Redis down: reads fail open; money-moving writes fail closed (503).

4.6 ERRORS AND OBSERVABILITY
- All errors are application/problem+json with type, title, status, detail,
  instance, and a correlation_id extension.
- X-Correlation-ID accepted or generated; present in every log line and
  response header.
- Metrics: request count and latency histogram, contributions, settlement
  outcomes, circuit-breaker state.

4.7 SECURITY REQUIREMENTS
Tier 1 baseline (cheap to build now, painful to retrofit later)
- Object-level authorization (OWASP API1): every query on spends, ledger,
  contributions and campaigns filters by the authenticated user_id in the
  service layer; "accept" checks creator_id; loans filter on the caller's role
  (lender_id or borrower_id) inside the WHERE clause. Tests prove user B gets 403/404
  on user A's resources.
- Authentication: argon2id password hashing; JWT with short expiry (for
  example 30 minutes), algorithm pinned on decode, exp/iat/sub validated,
  signing secret from the environment (32+ random bytes), never hard-coded.
  Login returns the same generic error for unknown user and wrong password.
- Input validation: Pydantic strict types; positive Decimal amounts with
  maximums and 2 dp; string length limits; extra="forbid" so unknown fields
  are rejected. Separate request and response schemas so clients can never set
  balance, status or credit score (mass assignment).
- SQL: SQLAlchemy parameterised queries only; no string-built SQL.
- Money safety: DB CHECK constraints, ledger invariant, and idempotency keys
  scoped per user so one user can never replay another user's response.
- Secrets: all from environment; .env never committed; .env.example holds fake
  values; tokens, passwords and keys redacted from logs.
- Errors: problem-details responses never include stack traces or SQL.
- Network exposure: Postgres and Redis are never published to the public
  internet. Redis has a password and listens on the internal network only; in
  compose publish DB/Redis ports to localhost only, if at all.
- Operational endpoints: /metrics and /docs disabled or restricted outside
  local/dev via a config flag; health endpoints reveal no sensitive detail.
- CORS: explicit allow-list (or none, since there is no frontend); never a
  wildcard with credentials.
- Container: non-root user, slim base image, .dockerignore excludes .env and
  .git.
- Dependencies: versions pinned in requirements.txt.
Tier 2
- Rate limiting on /auth/login and money-moving routes (Redis counters; fail
  closed on login).
- CI: pip-audit, Dependabot updates, gitleaks secret scan.
Tier 3: see section 8, category C.
Testing note: run Locust only against your own local or test environment,
never against third-party or shared infrastructure.

--------------------------------------------------------------------------------
5. PROJECT LAYOUT
--------------------------------------------------------------------------------
urge-core/
├── app/
│   ├── main.py
│   ├── api/v1/            auth.py, account.py, spend.py, crowdfund.py,
│   │                      friends.py, loans.py, health.py
│   ├── core/              config.py, logging.py, security.py, errors.py,
│   │                      middleware.py
│   ├── db/                session.py, redis.py (client + breaker)
│   ├── models/            domain_models.py
│   ├── schemas/           auth.py, spend.py, crowdfund.py,
│   │                      friends.py, loans.py
│   ├── services/          ledger_service.py, friction_service.py,
│   │                      vwar_service.py, settlement_service.py,
│   │                      friendship_service.py, loan_service.py
│   └── workers/           outbox_relay.py, expiry_listener.py, reconciler.py
├── alembic/
├── tests/                 unit/, integration/, conftest.py
├── loadtests/             locustfile.py, verify_invariants.py
├── bruno/                 API collection
├── k8s/                   Tier 2
├── terraform/             Tier 3, only if applied to real resources
├── .github/workflows/     ci.yml
├── docs/                  design-spec.md, DECISIONS.md, architecture.md,
│                          benchmarks.md, threat-model.md, runbook.md
├── docker-compose.yml, Dockerfile, requirements.txt
├── .env.example, LICENSE, CHANGELOG.md, README.md

--------------------------------------------------------------------------------
6. FINAL DESIGN DECISIONS
--------------------------------------------------------------------------------
D1. Lender bids must be <= the campaign's target_interest_rate.
D2. Over-capacity contributions are partially filled.
D3. Medium/Strict spends are debited at approval, with a balance re-check.
D4. Redis outage: money-moving idempotent writes fail closed (503).
D5. Pessimistic locking (FOR UPDATE) for contributions. Tier 3 includes a
    benchmark against optimistic and serializable-retry approaches.
D6. Postgres deadline plus reconciler is the source of truth for expiry;
    the Redis TTL is only a fast path.
D7. Credit score is unused in Tier 1; repayment flow is Tier 3.
D8. Settlement window is a setting (default 2 h) so tests run in seconds.
D9. Authorization is enforced in the service layer (not only in routes) so
    workers and future callers cannot bypass it.
D10. Settlement is built in two stages: (1) DB deadline + reconciler +
    settle_expired (correct on its own), then (2) the outbox relay and Redis
    TTL/keyspace listener as a fast path. Do not describe the system as
    event-driven in the README until stage 2 exists.
D11. Social-loan money movements use their own ledger entry types
    (P2P_LOAN_DEBIT/CREDIT, P2P_REPAY_DEBIT/CREDIT), not SPEND and PAYOUT.
    SPEND means a Domain A purchase and PAYOUT a crowdfund disbursement;
    reusing them would corrupt "total spent" style queries and blur the
    Domain A / Domain B boundary. Cost: four more values in one CHECK.
D12. ONE GLOBAL LOCK HIERARCHY for every money transaction:
    (1) the parent row first (a campaign OR a social loan), then
    (2) user rows, in ASCENDING user_id when there is more than one.
    Never lock a parent row while holding a user lock; never lock users in
    any other order. Contribute: campaign, then the lender. Campaign
    accept: campaign, then the borrower. settle_expired: campaign, then
    lenders ascending. Loan accept/repay: loan, then both users ascending.
D13. Social-loan interest is a flat percentage of principal agreed at
    request time; amount_due is stored. No accrual, no late fees. Credit-
    score effects stay in Tier 3 (D7).
D14. Social loans transfer at acceptance, with no escrow: one specific
    lender explicitly accepts one specific request. Crowdfunding keeps
    escrow because many lenders commit before the borrower accepts.
D15. Friendship uniqueness is enforced by the database (unique index on
    the unordered pair), not by an application-level existence check.
D16. Any read that gates a money decision (a balance, a status) is a
    SELECT ... FOR UPDATE executed with populate_existing. get_current_user
    already loaded the User into the request session, and without
    populate_existing the ORM returns that cached, possibly stale object.

--------------------------------------------------------------------------------
7. STATUS CHECKLIST (update as you go)
--------------------------------------------------------------------------------
Tier 1
[ ] Project skeleton, config, async DB session, Alembic initial migration
[ ] Auth (register, login, JWT) and /me endpoints
[ ] Correlation ID, JSON logging, RFC 9457 error handler, health probes
[ ] Ledger service and balance/ledger invariant test
[ ] Domain A: friction config, initiate, force-approve, abort
[ ] Redis cache with circuit-breaker fallback
[ ] Domain B: campaigns, contribute with locking, VWAR, partial fills
[ ] Concurrency integration test (50+ simultaneous contributions)
[ ] Settlement: accept + reconciler sweep (DB deadline) + settle_expired
[ ] Race-condition demo test (unsafe version fails, locked version passes)
[ ] Architecture diagram (Mermaid) linked from the README
[ ] Idempotency middleware with all edge cases
[ ] CI green (lint, tests with real containers, image build)
[ ] Security baseline (4.7) implemented, including authorization tests
[ ] README with architecture diagram and run instructions
Tier 1B (restored in v3.1; built after the v0.2 core)
[ ] Friendship: request, accept, decline, list; DB-level pair uniqueness
[ ] SocialLoanMemo: request, accept (ordered locks + ledger), reject, repay
[ ] Loan tests: double accept (one 200, one 409); opposite-direction accepts
    run concurrently with no deadlock; insufficient funds writes nothing;
    invariants I1 and I2 hold after accept and repay; a stranger gets 404
[ ] Deadlock demo: lender-then-borrower order deadlocks, ascending passes
Tier 2
[ ] Locust run with invariant verification, results in docs/benchmarks.md
[ ] Prometheus metrics and Grafana dashboard
[ ] Kubernetes manifests verified on kind/minikube
[ ] Image published to GHCR from CI
[ ] Bruno collection
[ ] Rate limiting; pip-audit, Dependabot and gitleaks in CI
[ ] Outbox relay, Redis TTL key and expiry listener (settlement fast path)
[ ] Basic live deployment (single VM/container host) with public /docs URL
Tier 3 ("10/10" extras; * = suggested minimum set)
[ ] A2* Property-based tests (Hypothesis) for VWAR and the ledger invariant
[ ] A3  Schemathesis fuzzing against the OpenAPI schema in CI
[ ] A4* Chaos scripts: kill Redis / listener / relay / app mid-settlement
[ ] A5  Correctness verified with 3 app replicas running
[ ] A6  Coverage gate in CI
[ ] A7  Outbox poison-message handling (attempts cap, failed state)
[ ] B1* Locking-strategy benchmark (FOR UPDATE vs optimistic vs serializable)
[ ] B2  EXPLAIN ANALYZE and index decisions with before/after numbers
[ ] B3  Connection pool tuning notes
[ ] C1* Threat model (docs/threat-model.md) + OWASP API Top 10 checklist
[ ] C2  Refresh-token rotation with reuse detection; revocation list
[ ] C3* CodeQL, Trivy image scan, SBOM in CI
[ ] C4  Container hardening, securityContext, NetworkPolicy
[ ] C5  Authorization test suite (users cannot touch each other's data)
[ ] D1* Continuous deploy from main (basic deployment is Tier 2)
[ ] D2  Terraform applied to real resources (destroy and recreate once)
[ ] D3  Kustomize/Helm, 3 replicas, resource limits, HPA on local cluster
[ ] D4  Grafana alerts, OpenTelemetry traces to Jaeger, a simple SLO
[ ] D5* Runbook (docs/runbook.md)
[ ] D6  Backup and restore drill
[ ] E1  Repayment flow and credit-score updates
[ ] E2  Notification consumer driven from the outbox
[-] E3  Friendship and SocialLoanMemo: MOVED to Tier 1B in v3.1
[ ] F1* Demo video (2-3 min) and README GIF
[ ] F2  Write-up post on lessons learned
[ ] F4  PR workflow, semantic versions, CHANGELOG, tagged releases

--------------------------------------------------------------------------------
8. TIER 3: THE "10/10" EXTENSIONS
--------------------------------------------------------------------------------
Not all are required. Pick across categories; depth beats quantity.

A. CORRECTNESS EVIDENCE (highest value)
  A1. [MOVED TO TIER 1] Race-condition demo: a test that shows lost updates / overfunding when
      the lock is removed, then passes with it. Keep both versions in the
      repo (the unsafe one clearly marked).
  A2. Property-based tests (Hypothesis) for VWAR and the ledger invariant.
  A3. Schemathesis fuzzing against the OpenAPI schema in CI.
  A4. Chaos scripts: kill Redis, kill each worker, kill the app mid-settlement;
      document and verify recovery.
  A5. Correctness verified with 3 app replicas running at once.
  A6. Coverage gate in CI (a sensible threshold, such as 85% on services).
  A7. Outbox poison-message handling: attempts cap, a 'failed' state, and an
      alert/metric, so one bad event can never block the relay.

B. PERFORMANCE EVIDENCE
  B1. Benchmark FOR UPDATE vs optimistic (version column) vs SERIALIZABLE with
      retry; publish results and justify D5.
  B2. EXPLAIN ANALYZE on key queries; index decisions with before/after data.
  B3. Connection pool tuning notes.

C. SECURITY (the baseline is in 4.7 and Tiers 1-2; these go further)
  C1. Threat model (STRIDE-lite) in docs/threat-model.md plus an OWASP API
      Security Top 10 checklist mapping each risk to where you handle it.
  C2. Refresh tokens with rotation and reuse detection; revocation list.
  C3. CI: CodeQL, Trivy image scan, SBOM generation.
  C4. Container hardening: read-only root filesystem, dropped capabilities,
      Kubernetes securityContext and NetworkPolicy on the local cluster.
  C5. Authorization test suite proving users cannot read or modify each
      other's data.

D. CLOUD AND OPERATIONS
  D1. Continuous deploy from main after CI passes. (The basic live
      deployment itself is now Tier 2; this item only automates it.)
  D2. Terraform applied to real resources; remote state; destroyed and
      recreated at least once to prove it works.
  D3. Kustomize or Helm; 3 replicas; resource limits; HPA on a local cluster.
  D4. Grafana alerts, OpenTelemetry traces to Jaeger, a simple SLO
      (for example, 99% of contributions under a stated latency).
  D5. Runbook (docs/runbook.md): "settlement stuck", "Redis down", "DB
      failover", with the exact steps to check and fix.
  D6. Backup and restore drill: pg_dump/restore into a fresh database, then
      run the ledger invariant check against the restored copy; document it.

E. DOMAIN DEPTH
  E1. Repayment flow and credit-score updates driven only by repayment
      history, with tests.
  E2. Notification consumer driven from the outbox (webhook simulator).
  E3. [MOVED TO TIER 1B in v3.1] Friendship and SocialLoanMemo (see 4.3A).

F. COMMUNICATION
  F1. 2 to 3 minute demo video and a README GIF.
  F2. A write-up post on what you learned (concurrency, outbox, reconciler).
  F3. [MOVED TO TIER 1] C4-style architecture diagrams in Mermaid.
  F4. PR-based workflow even when solo, semantic versioning, CHANGELOG,
      tagged releases (v1.0 at end of Tier 2).

WHAT "10/10" MEANS HERE
  The system is deployed, correctness is proven under failure and load, the
  numbers are published, security basics are automated, and a stranger can
  run it in three commands and understand why each decision was made.
  Suggested minimum set: A2, A4, B1, C1, C3, D1, D5, F1.

--------------------------------------------------------------------------------
9. NON-GOALS
--------------------------------------------------------------------------------
Real payments, KYC, a frontend, mobile apps, real credit scoring, multi-region
deployment.
