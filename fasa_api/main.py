"""FastAPI surface for the FASA feed formulation engine.

Run locally:
    uvicorn fasa_api.main:app --reload --port 8000

Endpoints:
    GET  /health                                    liveness probe
    GET  /supported                                 enumerate species/stages/systems
    POST /formulate                                 run the LP
    POST /validate-recipe                           recompute composition for an explicit recipe
"""

from __future__ import annotations

from typing import Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from fasa_core import __version__
from fasa_core.config.defaults import (
    SUPPORTED_PRODUCTION_SYSTEMS,
    SUPPORTED_SPECIES,
)
from fasa_core.data_loader import list_supported_stages
from fasa_core.models import FormulateRequest, FormulateResponse
from fasa_core.optimizer import formulate
from fasa_core.validator import compute_composition

app = FastAPI(
    title="FASA Feed Formulation Engine",
    version=__version__,
    description=(
        "Optimization service for low-cost, digestibility-aware aquaculture feed "
        "formulation in Sub-Saharan Africa. Backbone of the FASA digital application."
    ),
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/supported")
def supported() -> dict:
    out: Dict[str, Dict[str, List[str]]] = {}
    for sp in SUPPORTED_SPECIES:
        out[sp] = {}
        for sys in SUPPORTED_PRODUCTION_SYSTEMS:
            try:
                out[sp][sys] = list_supported_stages(sp, sys)
            except Exception:
                out[sp][sys] = []
    return {"species": SUPPORTED_SPECIES,
            "production_systems": SUPPORTED_PRODUCTION_SYSTEMS,
            "stages_by_species_and_system": out}


@app.post("/formulate", response_model=FormulateResponse)
def formulate_endpoint(req: FormulateRequest) -> FormulateResponse:
    if req.species not in SUPPORTED_SPECIES:
        raise HTTPException(status_code=400,
                            detail=f"Unsupported species in MVP: {req.species}")
    if req.production_system not in SUPPORTED_PRODUCTION_SYSTEMS:
        raise HTTPException(status_code=400,
                            detail=f"Unsupported production system in MVP: {req.production_system}")

    try:
        return formulate(
            species=req.species,
            stage=req.stage,
            production_system=req.production_system,
            prices=req.prices,
            processing_method=req.processing_method,
            premix_enabled=req.premix_enabled,
            premix_rate=req.premix_rate,
            max_fishmeal_cost_share=req.max_fishmeal_cost_share,
            max_binder_inclusion=req.max_binder_inclusion,
            custom_premix_mask_codes=req.custom_premix_mask_codes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# --------- ad-hoc composition lookup --------------------------------------- #


class ValidateRecipeRequest(BaseModel):
    fractions: Dict[str, float]            # FICD code -> mass fraction (0..1)
    parameters: List[str] | None = None    # FICD parameter names to report; None = all


@app.post("/validate-recipe")
def validate_recipe(req: ValidateRecipeRequest) -> dict:
    df = compute_composition(req.fractions, parameters=req.parameters)
    return df["value"].round(6).to_dict()
