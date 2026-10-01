-- Initialize pgvector extension for diagnostic signature matching
CREATE EXTENSION IF NOT EXISTS vector;

-- Verification log
DO $$
BEGIN
    RAISE NOTICE 'pgvector extension successfully initialized for database %', current_database();
END $$;
