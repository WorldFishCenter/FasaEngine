# FASA Feed Formulation Engine — MVP

Optimization core for the FASA digital application: low-cost, digestibility-aware feed formulation for Nile Tilapia and African Catfish using locally available African ingredients.

## Who this repo is for

- **Feed formulators / mills**: explore least-cost formulations under explicit nutritional + toxin constraints.
- **Developers**: run the FastAPI service and integrate it into a product.
- **Researchers**: extend constraint sets, data crosswalks, and future interaction/chance-constraint hooks.

## Status

This repository is an **MVP**. The public surface is stable enough for demos and integration experiments, but expect breaking changes as the data model and constraint set evolve.

## What's in this MVP

- **Linear programming engine** (PuLP + HiGHS) that solves a digestibility-aware least-cost feed formulation against the active ASNS constraints for a chosen species/stage/production-system tuple.
- **Premix-aware constraint masking**: vitamins and trace minerals are assumed satisfied by a fixed-rate vitamin/mineral premix (default 0.5%), keeping the LP focused on macros, amino acids, digestible energy, Ca, P, fatty acids, and toxin ceilings.
- **Hard ceilings on toxins / anti-nutrients**: aflatoxin B, gossypol, phytic acid, glucosinolates, tannins, etc. are enforced as Maximum constraints regardless of premix or override settings.
- **Safety caps**: collective binder cap (default ≤ 25 % mass) and fish-meal cost-share cap (default ≤ 20 % of recipe cost), aligning with the FASA goal of reducing reliance on imported marine ingredients.
- **Hard-fail with IIS reporting**: when the constraint set is infeasible at the supplied prices/pool, a deletion-filter algorithm extracts a minimal Irreducible Inconsistent Subset of constraints and returns it to the caller so the miller knows exactly why the recipe could not be built.
- **PAFF benchmark gate**: independent recomputation of PAFF reference recipes' nutrient composition acts as the correctness test for the data-loading and crosswalk pipeline.
- **FastAPI surface** with `/formulate`, `/supported`, `/validate-recipe`, and `/health` endpoints.
- **Architectural hooks** (no-ops in MVP) for the post-MVP non-additive interaction layer (Hua & Bureau 2012) and chance-constrained variability handling.

## Layout

```
fasa_engine/
├── data/
│   ├── ASNS_nutrition_specification_database.csv
│   ├── FICD_feed_ingredient_composition_database.csv
│   ├── PAFF_practical_aquaculture_feed_formulation_database_Feed_Formulations.csv
│   └── PAFF_practical_aquaculture_feed_formulation_database_Calculated_Composition.csv
├── fasa_core/
│   ├── config/
│   │   ├── crosswalk.json              ASNS spec code -> FICD parameter (+ unit factor)
│   │   ├── premix_mask.json            which spec codes the premix covers
│   │   ├── ingredient_pool_africa.csv  curated, plausibly-African ingredient shortlist
│   │   └── defaults.py                 numeric defaults (premix rate, caps, etc.)
│   ├── data_loader.py                  ASNS / FICD / PAFF loaders (cached)
│   ├── crosswalk.py                    spec → FICD parameter resolver
│   ├── ingredient_pool.py              pool filter
│   ├── constraint_builder.py           solver-agnostic LP constraint emission
│   ├── optimizer.py                    PuLP+HiGHS solve, IIS via deletion filter
│   ├── validator.py                    independent composition recompute + PAFF gate
│   └── models.py                       pydantic request/response schemas
├── fasa_api/
│   └── main.py                         FastAPI app
├── tests/test_smoke.py                 pytest smoke + PAFF reproduction
├── examples/tilapia_starter_demo.py    runnable end-to-end demo
└── requirements.txt
```

## Data files (required)

This engine needs four CSVs (committed under `data/` by default):

- `data/ASNS_nutrition_specification_database.csv` (nutrition constraints by species/stage/system)
- `data/FICD_feed_ingredient_composition_database.csv` (ingredient nutrient composition; long format, pivoted at runtime)
- `data/PAFF_practical_aquaculture_feed_formulation_database_Feed_Formulations.csv` (reference formulations)
- `data/PAFF_practical_aquaculture_feed_formulation_database_Calculated_Composition.csv` (reference calculated composition)

Filenames are currently **expected to match exactly** (see `fasa_core/config/defaults.py`).

## Quickstart

```bash
cd fasa_engine

# Recommended: create an isolated environment
python3 -m venv .venv
source .venv/bin/activate

# Option A (simple): install dependencies only
pip install -r requirements.txt

# Option B (recommended for dev): install the project in editable mode
pip install -e ".[dev]"

# Data files are expected in ./data by default.

# 1. Run the smoke tests (loads ASNS/FICD/PAFF, verifies crosswalk, runs an LP)
pytest -q

# 2. Run the end-to-end demo
python -m examples.tilapia_starter_demo

# 3. Spin up the API
uvicorn fasa_api.main:app --reload --port 8000
# then open docs at http://127.0.0.1:8000/docs
```

## API quick usage

The API is self-documented at `GET /docs`. Endpoints:

- `GET /health` liveness probe
- `GET /supported` discover valid `species`, `production_system`, and `stage` strings
- `POST /formulate` run the optimization
- `POST /validate-recipe` recompute composition for an explicit recipe

Notes:
- Browsers issue **GET** requests; `GET /formulate` will return **405 Method Not Allowed** because `/formulate` is **POST-only**.
- `stage` must match the ASNS `stage_weight` label exactly. Use `/supported` to discover valid values.

### POST /formulate (example body)

```json
{
  "species": "Nile Tilapia",
  "stage": "< 5g (Starter)",
  "production_system": "General-LowCost",
  "processing_method": "pelleted",
  "premix_enabled": true,
  "premix_rate": 0.005,
  "max_fishmeal_cost_share": 0.20,
  "max_binder_inclusion": 0.25,
  "prices": {
    "30355": 0.30,
    "31237": 0.55,
    "10018": 1.50,
    "62134": 0.80,
    "62138": 0.10
  }
}
```

### Reading the response (high level)

- **`recipe`**: ingredient inclusions (percent of final feed) + cost breakdown.
- **`composition`**: per-spec achieved vs target, including toxin ceilings.
- **`status`**:
  - `optimal`: solution exists and is least-cost under constraints
  - `infeasible`: no solution; see `infeasibility.iis_codes` / `iis_explanations` for why

## Modeling notes

1. **Decision variables** `x_i ∈ [0, max_inclusion_i]` = mass fraction of each priced+available ingredient.
2. **Objective** `min Σ price_i × x_i` (USD/kg or local currency, supplied at runtime).
3. **Mass balance** `Σ x_i = 1 − premix_rate` so the premix takes a fixed slice.
4. **Nutritional constraints** generated 1:1 from active ASNS rows for the given (species, system, stage):
   - Minimum / Maximum specs become inequalities,
   - Ratio specs (e.g., DP/DE) are linearized.
   - The `dig_*_fish_percent` and `dig_p_*_percent` FICD columns are bound directly to the corresponding ASNS digestible-nutrient codes — *digestibility is baked into the constraint LHS, not bolted on after*.
5. **Energy column selection** is data-driven: ASNS itself carries the species-appropriate energy code (Tilapia ⇒ ED02 DE-Omni, African Catfish ⇒ ED01 DE-Carni). The crosswalk then maps that code to the pelleted vs. extruded FICD variant per the request's `processing_method`.
6. **Hard toxin ceilings** are NEVER masked, even via override (TX01–TX16 always emit Maximum constraints).
7. **Soft warnings** are appended (not enforced) when any single ingredient exceeds 40 % inclusion.
8. **On infeasibility**, a deletion-filter IIS is returned so the user can see which constraints conflict.

## Post-MVP roadmap (hooks already in place)

- `optimizer._apply_interaction_corrections` — non-additive ingredient interaction terms (e.g., phytate × Ca → reduced P digestibility), per Hua & Bureau (2012).
- `optimizer._apply_anti_nutrient_digestibility_penalties` — anti-nutrient concentrations downgrade digestible-protein/AA coefficients.
- `optimizer._solve_chance_constrained` — stochastic LP using ingredient nutrient CV.
- Country-specific availability tags (Kenya / Nigeria / Zambia) replacing the single Africa pool.

## References

- Bureau, D.P. (2014). *Optimization of the Formulation of Aquaculture Feeds…*
- Hua, K. & Bureau, D.P. (2012). *Exploring the possibility of quantifying the effects of plant protein ingredients in fish feeds…*
- Avadí, A. *et al.* (2022). *How to enhance the sustainability and inclusiveness of smallholder aquaculture production systems in Zambia?*
