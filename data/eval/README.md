# CareerCrew evaluation dataset contract

`cases.jsonl` is the checked-in, immutable-by-convention baseline dataset for
Phase 7 real-model and offline regression evaluation.

- Dataset version: `2026-09-10.v1`
- Format: one UTF-8 JSON object per line.
- Identity: `case_id` is canonical. `id` remains an accepted read-time alias
  for the existing dataset and is normalized to `case_id`; duplicate IDs fail
  loading.
- Required fields: `case_id` (or legacy `id`), `kind`, `question`, and
  `expected`. Supported kinds are `route`, `retrieval`, `citation`, `tool`,
  `memory`, and `consult`.
- Privacy: keep cases synthetic or redacted. Reports retain only IDs, kinds,
  timings, tokens, and safe error codes; never add prompts, answers, resumes,
  user IDs, or provider credentials.

## Commands

```bash
# Offline non-regression gate (required on PRs)
python scripts/eval_runner.py --offline --compare data/eval/baseline.json --fail-on-regression

# Intentional, human-reviewed offline baseline update
python scripts/eval_runner.py --offline --update-baseline

# Optional real-model observation: only unavailable configuration/dependencies may skip
python scripts/eval_runner.py --real --allow-skip --report reports/real-eval.json

# Protected release gate: missing environment, collection errors, case failures, or regressions fail
python scripts/eval_runner.py --real --require-real --compare data/eval/baseline.json --fail-on-regression --report reports/real-eval-release.json
```

Do not edit this dataset to make a failing run pass. Dataset or baseline changes
require human review, a new documented version, and an intentional baseline
update. Offline fixtures describe the recorded observation for this exact
dataset; real-model reports are observations, not approval to alter either
artifact.

Promoted bad-case JSONL supplied through `--bad-cases` also accepts legacy
`id`. Its `rubric` must contain a non-empty `must_include` and/or
`must_not_contain` list. When `rubric` is absent, a non-empty string/list
`expected` is normalized to `must_include`; an empty rubric is rejected rather
than treated as a passing case.
