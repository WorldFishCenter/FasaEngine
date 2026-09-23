"""Min/max inclusion layer: commercial-practice bounds on nutrients and ingredients.

ASNS states what the fish requires. This layer states what a feed mill can actually
formulate and process — the knowledge a formulator applies by hand on top of a
composition table (fibre ceilings, per-ingredient palatability/extrudability caps,
minimum carrier levels). Without it a least-cost LP happily returns diets that meet
every nutrient target yet cannot be extruded or will not grow fish.

Two config files, both shipped with a documented header and no data rows yet (so the
engine behaves exactly as before until the columns are filled):

  * `config/nutrient_limits.csv`    bounds on dietary nutrient levels, keyed by ASNS code
  * `config/ingredient_limits.csv`  bounds on single-ingredient inclusion, keyed by FICD code

Both share the same scoping convention: the `species`, `production_system`,
`stage_weight` and `processing_method` columns are filters, blank meaning "applies to
all". `stage_weight` matches as a substring of the ASNS stage label (the convention
`crosswalk.premix_mask_codes` already uses for its stage overrides). When several rows
match, the most specific row wins; ties resolve toward the tighter bound, and each
direction resolves independently.

Precedence per code: a request-supplied limit replaces the CSV-resolved one wholesale
(the `custom_premix_mask_codes` precedent), and for ingredients the pool CSV's generated
`max_inclusion` is the fallback when neither layer names the ingredient.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd

from . import crosswalk
from .config.defaults import DEFAULT_PROCESSING_METHOD
from .ingredient_pool import IngredientRecord

NUTRIENT_LIMITS_PATH = Path(__file__).parent / "config" / "nutrient_limits.csv"
INGREDIENT_LIMITS_PATH = Path(__file__).parent / "config" / "ingredient_limits.csv"

# Scope columns shared by both files; blank cell ⇒ no filtering on that dimension.
SCOPE_COLUMNS = ("species", "production_system", "stage_weight", "processing_method")


@dataclass(frozen=True)
class Bound:
    """A resolved min/max pair for one spec or ingredient code.

    `source` labels where the pair came from — "limits" (CSV), "request" (per-call
    override), or "pool" (the generated pool `max_inclusion` fallback) — and is
    echoed through to the response so a client can explain a binding bound.
    """

    minimum: Optional[float] = None
    maximum: Optional[float] = None
    source: str = "limits"


@dataclass(frozen=True)
class LimitScope:
    """What a limit row is matched against — one request's formulation context.

    Mirrors `SCOPE_COLUMNS`. Any field may be left unset: a row whose matching column
    is blank applies regardless, so a caller that knows only the processing method
    still picks up the blanket rows.
    """

    species: Optional[str] = None
    stage: Optional[str] = None
    production_system: Optional[str] = None
    processing_method: str = DEFAULT_PROCESSING_METHOD


# =========================================================================== #
# public                                                                       #
# =========================================================================== #


def from_request(limits: Optional[dict]) -> dict[str, Bound]:
    """Adapt a request's ``{code: {min, max}}`` mapping into request-sourced bounds.

    Accepts the pydantic limit models or plain dicts, so the API layer stays a
    pass-through and direct core callers can hand in literals.
    """
    out: dict[str, Bound] = {}
    for code, limit in (limits or {}).items():
        pair = limit if isinstance(limit, dict) else {"min": limit.min, "max": limit.max}
        out[str(code)] = Bound(
            minimum=pair.get("min"), maximum=pair.get("max"), source="request"
        )
    return out


def nutrient_bounds(
    scope: LimitScope,
    overrides: Optional[dict[str, Bound]] = None,
) -> dict[str, Bound]:
    """Resolve the nutrient-level bounds active for one request, keyed by ASNS code."""
    resolved = _resolve(nutrient_limit_rows(), scope)
    resolved.update(overrides or {})
    return resolved


def ingredient_bounds(
    scope: LimitScope,
    pool: Iterable[IngredientRecord],
    overrides: Optional[dict[str, Bound]] = None,
) -> dict[str, Bound]:
    """Resolve the per-ingredient inclusion bounds active for one request.

    Falls back to the pool CSV's generated `max_inclusion` for ingredients that
    neither the limits file nor the request names.
    """
    resolved = _resolve(ingredient_limit_rows(), scope)
    resolved.update(overrides or {})
    for rec in pool:
        if rec.code not in resolved and rec.max_inclusion is not None:
            resolved[rec.code] = Bound(maximum=rec.max_inclusion, source="pool")
    return resolved


def box(bound: Optional[Bound]) -> tuple[float, float]:
    """The mass-fraction box a bound implies; an unset side opens to the full [0, 1].

    Shared by the LP's variable bounds and the pre-solve conflict check so the two
    cannot disagree about what a missing minimum or maximum means.
    """
    if bound is None:
        return 0.0, 1.0
    return (
        0.0 if bound.minimum is None else bound.minimum,
        1.0 if bound.maximum is None else bound.maximum,
    )


def zero_cap_warnings(
    bounds: dict[str, Bound],
    pool_by_code: dict[str, IngredientRecord],
) -> list[str]:
    """Flag priced ingredients a 0 % ceiling removed from consideration.

    Without this the ingredient simply vanishes from the response and the miller
    cannot tell a "too expensive" exclusion from a "never recommend this" one.
    """
    return [
        f"[limit] '{pool_by_code[code].description}' is priced but excluded by a "
        f"0% maximum inclusion limit ({bound.source})."
        for code, bound in sorted(bounds.items())
        if bound.maximum == 0.0 and code in pool_by_code
    ]


def bound_conflicts(
    bounds: dict[str, Bound],
    codes: Iterable[str],
    target_mass: float,
) -> list[str]:
    """Report inclusion bounds that cannot add up to the required feed mass.

    These are decision-variable bounds, not rows in the constraint list, so the
    deletion-filter IIS cannot see them: it would burn a solve per nutrient
    constraint and then blame the nutrients. Checking the box directly turns the
    single most likely misconfiguration into a message the caller can act on.
    """
    boxes = [box(bounds.get(c)) for c in codes]
    floor = sum(lo for lo, _ in boxes)
    ceiling = sum(hi for _, hi in boxes)

    out: list[str] = []
    if floor > target_mass + 1e-9:
        out.append(
            f"Minimum inclusion limits on the priced ingredients sum to "
            f"{floor * 100:.2f}%, above the {target_mass * 100:.2f}% of feed mass left "
            f"for ingredients. Lower a minimum or reduce the premix rate."
        )
    if ceiling < target_mass - 1e-9:
        out.append(
            f"Maximum inclusion limits on the priced ingredients sum to "
            f"{ceiling * 100:.2f}%, below the {target_mass * 100:.2f}% of feed mass that "
            f"must be filled. Price more ingredients or raise a maximum."
        )
    return out


# =========================================================================== #
# loading                                                                      #
# =========================================================================== #


@lru_cache(maxsize=1)
def nutrient_limit_rows() -> tuple[dict, ...]:
    """Parsed nutrient-limit rows. Raises on an unmappable code or a unit mismatch."""
    rows = _load(NUTRIENT_LIMITS_PATH, "spec_code", "min", "max")
    for row in rows:
        code = row["key"]
        if crosswalk.resolve(code)[0] is None:
            raise ValueError(
                f"nutrient_limits.csv: spec_code {code!r} has no crosswalk entry."
            )
        declared = (row["raw"].get("unit") or "").strip()
        expected = crosswalk.spec_unit(code)
        if declared and declared != expected:
            raise ValueError(
                f"nutrient_limits.csv: spec_code {code!r} declares unit {declared!r} "
                f"but the crosswalk's ASNS unit is {expected!r}."
            )
    return rows


@lru_cache(maxsize=1)
def ingredient_limit_rows() -> tuple[dict, ...]:
    """Parsed ingredient-limit rows. Raises on a bound outside [0, 1]."""
    rows = _load(INGREDIENT_LIMITS_PATH, "code", "min_inclusion", "max_inclusion")
    for row in rows:
        for field in ("min", "max"):
            value = row[field]
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"ingredient_limits.csv: code {row['key']!r} has "
                    f"{field}_inclusion {value!r} outside [0, 1] (mass fraction)."
                )
    return rows


def _load(path: Path, key_col: str, min_col: str, max_col: str) -> tuple[dict, ...]:
    """Parse one limits CSV into normalized rows (cached by the callers above).

    Rows carry a `specificity` count — how many scope columns are filled — which
    `_resolve` uses to let a stage-specific row beat a blanket one.
    """
    # No existence guard: the files are committed config, so a missing one is a
    # deployment defect that should surface (like the pool CSV and crosswalk.json),
    # not silently disable the layer. `/ready` calls the loaders for exactly this.
    raw = pd.read_csv(path, comment="#", dtype=str, keep_default_na=False)
    missing = {key_col, min_col, max_col, *SCOPE_COLUMNS} - set(raw.columns)
    if missing:
        raise ValueError(f"{path.name}: missing column(s) {sorted(missing)}.")

    out: list[dict] = []
    for _, r in raw.iterrows():
        key = str(r[key_col]).strip()
        if not key:
            continue
        lo, hi = _num(r[min_col]), _num(r[max_col])
        if lo is None and hi is None:
            continue
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"{path.name}: {key!r} has minimum {lo} above maximum {hi}.")
        scope = {c: str(r[c]).strip() for c in SCOPE_COLUMNS}
        out.append({
            "key": key,
            "min": lo,
            "max": hi,
            "scope": scope,
            "specificity": sum(1 for v in scope.values() if v),
            "raw": {c: str(v).strip() for c, v in r.items()},
        })
    return tuple(out)


def _num(cell: object) -> Optional[float]:
    text = str(cell).strip()
    return float(text) if text else None


# =========================================================================== #
# resolution                                                                   #
# =========================================================================== #


def _resolve(rows: tuple[dict, ...], scope: LimitScope) -> dict[str, Bound]:
    by_key: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if _in_scope(row["scope"], scope):
            by_key[row["key"]].append(row)
    return {
        key: Bound(
            minimum=_tightest(matches, "min", max),
            maximum=_tightest(matches, "max", min),
        )
        for key, matches in by_key.items()
    }


def _in_scope(row: dict[str, str], scope: LimitScope) -> bool:
    # stage matches as a substring so "Starter" covers "< 5g (Starter)"
    return (
        row["species"] in ("", scope.species)
        and row["production_system"] in ("", scope.production_system)
        and (not row["stage_weight"] or row["stage_weight"] in (scope.stage or ""))
        and row["processing_method"] in ("", scope.processing_method)
    )


def _tightest(
    rows: list[dict],
    field: str,
    pick: Callable[[Iterable[float]], float],
) -> Optional[float]:
    """Most specific rows win; ties resolve toward the tighter bound via `pick`."""
    candidates = [r for r in rows if r[field] is not None]
    if not candidates:
        return None
    top = max(r["specificity"] for r in candidates)
    return pick(r[field] for r in candidates if r["specificity"] == top)
