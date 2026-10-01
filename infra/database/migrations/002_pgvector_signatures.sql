-- ==============================================================================
-- FleetGuard Pulse - Migration 002: pgvector Diagnostic Signatures Schema & HNSW
-- ==============================================================================

-- 1. Ensure pgvector extension is enabled
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Diagnostic Signatures Table
-- Stores standardized 16-dimensional telemetry vector representations of failure signatures
CREATE TABLE IF NOT EXISTS diagnostic_signatures (
    signature_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fault_type VARCHAR(100) NOT NULL,
    vehicle_type VARCHAR(10) NOT NULL CHECK (vehicle_type IN ('ICE', 'HEV', 'BEV')),
    description TEXT NOT NULL,
    feature_schema_version VARCHAR(20) NOT NULL DEFAULT '1.0',
    embedding vector(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. HNSW Index for Approximate Nearest Neighbor Vector Search
-- Uses Cosine Distance Metric (vector_cosine_ops)
-- m = 16 (bi-directional links per node), ef_construction = 64 (size of dynamic candidate list during build)
CREATE INDEX IF NOT EXISTS idx_diagnostic_signatures_hnsw 
ON diagnostic_signatures 
USING hnsw (embedding vector_cosine_ops) 
WITH (m = 16, ef_construction = 64);

-- 4. B-Tree filters on categorical fields
CREATE INDEX IF NOT EXISTS idx_diagnostic_signatures_fault_type ON diagnostic_signatures(fault_type);
CREATE INDEX IF NOT EXISTS idx_diagnostic_signatures_vehicle_type ON diagnostic_signatures(vehicle_type);
