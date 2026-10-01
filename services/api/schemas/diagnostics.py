"""
FleetGuard Pulse - Diagnostic Vector Search Schemas.
Represents pgvector nearest-neighbor similarity search results over failure signatures.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class DiagnosticSignatureMatch(BaseModel):
    signature_id: str
    fault_type: str
    vehicle_type: str
    description: str
    cosine_distance: float
    similarity_score: float = Field(..., description="Cosine similarity score (1.0 - cosine_distance)")
    feature_schema_version: str = "1.0"


class DiagnosticSimilarityResponse(BaseModel):
    query_vector_dimension: int = 16
    matches: List[DiagnosticSignatureMatch]
    methodology: str = (
        "PostgreSQL pgvector cosine distance nearest-neighbor search over historical "
        "diagnostic fault signatures. Demonstrates embedding similarity search, not predictive ML."
    )
