"""
FleetGuard Pulse - Keycloak-Compatible JWT Token Validator.
Implements OIDC/OAuth2 bearer token verification with strict issuer,
audience, signature, and expiration validation.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
import jwt
from jwt.exceptions import (
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    PyJWTError,
)

from services.api.auth.models import AuthenticatedUser, UserRole
from services.api.config import settings
from services.api.exceptions import AuthenticationError

logger = logging.getLogger("fleetguard.api.jwt")

if settings.AUTH_DEV_MODE:
    logger.warning(
        "⚠️  SECURITY NOTICE: AUTH_DEV_MODE is ENABLED in API configuration. "
        "Local HMAC development tokens are accepted. DO NOT DEPLOY WITH AUTH_DEV_MODE=True IN PRODUCTION."
    )


def create_access_token(
    user_id: str,
    tenant_id: str,
    email: str,
    roles: List[UserRole],
    full_name: str = "Test User",
    expires_delta: Optional[timedelta] = None,
    issuer: Optional[str] = None,
    audience: Optional[str] = None,
    secret_key: Optional[str] = None,
) -> str:
    """
    Generate a signed JWT token matching Keycloak / OIDC standard claims.
    Used for local development, integration tests, and smoke testing.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(hours=2))

    payload: Dict[str, Any] = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "email": email,
        "name": full_name,
        "preferred_username": email,
        "iss": issuer or settings.JWT_ISSUER,
        "aud": audience or settings.JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        # Flat role list
        "roles": [r.value if isinstance(r, UserRole) else str(r) for r in roles],
        # Keycloak standard nested role structure
        "realm_access": {
            "roles": [r.value if isinstance(r, UserRole) else str(r) for r in roles]
        },
    }

    key = secret_key or settings.JWT_SECRET_KEY
    token = jwt.encode(payload, key, algorithm="HS256")
    return token


def verify_jwt_token(token: str) -> AuthenticatedUser:
    """
    Validate incoming Bearer JWT against configured cryptographic keys,
    issuer, audience, and expiration constraints.
    """
    if not token or not isinstance(token, str):
        raise AuthenticationError("Missing or empty bearer token")

    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    # Determine key and algorithm with safe failure in production mode
    if not settings.AUTH_DEV_MODE:
        if settings.JWT_PUBLIC_KEY:
            key = settings.JWT_PUBLIC_KEY
            algorithms = ["RS256"]
        elif settings.JWT_SECRET_KEY and settings.JWT_SECRET_KEY != "fleetguard-dev-super-secret-jwt-key-32b-min!!":
            key = settings.JWT_SECRET_KEY
            algorithms = [settings.JWT_ALGORITHM or "HS256"]
        else:
            # Production mode cannot silently fall back to default development secret
            raise AuthenticationError(
                "Production authentication misconfigured: cryptographic public key (RS256) or secure production secret required"
            )
    else:
        key = settings.JWT_SECRET_KEY
        algorithms = [settings.JWT_ALGORITHM, "HS256"]

    try:
        # Strict claim validation
        payload = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except ExpiredSignatureError:
        raise AuthenticationError("Authentication token has expired")
    except InvalidAudienceError:
        raise AuthenticationError("Token audience does not match configured API audience")
    except InvalidIssuerError:
        raise AuthenticationError("Token issuer does not match configured Identity Provider issuer")
    except (InvalidSignatureError, ImmatureSignatureError):
        raise AuthenticationError("Invalid token cryptographic signature")
    except PyJWTError as e:
        raise AuthenticationError(f"JWT validation failed: {str(e)}")
    except Exception as e:
        logger.error("Unexpected JWT decode failure: %s", e)
        raise AuthenticationError("Malformed or undecodable authentication token")

    # Extract claims
    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    email = payload.get("email") or payload.get("preferred_username") or "user@fleetguard.internal"
    full_name = payload.get("name") or "Fleet User"

    if not user_id or not tenant_id:
        raise AuthenticationError("Token is missing required 'sub' or 'tenant_id' identity claims")

    # Extract roles (supports both top-level 'roles' and Keycloak 'realm_access.roles')
    raw_roles = payload.get("roles") or []
    if not raw_roles and isinstance(payload.get("realm_access"), dict):
        raw_roles = payload.get("realm_access", {}).get("roles", [])

    parsed_roles: List[UserRole] = []
    for r in raw_roles:
        r_str = str(r).upper()
        if r_str in UserRole.__members__:
            parsed_roles.append(UserRole[r_str])

    return AuthenticatedUser(
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        email=str(email),
        full_name=str(full_name),
        roles=parsed_roles,
    )
