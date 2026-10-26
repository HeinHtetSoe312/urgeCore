# Changelog

## v0.2-alpha (2026-10-26)

- Alembic async environment and `001_initial_schema` migration
- Ledger service with invariants I1 (balance matches ledger), I2 (money conserved) and
  I3 (campaign counters match contributions)
- Crowdfunding: create campaign, contribute (partial fills, VWAR), list and read campaigns
- `GET /api/v1/me/ledger`
- Pessimistic row locking with one global lock order; `populate_existing` on locking reads
- Tests: 50-way concurrent contribution test, authorization tests, migration test,
  unsafe-vs-locked race demonstration

## v0.1.0 (2026-10-19)

- Project skeleton: auth (argon2id + JWT), `/me`, RFC 9457 errors, correlation IDs, health
  probes, SQLAlchemy models, Docker Compose, CI (ruff + tests against real Postgres and Redis)
- Pinned dependencies, MIT license, design specification
- The legacy Flask prototype is preserved at the `legacy-flask-baseline` tag
