# FASA Feed Formulation Engine — Testing Guide

This guide covers the model rationale, data structure, API usage, and interpretation of results.

---

## Contents

1. [What the Tool Does](#1-what-the-tool-does)
2. [Nutritional Framework — the ASNS Database](#2-nutritional-framework--the-asns-database)
  - 2.1 [Production Systems](#21-production-systems)
  - 2.2 [Supported Species and Stages](#22-supported-species-and-stages)
  - 2.3 [Constraint Categories](#23-constraint-categories)
3. [Ingredient Composition Database — FICD](#3-ingredient-composition-database--ficd)
4. [Ingredient Pool](#4-ingredient-pool)
5. [How the Optimizer Works](#5-how-the-optimizer-works)
  - 5.1 [Premix Masking](#51-premix-masking)
  - 5.2 [Min/Max Inclusion Limits](#52-minmax-inclusion-limits)
6. [Endpoint Reference](#6-endpoint-reference)
  - 6.1 `[GET /supported](#61-get-supported)`
  - 6.2 `[POST /formulate` — Request Schema](#62-post-formulate--request-schema)
  - 6.3 `[POST /formulate` — Response Schema and Interpretation](#63-post-formulate--response-schema-and-interpretation)
  - 6.4 `[POST /validate-recipe` — Request and Response](#64-post-validate-recipe--request-and-response)
7. [Possible Outcomes](#7-possible-outcomes)
  - 7.1 [Optimal](#71-optimal)
  - 7.2 [Infeasible](#72-infeasible)
  - 7.3 [Error](#73-error)
8. [Warnings](#8-warnings)
9. [Known Limitations](#9-known-limitations)
  - 9.1 [Country Availability Is Advisory Only](#91-country-availability-is-advisory-only)
  - 9.2 [No Ingredient Price Book](#92-no-ingredient-price-book)
  - 9.3 [Inclusion Limit Tables Are Not Yet Populated](#93-inclusion-limit-tables-are-not-yet-populated)
  - 9.4 [Premix Nutrient Contribution Not Modelled](#94-premix-nutrient-contribution-not-modelled)
  - 9.5 [Anti-Nutritional Interactions Not Modelled](#95-anti-nutritional-interactions-not-modelled)
  - 9.6 [No Non-Additive Energy Interactions](#96-no-non-additive-energy-interactions)

---

## 1. What the Tool Does

FASA solves a **least-cost feed formulation problem**: given a set of locally available ingredients with known prices and nutritional composition, it finds the ingredient combination that meets a set of nutritional requirements at the lowest possible cost per kilogram of feed.

The approach is equivalent to the classical linear programming (LP) diet formulation method used in animal nutrition. The objective function minimises the weighted sum of ingredient prices. The constraints encode nutritional minima, maxima, and structural rules (see §3).

The tool does **not** optimise for palatability, pellet quality, or any criterion beyond cost and nutritional compliance. Those criteria enter as bounds rather than objectives, through the min/max inclusion layer (§5.2).

[↑ Contents](#contents)

---

## 2. Nutritional Framework — the ASNS Database

All nutritional requirements are sourced from the **Aquaculture Species Nutrition Specifications (ASNS)** database, a structured table of minimum and maximum nutrient targets per species, production system, and growth stage.

Each constraint row has:


| Column              | Meaning                                                                     |
| ------------------- | --------------------------------------------------------------------------- |
| `species`           | Target species (e.g. Nile Tilapia)                                          |
| `production_system` | Husbandry intensity profile (see §2.1)                                      |
| `stage_weight`      | Growth stage label, used verbatim in API requests                           |
| `code`              | Specification code (e.g. `PA03`, `AA05`, `TX01`)                            |
| `specification`     | Full name of the nutrient or constraint                                     |
| `unit`              | Measurement unit (%, kcal, mg, g, ppb, etc.)                                |
| `restriction_type`  | `Minimum`, `Maximum`, or `Ratio`                                            |
| `value`             | Numeric threshold; **blank rows are inactive** and are not passed to the LP |


Constraints with a blank `value` exist as placeholders but impose no requirement in the current dataset.

### 2.1 Production Systems

Two production system profiles are implemented:


| System            | Meaning                                                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `General`         | Standard nutritional specifications; applicable to most commercial and semi-commercial systems                                             |
| `General-LowCost` | Relaxed specifications (lower CP, digestible protein, and energy targets) intended for low-input, subsistence-oriented production contexts |


> **Important:** `General-LowCost` is only defined in the ASNS database for **Nile Tilapia**. Requesting `African Catfish` with `General-LowCost` will yield no active nutritional constraints and is not a valid combination in the current dataset.

### 2.2 Supported Species and Stages

The engine currently supports two species. Valid `stage` strings are listed below exactly as they must appear in API requests (use `GET /supported` to retrieve them programmatically).

**Nile Tilapia** — `General` and `General-LowCost`:

`< 5g (Starter)` · `5-10g (Pre-grower)` · `10-30g (Pre-grower)` · `30-70g (Grower)` · `70-100g (Grower)` · `100-200g (Grower)` · `200-400g (Grower)` · `400-800g (Grower)` · `>800g (Grower)` · `>1000g (Brood)`

**African Catfish** — `General` only:

`< 5g (Starter)` · `5-50g (Pre-grower)` · `50-200g (Grower)` · `200-500g (Grower)` · `500-800g (Grower)` · `800-1000g (Grower)` · `1000-1200g (Grower)` · `>1200g (Grower)` · `>1000g (Brood)`

### 2.3 Constraint Categories


| Code prefix  | Category                                                                                    | Typical unit              |
| ------------ | ------------------------------------------------------------------------------------------- | ------------------------- |
| `PA`         | Proximate composition (moisture, CP, crude lipids, crude fibre, ash, NFE, NDF, ADF, starch) | %                         |
| `ED`         | Digestible energy by species model (fish carnivore, fish omnivore, carp, shrimp)            | kcal/kg                   |
| `ADPXF`      | Apparent digestibility — protein and energy (fish reference model)                          | %, kcal/kg                |
| `ADPXF09/10` | Digestible protein-to-energy ratio (DP/DE)                                                  | g/MJ or g/kcal            |
| `AA`         | Total amino acids (10 EAAs + TSAA, Phe+Tyr, Taurine)                                        | %                         |
| `ADAAF`      | Digestible amino acids (fish reference model)                                               | %                         |
| `FA`         | Fatty acids (n-3, n-6, EPA, DHA, EPA+DHA, phospholipids, cholesterol)                       | % or mg/kg                |
| `M01–M07`    | Macro-minerals (Ca, P, Na, Cl, K, Mg) and digestible P                                      | %                         |
| `M08–M13`    | Trace minerals (Cu, Fe, Mn, Se, Zn, I)                                                      | mg/kg                     |
| `V01–V15`    | Vitamins                                                                                    | mg/kg, µg/kg, IU/kg       |
| `TX01–TX16`  | Toxins and anti-nutritional factors                                                         | ppb, mg/kg, g/kg, mmol/kg |


Energy constraints (`ED01–ED04`) are species-specific: Nile Tilapia uses the omnivore model (`ED02`); African Catfish uses the carnivore model (`ED01`). Only the constraint with a non-blank value for a given species/stage combination is active.

[↑ Contents](#contents)

---

## 3. Ingredient Composition Database — FICD

The **Feed Ingredient Composition Database (FICD)** provides the nutritional composition of each ingredient. It is stored in long format (one row per ingredient × parameter combination) and is pivoted at runtime to a matrix of ~277 composition parameters per ingredient.

Each ingredient is identified by a numeric `code` and a `description`. The composition parameters include all proximate, energy, amino acid, fatty acid, mineral, vitamin, toxin, and digestibility values required to build the LP coefficient matrix.

The crosswalk between ASNS constraint codes and FICD parameter names is maintained internally. When a constraint cannot be mapped to a FICD parameter (e.g. no FICD column exists for that nutrient), the constraint is **silently dropped** and a warning is appended to the response.

Energy columns are selected by processing method: for `pelleted` feeds, the engine reads `de_*_pelleted_kcal_kg` columns; for `extruded` feeds, it reads `de_*_extruded_kcal_kg` columns.

[↑ Contents](#contents)

---

## 4. Ingredient Pool

The optimizer draws from a **country-tagged ingredient pool** of 330 ingredients considered plausibly available in sub-Saharan Africa. Only ingredients from this pool that also appear in the `prices` dictionary of the request are admitted into the LP.

The pool is generated by `scripts/build_ingredient_pool.py` from a per-country usable-ingredient list intersected with FICD (the composition database), plus a small set of retained import variants. It is stored in `fasa_core/config/ingredient_pool_africa.csv` with these columns:


| Column                 | Meaning                                                                                                                                                     |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `code` / `description` | FICD ingredient code and name                                                                                                                               |
| `class`                | Informational grouping label, auto-derived from the description; **not used by the LP**                                                                     |
| `is_fishmeal`          | `1` for fish-meal products; participates in the opt-in `max_fishmeal_cost_share` cap                                                                        |
| `is_binder`            | `1` for starch/flour/cassava binders; participates in the opt-in `max_binder_inclusion` cap                                                                 |
| `max_inclusion`        | Optional per-ingredient ceiling; blank for all current entries. Superseded by `ingredient_limits.csv` where that file names the ingredient (§5.2)            |
| `countries`            | Comma-separated ISO-2 codes (`KE`, `NG`, `ZM`) where the ingredient is locally available; blank = not locally available in any tracked country (imports)    |


The `countries` column is **advisory only**: it drives the per-line `locally_available` flag in the response and is never used to restrict the LP (see §6.2 `country`, and §9.1).

Representative rows (the full list lives in the CSV):


| Code  | Description                                | Class          | is_fishmeal | is_binder | countries            |
| ----- | ------------------------------------------ | -------------- | ----------- | --------- | -------------------- |
| 30355 | Corn, grain                                | cereal         | 0           | 0         | KE,NG,ZM             |
| 30307 | Cassava, tuber, meal                       | binder         | 0           | 1         | KE,NG,ZM             |
| 10018 | Fish meal, sardine, 66% CP                 | animal_protein | 1           | 0         | KE,NG,ZM             |
| 62134 | Dicalcium phosphate anhydrous, DCP         | mineral        | 0           | 0         | KE,NG                |
| 27108 | Black soldier fly, Full-fat                | insect_meal    | 0           | 0         | ZM                   |
| 10073 | Fish meal, mixed fish, Mauritania, 66% CP  | animal_protein | 1           | 0         | *(blank — import)*   |


Currently 12 ingredients are flagged `is_fishmeal` and 7 `is_binder`. These flags are auto-derived from the description (fish-meal = descriptions beginning "Fish meal …"; binder = starch/flour/cassava products) and feed only the opt-in advisory caps in §5.

No ingredient in the pool CSV currently carries a hard per-ingredient inclusion limit. Per-ingredient bounds are now the job of the curated inclusion-limit layer (§5.2), which is hand-maintained rather than generated and so survives a pool rebuild; the pool's own `max_inclusion` column remains as a fallback for ingredients that layer does not name. Until the limit tables are populated, all ingredients are bounded only by nutritional constraints, toxin ceilings, and (optionally) the advisory binder/fish-meal caps.

> **Coverage note:** 141 codes from the country list (all Zambia-only, a contiguous block) have no composition rows in FICD and are therefore excluded from the pool; they cannot be formulated until FICD gains their data.

[↑ Contents](#contents)

---

## 5. How the Optimizer Works

The LP is formulated as follows.

**Decision variables:** `x_i` = mass fraction of ingredient `i` in the final feed (dimensionless, bounded `[min_inclusion_i, max_inclusion_i]` where the inclusion-limit layer defines them, otherwise `[0, 1]` — see §5.2).

**Objective:** minimise `Σ price_i × x_i`

**Constraints:**

1. **Mass balance:** `Σ x_i = 1 − premix_rate`
  If `premix_enabled = true`, a fixed mass fraction (default 0.5%) is reserved for a vitamin/mineral premix. The premix mass is excluded from the LP decision variables; its nutritional contribution is **not modelled** (see §10.4).
2. **Nutritional constraints:** For each active ASNS row with a mapped FICD parameter:
  `Σ composition_ij × x_i ≥ target_j` (Minimum)  
   `Σ composition_ij × x_i ≤ target_j` (Maximum)
3. **DP/DE ratio:** Linearised to a single minimum inequality: `Σ (dCP_i − rhs × dDE_i) × x_i ≥ 0`.
4. **Binder cap (opt-in):** `Σ_{i ∈ binders} x_i ≤ max_binder_inclusion`. Not applied by default; only emitted when the caller supplies a value in `[0, 1)`.
5. **Fish-meal cost-share cap (opt-in):** `Σ_{FM} price_i × x_i ≤ max_fishmeal_cost_share × Σ price_i × x_i` (linearised). Not applied by default; only emitted when the caller supplies a value in `[0, 1)`.
6. **Nutrient inclusion limits:** additional `Minimum`/`Maximum` rows contributed by the inclusion-limit layer (see §5.2). They are indistinguishable from ASNS rows in the LP.

The solver used is HiGHS (via PuLP), with a fallback to CBC. The time limit is 30 seconds per request. The solution is exact (continuous LP) and globally optimal within the model's assumptions.

### 5.1 Premix Masking

When `premix_enabled = true`, ASNS constraints for vitamins (V01–V15) and trace minerals (M08–M13) are **excluded from the LP** on the assumption that these micronutrients are supplied by the premix. Toxin constraints (TX01–TX16) are **always enforced**, regardless of premix settings.

For brood stock stages, Vitamin C (V09) is re-activated even when premix masking is enabled (it is removed from the default mask for the `Brood` stage).

Custom masking can be specified per request via `custom_premix_mask_codes` (see §7.2).

### 5.2 Min/Max Inclusion Limits

Nutrient composition alone is not enough to formulate on. ASNS states what the fish *requires*; it does not state what a mill can actually mix, pellet or extrude. An LP given only composition data will load up on whatever is cheapest per unit of nutrient — commonly bran by-products — and return a diet that satisfies every nutrient target while being unextrudable and unable to grow fish. Commercial formulation closes that gap with a second layer of bounds, applied by hand: a ceiling on dietary fibre, and a ceiling (or floor) on how much of any single ingredient may go in.

That layer is now part of the engine. It has two halves:


| Layer                | Keyed by             | Effect on the LP                                                    | Config file                              |
| -------------------- | -------------------- | ------------------------------------------------------------------- | ---------------------------------------- |
| Nutrient limits      | ASNS spec code       | Extra `Minimum`/`Maximum` constraint rows on dietary nutrient levels | `fasa_core/config/nutrient_limits.csv`   |
| Ingredient limits    | FICD ingredient code | The decision variable's box: `min_inclusion ≤ x_i ≤ max_inclusion`   | `fasa_core/config/ingredient_limits.csv` |


Both files ship with a documented header and **no data rows yet** — the values are still being compiled. While they are empty the engine behaves exactly as it did before: ingredients are bounded only by the ASNS constraints, the toxin ceilings and the opt-in advisory caps. Filling the columns activates the layer with no code change. In the meantime, either layer can be supplied per request via `nutrient_limits` / `ingredient_limits` (see §6.2).

**Units — read this before sending limits.** The two halves use different units, and the ingredient half flips between request and response:

| Where | Quantity | Unit |
| --- | --- | --- |
| `nutrient_limits` request, and `nutrient_limits.csv` `min`/`max` | dietary nutrient level | the **ASNS unit for that spec code** — `%` for proximates and amino acids, `kcal/kg` for energy, `mg/kg` for trace minerals, `ppb` for mycotoxins (see §2.3) |
| `ingredient_limits` request, and `ingredient_limits.csv` `min_inclusion`/`max_inclusion` | single-ingredient inclusion | **mass fraction of total feed, in [0, 1]** — `0.15` means 15% |
| `min_inclusion_percent` / `max_inclusion_percent` in the response | the same bound, echoed back | **percent of feed, 0-100** — the 0.15 above comes back as `15.0` |

So an ingredient bound is **sent as a fraction and reported as a percentage**. Values outside [0, 1] on the request are rejected with a 422, which catches `15` sent for 15%, but `0.15` displayed as "0.15%" is a silent client-side error — convert on the way in and out. Nutrient bounds are not rescaled in either direction: they go in and come back in the ASNS unit.

**Scoping.** Both files share four filter columns — `species`, `production_system`, `stage_weight`, `processing_method` — where a blank cell means "applies to all". `stage_weight` matches as a substring of the ASNS stage label, so `Starter` covers `< 5g (Starter)` (the same convention as `premix_mask.json`). `processing_method` exists because the same ingredient often tolerates a different rate in a pellet than in an extrudate. When several rows match one request, the most specific row wins (most non-blank filters); ties resolve toward the tighter bound, and each direction resolves independently.

**Nutrient limits and ASNS.** Resolution is per (spec code, direction):

- The direction is already in ASNS for the requested stage → the **tighter** value binds (max of minimums, min of maximums), and the composition line reports `source: "asns+limits"`. A commercial 8% fibre ceiling therefore never relaxes a 7% ASNS requirement.
- The direction is absent from ASNS → a new constraint is emitted (`source: "limits"`). This is how ceilings ASNS does not carry at all — ash, NDF/ADF — get added.
- A bound this layer contributes is **never masked by the premix**: an explicit operator bound always binds. A plain ASNS row for the same code stays masked, so capping zinc does not also resurrect the zinc minimum the premix supplies.
- Ratio specs (DP/DE) are not supported by this layer; a limit on one is skipped with a warning.

Because nutrient limits become ordinary constraint rows, they inherit the whole existing pipeline: unit conversion, the `composition` report, and the deletion-filter IIS (an infeasibility a nutrient limit caused is named in `iis_codes`, tagged `[limits]` or `[request]` in the explanation).

**Ingredient limits.** These become the decision variable's bounds, so they cost the solver nothing:

- A `max_inclusion` of 0 removes the ingredient from consideration entirely, even when it is priced. The response then carries a `[limit]` warning naming it, so a "we should not recommend this at all" exclusion is distinguishable from a "too expensive today" one.
- A `min_inclusion` only applies to ingredients the caller actually priced — the engine cannot force in an ingredient it has no price for.
- A row here supersedes the pool CSV's generated `max_inclusion` column (§4) for that ingredient.
- Each `recipe` line echoes the box that was applied (`min_inclusion_percent`, `max_inclusion_percent`, `limit_source`), so a client can explain why an ingredient stopped where it did.

Because these are variable bounds rather than constraint rows, the IIS cannot see them. Limits that cannot add up to the required feed mass — ceilings summing below `1 − premix_rate`, or floors summing above it — are therefore detected before the solve and reported in `infeasibility.bound_conflicts` instead (see §7.2).

Both halves are also checked by `POST /validate-recipe` (§6.4), which scores a recipe the caller supplies rather than one the LP produced.

[↑ Contents](#contents)

---

## 6. Endpoint Reference

### 6.1 `GET /supported`

Returns the complete list of supported species, production systems, countries, and valid stage labels.

**Use this endpoint first** to confirm the exact strings required for `species`, `production_system`, `stage`, and `country` in formulation requests. Stage labels must match exactly (including spacing, capitalisation, and punctuation).

**Response structure:**

```json
{
  "species": ["Nile Tilapia", "African Catfish"],
  "production_systems": ["General-LowCost", "General"],
  "countries": ["KE", "NG", "ZM"],
  "stages_by_species_and_system": {
    "Nile Tilapia": {
      "General": ["< 5g (Starter)", "5-10g (Pre-grower)", ...],
      "General-LowCost": ["< 5g (Starter)", ...]
    },
    "African Catfish": {
      "General": ["< 5g (Starter)", ...],
      "General-LowCost": []
    }
  }
}
```

---

### 6.2 `POST /formulate` — Request Schema

All field definitions and defaults:


| Field                      | Type            | Required | Default             | Definition                                                                                                                                                                                                             |
| -------------------------- | --------------- | -------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `species`                  | string          | **Yes**  | —                   | Target species. Allowed: `"Nile Tilapia"` or `"African Catfish"`                                                                                                                                                       |
| `stage`                    | string          | **Yes**  | —                   | Growth stage label. Must match exactly one of the labels returned by `GET /supported` for the chosen species and production system                                                                                     |
| `production_system`        | string          | No       | `"General-LowCost"` | Nutritional specification profile. `"General"` applies standard targets; `"General-LowCost"` applies relaxed targets (Nile Tilapia only)                                                                               |
| `country`                  | string or null  | No       | `null`              | Optional ISO-2 country code (`"KE"`, `"NG"`, `"ZM"`; case-insensitive). When supplied, each recipe line is flagged `locally_available` per the pool's `countries` tags. Advisory highlight only — **never** restricts the LP |
| `prices`                   | object          | **Yes**  | —                   | Dictionary mapping ingredient `code` (as a string) to price per kg (float). Only codes present in the configured pool are used; unlisted codes are ignored. At least one ingredient must be provided                   |
| `processing_method`        | string          | No       | `"pelleted"`        | Feed manufacturing method. Selects the corresponding digestible energy column from FICD. Allowed: `"pelleted"` or `"extruded"`                                                                                         |
| `premix_enabled`           | boolean         | No       | `true`              | If `true`, vitamin and trace mineral constraints are excluded from the LP (assumed covered by premix). Toxin constraints are always active                                                                             |
| `premix_rate`              | float           | No       | `0.005`             | Mass fraction of the feed reserved for the premix (0–0.10 exclusive). Default 0.005 = 0.5%. This mass is subtracted from the ingredient budget before the LP runs                                                      |
| `batch_size_kg`            | float or null   | No       | `null`              | Total batch size in kg (0 exclusive, max 1 000 000). When supplied, the response includes per-ingredient `quantity_kg`, `premix_quantity_kg`, and `total_cost`. Omit to receive percent-only output                    |
| `max_fishmeal_cost_share`  | float or null   | No       | `null`              | Optional cap on fish-meal cost share (is_fishmeal = true). Range [0, 1]. Omit (or send `null`) to apply no cap — cost alone then drives fish-meal inclusion                                                            |
| `max_binder_inclusion`     | float or null   | No       | `null`              | Optional cap on collective binder mass fraction (is_binder = true). Range [0, 1]. Omit (or send `null`) to apply no cap                                                                                                |
| `custom_premix_mask_codes` | list of strings | No       | `null`              | If provided, **replaces** the default premix mask entirely. List of ASNS specification codes (e.g. `["V01","V02","M08"]`) to exclude from the LP. Toxin codes (TX*) in this list are still enforced. Maximum 200 codes |
| `nutrient_limits`          | object or null  | No       | `null`              | Per-request override of the nutrient inclusion-limit layer (§5.2): ASNS spec code → `{"min": …, "max": …}` in that code's ASNS unit, e.g. `{"PA05": {"max": 8}}`. An entry **replaces** the configured limit for that code. Either key may be omitted. Maximum 300 codes |
| `ingredient_limits`        | object or null  | No       | `null`              | Per-request override of the ingredient inclusion-limit layer (§5.2): FICD ingredient code → `{"min": …, "max": …}` as a mass fraction of total feed in [0, 1], e.g. `{"31605": {"max": 0.15}}`. An entry **replaces** the configured limit for that ingredient. Maximum 300 codes |


**Example minimum request body:**

```json
{
  "species": "Nile Tilapia",
  "stage": "30-70g (Grower)",
  "production_system": "General",
  "prices": {
    "31237": 0.45,
    "30355": 0.22,
    "10018": 1.80,
    "52117": 1.10,
    "62134": 0.30,
    "62135": 0.05,
    "61109": 2.50,
    "61111": 4.00
  }
}
```

Prices are in the currency of your choice; the returned `cost_per_kg` will be expressed in the same currency. The model is currency-agnostic.

**Practical note on ingredient selection:** The LP can only use ingredients for which both a price and a pool entry exist. Providing more ingredients increases the feasible space and generally reduces cost. If the ingredient set is too restricted, the solver may return `infeasible`.

**Example request with inclusion limits:** hold dietary crude fibre below 8% of the diet, cap wheat bran and rice bran at 15% each, and exclude cottonseed meal outright.

```json
{
  "species": "Nile Tilapia",
  "stage": "< 5g (Starter)",
  "production_system": "General-LowCost",
  "prices": { "...": 0.0 },
  "nutrient_limits": {
    "PA05": { "max": 8.0 }
  },
  "ingredient_limits": {
    "31605": { "max": 0.15 },
    "30937": { "max": 0.15 },
    "30404": { "max": 0.0 }
  }
}
```

Both objects are optional and independent. Values sent here override the configured CSV layer for the codes they name and leave every other code resolving from the files as usual.

---

### 6.3 `POST /formulate` — Response Schema and Interpretation


| Field               | Type            | Meaning                                                                                                                 |
| ------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `status`            | string          | Outcome: `"optimal"`, `"infeasible"`, or `"error"`                                                                      |
| `species`           | string          | Echo of input                                                                                                           |
| `stage`             | string          | Echo of input                                                                                                           |
| `production_system` | string          | Echo of input                                                                                                           |
| `processing_method` | string          | Echo of input                                                                                                           |
| `country`           | string or null  | Echo of input (null when omitted)                                                                                       |
| `premix_enabled`    | boolean         | Echo of input                                                                                                           |
| `premix_rate`       | float           | Echo of input                                                                                                           |
| `max_fishmeal_cost_share` | float or null | Echo of input (null when no cap was applied)                                                                          |
| `max_binder_inclusion`    | float or null | Echo of input (null when no cap was applied)                                                                          |
| `batch_size_kg`     | float or null   | Echo of input (null when omitted)                                                                                       |
| `premix_quantity_kg`| float or null   | `batch_size_kg × premix_rate`, rounded to 3 decimals. Populated only when `batch_size_kg` is supplied and `premix_enabled = true` |
| `total_cost`        | float or null   | `cost_per_kg × batch_size_kg`, rounded to 2 decimals. Populated only when `batch_size_kg` is supplied and status is `"optimal"`   |
| `cost_per_kg`       | float or null   | Minimised feed cost per kg (priced ingredients only; excludes the premix fraction). Null when status is not `"optimal"` |
| `recipe`            | list            | Ingredient lines (see below). Empty when not optimal                                                                    |
| `composition`       | list            | Nutritional constraint lines (see below). Empty when not optimal                                                        |
| `warnings`          | list of strings | Non-fatal issues (see §7.4)                                                                                             |
| `infeasibility`     | object or null  | Present when status is `"infeasible"` (see §7.5)                                                                        |


**Recipe lines** (`recipe` list):


| Field               | Meaning                                                                                                                                                                            |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `code`              | FICD ingredient code                                                                                                                                                               |
| `description`       | Ingredient name                                                                                                                                                                    |
| `inclusion_percent` | Mass fraction in the feed, expressed as a percentage. When `premix_enabled = true`, the sum of all `inclusion_percent` values equals `(1 − premix_rate) × 100` and the remaining share (default 0.5%) is the premix; when `premix_enabled = false`, the sum equals 100 |
| `cost_per_kg`       | Price as supplied in the request                                                                                                                                                   |
| `cost_contribution` | This ingredient's contribution to the total feed cost (fraction × price). Summing all `cost_contribution` values gives `cost_per_kg`                                               |
| `quantity_kg`       | Absolute mass of this ingredient in kg, rounded to 3 decimals. Populated only when `batch_size_kg` is supplied on the request; otherwise `null`                                    |
| `locally_available` | Boolean or null. When a `country` was supplied on the request, `true`/`false` indicates whether this ingredient is tagged for that country; `null` when no `country` was requested |
| `min_inclusion_percent` | The inclusion floor applied to this ingredient, as a **percentage** of feed (0-100) — note that `ingredient_limits` is *sent* as a fraction in [0, 1]; `null` when unbounded below (§5.2) |
| `max_inclusion_percent` | The inclusion ceiling applied to this ingredient, as a **percentage** of feed (0-100); `null` when unbounded above (§5.2)                                                      |
| `limit_source`      | Where that box came from: `"limits"` (config CSV), `"request"` (per-call override), or `"pool"` (the pool CSV's `max_inclusion`). `null` when no limit applied to this ingredient |


**Composition lines** (`composition` list):


| Field              | Meaning                                                                                                                  |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `code`             | ASNS specification code                                                                                                  |
| `spec_label`       | Human-readable name of the constraint                                                                                    |
| `restriction_type` | `"Minimum"`, `"Maximum"`, or `"Minimum"` (ratios are linearised to a minimum constraint)                                 |
| `target`           | Constraint threshold actually enforced — the ASNS value, or the tighter value if the inclusion-limit layer overrode it   |
| `achieved`         | Value realised by the optimised recipe                                                                                   |
| `unit`             | Measurement unit                                                                                                         |
| `in_spec`          | Boolean: `true` if the achieved value satisfies the constraint. Should be `true` for all rows in an `"optimal"` solution |
| `source`           | Where `target` came from: `"asns"`, `"asns+limits"` / `"asns+request"` (an ASNS target tightened by the inclusion-limit layer), or `"limits"` / `"request"` (a bound ASNS does not state for this stage). See §5.2 |


The `composition` list includes only constraints that were active in the LP (i.e. those with a non-blank ASNS value or an inclusion limit, a mapped FICD parameter, and not masked by the premix). Masked constraints (vitamins, trace minerals) do not appear unless the inclusion-limit layer gives them an explicit bound.

---

### 6.4 `POST /validate-recipe` — Request and Response

This endpoint scores a **user-defined recipe** without running the optimiser: it recomputes the recipe's nutritional composition from FICD and checks its inclusion rates against the min/max inclusion layer (§5.2). Use it to check a hand-edited recipe, an externally sourced formulation, or a recipe `/formulate` returned that the miller has since adjusted.

**Request:**


| Field               | Type            | Required | Default      | Meaning                                                                                                                                                    |
| ------------------- | --------------- | -------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fractions`         | object          | **Yes**  | —            | Dictionary mapping ingredient code (string) to mass fraction (float in [0, 1])                                                                             |
| `parameters`        | list of strings | No       | `null`       | FICD parameter column names to include in `composition` (e.g. `["crude_protein_percent"]`). If omitted, all parameters are returned                        |
| `species`           | string or null  | No       | `null`       | Optional. Scopes the inclusion limits, and (with `stage` and `production_system`) enables the nutrient checks                                               |
| `stage`             | string or null  | No       | `null`       | Optional ASNS `stage_weight` label                                                                                                                         |
| `production_system` | string or null  | No       | `null`       | Optional. Required together with `species` and `stage` for the nutrient checks                                                                              |
| `processing_method` | string          | No       | `"pelleted"` | Scopes the inclusion limits and selects the digestible-energy column for the nutrient checks                                                                |
| `premix_enabled`    | boolean         | No       | `true`       | Mirrors `/formulate`: when `true`, the vitamin and trace-mineral specs the premix covers are excluded from the nutrient checks (the premix's own contribution is not modelled) |
| `nutrient_limits`   | object or null  | No       | `null`       | Same shape, units and meaning as on `/formulate` (§6.2; units in §5.2 — ASNS unit per spec code); overrides the configured limits for the codes it names   |
| `ingredient_limits` | object or null  | No       | `null`       | Same shape, units and meaning as on `/formulate` (§6.2; units in §5.2 — mass fraction in [0, 1], reported back as a percentage); overrides the configured limits |


All fields other than `fractions` are optional, so the original payload shape (`fractions` + `parameters`) keeps working unchanged.

**Response:**


| Field                     | Type            | Meaning                                                                                                                              |
| ------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `composition`             | object          | `Σ composition_ij × fraction_i` per requested FICD parameter, rounded to 6 decimals                                                   |
| `total_inclusion_percent` | float           | Sum of the supplied fractions, as a percentage of feed mass                                                                          |
| `in_limits`               | boolean         | `true` when every check that ran passed — both the inclusion checks and (when they ran) the nutrient checks                            |
| `inclusion_checks`        | list            | One line per supplied ingredient: `code`, `description`, `inclusion_percent`, the applied box (`min_inclusion_percent`, `max_inclusion_percent`, `limit_source`) and `in_limits` |
| `nutrient_checks`         | list            | Composition lines in the same shape as `/formulate`'s `composition` (§6.3), including `target`, `achieved`, `in_spec` and `source`. Empty unless `species`, `stage` and `production_system` were all supplied |
| `warnings`                | list of strings | Non-fatal notes — see below                                                                                                          |


```json
{
  "composition": { "crude_fibre_percent": 4.817768 },
  "total_inclusion_percent": 99.5,
  "in_limits": false,
  "inclusion_checks": [
    {
      "code": "31605",
      "description": "Wheat bran",
      "inclusion_percent": 40.0,
      "min_inclusion_percent": null,
      "max_inclusion_percent": 15.0,
      "limit_source": "request",
      "in_limits": false
    }
  ],
  "nutrient_checks": [
    {
      "code": "PA05",
      "spec_label": "Crude Fibre",
      "restriction_type": "Maximum",
      "target": 7.0,
      "achieved": 4.817768,
      "unit": "%",
      "in_spec": true,
      "source": "asns"
    }
  ],
  "warnings": []
}
```

**What runs when.** The inclusion checks always run — limit rows with blank scope columns apply to every request, so a blanket ceiling binds even with no `species`/`stage` given. The nutrient checks need the full `(species, stage, production_system)` triple to resolve an ASNS row set; supply part of it and they are skipped with a `[skip]` warning.

**Warnings specific to this endpoint:**


| Warning   | Meaning                                                                                                                                                                       |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[mass]`  | The fractions sum to something other than 99–100% of feed mass, so they do not describe a complete diet                                                                        |
| `[skip]`  | Either the scope was incomplete for the nutrient checks, or some codes are absent from the ingredient pool. Pool-absent codes still contribute to `composition` (that path reads FICD directly) but can hold no inclusion limit and contribute nothing to the nutrient checks — the same restriction `/formulate` has |


**Consistency with `/formulate`.** The nutrient checks reuse the optimiser's own constraint set and achieved-vs-target arithmetic, so a recipe `/formulate` returned scores as fully in spec when fed straight back. The `in_spec` tolerance is scaled to each constraint's coefficients and budgets for the 4-decimal precision of the `inclusion_percent` values this API publishes; without that, any exactly-binding constraint (and the DP/DE ratio, whose linearised target is 0) would read as violated on a round trip.

[↑ Contents](#contents)

---

## 7. Possible Outcomes

### 7.1 Optimal

The LP found a feasible solution and the solver converged to a global minimum. All nutritional constraints are satisfied by the returned recipe. The `cost_per_kg` field contains the minimised feed cost.

A soft warning is generated (but the solution remains optimal) if any single ingredient exceeds 40% of total feed mass. High single-ingredient inclusion may indicate an undersupplied ingredient set or a very restrictive constraint profile.

### 7.2 Infeasible

No combination of the supplied ingredients can simultaneously satisfy all active nutritional constraints within the structural limits (mass balance, toxin ceilings, ingredient inclusion limits, and — when the caller opted in — the binder or fish-meal cost-share caps).

The `infeasibility` object contains:


| Field              | Meaning                                                                                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `iis_codes`        | List of ASNS specification codes in the approximate irreducible infeasible subset (IIS) — the minimal set of conflicting constraints identified by the engine |
| `iis_explanations` | Human-readable description of each conflicting constraint, tagged with its source (`[asns]`, `[limits]`, `[request]`)                                          |
| `bound_conflicts`  | Ingredient inclusion limits that cannot add up to the required feed mass. Populated instead of `iis_codes` — see below                                         |
| `suggestion`       | A general diagnostic suggestion                                                                                                                               |


**Common causes of infeasibility:**

- The ingredient set is too small or nutritionally inadequate to meet one or more active constraints simultaneously (e.g. insufficient amino acid sources to satisfy a protein minimum, especially when an opt-in fish-meal cost-share cap is also being applied).
- A constraint requires a nutrient for which no supplied ingredient contains that nutrient in the FICD database (composition value is zero or absent for all included ingredients).
- Conflicting constraints: e.g. a high protein minimum combined with a low crude fibre maximum may require ingredients that simultaneously violate another constraint.
- An inclusion limit (§5.2) is too tight for the priced set: a nutrient ceiling below what any affordable combination can reach, or per-ingredient caps that leave no room for a nutrient minimum.

**Bound conflicts.** Ingredient inclusion limits are decision-variable bounds rather than constraint rows, so the IIS cannot attribute a failure to them. When the ceilings on the priced ingredients sum to less than `1 − premix_rate`, or the floors sum to more, no constraint subset can ever be feasible — so the engine detects this before solving, returns `iis_codes: []`, and states the arithmetic in `bound_conflicts`:

```json
{
  "iis_codes": [],
  "iis_explanations": [],
  "bound_conflicts": [
    "Maximum inclusion limits on the priced ingredients sum to 24.00%, below the 99.50% of feed mass that must be filled. Price more ingredients or raise a maximum."
  ],
  "suggestion": "Adjust the ingredient inclusion limits so their range spans the required feed mass, or price additional ingredients."
}
```

**Diagnostic approach:** Check `bound_conflicts` first — when it is non-empty the inclusion limits alone are the cause and no IIS was computed. Examine the `iis_codes` returned. If, for example, the IIS names amino-acid codes (e.g. `AA05` Lysine) and you opted into `max_fishmeal_cost_share`, consider adding a synthetic lysine source (code `61109`) or removing/relaxing the fish-meal cost cap. If no opt-in cap is in play, the conflict lies entirely between the ingredient set and the ASNS targets.

### 7.3 Error

An internal processing failure. HTTP 400 errors indicate an invalid request (unsupported species, production system, or malformed body). HTTP 500 errors indicate a server-side failure.

[↑ Contents](#contents)

---

## 8. Warnings

Warnings are non-fatal messages appended to any response (including optimal solutions). They do not invalidate the result but indicate model limitations or data gaps.


| Warning type            | Meaning                                                                                                              |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Unmapped specification  | An ASNS constraint has no corresponding FICD parameter column; the constraint was dropped and not enforced by the LP |
| Single ingredient > 40% | One ingredient exceeds 40% of total mass in the optimal solution; may warrant inspection                             |
| `[skip]` nutrient limit | A nutrient inclusion limit (§5.2) names a code with no FICD mapping, or a ratio spec; the limit was ignored          |
| `[limit]` excluded      | A priced ingredient was removed from consideration by a 0% maximum inclusion limit (§5.2)                            |


[↑ Contents](#contents)

---

## 9. Known Limitations

The following limitations reflect the current MVP implementation and should be considered when interpreting results.

### 9.1 Country Availability Is Advisory Only

Ingredients are tagged with the countries where they are locally available (ISO-2: Kenya `KE`, Nigeria `NG`, Zambia `ZM`), and an optional `country` on `/formulate` flags each recipe line as `locally_available`. This is **advisory only** — by design, the optimizer always draws on the full pool and is **never** restricted to local ingredients, because millers routinely buy imported soy, premix, etc., and a hard country filter would make the tool unusable where local data is sparse. Country tags therefore highlight local sourcing; they do not change the recipe or its cost.

Two related gaps remain: only three countries are currently tracked, and 141 Zambia-specific codes from the source list lack composition data in FICD and are excluded from the pool until that data is added (see §4).

### 9.2 No Ingredient Price Book

The engine has no internal price reference. Prices must be supplied by the user in every request. There is no validation of price plausibility or currency consistency. Results are directly sensitive to the price values provided.

### 9.3 Inclusion Limit Tables Are Not Yet Populated

The min/max inclusion layer described in §5.2 is implemented and wired into the LP, but both of its tables — `fasa_core/config/nutrient_limits.csv` and `fasa_core/config/ingredient_limits.csv` — ship without data rows. The values are still being compiled.

Until they are filled, ingredient inclusions are bounded only by the ASNS nutritional constraints, the TX01–TX16 toxin ceilings, and — when the caller opts in — the collective binder or fish-meal cost-share caps. This is the practical limitation behind diets that look cheap and pass every nutrient check yet would not be recommended in practice: a 40% bran inclusion, for instance, is within every ASNS target the engine can currently see, but such a mash will not extrude and will not support growth.

Callers that already know the bounds they want can supply them per request through `nutrient_limits` and `ingredient_limits` (§6.2) without waiting for the tables. Once the tables are populated the same bounds apply automatically to every request in scope.

### 9.4 Premix Nutrient Contribution Not Modelled

When `premix_enabled = true`, the LP reserves `premix_rate` of the feed mass for a premix and skips vitamin and trace mineral constraints. However, the nutritional content of the premix itself is **not added** to the composition output. The `composition` response reflects only the contribution of the optimised ingredient fraction. Achieved values for vitamins and trace minerals are not reported.

### 9.5 Anti-Nutritional Interactions Not Modelled

The LP treats ingredient composition as strictly additive. Digestibility penalties from anti-nutritional factors (e.g. phytate reducing phosphorus bioavailability, tannins reducing protein digestibility, gossypol interacting with lysine) are not modelled. Toxin constraints (TX01–TX16) are enforced as hard ceilings on total dietary concentration, but interaction effects between anti-nutritional factors are not captured.

### 9.6 No Non-Additive Energy Interactions

Digestible energy values in FICD are ingredient-specific and additive in the LP. Interactions between energy substrates (e.g. protein-sparing by lipid) are not accounted for beyond what is inherent in the digestible energy coefficients.

[↑ Contents](#contents)