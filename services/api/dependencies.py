"""
FleetGuard Pulse - FastAPI Core Dependencies.
Provides injected datastore connections, authenticated principal resolution,
multi-tenant context isolation, and role authorization.
"""

from typing import Callable, Generator, List, Optional
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import psycopg2
import redis

from services.api.auth.jwt import verify_jwt_token
from services.api.auth.models import AuthenticatedUser, UserRole
from services.api.db import get_db_connection, get_redis_client
from services.api.exceptions import AuthenticationError, InsufficientPermissionsError
from services.api.rate_limit import RateLimiter

# Standard HTTP Bearer scheme
bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[psycopg2.extensions.connection, None, None]:
    """Dependency that yields a PostgreSQL connection checked out from the pool."""
    with get_db_connection() as conn:
        yield conn


def get_redis() -> redis.Redis:
    """Dependency that yields the Redis client singleton."""
    return get_redis_client()


def get_ch():
    """Dependency that yields the active ClickHouse client or raises DatabaseUnavailableError."""
    from services.api.db import get_clickhouse_client
    from services.api.exceptions import DatabaseUnavailableError
    ch = get_clickhouse_client()
    if ch is None:
        raise DatabaseUnavailableError("ClickHouse")
    return ch


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> AuthenticatedUser:
    """
    Extract and validate Bearer JWT token from Authorization header.
    Attaches authenticated principal and tenant_id to request state.
    """
    if not credentials or not credentials.credentials:
        raise AuthenticationError("Missing Authorization header with Bearer token")

    token = credentials.credentials
    user = verify_jwt_token(token)

    # Attach tenant context to request state for middleware and rate limiting
    request.state.tenant_id = user.tenant_id
    request.state.user = user

    return user


async def get_tenant_id(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> str:
    """Extract authenticated tenant_id isolation boundary."""
    return current_user.tenant_id


def require_roles(*allowed_roles: UserRole) -> Callable:
    """
    Dependency factory enforcing that authenticated user holds at least
    one of the specified roles (ADMIN, DISPATCHER, TECHNICIAN).
    """

    async def _role_guard(
        current_user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if not allowed_roles:
            return current_user

        if not current_user.has_any_role(*allowed_roles):
            req_names = [r.value for r in allowed_roles]
            user_names = [r.value for r in current_user.roles]
            raise InsufficientPermissionsError(
                message=f"Access denied. Requires one of roles: {req_names}. Principal has: {user_names}",
                details={"required_roles": req_names, "user_roles": user_names},
            )
        return current_user

    return _role_guard


# Standard rate limiter dependency
check_rate_limit = RateLimiter()
