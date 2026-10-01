"""
FleetGuard Pulse - API Standalone Server Entry Point.
Executes uvicorn server with production-ready settings.
"""

import uvicorn
from services.api.config import settings


def main():
    uvicorn.run(
        "services.api.app:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=True,
    )


if __name__ == "__main__":
    main()
