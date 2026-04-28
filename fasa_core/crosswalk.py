"""Spec-code → FICD parameter resolver, with unit conversions.

Reads `config/crosswalk.json` once and exposes:

  resolve(spec_code, processing_method="pelleted")
    → (ficd_param: str, unit_factor: float)         for non-ratio specs
    → ("__ratio__", {"numer": ..., "denom": ...})   for DP/DE-style ratios
    → (None, None)                                  if the spec is unmappable

  premix_mask_codes()  → set[str] of ASNS codes masked by default
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Tuple

CROSSWALK_PATH = Path(__file__).parent / "config" / "crosswalk.json"
PREMIX_PATH    = Path(__file__).parent / "config" / "premix_mask.json"


@lru_cache(maxsize=1)
def _crosswalk_raw() -> dict[str, Any]:
    return json.loads(CROSSWALK_PATH.read_text())


@lru_cache(maxsize=1)
def _premix_raw() -> dict[str, Any]:
    return json.loads(PREMIX_PATH.read_text())


def resolve(spec_code: str, processing_method: str = "pelleted") -> Tuple[Any, Any]:
    """Map an ASNS spec code to a FICD parameter and its unit conversion factor.

    Returns
    -------
    (ficd_param, unit_factor)
        ficd_param  : str | None | "__ratio__"
        unit_factor : float (multiplier applied to the ASNS spec *target value*
                      so it lives in FICD's native units; coefficients come from
                      FICD unchanged) — or a dict for ratio specs.
    """
    cw = _crosswalk_raw()
    if spec_code not in cw or spec_code.startswith("_"):
        return (None, None)
    entry = cw[spec_code]

    # ratio specs (DP/DE etc.)
    if "ratio" in entry:
        return ("__ratio__", entry["ratio"])

    factor = float(entry.get("unit_factor", 1.0))

    # processing-dependent specs (energy)
    if processing_method == "extruded" and "ficd_param_extruded" in entry:
        return (entry["ficd_param_extruded"], factor)
    if "ficd_param_pelleted" in entry:
        return (entry["ficd_param_pelleted"], factor)

    return (entry.get("ficd_param"), factor)


def premix_mask_codes(stage: str | None = None,
                      override: list[str] | None = None) -> set[str]:
    """Return the set of ASNS spec codes whose constraints are skipped when
    premix_enabled = True.

    Parameters
    ----------
    stage    : optional ASNS stage_weight label; consulted for stage-specific
               add/remove tweaks declared in premix_mask.json
    override : optional explicit list of codes; if supplied, used wholesale
               (no additive merging with defaults).
    """
    if override is not None:
        return set(override)

    raw = _premix_raw()
    base = set(raw.get("default_mask_codes", []))

    overrides = raw.get("stage_overrides", {})
    if stage:
        for key, mods in overrides.items():
            if key.startswith("_"):
                continue
            if key in stage:
                base = (base | set(mods.get("add", []))) - set(mods.get("remove", []))
                break
    return base


def spec_label(spec_code: str) -> str:
    cw = _crosswalk_raw()
    if spec_code in cw and isinstance(cw[spec_code], dict):
        return cw[spec_code].get("spec_label", spec_code)
    return spec_code


def spec_unit(spec_code: str) -> str:
    cw = _crosswalk_raw()
    if spec_code in cw and isinstance(cw[spec_code], dict):
        return cw[spec_code].get("unit_asns", "")
    return ""
