# Design

Urge Core Engine is a simulated financial backend: users hold a wallet balance, every change
to a balance is recorded in an append-only ledger, and users can crowdfund small loans.
It is a learning project. There is no real money, payment provider or KYC.

## Data model

| Table | Purpose |
|-------|---------|
| `users` | Account, argon2id password hash, `balance` (`Numeric(12,2)`, CHECK `>= 0`, starts at 100.00) |
| `ledger_entries` | Append-only signed amounts, one row per balance change, with a reference to what caused it |
| `crowdfund_campaigns` | A borrower's target amount and maximum rate, plus running totals and a status |
| `crowdfund_contributions` | One lender's escrowed amount and yield bid for one campaign |
| `friction_configs`, `spending_ledger`, `outbox_events` | Created by the first migration but not used by any feature yet |

Money is `Decimal` in Python and `Numeric` in PostgreSQL, never a float.

## Invariants (checked by the tests)

1. **I1** For every user, `balance == 100.00 + SUM(ledger amounts)`.
2. **I2** Money is conserved: `SUM(balances) + SUM(held contributions) == 100.00 * users`.
3. **I3** Each campaign's `current_raised` and `weighted_yield_sum` equal the sums over its contributions.

Balances change only through `ledger_service.post_entry`, which writes the ledger row in the
same transaction.

## Contributing to a campaign

One transaction, with locks taken in a fixed order:

1. Lock the campaign row (`SELECT ... FOR UPDATE`). Concurrent contributors queue here.
2. Check the campaign is active, the caller is not its creator, and the bid is within the maximum rate.
3. Take `min(requested, remaining)`: a contribution that does not fully fit is partially filled.
4. Lock the lender's user row, insert the contribution, post the ledger entry, update the campaign totals.
5. If the campaign is now full, mark it `pending_settlement`. Commit.

Rules that keep this safe:

- **Lock order:** the parent row (campaign) first, then user rows. Every money transaction
  follows it, so two transactions cannot wait on each other in a cycle.
- **`populate_existing`:** the request's session has already loaded the caller's user. A locking
  query alone would return that cached object with a possibly stale balance, so locking reads
  use `populate_existing` to refresh it.
- **Volume-weighted average rate (VWAR):** `SUM(amount * bid) / SUM(amount)`, rounded half-up to 2 places.

## API

| Method and path | What it does |
|-----------------|--------------|
| `POST /api/v1/auth/register`, `POST /api/v1/auth/login` | Create an account, get a short-lived JWT |
| `GET /api/v1/me`, `GET /api/v1/me/ledger` | The caller's profile and their own ledger rows |
| `POST /api/v1/crowdfund`, `GET /api/v1/crowdfund`, `GET /api/v1/crowdfund/{id}` | Create, list active and read campaigns |
| `POST /api/v1/crowdfund/contribute` | Contribute to a campaign |

Identity always comes from the token, never from the request body, and unknown body fields are rejected.

## Security and operations

- Argon2id password hashing, with a dummy-hash check so unknown usernames and wrong passwords take similar time
- Short-lived JWTs with the algorithm pinned
- Strict Pydantic v2 validation
- Liveness and readiness probes, JSON logs with a correlation ID per request, RFC 9457 error responses

## Not built yet

Campaign acceptance and refunds, the spending-friction domain, 1-on-1 loans, idempotency keys,
rate limiting, metrics and deployment. 
