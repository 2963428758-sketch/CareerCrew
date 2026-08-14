# Task 1 Report: Postgres 情景记忆最新事件排序

## Implementation

- Updated `PostgresMemoryDb.latest_episodic` to query `ORDER BY ts DESC, id DESC`, so the newest timestamp wins and equal timestamps use the largest ID as the deterministic tie-breaker.
- Added a real PostgreSQL integration test. It writes a newer event before an older one, then writes a lower ID with the same newest timestamp; `latest_episodic` must still return `e_010`.
- Added the `postgres-memory` GitHub Actions job with a PostgreSQL 16 service and `POSTGRES_TEST_DSN`, which runs that integration test directly.

## Tests and Results

- `POSTGRES_TEST_DSN=postgresql://careercrew:careercrew@localhost:5432/careercrew F:\Python_develop\miniconda3\envs\careercrew\python.exe -m pytest -q tests/integration/test_postgres_memory_db.py` — passed (1 test) against local PostgreSQL 16.
- `F:\Python_develop\miniconda3\envs\careercrew\python.exe -m pytest -q tests/unit/test_episodic_memory.py` — passed (7 tests).
- `F:\Python_develop\miniconda3\envs\careercrew\python.exe -m compileall -q careercrew_core/memory/db.py tests/integration/test_postgres_memory_db.py` — passed.
- Parsed `.github/workflows/ci.yml` with PyYAML and checked the PostgreSQL job/service/DSN — passed.
- Queried the local database after the test: zero `postgres-order-*` episodic rows remained.

## Files Changed

- `careercrew_core/memory/db.py`
- `tests/integration/test_postgres_memory_db.py`
- `.github/workflows/ci.yml`

## Self-Review

- The production Postgres query, rather than `FakeMemoryDb`, is the only behavior changed.
- The regression asserts database-observed behavior through `PostgresMemoryDb`; it does not inspect SQL text.
- The test data isolates itself with a UUID user ID and removes it in `finally`.
- The CI job installs only the dependencies needed for this database test and provides a health-checked PostgreSQL service.

## Concerns

None. The GitHub-hosted CI job has not run yet from this local checkout.
