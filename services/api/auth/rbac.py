"""
FleetGuard Pulse - Role-Based Access Control (RBAC) Enforcer.
Provides FastAPI dependency factories enforcing locked roles: ADMIN, DISPATCHER, TECHNICIAN.
"""

from typing import Callable, Sequence
from fastapi import Depends

from services.api.auth.models import AuthenticatedUser, UserRole
from services.api.exceptions import InsufficientPermissionsError


def require_roles(*allowed_roles: UserRole) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    """
    FastAPI dependency factory enforcing that the authenticated principal
    possesses at least one of the specified allowed RBAC roles.
    """

    def role_checker(
        current_user: AuthenticatedUser = Depends(),  # Resolved via main dependency
    ) -> AuthenticatedUser:
        if not allowed_roles:
            return current_user

        if not current_user.has_any_role(*allowed_roles):
            required = [r.value for r in allowed_roles]
            user_has = [r.value for r in current_user.roles]
            raise InsufficientPermissionsError(
                message=f"Action requires one of roles {required}; user only has {user_has}",
                details={"required_roles": required, "user_roles": user_has},
            )
        return current_user

    return role_checker
