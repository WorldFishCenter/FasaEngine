"""Build the default price list for the app from the FASA team's spreadsheets.

Writes ``data/FASA_default_prices.csv``: one row per country and priced ingredient, with
the engine code to send in ``prices`` (or as ``premix_price``) and a status: ``ok``,
``to check`` (``what_to_check`` says what) or ``missing`` (no price yet). The engine does
not read it; prices always come from the caller. Sources:

  * FASA APP DATA.xlsx, sheet Matrix: price per kg in local currency (columns F-H) for
    each name in column E;
  * the decisions workbook, tab 1: the countries of each FASA line (column C) and the
    prices of FASA lines the Matrix does not price (columns M-O).

A name with a FASA line gets its FASA code. Other names get an IAFFD code: from the
Default ING sheets (``DEFAULT_ING_CODES``), or matched by name by us (``BY_NAME``,
``to check`` unless IAFFD has only that version). Needs openpyxl, which the engine does
not; run from the repo root:
    uv run --no-project --with pandas --with openpyxl python scripts/build_fasa_prices.py \\
        "<path to>/FASA APP DATA.xlsx" "<path to>/FASA engine decisions.xlsx"
Run it again whenever the FASA team changes either file, or the FASA lines or the pool change.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import NamedTuple

import openpyxl
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # allow `import fasa_core` without installing the package

from fasa_core.config.defaults import DEFAULT_DATA_DIR, normalize_country  # noqa: E402  (after sys.path bootstrap)
from fasa_core.ingredient_pool import load_pool  # noqa: E402
from scripts.build_fasa_ingredients import name_key, read_lines  # noqa: E402

OUT = DEFAULT_DATA_DIR / "FASA_default_prices.csv"


class Country(NamedTuple):
    currency: str
    name: str
    matrix_col: int  # its price column in FASA APP DATA, sheet Matrix (F-H)
    tab1_col: int  # its price column in decisions tab 1 (M-O)


# in the order the price list gives them
COUNTRIES = {
    "NG": Country("NGN", "Nigeria", 6, 13),
    "KE": Country("KES", "Kenya", 7, 14),
    "ZM": Country("ZMW", "Zambia", 8, 15),
}
STATUS_ORDER = {"ok": 0, "to check": 1, "missing": 2}
# IAFFD codes the Default ING sheets give
DEFAULT_ING_CODES = {"rapeseed": "30906", "lysine": "61108", "methonine": "61111", "vitamin c": "60128"}
# Matrix names with no FASA line, matched to IAFFD by us
BY_NAME = {
    "fishmeal": "10022", "poultry meal": "23001", "blood meal": "20002", "meat and bone meal": "22000",
    "feather meal": "21001", "soy bean cake": "31235", "corn gluten meal": "30345",
    "palm kernel meal": "30806", "brewer's spent grain": "30212", "corn grain": "30355",
    "corn bran": "30351", "rice, broken": "30944", "wheat flour": "31621", "wheat bran": "31605",
    "cassava tuber, meal": "30307", "cassava starch": "30311", "palm oil": "52113",
    "fish oil": "50123", "vegetable oil": "52117", "dicalcium phosphate": "62134",
    "defatted black soldier fly": "27002", "maggot /meal": "27001",
}
# same ingredient and name in IAFFD, which has only that version: nothing to check
ONLY_IAFFD_VERSION = {"corn grain", "corn bran", "rice, broken", "wheat bran", "cassava tuber, meal",
                      "palm oil", "dicalcium phosphate", "defatted black soldier fly"}
NOT_IN_ENGINE = {  # priced in the Matrix, no engine ingredient
    "black soldier fly": "Same as the FASA black soldier fly lines? If so, drop this row.",
    "bone meal": "No IAFFD ingredient of this name: drop it, or name the IAFFD ingredient to use.",
    "azollla???": "Marked ??? in FASA APP DATA: keep it? It has no lab sample or IAFFD code yet.",
    "moringa leaf ???": "Marked ??? in FASA APP DATA: keep it? It has no lab sample or IAFFD code yet.",
    "water lentil (lemna) ???": "Marked ??? in FASA APP DATA: keep it? It has no lab sample or IAFFD code yet.",
}


def main(app_data: str, decisions: str) -> int:
    desc = {r.code: r.description for r in load_pool()}
    lines = read_lines()

    # tab 1 row of each FASA line: a kept row (column E not "Remove"), by name and lab sample
    # ("<sample> [<country>]"), as a name alone is not unique (sunflower cake is on a
    # Kenyan and a Zambian line)
    tab1 = openpyxl.load_workbook(decisions, data_only=True)["1 Ingredients"]
    kept = [row for row in range(10, tab1.max_row + 1)
            if tab1.cell(row, 2).value and name_key(tab1.cell(row, 5).value) != "remove"]
    by_key = {(name_key(tab1.cell(row, 2).value), name_key(tab1.cell(row, 6).value)): row for row in kept}
    assert len(by_key) == len(kept), "two kept tab 1 rows share a name and lab sample"
    listed, typed = {}, {}  # FASA code -> countries tab 1 lists; price in each country column
    for line in lines.itertuples():
        row = by_key[(name_key(line.name), name_key(f"{line.sample} [{line.country}]"))]
        listed[line.code] = {n for c in str(tab1.cell(row, 3).value or "").split(",") if (n := normalize_country(c))}
        typed[line.code] = {cc: tab1.cell(row, c.tab1_col).value for cc, c in COUNTRIES.items()}

    rows, seen = [], set()

    def add(cc, code, name, price, status, what=""):
        assert not code or code == "premix" or code in desc, code
        if code and (cc, code) in seen:
            return
        seen.add((cc, code))
        rows.append({
            "country": cc, "currency": COUNTRIES[cc].currency, "code": code, "name": name,
            "engine_description": desc.get(code, ""),
            "price_per_kg": "" if price is None else f"{price:g}", "status": status,
            "check_by": "Serge" if status != "ok" else "", "what_to_check": what,
        })

    matrix = openpyxl.load_workbook(app_data, data_only=True)["Matrix"]
    for row in range(6, matrix.max_row + 1):
        name = " ".join(str(matrix.cell(row, 5).value or "").split())
        if not name:
            continue
        key = name.lower()
        fasa_lines = lines[lines.name.map(name_key) == key]
        for cc, country in COUNTRIES.items():
            price = matrix.cell(row, country.matrix_col).value
            if not isinstance(price, (int, float)):
                continue
            if key == "vitamin/mineral premix":
                add(cc, "premix", name, price, "ok", "Send as premix_price, not inside prices.")
                continue
            if len(fasa_lines):
                same = fasa_lines[fasa_lines.country == country.name]
                line = (same if len(same) else fasa_lines).iloc[0]
                if listed[line.code] and cc not in listed[line.code]:
                    others = ", ".join(COUNTRIES[c].name for c in sorted(listed[line.code]))
                    add(cc, line.code, name, price, "to check",
                        f"Decisions tab 1 lists it for {others} only. Keep it, at this price, for {country.name}?")
                else:
                    add(cc, line.code, name, price, "ok")
            elif key in DEFAULT_ING_CODES:
                add(cc, DEFAULT_ING_CODES[key], name, price, "ok")
            elif key in ONLY_IAFFD_VERSION:
                add(cc, BY_NAME[key], name, price, "ok")
            elif key in BY_NAME:
                add(cc, BY_NAME[key], name, price, "to check",
                    f"No FASA lab sample: the engine uses IAFFD '{desc[BY_NAME[key]]}'. "
                    "Is that the right one (IAFFD has other versions)?")
            elif key in NOT_IN_ENGINE:
                add(cc, "", name, price, "to check", NOT_IN_ENGINE[key])

    # FASA lines: the tab 1 price where the Matrix has none, then a "missing" row for any
    # country tab 1 lists with no price at all
    for line in lines.itertuples():
        countries = listed[line.code]
        for column, price in typed[line.code].items():
            if not isinstance(price, (int, float)):
                continue
            if len(countries) == 1 and column not in countries:
                # typed in another country's column: it belongs to the one country tab 1 lists
                (cc,) = countries
                add(cc, line.code, line.name, price, "to check",
                    f"Price typed in the {COUNTRIES[column].name} column of decisions tab 1; tab 1 lists "
                    f"it for {COUNTRIES[cc].name} only. Is {price:g} the {COUNTRIES[cc].name} price "
                    f"({COUNTRIES[cc].currency})?")
            else:
                add(column, line.code, line.name, price, "ok")
        for cc in sorted(countries):
            if (cc, line.code) not in seen:
                add(cc, line.code, line.name, None, "missing", f"No price for {COUNTRIES[cc].name}.")
    for cc, country in COUNTRIES.items():
        if (cc, "premix") not in seen:
            add(cc, "premix", "Vitamin/mineral premix", None, "missing",
                f"No premix price for {country.name}. Send as premix_price, not inside prices.")

    order = list(COUNTRIES)
    rows.sort(key=lambda r: (order.index(r["country"]), r["code"] == "premix", STATUS_ORDER[r["status"]],
                             r["name"].lower()))
    with open(OUT, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    table = pd.DataFrame(rows)
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(rows)} rows\n"
          f"{pd.crosstab(table.country, table.status).to_string()}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
