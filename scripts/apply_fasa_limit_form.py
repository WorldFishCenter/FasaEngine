"""Apply the maximums the FASA team entered in the ingredient form to ingredient_limits.csv.

The form ("FASA ingredient maximums and groups.xlsx", sheet Ingredients) lists every pool
ingredient: code in column B, maximum % of feed per FASA weight group in columns K-P
(tilapia 0-10 g, 10-100 g, >100 g; catfish 0-10 g, 10-200 g, >200 g). It was sent pre-filled
with the maximums the engine used, so a line is complete: where its values differ from the
engine's, all of that ingredient's rows are replaced by the form's, written at the end of the
file (an empty cell = no maximum, 0 = never used). Lines that match the engine are left
alone, and so are the file's comments. Run it again each time the team returns the form;
needs openpyxl, which the engine does not:
    uv run --no-project --with pandas --with openpyxl \\
        python scripts/apply_fasa_limit_form.py "<path to>/FASA ingredient maximums and groups.xlsx"
"""

from __future__ import annotations

import csv
import io
import sys
from functools import cache
from itertools import product
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # allow `import fasa_core` without installing the package

from fasa_core.config.defaults import SUPPORTED_PRODUCTION_SYSTEMS, SUPPORTED_SPECIES  # noqa: E402
from fasa_core.data_loader import list_supported_stages  # noqa: E402
from fasa_core.inclusion_limits import INGREDIENT_LIMITS_PATH, LimitScope, ingredient_bounds  # noqa: E402
from fasa_core.ingredient_pool import load_pool  # noqa: E402

# form columns K-P -> (species, weight group, ASNS stages in it), as decisions tab 3b
GROUPS = [
    ("Nile Tilapia", "0-10 g", ["< 5g (Starter)", "5-10g (Pre-grower)"]),
    ("Nile Tilapia", "10-100 g", ["10-30g (Pre-grower)", "30-70g (Grower)", "70-100g (Grower)"]),
    ("Nile Tilapia", ">100 g", ["100-200g (Grower)", "200-400g (Grower)", "400-800g (Grower)",
                                ">800g (Grower)", ">1000g (Brood)"]),
    ("African Catfish", "0-10 g", ["< 5g (Starter)"]),
    ("African Catfish", "10-200 g", ["5-50g (Pre-grower)", "50-200g (Grower)"]),
    ("African Catfish", ">200 g", ["200-500g (Grower)", "500-800g (Grower)", "800-1000g (Grower)",
                                   "1000-1200g (Grower)", ">1200g (Grower)", ">1000g (Brood)"]),
]


@cache
def scope_bounds(scope: LimitScope) -> dict:
    """Every ingredient's bounds in one scope, resolved once for all the form's lines."""
    return ingredient_bounds(scope, [])


def engine_maxima(code: str) -> list[float | None]:
    """The engine's maximum % per weight group (one value: the form has no column per stage,
    production system or processing method, so all of them in a group must agree)."""
    out = []
    for species, _, stages in GROUPS:
        found = set()
        for stage, system, method in product(stages, SUPPORTED_PRODUCTION_SYSTEMS, ("pelleted", "extruded")):
            bound = scope_bounds(LimitScope(species, stage, system, method)).get(code)
            found.add(None if bound is None or bound.maximum is None else round(100 * bound.maximum, 6))
        assert len(found) == 1, f"{code}: {species} maximums in one weight group disagree: {found}"
        out.append(found.pop())
    return out


def form_rows(code: str, name: str, maxima: list[float | None], note: str) -> list[list[str]]:
    rows = []
    for species in SUPPORTED_SPECIES:
        mine = [(g, stages, m) for (sp, g, stages), m in zip(GROUPS, maxima) if sp == species]
        values = {m for _, _, m in mine}
        if len(values) == 1:  # one value for the species: one row
            (m,) = values
            if m is not None:
                rows.append([code, species, "", "", "", "", f"{m / 100:g}", f"{note}: {name}"])
            continue
        for group, stages, m in mine:
            if m is not None:
                rows += [[code, species, "", stage, "", "", f"{m / 100:g}", f"{note} ({group}): {name}"]
                         for stage in stages]
    return rows


def rewrite(lines: list[str], replace: dict[str, list[list[str]]]) -> str:
    """The limits file without the rows of each replaced ingredient, its new rows at the end."""
    out = io.StringIO()
    out.writelines(ln for ln in lines if ln.split(",", 1)[0] not in replace)
    csv.writer(out, lineterminator="\n").writerows(row for rows in replace.values() for row in rows)
    return out.getvalue()


def main(form: str) -> int:
    import openpyxl  # here, not at the top: the tests import rewrite() without it

    for species in SUPPORTED_SPECIES:  # an ASNS stage in no group would lose its maximum
        asns = {s for system in SUPPORTED_PRODUCTION_SYSTEMS for s in list_supported_stages(species, system)}
        grouped = {s for sp, _, stages in GROUPS if sp == species for s in stages}
        assert asns == grouped, f"{species}: GROUPS and the ASNS stages differ: {sorted(asns ^ grouped)}"

    pooled = {r.code for r in load_pool()}
    book = openpyxl.load_workbook(form, data_only=True)
    ws = book["Ingredients"]
    note = f"FASA ingredient form of {book.properties.modified:%Y-%m-%d}"  # when the team saved it
    replace, skipped = {}, []
    for r in range(9, ws.max_row + 1):
        code = str(ws.cell(r, 2).value or "").strip()
        if not code:
            continue
        if code not in pooled:
            skipped.append(code)
            continue
        maxima = [ws.cell(r, c).value for c in range(11, 17)]
        for m in maxima:
            if m is not None and not (isinstance(m, (int, float)) and 0 <= m <= 100):
                raise SystemExit(f"{code}: maximum {m!r} is not a % between 0 and 100")
        maxima = [None if m is None else round(float(m), 6) for m in maxima]
        if maxima != engine_maxima(code):
            replace[code] = form_rows(code, " ".join(str(ws.cell(r, 3).value).split()), maxima, note)

    text = rewrite(INGREDIENT_LIMITS_PATH.read_text().splitlines(keepends=True), replace)
    INGREDIENT_LIMITS_PATH.write_text(text, newline="")
    print(f"replaced the maximums of {len(replace)} ingredients: {', '.join(replace) or 'none'}")
    if skipped:
        print(f"skipped, not in the pool: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
