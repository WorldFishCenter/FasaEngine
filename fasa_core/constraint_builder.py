"""Solver-agnostic constraint emission.

For a given (species, stage, system) and ingredient pool, produce a list of
linear constraints in a tiny intermediate form that the optimizer module then
materializes into the chosen solver's API.

Intermediate form per row:
    {
      "spec_code":        ASNS code (e.g. 'PA03')
      "spec_label":       human-readable
      "restriction_type": "Minimum" | "Maximum" | "Ratio"
      "rhs":              float  (the ASNS target, after unit conversion)
      "coeffs":           dict[ingredient_code -> float]   (LHS sum coefficients)
      "constant":         float (added to the LHS RHS-side, e.g. premix contribution)
      "unit":             ASNS unit string (informational)
      "kind":             "linear"  (ratios get linearized in this same form)
    }

The premix mask is applied here: masked spec codes never make it into the
output. Toxin (TX*) maximums are NEVER masked even if the user passes a custom
mask that includes them — the premix doesn't add toxins, and the safety
ceilings on aflatoxin/gossypol/etc. are non-negotiable per the FASA brief.

The nutrient inclusion-limit layer (`inclusion_limits`) is folded into the ASNS
row set before emission, so the limits inherit the whole existing pipeline —
crosswalk resolution, unit conversion, coefficients, the composition report and
the deletion-filter IIS. A row the layer created or tightened is exempt from the
premix mask — an explicit operator bound always binds — while a plain ASNS row
for the same code stays masked, so capping zinc does not also resurrect the zinc
minimum the premix supplies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from . import crosswalk
from .config.defaults import IN_SPEC_ABS_TOL, IN_SPEC_INPUT_TOL, IN_SPEC_REL_TOL
from .data_loader import get_active_constraints
from .inclusion_limits import Bound
from .ingredient_pool import IngredientRecord, attach_ficd_rows
from .models import NutrientLine


@dataclass
class LinearConstraint:
    spec_code: str
    spec_label: str
    restriction_type: str   # "Minimum" | "Maximum" | "Ratio" (linearized)
    rhs: float
    coeffs: dict[str, float]
    constant: float
    unit: str
    source: str = "asns"    # "asns" | "asns+<layer>" | "<layer>"; see inclusion_limits

    def __repr__(self) -> str:                                                # pragma: no cover
        op = {"Minimum": ">=", "Maximum": "<=", "Ratio": "="}[self.restriction_type]
        return f"<{self.spec_code} {self.spec_label!r}: ... {op} {self.rhs:g} {self.unit}>"


def build_constraints(
    species: str,
    stage: str,
    production_system: str,
    pool: list[IngredientRecord],
    processing_method: str = "pelleted",
    premix_enabled: bool = True,
    premix_rate: float = 0.005,
    premix_mask_override: Optional[list[str]] = None,
    nutrient_limits: Optional[dict[str, Bound]] = None,
) -> tuple[list[LinearConstraint], list[str]]:
    """Materialize the active constraint set.

    Returns
    -------
    constraints : list[LinearConstraint]
    warnings    : list[str] — non-fatal notes (unmappable specs, etc.)
    """
    asns_active = get_active_constraints(species, stage, production_system)
    asns_active, warnings = _apply_nutrient_limits(asns_active, nutrient_limits or {})
    ficd_pool = attach_ficd_rows(pool).set_index("code")

    mask = (
        crosswalk.premix_mask_codes(stage, premix_mask_override)
        if premix_enabled
        else set()
    )

    out: list[LinearConstraint] = []

    for _, row in asns_active.iterrows():
        code = row["code"]
        rtype = row["restriction_type"]
        source = row["source"]

        # --- masking rules -------------------------------------------------- #
        if code in mask and not code.startswith("TX") and source == "asns":
            # vit/trace-mineral satisfied by premix; skip silently
            continue
        # toxins are NEVER masked, even via override. Neither is a row the limit layer
        # created or tightened — but a plain ASNS row for the same code stays masked,
        # so bounding zinc's maximum never resurrects the minimum the premix supplies.

        ficd_param, factor = crosswalk.resolve(code, processing_method)
        unit = row["unit"] or crosswalk.spec_unit(code)
        spec_label = crosswalk.spec_label(code)

        if ficd_param is None:
            warnings.append(
                f"[skip] no FICD mapping for spec {code} ({spec_label}); "
                f"constraint dropped from MVP."
            )
            continue

        rhs_raw = float(row["value_numeric"])

        # ------------- linear (non-ratio) specs ---------------------------- #
        if ficd_param != "__ratio__":
            coeffs = _ingredient_coefficients(ficd_pool, ficd_param)
            constant = 0.0  # placeholder — premix nutrient credit could be added here
                            # in the future for non-masked specs that the premix still
                            # contributes to (e.g., choline). For MVP we keep it 0.

            # apply the unit conversion to the spec target
            rhs = rhs_raw * float(factor)

            out.append(
                LinearConstraint(
                    spec_code=code,
                    spec_label=spec_label,
                    restriction_type=rtype,
                    rhs=rhs,
                    coeffs=coeffs,
                    constant=constant,
                    unit=unit,
                    source=source,
                )
            )
            continue

        # ------------- ratio specs (linearize as ≥) ------------------------ #
        # ASNS labels DP/DE etc. as 'Ratio' but the biological intent is a
        # *minimum* protein-to-energy density (Bureau 2014, NRC 2011): below the
        # threshold, dietary protein is wasted as energy. We therefore emit
        # ratio constraints as ≥ inequalities, not equalities. Upper-bound
        # ratios (none in current ASNS) would need a parallel _max variant.
        ratio = factor   # `factor` carries the dict for ratio entries
        numer_param  = ratio["numer"]
        denom_param  = ratio["denom"]
        numer_factor = float(ratio.get("numer_factor", 1.0))   # %  → g/kg, etc.
        denom_factor = float(ratio.get("denom_factor", 1.0))   # kcal/kg → MJ/kg, etc.

        a = _ingredient_coefficients(ficd_pool, numer_param)
        b = _ingredient_coefficients(ficd_pool, denom_param)

        # Linearize ratio:  (Σ a_i x_i · numer_factor) / (Σ b_i x_i · denom_factor) ≥ rhs
        # ⇒  Σ (numer_factor · a_i − rhs · denom_factor · b_i) x_i  ≥  0
        coeffs = {
            code_i: numer_factor * a.get(code_i, 0.0)
                    - rhs_raw * denom_factor * b.get(code_i, 0.0)
            for code_i in set(a) | set(b)
        }
        out.append(
            LinearConstraint(
                spec_code=code,
                spec_label=f"{spec_label} [linearized ≥]",
                restriction_type="Minimum",
                rhs=0.0,
                coeffs=coeffs,
                constant=0.0,
                unit=unit,
                source=source,
            )
        )
    return out, warnings


def _apply_nutrient_limits(
    asns_active: pd.DataFrame,
    bounds: dict[str, Bound],
) -> tuple[pd.DataFrame, list[str]]:
    """Fold the nutrient inclusion-limit layer into the active ASNS rows.

    Where ASNS already states the same direction for a spec code, the tighter value
    replaces the target; where it does not, a row is appended. Either way the result
    is an ordinary ASNS-shaped frame, so the emission loop below stays unchanged.
    """
    df = asns_active.copy()
    df["source"] = "asns"
    if not bounds:
        return df, []

    warnings: list[str] = []
    present = {(r["code"], r["restriction_type"]): i for i, r in df.iterrows()}
    appended: list[dict] = []

    for code, bound in bounds.items():
        for rtype, value in (("Minimum", bound.minimum), ("Maximum", bound.maximum)):
            if value is None:
                continue

            idx = present.get((code, rtype))
            if idx is not None:
                current = float(df.at[idx, "value_numeric"])
                tighter = max(current, value) if rtype == "Minimum" else min(current, value)
                if tighter != current:
                    df.at[idx, "value_numeric"] = tighter
                    df.at[idx, "source"] = f"asns+{bound.source}"
                continue

            ficd_param, _ = crosswalk.resolve(code)
            if ficd_param is None:
                warnings.append(
                    f"[skip] nutrient limit for {code} has no FICD mapping; ignored."
                )
                continue
            if ficd_param == "__ratio__":
                warnings.append(
                    f"[skip] nutrient limit for {code} targets a ratio spec "
                    f"({crosswalk.spec_label(code)}); not supported by this layer."
                )
                continue

            appended.append({
                "code": code,
                "specification": crosswalk.spec_label(code),
                "unit": crosswalk.spec_unit(code),
                "restriction_type": rtype,
                "value_numeric": float(value),
                "source": bound.source,
            })

    if appended:
        df = pd.concat([df, pd.DataFrame(appended)], ignore_index=True)
    return df, warnings


# =========================================================================== #
# scoring                                                                      #
# =========================================================================== #


def score_constraints(
    constraints: list[LinearConstraint],
    fractions: dict[str, float],
) -> list[NutrientLine]:
    """Recompute Σ a_i x_i + constant per constraint and label it against the target.

    Shared by `/formulate` (scoring the LP solution) and `/validate-recipe` (scoring
    a recipe the caller supplies), so both answer the achieved-vs-target question
    through exactly the same arithmetic.
    """
    out: list[NutrientLine] = []
    for con in constraints:
        weights = [con.coeffs.get(code, 0.0) for code in fractions]
        achieved = sum(w * f for w, f in zip(weights, fractions.values())) + con.constant

        # Scale the tolerance to the row's own coefficients rather than to an absolute
        # epsilon; the dominant term budgets for quantization of the caller's
        # fractions. See IN_SPEC_INPUT_TOL for why.
        tol = (
            IN_SPEC_ABS_TOL
            + IN_SPEC_REL_TOL * abs(con.rhs)
            + IN_SPEC_INPUT_TOL * sum(abs(w) for w in weights)
        )

        in_spec = (
            (con.restriction_type == "Minimum" and achieved >= con.rhs - tol) or
            (con.restriction_type == "Maximum" and achieved <= con.rhs + tol) or
            (con.restriction_type == "Ratio"   and abs(achieved - con.rhs) <= tol)
        )
        out.append(NutrientLine(
            code=con.spec_code,
            spec_label=con.spec_label,
            restriction_type=con.restriction_type,
            target=con.rhs,
            achieved=round(achieved, 6),
            unit=con.unit,
            in_spec=bool(in_spec),
            source=con.source,
        ))
    return out


def _ingredient_coefficients(ficd_pool: pd.DataFrame, param: str) -> dict[str, float]:
    """Pull the FICD `param` value for each pooled ingredient. Missing → 0."""
    if param not in ficd_pool.columns:
        return {}
    series = ficd_pool[param].fillna(0.0)
    return {str(ix): float(v) for ix, v in series.items()}
