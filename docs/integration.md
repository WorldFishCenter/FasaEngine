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

Use the OpenAPI contract for generated clients and payload validation.

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
- Call `/supported` first to fetch valid `species`, `production_system`, `stage`, and `countries`.
- Build `/formulate` payload from those discovered values.
- Optionally send `country` (ISO-2: `KE`/`NG`/`ZM`) to have each recipe line flagged
  `locally_available` (`true`/`false`; `null` when no `country` is sent). This is an
  advisory highlight only — the optimizer is never restricted to local ingredients.
- Optionally send `nutrient_limits` and/or `ingredient_limits` to bound dietary nutrient
  levels (ASNS spec code -> `{min, max}` in that code's ASNS unit) or single-ingredient
  inclusion (FICD code -> `{min, max}` as a mass fraction of feed). These override the
  engine's configured limit tables for the codes they name; where ASNS already states the
  same bound, the tighter value binds. Each `recipe` line echoes the box applied
  (`min_inclusion_percent`, `max_inclusion_percent`, `limit_source`) and each
  `composition` line carries a `source` naming where its target came from.
- **Watch the units on ingredient limits:** you send a **fraction** (`{"max": 0.15}`) and
  get back a **percentage** (`"max_inclusion_percent": 15.0`). Out-of-range request values
  are rejected with 422, so `15` sent for 15% fails loudly, but rendering `0.15` as "0.15%"
  fails silently — convert in both directions. Nutrient limits are not rescaled: they go in
  and come back in that spec code's ASNS unit.
- Handle `status` in response (`optimal`, `infeasible`, `error`).
- On `infeasible`, check `infeasibility.bound_conflicts` before `iis_codes`: when it is
  non-empty the ingredient inclusion limits alone cannot add up to the feed mass and no
  IIS was computed.
- To check a recipe the user edited (or one from elsewhere) without re-running the LP,
  post it to `/validate-recipe` with the same `species`/`stage`/`production_system` and
  any limit overrides. It returns `in_limits`, per-ingredient `inclusion_checks`, and
  `nutrient_checks` in the same shape as `/formulate`'s `composition`. All fields other
  than `fractions` are optional, so existing callers are unaffected.
- Log request IDs (if the calling client or service provides them) for easier debugging.

## 7) Upgrade playbook

- Before upgrading environments:
  - compare old vs new `openapi.json`
  - run integration tests against the target deployment
- Avoid hardcoding enum-like values outside `/supported` when possible.
- Track README release notes for contract-impacting changes.
