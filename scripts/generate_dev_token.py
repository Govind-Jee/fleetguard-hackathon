#!/usr/bin/env python3
"""
Generate a short-lived or custom development JWT token for FleetGuard Pulse.
Writes to stdout or updates frontend/.env (git-ignored) for local developer convenience.
"""

import argparse
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import timedelta
from services.api.auth.jwt import create_access_token
from services.api.auth.models import UserRole


def main():
    parser = argparse.ArgumentParser(description="Generate local FleetGuard JWT dev token")
    parser.add_argument("--hours", type=int, default=8, help="Token validity in hours (default: 8)")
    parser.add_argument("--tenant-id", type=str, default="a0000000-0000-0000-0000-000000000001")
    parser.add_argument("--user-id", type=str, default="b0000000-0000-0000-0000-000000000001")
    parser.add_argument("--email", type=str, default="admin@metrotransit.com")
    parser.add_argument("--roles", nargs="+", default=["ADMIN", "DISPATCHER", "TECHNICIAN"])
    parser.add_argument("--write-frontend-env", action="store_true", help="Write token to frontend/.env")

    args = parser.parse_args()

    roles = [UserRole(r) for r in args.roles]

    token = create_access_token(
        user_id=args.user_id,
        tenant_id=args.tenant_id,
        email=args.email,
        roles=roles,
        expires_delta=timedelta(hours=args.hours),
    )

    if args.write_frontend_env:
        with open("frontend/.env", "w") as f:
            f.write(f"VITE_API_BASE_URL=/api\n")
            f.write(f"VITE_AUTH_TOKEN={token}\n")
        print("Updated frontend/.env with fresh development token (git-ignored).")
    else:
        print(token)


if __name__ == "__main__":
    main()
