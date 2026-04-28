"""LP solver wrapper around PuLP + HiGHS.

Public entry point:  formulate(...)

Architectural hooks reserved for post-MVP extensions
(see Hua & Bureau 2012 — non-additive ingredient interactions, anti-nutrient
effects on digestibility, chance-constrained variability handling):

  * `_apply_interaction_corrections(coeffs, ingredients_chosen) -> coeffs`
        Empty in MVP. Future: pairwise correction terms applied to the LP
        coefficient matrix before solving (e.g., phytate × Ca → P digestibility).

  * `_apply_anti_nutrient_digestibility_penalties(constraints) -> constraints`
        Empty in MVP. Future: tannin / ANF concentrations downgrade digestible-
        protein/AA coefficients of accompanying ingredients.

  * `_solve_chance_constrained(...)`
        Empty in MVP. Future: stochastic-LP / robust-LP variant using ingredient
        nutrient CV distributions.
"""

from __future__ import annotations

from typing import Optional

import pulp

from .config.defaults import (
    DEFAULT_MAX_BINDER_INCLUSION,
    DEFAULT_MAX_FISHMEAL_COST_SHARE,
    DEFAULT_PREMIX_RATE,
    DEFAULT_PROCESSING_METHOD,
    DEFAULT_SOLVER,
    SOLUTION_FRACTION_TOL,
    SOLVER_TIME_LIMIT_SECONDS,
    WARN_INGREDIENT_INCLUSION_THRESHOLD,
)
from .constraint_builder import LinearConstraint, build_constraints
from .ingredient_pool import IngredientRecord, load_pool
from .models import (
    FormulateResponse,
    InfeasibilityReport,
    IngredientLine,
    NutrientLine,
)


# =========================================================================== #
# public                                                                       #
# =========================================================================== #


def formulate(
    species: str,
    stage: str,
    production_system: str,
    prices: dict[str, float],
    *,
    processing_method: str = DEFAULT_PROCESSING_METHOD,
    premix_enabled: bool = True,
    premix_rate: float = DEFAULT_PREMIX_RATE,
    max_fishmeal_cost_share: float = DEFAULT_MAX_FISHMEAL_COST_SHARE,
    max_binder_inclusion: float = DEFAULT_MAX_BINDER_INCLUSION,
    custom_premix_mask_codes: Optional[list[str]] = None,
) -> FormulateResponse:
    """Run the LP and return a structured response.

    On infeasibility we run a deletion-filter to extract an Irreducible
    Inconsistent Subset (IIS) of constraint codes and return that to the caller.
    """
    # ---------- 1. pool & coefficient assembly ------------------------------ #

    pool = load_pool(only_codes=set(prices.keys()))
    if not pool:
        return _err_response(
            species, stage, production_system, processing_method,
            premix_enabled, premix_rate,
            "No priced ingredients overlap with the configured pool.",
        )

    pool_by_code = {r.code: r for r in pool}
    ingr_codes = list(pool_by_code.keys())

    constraints, build_warnings = build_constraints(
        species=species,
        stage=stage,
        production_system=production_system,
        pool=pool,
        processing_method=processing_method,
        premix_enabled=premix_enabled,
        premix_rate=premix_rate,
        premix_mask_override=custom_premix_mask_codes,
    )

    # MVP placeholder hook (no-op). Wire in non-additive interaction corrections
    # here when empirical pairwise data becomes available (Hua & Bureau 2012).
    constraints = _apply_anti_nutrient_digestibility_penalties(constraints)

    # ---------- 2. build & solve the LP ------------------------------------- #

    prob, x = _build_pulp_problem(
        ingr_codes, pool_by_code, prices, constraints,
        premix_rate=premix_rate if premix_enabled else 0.0,
        max_fishmeal_cost_share=max_fishmeal_cost_share,
        max_binder_inclusion=max_binder_inclusion,
    )
    status = _solve(prob)

    # ---------- 3. infeasibility path --------------------------------------- #

    if status != pulp.LpStatusOptimal:
        iis = _deletion_filter_iis(
            ingr_codes, pool_by_code, prices, constraints,
            premix_rate=premix_rate if premix_enabled else 0.0,
            max_fishmeal_cost_share=max_fishmeal_cost_share,
            max_binder_inclusion=max_binder_inclusion,
        )
        return FormulateResponse(
            status="infeasible",
            species=species, stage=stage, production_system=production_system,
            processing_method=processing_method,
            warnings=build_warnings,
            infeasibility=InfeasibilityReport(
                iis_codes=[c.spec_code for c in iis],
                iis_explanations=[
                    f"{c.spec_code} ({c.spec_label}): {c.restriction_type} "
                    f"{c.rhs:g} {c.unit} cannot be met from the priced pool."
                    for c in iis
                ],
                suggestion=(
                    "Consider adding alternative ingredients (e.g., synthetic Lys/Met, "
                    "fish meal, soybean meal), increasing the premix rate, or relaxing "
                    "the production-system tier (General-LowCost ↔ General)."
                ),
            ),
            premix_enabled=premix_enabled,
            premix_rate=premix_rate,
        )

    # ---------- 4. extract & decorate solution ------------------------------ #

    solution_fractions = {c: float(v.value() or 0.0) for c, v in x.items()}
    cost = float(pulp.value(prob.objective))

    recipe = []
    warnings = list(build_warnings)
    for code, frac in solution_fractions.items():
        if frac < SOLUTION_FRACTION_TOL:
            continue
        rec = pool_by_code[code]
        recipe.append(IngredientLine(
            code=code,
            description=rec.description,
            inclusion_percent=round(frac * 100.0, 4),
            cost_per_kg=prices[code],
            cost_contribution=round(frac * prices[code], 6),
        ))
        if frac > WARN_INGREDIENT_INCLUSION_THRESHOLD:
            warnings.append(
                f"[soft] '{rec.description}' is included at "
                f"{frac*100:.1f}% — exceeds the {WARN_INGREDIENT_INCLUSION_THRESHOLD*100:.0f}% "
                f"single-ingredient guard threshold."
            )

    composition = _build_composition_report(
        constraints, solution_fractions, premix_enabled
    )

    recipe.sort(key=lambda r: -r.inclusion_percent)
    return FormulateResponse(
        status="optimal",
        species=species, stage=stage, production_system=production_system,
        processing_method=processing_method,
        cost_per_kg=round(cost, 6),
        recipe=recipe,
        composition=composition,
        warnings=warnings,
        premix_enabled=premix_enabled,
        premix_rate=premix_rate,
    )


# =========================================================================== #
# LP construction                                                             #
# =========================================================================== #


def _build_pulp_problem(
    ingr_codes: list[str],
    pool_by_code: dict[str, IngredientRecord],
    prices: dict[str, float],
    constraints: list[LinearConstraint],
    premix_rate: float,
    max_fishmeal_cost_share: float,
    max_binder_inclusion: float,
):
    prob = pulp.LpProblem("FASA_FeedFormulation", pulp.LpMinimize)

    x: dict[str, pulp.LpVariable] = {}
    for code in ingr_codes:
        ub = pool_by_code[code].max_inclusion if pool_by_code[code].max_inclusion is not None else 1.0
        x[code] = pulp.LpVariable(f"x_{code}", lowBound=0.0, upBound=ub, cat="Continuous")

    # objective
    prob += pulp.lpSum(prices[c] * x[c] for c in ingr_codes), "TotalCost_per_kg"

    # mass balance — note the premix takes a fixed slice
    prob += pulp.lpSum(x[c] for c in ingr_codes) == 1.0 - premix_rate, "MassBalance"

    # nutritional constraints
    for k, con in enumerate(constraints):
        lhs = pulp.lpSum(con.coeffs.get(c, 0.0) * x[c] for c in ingr_codes) + con.constant
        name = f"con_{k}_{con.spec_code}"
        if con.restriction_type == "Minimum":
            prob += lhs >= con.rhs, name
        elif con.restriction_type == "Maximum":
            prob += lhs <= con.rhs, name
        elif con.restriction_type == "Ratio":
            prob += lhs == con.rhs, name

    # binder cap
    binders = [c for c in ingr_codes if pool_by_code[c].is_binder]
    if binders and max_binder_inclusion < 1.0:
        prob += pulp.lpSum(x[c] for c in binders) <= max_binder_inclusion, "BinderCap"

    # fish-meal cost-share cap:
    #   Σ_{i ∈ FM} price_i * x_i  <=  share *  Σ_i price_i * x_i
    fishmeals = [c for c in ingr_codes if pool_by_code[c].is_fishmeal]
    if fishmeals and max_fishmeal_cost_share < 1.0:
        fm_cost = pulp.lpSum(prices[c] * x[c] for c in fishmeals)
        all_cost = pulp.lpSum(prices[c] * x[c] for c in ingr_codes)
        prob += fm_cost <= max_fishmeal_cost_share * all_cost, "FishMealCostShareCap"

    return prob, x


def _solve(prob: pulp.LpProblem) -> int:
    """Try in-process HiGHS first; fall back to bundled CBC. Time-limited."""
    # `HiGHS` = PuLP's in-process highspy binding (no separate binary needed).
    # `HiGHS_CMD` would need a `highs` executable on $PATH; we don't rely on that.
    try:
        solver = pulp.HiGHS(msg=False, timeLimit=SOLVER_TIME_LIMIT_SECONDS)
        prob.solve(solver)
    except Exception:
        prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=SOLVER_TIME_LIMIT_SECONDS))
    return prob.status


# =========================================================================== #
# IIS via deletion filter                                                     #
# =========================================================================== #


def _deletion_filter_iis(
    ingr_codes, pool_by_code, prices, constraints, *,
    premix_rate, max_fishmeal_cost_share, max_binder_inclusion,
) -> list[LinearConstraint]:
    """Greedy deletion-filter: returns a minimal infeasible subset.

    For each constraint we try removing it; if the LP without it is still
    infeasible, we drop it permanently. What remains is an IIS.
    O(|C| × solve_time); for ~30 constraints and HiGHS this is sub-second.
    """
    keep = list(constraints)

    def _is_infeasible(subset):
        prob, _ = _build_pulp_problem(
            ingr_codes, pool_by_code, prices, subset,
            premix_rate=premix_rate,
            max_fishmeal_cost_share=max_fishmeal_cost_share,
            max_binder_inclusion=max_binder_inclusion,
        )
        st = _solve(prob)
        return st != pulp.LpStatusOptimal

    if not _is_infeasible(keep):
        # the original solve returned non-optimal but the LP is feasible now?
        # could happen with marginal numerical issues; return empty IIS
        return []

    i = 0
    while i < len(keep):
        candidate = keep[:i] + keep[i + 1:]
        if _is_infeasible(candidate):
            keep = candidate
        else:
            i += 1
    return keep


# =========================================================================== #
# composition report                                                          #
# =========================================================================== #


def _build_composition_report(
    constraints: list[LinearConstraint],
    fractions: dict[str, float],
    premix_enabled: bool,
) -> list[NutrientLine]:
    """For each emitted constraint, recompute Σ a_i x_i + constant and label it."""
    out: list[NutrientLine] = []
    for con in constraints:
        achieved = sum(con.coeffs.get(c, 0.0) * fractions.get(c, 0.0)
                       for c in fractions) + con.constant
        in_spec = (
            (con.restriction_type == "Minimum" and achieved >= con.rhs - 1e-6) or
            (con.restriction_type == "Maximum" and achieved <= con.rhs + 1e-6) or
            (con.restriction_type == "Ratio"   and abs(achieved - con.rhs) < 1e-6)
        )
        out.append(NutrientLine(
            code=con.spec_code,
            spec_label=con.spec_label,
            restriction_type=con.restriction_type,
            target=con.rhs,
            achieved=round(achieved, 6),
            unit=con.unit,
            in_spec=bool(in_spec),
        ))
    return out


# =========================================================================== #
# post-MVP hooks (no-ops for now)                                             #
# =========================================================================== #


def _apply_interaction_corrections(coeffs: dict, chosen: set) -> dict:
    """Reserved for non-additive ingredient interactions (Hua & Bureau 2012).

    Will, in v2, mutate per-ingredient nutrient coefficients based on the
    presence of other ingredients (e.g., phytate × Ca → reduced P availability).
    """
    return coeffs                                                              # pragma: no cover


def _apply_anti_nutrient_digestibility_penalties(
    constraints: list[LinearConstraint],
) -> list[LinearConstraint]:
    """Reserved for anti-nutrient → digestibility penalty layer.

    Will, in v2, downgrade digestible-protein and digestible-AA coefficients
    of ingredients that co-occur with high tannin / ANF / lectin content.
    """
    return constraints


def _err_response(species, stage, system, method, premix_enabled, premix_rate, msg):
    return FormulateResponse(
        status="error",
        species=species, stage=stage, production_system=system,
        processing_method=method, warnings=[msg],
        premix_enabled=premix_enabled, premix_rate=premix_rate,
    )
