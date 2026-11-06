"""Build the FASA ingredient composition file from the FASA lab results.

Writes ``data/FASA_feed_ingredient_composition.csv`` in FICD's long format
(``code,description,ingredient,quantity``), one block per line of
``scripts/data/fasa_ingredients.csv``. It is a separate file so a FICD import never
overwrites it; the engine reads both (``data_loader.load_ficd_wide``).

Values, as the FASA team decided (decisions workbook, 5 November 2026):

  * lab values are as-fed. A value written "<0.1" counts as zero, and the line's
    own lab value always wins over a filled one;
  * tannin, gossypol and phytic acid are in % and saponin in mg/g in the lab file,
    converted to the units the rules read;
  * phosphorus, the toxins, the anti-nutrients the lab did not measure, the trace
    minerals and the vitamins are filled from the linked IAFFD ingredient;
  * digestible energy = lab gross energy x the linked IAFFD ingredient's digestibility %;
  * starch comes from the lab only. Values for the rules the team dropped are left out.

Fails if a line's lab sample is missing or empty, or if a rule the engine checks has no
source. Needs openpyxl, which the engine does not; run from the repo root:
    uv run --no-project --with pandas --with openpyxl \\
        python scripts/build_fasa_ingredients.py "<path to>/Ingredient Databasev2.xlsx"
The lab file is the FASA team's and lives outside the repo; only the CSV built from it is
versioned. Then rebuild the pool: python scripts/build_ingredient_pool.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # allow `import fasa_core` without installing the package

from fasa_core import crosswalk  # noqa: E402  (after sys.path bootstrap)
from fasa_core.config.defaults import (  # noqa: E402
    DEFAULT_DATA_DIR,
    DROPPED_RULES,
    FASA_FICD_FILENAME,
    FICD_FILENAME,
    SAPONIN_RULE,
    SUPPORTED_PRODUCTION_SYSTEMS,
    SUPPORTED_SPECIES,
)
from fasa_core.data_loader import load_asns  # noqa: E402

LINES_SRC = REPO_ROOT / "scripts" / "data" / "fasa_ingredients.csv"
OUT = DEFAULT_DATA_DIR / FASA_FICD_FILENAME
LAB_SHEET = "Nutrient composition"

# lab column -> (FICD parameter, factor to its unit)
LAB = {
    "Dry Matter %": ("dry_matter_percent", 1),
    "Ash Content %": ("ash_percent", 1),
    "Crude Protein %": ("crude_protein_percent", 1),
    "Crude Fibre %": ("crude_fibre_percent", 1),
    "Crude Lipid %": ("crude_lipids_percent", 1),
    "Gross Calorific Value J/g": ("gross_energy_kcal_kcal_kg", 1 / 4.184),  # kJ/kg -> kcal/kg
    "L-Arginine": ("arginine_percent", 1),
    "L-Histidine": ("histidine_percent", 1),
    "L-Isoleucine": ("isoleucine_percent", 1),
    "L-leucine": ("leucine_percent", 1),
    "L-lysine": ("lysine_percent", 1),
    "L-Methionine": ("methionine_percent", 1),
    "L-Phenylalanine": ("phenylalanine_percent", 1),
    "L-Threonine": ("threonine_percent", 1),
    "L-Tryptophan": ("tryptophan_percent", 1),
    "L-valine": ("valine_percent", 1),
    "L-tyrosine": ("tyrosine_percent", 1),
    "Saponin*": ("saponin_mg_kg", 1000),                # mg/g -> mg/kg
    "Tannin*": ("tannins_mg_eq_cathin_kg", 10000),      # % -> mg/kg
    "Phytic Acid*": ("phytic_acid_g_kg", 10),           # % -> g/kg
    "Total Gossypol*": ("gossypol_mg_kg", 10000),       # % -> mg/kg
}
# FICD parameter -> lab columns it adds up
LAB_SUMS = {
    "cystine_percent": ("L-Cysteine", "L-Cystine"),
    "tsaa_met_cys_percent": ("L-Methionine", "L-Cysteine", "L-Cystine"),
    "phe_tyr_percent": ("L-Phenylalanine", "L-tyrosine"),
    "epa_dha_percent": ("Eicosapentaenoic acid EPA (C20: 5n3)", "Docosahexaenoic acid DHA (C22: 6n3)"),
    "sum_n_3_percent": ("α-linolenic acid (C18: 3n3)", "Eicosatrienoic acid (C20: 3n3)",
                        "Eicosapentaenoic acid EPA (C20: 5n3)", "Docosahexaenoic acid DHA (C22: 6n3)"),
    "sum_n_6_percent": ("Linolelaidic acid (C18: 2n6t)", "Linoleic acid (C18: 2n6c)",
                        "γ-linolenic acid (C18: 3n6)", "Eicosatrienoic acid (C20: 3n6)",
                        "Arachidonic acid (C20: 4n6)"),
}
# rules whose values come from the linked IAFFD ingredient where the lab has none:
# phosphorus, the 16 toxins and anti-nutrients, trace minerals, vitamins
FILL_RULES = (
    ["M02", "M08", "M09", "M10", "M11", "M12", "M13"]
    + [f"TX{n:02d}" for n in range(1, 17)]
    + [f"V{n:02d}" for n in range(1, 14)]
)
# FICD digestible energy -> the IAFFD digestibility % it is gross energy x (FICD's own rule)
DIGESTIBILITY = {
    "de_fish_carni_pelleted_kcal_kg": "adc_ge_carni_pelleted_percent",
    "de_fish_omni_pelleted_kcal_kg": "adc_ge_omni_pelleted_percent",
    "de_fish_carni_extruded_kcal_kg": "adc_ge_carni_extruded_percent",
    "de_fish_omni_extruded_kcal_kg": "adc_ge_omni_extruded_percent",
    "dig_ge_de_fish_kcal": "adc_ge_fish_percent",
}


def _num(cell: object) -> float | None:
    if isinstance(cell, str) and cell.strip().startswith("<"):
        return 0.0
    value = pd.to_numeric(cell, errors="coerce")
    return None if pd.isna(value) else float(value)


def _key(name: object) -> str:
    return " ".join(str(name).split()).lower()


def read_lab(path: Path) -> tuple[dict[tuple[str, str], dict[str, float | None]], str | None]:
    """Lab samples keyed by (name, country) -> {FICD parameter: value}, and the starch column used."""
    raw = pd.read_excel(path, sheet_name=LAB_SHEET, header=None, dtype=object)
    header = [" ".join(str(h).split()) for h in list(raw.iloc[0, :3]) + list(raw.iloc[1, 3:])]
    col = {h: i for i, h in enumerate(header) if h != "nan"}
    starch = next((h for h in col if "starch" in h.lower()), None)
    lab_map = dict(LAB)
    if starch:
        lab_map[starch] = ("starch_percent", 1)

    samples = {}
    for _, row in raw.iloc[2:].iterrows():
        if pd.isna(row.iloc[0]):
            continue
        cell = {h: _num(row.iloc[i]) for h, i in col.items()}
        values = {param: (None if cell[h] is None else cell[h] * factor)
                  for h, (param, factor) in lab_map.items()}
        for param, parts in LAB_SUMS.items():
            found = [cell[h] for h in parts if cell[h] is not None]
            values[param] = sum(found) if found else None
        dm = values["dry_matter_percent"]
        values["moisture_percent"] = None if dm is None else 100 - dm
        samples[(_key(row.iloc[col["Sample Name"]]), _key(row.iloc[col["Country of origin"]]))] = values
    return samples, starch


def read_iaffd(codes: set[str]) -> dict[str, dict[str, float]]:
    long = pd.read_csv(DEFAULT_DATA_DIR / FICD_FILENAME, dtype={"code": str})
    long = long[long["code"].isin(codes)]
    long["quantity"] = pd.to_numeric(long["quantity"], errors="coerce")
    return {code: dict(zip(g["ingredient"], g["quantity"])) for code, g in long.groupby("code")}


def checked_params() -> set[str]:
    """FICD parameters read by the rules the engine applies to tilapia and catfish."""
    asns = load_asns()
    codes = set(asns.loc[
        asns["species"].isin(SUPPORTED_SPECIES)
        & asns["production_system"].isin(SUPPORTED_PRODUCTION_SYSTEMS)
        & asns["value_numeric"].notna(), "code"])
    codes = {c for c in codes if not crosswalk.duplicate_of(c)} - DROPPED_RULES
    codes = (codes - crosswalk.premix_mask_codes()) | {SAPONIN_RULE[1]}
    params = set()
    for code in codes:
        for method in ("pelleted", "extruded"):
            param, factor = crosswalk.resolve(code, method)
            params |= {factor["numer"], factor["denom"]} if param == "__ratio__" else {param}
    return params


def main(lab_path: str) -> int:
    lines = pd.read_csv(LINES_SRC, comment="#", dtype=str, keep_default_na=False)
    samples, starch = read_lab(Path(lab_path))
    iaffd = read_iaffd(set(lines["iaffd_code"]))
    fill = {crosswalk.resolve(code)[0] for code in FILL_RULES} | set(DIGESTIBILITY.values())

    rows, problems = [], []
    for line in lines.itertuples():
        lab = samples.get((_key(line.sample), _key(line.country)))
        link = iaffd.get(line.iaffd_code)
        if lab is None or lab["crude_protein_percent"] is None:
            problems.append(f"{line.code}: no lab values for {line.sample} [{line.country}]")
            continue
        if link is None:
            problems.append(f"{line.code}: IAFFD code {line.iaffd_code} not in FICD")
            continue
        values = dict(lab)
        for param in sorted(fill):  # sorted: same file on every rebuild
            if values.get(param) is None and pd.notna(link.get(param)):
                values[param] = link[param]
        ge = values["gross_energy_kcal_kcal_kg"]
        for de, adc in DIGESTIBILITY.items():
            if ge is not None and pd.notna(link.get(adc)):
                values[de] = ge * link[adc] / 100
        description = f"{line.name} [FASA, {line.country}]"
        rows += [(line.code, description, p, round(v, 6)) for p, v in values.items() if v is not None]

    out = pd.DataFrame(rows, columns=["code", "description", "ingredient", "quantity"])
    # starch is lab-only and reported below, so a lab file without it still builds
    uncovered = checked_params() - set(out["ingredient"]) - {"starch_percent"}
    if uncovered:
        problems.append(f"rules with no FASA source: {sorted(uncovered)}")
    if problems:
        raise SystemExit("\n".join(problems))

    out.to_csv(OUT, index=False)
    with_starch = out.loc[out["ingredient"] == "starch_percent", "code"].nunique()
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {out['code'].nunique()} ingredients, {len(out)} values")
    print(f"  starch: {with_starch} with a lab value "
          f"({'column ' + repr(starch) if starch else 'no starch column in the lab file'})")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
