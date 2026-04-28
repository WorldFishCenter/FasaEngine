"""Independent recomputation of nutrient composition + PAFF benchmark gate.

This module is the safety net against unit-conversion bugs and silent FICD
column-mapping errors. The `validate()` function is called automatically by
the API and also exposed for ad-hoc testing.

PAFF benchmark: feed the engine the 36 reference recipes' inclusion vectors
*directly* (i.e., bypass the LP and compute composition only) and compare
nutrient-by-nutrient with the published Calculated_Composition table.
"""

from __future__ import annotations

import pandas as pd

from .config.defaults import VALIDATION_REL_TOL
from .data_loader import load_ficd_wide, load_paff


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
