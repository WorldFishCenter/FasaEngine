# Integration Guide (External Developers)

This guide is for teams integrating FASA into a web app, mobile app, dashboard, or backend service.

## 1) Quick architecture view

- `fasa_core/`: domain and optimization engine (business logic)
- `fasa_api/`: HTTP adapter (FastAPI endpoints and transport concerns)
- `data/`: required CSV data assets used by the engine

For integrations, treat the HTTP API as the stable boundary.

## 2) Base URL and authentication

- Base URL: provided by the deployment team (Cloud Run service URL)
- Auth:
  - `Authorization: Bearer <token>`, or
  - `X-API-Key: <token>`
- `/health` is public for liveness checks.
- Other endpoints require token auth unless `FASA_REQUIRE_AUTH=false` in the environment.

Example:

```bash
curl -X GET "${BASE_URL}/supported" \
  -H "Authorization: Bearer ${FASA_API_TOKEN}"
```

## 3) API contract source of truth

- Swagger UI: `${BASE_URL}/docs`
- OpenAPI JSON: `${BASE_URL}/openapi.json`

Use the OpenAPI contract for generated clients and payload validation in your app.

## 4) Error handling contract

Business/auth errors follow:

```json
{
  "detail": {
    "code": "unauthorized",
    "message": "Invalid or missing API token.",
    "details": null
  }
}
```

Recommended client behavior:

- `400`: show actionable message to user (invalid request values)
- `401`: refresh/replace token and retry once
- `422`: treat as client payload validation issue
- `503`: service not ready; retry with backoff

## 5) Retry and timeout recommendations

- Set client timeout to 90-120s for `/formulate` calls.
- Retry strategy:
  - Retry only on `503` and transient network failures.
  - Use exponential backoff (e.g. 1s, 2s, 4s; max 3 retries).
  - Do not retry `400/401/422` blindly.

## 6) Integration checklist

- Validate connectivity with `/health` and `/ready`.
- Call `/supported` first to fetch valid `species`, `production_system`, and `stage`.
- Build `/formulate` payload from those discovered values.
- Handle `status` in response (`optimal`, `infeasible`, `error`).
- Log request IDs on your side (if your client/service adds them) for easier debugging.

## 7) Upgrade playbook

- Before upgrading environments:
  - compare old vs new `openapi.json`
  - run your client integration tests against the target deployment
- Avoid hardcoding enum-like values outside `/supported` when possible.
- Track README release notes for contract-impacting changes.
