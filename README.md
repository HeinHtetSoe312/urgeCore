# Urge Core Engine

An asynchronous FastAPI backend that simulates a small financial engine: wallets with an
append-only ledger, and crowdfunded social credit where row-level locking stops concurrent
requests from corrupting balances.

> **Status: in progress (v0.2-alpha).** Anything listed under "Implemented" is only included 
> when its test is green in CI. Anything listed under "Planned" does not exist yet. This is a 
> simulation: no real money, no payment provider, no KYC.

## Implemented

- Async FastAPI service, SQLAlchemy 2.0 (async), PostgreSQL 15, Docker Compose (Redis is used by the readiness probe only)
- Registration and login: argon2id hashing, short-lived JWTs with the algorithm pinned
- Strict validation (Pydantic v2, unknown fields rejected), RFC 9457 error responses,
      correlation IDs, health probes
- CI on GitHub Actions: ruff and the integration tests against real Postgres and Redis
      containers
- Alembic async environment and initial schema migration, tested up and down
- Ledger service with tested invariants (balance matches ledger; money is conserved)
- Crowdfunding campaigns: create, contribute, partial fills, volume-weighted average rate
- `SELECT ... FOR UPDATE` locking with one global lock order, verified by a 50-way
      concurrent contribution test and an unsafe-versus-locked demonstration
**Stress testing:** Deliberately broke the locking to verify that the concurrency test fails as expected.

## Planned (not built)

Campaign acceptance and refunds (settlement), the spending-friction domain, 1-on-1 social
loans, idempotency keys, rate limiting, metrics, deployment, load tests.

## Design

- [`docs/design-spec.md`](docs/design-spec.md): target design and schema
- [`docs/architecture.md`](docs/architecture.md): the contribute flow and the lock hierarchy
- [`docs/DECISIONS.md`](docs/DECISIONS.md): decision log

Principles: PostgreSQL is the source of truth; every balance change writes a ledger row in the
same transaction; one global lock order (parent row first, then user rows in ascending id), so
transactions cannot deadlock; every locking read refreshes the ORM's cached copy
(`populate_existing`).

## Run it

Requires Docker and Python 3.11+ (developed on 3.12).

```bash
cp .env.example .env                 # then set the passwords and JWT_SECRET
docker compose up -d                 # Postgres + Redis
pip install -r requirements-dev.txt
alembic upgrade head                 # create the schema
uvicorn app.main:app --reload        # API docs at http://localhost:8000/docs
```

Try it:

```bash
curl -s -X POST localhost:8000/api/v1/auth/register -H 'content-type: application/json' \
  -d '{"username":"alice","password":"a-long-passphrase"}'
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"username":"alice","password":"a-long-passphrase"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s -X POST localhost:8000/api/v1/crowdfund -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"title":"Bike repair","target_amount":"100.00","target_interest_rate":"8.00"}'
```

Tests start their own throwaway Postgres and Redis containers, so Docker must be running:

```bash
ruff check . && ruff format --check . && pytest -q
```

## Known limitations

- Simulation only. No frontend.
- Campaigns can fill up but cannot yet be accepted or refunded, so contributed money stays
  escrowed.
- No idempotency keys: a client that retries a money-moving request could apply it twice.
- No rate limiting: do not expose this to the internet.
- The ledger is one signed row per user with implicit escrow; it is not double-entry.

## Project history

Urge started as a first-year Flask prototype (tag `legacy-flask-baseline`). The prototype was
not under version control until it was imported as a single baseline commit on 17 October
2026, so this repository's history does not cover its original development. In October 2026 I
began rewriting it as an asynchronous FastAPI service; this repository tracks that rewrite.
Tags: `legacy-flask-baseline` (the prototype), `v0.1.0` (skeleton), `v0.2-alpha` (ledger and
crowdfunding).

**Why a rewrite:**  I have always wanted to expand on the original project, or protoype, as a class project but my technical capabilities were too limited. Now that I am barely capable after countless tutorials, I decided to plan and rewrite it instead of starting an entirely new project.

## License

MIT, see `LICENSE`.
