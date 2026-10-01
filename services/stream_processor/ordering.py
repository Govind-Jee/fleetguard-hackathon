"""
FleetGuard Pulse - Out-Of-Order Event Protection

Ensures late-arriving or reordered telemetry messages do not overwrite current vehicle state.
Maintains monotonically increasing watermarks per VIN.
"""

import logging
from typing import Dict, Optional, Tuple
from services.stream_processor.metrics import default_metrics

logger = logging.getLogger("stream_processor.ordering")


class OutOfOrderProtector:
    """
    Tracks per-vehicle high-water marks for sequence numbers and timestamps.
    Prevents stale telemetry updates from overwriting hot state in Redis.
    """

    def __init__(self, redis_client=None, metrics=None):
        self.redis_client = redis_client
        self.metrics = metrics or default_metrics
        # In-memory fast cache for recent high water marks: vin -> (latest_seq, latest_timestamp)
        self._watermarks: Dict[str, Tuple[int, str]] = {}

    def check_and_update(
        self, vin: str, sequence_number: int, timestamp: str
    ) -> Tuple[bool, Optional[int]]:
        """
        Evaluate if the event is in-order compared to the latest known state.

        Args:
            vin: Standardized 17-character VIN.
            sequence_number: Monotonically increasing sequence number.
            timestamp: ISO-8601 UTC timestamp.

        Returns:
            Tuple of (is_in_order: bool, last_known_sequence: Optional[int])
            - True if sequence_number > last_known_sequence (or first event seen).
            - False if sequence_number <= last_known_sequence (out-of-order / stale).
        """
        last_seq, last_ts = self._get_watermark(vin)

        if last_seq is None:
            # First time seeing this VIN
            self._set_watermark(vin, sequence_number, timestamp)
            return True, None

        if sequence_number <= last_seq:
            # Out of order or stale re-delivery
            self.metrics.increment("events_out_of_order")
            logger.debug(
                "Detected out-of-order event for VIN %s: incoming seq %d <= current seq %d",
                vin,
                sequence_number,
                last_seq,
            )
            return False, last_seq

        # Newer event received! Update watermark
        gap = sequence_number - last_seq - 1
        if gap > 0:
            logger.debug(
                "Sequence gap for VIN %s: jumped from %d to %d (missing %d)",
                vin,
                last_seq,
                sequence_number,
                gap,
            )

        self._set_watermark(vin, sequence_number, timestamp)
        return True, last_seq

    def _get_watermark(self, vin: str) -> Tuple[Optional[int], Optional[str]]:
        """Fetch latest watermark from in-memory cache or Redis."""
        if vin in self._watermarks:
            return self._watermarks[vin]

        if self.redis_client:
            try:
                seq = self.redis_client.hget(f"vehicle:state:{vin}", "sequence_number")
                ts = self.redis_client.hget(f"vehicle:state:{vin}", "timestamp")
                if seq is not None:
                    parsed_seq = int(seq)
                    parsed_ts = ts.decode("utf-8") if isinstance(ts, bytes) else str(ts)
                    self._watermarks[vin] = (parsed_seq, parsed_ts)
                    return parsed_seq, parsed_ts
            except Exception as e:
                logger.warning("Redis watermark fetch failed for %s: %s", vin, e)

        return None, None

    def _set_watermark(self, vin: str, seq: int, ts: str) -> None:
        """Update watermark in memory."""
        self._watermarks[vin] = (seq, ts)
