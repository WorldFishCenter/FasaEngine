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

The premix is applied here too. Its composition (premix_composition.json) is
credited through `constant` — `amount * premix_rate` per kg of feed — so its
vitamins and trace minerals are checked like any other nutrient. The premix
mask covers only what the premix lacks: masked spec codes never make it into the
output. Toxin (TX*) maximums are NEVER masked, even if premix_mask.json lists
them — the premix doesn't add toxins, and the safety ceilings on
aflatoxin/gossypol/etc. are non-negotiable per the FASA brief.

The FASA team's changes to the ASNS rules come first (`_apply_fasa_rules`; the values
live in config/defaults.py): some rules are dropped for every feed, catfish crude protein
follows the FASA requirements table, crude protein and lipid get a maximum, and a saponin
maximum is added. A rule this step created or changed reports source "fasa".

The nutrient inclusion-limit layer (`inclusion_limits`) is folded into the ASNS
row set before emission, so the limits inherit the whole existing pipeline —
crosswalk resolution, unit conversion, coefficients, the composition report and
the deletion-filter IIS. A row the layer created or tightened is exempt from the
premix mask — an explicit operator bound always binds — while a plain ASNS row
for the same code stays masked, so capping choline does not also resurrect the
choline minimum the FASA team dropped.

Group limits (config/group_limits.csv) are emitted last: one row per bound on the sum of
the priced members' inclusion, in % of feed, under the group's name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from . import crosswalk
from .config.defaults import (
    DROPPED_RULES,
    FASA_REQUIREMENTS,
    IN_SPEC_ABS_TOL,
    IN_SPEC_INPUT_TOL,
    IN_SPEC_REL_TOL,
    PROTEIN_LIPID_RANGE,
    SAPONIN_RULE,
)
from .data_loader import get_active_constraints
from .inclusion_limits import Bound, LimitScope, group_bounds
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
    source: str = "asns"    # "asns" | "fasa" | "<that>+<layer>" | "<layer>"; see inclusion_limits

    def __repr__(self) -> str:                                                # pragma: no cover
        op = {"Minimum": ">=", "Maximum": "<=", "Ratio": "="}[self.restriction_type]
        return f"<{self.spec_code} {self.spec_label!r}: ... {op} {self.rhs:g} {self.unit}>"


def build_constraints(
    species: str,
    stage: str,
    production_system: str,
    pool: list[IngredientRecord],
    *,
    premix_rate: float,
    processing_method: str = "pelleted",
    nutrient_limits: Optional[dict[str, Bound]] = None,
) -> tuple[list[LinearConstraint], list[str]]:
    """Materialize the active constraint set.

    Returns
    -------
    constraints : list[LinearConstraint]
    warnings    : list[str] — non-fatal notes (unmappable specs, etc.)
    """
    asns_active = _apply_fasa_rules(
        get_active_constraints(species, stage, production_system), species, stage
    )
    asns_active, warnings = _apply_nutrient_limits(asns_active, nutrient_limits or {})
    ficd_pool = attach_ficd_rows(pool).set_index("code")

    # every feed carries the premix: its composition is credited below; the codes in
    # premix_mask.json are skipped
    premix = crosswalk.premix_composition()
    mask = crosswalk.premix_mask_codes(stage)

    out: list[LinearConstraint] = []

    for _, row in asns_active.iterrows():
        code = row["code"]
        rtype = row["restriction_type"]
        source = row["source"]

        if source == "asns" and crosswalk.duplicate_of(code):
            # same requirement as another code in another unit; that code binds
            continue

        # --- masking rules -------------------------------------------------- #
        if code in mask and not code.startswith("TX") and source == "asns":
            # in premix_mask.json: not checked; skip silently
            continue
        # toxins are NEVER masked. Neither is a row the limit layer
        # created or tightened — but a plain ASNS row for the same code stays masked,
        # so bounding choline's maximum never resurrects the dropped minimum.

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
            # the premix's own content of this nutrient per kg of feed (0 for most
            # specs), converted like the target into FICD units
            constant = premix.get(code, 0.0) * premix_rate * float(factor)

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

    scope = LimitScope(species, stage, production_system, processing_method)
    groups, group_warnings = _group_constraints(pool, group_bounds(scope))
    return out + groups, warnings + group_warnings


def _apply_fasa_rules(asns_active: pd.DataFrame, species: str, stage: str) -> pd.DataFrame:
    """Apply the FASA team's changes to the ASNS rules (decisions of 5 November 2026).

    Dropped rules leave every feed; a rule created or changed here reports source "fasa".
    """
    df = asns_active[~asns_active["code"].isin(DROPPED_RULES)].copy()
    df["source"] = "asns"

    for code, value in FASA_REQUIREMENTS.get((species, stage), {}).items():
        df.loc[df["code"] == code, ["value_numeric", "source"]] = [value, "fasa"]

    added = []
    for code, width in PROTEIN_LIPID_RANGE.items():
        for idx in df.index[(df["code"] == code) & (df["restriction_type"] == "Minimum")]:
            minimum = float(df.at[idx, "value_numeric"])
            added.append({**df.loc[idx].to_dict(), "restriction_type": "Maximum",
                          "value_numeric": round(minimum + width, 6), "source": "fasa"})
            df.loc[idx, ["value_numeric", "source"]] = [round(minimum - width, 6), "fasa"]

    soyasaponin, saponin = SAPONIN_RULE
    for idx in df.index[df["code"] == soyasaponin]:
        added.append({**df.loc[idx].to_dict(), "code": saponin, "source": "fasa"})

    return pd.concat([df, pd.DataFrame(added)], ignore_index=True) if added else df


def _group_constraints(
    pool: list[IngredientRecord],
    bounds: dict[str, Bound],
) -> tuple[list[LinearConstraint], list[str]]:
    """One row per group bound: the priced members' inclusion summed, in % of feed."""
    out: list[LinearConstraint] = []
    warnings: list[str] = []
    for group, bound in sorted(bounds.items()):
        members = {rec.code: 100.0 for rec in pool if rec.group == group}
        if not members:
            if bound.minimum:
                warnings.append(
                    f"[limit] the {bound.minimum * 100:g}% minimum on '{group}' was not "
                    f"applied: none of its ingredients is priced."
                )
            continue
        for rtype, value in (("Minimum", bound.minimum), ("Maximum", bound.maximum)):
            if value is not None:
                out.append(LinearConstraint(
                    spec_code=group,
                    spec_label=f"{group} (ingredients together)",
                    restriction_type=rtype,
                    rhs=value * 100.0,
                    coeffs=members,
                    constant=0.0,
                    unit="% of feed",
                    source=bound.source,
                ))
    return out, warnings


def _apply_nutrient_limits(
    asns_active: pd.DataFrame,
    bounds: dict[str, Bound],
) -> tuple[pd.DataFrame, list[str]]:
    """Fold the nutrient inclusion-limit layer into the active ASNS rows.

    Runs after `_apply_fasa_rules`, which sets each row's `source`. Where the frame
    already states the same direction for a spec code, the tighter value replaces the
    target and `+limits` (or `+request`) is appended to its source; where it does not, a
    row is appended. The emission loop below reads the result unchanged.
    """
    df = asns_active.copy()
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
                    df.at[idx, "source"] = f"{df.at[idx, 'source']}+{bound.source}"
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
