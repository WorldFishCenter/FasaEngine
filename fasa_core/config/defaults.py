"""Engine-wide numeric defaults. Override via API request payload."""

from pathlib import Path

# --- file system ---
PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = PACKAGE_ROOT / "data"

ASNS_FILENAME = "ASNS_nutrition_specification_database.csv"
FICD_FILENAME = "FICD_feed_ingredient_composition_database.csv"
PAFF_FORMULATIONS_FILENAME = (
    "PAFF_practical_aquaculture_feed_formulation_database_Feed_Formulations.csv"
)
PAFF_COMPOSITION_FILENAME = (
    "PAFF_practical_aquaculture_feed_formulation_database_Calculated_Composition.csv"
)

# --- production scope ---
SUPPORTED_SPECIES = ("Nile Tilapia", "African Catfish")
SUPPORTED_PRODUCTION_SYSTEMS = ("General-LowCost", "General")

# Countries with local-availability tags in the ingredient pool (ISO-2). Used to
# validate the optional `/formulate` `country` field and surfaced via `/supported`.
# The LP is never restricted by country — the tag only flags `locally_available`.
SUPPORTED_COUNTRIES = ("KE", "NG", "ZM")


def normalize_country(value: "str | None") -> "str | None":
    """Canonicalize an ISO-2 country code: strip + upper-case; blank/None → None.

    Single source of truth for country-code normalization, shared by the API
    request validator, the core `formulate()` entry point, and the pool loader.
    """
    return ((value or "").strip().upper() or None)

def as_percent(value: "float | None") -> "float | None":
    """Mass fraction → percent of feed, at the precision the API reports inclusions.

    Single source of truth for the fraction→percent rule, shared by the optimizer's
    recipe lines and the validator's inclusion checks; None passes through.
    """
    return None if value is None else round(value * 100.0, 4)


# --- premix ---
# Every feed carries a vitamin/mineral premix. It is modelled as a fixed slice of the
# feed that supplies the vitamins and trace minerals listed in premix_mask.json (their
# constraints are skipped) and adds nothing else: its own nutrients are not counted.
# Moving to a real premix with a known composition means crediting its nutrients in
# constraint_builder (the `constant` term) and trimming the mask to what it covers.
PREMIX_RATES = (0.01, 0.015, 0.02)   # the rates a caller may choose: 1, 1.5 or 2 % of feed
DEFAULT_PREMIX_RATE = 0.02


def check_premix_rate(rate: float) -> float:
    """Return `rate` if it is one of PREMIX_RATES, else raise ValueError.

    Single source of truth for the premix-rate rule, shared by the API request
    validator and the core `formulate()` entry point.
    """
    if rate not in PREMIX_RATES:
        raise ValueError(f"premix_rate must be one of {list(PREMIX_RATES)}")
    return rate

# --- processing ---
DEFAULT_PROCESSING_METHOD = "pelleted"   # "pelleted" | "extruded"

# --- soft warnings ---
WARN_INGREDIENT_INCLUSION_THRESHOLD = 0.40   # log a soft warning above 40 % single-ingredient inclusion

# --- numerical tolerances ---
SOLUTION_FRACTION_TOL  = 1e-6   # ingredients below this fraction are dropped from the reported recipe

# `in_spec` tolerance for achieved-vs-target:
#     tol = ABS + REL*|target| + INPUT*Σ|a_i|
# An absolute epsilon alone is wrong for two reasons. A linearized ratio (DP/DE) has
# target = 0 with coefficients in the hundreds, and energy rows carry coefficients in
# the thousands — so the meaningful error scale is the row's own coefficients, not 1e-6.
# The INPUT term is the dominant one: it budgets for quantization of the caller's
# fractions, which matters because the API publishes inclusion_percent at 4 decimals
# (a 1e-6 quantum in fraction terms) and /validate-recipe accepts those values back.
# Without it, a recipe that /formulate just returned reads as out of spec on any
# exactly-binding constraint. 2e-6 is 4x the 5e-7 worst-case half-quantum per
# ingredient; even on the largest rows the resulting tolerance stays physically
# negligible (~0.07 kcal on a 3243 kcal/kg energy minimum).
IN_SPEC_ABS_TOL        = 1e-6
IN_SPEC_REL_TOL        = 1e-9
IN_SPEC_INPUT_TOL      = 2e-6
VALIDATION_REL_TOL     = 0.02   # 2 % — relaxed from 0.1 % because PAFF Calculated_Composition is
                                # published with 2-decimal precision; rounding alone consumes
                                # ~0.5 % at our 5-7 % ash / fibre values. 2 % rejects real
                                # column-mapping bugs while tolerating PAFF rounding & minor
                                # FICD-source-version drift. Unit-conversion bugs would still
                                # be caught (those produce 10× / 100× errors).

# --- solver ---
# Use PuLP's in-process HiGHS binding ("HiGHS"); fall back to bundled CBC.
DEFAULT_SOLVER = "HiGHS"   # PuLP solver identifier
SOLVER_TIME_LIMIT_SECONDS = 30
