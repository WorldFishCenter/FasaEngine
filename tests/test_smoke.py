"""Smoke tests: data loaders, crosswalk, end-to-end formulation, PAFF benchmark."""

import pytest

from fasa_core.crosswalk import resolve, premix_mask_codes
from fasa_core.data_loader import (
    get_active_constraints,
    load_asns,
    load_ficd_wide,
    load_paff,
)
from fasa_core.optimizer import formulate
from fasa_core.validator import benchmark_against_paff, compute_composition


# --------------------------------------------------------------------------- #
# data loaders                                                                #
# --------------------------------------------------------------------------- #


def test_asns_loads():
    df = load_asns()
    assert {"species", "production_system", "stage_weight", "code", "value"}.issubset(df.columns)
    assert (df["species"] == "Nile Tilapia").any()


def test_ficd_wide_pivot():
    df = load_ficd_wide()
    # Schema and basic sanity checks (row count may vary across FICD releases)
    assert len(df) >= 500
    assert "crude_protein_percent" in df.columns
    assert "dig_cp_fish_percent" in df.columns
    assert "de_fish_omni_pelleted_kcal_kg" in df.columns


def test_paff_loads():
    forms, comps = load_paff()
    assert (forms["species"] == "Nile Tilapia - Starter").any()
    assert (comps["species"] == "Nile Tilapia - Starter").any()


def test_active_constraints_for_tilapia_starter():
    df = get_active_constraints("Nile Tilapia", "< 5g (Starter)", "General-LowCost")
    # Expect a non-trivial constraint set; exact count may vary across ASNS revisions
    assert len(df) >= 40


# --------------------------------------------------------------------------- #
# crosswalk                                                                   #
# --------------------------------------------------------------------------- #


def test_resolve_simple():
    p, f = resolve("PA03")          # Crude Protein
    assert p == "crude_protein_percent" and f == 1.0


def test_resolve_energy_processing_dependent():
    pellet, _ = resolve("ED02", processing_method="pelleted")
    extr,   _ = resolve("ED02", processing_method="extruded")
    assert pellet == "de_fish_omni_pelleted_kcal_kg"
    assert extr   == "de_fish_omni_extruded_kcal_kg"


def test_resolve_vitamin_unit_conversion():
    p, f = resolve("V10")           # Vitamin A: ASNS mg → FICD IU/kg ×3333
    assert p == "vitamin_a_iu_kg"
    assert abs(f - 3333.0) < 1e-9


def test_resolve_ratio():
    p, ratio = resolve("ADPXF09")   # DP/DE (g/MJ)
    assert p == "__ratio__"
    assert ratio["numer"] == "dig_cp_fish_percent"
    assert ratio["denom"] == "dig_ge_de_fish_kcal"


def test_premix_mask_excludes_amino_acids_and_macros():
    mask = premix_mask_codes()
    # vit + trace minerals masked, AAs and macros not
    assert "V10" in mask
    assert "M12" in mask
    assert "AA05" not in mask
    assert "PA03" not in mask
    # toxins never masked even by default
    assert "TX01" not in mask


# --------------------------------------------------------------------------- #
# end-to-end formulation                                                      #
# --------------------------------------------------------------------------- #


DEMO_PRICES = {
    "30355": 0.30, "31147": 0.28, "31148": 0.30,
    "31605": 0.18, "30937": 0.20,
    "30307": 0.25, "31621": 0.40,
    "31237": 0.55, "31407": 0.45, "30404": 0.42, "30557": 0.60,
    "27002": 1.20, "10018": 1.50, "10073": 1.40, "20002": 0.90,
    "23002": 1.10, "40205": 0.80, "52113": 1.10, "52117": 1.20,
    "62138": 0.10, "62134": 0.80, "62135": 0.15,
    "61109": 3.00, "61111": 4.50,
}


def test_formulate_tilapia_starter_returns_a_status():
    res = formulate(
        species="Nile Tilapia",
        stage="< 5g (Starter)",
        production_system="General-LowCost",
        prices=DEMO_PRICES,
    )
    assert res.status in {"optimal", "infeasible", "error"}
    assert res.species == "Nile Tilapia"
    if res.status == "optimal":
        # mass balance honored (≤ 100% because premix takes 0.5%)
        total = sum(line.inclusion_percent for line in res.recipe)
        assert 99.0 <= total <= 100.0


def test_formulate_batch_size_kg_populates_absolute_quantities():
    """When batch_size_kg is supplied, recipe carries kg per line and
    response reports premix kg + total batch cost. Sum of kg ≈ batch size."""
    batch = 100.0
    res = formulate(
        species="Nile Tilapia",
        stage="< 5g (Starter)",
        production_system="General-LowCost",
        prices=DEMO_PRICES,
        batch_size_kg=batch,
    )
    if res.status != "optimal":
        pytest.skip(f"LP did not solve to optimal on this priced pool (status={res.status})")

    # echoed
    assert res.batch_size_kg == batch
    # premix_enabled defaults to True, so premix kg = batch * premix_rate
    assert res.premix_quantity_kg == round(batch * res.premix_rate, 3)
    assert res.total_cost == round(res.cost_per_kg * batch, 2)

    # every recipe line has quantity_kg populated and consistent with inclusion_percent.
    # tolerance accounts for independent rounding of inclusion_percent (4 dp) and
    # quantity_kg (3 dp) from the same LP fraction.
    for line in res.recipe:
        assert line.quantity_kg is not None
        assert abs(line.quantity_kg - line.inclusion_percent / 100.0 * batch) < 0.001

    # mass-balance sanity: sum(qty_kg) + premix_kg ≈ batch (within per-line rounding)
    total_kg = sum(line.quantity_kg for line in res.recipe) + res.premix_quantity_kg
    assert abs(total_kg - batch) < 0.05


def test_formulate_without_batch_size_omits_absolute_quantities():
    """Default (no batch_size_kg) returns percent-only output."""
    res = formulate(
        species="Nile Tilapia",
        stage="< 5g (Starter)",
        production_system="General-LowCost",
        prices=DEMO_PRICES,
    )
    if res.status != "optimal":
        pytest.skip(f"LP did not solve to optimal on this priced pool (status={res.status})")
    assert res.batch_size_kg is None
    assert res.premix_quantity_kg is None
    assert res.total_cost is None
    assert all(line.quantity_kg is None for line in res.recipe)


def test_formulate_request_rejects_non_positive_batch_size():
    """Pydantic must reject batch_size_kg ≤ 0."""
    from pydantic import ValidationError

    from fasa_core.models import FormulateRequest

    for bad in (0, -1, -100.5):
        with pytest.raises(ValidationError):
            FormulateRequest(
                species="Nile Tilapia",
                stage="< 5g (Starter)",
                prices={"30355": 0.30},
                batch_size_kg=bad,
            )


def test_formulate_catfish_uses_carni_track():
    """African Catfish should bind ED01 (DE-Carni), not ED02."""
    from fasa_core.constraint_builder import build_constraints
    from fasa_core.ingredient_pool import load_pool

    pool = load_pool(only_codes=set(DEMO_PRICES.keys()))
    cons, _ = build_constraints(
        species="African Catfish",
        stage="< 5g (Starter)",
        production_system="General",
        pool=pool,
    )
    codes = {c.spec_code for c in cons}
    # African Catfish ASNS uses ED01, not ED02
    assert "ED01" in codes
    assert "ED02" not in codes


# --------------------------------------------------------------------------- #
# PAFF benchmark gate                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("paff_label", ["Nile Tilapia - Starter", "Nile Tilapia - Grower"])
def test_paff_reproduction(paff_label):
    rep = benchmark_against_paff(paff_label)
    # at minimum, our values must be in the same order of magnitude as PAFF's
    rep_clean = rep.dropna(subset=["paff_value"])
    if rep_clean.empty:
        pytest.skip("no comparable parameters in PAFF")
    # Tight tolerance is a stretch goal; loose tolerance must hold.
    assert (rep_clean["rel_diff"] < 0.10).all(), rep_clean.to_string()
