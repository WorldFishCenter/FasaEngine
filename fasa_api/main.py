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

import logging
import os
import time
from pathlib import Path
from typing import Dict, List

from fastapi import Depends, FastAPI, Header, HTTPException, status

from fasa_core import __version__
from fasa_core.config.defaults import (
    ASNS_FILENAME,
    DEFAULT_DATA_DIR,
    FICD_FILENAME,
    PAFF_COMPOSITION_FILENAME,
    PAFF_FORMULATIONS_FILENAME,
    SUPPORTED_PRODUCTION_SYSTEMS,
    SUPPORTED_SPECIES,
)
from fasa_core.data_loader import list_supported_stages, load_ficd_wide
from fasa_core.models import (
    ErrorResponse,
    FormulateRequest,
    FormulateResponse,
    HealthResponse,
    SupportedResponse,
    ValidateRecipeRequest,
    ValidateRecipeResponse,
)
from fasa_core.optimizer import formulate
from fasa_core.validator import compute_composition

LOGGER = logging.getLogger("fasa_api")


def _error(code: str, message: str, details: str | None = None) -> dict:
    return {"code": code, "message": message, "details": details}


def _require_auth(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    required = os.getenv("FASA_REQUIRE_AUTH", "true").lower() == "true"
    if not required:
        return

    expected = os.getenv("FASA_API_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_error(
                "server_misconfigured",
                "FASA_API_TOKEN is not configured while auth is enabled.",
            ),
        )

    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    elif x_api_key:
        token = x_api_key.strip()

    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error("unauthorized", "Invalid or missing API token."),
        )


def _readiness_check() -> tuple[bool, str]:
    required_files = (
        ASNS_FILENAME,
        FICD_FILENAME,
        PAFF_FORMULATIONS_FILENAME,
        PAFF_COMPOSITION_FILENAME,
    )
    for filename in required_files:
        if not (Path(DEFAULT_DATA_DIR) / filename).exists():
            return False, f"Missing required data file: {filename}"
    try:
        load_ficd_wide()
    except Exception as exc:
        return False, f"Failed to preload FICD table: {exc}"
    return True, "ready"


app = FastAPI(
    title="FASA Feed Formulation Engine",
    version=__version__,
    description=(
        "Optimization service for low-cost, digestibility-aware aquaculture feed "
        "formulation in Sub-Saharan Africa. Backbone of the FASA digital application."
    ),
)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Liveness probe",
)
def health() -> HealthResponse:
    return {"status": "ok", "version": __version__}


@app.get(
    "/ready",
    response_model=HealthResponse,
    tags=["system"],
    summary="Readiness probe",
)
def ready() -> HealthResponse:
    ok, reason = _readiness_check()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error("not_ready", "Readiness checks failed.", reason),
        )
    return {"status": "ok", "version": __version__}


@app.get(
    "/supported",
    response_model=SupportedResponse,
    tags=["api"],
    summary="List supported species, systems, and stages",
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid token"},
        500: {"model": ErrorResponse, "description": "Configuration error"},
    },
)
def supported(_: None = Depends(_require_auth)) -> SupportedResponse:
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


@app.post(
    "/formulate",
    response_model=FormulateResponse,
    tags=["api"],
    summary="Run feed formulation optimization",
    responses={
        400: {"model": ErrorResponse, "description": "Bad request"},
        401: {"model": ErrorResponse, "description": "Missing or invalid token"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        500: {"model": ErrorResponse, "description": "Internal error"},
    },
)
def formulate_endpoint(
    req: FormulateRequest,
    _: None = Depends(_require_auth),
) -> FormulateResponse:
    started_at = time.perf_counter()
    LOGGER.info(
        "formulate.request species=%s stage=%s system=%s prices=%d premix_enabled=%s",
        req.species,
        req.stage,
        req.production_system,
        len(req.prices),
        req.premix_enabled,
    )
    if req.species not in SUPPORTED_SPECIES:
        raise HTTPException(
            status_code=400,
            detail=_error("unsupported_species", "Unsupported species in MVP.", req.species),
        )
    if req.production_system not in SUPPORTED_PRODUCTION_SYSTEMS:
        raise HTTPException(
            status_code=400,
            detail=_error(
                "unsupported_production_system",
                "Unsupported production system in MVP.",
                req.production_system,
            ),
        )

    try:
        result = formulate(
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
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        LOGGER.info(
            "formulate.result status=%s elapsed_ms=%.2f warnings=%d",
            result.status,
            elapsed_ms,
            len(result.warnings),
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=_error("invalid_request", "Formulation request is invalid.", str(e)),
        ) from e


@app.post(
    "/validate-recipe",
    response_model=ValidateRecipeResponse,
    tags=["api"],
    summary="Recompute composition for an explicit recipe",
    responses={
        400: {"model": ErrorResponse, "description": "Bad request"},
        401: {"model": ErrorResponse, "description": "Missing or invalid token"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
def validate_recipe(
    req: ValidateRecipeRequest,
    _: None = Depends(_require_auth),
) -> ValidateRecipeResponse:
    if any(v < 0.0 or v > 1.0 for v in req.fractions.values()):
        raise HTTPException(
            status_code=400,
            detail=_error("invalid_fraction", "All fraction values must be within [0,1]."),
        )
    df = compute_composition(req.fractions, parameters=req.parameters)
    return {"composition": df["value"].round(6).to_dict()}
