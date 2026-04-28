"""Filter the FICD wide table down to the ingredients the LP is allowed to use.

For the MVP we draw from a single 'plausibly African' shortlist in
`config/ingredient_pool_africa.csv`. Each row carries flags for the
fish-meal cost-share cap (`is_fishmeal`) and binder cap (`is_binder`),
plus an optional per-ingredient `max_inclusion`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from .data_loader import load_ficd_wide

POOL_PATH = Path(__file__).parent / "config" / "ingredient_pool_africa.csv"


@dataclass(frozen=True)
class IngredientRecord:
    code: str
    description: str
    cls: str
    is_fishmeal: bool
    is_binder: bool
    max_inclusion: Optional[float]   # None ⇒ no per-ingredient cap


def load_pool(only_codes: Optional[Iterable[str]] = None) -> list[IngredientRecord]:
    """Return the active ingredient pool, optionally restricted to `only_codes`.

    `only_codes` is typically the set of ingredient codes the miller has
    a price for at request time; ingredients without prices are excluded.
    """
    raw = pd.read_csv(POOL_PATH, comment="#", dtype={"code": str})
    raw = raw[raw["code"].notna()].copy()
    keep = set(map(str, only_codes)) if only_codes is not None else None

    out: list[IngredientRecord] = []
    for _, r in raw.iterrows():
        code = str(r["code"]).strip()
        if keep is not None and code not in keep:
            continue
        out.append(
            IngredientRecord(
                code=code,
                description=str(r["description"]),
                cls=str(r["class"]),
                is_fishmeal=bool(int(r.get("is_fishmeal", 0) or 0)),
                is_binder=bool(int(r.get("is_binder", 0) or 0)),
                max_inclusion=(
                    float(r["max_inclusion"]) if pd.notna(r.get("max_inclusion")) else None
                ),
            )
        )
    return out


def attach_ficd_rows(records: list[IngredientRecord]) -> pd.DataFrame:
    """Return a wide FICD frame (one row per pool ingredient) keyed by code."""
    ficd = load_ficd_wide()
    codes = [r.code for r in records]
    sub = ficd[ficd["code"].isin(codes)].copy()
    missing = set(codes) - set(sub["code"])
    if missing:
        raise ValueError(
            f"Pool references FICD codes not present in the ingredient database: "
            f"{sorted(missing)}"
        )
    return sub.set_index("code").reindex(codes).reset_index()
