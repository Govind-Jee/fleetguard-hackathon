"""
FleetGuard Pulse - Diagnostic Vector Search Service Layer.
Executes PostgreSQL 16 + pgvector HNSW cosine distance nearest-neighbor queries.
"""

import logging
from typing import List, Optional
import psycopg2

from services.api.exceptions import InvalidInputError
from services.api.schemas.diagnostics import (
    DiagnosticSignatureMatch,
    DiagnosticSimilarityResponse,
)

logger = logging.getLogger("fleetguard.api.services.diagnostic")


class DiagnosticService:

    @staticmethod
    def search_similar_signatures(
        conn: psycopg2.extensions.connection,
        query_vector: List[float],
        vehicle_type: Optional[str] = None,
        limit: int = 5,
    ) -> DiagnosticSimilarityResponse:
        """
        Query nearest diagnostic signatures using pgvector cosine distance (<=>).
        Strictly validates that vector dimension equals 16.
        """
        if len(query_vector) != 16:
            raise InvalidInputError(
                message=f"Query vector must have exactly 16 dimensions; received {len(query_vector)}",
                details={"expected_dimension": 16, "actual_dimension": len(query_vector)},
            )

        limit = min(20, max(1, limit))
        vector_str = f"[{','.join(f'{x:.6f}' for x in query_vector)}]"

        sql = """
        SELECT 
            signature_id, fault_type, vehicle_type, description, feature_schema_version,
            embedding <=> %s::vector AS cosine_distance
        FROM diagnostic_signatures
        WHERE (%s::varchar IS NULL OR vehicle_type = %s)
        ORDER BY embedding <=> %s::vector ASC
        LIMIT %s;
        """
        v_type_filter = vehicle_type.upper() if vehicle_type else None

        with conn.cursor() as cur:
            cur.execute(sql, (vector_str, v_type_filter, v_type_filter, vector_str, limit))
            rows = cur.fetchall()

        matches: List[DiagnosticSignatureMatch] = []
        for r in rows:
            dist = float(r[5])
            sim = max(0.0, 1.0 - dist)
            matches.append(
                DiagnosticSignatureMatch(
                    signature_id=str(r[0]),
                    fault_type=r[1],
                    vehicle_type=r[2],
                    description=r[3],
                    feature_schema_version=r[4],
                    cosine_distance=round(dist, 4),
                    similarity_score=round(sim, 4),
                )
            )

        return DiagnosticSimilarityResponse(
            query_vector_dimension=16,
            matches=matches,
        )
