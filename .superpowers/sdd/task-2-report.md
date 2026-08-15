# Task 2 report: local accounts, JWT, and administrator provisioning

## Implementation

- Added a focused SQLite-backed account and refresh-session store at `careercrew_api/auth/service.py`.
  Account IDs are opaque `u_<uuid>` values, except the first bootstrap administrator is always
  `u_001`; this preserves the ownership invariant for existing single-user data without altering
  business storage before Task 3.
- Passwords use `argon2-cffi`'s `PasswordHasher`.  Account responses contain only `id`,
  `username`, and `role`; password hashes and refresh-token values are never serialized.
- Added short-lived HS256 access JWTs and random opaque refresh tokens.  Refresh tokens are stored
  only as SHA-256 hashes, rotate atomically on `/api/auth/refresh`, and are removed by logout.
- Added `/api/auth/bootstrap`, `/api/auth/token` (and `/login` alias), `/refresh`, `/logout`,
  `/me`, and administrator-only `/users` routes.  Refresh tokens are `HttpOnly`, `SameSite=Lax`,
  scoped to `/api/auth`, and never returned in JSON.
- Added `auth` configuration.  Development/test uses a per-process random fallback signing secret;
  production requires an explicit 32+ character secret and `cookie_secure=true` when the FastAPI
  application is built.  Local CORS already has explicit Vite origins and `allow_credentials=true`,
  which is compatible with the refresh cookie.

## Tests and results

- `F:\Python_develop\miniconda3\envs\careercrew\python.exe -m pytest -q tests/api/test_auth_api.py`
  -> 4 passed.
- `F:\Python_develop\miniconda3\envs\careercrew\python.exe -m py_compile careercrew_api\auth\service.py careercrew_api\auth\dependencies.py careercrew_api\routers\auth.py careercrew_core\state\settings.py`
  -> passed.
- `F:\Python_develop\miniconda3\envs\careercrew\python.exe -m pytest -q tests/unit/test_config_loading.py tests/api`
  -> 85 passed.
- `git diff --check` -> passed.

The auth API tests cover password login, unauthenticated/protected `/me`, absence of raw refresh
tokens in JSON, refresh-cookie rotation and replay rejection, logout invalidation, administrator-only
account creation, and production startup failure without an authentication secret.

## Files changed

- `pyproject.toml`
- `config/settings.yaml`
- `careercrew_core/state/settings.py`
- `careercrew_api/main.py`
- `careercrew_api/schemas.py`
- `careercrew_api/auth/__init__.py`
- `careercrew_api/auth/service.py`
- `careercrew_api/auth/dependencies.py`
- `careercrew_api/routers/auth.py`
- `tests/api/test_auth_api.py`

## Self-review

- Bootstrap uses `BEGIN IMMEDIATE` and the fixed `u_001` ID, so a concurrent first-user request
  cannot create two bootstrap administrators.
- Refresh rotation is a single immediate SQLite transaction: the presented token is deleted before
  the replacement hash is inserted, making an old-token replay fail.
- Access JWT verification requires subject, role, type, and expiry, then checks that the account
  still exists with the same role.
- Task 3 boundaries were intentionally left untouched: existing business endpoints still accept
  their current user identifiers and are not yet protected by this foundation.

## Concerns

- Account/session storage is local SQLite by design for local credentials and no new service.  A
  horizontally scaled production deployment would need a shared account/session backend as a
  follow-up, before running multiple API instances.
- The existing API CORS policy targets local Vite origins.  A production deployment must set its
  approved HTTPS frontend origins alongside `auth.cookie_secure: true` and `AUTH_JWT_SECRET`.
