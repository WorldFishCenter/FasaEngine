"""Independent recomputation of nutrient composition + PAFF benchmark gate.

This module is the safety net against unit-conversion bugs and silent FICD
column-mapping errors. The `validate()` function is called automatically by
the API and also exposed for ad-hoc testing.

`validate_recipe()` backs POST /validate-recipe: it recomputes composition for a
recipe the caller supplies and scores it against the min/max inclusion layer, so a
hand-edited or externally sourced recipe can be checked without re-running the LP.

PAFF benchmark: feed the engine the 36 reference recipes' inclusion vectors
*directly* (i.e., bypass the LP and compute composition only) and compare
nutrient-by-nutrient with the published Calculated_Composition table.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

import pandas as pd

from . import inclusion_limits
from .config.defaults import (
    DEFAULT_PROCESSING_METHOD,
    SOLUTION_FRACTION_TOL,
    VALIDATION_REL_TOL,
    as_percent,
)
from .constraint_builder import build_constraints, score_constraints
from .data_loader import load_ficd_wide, load_paff
from .inclusion_limits import LimitScope
from .ingredient_pool import load_pool
from .models import IngredientLimitLine, NutrientLine, ValidateRecipeResponse

# A complete diet sums to 100% of feed mass, or a little less when a vitamin/mineral
# premix takes the remainder (the LP returns 1 - premix_rate, default 99.5%). Same
# band the smoke tests assert on the LP's own output.
MIN_TOTAL_INCLUSION = 0.99
MAX_TOTAL_INCLUSION = 1.0


# --------------------------------------------------------------------------- #
# ad-hoc recipe → nutrient composition                                        #
# --------------------------------------------------------------------------- #


def compute_composition(
    fractions: dict[str, float],
    parameters: list[str] | None = None,
) -> pd.DataFrame:
    """Compute  composition[p] = Σ_i frac_i * ficd[i, p]  for each parameter p.

    Useful for: (a) the PAFF benchmark, (b) sanity-checking LP outputs against
    a clean independent code path, (c) front-end "what-if" displays without
    re-running the LP.
    """
    ficd = load_ficd_wide()
    if parameters is None:
        parameters = [c for c in ficd.columns if c not in ("code", "description")]

    frac_series = pd.Series(fractions, dtype="float64")
    sub = ficd[ficd["code"].isin(frac_series.index)].set_index("code")
    sub = sub.reindex(frac_series.index)
    weighted = sub[parameters].fillna(0.0).mul(frac_series, axis=0)
    composition = weighted.sum(axis=0)
    return composition.rename("value").to_frame()


# --------------------------------------------------------------------------- #
# explicit recipe → composition + inclusion-rate checks                       #
# --------------------------------------------------------------------------- #


def validate_recipe(
    fractions: dict[str, float],
    *,
    parameters: Optional[list[str]] = None,
    species: Optional[str] = None,
    stage: Optional[str] = None,
    production_system: Optional[str] = None,
    processing_method: str = DEFAULT_PROCESSING_METHOD,
    premix_enabled: bool = True,
    nutrient_limits: Optional[dict] = None,
    ingredient_limits: Optional[dict] = None,
) -> ValidateRecipeResponse:
    """Score a caller-supplied recipe: composition, inclusion rates, nutrient levels.

    Composition always comes back. The per-ingredient inclusion checks always run —
    limit rows with a blank scope column apply to every request, so they bind even
    when no species/stage is given. The nutrient checks need the full
    (species, stage, production_system) triple to resolve an ASNS row set, and are
    omitted with a warning when it is incomplete.
    """
    fractions = {str(code): float(frac) for code, frac in fractions.items()}
    composition = compute_composition(fractions, parameters=parameters)
    scope = LimitScope(
        species=species,
        stage=stage,
        production_system=production_system,
        processing_method=processing_method,
    )

    pool = load_pool(only_codes=set(fractions))
    descriptions = _ficd_descriptions()
    warnings: list[str] = []

    unpooled = sorted(set(fractions) - {rec.code for rec in pool})
    if unpooled:
        # These still contribute to `composition` (that path reads FICD directly),
        # but they carry no pool entry, so they can hold no inclusion limit and
        # contribute nothing to the nutrient checks — same restriction /formulate has.
        warnings.append(
            f"[skip] {len(unpooled)} code(s) are absent from the ingredient pool, so they "
            f"carry no inclusion limits and are excluded from the nutrient checks: "
            f"{', '.join(unpooled)}."
        )

    # ---------- inclusion rates --------------------------------------------- #

    total = sum(fractions.values())
    # The band carries a tolerance so summation noise at exactly 1.0 does not warn.
    if not (MIN_TOTAL_INCLUSION - SOLUTION_FRACTION_TOL
            <= total
            <= MAX_TOTAL_INCLUSION + SOLUTION_FRACTION_TOL):
        warnings.append(
            f"[mass] inclusions sum to {total * 100:.2f}% of feed mass. A complete diet "
            f"sums to 100%, or {MIN_TOTAL_INCLUSION * 100:.0f}-100% when a vitamin/mineral "
            f"premix takes the remainder."
        )

    box = inclusion_limits.ingredient_bounds(
        scope, pool, overrides=inclusion_limits.from_request(ingredient_limits)
    )

    inclusion_checks = [
        _check_inclusion(code, frac, box.get(code), descriptions.get(code, ""))
        for code, frac in sorted(fractions.items(), key=lambda kv: -kv[1])
    ]

    # ---------- nutrient levels --------------------------------------------- #

    nutrient_checks: list[NutrientLine] = []
    if species and stage and production_system:
        constraints, build_warnings = build_constraints(
            species=species,
            stage=stage,
            production_system=production_system,
            pool=pool,
            processing_method=processing_method,
            premix_enabled=premix_enabled,
            nutrient_limits=inclusion_limits.nutrient_bounds(
                scope, overrides=inclusion_limits.from_request(nutrient_limits)
            ),
        )
        warnings += build_warnings
        nutrient_checks = score_constraints(constraints, fractions)
    elif any((species, stage, production_system)) or nutrient_limits:
        warnings.append(
            "[skip] nutrient checks need species, stage and production_system together; "
            "only the per-ingredient inclusion limits were checked."
        )

    return ValidateRecipeResponse(
        composition=composition["value"].round(6).to_dict(),
        total_inclusion_percent=as_percent(total),
        in_limits=(
            all(line.in_limits for line in inclusion_checks)
            and all(line.in_spec for line in nutrient_checks)
        ),
        inclusion_checks=inclusion_checks,
        nutrient_checks=nutrient_checks,
        warnings=warnings,
    )


def _check_inclusion(
    code: str,
    fraction: float,
    bound: Optional[inclusion_limits.Bound],
    description: str,
) -> IngredientLimitLine:
    """Compare one inclusion against its resolved box, tolerating fraction-scale noise."""
    low = bound.minimum if bound is not None else None
    high = bound.maximum if bound is not None else None
    return IngredientLimitLine(
        code=code,
        description=description,
        inclusion_percent=as_percent(fraction),
        min_inclusion_percent=as_percent(low),
        max_inclusion_percent=as_percent(high),
        limit_source=bound.source if bound is not None else None,
        in_limits=(
            (low is None or fraction >= low - SOLUTION_FRACTION_TOL)
            and (high is None or fraction <= high + SOLUTION_FRACTION_TOL)
        ),
    )


@lru_cache(maxsize=1)
def _ficd_descriptions() -> dict[str, str]:
    """code -> description for every FICD ingredient. Read-only; derived once."""
    ficd = load_ficd_wide()
    return dict(zip(ficd["code"].astype(str), ficd["description"]))


# --------------------------------------------------------------------------- #
# PAFF benchmark gate                                                         #
# --------------------------------------------------------------------------- #


def benchmark_against_paff(
    species_label: str,
    parameters_to_check: list[str] = (
        "crude_protein_percent",
        "crude_lipids_percent",
        "crude_fibre_percent",
        "ash_percent",
        "lysine_percent",
        "methionine_percent",
        "phosphorus_percent",
    ),
) -> pd.DataFrame:
    """Recompute one PAFF reference formulation and diff vs. published values.

    Returns a DataFrame with columns
      [parameter, our_value, paff_value, abs_diff, rel_diff]
    """
    forms, comps = load_paff()
    rec = forms[forms["species"] == species_label]
    if rec.empty:
        raise ValueError(f"No PAFF formulation for species_label={species_label!r}")

    fractions = {str(c): float(p) / 100.0 for c, p in
                 zip(rec["iaffd_code"], rec["inclusion_percent"])}
    ours = compute_composition(fractions, parameters=list(parameters_to_check))

    # PAFF composition is keyed by 'nutrient' name (free text, not code), so we
    # provide a small mapping for the parameters we benchmark.
    name_map = {
        "crude_protein_percent": "Crude Protein",
        "crude_lipids_percent":  "Crude Lipids",
        "crude_fibre_percent":   "Crude Fibre",
        "ash_percent":           "Ash",
        "lysine_percent":        "Lysine",
        "methionine_percent":    "Methionine",
        "phosphorus_percent":    "Phosphorus",
    }
    paff_sub = comps[comps["species"] == species_label].set_index("nutrient")["value"]

    rows = []
    for p, ours_v in ours["value"].items():
        paff_name = name_map.get(p, p)
        paff_v = float(paff_sub.get(paff_name, float("nan")))
        rows.append({
            "parameter": p,
            "our_value": float(ours_v),
            "paff_value": paff_v,
            "abs_diff":  abs(float(ours_v) - paff_v) if pd.notna(paff_v) else float("nan"),
            "rel_diff":  (abs(float(ours_v) - paff_v) / paff_v
                          if pd.notna(paff_v) and paff_v != 0 else float("nan")),
        })
    return pd.DataFrame(rows)


def benchmark_passes(report: pd.DataFrame, tol: float = VALIDATION_REL_TOL) -> bool:
    """True if every comparable parameter is within `tol` relative tolerance."""
    diffs = report["rel_diff"].dropna()
    return bool(len(diffs)) and bool((diffs <= tol).all())
