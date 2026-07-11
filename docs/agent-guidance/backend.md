# Backend Engineering Guidance

- Keep FastAPI routes thin and place reusable orchestration or domain behavior in focused modules.
- Do not run blocking network, filesystem, subprocess, or database work directly on an async event loop. Use the repository's established execution boundary.
- Apply explicit timeouts, bounded retries, and observable failure handling to external connectors. Do not create unbounded background tasks.
- Protect shared mutable state with deterministic synchronization and preserve cancellation and cleanup behavior.
- Prefer enforceable SQLite constraints such as `UNIQUE`, `NOT NULL`, foreign keys, and justified `CHECK` clauses over application-only assumptions.
- Keep writes and schema transitions transactional. Preserve existing data through explicit, non-destructive migrations.
- Support frequent filtering, joins, and ordering with evidence-based indexes; avoid N+1 access patterns through joins, batching, or prefetching.
- Treat request/response models, database schemas, connector payloads, and documented endpoints as contracts. Update callers, tests, and API documentation together when a contract changes.
- Validate malformed, missing, null, and partial external payloads at the trust boundary without logging secrets or private content.
- Run focused tests for the affected module, then `python -m unittest discover -s tests` for backend behavior changes.

