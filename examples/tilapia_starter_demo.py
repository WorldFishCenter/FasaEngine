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
    "10018": 1.50,   # Fish meal, sardine, 66% CP   (capped by cost-share)
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


def _run(label: str, **overrides):
    print(f"\n{'='*78}\n[{label}]\n{'='*78}")
    res = formulate(
        species="Nile Tilapia",
        stage="< 5g (Starter)",
        production_system="General-LowCost",
        prices=DEMO_PRICES,
        processing_method="pelleted",
        premix_enabled=True,
        premix_rate=0.005,
        **overrides,
    )
    print(json.dumps(res.model_dump(), indent=2, default=str))
    return res


def main() -> int:
    # Scenario A — strict defaults (FM cost-share ≤ 20 %, binder ≤ 25 %).
    # Tilapia STARTER diets are biologically demanding; on this priced pool
    # the two caps are *jointly* infeasible. The engine returns an IIS report
    # naming PA02/PA11/ADPXF09/FA14 so the miller learns *why* and can choose
    # which relaxation to take. This is the diagnostic value of the LP gate.
    a = _run("STRICT defaults — 20 % FM cost-share + 25 % binder")

    # Scenario B — keep low FM cost-share (sustainability story), but allow
    # more wheat flour / cassava as a binder. Realistic for cost-conscious
    # smallholder mills that have access to cheap local starch.
    b = _run("Relax BINDER → 20 % FM cost-share + 40 % binder",
             max_fishmeal_cost_share=0.20, max_binder_inclusion=0.40)

    # Scenario C — keep tight binder cap, but lift FM cost-share. Realistic
    # for premium mills that prioritize compact pellets over fish-meal frugality.
    c = _run("Relax FM   → 40 % FM cost-share + 25 % binder",
             max_fishmeal_cost_share=0.40, max_binder_inclusion=0.25)

    # Success if any of the relaxation scenarios solved.
    return 0 if "optimal" in {a.status, b.status, c.status} else 1


if __name__ == "__main__":
    sys.exit(main())
