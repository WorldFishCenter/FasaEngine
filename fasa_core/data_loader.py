"""Loaders for ASNS, FICD, and PAFF.

Heavy lifting: reshape FICD from long to wide so each ingredient is a single
row keyed by code, with one column per parameter. Cached in memory because the
FICD table is 222k rows and we don't want to re-read on every API call.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from .config.defaults import (
    ASNS_FILENAME,
    DEFAULT_DATA_DIR,
    FICD_FILENAME,
    PAFF_COMPOSITION_FILENAME,
    PAFF_FORMULATIONS_FILENAME,
)


def _resolve(data_dir: Optional[Path], filename: str) -> Path:
    base = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    return base / filename


# ---------- ASNS ------------------------------------------------------------ #


@lru_cache(maxsize=4)
def load_asns(data_dir: Optional[Path] = None) -> pd.DataFrame:
    """Load the species nutritional specification database.

    Returns a frame with one row per (species, system, stage, code) and a
    `value_numeric` column that's NaN for blank entries.
    """
    df = pd.read_csv(_resolve(data_dir, ASNS_FILENAME))
    df["value_numeric"] = pd.to_numeric(df["value"], errors="coerce")
    return df


def get_active_constraints(
    species: str,
    stage: str,
    production_system: str,
    data_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Subset ASNS to constraints with concrete numeric values for a given stage."""
    asns = load_asns(data_dir)
    sub = asns[
        (asns["species"] == species)
        & (asns["production_system"] == production_system)
        & (asns["stage_weight"] == stage)
        & asns["value_numeric"].notna()
    ].copy()
    if sub.empty:
        raise ValueError(
            f"No ASNS constraints found for ({species!r}, {production_system!r}, "
            f"{stage!r}). Check spelling against the ASNS CSV."
        )
    return sub.reset_index(drop=True)


# ---------- FICD ------------------------------------------------------------ #


@lru_cache(maxsize=4)
def load_ficd_wide(data_dir: Optional[Path] = None) -> pd.DataFrame:
    """Pivot FICD from long to wide.

    Returns a frame indexed by ingredient `code` with columns:
        - description
        - one column per parameter (277 of them)
    """
    long = pd.read_csv(_resolve(data_dir, FICD_FILENAME))
    long["quantity"] = pd.to_numeric(long["quantity"], errors="coerce")

    wide = long.pivot_table(
        index=["code", "description"],
        columns="ingredient",
        values="quantity",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    wide["code"] = wide["code"].astype(str)
    return wide


# ---------- PAFF ------------------------------------------------------------ #


@lru_cache(maxsize=4)
def load_paff(data_dir: Optional[Path] = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load both PAFF tables: (formulations, calculated_composition)."""
    forms = pd.read_csv(_resolve(data_dir, PAFF_FORMULATIONS_FILENAME))
    comps = pd.read_csv(_resolve(data_dir, PAFF_COMPOSITION_FILENAME))
    forms["iaffd_code"] = forms["iaffd_code"].astype(str)
    return forms, comps


def list_supported_stages(species: str, production_system: str,
                          data_dir: Optional[Path] = None) -> list[str]:
    """Enumerate the stage_weight labels available for a species/system pair."""
    asns = load_asns(data_dir)
    sub = asns[
        (asns["species"] == species)
        & (asns["production_system"] == production_system)
    ]
    return sorted(sub["stage_weight"].dropna().unique().tolist())
