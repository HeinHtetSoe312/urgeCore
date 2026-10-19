# Urge Core Engine

An asynchronous FastAPI backend, being built as a portfolio project: wallets with an
append-only ledger, and crowdfunded social credit where row-level locking stops concurrent
requests from corrupting balances.

> **Status: v0.1.0, a skeleton.** Only the foundation exists (see "Implemented"). The ledger,
> crowdfunding and database migrations are not built yet. This is a simulation: no real money,
> no payment provider, no KYC.

## Implemented in v0.1.0

- Async FastAPI service, SQLAlchemy 2.0 (async) models, PostgreSQL 15 and Redis via Docker Compose
- Registration and login: argon2id password hashing, short-lived JWTs with the algorithm pinned
- `GET /api/v1/me` (the authenticated user's profile)
- Strict validation (Pydantic v2, unknown fields rejected), RFC 9457 error responses,
  correlation IDs, JSON logging, health probes
- Money columns are `Numeric(12,2)` with database CHECK constraints
- Tests that run against throwaway Postgres and Redis containers
- CI on GitHub Actions: ruff and the tests

## Planned (not built)

Alembic migrations, the ledger service, crowdfunding campaigns with row locking, settlement,
the spending-friction domain, 1-on-1 social loans, idempotency keys, rate limiting, metrics,
deployment. The target design is in [`docs/design-spec.md`](docs/design-spec.md) and is a plan,
not a description of the current code.

## Run it

Requires Docker and Python 3.11+ (developed on 3.12).

```bash
cp .env.example .env                 # then set the passwords and JWT_SECRET
docker compose up -d                 # Postgres + Redis
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && pytest -q
```

The tests create their own tables in a throwaway database, so Docker must be running. The
database schema is not created outside the tests yet: migrations arrive in v0.2, so the API
cannot register users against the compose database until then.

## Known limitations

- Simulation only. No frontend.
- No migrations yet, so the API has no persistent schema outside the tests.
- No rate limiting and no idempotency keys: do not expose this to the internet.

## Project history

Urge started as a first-year Flask prototype (tag `legacy-flask-baseline`). The prototype was
not under version control until it was imported as a single baseline commit on 17 October
2026, so this repository's history does not cover its original development. In October 2026 I
began rewriting it as an asynchronous FastAPI service; this repository tracks that rewrite,
starting with the v0.1.0 skeleton.

**Why a rewrite:** the prototype stored balances as floats, changed balances with a
check-then-update and no lock or ledger, used GET routes that move money, and had a
hard-coded Flask `SECRET_KEY` (a placeholder demo value, not a real credential).

## How this was built

Built with AI assistance: the skeleton began as an AI-generated starter that I then ran, tested
and adapted, and AI tools are used for review and boilerplate. <!-- Edit this line so it is
exactly true for you. -->

## License

MIT, see `LICENSE`.
