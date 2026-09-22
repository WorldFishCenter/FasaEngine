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
# country-tagged pool + local-availability highlighting                       #
# --------------------------------------------------------------------------- #


def test_pool_carries_country_tags_and_every_code_resolves_in_ficd():
    """The expanded pool tags ingredients by ISO-2 country, and every code it
    references must have FICD composition (codes without data are excluded)."""
    from fasa_core.ingredient_pool import attach_ficd_rows, load_pool

    pool = load_pool()
    assert len(pool) >= 300
    attach_ficd_rows(pool)  # raises if any pool code is missing from FICD

    by_code = {r.code: r for r in pool}
    # locally available across all three tracked countries
    assert by_code["30355"].countries == frozenset({"KE", "NG", "ZM"})
    # import-only variant: not locally available anywhere tracked
    assert by_code["10073"].countries == frozenset()


def test_formulate_country_flags_locally_available():
    """With a country, each recipe line's locally_available reflects the pool tag."""
    from fasa_core.ingredient_pool import load_pool

    by_code = {r.code: r for r in load_pool(only_codes=set(DEMO_PRICES.keys()))}
    res = formulate(
        species="Nile Tilapia",
        stage="< 5g (Starter)",
        production_system="General-LowCost",
        prices=DEMO_PRICES,
        country="ZM",
    )
    if res.status != "optimal":
        pytest.skip(f"LP did not solve to optimal (status={res.status})")

    assert res.country == "ZM"
    for line in res.recipe:
        assert isinstance(line.locally_available, bool)
        assert line.locally_available == ("ZM" in by_code[line.code].countries)
    # a normal least-cost recipe draws on at least one locally available ingredient
    assert any(line.locally_available for line in res.recipe)


def test_formulate_without_country_leaves_locally_available_none():
    """Omitting country yields null locally_available (no local context)."""
    res = formulate(
        species="Nile Tilapia",
        stage="< 5g (Starter)",
        production_system="General-LowCost",
        prices=DEMO_PRICES,
    )
    if res.status != "optimal":
        pytest.skip(f"LP did not solve to optimal (status={res.status})")
    assert res.country is None
    assert all(line.locally_available is None for line in res.recipe)


def test_formulate_request_normalizes_and_validates_country():
    """country is upper-cased before validation; unsupported values are rejected."""
    from pydantic import ValidationError

    from fasa_core.models import FormulateRequest

    req = FormulateRequest(
        species="Nile Tilapia",
        stage="< 5g (Starter)",
        prices={"30355": 0.30},
        country="ke",
    )
    assert req.country == "KE"

    with pytest.raises(ValidationError):
        FormulateRequest(
            species="Nile Tilapia",
            stage="< 5g (Starter)",
            prices={"30355": 0.30},
            country="US",
        )


def test_parse_countries_normalizes_and_handles_blanks():
    """The pool cell parser upper-cases, strips, and drops empty tokens."""
    import math

    from fasa_core.ingredient_pool import _parse_countries

    assert _parse_countries("KE,NG,ZM") == frozenset({"KE", "NG", "ZM"})
    assert _parse_countries(" ke , ng ") == frozenset({"KE", "NG"})
    assert _parse_countries("KE,,ZM,") == frozenset({"KE", "ZM"})
    assert _parse_countries("") == frozenset()
    assert _parse_countries(None) == frozenset()
    assert _parse_countries(math.nan) == frozenset()


def test_formulate_core_normalizes_country_for_direct_callers():
    """Core formulate() upper-cases country itself, so a lowercase direct call still flags."""
    res = formulate(
        species="Nile Tilapia",
        stage="< 5g (Starter)",
        production_system="General-LowCost",
        prices=DEMO_PRICES,
        country="zm",
    )
    if res.status != "optimal":
        pytest.skip(f"LP did not solve to optimal (status={res.status})")
    assert res.country == "ZM"
    assert all(isinstance(line.locally_available, bool) for line in res.recipe)


def test_country_never_changes_the_lp():
    """The country tag is advisory: identical prices must yield an identical recipe/cost."""
    common = dict(
        species="Nile Tilapia",
        stage="< 5g (Starter)",
        production_system="General-LowCost",
        prices=DEMO_PRICES,
    )
    base = formulate(**common)
    tagged = formulate(**common, country="ZM")
    if base.status != "optimal":
        pytest.skip(f"LP did not solve to optimal (status={base.status})")
    assert base.cost_per_kg == tagged.cost_per_kg
    assert (
        {(l.code, l.inclusion_percent) for l in base.recipe}
        == {(l.code, l.inclusion_percent) for l in tagged.recipe}
    )


def test_formulate_error_path_echoes_country():
    """Non-optimal responses still echo the requested country."""
    res = formulate(
        species="Nile Tilapia",
        stage="< 5g (Starter)",
        production_system="General-LowCost",
        prices={"00000000": 1.0},  # no overlap with the pool -> error status
        country="NG",
    )
    assert res.status == "error"
    assert res.country == "NG"


def test_supported_countries_match_request_literal():
    """Guard against drift between SUPPORTED_COUNTRIES and the FormulateRequest Literal."""
    from typing import get_args

    from fasa_core.config.defaults import SUPPORTED_COUNTRIES
    from fasa_core.models import FormulateRequest

    annotation = FormulateRequest.model_fields["country"].annotation
    literal = next(a for a in get_args(annotation) if a is not type(None))
    assert set(get_args(literal)) == set(SUPPORTED_COUNTRIES)


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


# --------------------------------------------------------------------------- #
# min/max inclusion layer                                                     #
# --------------------------------------------------------------------------- #


BASE = dict(
    species="Nile Tilapia",
    stage="< 5g (Starter)",
    production_system="General-LowCost",
    prices=DEMO_PRICES,
)


def _spec(res, code):
    return next(line for line in res.composition if line.code == code)


def test_limits_config_files_ship_without_data_rows():
    """The layer is wired but empty, so today's formulations are unchanged."""
    from fasa_core.inclusion_limits import ingredient_limit_rows, nutrient_limit_rows

    assert nutrient_limit_rows() == ()
    assert ingredient_limit_rows() == ()


def test_nutrient_limit_tighter_than_asns_replaces_the_target():
    """ASNS caps starter crude fibre at 7%; a 3% practice limit must bind instead."""
    res = formulate(**BASE, nutrient_limits={"PA05": {"max": 3.0}})
    fibre = _spec(res, "PA05")
    assert fibre.restriction_type == "Maximum"
    assert fibre.target == 3.0
    assert fibre.source == "asns+request"


def test_nutrient_limit_looser_than_asns_never_loosens_it():
    """A commercial 8% fibre ceiling must not relax the 7% ASNS requirement."""
    res = formulate(**BASE, nutrient_limits={"PA05": {"max": 8.0}})
    fibre = _spec(res, "PA05")
    assert fibre.target == 7.0
    assert fibre.source == "asns"


def test_nutrient_limit_adds_a_bound_asns_does_not_state():
    """ASNS has no ash ceiling for this stage; the limit layer supplies one."""
    res = formulate(**BASE, nutrient_limits={"PA06": {"max": 8.0}})
    ash = _spec(res, "PA06")
    assert (ash.restriction_type, ash.target, ash.source) == ("Maximum", 8.0, "request")


def test_nutrient_limit_on_a_ratio_spec_is_skipped_with_a_warning():
    res = formulate(**BASE, nutrient_limits={"ADPXF09": {"min": 30.0}})
    assert any("ratio spec" in w for w in res.warnings)


def test_nutrient_limit_is_not_masked_by_the_premix():
    """Zinc is premix-masked, but an explicit operator bound must still bind."""
    res = formulate(**BASE, premix_enabled=True, nutrient_limits={"M12": {"max": 250.0}})
    zinc = _spec(res, "M12")
    assert (zinc.restriction_type, zinc.target, zinc.source) == ("Maximum", 250.0, "request")


def test_ingredient_limit_floor_is_honored_and_echoed():
    """A minimum forces the ingredient in and the line reports the applied box."""
    res = formulate(**BASE, ingredient_limits={"10018": {"min": 0.05}})
    if res.status != "optimal":
        pytest.skip(f"LP did not solve to optimal (status={res.status})")
    line = next(l for l in res.recipe if l.code == "10018")
    assert line.inclusion_percent >= 5.0 - 1e-3
    assert line.min_inclusion_percent == 5.0
    assert line.limit_source == "request"


def test_ingredient_limit_ceiling_is_honored():
    res = formulate(**BASE, ingredient_limits={"31621": {"max": 0.15}})
    if res.status != "optimal":
        pytest.skip(f"LP did not solve to optimal (status={res.status})")
    line = next((l for l in res.recipe if l.code == "31621"), None)
    if line is not None:
        assert line.inclusion_percent <= 15.0 + 1e-3
        assert line.max_inclusion_percent == 15.0


def test_ingredient_zero_ceiling_excludes_a_priced_ingredient_and_warns():
    """'Do not recommend this, full stop' — the exclusion must be visible."""
    res = formulate(**BASE, ingredient_limits={"31605": {"max": 0.0}})
    assert all(line.code != "31605" for line in res.recipe)
    assert any("31605" in w or "Wheat bran" in w for w in res.warnings)


def test_ceilings_that_cannot_fill_the_feed_report_a_bound_conflict():
    """Bounds are variable boxes, not constraint rows, so the IIS cannot see them."""
    res = formulate(**BASE, ingredient_limits={c: {"max": 0.01} for c in DEMO_PRICES})
    assert res.status == "infeasible"
    assert res.infeasibility.iis_codes == []
    assert len(res.infeasibility.bound_conflicts) == 1
    assert "below" in res.infeasibility.bound_conflicts[0]


def test_floors_above_the_available_feed_mass_report_a_bound_conflict():
    limits = {c: {"min": 0.10} for c in list(DEMO_PRICES)[:12]}
    res = formulate(**BASE, ingredient_limits=limits)
    assert res.status == "infeasible"
    assert len(res.infeasibility.bound_conflicts) == 1
    assert "above" in res.infeasibility.bound_conflicts[0]


def test_a_binding_nutrient_limit_is_named_in_the_iis():
    """An infeasibility the limit layer caused must be attributable to it."""
    res = formulate(**BASE, nutrient_limits={"PA03": {"max": 20.0}})
    assert res.status == "infeasible"
    assert "PA03" in res.infeasibility.iis_codes
    assert any("[request]" in e for e in res.infeasibility.iis_explanations)


def test_limits_absent_leaves_the_recipe_and_the_box_untouched():
    """Wiring the layer in must not move today's baseline result."""
    base = formulate(**BASE)
    if base.status != "optimal":
        pytest.skip(f"LP did not solve to optimal (status={base.status})")
    assert all(line.limit_source is None for line in base.recipe)
    assert all(line.max_inclusion_percent is None for line in base.recipe)
    assert all(line.source == "asns" for line in base.composition)


def test_scope_resolution_prefers_the_most_specific_row(tmp_path):
    """A stage-scoped row beats a blanket one; ties fall to the tighter bound."""
    from fasa_core.inclusion_limits import LimitScope, _load, _resolve

    csv = tmp_path / "limits.csv"
    csv.write_text(
        "code,species,production_system,stage_weight,processing_method,"
        "min_inclusion,max_inclusion\n"
        "31605,,,,,,0.30\n"                       # blanket ceiling
        "31605,,,Starter,,,0.10\n"                # stage-specific: substring match
        "31605,Nile Tilapia,,,,,0.20\n"           # equally specific as the stage row
        "30355,,,,,0.05,\n"                       # floor only
    )
    rows = _load(csv, "code", "min_inclusion", "max_inclusion")
    resolved = _resolve(rows, LimitScope("Nile Tilapia", "< 5g (Starter)", "General-LowCost"))

    # two rows tie at specificity 1; the tighter ceiling wins
    assert resolved["31605"].maximum == 0.10
    assert resolved["31605"].minimum is None
    assert (resolved["30355"].minimum, resolved["30355"].maximum) == (0.05, None)


def test_scope_filters_exclude_non_matching_rows(tmp_path):
    from fasa_core.inclusion_limits import LimitScope, _load, _resolve

    csv = tmp_path / "limits.csv"
    csv.write_text(
        "code,species,production_system,stage_weight,processing_method,"
        "min_inclusion,max_inclusion\n"
        "31605,African Catfish,,,,,0.10\n"
        "30355,,,,extruded,,0.10\n"
    )
    rows = _load(csv, "code", "min_inclusion", "max_inclusion")
    tilapia = LimitScope("Nile Tilapia", "< 5g (Starter)", "General-LowCost")
    catfish = LimitScope("African Catfish", "< 5g (Starter)", "General", "extruded")
    assert _resolve(rows, tilapia) == {}
    assert set(_resolve(rows, catfish)) == {"31605", "30355"}


def test_limits_csv_rejects_an_inverted_bound(tmp_path):
    from fasa_core.inclusion_limits import _load

    csv = tmp_path / "limits.csv"
    csv.write_text(
        "code,species,production_system,stage_weight,processing_method,"
        "min_inclusion,max_inclusion\n"
        "31605,,,,,0.40,0.10\n"
    )
    with pytest.raises(ValueError, match="above maximum"):
        _load(csv, "code", "min_inclusion", "max_inclusion")


def test_request_limit_models_reject_invalid_pairs():
    from pydantic import ValidationError

    from fasa_core.models import IngredientInclusionLimit, NutrientLimit

    with pytest.raises(ValidationError):
        IngredientInclusionLimit(max=1.5)          # above 100% of feed
    with pytest.raises(ValidationError):
        IngredientInclusionLimit(min=0.4, max=0.1)  # inverted
    with pytest.raises(ValidationError):
        NutrientLimit(min=-1.0)                     # negative nutrient level


# --------------------------------------------------------------------------- #
# /validate-recipe: composition + inclusion-rate checks                       #
# --------------------------------------------------------------------------- #


def _lp_fractions(**overrides):
    """The LP's own recipe as a fractions dict, via the 4-dp percentages it publishes."""
    res = formulate(**{**BASE, **overrides})
    if res.status != "optimal":
        pytest.skip(f"LP did not solve to optimal (status={res.status})")
    return {line.code: line.inclusion_percent / 100.0 for line in res.recipe}


def test_validate_recipe_accepts_the_lp_solution_as_in_spec():
    """A recipe /formulate just returned must not read as non-compliant.

    Guards the `in_spec` tolerance: constraints the LP drives to exactly binding
    (and the DP/DE ratio, whose linearized target is 0) lose ~1e-5 when the
    published 4-decimal inclusion_percent values are fed back in.
    """
    from fasa_core.validator import validate_recipe

    res = validate_recipe(
        _lp_fractions(),
        parameters=["crude_protein_percent"],
        species=BASE["species"],
        stage=BASE["stage"],
        production_system=BASE["production_system"],
    )
    off_spec = [line.code for line in res.nutrient_checks if not line.in_spec]
    assert off_spec == []
    assert res.in_limits is True
    assert res.nutrient_checks, "nutrient checks should run when the full scope is given"
    assert 99.0 <= res.total_inclusion_percent <= 100.0


def test_validate_recipe_still_catches_a_real_nutrient_violation():
    """The tolerance must not be loose enough to pass an implausible diet."""
    from fasa_core.validator import validate_recipe

    res = validate_recipe(
        {"31621": 0.995},  # all wheat flour: nowhere near the protein/energy targets
        parameters=[],
        species=BASE["species"],
        stage=BASE["stage"],
        production_system=BASE["production_system"],
    )
    violations = {line.code for line in res.nutrient_checks if not line.in_spec}
    assert {"PA03", "ED02"} <= violations
    assert res.in_limits is False


def test_validate_recipe_flags_an_inclusion_above_its_ceiling():
    """The colleague's case: 40% bran against a 15% ceiling."""
    from fasa_core.validator import validate_recipe

    fractions = {"31605": 0.40, "31621": 0.595}
    res = validate_recipe(fractions, parameters=[], ingredient_limits={"31605": {"max": 0.15}})

    bran = next(line for line in res.inclusion_checks if line.code == "31605")
    assert bran.inclusion_percent == 40.0
    assert bran.max_inclusion_percent == 15.0
    assert bran.limit_source == "request"
    assert bran.in_limits is False
    assert res.in_limits is False
    # the unbounded ingredient is reported too, and passes
    other = next(line for line in res.inclusion_checks if line.code == "31621")
    assert (other.max_inclusion_percent, other.limit_source, other.in_limits) == (None, None, True)


def test_validate_recipe_flags_an_inclusion_below_its_floor():
    from fasa_core.validator import validate_recipe

    res = validate_recipe(
        {"10018": 0.01, "31621": 0.985},
        parameters=[],
        ingredient_limits={"10018": {"min": 0.05}},
    )
    line = next(c for c in res.inclusion_checks if c.code == "10018")
    assert (line.min_inclusion_percent, line.in_limits) == (5.0, False)


def test_validate_recipe_applies_a_nutrient_limit_tighter_than_asns():
    from fasa_core.validator import validate_recipe

    res = validate_recipe(
        _lp_fractions(),
        parameters=[],
        species=BASE["species"],
        stage=BASE["stage"],
        production_system=BASE["production_system"],
        nutrient_limits={"PA05": {"max": 0.5}},  # far below the achieved ~1.5%
    )
    fibre = next(line for line in res.nutrient_checks if line.code == "PA05")
    assert (fibre.target, fibre.source, fibre.in_spec) == (0.5, "asns+request", False)
    assert res.in_limits is False


def test_validate_recipe_without_scope_checks_inclusions_only():
    """Backward compatible: the original payload still returns composition."""
    from fasa_core.validator import validate_recipe

    res = validate_recipe({"30355": 0.5, "31237": 0.495},
                          parameters=["crude_protein_percent"])
    assert set(res.composition) == {"crude_protein_percent"}
    assert res.nutrient_checks == []
    assert len(res.inclusion_checks) == 2
    assert res.in_limits is True
    assert res.warnings == []


def test_validate_recipe_warns_when_the_scope_is_incomplete():
    from fasa_core.validator import validate_recipe

    res = validate_recipe({"30355": 0.995}, parameters=[], species=BASE["species"])
    assert res.nutrient_checks == []
    assert any("nutrient checks need" in w for w in res.warnings)


def test_validate_recipe_warns_when_inclusions_do_not_form_a_diet():
    from fasa_core.validator import validate_recipe

    res = validate_recipe({"30355": 0.5}, parameters=[])
    assert res.total_inclusion_percent == 50.0
    assert any(w.startswith("[mass]") for w in res.warnings)


def test_validate_recipe_warns_on_codes_outside_the_ingredient_pool():
    """Such codes still reach `composition` but can hold no limit — say so."""
    from fasa_core.validator import validate_recipe

    res = validate_recipe({"30355": 0.5, "31621": 0.495, "10073": 0.0},
                          parameters=[], ingredient_limits={"30355": {"max": 0.4}})
    assert not any(w.startswith("[skip]") for w in res.warnings)

    res = validate_recipe({"99999": 0.995}, parameters=[])
    assert any("99999" in w and w.startswith("[skip]") for w in res.warnings)


def test_validate_recipe_rejects_an_unknown_stage():
    from fasa_core.validator import validate_recipe

    with pytest.raises(ValueError, match="No ASNS constraints"):
        validate_recipe({"30355": 0.995}, parameters=[], species="Nile Tilapia",
                        stage="not-a-stage", production_system="General")
