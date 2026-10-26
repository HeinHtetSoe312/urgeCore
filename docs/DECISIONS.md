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

### ADR-005: Every contribution locks the campaign row first
- **Problem:** Two contributions that arrive together both read the same remaining capacity, both pass the check and both write. The campaign ends up with wrong totals and the lenders are charged for money the campaign never recorded.
- **Options considered:**
  1. Pessimistic locking: `SELECT ... FOR UPDATE` on the campaign row at the start of the transaction.
  2. Optimistic locking: a version column with retry on conflict.
  3. `SERIALIZABLE` isolation with retry on serialization failure.
  4. A single conditional `UPDATE ... WHERE raised + amount <= target`.
- **Decision and why:** Option 1. Many requests contend for one hot row, which is where retries (options 2 and 3) multiply work and waste connections, while a short lock just queues requests. A contribution also writes a contribution row and a ledger row and applies a partial fill in one transaction, so a lone conditional `UPDATE` does not cover the whole operation. The lock lives in Postgres, so it holds across any number of app instances. A test runs the same workload twice: without the lock, 10 lenders each contributing 10.00 to a 50.00 campaign are charged 100.00 in total while the campaign records only 10.00 raised, and the invariant check flags it; with the lock exactly five succeed and five get a conflict.
- **Trade-offs / what could go wrong:** Contributions to one campaign are serialised, which caps throughput per campaign. A transaction that stays open blocks everyone behind it, so no network calls belong inside it. The database CHECK on `current_raised` would not have caught the unlocked bug (each lost update still wrote a valid number), which is why the invariant checks exist. This was not benchmarked against the retry-based options.

### ADR-006: Lock order is parent row first, then user rows in ascending id
- **Problem:** A deadlock happens when two transactions each hold a lock the other needs. Postgres detects the cycle and aborts one of them, so a user sees a failed request that was not their fault.
- **Options considered:**
  1. No fixed order; rely on deadlock detection and retry.
  2. A fixed global order for every money transaction.
  3. One global lock for all money operations.
- **Decision and why:** Option 2. Every transaction locks the parent row (the campaign) first, then user rows, in ascending id when it needs more than one. If all transactions acquire locks in the same order, a wait cycle cannot form. Option 3 is safe but serialises the whole system, and retrying after a deadlock hides a design bug and fails requests under load. Today a contribution locks one campaign and one user, so the ascending-id rule matters once an operation touches several users (settlement, loans). A test has 20 lenders each contribute to two campaigns at the same time and expects all 40 to succeed within a timeout, so a deadlock fails the test instead of hanging it.
- **Trade-offs / what could go wrong:** The order is a convention, not something the database enforces, so one new code path that locks in a different order can bring deadlocks back. Taking the parent first holds it slightly longer. Sorting ids is extra code that must not be skipped.

### ADR-007: `lock_user` and `lock_campaign` use `populate_existing`
- **Problem:** SQLAlchemy keeps one object per row in the session. The dependency that resolves the current user loads the user into the request's session before the service runs. A later `SELECT ... FOR UPDATE` then locks the real row but returns that cached object with its old values, so a balance check can pass on outdated data.
- **Options considered:**
  1. `populate_existing` on the locking query.
  2. `session.refresh(obj, with_for_update=True)` after loading.
  3. Never load the full user before the lock; carry only the id.
- **Decision and why:** Option 1, inside the two lock helpers, so every locking read overwrites the cached object with the row that was actually locked and call sites cannot forget it. Option 3 is fragile because any dependency can load the user first. Two tests cover it: one changes the balance from another session and shows the locking read returns the fresh value; the other shows the pitfall, that the same read without the option returns the cached object with the old balance.
- **Trade-offs / what could go wrong:** `populate_existing` discards unflushed changes on that object, so nothing should be modified on it before the lock is taken. It reloads the whole row. It only helps for objects fetched through the helpers; reading a balance from another loaded copy would still be stale.

### ADR-008: Append-only ledger; balances change only through `post_entry`
- **Problem:** Every balance needs an explanation and a way to detect corruption, and no code path should be able to change a balance silently.
- **Options considered:**
  1. A mutable balance column with no history.
  2. Balance derived only from the ledger (no balance column).
  3. An append-only ledger plus a balance column, both written by one function in the same transaction.
  4. Full double-entry accounting with an account for every party.
- **Decision and why:** Option 3. `post_entry` is the only place that inserts a ledger row and changes a balance, inside the caller's transaction, and it refuses a zero amount, a sub-cent amount or a result below zero. Ledger rows are only ever inserted. Tests check three invariants. I1: each user's balance equals 100.00 plus the sum of their ledger entries (catches a balance changed outside the ledger, a lost update, a double-applied entry). I2: balances plus funds still held in contributions equal 100.00 times the number of users (catches money created or destroyed). I3: each campaign's raised total and weighted sum equal the sums over its contributions (catches the campaign counters drifting from the real records). Option 4 is more rigorous but more work than this project needed.
- **Trade-offs / what could go wrong:** Not double-entry: escrow is implicit, so a ledger line has no explicit counter-entry. The balance column duplicates what the ledger holds, so the invariants must stay in the tests. "Append-only" and "only through `post_entry`" are held by convention and review, not by database permissions or triggers.

### ADR-009: Over-capacity contributions are partially filled, not rejected
- **Problem:** A contributor offers more than the campaign still needs. Under concurrency the remaining amount changes between the client reading it and the request being processed, so the client cannot reliably know what fits.
- **Options considered:**
  1. Reject any contribution larger than the remaining amount.
  2. Accept only the amount that fits (partial fill) and report what was accepted.
- **Decision and why:** Option 2. The campaign can reach its target exactly instead of stalling a little short, contributors do not have to guess the remaining capacity, and the outcome of concurrent requests is predictable: the earliest requests fill the campaign and later ones are turned away. The response gives the requested and accepted amounts and a `partially_filled` flag, and only the accepted amount is debited and recorded. A contribution to a campaign that is no longer active returns 409. The 50-way concurrency test checks exactly this boundary: a 205.00 target, fifty 10.00 contributions, 20 full fills plus one partial fill of 5.00 (21 accepted, 29 refused).
- **Trade-offs / what could go wrong:** The client can receive less than it asked for and must read the accepted amount. Weighted-average calculations must use the accepted amount, not the requested one. First come, first served: there is no fairness mechanism between contributors.