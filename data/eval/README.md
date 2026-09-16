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

# Optional product-runtime observation: only unavailable configuration/dependencies may skip
CAREERCREW_EVAL_RUNTIME=1 CAREERCREW_EVAL_RUN_ID=nightly_20260911 \
  CAREERCREW_EVAL_USER_ID=eval_nightly_20260911 \
  CAREERCREW_EVAL_TENANT_ATTESTATION=eval_nightly_20260911:nightly_20260911:provisioned \
  CAREERCREW_EVAL_TENANT_ATTESTATION_URL=https://<protected-provisioner>/v1/eval-tenants/attest \
  CAREERCREW_EVAL_TENANT_ATTESTATION_TOKEN=<protected-token> \
  CAREERCREW_EVAL_TENANT_ATTESTATION_NONCE=<provisioning-nonce> \
  CAREERCREW_EVAL_DISABLE_REMOTE_TRACING=1 \
  python scripts/eval_runner.py --real --runtime --allow-skip --report reports/real-eval.json

# Protected release gate: inject the dedicated eval tenant and runtime endpoints
# from the CI protected environment; missing environment, collection errors,
# case failures, cleanup failures, or regressions fail.
python scripts/eval_runner.py --real --runtime --require-real --compare data/eval/baseline.json --fail-on-regression --report reports/real-eval-release.json
```

`--model-probe` is a provider-connectivity diagnostic only. It does not run
CareerCrew's product runtime and is never valid with `--require-real`.
With `--require-real`, the runner also requires a protected provisioning
authority receipt matching the dedicated user, run ID, nonce, and a future
expiry; the local `provisioned` string is only a structural guard.

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
