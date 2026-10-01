"""
FleetGuard Pulse - Telemetry Event Schema Validator

Validates incoming raw telemetry records against the authoritative Pydantic TelemetryEvent schema.
Handles malformed JSON and schema mismatches gracefully without crashing the processing pipeline.
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple, Union
from pydantic import ValidationError

from services.simulator.schema import TelemetryEvent
from services.stream_processor.metrics import default_metrics

logger = logging.getLogger("stream_processor.validator")


class TelemetryValidator:
    """Validates raw event payloads against TelemetryEvent Pydantic schema."""

    def __init__(self, metrics=None):
        self.metrics = metrics or default_metrics

    def validate(
        self, raw_data: Union[str, bytes, Dict[str, Any]]
    ) -> Tuple[Optional[TelemetryEvent], Optional[str]]:
        """
        Validate incoming raw telemetry data.

        Args:
            raw_data: JSON string, bytes, or parsed dictionary.

        Returns:
            Tuple of (TelemetryEvent if valid else None, error_message if invalid else None)
        """
        self.metrics.increment("events_received")

        # 1. Parse JSON if string or bytes
        if isinstance(raw_data, (str, bytes)):
            try:
                data_dict = json.loads(raw_data)
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                self.metrics.increment("events_invalid")
                error_msg = f"JSON decode failure: {str(err)}"
                logger.warning("Dropped malformed payload: %s", error_msg)
                return None, error_msg
        elif isinstance(raw_data, dict):
            data_dict = raw_data
        else:
            self.metrics.increment("events_invalid")
            error_msg = f"Unsupported data type: {type(raw_data).__name__}"
            logger.warning("Dropped unexpected type: %s", error_msg)
            return None, error_msg

        # 2. Validate against Pydantic schema
        try:
            event = TelemetryEvent.model_validate(data_dict)
            self.metrics.increment("events_valid")
            return event, None
        except ValidationError as err:
            self.metrics.increment("events_invalid")
            # Create a concise error summary
            error_details = "; ".join(
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in err.errors()
            )
            error_msg = f"Schema validation error: {error_details}"
            logger.warning("Dropped invalid schema event: %s", error_msg)
            return None, error_msg
        except Exception as err:
            self.metrics.increment("events_invalid")
            error_msg = f"Unexpected validation exception: {str(err)}"
            logger.error("Unexpected error validating event: %s", error_msg, exc_info=True)
            return None, error_msg
