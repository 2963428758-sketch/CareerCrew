# Task T0.2 Report — Qdrant owner-migration verification script + migration report

## Status

DONE

## What I implemented

New script `scripts/verify_qdrant_ownership.py` (chose new script over modifying
`migrate_knowledge_visibility.py`, since that sibling is a knowledge-only user_id→owner
transform with a different semantic; the new script adds snapshot + unowned counting + the
plan-required JSON report without disturbing existing behavior).

Script responsibilities (CLI style matching the sibling: argparse, PROJECT_ROOT
`sys.path` insertion, qdrant_client via `load_settings`):

- `--collection NAME` — process one collection (default: both existing collections).
- `--default-owner u_001` — owner value for backfill (default per plan).
- `--apply` — write mode; default is dry-run (writes nothing).
- `--report PATH` — JSON report path; default prints to stdout AND writes
  `data/migrations/qdrant-owner-report-<timestamp>.json` (creates dir if missing).
- Snapshot step: for each collection POST snapshot and record the name. `--apply` aborts
  on snapshot failure; dry-run only warns and continues.
- Statistics per collection: `scanned`(=points) / `unowned` / `changed` / `skipped` /
  `conflicts`. `unowned` = point with neither `owner_user_id` nor `user_id`.
  `changed` = points that would be written with `owner_user_id` (orphans). `conflicts` =
  point already carrying an `owner_user_id` differing from `--default-owner` (never
  overwritten). `unresolved` set equal to `conflicts` (semantically identical here).
- Report JSON includes plan-required fields: `snapshot_id(s)`, `scanned`, `updated`,
  `conflicts`, `unresolved`, `started_at`, `finished_at`, plus per-collection detail and a
  `mode` marker.
- Migration rule unchanged: unowned → `owner_user_id = u_001`. Episodic orphans are
  backfilled with `owner_user_id` while its `user_id` semantic is left untouched.
- After `--apply`, automatically re-runs dry-run and prints
  `changed=0 conflicts=0 unowned=0`; any non-zero ⇒ non-zero exit code (plan: else migration
  failed).

Key semantics reconciliation (see brief "现状"):
- Knowledge (`careercrew_mm`) uses `owner_user_id` as its ownership key.
- Episodic (`careercrew_episodic_v2`) uses `user_id`. A point counts as owned if *either*
  key is present (so the prior backfill of `owner_user_id` on episodic points also counts
  as owned); orphan = both keys absent.

## What I tested + results

New unit tests: `tests/unit/test_verify_qdrant_ownership.py` (10 tests, TDD).

| Test | What it verifies |
|------|------------------|
| `test_classify_owned_knowledge` | `owner_user_id` present ⇒ owned |
| `test_classify_owned_episodic_by_user_id` | `user_id` present ⇒ owned |
| `test_classify_orphan` | neither key ⇒ orphan |
| `test_classify_owned_by_owner_when_episodic_user_id_absent` | episodic point w/ owner_user_id only ⇒ owned |
| `test_verify_dryrun_no_write` | dry-run does not call `set_payload`, counts correct |
| `test_verify_apply_backfills_and_rerun_all_zero` | apply backfills, re-run yields all-zero |
| `test_verify_conflict_not_overwritten` | conflicting owner not overwritten, counted as conflict |
| `test_snapshot_collection_success` | snapshot name returned |
| `test_snapshot_collection_failure_returns_none` | failure ⇒ None (no throw) |
| `test_build_report_has_required_fields` | report JSON has all plan-required fields |

Full backend suite: `uv run pytest -q` → **449 passed, 8 skipped** (baseline 439 +
10 new), exit 0.

## TDD Evidence

### RED

```
$ uv run pytest tests/unit/test_verify_qdrant_ownership.py -q
...
tests\unit\test_verify_qdrant_ownership.py:18: in <module>
    from verify_qdrant_ownership import (  # noqa: E402
E   ModuleNotFoundError: No module named 'verify_qdrant_ownership'
```

Expected: the module did not exist yet, so collection failed — confirming the tests are
genuinely exercising implementation that must now be written.

### GREEN

```
$ uv run pytest tests/unit/test_verify_qdrant_ownership.py -q
..........                                                               [100%]
10 passed
```

## Real dry-run / apply results

Ran against live Qdrant 1.19.0 at `http://localhost:6333` (real dev data).

- **careercrew_mm**: points=211, unowned=0, changed=0, skipped=211, conflicts=0
- **careercrew_episodic_v2**: points=14, unowned=0, changed=0, skipped=14, conflicts=0
- **totals**: scanned=225, updated=0, conflicts=0, unowned=0

Since `unowned=0` everywhere **no apply was needed** (per brief: apply only if unowned>0).
Final verification result: already consistent — `changed=0 conflicts=0 unowned=0`.

Snapshot IDs (real, recorded in report JSON):

- `careercrew_mm-8719326142855901-2026-08-15-13-19-22.snapshot`
- `careercrew_episodic_v2-8719326142855901-2026-08-15-13-19-23.snapshot`

## Report JSON

Path: `data/migrations/qdrant-owner-report-20260815-211924.json`

(A second timestamped file `qdrant-owner-report-20260815-211851.json` was produced by an
intermediate buggy dry-run before a fix; both are gitignored. The 211851 file predates the
`apply`-block fix and is superseded by 211924.)

Content summary:

```json
{
  "snapshot_id": {"careercrew_mm": "...-13-19-22.snapshot", "careercrew_episodic_v2": "...-13-19-23.snapshot"},
  "scanned": 225, "updated": 0, "conflicts": 0, "unresolved": 0,
  "started_at": "2026-08-15T13:19:22.457056+00:00",
  "finished_at": "2026-08-15T13:19:24.000690+00:00",
  "mode": "DRY-RUN",
  "collections": {
    "careercrew_mm": {"key_field": "owner_user_id", "points": 211, "unowned": 0, "changed": 0, "skipped": 211, "conflicts": 0},
    "careercrew_episodic_v2": {"key_field": "user_id", "points": 14, "unowned": 0, "changed": 0, "skipped": 14, "conflicts": 0}
  }
}
```

## Files changed

- `scripts/verify_qdrant_ownership.py` (new)
- `tests/unit/test_verify_qdrant_ownership.py` (new)
- `.gitignore` (added `data/migrations/`)

Commit: `64d1156` — `feat(qdrant): ownership verification script with snapshot and migration report`

## Self-review findings

- **Completeness**: all brief requirements covered — CLI, snapshot, dry-run/apply,
  unowned/changed/skipped/conflicts/unresolved, JSON report with required fields,
  auto re-verify after apply, exit codes, real dry-run execution + report, gitignore.
- **Quality**: pure counting logic (`_classify_point`, `scan_collection`,
  `verify_collection`, `build_report`) separated from I/O; tests use a `FakeClient`, no
  :memory: Qdrant dependency.
- **YAGNI**: did not implement apply-time re-verify persistence beyond the plan's
  requirement; no extra flags.
- **Discipline**: only staged script/test/.gitignore — did not touch unrelated modified
  files in the working tree (careercrew_web/*, .superpowers/*).

## Concerns

- The brief still cites the plan's `232` estimate; actual current dry-run total is **225**
  (211 + 14). Per brief, acceptance is "post-migration dry-run all zero", which holds.
- `snapshot_id` is reported as a per-collection map (plan says "snapshot ID(s)"; plural
  allowed). A single scalar is not well-defined when two collections are snapshotted.

## Fix Round (review findings)

Addresses reviewer Important findings 1–3 on `scripts/verify_qdrant_ownership.py`.

### Changes made

- **Finding 1 — symmetric conflict rule.** Removed the `and owner != ORPHAN_OWNER` term
  from the conflict condition in `verify_collection`; conflict is now purely
  `owner is not None and owner != default_owner`. With `--default-owner u_999`, a point
  owned by `u_001` now correctly counts as a conflict (it is no longer a magic exempt
  constant), and a point owned by `u_999` counts as skipped (equal to default, not a
  conflict-against-itself). Backfill logic was left keyed on key presence (orphan = both
  keys absent), so it was already independent of the `ORPHAN_OWNER` constant.
- **Finding 3 — unresolved accounting.** Wrapped the `set_payload` call during apply in
  try/except: on failure the point increments a new per-collection `unresolved` counter
  (instead of `changed`) and the loop `continue`s to the remaining points.
- **Finding 2 — unresolved != conflicts by construction.** `verify_collection` now returns
  a 6-tuple `(scanned, unowned, changed, skipped, conflicts, unresolved)`; `run` stores
  `unresolved` per collection; `build_report` computes `unresolved` independently via
  `sum(c.get("unresolved", 0) ...)` instead of aliasing `conflicts`.

### Tests

- Updated `test_verify_dryrun_no_write`, `test_verify_apply_backfills_and_rerun_all_zero`,
  and `test_verify_conflict_not_overwritten` to unpack the new 6-tuple.
- Added `test_verify_conflict_with_non_default_owner` (non-default `--default-owner`:
  another owner = conflict, default value not magic).
- Added `test_verify_apply_set_payload_failure_counts_unresolved` (apply `set_payload`
  raises → counted in `unresolved` not `changed`, run continues; report `unresolved`
  independent of `conflicts`), backed by a `FailingSetPayloadClient` fake.

Commands + results:

```
$ uv run pytest tests/unit/test_verify_qdrant_ownership.py -q
12 passed

$ uv run pytest -q
451 passed, 8 skipped, 3 warnings   (baseline 449 passed + 8 skipped)
```

### Commit

Commit: `fix(qdrant): symmetric conflict rule and unresolved accounting for apply failures`
(HEAD of `feature/agent-feedback-eval`; SHA self-referential to this commit — retrieve via
`git log --oneline -1`)
