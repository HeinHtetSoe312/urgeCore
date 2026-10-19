# Decision log

Short records of the main design choices and their costs. 

### ADR-001: Postgres is the source of truth; Redis is only an accelerator
- **Problem:** Balances, ledger entries and campaign state need one authoritative home. Money data must survive crashes and never be half-applied, while health checks (and later, caches) benefit from a fast store.
- **Options considered:**
  1. Postgres only.
  2. Postgres as the source of truth, Redis as an optional accelerator.
  3. Redis as the primary store with persistence enabled (AOF/RDB), Postgres as a copy.
- **Decision and why:** Option 2. Postgres gives ACID transactions, constraints, row locks and durable commits, which is what money logic depends on. Redis is an in-memory store that can lose recent writes on failure and has no equivalent of multi-row transactions and constraints. Today Redis is used only by the readiness probe. The rule going forward: anything held in Redis must be losable or rebuildable from Postgres without losing money, and a cached value never gates a money decision.
- **Trade-offs / what could go wrong:** Two stateful services to run and monitor. Once caching exists, cache and database can disagree, so stale reads must be tolerated or avoided on money paths. Readiness checks both services, so a Redis outage marks an otherwise working instance as not ready. Postgres becomes the throughput ceiling and the connection pool has to be sized for that.

### ADR-002: argon2id password hashing and short-lived JWTs
- **Problem:** Store passwords so a database leak does not expose them, authenticate API calls without a server-side session store, and avoid revealing which usernames exist.
- **Options considered:**
  1. bcrypt, scrypt or argon2id for hashing.
  2. Server-side sessions, opaque tokens or signed JWTs for authentication.
- **Decision and why:** argon2id (argon2-cffi defaults), because it is memory-hard, which makes large-scale GPU cracking more expensive than for CPU-bound hashes, and it is a current OWASP recommendation. Signed JWTs (HS256) that expire after 30 minutes by default, with `exp`, `iat` and `sub` required, the algorithm pinned on decode and a signing secret of at least 32 characters checked at startup: stateless verification, no session table, and a small window if a token leaks. Login returns one generic 401 for an unknown user and a wrong password. For an unknown username the code still verifies the password against a dummy hash created at startup, so both cases cost about the same time and the response time does not reveal whether an account exists. Hashing runs in a thread pool so it does not block the event loop.
- **Trade-offs / what could go wrong:** A JWT cannot be revoked before it expires, and there are no refresh tokens, so users log in again every 30 minutes. Argon2 is deliberately expensive, so login is a CPU and memory target until rate limiting exists. The dummy hash equalises the hashing time only; the database lookup still differs slightly, and registration returns a conflict when a username is taken, which reveals that it exists.

### ADR-003: Numeric/Decimal for money, with database CHECK constraints
- **Problem:** Represent money exactly and make invalid states, such as a negative balance or a zero-amount ledger entry, impossible even if application code has a bug.
- **Options considered:**
  1. Floating point.
  2. Integer minor units (cents).
  3. `Numeric(12,2)` in the database and `Decimal` in Python.
- **Decision and why:** Option 3, with CHECK constraints on money and status columns (for example `balance >= 0`, `amount <> 0` on ledger rows, `amount > 0` on contributions, and a fixed list of valid statuses). Binary floats cannot represent most decimal fractions exactly, so sums drift and equality checks fail. `Numeric`/`Decimal` is exact, readable in queries and aggregates exactly in SQL. Validation at the API (strict Pydantic types, positive amounts, two decimal places) rejects bad input early, but only the database constraint protects every code path, including future ones and manual fixes.
- **Trade-offs / what could go wrong:** Decimal values must never be mixed with floats, and rounding rules are our job (round only when storing or displaying). Constraints must be kept in step with the models through migrations. A CHECK constraint only sees one row, so rules that span rows (a balance against its ledger total) still need tests.

### ADR-004: Validate the correlation ID before it is logged
- **Problem:** A correlation ID ties together the log lines and error response of one request. If it comes from a client header and is used as-is, a client controls part of our logs and of our response headers.
- **Options considered:**
  1. Trust and echo whatever the client sends.
  2. Always generate the ID on the server.
  3. Accept a client-supplied ID only if it matches a strict pattern, otherwise generate one.
- **Decision and why:** Option 3. A client or upstream proxy may supply an ID so a trace can span services, but it is accepted only if it is 1 to 64 characters from letters, digits, dot, underscore and hyphen. Anything else is replaced by a generated UUID. Logs are JSON, which already escapes newlines inside a value, so the check is a second layer: it bounds size and character set, keeps IDs searchable and stops hostile content being echoed into a response header or read by a downstream log tool that is not JSON-aware.
- **Trade-offs / what could go wrong:** A legitimate ID in another format is replaced, which breaks tracing across services for that request. A client can still send a valid-looking ID that collides with another request's, so the ID is for correlation only and is never proof of identity or ownership.