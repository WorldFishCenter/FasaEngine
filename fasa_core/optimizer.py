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

import logging
import time
from typing import Optional

import pulp

from . import inclusion_limits
from .config.defaults import (
    DEFAULT_MAX_BINDER_INCLUSION,
    DEFAULT_MAX_FISHMEAL_COST_SHARE,
    DEFAULT_PREMIX_RATE,
    DEFAULT_PROCESSING_METHOD,
    DEFAULT_SOLVER,
    SOLUTION_FRACTION_TOL,
    SOLVER_TIME_LIMIT_SECONDS,
    WARN_INGREDIENT_INCLUSION_THRESHOLD,
    as_percent,
    normalize_country,
)
from .constraint_builder import LinearConstraint, build_constraints, score_constraints
from .inclusion_limits import Bound, LimitScope
from .ingredient_pool import IngredientRecord, load_pool
from .models import (
    FormulateResponse,
    InfeasibilityReport,
    IngredientLine,
)

LOGGER = logging.getLogger("fasa_core.optimizer")


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
    max_fishmeal_cost_share: Optional[float] = DEFAULT_MAX_FISHMEAL_COST_SHARE,
    max_binder_inclusion: Optional[float] = DEFAULT_MAX_BINDER_INCLUSION,
    custom_premix_mask_codes: Optional[list[str]] = None,
    batch_size_kg: Optional[float] = None,
    country: Optional[str] = None,
    nutrient_limits: Optional[dict] = None,
    ingredient_limits: Optional[dict] = None,
) -> FormulateResponse:
    """Run the LP and return a structured response.

    On infeasibility we run a deletion-filter to extract an Irreducible
    Inconsistent Subset (IIS) of constraint codes and return that to the caller.
    """
    # Normalize the (advisory) country tag here so the core is self-contained:
    # direct callers get the same case/whitespace handling as the API layer, and
    # `locally_available` is compared against the pool's upper-cased ISO-2 tags.
    country = normalize_country(country)

    # ---------- 1. pool & coefficient assembly ------------------------------ #

    pool = load_pool(only_codes=set(prices.keys()))
    if not pool:
        return _err_response(
            species, stage, production_system, processing_method,
            premix_enabled, premix_rate,
            max_fishmeal_cost_share, max_binder_inclusion,
            batch_size_kg, country,
            "No priced ingredients overlap with the configured pool.",
        )

    pool_by_code = {r.code: r for r in pool}
    ingr_codes = list(pool_by_code.keys())

    # The min/max inclusion layer: nutrient bounds join the ASNS constraint set,
    # ingredient bounds become the decision variables' box.
    scope = LimitScope(
        species=species,
        stage=stage,
        production_system=production_system,
        processing_method=processing_method,
    )
    nutrient_box = inclusion_limits.nutrient_bounds(
        scope, overrides=inclusion_limits.from_request(nutrient_limits)
    )
    ingredient_box = inclusion_limits.ingredient_bounds(
        scope, pool, overrides=inclusion_limits.from_request(ingredient_limits)
    )

    constraints, build_warnings = build_constraints(
        species=species,
        stage=stage,
        production_system=production_system,
        pool=pool,
        processing_method=processing_method,
        premix_enabled=premix_enabled,
        premix_rate=premix_rate,
        premix_mask_override=custom_premix_mask_codes,
        nutrient_limits=nutrient_box,
    )
    build_warnings += inclusion_limits.zero_cap_warnings(ingredient_box, pool_by_code)

    # MVP placeholder hook (no-op). Wire in non-additive interaction corrections
    # here when empirical pairwise data becomes available (Hua & Bureau 2012).
    constraints = _apply_anti_nutrient_digestibility_penalties(constraints)

    target_mass = 1.0 - (premix_rate if premix_enabled else 0.0)
    solver_kwargs = dict(
        premix_rate=premix_rate if premix_enabled else 0.0,
        max_fishmeal_cost_share=max_fishmeal_cost_share,
        max_binder_inclusion=max_binder_inclusion,
        bounds=ingredient_box,
    )

    def _infeasible(report: InfeasibilityReport) -> FormulateResponse:
        return FormulateResponse(
            status="infeasible",
            species=species, stage=stage, production_system=production_system,
            processing_method=processing_method,
            country=country,
            warnings=build_warnings,
            infeasibility=report,
            premix_enabled=premix_enabled,
            premix_rate=premix_rate,
            max_fishmeal_cost_share=max_fishmeal_cost_share,
            max_binder_inclusion=max_binder_inclusion,
            batch_size_kg=batch_size_kg,
        )

    # ---------- 2. bound-feasibility pre-check ------------------------------ #
    # Inclusion bounds that cannot sum to the feed mass make every subset of the
    # constraint list infeasible, so the deletion filter would spend a solve per
    # nutrient and then blame the nutrients. Report the real cause instead.

    conflicts = inclusion_limits.bound_conflicts(ingredient_box, ingr_codes, target_mass)
    if conflicts:
        return _infeasible(InfeasibilityReport(
            iis_codes=[],
            iis_explanations=[],
            bound_conflicts=conflicts,
            suggestion=(
                "Adjust the ingredient inclusion limits so their range spans the "
                "required feed mass, or price additional ingredients."
            ),
        ))

    # ---------- 3. build & solve the LP ------------------------------------- #

    prob, x = _build_pulp_problem(
        ingr_codes, pool_by_code, prices, constraints, **solver_kwargs
    )
    status = _solve(prob)

    # ---------- 4. infeasibility path --------------------------------------- #

    if status != pulp.LpStatusOptimal:
        iis = _deletion_filter_iis(
            ingr_codes, pool_by_code, prices, constraints, **solver_kwargs
        )
        return _infeasible(InfeasibilityReport(
            iis_codes=[c.spec_code for c in iis],
            iis_explanations=[
                f"{c.spec_code} ({c.spec_label}): {c.restriction_type} "
                f"{c.rhs:g} {c.unit} cannot be met from the priced pool "
                f"[{c.source}]."
                for c in iis
            ],
            suggestion=(
                "Consider adding alternative ingredients (e.g., synthetic Lys/Met, "
                "fish meal, soybean meal), increasing the premix rate, relaxing an "
                "inclusion limit, or relaxing the production-system tier "
                "(General-LowCost ↔ General)."
            ),
        ))

    # ---------- 5. extract & decorate solution ------------------------------ #

    solution_fractions = {c: float(v.value() or 0.0) for c, v in x.items()}
    cost = float(pulp.value(prob.objective))

    recipe = []
    warnings = list(build_warnings)
    for code, frac in solution_fractions.items():
        if frac < SOLUTION_FRACTION_TOL:
            continue
        rec = pool_by_code[code]
        qty_kg = round(frac * batch_size_kg, 3) if batch_size_kg is not None else None
        bound = ingredient_box.get(code)
        recipe.append(IngredientLine(
            code=code,
            description=rec.description,
            inclusion_percent=as_percent(frac),
            cost_per_kg=prices[code],
            cost_contribution=round(frac * prices[code], 6),
            quantity_kg=qty_kg,
            locally_available=(country in rec.countries) if country is not None else None,
            min_inclusion_percent=as_percent(bound.minimum) if bound else None,
            max_inclusion_percent=as_percent(bound.maximum) if bound else None,
            limit_source=bound.source if bound else None,
        ))
        if frac > WARN_INGREDIENT_INCLUSION_THRESHOLD:
            warnings.append(
                f"[soft] '{rec.description}' is included at "
                f"{frac*100:.1f}% — exceeds the {WARN_INGREDIENT_INCLUSION_THRESHOLD*100:.0f}% "
                f"single-ingredient guard threshold."
            )

    composition = score_constraints(constraints, solution_fractions)

    recipe.sort(key=lambda r: -r.inclusion_percent)

    total_cost = round(cost * batch_size_kg, 2) if batch_size_kg is not None else None
    premix_qty_kg = (
        round(batch_size_kg * premix_rate, 3)
        if batch_size_kg is not None and premix_enabled
        else None
    )

    return FormulateResponse(
        status="optimal",
        species=species, stage=stage, production_system=production_system,
        processing_method=processing_method,
        country=country,
        cost_per_kg=round(cost, 6),
        recipe=recipe,
        composition=composition,
        warnings=warnings,
        premix_enabled=premix_enabled,
        premix_rate=premix_rate,
        max_fishmeal_cost_share=max_fishmeal_cost_share,
        max_binder_inclusion=max_binder_inclusion,
        batch_size_kg=batch_size_kg,
        premix_quantity_kg=premix_qty_kg,
        total_cost=total_cost,
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
    max_fishmeal_cost_share: Optional[float],
    max_binder_inclusion: Optional[float],
    bounds: dict[str, Bound],
):
    prob = pulp.LpProblem("FASA_FeedFormulation", pulp.LpMinimize)

    # `bounds` is the resolved inclusion-limit box (it already folds in the pool
    # CSV's generated max_inclusion); unbounded ingredients get the full [0, 1].
    x: dict[str, pulp.LpVariable] = {}
    for code in ingr_codes:
        lb, ub = inclusion_limits.box(bounds.get(code))
        x[code] = pulp.LpVariable(f"x_{code}", lowBound=lb, upBound=ub, cat="Continuous")

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

    # binder cap — opt-in; skipped when None or 1.0
    binders = [c for c in ingr_codes if pool_by_code[c].is_binder]
    if binders and max_binder_inclusion is not None and max_binder_inclusion < 1.0:
        prob += pulp.lpSum(x[c] for c in binders) <= max_binder_inclusion, "BinderCap"

    # fish-meal cost-share cap — opt-in; skipped when None or 1.0
    #   Σ_{i ∈ FM} price_i * x_i  <=  share *  Σ_i price_i * x_i
    fishmeals = [c for c in ingr_codes if pool_by_code[c].is_fishmeal]
    if fishmeals and max_fishmeal_cost_share is not None and max_fishmeal_cost_share < 1.0:
        fm_cost = pulp.lpSum(prices[c] * x[c] for c in fishmeals)
        all_cost = pulp.lpSum(prices[c] * x[c] for c in ingr_codes)
        prob += fm_cost <= max_fishmeal_cost_share * all_cost, "FishMealCostShareCap"

    return prob, x


def _solve(prob: pulp.LpProblem) -> int:
    """Try in-process HiGHS first; fall back to bundled CBC. Time-limited."""
    started_at = time.perf_counter()
    backend = DEFAULT_SOLVER
    # `HiGHS` = PuLP's in-process highspy binding (no separate binary needed).
    # `HiGHS_CMD` would need a `highs` executable on $PATH; we don't rely on that.
    try:
        solver = pulp.HiGHS(msg=False, timeLimit=SOLVER_TIME_LIMIT_SECONDS)
        prob.solve(solver)
    except Exception:
        backend = "CBC"
        prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=SOLVER_TIME_LIMIT_SECONDS))
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    LOGGER.info(
        "solver.result backend=%s status=%s elapsed_ms=%.2f",
        backend,
        pulp.LpStatus.get(prob.status, prob.status),
        elapsed_ms,
    )
    return prob.status


# =========================================================================== #
# IIS via deletion filter                                                     #
# =========================================================================== #


def _deletion_filter_iis(
    ingr_codes, pool_by_code, prices, constraints, *,
    premix_rate, max_fishmeal_cost_share, max_binder_inclusion, bounds,
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
            bounds=bounds,
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


def _err_response(
    species, stage, system, method,
    premix_enabled, premix_rate,
    max_fishmeal_cost_share, max_binder_inclusion,
    batch_size_kg, country,
    msg,
):
    return FormulateResponse(
        status="error",
        species=species, stage=stage, production_system=system,
        processing_method=method, country=country, warnings=[msg],
        premix_enabled=premix_enabled, premix_rate=premix_rate,
        max_fishmeal_cost_share=max_fishmeal_cost_share,
        max_binder_inclusion=max_binder_inclusion,
        batch_size_kg=batch_size_kg,
    )
