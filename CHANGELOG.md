# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `/formulate`, `/validate-recipe` and `/supported` responses now include `engine_version`, the engine release that produced them (as `/health` already reports it under `version`), so a stored recipe or check can be traced to the engine that made it.
- The FASA team's default prices for Nigeria, Kenya and Zambia, in `data/FASA_default_prices.csv`, for the app to offer as starting prices. Each row gives the code to send in `prices` (or the `premix_price`), the price per kg in local currency, and whether it is final (`ok`) or still `to check` or `missing`. As of 6 November 2026: 134 rows, 76 ok, 57 to check, and the Zambia premix price missing.

### Changed
- FASA ingredients now take their amino acids from the IAFFD ingredient the FASA team paired with each, scaled to the FASA lab crude protein, as the team decided on 6 November 2026; the lab amino acids, 2 to 3 times lower than IAFFD's, are no longer used. With the FASA default prices, 80 of 84 test formulations now have a recipe (76 before) and FASA ingredients make up a median 27% of it (21% before).
- FASA ingredients now have lab starch values (FASA lab file of 6 November 2026), so they count towards the starch minimum instead of counting as zero. The same file corrects the ash of Zambian tea waste from 23.2% to 5.9%. With the FASA default prices, 80 of 84 test formulations have a recipe, as before, and FASA ingredients make up a median 28% of it.
- Maximum inclusion per weight group for 15 common ingredients, from the FASA team's ingredient form of 6 November 2026: feather meal, L-lysine, maize, fish meal, cassava starch, wheat flour, meat and bone meal, corn gluten meal, the vitamin C product, DCP, fish oil, soybean oil, DL-methionine, palm oil and palm kernel meal. Four earlier maximums go up: grain maize for tilapia over 100 g (10% to 40%), 60% CP corn gluten meal for tilapia (7/5/5% to 15/20/30%), wheat flour for catfish over 10 g (10% to 15%) and DL-methionine for tilapia from 10 g (0.2% to 0.6%); the form sets each IAFFD version on its own, so the other maizes and corn gluten meals keep their earlier maximums. With the FASA default prices, 75 of 84 test formulations have a recipe (80 before): tilapia up to 10 g in Kenya and Zambia and Kenyan tilapia brood no longer get one.
- The seven IAFFD rice brans may now make up at most 10% of the feed for both species (it was 30% for tilapia and 15% for catfish), the rice bran maximum the FASA team set on 6 November 2026; the Kenyan FASA rice bran already had 10% at every stage. With the FASA default prices no recipe changes, as none used more than 10%.

### Removed
- Chikanda (`FASA-ZM-11`), at the FASA team's request: it is no longer an ingredient and has no default price. Its code is not reused. Migration: stop sending `FASA-ZM-11` in `prices`; it is now ignored with a `[skip]` warning.

## [1.1.0] - 2026-11-05

### Added
- `/validate-recipe` takes an optional `premix_rate` (`0.01`, `0.015` or `0.02`, default `0.02`), so its nutrient checks count the premix as `/formulate` does. When checking a recipe made at 1% or 1.5%, send that rate.
- 43 FASA ingredients, the lines the FASA team kept in the decisions workbook returned on 5 November 2026: FASA lab samples used as-fed, with phosphorus, toxins, the anti-nutrients the lab did not measure, trace minerals and vitamins from the IAFFD ingredient the team linked to each, and digestible energy equal to gross energy times that IAFFD ingredient's digestibility. Price them like any other ingredient, with the codes `FASA-KE-01` to `FASA-ZM-11` listed in `scripts/data/fasa_ingredients.csv`; all 299 IAFFD ingredients stay. With the 24 test prices and every FASA ingredient at almost no cost, all 19 General stages have a recipe, and FASA ingredients make up 42 to 68% of it (median 57%).
- Maximum inclusion for each FASA ingredient, per species (workbook tab 1), and per stage where FASA APP DATA gives a weight-group value, which then wins. That only applies to soybean meal (tilapia 35/40/45%, catfish 36%) and rice bran (10%).
- Maximum inclusion for 31 IAFFD ingredients whose FASA line the team removed for lack of a lab sample, taking the FASA team's limits for that line: blood meal (tilapia 5%, catfish 4%), poultry meal (tilapia 10/7/4% by weight group, catfish 8%), corn gluten meal (tilapia 7/5/5%), rapeseed meal (tilapia 8/7% from 10 g, catfish 10%), corn bran and wheat bran (10%), broken rice (tilapia 15%, catfish 6%), cassava tuber meal (tilapia 0% up to 10 g, then 6%; catfish 6%), maize (tilapia over 100 g, 10%), palm oil (tilapia from 10 g, 3%), synthetic methionine (tilapia from 10 g, 0.2%) and wheat flour (catfish 10%). Where FASA APP DATA does not say max or min, the value is read as a maximum. Without them, recipes with real prices could hold 26-42% blood meal.
- Limits on groups of ingredients together: all brans at most 15%, and fishmeals at least 5% for tilapia up to 10 g and 3% above. They count the FASA ingredients the team marked and the IAFFD ones of the same kind (13 brans and wheat pollards, 27 fish and shrimp meals in all). In `/formulate` a group minimum applies only when one of its ingredients is priced, otherwise a warning says it was not applied; `/validate-recipe` always checks it.
- An ash maximum, from WorldFish's feed formulation constraints: 10% for tilapia, 10% for catfish under 5 g and 8% from 500 g (none yet for catfish 5-500 g). IAFFD's own ash maximum is blank, so feeds had no ash limit before; with real prices, ash reached 16%.
- A saponin maximum (`TX15F`) for the FASA lab saponin values, equal to the ASNS soyasaponin maximum for the stage.
- A range for crude protein of 2 points either side of the requirement, and 1 point for crude lipid: the minimum comes down by that much and a maximum is added (African Catfish 50-200g: 34-38% protein).
- `/formulate` warns when a priced code is not in the ingredient pool (it is still ignored, as before), and when a request leaves out `production_system`, which then defaults to General-LowCost.

### Changed
- `/formulate` refuses a negative price: the API returns 422 and `fasa_core.formulate` raises an error. A price of 0 stays allowed, for a free by-product. Before, a negative price was accepted and made `cost_per_kg` wrong. Migration: send prices of 0 or more.
- These rules are dropped for every feed, as the FASA team decided: digestible protein and digestible protein per unit of energy, digestible amino acids, digestible phosphorus, phospholipids, cholesterol, sodium, chlorine, potassium, magnesium, and the 10% moisture minimum. Without the moisture minimum, all 19 General stages have a recipe with the 24 test prices (9 before).
- African Catfish crude protein follows the FASA requirements table: 36.0% at 50-200g (ASNS 35.6%) and 31.5% at 800-1000g (ASNS 31.7%).
- The 5% / 2.5% caps on IAFFD shrimp meal (14002) and broken dried shrimp (14007) are removed; the FASA Ochonga lines carry them instead.
- The FASA team confirmed keeping the digestible energy rules for every feed, with FASA ingredients' digestible energy calculated as above.
- `composition` and `nutrient_checks` no longer list the dropped rules, and gain the protein and lipid maximums, `TX15F`, and one line per group limit, whose `code` is the group name (for example `All brans`), in % of feed. `source` reads `fasa` for a rule the FASA team added or changed. Migration: the dropped rules' codes (for example `PA02`, `ADAAF01`, `M03`) no longer appear in `composition` or `nutrient_checks`, so stop looking them up; and do not assume every `composition` or `iis_codes` entry is an ASNS code.
- The premix's vitamins and trace minerals now count in every formulation. The composition the FASA team supplied on 29 October 2026 (13 vitamins and 6 trace minerals per kg of premix) is added at the chosen `premix_rate`, and these nutrients are checked against ASNS like any other instead of being assumed covered. With the test prices, all 59 formulations that had a solution keep one and 58 are unchanged; Nile Tilapia, General, 30-70g at 1% premix costs 0.2% more because the ingredients now top up iodine.
- `composition` in `/formulate` and `nutrient_checks` in `/validate-recipe` now list the 13 vitamins and 6 trace minerals, with the premix's share included in `achieved`.
- Brood stages no longer need vitamin C from the ingredients, since the premix supplies it. With the test prices, African Catfish brood at 1% premix now has a solution.
- At 1% the premix alone is below the ASNS minimum for iodine in 10 species and stage combinations, for iron in 3 and for selenium in 1, so the ingredients must supply the rest. The FICD iodine gap noted in 0.5.0 therefore matters in those cases.
- Choline and inositol are not in the premix and are not checked: the FASA team dropped these rules. The premix's cobalt and BHT are not used, as ASNS sets no requirement for them.

## [1.0.0] - 2026-10-15

### Changed
- Every feed now includes the vitamin/mineral premix, as agreed with the FASA team on 15 October 2026. Callers choose its rate from 1%, 1.5% or 2% (`premix_rate` `0.01`, `0.015` or `0.02`; default 2%, previously 0.5%) and send its price per kg as the new required `premix_price`. The premix cost is now part of `cost_per_kg` and `total_cost`, which rise by `premix_rate × premix_price`.
- The premix is still assumed to supply the vitamins and trace minerals, and its own nutrients are not counted, so a larger premix leaves less room for the other ingredients. With the test prices, 10 of the 28 pelleted species and stage combinations have no solution at 2%, against 6 at the old 0.5%.
- Python callers of `fasa_core.formulate` get the same rule as the API: a `premix_rate` other than 0.01, 0.015 or 0.02 raises an error.

### Removed
- The premix on/off switch (`premix_enabled`, on `/formulate` and `/validate-recipe`), the fish-meal cost-share cap (`max_fishmeal_cost_share`) and the binder cap (`max_binder_inclusion`); responses no longer echo them. Stop sending these fields: requests that include them are now rejected (422).
- The option to change which vitamins and trace minerals the premix is assumed to supply (`custom_premix_mask_codes`): as agreed on 15 October, the premix composition is fixed. Stop sending this field: requests that include it are now rejected (422).
- The 32 IAFFD vitamin and mineral premix products from the ingredient pool (331 to 299 ingredients), so a premix cannot be priced in on top of the fixed one. Vitamin C (Rovimix Stay-C 35, code 60128) stays and can be added at a fixed rate through `ingredient_limits`.

## [0.5.0] - 2026-10-14

### Added
- A repeatable way to load new ASNS and FICD releases into the engine: `scripts/import_datasets.py` converts the files exported from the FASA database (see the README).

### Changed
- Nutrition requirements (ASNS) and ingredient composition (FICD) updated to v11.1 (30 July 2026). The PAFF reference recipes stay at v6.0 (3 December 2025). Six ingredients are new; one of them, fermented rapeseed meal (30918), joins the ingredient pool. With the test prices every species and stage gives the same kind of result as before (a recipe, or no solution), and costs per kg move by −2.9% to +2.3%.
- Vitamin A and D requirements are now published in IU/kg and used as they are. If you send your own Vitamin A or D limits, send them in IU/kg (previously mg and µg).
- Units in results now read per kg, e.g. `kcal/kg` and `mg/kg` instead of `kcal` and `mg`.
- Maximum inclusion levels per species (Nile Tilapia, African Catfish) from the max-inclusion table supplied in October 2026 now apply to 17 of its 42 ingredients. These cover 75 FICD entries, because some ingredients have several FICD variants (rice bran has 7). Recipes that went over a ceiling change: with the test prices, low-cost tilapia grower diets drop from 44–51% rice bran to the 30% ceiling, at a 2–4% higher cost per kg.

### Removed
- Pig and poultry digestibility values are no longer reported by `/validate-recipe`, because FICD v11.1 no longer includes them. Remove them from any `parameters` list you send. Three values are new: proline, its share of protein, and dietary electrolyte balance.

### Fixed
- `/validate-recipe` now returns a clear "bad request" error, instead of a server error, when asked for a value the ingredient database does not hold.

### Notes
- Iodine values in the FICD v11.1 file are wrong (they repeat the dietary electrolyte balance), so the engine keeps the previous release's iodine values until a corrected file is available. The six new ingredients have no iodine value. Iodine is normally covered by the premix, so this matters only when the premix is switched off or a request sets an iodine limit.
- Fermented rapeseed meal (30918) has no digestible energy or digestible amino acid values yet, so the engine counts them as zero.
- 25 of the 42 rows in the max-inclusion table are not used: 24 name ingredients with no composition data, and one has no separate entry. No nutrient limits are set yet.
- A ceiling applies to each ingredient variant separately, not to their sum: two rice brans can each reach 30%.

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

