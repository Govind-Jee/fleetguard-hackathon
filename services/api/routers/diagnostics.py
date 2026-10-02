"""
FleetGuard Pulse - Diagnostic Vector Search Router.
Exposes pgvector cosine similarity matching over CAN-bus diagnostic signatures.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
import psycopg2

from services.api.auth.models import AuthenticatedUser, UserRole
from services.api.dependencies import check_rate_limit, get_current_user, get_db, require_roles
from services.api.exceptions import InvalidInputError
from services.api.schemas.diagnostics import DiagnosticSimilarityResponse
from services.api.services.diagnostic_service import DiagnosticService

router = APIRouter(prefix="/diagnostics", tags=["Diagnostics"], dependencies=[Depends(check_rate_limit)])


@router.get(
    "/similar",
    response_model=DiagnosticSimilarityResponse,
    summary="Search Similar Diagnostic Signatures (pgvector)",
    description=(
        "Executes a cosine nearest-neighbor search against the 16-dimensional PostgreSQL pgvector "
        "catalog of known mechanical fault signatures. NOTE: This represents embedding similarity search, not predictive ML."
    ),
)
def get_similar_diagnostics(
    vector: str = Query(
        ...,
        description="Comma-separated 16-dimensional normalized telemetry embedding vector",
        examples=["0.64,2.05,0.59,0.86,3.75,0.49,-1.15,0.44,0.00,0.00,0.00,0.00,0.54,0.88,1.00,0.00"],
    ),
    vehicle_type: Optional[str] = Query(None, pattern="^(ICE|HEV|BEV)$", description="Optional powertrain filter"),
    limit: int = Query(5, ge=1, le=20, description="Max nearest neighbors to retrieve"),
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.TECHNICIAN, UserRole.ADMIN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    try:
        cleaned = vector.strip("[]() \t\n")
        parsed_vector = [float(x.strip()) for x in cleaned.split(",") if x.strip()]
    except Exception as e:
        raise InvalidInputError(
            message="Vector parameter must be a valid comma-separated list of 16 floating-point numbers",
            details={"error": str(e)},
        )

    return DiagnosticService.search_similar_signatures(
        conn=conn,
        query_vector=parsed_vector,
        vehicle_type=vehicle_type,
        limit=limit,
    )
