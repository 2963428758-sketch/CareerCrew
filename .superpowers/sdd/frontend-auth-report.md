# Frontend local-account authentication report

## Delivered

- Added `GET /api/auth/bootstrap`, a read-only unauthenticated capability check returning only `{ "available": boolean }`. It is true only in development before any account exists; it exposes no account data.
- Added an application-level authentication gate. Startup exchanges the HttpOnly refresh cookie for an access token; while that check is running the existing pages are not mounted. An anonymous browser sees the normal username/password form, or the first-admin form only when the capability endpoint says bootstrap is available.
- Access tokens live only in the `careercrew_web/src/lib/auth.ts` module. Neither access nor refresh tokens are written to `localStorage` or `sessionStorage`; refresh tokens remain browser-managed HttpOnly cookies.
- Consolidated every existing frontend business request, including NDJSON streaming and upload polling, behind `apiFetch`. It sends `credentials: include`, attaches the current bearer token, makes one refresh-and-retry attempt after a 401, and changes the application state back to anonymous if refresh or retry fails.
- Added an authenticated user indicator and logout action. Logout calls the server endpoint, then always clears the in-memory client session.

## Verification

- `F:\Python_develop\miniconda3\envs\careercrew\python.exe -m pytest -q tests/api/test_auth_api.py` — 5 passed.
- `npm run build` in `careercrew_web` — passed.
- `npm run lint` in `careercrew_web` — passed with two pre-existing Fast Refresh warnings in `src/components/ui/button.tsx` and `src/components/ui/badge.tsx`.
- No frontend test runner is configured in `careercrew_web/package.json`; focused automated frontend unit tests were therefore not added.

## Manual acceptance checklist

1. With a fresh development account database, open the web app: only the first-admin form is rendered. Create an account using a valid username and a password of at least 12 characters; the main application should load immediately.
2. Reload the page: no login form should flash after the refresh cookie is exchanged for an in-memory access token. Inspect browser storage and verify there are no token entries.
3. Use a protected page, then wait for or force access-token expiry. The next API request should refresh once and complete without returning to login.
4. Clear or revoke the refresh cookie/session, then make a protected request. The app should return to the login screen; it must not repeatedly retry the request.
5. Click the sidebar logout icon. Verify `POST /api/auth/logout` succeeds, reload the app, and verify the login screen remains visible.
6. In a non-development deployment or after any account exists, verify the first-admin form is absent and only username/password login is available.

## Scope and concerns

- The refresh/retry path intentionally retries once only. Current request bodies are JSON or `FormData`, which are reusable for that retry. If a future endpoint sends a one-shot `ReadableStream` body, it should opt out or provide a body factory.
- This change does not add public registration, change cookie attributes, or alter authorization rules. Creating non-admin accounts remains the existing authenticated administrator-only API.
