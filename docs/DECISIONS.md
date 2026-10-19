# Decision log

Write each entry in your own words. If you cannot answer the questions, you do not
understand the decision yet: learn it first.

## Template

### ADR-NNN: <title>
- Problem: what were you trying to solve?
- Options considered:
- Decision and why:
- Trade-offs / what could go wrong:

## Entries to write during Week 1

- ADR-001: Why Postgres is the source of truth and Redis only an accelerator.
- ADR-002: Why argon2id and short-lived JWTs; what the dummy-hash trick protects against.
- ADR-003: Why Numeric/Decimal with CHECK constraints instead of floats or app-only validation.
- ADR-004: Why the correlation ID is validated before it is logged.
