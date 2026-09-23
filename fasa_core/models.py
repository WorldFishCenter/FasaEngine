"""Pydantic data classes used by both the engine and the FastAPI surface.

Keeping these in a dedicated module lets the API and the core engine share a
single source of truth for input/output shapes.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from .config.defaults import normalize_country


# ---------- inclusion limits (shared by request and response) --------------- #


class _Limit(BaseModel):
    """Base for the min/max pairs of the inclusion-limit layer."""

    model_config = ConfigDict(extra="forbid")

    min: Optional[float] = None
    max: Optional[float] = None

    @model_validator(mode="after")
    def _min_not_above_max(self):
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"min ({self.min}) must not exceed max ({self.max})")
        return self


class NutrientLimit(_Limit):
    """Bound on a dietary nutrient level. Values are in the ASNS unit for the spec
    code they are keyed by — % for proximates and amino acids, kcal/kg for energy,
    mg/kg for trace minerals, ppb for mycotoxins. Omit a side to leave it unbounded."""

    min: Optional[float] = Field(
        default=None, ge=0.0, description="Lower bound in this spec code's ASNS unit."
    )
    max: Optional[float] = Field(
        default=None, ge=0.0, description="Upper bound in this spec code's ASNS unit."
    )


class IngredientInclusionLimit(_Limit):
    """Bound on a single ingredient's inclusion, as a mass FRACTION of total feed in
    [0, 1] — 0.15 means 15% of the feed. Note the unit flip against the response,
    which reports the same bound as a percentage (`max_inclusion_percent: 15.0`).
    Omit a side to leave it unbounded."""

    min: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Lower bound as a mass fraction of total feed (0.05 = 5%).",
    )
    max: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Upper bound as a mass fraction of total feed (0.15 = 15%). 0 excludes the ingredient.",
    )


# ---------- request --------------------------------------------------------- #


class FormulateRequest(BaseModel):
    """JSON payload accepted by POST /formulate."""

    model_config = ConfigDict(extra="forbid")

    species: Literal["Nile Tilapia", "African Catfish"]
    stage: str = Field(
        ...,
        description="ASNS stage_weight label, e.g. '< 5g (Starter)'.",
        examples=["< 5g (Starter)"],
    )
    production_system: Literal["General-LowCost", "General"] = "General-LowCost"

    country: Optional[Literal["KE", "NG", "ZM"]] = Field(
        default=None,
        description=(
            "Optional ISO-2 country code (KE/NG/ZM). When supplied, each recipe line is "
            "flagged `locally_available` according to the pool's country tags. The LP is "
            "never restricted to local ingredients — this is an advisory highlight only."
        ),
        examples=["ZM"],
    )

    @field_validator("country", mode="before")
    @classmethod
    def _normalize_country(cls, v):
        """Accept lower/mixed-case ISO-2 codes (e.g. 'ke') by normalizing before validation."""
        return normalize_country(v) if isinstance(v, str) else v

    prices: Dict[str, float] = Field(
        ...,
        description=(
            "Mapping of FICD ingredient code (string) -> price per kg in the user's "
            "local currency. Only ingredients present in this mapping AND in the "
            "configured availability pool are eligible."
        ),
        min_length=1,
        max_length=300,
    )

    batch_size_kg: Optional[float] = Field(
        default=None,
        gt=0,
        le=1_000_000,
        description=(
            "Optional total batch size in kg. When supplied, the response includes "
            "per-ingredient quantity_kg, premix_quantity_kg, and total_cost. "
            "Omit to receive percent-only output."
        ),
    )

    processing_method: Literal["pelleted", "extruded"] = "pelleted"
    premix_enabled: bool = True
    premix_rate: float = Field(0.005, ge=0.0, lt=0.10)

    max_fishmeal_cost_share: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Optional cap on fish-meal cost share (fraction of total recipe cost). "
            "Omit (or send null) to apply no cap — cost alone then drives fish-meal "
            "inclusion. Kept as an opt-in advisory input for callers that want to "
            "force a sustainability ceiling."
        ),
    )
    max_binder_inclusion: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Optional cap on collective binder mass fraction. Omit (or send null) "
            "to apply no cap — appropriate when the binder product's manufacturer-"
            "recommended inclusion rate is unknown. Kept as an opt-in advisory input."
        ),
    )

    custom_premix_mask_codes: Optional[List[str]] = Field(
        default=None,
        description=(
            "Override the default premix mask. If provided, replaces the default "
            "list of ASNS spec codes whose constraints will be skipped."
        ),
        max_length=200,
    )

    nutrient_limits: Optional[Dict[str, NutrientLimit]] = Field(
        default=None,
        description=(
            "Per-request override of the nutrient inclusion-limit layer: ASNS spec code "
            "-> {min, max} in that code's ASNS unit (e.g. {'PA05': {'max': 8}} to hold "
            "crude fibre below 8% of the diet). An entry replaces the configured limit "
            "for that code. Where ASNS already states the same direction, the tighter "
            "value binds. Ratio specs are not supported and are skipped with a warning."
        ),
        max_length=300,
    )
    ingredient_limits: Optional[Dict[str, IngredientInclusionLimit]] = Field(
        default=None,
        description=(
            "Per-request override of the ingredient inclusion-limit layer: FICD "
            "ingredient code -> {min, max} as a mass fraction of total feed (e.g. "
            "{'31147': {'max': 0.2}} to cap rice bran at 20%). An entry replaces the "
            "configured limit for that ingredient. A max of 0 excludes the ingredient "
            "even when it is priced; a min only applies to priced ingredients."
        ),
        max_length=300,
    )


class ValidateRecipeRequest(BaseModel):
    """JSON payload accepted by POST /validate-recipe."""

    model_config = ConfigDict(extra="forbid")

    fractions: Dict[str, float] = Field(
        ...,
        description="FICD ingredient code -> mass fraction in [0, 1].",
        min_length=1,
        max_length=300,
    )
    parameters: List[str] | None = Field(
        default=None,
        description="FICD parameter names to report; null means all parameters.",
        max_length=300,
    )

    # Scope for the inclusion-limit layer. All optional so the endpoint keeps
    # working as a plain composition recompute when they are omitted; limit rows
    # with a blank scope column always apply, scoped rows need the matching value.
    species: Optional[Literal["Nile Tilapia", "African Catfish"]] = Field(
        default=None,
        description=(
            "Optional. Scopes the inclusion limits and, together with `stage` and "
            "`production_system`, enables the nutrient checks."
        ),
    )
    stage: Optional[str] = Field(
        default=None,
        description="Optional ASNS stage_weight label, e.g. '< 5g (Starter)'.",
        examples=["< 5g (Starter)"],
    )
    production_system: Optional[Literal["General-LowCost", "General"]] = Field(
        default=None,
        description="Optional. Required (with `species` and `stage`) for the nutrient checks.",
    )
    processing_method: Literal["pelleted", "extruded"] = Field(
        default="pelleted",
        description=(
            "Scopes the inclusion limits and selects the digestible-energy column "
            "used by the nutrient checks."
        ),
    )
    premix_enabled: bool = Field(
        default=True,
        description=(
            "Mirrors /formulate: when true the vitamin and trace-mineral specs the "
            "premix covers are excluded from the nutrient checks, since the premix's "
            "own contribution is not modelled."
        ),
    )

    nutrient_limits: Optional[Dict[str, NutrientLimit]] = Field(
        default=None,
        description=(
            "ASNS spec code -> {min, max} in that code's ASNS unit, e.g. "
            "{'PA05': {'max': 8}}. Overrides the configured limits for the codes named."
        ),
        max_length=300,
    )
    ingredient_limits: Optional[Dict[str, IngredientInclusionLimit]] = Field(
        default=None,
        description=(
            "FICD ingredient code -> {min, max} as a mass fraction of total feed in "
            "[0, 1], e.g. {'31605': {'max': 0.15}}. Overrides the configured limits "
            "for the codes named."
        ),
        max_length=300,
    )


# ---------- response -------------------------------------------------------- #


class IngredientLine(BaseModel):
    code: str
    description: str
    inclusion_percent: float
    cost_per_kg: float
    cost_contribution: float
    quantity_kg: Optional[float] = None
    # True/False when a `country` was requested; None when no country context was given.
    locally_available: Optional[bool] = None
    min_inclusion_percent: Optional[float] = Field(
        default=None,
        description=(
            "Inclusion floor applied to this ingredient, as a PERCENTAGE of feed "
            "(limits are sent as fractions but reported as percentages). "
            "Null when unbounded below."
        ),
    )
    max_inclusion_percent: Optional[float] = Field(
        default=None,
        description="Inclusion ceiling, as a percentage of feed. Null when unbounded above.",
    )
    limit_source: Optional[str] = Field(
        default=None,
        description=(
            "Where that bound came from: 'limits' (config table), 'request' (this call), "
            "or 'pool' (the generated pool fallback). Null when no limit applied."
        ),
    )


class NutrientLine(BaseModel):
    code: str
    spec_label: str
    restriction_type: Literal["Minimum", "Maximum", "Ratio"]
    target: Optional[float]
    achieved: Optional[float]
    unit: str
    in_spec: bool
    masked_by_premix: bool = False
    source: str = Field(
        default="asns",
        description=(
            "Where `target` came from: 'asns' (species requirement alone), "
            "'asns+limits'/'asns+request' (an ASNS target tightened by the inclusion-limit "
            "layer), or 'limits'/'request' (a bound ASNS does not state for this stage)."
        ),
    )


class InfeasibilityReport(BaseModel):
    """Returned only when the LP is infeasible at the supplied prices/pool."""

    iis_codes: List[str] = Field(..., description="Irreducible Inconsistent Subset of ASNS spec codes.")
    iis_explanations: List[str]
    suggestion: str
    bound_conflicts: List[str] = Field(
        default=[],
        description=(
            "Ingredient inclusion limits that cannot add up to the required feed mass. "
            "These are decision-variable bounds rather than constraint rows, so they "
            "are reported here instead of through `iis_codes`; when this list is "
            "populated the IIS is not computed."
        ),
    )


class FormulateResponse(BaseModel):
    status: Literal["optimal", "infeasible", "error"]
    species: str
    stage: str
    production_system: str
    processing_method: str

    # echoed back when a country was requested; null otherwise
    country: Optional[str] = None

    cost_per_kg: Optional[float] = None
    recipe: List[IngredientLine] = []
    composition: List[NutrientLine] = []
    warnings: List[str] = []
    infeasibility: Optional[InfeasibilityReport] = None

    # always echoed back so the API client can display them
    premix_enabled: bool
    premix_rate: float
    max_fishmeal_cost_share: Optional[float] = None
    max_binder_inclusion: Optional[float] = None

    # populated only when batch_size_kg was supplied on the request
    batch_size_kg: Optional[float] = None
    premix_quantity_kg: Optional[float] = None
    total_cost: Optional[float] = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class SupportedResponse(BaseModel):
    species: List[str]
    production_systems: List[str]
    countries: List[str]
    stages_by_species_and_system: Dict[str, Dict[str, List[str]]]


class IngredientLimitLine(BaseModel):
    """One supplied ingredient's inclusion checked against the limit layer.

    All three percent fields are PERCENTAGES of feed mass, while `fractions` and
    `ingredient_limits` on the request are fractions in [0, 1] — 0.15 in, 15.0 out.
    """

    code: str = Field(..., description="FICD ingredient code.")
    description: str = Field(..., description="Ingredient name.")
    inclusion_percent: float = Field(
        ..., description="The supplied inclusion, as a percentage of feed mass."
    )
    min_inclusion_percent: Optional[float] = Field(
        default=None, description="Applied floor, percent of feed; null when unbounded below."
    )
    max_inclusion_percent: Optional[float] = Field(
        default=None, description="Applied ceiling, percent of feed; null when unbounded above."
    )
    limit_source: Optional[str] = Field(
        default=None,
        description=(
            "Where the bound came from: 'limits' (config table), 'request' (this call), "
            "or 'pool' (the generated pool fallback). Null when no limit applied."
        ),
    )
    in_limits: bool = Field(
        ..., description="False when this inclusion falls outside the applied box."
    )


class ValidateRecipeResponse(BaseModel):
    composition: Dict[str, float] = Field(
        ..., description="Weighted nutrient composition per requested FICD parameter."
    )

    total_inclusion_percent: float = Field(
        default=0.0,
        description=(
            "Sum of the supplied fractions, as a percentage of feed mass. A complete "
            "diet sums to 100%, or 99-100% when a premix takes the remainder."
        ),
    )
    in_limits: bool = Field(
        default=True,
        description=(
            "True when every check that ran passed — the per-ingredient inclusion "
            "checks and, when they ran, the nutrient checks."
        ),
    )
    inclusion_checks: List[IngredientLimitLine] = Field(
        default=[], description="One line per supplied ingredient. Always populated."
    )
    nutrient_checks: List[NutrientLine] = Field(
        default=[],
        description=(
            "Achieved-vs-target per active constraint, same shape as /formulate's "
            "`composition`. Empty unless species, stage and production_system were all supplied."
        ),
    )
    warnings: List[str] = Field(
        default=[],
        description="Non-fatal notes: '[mass]' (fractions do not form a complete diet), '[skip]' (a check could not run).",
    )


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: str | None = None
