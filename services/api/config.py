"""
FleetGuard Pulse - API Configuration Module.
Loads environment variables and provides structured settings for datastores,
auth, security, rate limiting, and ML model paths.
"""

import os
from typing import List, Optional
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()


class APISettings:
    """Central configuration for FleetGuard Pulse API."""

    def __init__(self):
        self.ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

        # Application Host & Port
        self.API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
        self.API_PORT: int = int(os.getenv("API_PORT", "8000"))

        # Authentication / Keycloak
        # In development mode, mock/local JWT tokens are allowed with a configured secret.
        # In production mode, external Keycloak issuer/audience and cryptographic signatures are strictly verified.
        self.AUTH_DEV_MODE: bool = os.getenv("AUTH_DEV_MODE", "true").lower() in ("true", "1", "yes")
        self.JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "fleetguard-dev-super-secret-jwt-key-32b-min!!")
        self.JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.JWT_ISSUER: str = os.getenv(
            "JWT_ISSUER", "https://auth.fleetguard.internal/realms/fleetguard"
        )
        self.JWT_AUDIENCE: str = os.getenv("JWT_AUDIENCE", "fleetguard-api")
        self.JWT_PUBLIC_KEY: Optional[str] = os.getenv("JWT_PUBLIC_KEY", None)

        # PostgreSQL 16 (Relational & pgvector)
        self.POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
        self.POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5433"))
        self.POSTGRES_DB: str = os.getenv("POSTGRES_DB", "fleetguard")
        self.POSTGRES_USER: str = os.getenv("POSTGRES_USER", "fleetguard_user")
        self.POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "fleetguard_dev_password")
        self.POSTGRES_POOL_MIN: int = int(os.getenv("POSTGRES_POOL_MIN", "2"))
        self.POSTGRES_POOL_MAX: int = int(os.getenv("POSTGRES_POOL_MAX", "20"))

        # Redis 7 (Hot state, caching, rate limiting)
        self.REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
        self.REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6380"))
        self.REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD") or None
        self.REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))

        # ClickHouse (Historical analytics)
        self.CLICKHOUSE_HOST: str = os.getenv("CLICKHOUSE_HOST", "localhost")
        self.CLICKHOUSE_PORT: int = int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123"))
        self.CLICKHOUSE_USER: str = os.getenv("CLICKHOUSE_USER", "default")
        self.CLICKHOUSE_PASSWORD: str = os.getenv("CLICKHOUSE_PASSWORD", "fleetguard_dev_password")
        self.CLICKHOUSE_DB: str = os.getenv("CLICKHOUSE_DB", "fleetguard_analytics")

        # Redpanda / Kafka
        self.REDPANDA_BOOTSTRAP_SERVERS: str = os.getenv("REDPANDA_BOOTSTRAP_SERVERS", "localhost:9092")
        self.REDPANDA_ALERT_TOPIC: str = os.getenv("REDPANDA_ALERT_TOPIC", "vehicle.alerts.v1")

        # Predictive ML Model Paths
        self.MODEL_PATH: str = os.getenv(
            "MODEL_PATH", "data/models/predictive_maintenance_model.joblib"
        )
        self.MODEL_METADATA_PATH: str = os.getenv(
            "MODEL_METADATA_PATH", "data/models/model_metadata.json"
        )
        self.RISK_CACHE_TTL_SECONDS: int = int(os.getenv("RISK_CACHE_TTL_SECONDS", "60"))

        # Rate Limiting
        self.RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
        self.RATE_LIMIT_REQUESTS_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "120"))

        # CORS
        raw_cors = os.getenv(
            "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:8000"
        )
        self.CORS_ORIGINS: List[str] = [origin.strip() for origin in raw_cors.split(",") if origin.strip()]

    @property
    def postgres_connection_dict(self) -> dict:
        return {
            "host": self.POSTGRES_HOST,
            "port": self.POSTGRES_PORT,
            "dbname": self.POSTGRES_DB,
            "user": self.POSTGRES_USER,
            "password": self.POSTGRES_PASSWORD,
        }


# Global singleton settings instance
settings = APISettings()
