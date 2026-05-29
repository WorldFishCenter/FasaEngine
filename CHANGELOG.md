# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-29

### Added
- Cloud Run deployment workflow for automated deployments.
- API token protection via `Authorization: Bearer` or `X-API-Key`.
- Readiness probe endpoint (`/ready`) and structured request/solver logging.
- Integration, architecture, and versioning documentation under `docs/`.
- `FormulateResponse` now echoes `max_fishmeal_cost_share` and `max_binder_inclusion` so clients can confirm which advisory caps (if any) were applied.
- Optional `batch_size_kg` input on `/formulate`. When supplied, each `recipe[]` line carries `quantity_kg` (gram-precision) and the response also reports `batch_size_kg`, `premix_quantity_kg`, and `total_cost`. Lets the miller-facing UX show absolute kg per ingredient and total batch cost without client-side multiplication.

### Changed
- Expanded API schema modeling and OpenAPI metadata coverage.
- Updated README with Cloud Run setup and API testing instructions.
- `max_fishmeal_cost_share` and `max_binder_inclusion` are now optional and default to `None` (no cap applied). Toxicity (TX01–TX16) and ASNS nutrient limits remain the only fixed constraints; callers that want a sustainability or pellet-quality ceiling can still pass either value explicitly. Backward-compatible: requests that previously supplied 0.20 / 0.25 continue to produce the same LP.
- Updated `docs/testing-guide.md` to reflect the relaxed caps, the new `batch_size_kg` flow, and the removal of per-ingredient inclusion limits.

### Removed
- Hardcoded blood meal `max_inclusion = 0.05` from `ingredient_pool_africa.csv`. The 5 % palatability ceiling was a commercial-industry rule-of-thumb without a supporting FASA feeding trial; consistent with the policy that only toxin and ASNS limits are fixed, the LP is now free to include blood meal up to whatever the nutrient and price constraints allow.

## [0.1.0] - 2026-05-07

### Added
- Initial MVP release of FASA feed formulation engine.
- FastAPI endpoints: `/health`, `/supported`, `/formulate`, `/validate-recipe`.
- LP optimization core (PuLP + HiGHS), PAFF benchmark checks, and smoke tests.

