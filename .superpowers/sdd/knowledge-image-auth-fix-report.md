# Knowledge image authentication fix

## Change

- `KnowledgePage` now requests protected `/api/knowledge/image` resources through `apiFetch`, converts successful responses to Blob object URLs, and renders only those URLs in Markdown, source thumbnails, and the lightbox.
- The page shows an in-place loading message while the authenticated request is pending and a non-link fallback on request or image decode failure. It does not expose a bearer token in a URL and does not restore a direct image endpoint URL.
- Object URLs are revoked when their associated image set is replaced or the rendering component unmounts.

## Validation

- `npm run lint` passed with two pre-existing Fast Refresh warnings in `src/components/ui/button.tsx` and `src/components/ui/badge.tsx`.
- `npm run build` passed (`tsc -b && vite build`). Vite reported the existing >500 kB chunk-size advisory.
- No frontend unit-test runner is configured in `careercrew_web/package.json`; validation therefore used static verification plus the production TypeScript build.
