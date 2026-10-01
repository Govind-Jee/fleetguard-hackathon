"""
FleetGuard Pulse - Authentication & Identity Domain Models.
Defines principal representations and locked RBAC roles.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class UserRole(str, Enum):
    """The locked canonical FleetGuard RBAC roles."""
    ADMIN = "ADMIN"
    DISPATCHER = "DISPATCHER"
    TECHNICIAN = "TECHNICIAN"


class AuthenticatedUser(BaseModel):
    """Validated principal identity attached to request state."""
    user_id: str
    tenant_id: str
    email: str
    full_name: Optional[str] = "Fleet User"
    roles: List[UserRole] = Field(default_factory=list)

    def has_role(self, role: UserRole) -> bool:
        """Check if user has a specific role."""
        return role in self.roles

    def has_any_role(self, *roles: UserRole) -> bool:
        """Check if user has any of the specified roles."""
        return any(r in self.roles for r in roles)
