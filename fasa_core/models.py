"""Pydantic data classes used by both the engine and the FastAPI surface.

Keeping these in a dedicated module lets the API and the core engine share a
single source of truth for input/output shapes.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict


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

    processing_method: Literal["pelleted", "extruded"] = "pelleted"
    premix_enabled: bool = True
    premix_rate: float = Field(0.005, ge=0.0, lt=0.10)

    max_fishmeal_cost_share: float = Field(0.20, ge=0.0, le=1.0)
    max_binder_inclusion:    float = Field(0.25, ge=0.0, le=1.0)

    custom_premix_mask_codes: Optional[List[str]] = Field(
        default=None,
        description=(
            "Override the default premix mask. If provided, replaces the default "
            "list of ASNS spec codes whose constraints will be skipped."
        ),
        max_length=200,
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


# ---------- response -------------------------------------------------------- #


class IngredientLine(BaseModel):
    code: str
    description: str
    inclusion_percent: float
    cost_per_kg: float
    cost_contribution: float


class NutrientLine(BaseModel):
    code: str
    spec_label: str
    restriction_type: Literal["Minimum", "Maximum", "Ratio"]
    target: Optional[float]
    achieved: Optional[float]
    unit: str
    in_spec: bool
    masked_by_premix: bool = False


class InfeasibilityReport(BaseModel):
    """Returned only when the LP is infeasible at the supplied prices/pool."""

    iis_codes: List[str] = Field(..., description="Irreducible Inconsistent Subset of ASNS spec codes.")
    iis_explanations: List[str]
    suggestion: str


class FormulateResponse(BaseModel):
    status: Literal["optimal", "infeasible", "error"]
    species: str
    stage: str
    production_system: str
    processing_method: str

    cost_per_kg: Optional[float] = None
    recipe: List[IngredientLine] = []
    composition: List[NutrientLine] = []
    warnings: List[str] = []
    infeasibility: Optional[InfeasibilityReport] = None

    # always echoed back so the API client can display them
    premix_enabled: bool
    premix_rate: float


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class SupportedResponse(BaseModel):
    species: List[str]
    production_systems: List[str]
    stages_by_species_and_system: Dict[str, Dict[str, List[str]]]


class ValidateRecipeResponse(BaseModel):
    composition: Dict[str, float]


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: str | None = None
