# FASA Feed Formulation Engine — MVP

Optimization core for the FASA digital application: low-cost, digestibility-aware feed formulation for Nile Tilapia and African Catfish using locally available African ingredients.

## Who this repo is for

- **Feed formulators / mills**: explore least-cost formulations under explicit nutritional + toxin constraints.
- **Developers**: run the FastAPI service and integrate it into a product.
- **Researchers**: extend constraint sets, data crosswalks, and future interaction/chance-constraint hooks.

## Status

This repository is an **MVP**. The public surface is stable enough for demos and integration experiments, but expect breaking changes as the data model and constraint set evolve.

## Architecture at a glance

The project has two main parts:

- `fasa_api`: the API interface
- `fasa_core`: the formulation and validation logic

Reference data is currently stored in `data/` CSV files.

For a simple high-level overview, see [`docs/architecture.md`](docs/architecture.md).
For integration details, see [`docs/integration.md`](docs/integration.md).

## API stability policy (pragmatic)

To keep this project easy to plug into web/mobile/desktop clients without overengineering:

- Current public contract is the OpenAPI schema exposed by the running API (`/docs` and `/openapi.json`).
- Backward-compatible changes (new optional fields, new endpoints) may happen at any time.
- Breaking changes are avoided by default; when needed, they are called out in `CHANGELOG.md` and integration docs.
- Target routing convention is `/v1/*` for long-term stability. Current unversioned routes remain supported for now to avoid forcing immediate client rewrites.
- Integrations should pin to a deployed environment and test against the current `openapi.json` before upgrading.

For versioning and release process, see [`docs/versioning.md`](docs/versioning.md).
Project changes are tracked in [`CHANGELOG.md`](CHANGELOG.md).

## What's in this MVP

- **Linear programming engine** (PuLP + HiGHS) that solves a digestibility-aware least-cost feed formulation against the active ASNS constraints for a chosen species/stage/production-system tuple.
- **Premix always included**: every feed carries a vitamin/mineral premix at 1, 1.5 or 2% of the feed (`premix_rate`, default 2%), priced by the caller (`premix_price`) and counted in the feed cost. Its composition, supplied by the FASA team (`fasa_core/config/premix_composition.json`), is counted at that rate, so its 13 vitamins and 6 trace minerals are checked against ASNS like any other nutrient, premix included. Choline and inositol, which it does not contain, are not checked (the FASA team dropped these rules). Premix products are not in the ingredient pool.
- **FASA ingredients**: 43 FASA lab samples (codes `FASA-KE-01` … `FASA-ZM-11`, listed in `scripts/data/fasa_ingredients.csv`) sit in the pool next to the 299 IAFFD ingredients. Their composition is kept in its own FICD-format file, `data/FASA_feed_ingredient_composition.csv`, so a FICD import never overwrites it. Lab values are used as-fed; the gaps the FASA team chose to fill (phosphorus, toxins, anti-nutrients, trace minerals, vitamins) come from a linked IAFFD ingredient, and digestible energy is the lab gross energy times that ingredient's digestibility.
- **FASA rule decisions** (decisions workbook, 5 November 2026; values in `fasa_core/config/defaults.py`): digestible protein, DP/DE, digestible amino acids, digestible phosphorus, phospholipids, cholesterol, Na/Cl/K/Mg and the moisture minimum are dropped for every feed; catfish crude protein follows the FASA requirements table where it differs; crude protein and lipid may range 2 / 1 points either side of the requirement (minimum lowered, maximum added); a saponin maximum (`TX15F`) applies the soyasaponin limit to the FASA lab saponin. Digestible energy stays for every feed.
- **Calls made without the FASA team** (5 November 2026; to change if they disagree): a lab value written "<0.1" counts as zero; both Ochonga lines (`FASA-KE-02`, `FASA-KE-03`, one lab sample) stay, each with its own maximum; General-LowCost stays; catfish crude protein changes only at the two stages the FASA table names (50-200 g and 800-1000 g); a FASA ingredient's `countries` is its lab sample's country and is advisory only; the premix sheet is read as written (calcium pantothenate counted as pantothenic acid, vitamin K3 as vitamin K); the team's "±2 / ±1" for protein and lipid is read as a range either side of the requirement (catfish 50-200g: 34-38%), not only a maximum above it; WorldFish's ash maximum, given for the General system, applies to General-LowCost too; where WorldFish's ingredient maximums differ from Serge's tab 1 (sunflower cake Zambia, Chikanda, cassava dried Kenya, brewery grains Kenya, local brewery waste Nigeria), Serge's are used; the group limits count the IAFFD fish and shrimp meals and brans (wheat pollard included) as well as the FASA ones; the FASA team's limits for FASA lines removed for lack of a lab sample (blood meal, poultry meal, corn gluten meal, maize, broken rice, rapeseed meal, corn bran, wheat bran, wheat flour, palm oil, cassava tuber meal, methionine) apply to the IAFFD ingredients of the same name.
- **Hard ceilings on toxins / anti-nutrients**: aflatoxin B, gossypol, phytic acid, glucosinolates, tannins, etc. are enforced as Maximum constraints and are never masked by the premix.
- **Min/max inclusion layer**: a second layer of bounds on top of composition data, because nutrient tables alone let the LP build diets that pass every target yet cannot be extruded or grown on. `fasa_core/config/nutrient_limits.csv` adds Minimum/Maximum bounds on dietary nutrient levels (the tighter of ASNS and the limit binds); `fasa_core/config/ingredient_limits.csv` bounds how much of any single ingredient may go in; `fasa_core/config/group_limits.csv` bounds a group of ingredients together (all brans at most 15%, fishmeals at least 5/3% for tilapia). The ingredient table carries maximums for 146 pool ingredients (103 IAFFD, 43 FASA), per species or, where the FASA weight groups differ, per stage; the nutrient table holds an ash maximum (tilapia 10%; catfish 10% under 5 g, 8% from 500 g, from WorldFish's feed constraints), and further rows take effect with no code change. Either can be supplied per request via `nutrient_limits` / `ingredient_limits`.
- **Hard-fail with IIS reporting**: when the constraint set is infeasible at the supplied prices/pool, a deletion-filter algorithm extracts a minimal Irreducible Inconsistent Subset of constraints and returns it to the caller so the miller knows exactly why the recipe could not be built.
- **PAFF benchmark gate**: independent recomputation of PAFF reference recipes' nutrient composition acts as the correctness test for the data-loading and crosswalk pipeline.
- **FastAPI surface** with `/formulate`, `/supported`, `/validate-recipe`, and `/health` endpoints. `/validate-recipe` scores a caller-supplied recipe against the same inclusion limits and constraint set the optimizer uses, so a hand-edited formulation can be checked without re-running the LP.
- **Architectural hooks** (no-ops in MVP) for the post-MVP non-additive interaction layer (Hua & Bureau 2012) and chance-constrained variability handling.

## Layout

```
fasa_engine/
├── data/
│   ├── ASNS_nutrition_specification_database.csv
│   ├── FICD_feed_ingredient_composition_database.csv
│   ├── FASA_feed_ingredient_composition.csv   FASA ingredients, FICD format (generated)
│   ├── PAFF_practical_aquaculture_feed_formulation_database_Feed_Formulations.csv
│   └── PAFF_practical_aquaculture_feed_formulation_database_Calculated_Composition.csv
├── fasa_core/
│   ├── config/
│   │   ├── crosswalk.json              ASNS spec code -> FICD parameter (+ unit factor)
│   │   ├── premix_composition.json     premix content per kg, counted at premix_rate
│   │   ├── premix_mask.json            specs skipped without a check (choline, inositol)
│   │   ├── ingredient_pool_africa.csv  country-tagged ingredient pool (KE/NG/ZM)
│   │   ├── nutrient_limits.csv         min/max bounds on dietary nutrient levels
│   │   ├── ingredient_limits.csv       min/max bounds on single-ingredient inclusion
│   │   ├── group_limits.csv            min/max bounds on a group of ingredients together
│   │   └── defaults.py                 numeric defaults (premix rates, FASA rule decisions, solver)
│   ├── data_loader.py                  ASNS / FICD / PAFF loaders (cached)
│   ├── crosswalk.py                    spec → FICD parameter resolver
│   ├── ingredient_pool.py              pool filter
│   ├── inclusion_limits.py             min/max inclusion layer (nutrient + ingredient)
│   ├── constraint_builder.py           solver-agnostic LP constraint emission
│   ├── optimizer.py                    PuLP+HiGHS solve, IIS via deletion filter
│   ├── validator.py                    recipe scoring (composition + inclusion limits) + PAFF gate
│   └── models.py                       pydantic request/response schemas
├── fasa_api/
│   └── main.py                         FastAPI app
├── scripts/
│   ├── build_ingredient_pool.py        regenerates the country-tagged pool CSV
│   ├── import_datasets.py              converts raw ASNS/FICD exports into data/
│   ├── build_fasa_ingredients.py       builds the FASA composition file from the lab results
│   └── data/
│       ├── countries_pool.csv          source country list (builder input)
│       └── fasa_ingredients.csv        the 43 FASA ingredients: code, lab sample, linked IAFFD code
├── tests/test_smoke.py                 pytest smoke + PAFF reproduction
├── examples/tilapia_starter_demo.py    runnable end-to-end demo
└── requirements.txt
```

## Data files (required)

This engine needs five CSVs (committed under `data/` by default):

- `data/ASNS_nutrition_specification_database.csv` (nutrition constraints by species/stage/system)
- `data/FICD_feed_ingredient_composition_database.csv` (ingredient nutrient composition; long format, pivoted at runtime)
- `data/FASA_feed_ingredient_composition.csv` (the FASA ingredients, same format; read together with FICD)
- `data/PAFF_practical_aquaculture_feed_formulation_database_Feed_Formulations.csv` (reference formulations)
- `data/PAFF_practical_aquaculture_feed_formulation_database_Calculated_Composition.csv` (reference calculated composition)

Filenames are currently **expected to match exactly** (see `fasa_core/config/defaults.py`).

Current versions: ASNS and FICD v11.1 (30 July 2026), PAFF v6.0 (3 December 2025).

Known data issues in FICD v11.1 (iodine carried over from the previous release; one new pool
ingredient without DE values): see [docs/testing-guide.md §3–4](docs/testing-guide.md#3-ingredient-composition-database--ficd).

To update ASNS and FICD from new FASA exports, convert them into this layout, then rebuild the
FASA ingredients (their gaps are filled from FICD) and the ingredient pool (it reads both):

```bash
python scripts/import_datasets.py "ASNS <date>.csv" "FICD <date>.csv"
uv run --no-project --with pandas --with openpyxl \
    python scripts/build_fasa_ingredients.py "<path to>/Ingredient Databasev2.xlsx"
python scripts/build_ingredient_pool.py
```

Run the last two steps also when a new FASA lab file arrives. `build_fasa_ingredients.py` needs
`openpyxl`, which the engine itself does not; it stops if a lab sample is missing or empty, or
if a rule the engine checks would have no FASA value source, and reports how many samples have
a starch value.

## Quickstart

```bash
cd fasa_engine

# Create an isolated environment
python3 -m venv .venv
source .venv/bin/activate

# Option A (simple): install dependencies only
pip install -r requirements.txt

# Option B (development): install the project in editable mode
pip install -e ".[dev]"

# Data files are expected in ./data by default.

# 1. Run the smoke tests (loads ASNS/FICD/PAFF, verifies crosswalk, runs an LP)
pytest -q

# 2. Run the end-to-end demo
python -m examples.tilapia_starter_demo

# 3. Spin up the API
export FASA_REQUIRE_AUTH=false
uvicorn fasa_api.main:app --reload --port 8000
# then open docs at http://127.0.0.1:8000/docs
```

## API quick usage

The API is self-documented at `GET /docs`. Endpoints:

- `GET /health` liveness probe
- `GET /ready` readiness probe (validates data files, FICD preload, and the inclusion-limit tables)
- `GET /supported` discover valid `species`, `production_system`, and `stage` strings
- `POST /formulate` run the optimization
- `POST /validate-recipe` score an explicit recipe: recompute composition and check its inclusion rates against the limit layer

Notes:
- Browsers issue **GET** requests; `GET /formulate` will return **405 Method Not Allowed** because `/formulate` is **POST-only**.
- `stage` must match the ASNS `stage_weight` label exactly. Use `/supported` to discover valid values.
- Unless `FASA_REQUIRE_AUTH=false`, all endpoints except `/health` require either:
  - `Authorization: Bearer <token>`, or
  - `X-API-Key: <token>`

For external teams integrating this API into other systems, see [`docs/integration.md`](docs/integration.md).

### POST /formulate (example body)

```json
{
  "species": "Nile Tilapia",
  "stage": "< 5g (Starter)",
  "production_system": "General-LowCost",
  "processing_method": "pelleted",
  "country": "ZM",
  "premix_rate": 0.02,
  "premix_price": 2.50,
  "batch_size_kg": 100,
  "prices": {
    "30355": 0.30,
    "31237": 0.55,
    "10018": 1.50,
    "62134": 0.80,
    "62138": 0.10
  },
  "nutrient_limits": { "PA05": { "max": 8.0 } },
  "ingredient_limits": { "31605": { "max": 0.15 } }
}
```

`nutrient_limits` (ASNS spec code → bound in that code's ASNS unit, e.g. `%` for fibre,
`kcal/kg` for energy) and `ingredient_limits` (FICD code → mass **fraction** of total feed
in `[0, 1]`, so `0.15` = 15%) are optional per-request overrides of the inclusion-limit
layer. They override the configured CSVs for the codes they name. Where ASNS already
states the same bound, the tighter value binds. Note that the response echoes an
ingredient bound as a **percentage** (`max_inclusion_percent: 15.0`), not a fraction.

`premix_rate` must be `0.01`, `0.015` or `0.02` (1, 1.5 or 2% of the feed; default `0.02`). `premix_price` is required: the premix price per kg, in the same currency as `prices`.

`country` is optional (ISO-2: `KE`, `NG`, `ZM`; discover valid values via `/supported`). When supplied, each recipe line is flagged `locally_available`. It is an advisory highlight only — the optimizer always draws on the full pool (millers routinely buy imported soy, fish meal, etc.), so a country is **never** a hard filter.

Example call with auth:

```bash
curl -X POST "http://127.0.0.1:8000/formulate" \
  -H "Authorization: Bearer ${FASA_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d @payload.json
```

### Reading the response (high level)

- **`recipe`**: ingredient inclusions (percent of final feed) + cost breakdown. If `batch_size_kg` was supplied on the request, each line also carries `quantity_kg`. If `country` was supplied, each line carries `locally_available` (`true`/`false`); it is `null` when no `country` was requested. Each line also echoes the inclusion box that was applied (`min_inclusion_percent`, `max_inclusion_percent`, `limit_source`).
- **`cost_per_kg`**: cost of the whole feed, premix included: the sum of the recipe lines' `cost_contribution` plus `premix_rate × premix_price`. Both premix values are echoed.
- **`batch_size_kg` / `premix_quantity_kg` / `total_cost`**: echoed only when `batch_size_kg` was supplied; otherwise `null`.
- **`composition`**: per-spec achieved vs target, including toxin ceilings. `source` says whether the target came from ASNS alone or from the inclusion-limit layer.
- **`status`**:
  - `optimal`: solution exists and is least-cost under constraints
  - `infeasible`: no solution; see `infeasibility.iis_codes` / `iis_explanations` for why, or `infeasibility.bound_conflicts` when the ingredient inclusion limits alone cannot add up to the feed mass

### Error envelope

Business/auth errors are returned with:

```json
{
  "detail": {
    "code": "unauthorized",
    "message": "Invalid or missing API token.",
    "details": null
  }
}
```

## Cloud Run deployment (test environment)

### Runtime contract

- Container command binds to `0.0.0.0:$PORT`.
- Required data files are bundled under `data/`.
- `/health` is liveness and public.
- `/ready` verifies data artifacts, FICD preload, and that the inclusion-limit tables parse.
- Auth is controlled by:
  - `FASA_REQUIRE_AUTH` (default: `true`)
  - `FASA_API_TOKEN` (required when auth enabled)

### Build locally

```bash
docker build -t fasa-engine-api:local .
docker run --rm -p 8080:8080 \
  -e FASA_REQUIRE_AUTH=true \
  -e FASA_API_TOKEN=local-dev-token \
  fasa-engine-api:local
```

### Manual gcloud deploy (fallback)

```bash
gcloud run deploy fasa-engine-api-test \
  --project "$GCP_PROJECT_ID" \
  --region "$GCP_REGION" \
  --source . \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --concurrency 2 \
  --timeout 120 \
  --max-instances 10 \
  --set-env-vars FASA_REQUIRE_AUTH=true \
  --set-secrets FASA_API_TOKEN=fasa-api-token:latest
```

### CI deployment

GitHub Actions workflow [`.github/workflows/deploy-cloud-run.yml`](.github/workflows/deploy-cloud-run.yml) deploys on `main` push or manual dispatch.

Configure:
- **Repository variables**:
  - `GCP_REGION`
  - `GCP_ARTIFACT_REGISTRY_REPO`
  - `CLOUD_RUN_SERVICE`
- **Repository secrets**:
  - `GCP_PROJECT_ID`
  - `GCP_WORKLOAD_IDENTITY_PROVIDER`
  - `GCP_DEPLOY_SERVICE_ACCOUNT`
  - `FASA_API_TOKEN_SECRET_NAME`

### API testing checklist

- Provide Cloud Run base URL and API token through a secure channel.
- Test `/supported`, `/formulate`, and `/validate-recipe` using `Authorization: Bearer <token>`.
- For production-like tests, keep request payloads below the current guard rails (`prices` and list fields max ~300 items).

## Modeling notes

1. **Decision variables** `x_i ∈ [min_inclusion_i, max_inclusion_i]` = mass fraction of each priced+available ingredient; the box comes from the inclusion-limit layer and defaults to `[0, 1]`.
2. **Objective** `min Σ price_i × x_i` (USD/kg or local currency, supplied at runtime). The premix cost `premix_rate × premix_price` is a constant, added to the reported cost.
3. **Mass balance** `Σ x_i = 1 − premix_rate` so the premix takes a fixed slice.
4. **Nutritional constraints** generated 1:1 from active ASNS rows for the given (species, system, stage), after the FASA team's changes (rules dropped, catfish protein, protein/lipid maximums, saponin):
   - Minimum / Maximum specs become inequalities,
   - Ratio specs (e.g., DP/DE) are linearized; none is active since DP/DE was dropped.
   - Digestible energy (`ED01`/`ED02`, `ADPXF04`) is the one digestible rule left: the FICD DE columns are bound directly to it — *digestibility is baked into the constraint LHS, not bolted on after*. The digestible protein, amino acid and phosphorus rules are dropped.
5. **Energy column selection** is data-driven: ASNS itself carries the species-appropriate energy code (Tilapia ⇒ ED02 DE-Omni, African Catfish ⇒ ED01 DE-Carni). The crosswalk then maps that code to the pelleted vs. extruded FICD variant per the request's `processing_method`.
6. **Hard toxin ceilings** are NEVER masked (TX01–TX16 always emit Maximum constraints).
7. **Nutrient inclusion limits** join the ASNS row set before emission, so they inherit unit conversion, the composition report, and IIS reporting. Where ASNS states the same direction the tighter value binds; a code the layer bounds is never masked by the premix.
8. **Group limits** add one row per bound on the sum of a group's priced members (e.g. all brans ≤ 15%), reported in `composition` and the IIS under the group name.
9. **Soft warnings** are appended (not enforced) when any single ingredient exceeds 40 % inclusion.
10. **On infeasibility**, a deletion-filter IIS is returned so the user can see which constraints conflict. Ingredient bounds that cannot sum to the feed mass are caught before the solve and reported separately as `bound_conflicts`.

## Post-MVP roadmap (hooks already in place)

- `optimizer._apply_interaction_corrections` — non-additive ingredient interaction terms (e.g., phytate × Ca → reduced P digestibility), per Hua & Bureau (2012).
- `optimizer._apply_anti_nutrient_digestibility_penalties` — anti-nutrient concentrations downgrade digestible-protein/AA coefficients.
- Chance-constrained solve — stochastic LP using ingredient nutrient CV (planned; no hook in the code yet).

Country-specific availability tags (Kenya / Nigeria / Zambia) are now **implemented**: the pool carries per-ingredient `countries` tags and `/formulate` accepts an optional `country` that flags `locally_available` in the response (without restricting the LP).

## References

- Bureau, D.P. (2014). *Optimization of the Formulation of Aquaculture Feeds…*
- Hua, K. & Bureau, D.P. (2012). *Exploring the possibility of quantifying the effects of plant protein ingredients in fish feeds…*
- Avadí, A. *et al.* (2022). *How to enhance the sustainability and inclusiveness of smallholder aquaculture production systems in Zambia?*
