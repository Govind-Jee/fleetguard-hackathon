/**
 * FleetGuard Pulse — Centralized Token & Authentication Service.
 * Centralizes Bearer JWT resolution, local storage caching, and development identity.
 */

const TOKEN_KEY = 'fleetguard_access_token';

export interface UserIdentity {
  userId: string;
  tenantId: string;
  email: string;
  roles: string[];
}

export function getAuthToken(): string {
  if (typeof window !== 'undefined') {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (stored && stored.trim().length > 0) {
      return stored.trim();
    }
  }

  // Environment-driven development token (configured via VITE_AUTH_TOKEN in frontend/.env)
  const envToken = (import.meta as any).env?.VITE_AUTH_TOKEN;
  if (envToken && typeof envToken === 'string' && envToken.trim().length > 0) {
    return envToken.trim();
  }

  return '';
}

export function setAuthToken(token: string): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem(TOKEN_KEY, token.trim());
  }
}

export function clearAuthToken(): void {
  if (typeof window !== 'undefined') {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function getDecodedUser(): UserIdentity {
  const token = getAuthToken();
  if (token) {
    try {
      const parts = token.split('.');
      if (parts.length === 3) {
        const payload = JSON.parse(atob(parts[1]));
        return {
          userId: payload.sub || 'user-unknown',
          tenantId: payload.tenant_id || 'a0000000-0000-0000-0000-000000000001',
          email: payload.email || 'operator@metrotransit.com',
          roles: payload.roles || ['ADMIN', 'DISPATCHER', 'TECHNICIAN'],
        };
      }
    } catch {
      // Fallback if atob fails
    }
  }

  return {
    userId: 'b0000000-0000-0000-0000-000000000001',
    tenantId: 'a0000000-0000-0000-0000-000000000001',
    email: 'admin@metrotransit.com',
    roles: ['ADMIN', 'DISPATCHER', 'TECHNICIAN'],
  };
}
