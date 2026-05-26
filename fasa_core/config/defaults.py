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

# --- premix ---
DEFAULT_PREMIX_RATE = 0.005   # 0.5 % of total feed mass (industry-typical for vit/min premix)

# --- processing ---
DEFAULT_PROCESSING_METHOD = "pelleted"   # "pelleted" | "extruded"

# --- safety / sanity caps ---
# Both caps default to None (no constraint applied) — they are opt-in advisory
# inputs surfaced through the API for callers that want to force a ceiling.
# Toxicity (TX01–TX16) and ASNS nutrient limits remain the only fixed constraints.
DEFAULT_MAX_FISHMEAL_COST_SHARE: float | None = None
DEFAULT_MAX_BINDER_INCLUSION:    float | None = None
WARN_INGREDIENT_INCLUSION_THRESHOLD = 0.40   # log a soft warning above 40 % single-ingredient inclusion

# --- numerical tolerances ---
SOLUTION_FRACTION_TOL  = 1e-6   # ingredients below this fraction are dropped from the reported recipe
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
