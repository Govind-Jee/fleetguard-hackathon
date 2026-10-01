"""
FleetGuard Pulse - Redis-Backed API Rate Limiter.
Implements bounded sliding/fixed window request throttling per tenant or client IP.
Returns HTTP 429 when quota is exceeded.
"""

import logging
import time
from typing import Optional
from fastapi import Request
import jwt

from services.api.config import settings
from services.api.db import get_redis_client
from services.api.exceptions import RateLimitExceededError
from services.api.metrics import api_metrics

logger = logging.getLogger("fleetguard.api.rate_limit")


class RateLimiter:
    """Redis-backed rate limiter using minute-bucketed atomic counters."""

    def __init__(
        self,
        requests_per_minute: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        self._explicit_limit = requests_per_minute is not None
        self._custom_limit = requests_per_minute
        self._explicit_enabled = enabled

    @property
    def is_enabled(self) -> bool:
        if self._explicit_enabled is not None:
            return self._explicit_enabled
        return settings.RATE_LIMIT_ENABLED

    @property
    def limit(self) -> int:
        if self._explicit_limit and self._custom_limit is not None:
            return self._custom_limit
        return settings.RATE_LIMIT_REQUESTS_PER_MINUTE

    async def __call__(self, request: Request) -> None:
        if not self.is_enabled:
            return

        # Identify rate-limit subject: tenant_id if authenticated, else client IP
        subject = getattr(request.state, "tenant_id", None)
        if not subject:
            # Peek at Bearer token if present to scope by tenant even if auth dependency hasn't run yet
            auth_header = request.headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                raw_token = auth_header[7:].strip()
                try:
                    unverified_payload = jwt.decode(raw_token, options={"verify_signature": False})
                    subject = unverified_payload.get("tenant_id")
                except Exception:
                    pass

        if subject:
            rate_key = f"tenant:{subject}"
        else:
            client_host = request.client.host if request.client else "unknown"
            rate_key = f"ip:{client_host}"

        current_ts = int(time.time())
        current_minute = current_ts // 60
        redis_key = f"rate_limit:{rate_key}:{current_minute}"
        seconds_remaining_in_window = 60 - (current_ts % 60)
        current_limit = self.limit

        try:
            r = get_redis_client()
            pipe = r.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, 65)  # Slightly longer than 60s to ensure expiry
            results = pipe.execute()
            current_count = results[0]

            # Attach headers to request state for middleware injection
            request.state.rate_limit_limit = current_limit
            request.state.rate_limit_remaining = max(0, current_limit - current_count)
            request.state.rate_limit_reset = seconds_remaining_in_window

            if current_count > current_limit:
                api_metrics.record_rate_limit_rejection()
                logger.warning(
                    "Rate limit exceeded for %s: %d/%d reqs/min",
                    rate_key,
                    current_count,
                    current_limit,
                )
                raise RateLimitExceededError(
                    retry_after=seconds_remaining_in_window,
                    details={
                        "limit": current_limit,
                        "current": current_count,
                        "retry_after_seconds": seconds_remaining_in_window,
                    },
                )
        except RateLimitExceededError:
            raise
        except Exception as e:
            # Datastore failure should not block legitimate API traffic (fail-open for rate limiter)
            logger.error("Rate limiter Redis failure (failing open): %s", e)
            api_metrics.record_db_error("redis_rate_limit")
