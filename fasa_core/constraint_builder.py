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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from . import crosswalk
from .data_loader import get_active_constraints
from .ingredient_pool import IngredientRecord, attach_ficd_rows


@dataclass
class LinearConstraint:
    spec_code: str
    spec_label: str
    restriction_type: str   # "Minimum" | "Maximum" | "Ratio" (linearized)
    rhs: float
    coeffs: dict[str, float]
    constant: float
    unit: str

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
) -> tuple[list[LinearConstraint], list[str]]:
    """Materialize the active constraint set.

    Returns
    -------
    constraints : list[LinearConstraint]
    warnings    : list[str] — non-fatal notes (unmappable specs, etc.)
    """
    asns_active = get_active_constraints(species, stage, production_system)
    ficd_pool = attach_ficd_rows(pool).set_index("code")

    mask = (
        crosswalk.premix_mask_codes(stage, premix_mask_override)
        if premix_enabled
        else set()
    )

    out: list[LinearConstraint] = []
    warnings: list[str] = []

    for _, row in asns_active.iterrows():
        code = row["code"]
        rtype = row["restriction_type"]

        # --- masking rules -------------------------------------------------- #
        if code in mask and not code.startswith("TX"):
            # vit/trace-mineral satisfied by premix; skip silently
            continue
        # toxins are NEVER masked, even via override
        # (we've already short-circuited above for non-TX masked codes)

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
            )
        )
    return out, warnings


def _ingredient_coefficients(ficd_pool: pd.DataFrame, param: str) -> dict[str, float]:
    """Pull the FICD `param` value for each pooled ingredient. Missing → 0."""
    if param not in ficd_pool.columns:
        return {}
    series = ficd_pool[param].fillna(0.0)
    return {str(ix): float(v) for ix, v in series.items()}
