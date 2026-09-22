# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-09-22

### Added
- Minimum/maximum inclusion layer. Nutrient composition alone is not enough to formulate on: the optimizer could return diets that met every nutrient target yet could not be extruded or produce growth, such as bran-heavy rations. Two new tables carry the limits a formulator would otherwise apply by hand — `fasa_core/config/nutrient_limits.csv` (bounds on dietary nutrient levels, by ASNS spec code) and `fasa_core/config/ingredient_limits.csv` (bounds on how much of a single ingredient may go in, by FICD code).
- Optional `nutrient_limits` and `ingredient_limits` inputs on `/formulate`, for callers that already know the bounds they want. An entry overrides the table for the code it names.
- `recipe[]` lines now carry the limit applied to each ingredient (`min_inclusion_percent`, `max_inclusion_percent`, `limit_source`), and `composition[]` lines carry `source`, saying whether a target came from the species requirement or from the limit layer.
- `infeasibility.bound_conflicts` explains, in plain language, ingredient limits that cannot add up to a full batch — the one failure the existing conflict report cannot describe.
- `/validate-recipe` now checks a recipe's inclusion rates, not only its composition. Optional `species`, `stage`, `production_system`, `processing_method`, `premix_enabled` and the two limit inputs scope the check; `in_limits`, `inclusion_checks`, `nutrient_checks`, `total_inclusion_percent` and `warnings` report the result. Existing payloads are unaffected.
- `/ready` also loads the two limit tables, so a malformed table is caught at deploy time rather than on the first request.

### Changed
- An ingredient given a `0` maximum is left out of the recipe even when it is priced, and the response names it in a warning — so "we should not recommend this at all" is distinguishable from "too expensive today".
- Where a limit and the species requirement bound the same nutrient, the tighter of the two applies. A limit can never relax an ASNS requirement.

### Fixed
- A recipe returned by `/formulate` no longer reads as out of spec when sent straight back to `/validate-recipe`. Both endpoints now score achieved-versus-target through the same code, with a tolerance that allows for the rounding in the published inclusion percentages.

### Notes
- Both tables ship with documented headers and **no data rows** — the values are still being compiled, so formulations are unchanged until the columns are filled. Activating them needs no code change.
- Ingredient limits are written and sent as a mass fraction of total feed (`0.15` = 15%) but reported back as a percentage (`max_inclusion_percent: 15.0`). Nutrient limits use the ASNS unit of their spec code and are not rescaled.

## [0.3.0] - 2026-07-21

### Added
- Country-aware ingredient pool. `fasa_core/config/ingredient_pool_africa.csv` gains a `countries` column (comma-separated ISO-2 codes: `KE`/`NG`/`ZM`) tagging where each ingredient is locally available.
- Optional `country` input on `/formulate` (ISO-2, case-insensitive). When supplied, each `recipe[]` line carries `locally_available` (`true`/`false`); it is `null` when no `country` is requested. `FormulateResponse` echoes the requested `country`.
- `/supported` now returns a `countries` list so clients can discover valid values.
- `scripts/build_ingredient_pool.py` regenerates the pool CSV from the source country list (`scripts/data/countries_pool.csv`) and FICD.

### Changed
- Expanded the ingredient pool from the original 39-item shortlist to 330 ingredients (the FICD-backed subset of the country list, plus the retained import variants). Descriptions come from FICD; `class` and the `is_fishmeal`/`is_binder` flags are auto-derived from the description (fishmeal only for "Fish meal ..."; binder for starch/flour/cassava). Existing formulations are unaffected — the LP still only uses priced ingredients, every previously priced code is retained, and the derived flags reproduce the prior curated flags exactly.

### Notes
- The optimizer is **never** restricted to local ingredients; `country` is an advisory highlight only, consistent with millers buying imported soy, premix, etc.
- 141 Zambia-only codes from the source list have no composition rows in FICD and are excluded from the pool until FICD gains their data.

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

