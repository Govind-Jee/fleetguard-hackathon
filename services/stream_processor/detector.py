"""
FleetGuard Pulse - Real-Time Health & Anomaly Detector

Deterministic multi-powertrain rules engine evaluating real-time vehicle health.
Detects critical mechanical, electrical, and thermal anomalies across ICE, HEV, and BEV architectures.
"""

import logging
import uuid
from typing import Dict, List, Optional, Tuple

from services.simulator.schema import TelemetryEvent, VehicleType
from services.stream_processor.models import AlertSeverity, CriticalAlert
from services.stream_processor.statistics import VehicleStreamingStats
from services.stream_processor.metrics import default_metrics

logger = logging.getLogger("stream_processor.detector")

# Critical & Warning DTC registries
CRITICAL_DTCS = {
    "P0217": "Engine Coolant Overtemperature Condition",
    "P0524": "Engine Oil Pressure Too Low",
    "P0A80": "Replace Hybrid/EV Battery Pack",
    "P0A78": "Drive Motor Inverter Performance Anomaly",
    "P0300": "Random/Multiple Cylinder Misfire Detected",
    "P0A1F": "Battery Energy Control Module Internal Fault",
}

WARNING_DTCS = {
    "P0117": "Engine Coolant Temperature Sensor 1 Circuit Low",
    "P0128": "Coolant Thermostat (Coolant Temp Below Regulating Temp)",
    "P0171": "System Too Lean (Bank 1)",
    "P0420": "Catalyst System Efficiency Below Threshold",
    "P0A0F": "Engine Failed to Start in Hybrid Mode",
}


class HealthAnomalyDetector:
    """Evaluates telemetry events and streaming stats against powertrain-specific health thresholds."""

    def __init__(self, metrics=None):
        self.metrics = metrics or default_metrics

    def evaluate(
        self, event: TelemetryEvent, stats: Optional[VehicleStreamingStats] = None
    ) -> Tuple[AlertSeverity, List[CriticalAlert]]:
        """
        Evaluate vehicle telemetry for anomalies and safety violations.

        Returns:
            Tuple of (Overall AlertSeverity: NORMAL/WARNING/CRITICAL, List of CriticalAlert payloads)
        """
        alerts: List[CriticalAlert] = []

        # 1. Kinematic & Vibration Check
        vibration_stats = stats.update_vibration(event.vibration) if stats else {}
        z_score = vibration_stats.get("vibration_z_score", 0.0)

        if event.vibration >= 4.0 or (z_score >= 3.5 and event.vibration >= 2.5):
            alerts.append(
                self._build_alert(
                    event=event,
                    severity=AlertSeverity.CRITICAL,
                    fault_type="EXCESSIVE_VIBRATION",
                    message=f"Severe structural vibration {event.vibration:.2f}G detected (Z-score: {z_score:.2f})",
                    snapshot={
                        "vibration": event.vibration,
                        "vibration_z_score": round(z_score, 2),
                        "speed_kmh": event.speed_kmh,
                    },
                )
            )
        elif event.vibration >= 2.0 or z_score >= 2.5:
            alerts.append(
                self._build_alert(
                    event=event,
                    severity=AlertSeverity.WARNING,
                    fault_type="ELEVATED_VIBRATION",
                    message=f"Elevated vibration {event.vibration:.2f}G detected (Z-score: {z_score:.2f})",
                    snapshot={
                        "vibration": event.vibration,
                        "vibration_z_score": round(z_score, 2),
                    },
                )
            )

        # 2. Powertrain-Specific Rules: ICE & HEV
        if event.vehicle_type in (VehicleType.ICE, VehicleType.HEV):
            # Coolant Temperature
            if event.coolant_temp_c is not None:
                if stats:
                    stats.update_coolant_temp(event.coolant_temp_c)
                if event.coolant_temp_c >= 115.0:
                    alerts.append(
                        self._build_alert(
                            event=event,
                            severity=AlertSeverity.CRITICAL,
                            fault_type="ENGINE_OVERHEAT",
                            message=f"Engine coolant temperature critical: {event.coolant_temp_c:.1f}°C (threshold: 115°C)",
                            snapshot={"coolant_temp_c": event.coolant_temp_c},
                        )
                    )
                elif event.coolant_temp_c >= 105.0:
                    alerts.append(
                        self._build_alert(
                            event=event,
                            severity=AlertSeverity.WARNING,
                            fault_type="COOLANT_TEMP_HIGH",
                            message=f"Engine coolant temperature elevated: {event.coolant_temp_c:.1f}°C (threshold: 105°C)",
                            snapshot={"coolant_temp_c": event.coolant_temp_c},
                        )
                    )

            # Oil Pressure (valid when engine running > 500 RPM)
            if (
                event.oil_pressure_kpa is not None
                and event.engine_rpm is not None
                and event.engine_rpm > 500.0
            ):
                if stats:
                    stats.update_oil_pressure(event.oil_pressure_kpa)
                if event.oil_pressure_kpa <= 80.0:
                    alerts.append(
                        self._build_alert(
                            event=event,
                            severity=AlertSeverity.CRITICAL,
                            fault_type="OIL_PRESSURE_CRITICAL_LOW",
                            message=f"Critical engine oil pressure loss: {event.oil_pressure_kpa:.1f} kPa at {event.engine_rpm:.0f} RPM",
                            snapshot={
                                "oil_pressure_kpa": event.oil_pressure_kpa,
                                "engine_rpm": event.engine_rpm,
                            },
                        )
                    )
                elif event.oil_pressure_kpa <= 150.0:
                    alerts.append(
                        self._build_alert(
                            event=event,
                            severity=AlertSeverity.WARNING,
                            fault_type="OIL_PRESSURE_LOW",
                            message=f"Low engine oil pressure: {event.oil_pressure_kpa:.1f} kPa at {event.engine_rpm:.0f} RPM",
                            snapshot={
                                "oil_pressure_kpa": event.oil_pressure_kpa,
                                "engine_rpm": event.engine_rpm,
                            },
                        )
                    )

        # 3. Powertrain-Specific Rules: BEV & HEV
        if event.vehicle_type in (VehicleType.BEV, VehicleType.HEV):
            # Battery Cell Temperature Delta (Thermal Runaway / Degradation)
            if event.cell_temp_delta_c is not None:
                if stats:
                    stats.update_cell_temp_delta(event.cell_temp_delta_c)
                if event.cell_temp_delta_c >= 8.0:
                    alerts.append(
                        self._build_alert(
                            event=event,
                            severity=AlertSeverity.CRITICAL,
                            fault_type="BATTERY_THERMAL_RUNAWAY_RISK",
                            message=f"Extreme battery cell temperature delta: {event.cell_temp_delta_c:.1f}°C (threshold: 8.0°C)",
                            snapshot={
                                "cell_temp_delta_c": event.cell_temp_delta_c,
                                "soc_pct": event.soc_pct,
                            },
                        )
                    )
                elif event.cell_temp_delta_c >= 5.0:
                    alerts.append(
                        self._build_alert(
                            event=event,
                            severity=AlertSeverity.WARNING,
                            fault_type="BATTERY_CELL_IMBALANCE",
                            message=f"Battery cell temperature imbalance: {event.cell_temp_delta_c:.1f}°C (threshold: 5.0°C)",
                            snapshot={
                                "cell_temp_delta_c": event.cell_temp_delta_c,
                                "soc_pct": event.soc_pct,
                            },
                        )
                    )

            # BEV State of Charge (SOC)
            if event.vehicle_type == VehicleType.BEV and event.soc_pct is not None:
                if event.soc_pct <= 5.0:
                    alerts.append(
                        self._build_alert(
                            event=event,
                            severity=AlertSeverity.CRITICAL,
                            fault_type="CRITICAL_LOW_SOC",
                            message=f"Traction battery critically depleted: {event.soc_pct:.1f}% SOC",
                            snapshot={"soc_pct": event.soc_pct},
                        )
                    )
                elif event.soc_pct <= 15.0:
                    alerts.append(
                        self._build_alert(
                            event=event,
                            severity=AlertSeverity.WARNING,
                            fault_type="LOW_BATTERY_SOC",
                            message=f"Traction battery low: {event.soc_pct:.1f}% SOC",
                            snapshot={"soc_pct": event.soc_pct},
                        )
                    )

        # 4. Diagnostic Trouble Code (DTC) Evaluations
        for dtc in event.dtc_codes:
            if dtc in CRITICAL_DTCS:
                alerts.append(
                    self._build_alert(
                        event=event,
                        severity=AlertSeverity.CRITICAL,
                        fault_type=f"DTC_CRITICAL_{dtc}",
                        message=f"Active critical DTC code {dtc}: {CRITICAL_DTCS[dtc]}",
                        snapshot={"dtc_code": dtc, "description": CRITICAL_DTCS[dtc]},
                    )
                )
            elif dtc in WARNING_DTCS:
                alerts.append(
                    self._build_alert(
                        event=event,
                        severity=AlertSeverity.WARNING,
                        fault_type=f"DTC_WARNING_{dtc}",
                        message=f"Active warning DTC code {dtc}: {WARNING_DTCS[dtc]}",
                        snapshot={"dtc_code": dtc, "description": WARNING_DTCS[dtc]},
                    )
                )

        # Determine overall severity
        has_critical = any(a.severity == AlertSeverity.CRITICAL for a in alerts)
        has_warning = any(a.severity == AlertSeverity.WARNING for a in alerts)

        if has_critical:
            overall = AlertSeverity.CRITICAL
        elif has_warning:
            overall = AlertSeverity.WARNING
        else:
            overall = AlertSeverity.NORMAL

        return overall, alerts

    def _build_alert(
        self,
        event: TelemetryEvent,
        severity: AlertSeverity,
        fault_type: str,
        message: str,
        snapshot: Dict[str, any],
    ) -> CriticalAlert:
        """Construct a validated CriticalAlert model and update counters."""
        if severity == AlertSeverity.CRITICAL:
            self.metrics.increment("alerts_critical")
        else:
            self.metrics.increment("alerts_warning")

        return CriticalAlert(
            alert_id=str(uuid.uuid4()),
            event_id=event.event_id,
            vin=event.vin,
            timestamp=event.timestamp,
            severity=severity,
            fault_type=fault_type,
            message=message,
            sequence_number=event.sequence_number,
            metrics_snapshot=snapshot,
        )
