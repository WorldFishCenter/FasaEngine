"""End-to-end demo: formulate a least-cost Nile Tilapia <5g (Starter) ration
on the General-LowCost track, using a representative African ingredient pool
and made-up market prices (USD/kg).

Run from the repo root:
    cd fasa_engine
    python -m examples.tilapia_starter_demo
"""

from __future__ import annotations

import json
import sys

from fasa_core.optimizer import formulate


# Indicative USD/kg prices supplied by the miller at request time.
# Replace at runtime — these numbers are illustrative only.
DEMO_PRICES = {
    # cereals
    "30355": 0.30,   # Corn, grain
    "31147": 0.28,   # Sorghum, grain
    "31148": 0.30,   # Sorghum, low tannin
    # cereal by-products
    "31605": 0.18,   # Wheat bran
    "30937": 0.20,   # Rice bran
    # binders
    "30307": 0.25,   # Cassava, tuber meal
    "31621": 0.40,   # Wheat flour
    # protein meals (plant)
    "31237": 0.55,   # Soybean meal, dehulled, 48% CP
    "31407": 0.45,   # Sunflower meal, 41% CP
    "30404": 0.42,   # Cottonseed meal, 36% CP, expeller
    "30557": 0.60,   # Groundnut meal, 45% CP
    # insect & animal
    "27002": 1.20,   # BSF larvae meal, defatted
    "10018": 1.50,   # Fish meal, sardine, 66% CP
    "10073": 1.40,   # Fish meal, mixed, Mauritania, 66% CP
    "20002": 0.90,   # Blood meal, ring dried
    "23002": 1.10,   # Poultry by-product meal, 60% CP
    # functional / oils / minerals / synthetic AAs
    "40205": 0.80,   # Brewers yeast
    "52113": 1.10,   # Palm oil
    "52117": 1.20,   # Soybean oil
    "62138": 0.10,   # Limestone
    "62134": 0.80,   # Dicalcium phosphate
    "62135": 0.15,   # Salt
    "61109": 3.00,   # L-Lysine HCl
    "61111": 4.50,   # DL-Methionine
}
PREMIX_PRICE = 2.50  # USD/kg for the vitamin/mineral premix, always included


def _run(label: str, **overrides):
    print(f"\n{'='*78}\n[{label}]\n{'='*78}")
    res = formulate(
        species="Nile Tilapia",
        stage="< 5g (Starter)",
        production_system="General-LowCost",
        prices=DEMO_PRICES,
        processing_method="pelleted",
        premix_price=PREMIX_PRICE,
        **overrides,
    )
    print(json.dumps(res.model_dump(), indent=2, default=str))
    return res


def main() -> int:
    # Scenario A — defaults, with batch_size_kg=100 so the response also reports
    # per-ingredient kg, premix kg, and total batch cost (premix included).
    # `country="ZM"` flags each recipe line's `locally_available` without changing
    # the LP (the optimizer always sees the full pool).
    a = _run("DEFAULTS — 2 % premix, batch_size_kg=100, country=ZM",
             batch_size_kg=100.0, country="ZM")

    # Scenario B — the min/max inclusion layer, passed per request. Composition data
    # alone lets the LP load up on bran: it satisfies every nutrient target yet the
    # mash will not extrude and the fish will not grow on it. Here a dietary fibre
    # ceiling joins the ASNS set (the tighter of the two binds) and the two brans get
    # per-ingredient ceilings. The same bounds normally come from
    # `fasa_core/config/{nutrient,ingredient}_limits.csv`.
    b = _run("Inclusion limits: fibre ≤ 8 % of diet, wheat/rice bran ≤ 15 % each",
             nutrient_limits={"PA05": {"max": 8.0}},
             ingredient_limits={"31605": {"max": 0.15}, "30937": {"max": 0.15}})

    # Success if any scenario produced an optimal solution.
    return 0 if "optimal" in {a.status, b.status} else 1


if __name__ == "__main__":
    sys.exit(main())
