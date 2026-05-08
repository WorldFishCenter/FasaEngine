# FASA Feed Formulation Engine — Testing Guide for Scientists

This guide is intended for aquaculture scientists evaluating the FASA feed formulation API.
It covers the model rationale, data structure, API usage, and interpretation of results.

---

## 1. What the Tool Does

FASA solves a **least-cost feed formulation problem**: given a set of locally available ingredients with known prices and nutritional composition, it finds the ingredient combination that meets a set of nutritional requirements at the lowest possible cost per kilogram of feed.

The approach is equivalent to the classical linear programming (LP) diet formulation method used in animal nutrition. The objective function minimises the weighted sum of ingredient prices. The constraints encode nutritional minima, maxima, and structural rules (see §3).

The tool does **not** optimise for palatability, pellet quality, or any criterion beyond cost and nutritional compliance.

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

---

## 3. Ingredient Composition Database — FICD

The **Feed Ingredient Composition Database (FICD)** provides the nutritional composition of each ingredient. It is stored in long format (one row per ingredient × parameter combination) and is pivoted at runtime to a matrix of ~277 composition parameters per ingredient.

Each ingredient is identified by a numeric `code` and a `description`. The composition parameters include all proximate, energy, amino acid, fatty acid, mineral, vitamin, toxin, and digestibility values required to build the LP coefficient matrix.

The crosswalk between ASNS constraint codes and FICD parameter names is maintained internally. When a constraint cannot be mapped to a FICD parameter (e.g. no FICD column exists for that nutrient), the constraint is **silently dropped** and a warning is appended to the response.

Energy columns are selected by processing method: for `pelleted` feeds, the engine reads `de_*_pelleted_kcal_kg` columns; for `extruded` feeds, it reads `de_*_extruded_kcal_kg` columns.

---

## 4. Ingredient Pool

The optimizer draws only from a fixed **Africa pool** of 44 ingredients considered plausibly available in sub-Saharan Africa. Only ingredients from this pool that also appear in the `prices` dictionary of the request are admitted into the LP.

The current pool (with ingredient class):


| Code  | Description                                       | Class               | Notes                       |
| ----- | ------------------------------------------------- | ------------------- | --------------------------- |
| 30354 | Corn, ear, ground, dent yellow                    | cereal              |                             |
| 30355 | Corn, grain                                       | cereal              |                             |
| 30372 | Corn, feed, flour                                 | cereal              |                             |
| 30342 | Corn gluten meal, 43% CP                          | protein_concentrate |                             |
| 30343 | Corn gluten meal, 50% CP                          | protein_concentrate |                             |
| 31147 | Sorghum, grain                                    | cereal              |                             |
| 31148 | Sorghum, grain, low tannin                        | cereal              |                             |
| 30307 | Cassava, tuber, meal                              | binder              |                             |
| 30310 | Cassava, chips                                    | binder              |                             |
| 30316 | Cassava, flour                                    | binder              |                             |
| 31605 | Wheat bran                                        | cereal_byproduct    |                             |
| 31608 | Wheat middlings                                   | cereal_byproduct    |                             |
| 31621 | Wheat flour                                       | binder              |                             |
| 30937 | Rice bran                                         | cereal_byproduct    |                             |
| 30938 | Rice bran, defatted                               | cereal_byproduct    |                             |
| 31237 | Soybean meal, dehulled, 48% CP, solvent extracted | protein_meal        |                             |
| 31252 | Soybean meal, USA, dehulled, Standard, 48% CP     | protein_meal        |                             |
| 31407 | Sunflower meal, solvent extract, 41% CP           | protein_meal        |                             |
| 31405 | Sunflower meal, solvent extract, 30% CP           | protein_meal        |                             |
| 30404 | Cottonseed meal, 36% CP, expeller                 | protein_meal        | Gossypol cap (TX06) applies |
| 30410 | Cottonseed meal, degossypoled                     | protein_meal        |                             |
| 30557 | Groundnut meal, 45% CP                            | protein_meal        |                             |
| 30845 | Peanut meal, expeller, with hulls                 | protein_meal        |                             |
| 27002 | Black soldier fly larvae meal, defatted           | insect_meal         |                             |
| 27108 | Black soldier fly, Full-fat                       | insect_meal         |                             |
| 10018 | Fish meal, sardine, 66% CP                        | animal_protein      | is_fishmeal = true          |
| 10073 | Fish meal, mixed fish, Mauritania, 66% CP         | animal_protein      | is_fishmeal = true          |
| 10040 | Fish meal, tilapia processing by-product, 42%     | animal_protein      | is_fishmeal = true          |
| 20002 | Blood meal, ring dried                            | animal_protein      | max_inclusion = 5%          |
| 23002 | Poultry by-product meal, 60% CP                   | animal_protein      |                             |
| 40205 | Yeast, Brewers yeast, 25% CP                      | functional          |                             |
| 52113 | Palm oil                                          | lipid               |                             |
| 52117 | Soybean oil                                       | lipid               |                             |
| 52118 | Sunflower oil                                     | lipid               |                             |
| 62138 | Limestone (Calcium Carbonate)                     | mineral             |                             |
| 62134 | Dicalcium phosphate anhydrous                     | mineral             |                             |
| 62135 | Salt, NaCl                                        | mineral             |                             |
| 61109 | L-Lysine HCL                                      | synthetic_aa        |                             |
| 61111 | DL-Methionine                                     | synthetic_aa        |                             |


Blood meal is the only ingredient with a hard maximum inclusion limit in the pool (5% of feed mass). All other ingredients are bounded only by collective caps (binder, fish-meal cost-share) or nutritional constraints.

Ingredients with `is_fishmeal = true` (sardine, Mauritanian, and tilapia by-product fish meals) are subject to the fish-meal cost-share cap (see §5.2). Ingredients with `is_binder = true` (cassava products, wheat flour) are subject to the binder inclusion cap.

---

## 5. How the Optimizer Works

The LP is formulated as follows.

**Decision variables:** `x_i` = mass fraction of ingredient `i` in the final feed (dimensionless, bounded [0, 1] or [0, max_inclusion_i] where defined).

**Objective:** minimise `Σ price_i × x_i`

**Constraints:**

1. **Mass balance:** `Σ x_i = 1 − premix_rate`
  If `premix_enabled = true`, a fixed mass fraction (default 0.5%) is reserved for a vitamin/mineral premix. The premix mass is excluded from the LP decision variables; its nutritional contribution is **not modelled** (see §7).
2. **Nutritional constraints:** For each active ASNS row with a mapped FICD parameter:
  `Σ composition_ij × x_i ≥ target_j` (Minimum)  
   `Σ composition_ij × x_i ≤ target_j` (Maximum)
3. **DP/DE ratio:** Linearised to a single minimum inequality: `Σ (dCP_i − rhs × dDE_i) × x_i ≥ 0`.
4. **Binder cap:** `Σ_{i ∈ binders} x_i ≤ max_binder_inclusion` (default 0.25).
5. **Fish-meal cost-share cap:** `Σ_{FM} price_i × x_i ≤ max_fishmeal_cost_share × Σ price_i × x_i` (default 0.20; linearised).

The solver used is HiGHS (via PuLP), with a fallback to CBC. The time limit is 30 seconds per request. The solution is exact (continuous LP) and globally optimal within the model's assumptions.

### Premix masking

When `premix_enabled = true`, ASNS constraints for vitamins (V01–V15) and trace minerals (M08–M13) are **excluded from the LP** on the assumption that these micronutrients are supplied by the premix. Toxin constraints (TX01–TX16) are **always enforced**, regardless of premix settings.

For brood stock stages, Vitamin C (V09) is re-activated even when premix masking is enabled (it is removed from the default mask for the `Brood` stage).

Custom masking can be specified per request via `custom_premix_mask_codes` (see §6.2).

---

## 6. API Access

### 6.1 Authentication

All API endpoints (except `/health` and `/ready`) require authentication. Include the token in one of two ways:

```
Authorization: Bearer <token>
```

or

```
X-Api-Key: <token>
```

### 6.2 Swagger Interface

The interactive documentation is available at:

```
<base_url>/docs
```

All endpoints can be tested directly from the browser interface. Click **Authorize** (top right), enter the token, and submit requests using the **Try it out** button on each endpoint.

---

## 7. Endpoint Reference

### 7.1 `GET /supported`

Returns the complete list of supported species, production systems, and valid stage labels.

**Use this endpoint first** to confirm the exact strings required for `species`, `production_system`, and `stage` in formulation requests. Stage labels must match exactly (including spacing, capitalisation, and punctuation).

**Response structure:**

```json
{
  "species": ["Nile Tilapia", "African Catfish"],
  "production_systems": ["General-LowCost", "General"],
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

### 7.2 `POST /formulate` — Request Schema

All field definitions and defaults:


| Field                      | Type            | Required | Default             | Definition                                                                                                                                                                                                             |
| -------------------------- | --------------- | -------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `species`                  | string          | **Yes**  | —                   | Target species. Allowed: `"Nile Tilapia"` or `"African Catfish"`                                                                                                                                                       |
| `stage`                    | string          | **Yes**  | —                   | Growth stage label. Must match exactly one of the labels returned by `GET /supported` for the chosen species and production system                                                                                     |
| `production_system`        | string          | No       | `"General-LowCost"` | Nutritional specification profile. `"General"` applies standard targets; `"General-LowCost"` applies relaxed targets (Nile Tilapia only)                                                                               |
| `prices`                   | object          | **Yes**  | —                   | Dictionary mapping ingredient `code` (as a string) to price per kg (float). Only codes present in the Africa pool are used; unlisted codes are ignored. At least one ingredient must be provided                       |
| `processing_method`        | string          | No       | `"pelleted"`        | Feed manufacturing method. Selects the corresponding digestible energy column from FICD. Allowed: `"pelleted"` or `"extruded"`                                                                                         |
| `premix_enabled`           | boolean         | No       | `true`              | If `true`, vitamin and trace mineral constraints are excluded from the LP (assumed covered by premix). Toxin constraints are always active                                                                             |
| `premix_rate`              | float           | No       | `0.005`             | Mass fraction of the feed reserved for the premix (0–0.10 exclusive). Default 0.005 = 0.5%. This mass is subtracted from the ingredient budget before the LP runs                                                      |
| `max_fishmeal_cost_share`  | float           | No       | `0.20`              | Maximum fraction of total ingredient cost attributable to fish-meal ingredients (is_fishmeal = true). Range [0, 1]                                                                                                     |
| `max_binder_inclusion`     | float           | No       | `0.25`              | Maximum combined mass fraction of binder-flagged ingredients (is_binder = true). Range [0, 1]                                                                                                                          |
| `custom_premix_mask_codes` | list of strings | No       | `null`              | If provided, **replaces** the default premix mask entirely. List of ASNS specification codes (e.g. `["V01","V02","M08"]`) to exclude from the LP. Toxin codes (TX*) in this list are still enforced. Maximum 200 codes |


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

**Practical note on ingredient selection:** The LP can only use ingredients for which both a price and an Africa-pool entry exist. Providing more ingredients increases the feasible space and generally reduces cost. If the ingredient set is too restricted, the solver may return `infeasible`.

---

### 7.3 `POST /formulate` — Response Schema and Interpretation


| Field               | Type            | Meaning                                                                                                                 |
| ------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `status`            | string          | Outcome: `"optimal"`, `"infeasible"`, or `"error"`                                                                      |
| `species`           | string          | Echo of input                                                                                                           |
| `stage`             | string          | Echo of input                                                                                                           |
| `production_system` | string          | Echo of input                                                                                                           |
| `processing_method` | string          | Echo of input                                                                                                           |
| `premix_enabled`    | boolean         | Echo of input                                                                                                           |
| `premix_rate`       | float           | Echo of input                                                                                                           |
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
| `inclusion_percent` | Mass fraction in the feed, expressed as a percentage. The sum of all `inclusion_percent` values equals `(1 − premix_rate) × 100`. The remaining share (default 0.5%) is the premix |
| `cost_per_kg`       | Price as supplied in the request                                                                                                                                                   |
| `cost_contribution` | This ingredient's contribution to the total feed cost (fraction × price). Summing all `cost_contribution` values gives `cost_per_kg`                                               |


**Composition lines** (`composition` list):


| Field              | Meaning                                                                                                                  |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `code`             | ASNS specification code                                                                                                  |
| `spec_label`       | Human-readable name of the constraint                                                                                    |
| `restriction_type` | `"Minimum"`, `"Maximum"`, or `"Minimum"` (ratios are linearised to a minimum constraint)                                 |
| `target`           | Constraint threshold value from the ASNS database                                                                        |
| `achieved`         | Value realised by the optimised recipe                                                                                   |
| `unit`             | Measurement unit                                                                                                         |
| `in_spec`          | Boolean: `true` if the achieved value satisfies the constraint. Should be `true` for all rows in an `"optimal"` solution |


The `composition` list includes only constraints that were active in the LP (i.e. those with a non-blank ASNS value, a mapped FICD parameter, and not masked by the premix). Masked constraints (vitamins, trace minerals) do not appear.

---

### 7.4 `POST /validate-recipe` — Request and Response

This endpoint recomputes the nutritional composition of a **user-defined recipe** without running the optimiser. It is useful for checking an existing formulation against the FICD composition data.

**Request:**


| Field        | Type            | Required | Meaning                                                                                                                                                    |
| ------------ | --------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fractions`  | object          | **Yes**  | Dictionary mapping ingredient code (string) to mass fraction (float in [0, 1]). Fractions do not need to sum to 1; each is treated independently           |
| `parameters` | list of strings | No       | List of FICD parameter column names to include in the output (e.g. `["crude_protein_percent", "lysine_percent"]`). If omitted, all parameters are returned |


**Response:**

```json
{
  "composition": {
    "crude_protein_percent": 32.41,
    "lysine_percent": 1.87,
    ...
  }
}
```

Each value is the weighted sum `Σ composition_ij × fraction_i` across the supplied ingredients, rounded to 6 decimal places. No nutritional constraints are checked; this is a pure composition calculation.

---

## 8. Possible Outcomes

### 8.1 Optimal

The LP found a feasible solution and the solver converged to a global minimum. All nutritional constraints are satisfied by the returned recipe. The `cost_per_kg` field contains the minimised feed cost.

A soft warning is generated (but the solution remains optimal) if any single ingredient exceeds 40% of total feed mass. High single-ingredient inclusion may indicate an undersupplied ingredient set or a very restrictive constraint profile.

### 8.2 Infeasible

No combination of the supplied ingredients can simultaneously satisfy all active nutritional constraints within the structural limits (mass balance, binder cap, fish-meal cost-share cap, maximum inclusions).

The `infeasibility` object contains:


| Field              | Meaning                                                                                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `iis_codes`        | List of ASNS specification codes in the approximate irreducible infeasible subset (IIS) — the minimal set of conflicting constraints identified by the engine |
| `iis_explanations` | Human-readable description of each conflicting constraint                                                                                                     |
| `suggestion`       | A general diagnostic suggestion                                                                                                                               |


**Common causes of infeasibility:**

- The ingredient set is too small or nutritionally inadequate to meet one or more active constraints simultaneously (e.g. insufficient amino acid sources to satisfy both a protein minimum and a cost-share cap on fish meal).
- A constraint requires a nutrient for which no supplied ingredient contains that nutrient in the FICD database (composition value is zero or absent for all included ingredients).
- Conflicting constraints: e.g. a high protein minimum combined with a low crude fibre maximum may require ingredients that simultaneously violate another constraint.

**Diagnostic approach:** Examine the `iis_codes` returned. If, for example, the IIS contains `AA05` (Lysine) and `max_fishmeal_cost_share`, consider adding a synthetic lysine source (code `61109`) or relaxing the fish-meal cost cap.

### 8.3 Error

An internal processing failure. HTTP 400 errors indicate an invalid request (unsupported species, production system, or malformed body). HTTP 500 errors indicate a server-side failure.

---

## 9. Warnings

Warnings are non-fatal messages appended to any response (including optimal solutions). They do not invalidate the result but indicate model limitations or data gaps.


| Warning type            | Meaning                                                                                                              |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Unmapped specification  | An ASNS constraint has no corresponding FICD parameter column; the constraint was dropped and not enforced by the LP |
| Single ingredient > 40% | One ingredient exceeds 40% of total mass in the optimal solution; may warrant inspection                             |


---

## 10. Known Limitations

The following limitations reflect the current MVP implementation and should be considered when interpreting results.

### 10.1 No Country-Localised Ingredient Pools

A single Africa-wide ingredient pool is used for all requests. There is no mechanism to restrict the ingredient set to a specific country or region (e.g. Kenya, Nigeria, Zambia). Per-country pool splits are planned for a future version.

### 10.2 No Ingredient Price Book

The engine has no internal price reference. Prices must be supplied by the user in every request. There is no validation of price plausibility or currency consistency. Results are directly sensitive to the price values provided.

### 10.3 No Maximum Inclusion Limits for Most Ingredients

The Africa pool defines a maximum inclusion limit for only one ingredient (blood meal: 5%). For all other ingredients, the LP has no per-ingredient upper bound. Practically, nutritional constraints and the collective binder/fish-meal caps impose implicit upper limits, but there are no ingredient-specific agronomic or processing ceilings for the remaining 38 ingredients.

### 10.4 Premix Nutrient Contribution Not Modelled

When `premix_enabled = true`, the LP reserves `premix_rate` of the feed mass for a premix and skips vitamin and trace mineral constraints. However, the nutritional content of the premix itself is **not added** to the composition output. The `composition` response reflects only the contribution of the optimised ingredient fraction. Achieved values for vitamins and trace minerals are not reported.

### 10.5 Anti-Nutritional Interactions Not Modelled

The LP treats ingredient composition as strictly additive. Digestibility penalties from anti-nutritional factors (e.g. phytate reducing phosphorus bioavailability, tannins reducing protein digestibility, gossypol interacting with lysine) are not modelled. Toxin constraints (TX01–TX16) are enforced as hard ceilings on total dietary concentration, but interaction effects between anti-nutritional factors are not captured.

### 10.6 No Non-Additive Energy Interactions

Digestible energy values in FICD are ingredient-specific and additive in the LP. Interactions between energy substrates (e.g. protein-sparing by lipid) are not accounted for beyond what is inherent in the digestible energy coefficients.