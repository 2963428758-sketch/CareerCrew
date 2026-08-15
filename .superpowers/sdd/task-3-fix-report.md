# Task 3 Review Fix Report

## Status

Completed against baseline/current head `4f26d37` on branch `codex/reliability-multitenancy`. All Important review findings are addressed with behavior-level regression coverage. The authenticated tenant isolation behavior from Task 3 remains green.

## Exact fixes

### 1. Qdrant legacy/tenant UUID source domains

- Split the former shared UUIDv5 namespace into explicit legacy/no-owner and tenant domains.
- Kept the original namespace and original length-prefixed name encoding for owner-scoped records. Existing tenant point IDs therefore remain stable; the regression pins the prior tenant UUID for `u_alice/e_001`.
- Assigned legacy/no-owner logical IDs a new fixed namespace. The former constructive collision pair—legacy logical ID `7:u_alicee_001` and tenant pair `(u_alice, e_001)`—now produces different physical IDs.
- Preserved `payload._id` and all public `VectorRecord.id` behavior.
- The regression performs actual in-memory Qdrant upserts for both members of the former collision pair and confirms that both records remain independently retrievable.

### 2. Complete and idempotent checkpoint migration

- Removed the `startswith("tenant:")` migration-status heuristic.
- Added a small `careercrew_tenant_thread_migrations` journal in the checkpoint SQLite database. Each successful apply records `(target_user_id, source_thread_id, destination_thread_id)` in the same transaction as all checkpoint table updates.
- Migration status is now based on a recorded source/destination pair plus the destination's current presence, not the spelling of a thread ID.
- Public IDs that merely begin with `tenant:` and even public IDs shaped exactly like the internal encoding (covered by `tenant:7:u_adminpublic`) migrate correctly.
- Reruns inspect the journal/current destination state and report zero changes without double-namespacing.
- Dry-run only reads the optional journal; it does not create the journal or otherwise mutate the database.

### 3. WAL-consistent, fresh checkpoint backups

- Replaced `shutil.copy2()` of the SQLite main file with `sqlite3.Connection.backup()`.
- A regression keeps a writer connection open in WAL mode, commits the source checkpoint into WAL, applies migration, and verifies the backup contains the pre-migration row. This proves the snapshot is not limited to the main database file.
- Every change-bearing apply writes a new UUID-suffixed `*.pre-tenant-migration-<uuid>.bak` snapshot. A later migration therefore cannot silently reuse or overwrite a stale backup.
- Idempotent no-change reruns do not create unnecessary backups.

### 4. Restart-idempotent and failure-strict Qdrant apply

- Qdrant destination comparison now includes normalized payload and vector semantics.
- If an interrupted prior run left both the legacy source and an identical tenant destination, dry-run reports one cleanup without mutation and apply deletes only the legacy source.
- If the destination differs in payload or vectors, migration records a conflict and preserves both records.
- New copies are retrieved and verified before source deletion; source deletion is retrieved and verified after the delete operation.
- Qdrant upsert/delete exceptions propagate from `migrate_qdrant_client`.
- The CLI no longer reports Qdrant exceptions as a successful `SKIP`; it prints `ERROR Qdrant` and returns exit code `3`. Ordinary migration conflicts continue to return exit code `2`.
- An injected delete interruption test proves the first apply raises after leaving a safe copied destination, and a retry recognizes the identical destination and finishes source cleanup.

## Behavior-level regression tests

Added or strengthened tests in:

- `tests/unit/test_tenant_isolation.py`
  - Existing owner-scoped physical UUID stays stable.
  - Former legacy/tenant constructive collision is separated.
  - Both formerly colliding records coexist and remain independently retrievable in real local Qdrant.
- `tests/unit/test_tenant_migration.py`
  - Exact internal-looking public checkpoint ID migrates and reruns idempotently.
  - Dry-run creates neither destination nor backup/journal changes.
  - WAL-resident committed source exists in the consistent backup.
  - A second change-bearing run creates a distinct second backup.
  - Identical copied Qdrant destination is cleaned up on retry.
  - Semantically different Qdrant destination is a non-destructive conflict.
  - Copy-then-delete interruption raises; retry finishes cleanup.
  - Qdrant CLI errors return nonzero.

## Verification results

Environment:

```powershell
$env:PYTHONPATH=(Get-Location).Path
F:\Python_develop\miniconda3\envs\careercrew\python.exe ...
```

1. Focused Task 3/authenticated isolation suite:

```powershell
python -m pytest -q tests/unit/test_tenant_migration.py tests/unit/test_tenant_isolation.py tests/unit/test_read_image.py tests/api/test_tenant_isolation_api.py
```

Result: `22 passed`.

2. Full unit and API regression suites:

```powershell
python -m pytest -q tests/unit tests/api
```

Result: `360 passed` (complete progress reached 100%; no failures).

3. Changed production modules compile:

```powershell
python -m py_compile careercrew_ai/vector_store/qdrant_store.py scripts/migrate_legacy_tenant.py
```

Result: passed.

4. Real repository dry-run:

```powershell
python scripts/migrate_legacy_tenant.py --target-user u_001 --skip-qdrant
```

Result: `mode=DRY-RUN`, `changes=3`, `conflicts=0`; no migration output was written.

5. Patch hygiene:

```powershell
git diff --check
```

Result: passed. Git emitted only the existing Windows LF/CRLF conversion notices.

The only test warning is the existing qdrant-client notice that payload indexes have no effect in local in-memory Qdrant mode.

## Self-review

- Finding 1: explicit namespace separation is present; the tenant namespace/name encoding is unchanged; logical `_id` remains unchanged; the exact former collision is covered at both mapping and store behavior levels.
- Finding 2: no thread ID prefix is used as migration status; an exact canonical-looking public ID is covered; apply+journal update is transactional; the immediate rerun is zero-change.
- Finding 3: checkpoint backup uses the SQLite backup API; WAL content is asserted; each later change-bearing run creates a new snapshot; dry-run/no-change reruns create none.
- Finding 4: identical destinations finish cleanup; differing destinations conflict; copy and delete outcomes are verified; mutation exceptions raise; CLI Qdrant exceptions are nonzero.
- Finding 5: dry-run immutability is asserted and exercised; the focused dual-user API/isolation suite and the full unit/API suites remain green.
- Scope: only Qdrant ID generation, the legacy migration script, focused tests, this plan, and this report changed. Pre-existing untracked SDD files were not edited or staged.

## Residual concerns

- No external Qdrant or production SQLite instance was mutated. The real migration must still be preceded by dry-run and operator review.
- Local Qdrant emits the expected payload-index warning; it does not affect migration or isolation assertions.
