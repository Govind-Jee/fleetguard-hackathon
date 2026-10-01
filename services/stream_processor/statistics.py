"""
FleetGuard Pulse - Real-Time Streaming Statistics

Implements mathematically rigorous, single-pass O(1) space and time algorithms:
- Welford's algorithm for online variance, standard deviation, and Z-score tracking.
- Exponentially Weighted Moving Average (EWMA) for noise reduction and trend detection.
"""

import math
from typing import Dict, Optional


class WelfordAccumulator:
    """
    Numerically stable online computation of sample mean, variance, and standard deviation.
    Based on B. P. Welford (1962). Complexity: O(1) time, O(1) space.
    """

    def __init__(self):
        self.count: int = 0
        self.mean: float = 0.0
        self.m2: float = 0.0

    def update(self, x: float) -> None:
        """Process a new observation x."""
        self.count += 1
        delta = x - self.mean
        self.mean += delta / self.count
        delta2 = x - self.mean
        self.m2 += delta * delta2

    @property
    def sample_variance(self) -> float:
        """Sample variance s^2 with Bessel's correction (n - 1)."""
        if self.count < 2:
            return 0.0
        return self.m2 / (self.count - 1)

    @property
    def standard_deviation(self) -> float:
        """Sample standard deviation s."""
        return math.sqrt(self.sample_variance)

    def z_score(self, x: float) -> float:
        """
        Compute how many standard deviations observation x is from the running mean.
        Returns 0.0 if insufficient samples (n < 3) or near-zero variance.
        """
        if self.count < 3:
            return 0.0
        std = self.standard_deviation
        if std < 1e-6:
            return 0.0
        return (x - self.mean) / std


class EWMASmoother:
    """
    Exponentially Weighted Moving Average (EWMA) filter.
    S_t = alpha * x_t + (1 - alpha) * S_{t-1}
    """

    def __init__(self, alpha: float = 0.2):
        if not (0.0 < alpha <= 1.0):
            raise ValueError(f"Alpha must be in (0.0, 1.0], got {alpha}")
        self.alpha: float = alpha
        self.value: Optional[float] = None

    def update(self, x: float) -> float:
        """Update and return smoothed value."""
        if self.value is None:
            self.value = x
        else:
            self.value = self.alpha * x + (1.0 - self.alpha) * self.value
        return self.value


class VehicleStreamingStats:
    """Maintains statistical trackers for a single vehicle across key telemetry sensors."""

    def __init__(self):
        self.welford_vibration = WelfordAccumulator()
        self.ewma_vibration = EWMASmoother(alpha=0.25)

        self.welford_coolant = WelfordAccumulator()
        self.ewma_coolant = EWMASmoother(alpha=0.15)

        self.welford_oil_pressure = WelfordAccumulator()
        self.ewma_oil_pressure = EWMASmoother(alpha=0.2)

        self.welford_cell_temp_delta = WelfordAccumulator()
        self.ewma_cell_temp_delta = EWMASmoother(alpha=0.2)

    def update_vibration(self, val: float) -> Dict[str, float]:
        """Update vibration stats and return summary dict."""
        self.welford_vibration.update(val)
        smoothed = self.ewma_vibration.update(val)
        return {
            "vibration_mean": self.welford_vibration.mean,
            "vibration_std": self.welford_vibration.standard_deviation,
            "vibration_z_score": self.welford_vibration.z_score(val),
            "vibration_smoothed": smoothed,
        }

    def update_coolant_temp(self, val: float) -> Dict[str, float]:
        """Update coolant temp stats and return summary dict."""
        self.welford_coolant.update(val)
        smoothed = self.ewma_coolant.update(val)
        return {
            "coolant_mean": self.welford_coolant.mean,
            "coolant_std": self.welford_coolant.standard_deviation,
            "coolant_z_score": self.welford_coolant.z_score(val),
            "coolant_smoothed": smoothed,
        }

    def update_oil_pressure(self, val: float) -> Dict[str, float]:
        """Update oil pressure stats and return summary dict."""
        self.welford_oil_pressure.update(val)
        smoothed = self.ewma_oil_pressure.update(val)
        return {
            "oil_pressure_mean": self.welford_oil_pressure.mean,
            "oil_pressure_std": self.welford_oil_pressure.standard_deviation,
            "oil_pressure_z_score": self.welford_oil_pressure.z_score(val),
            "oil_pressure_smoothed": smoothed,
        }

    def update_cell_temp_delta(self, val: float) -> Dict[str, float]:
        """Update cell temp delta stats and return summary dict."""
        self.welford_cell_temp_delta.update(val)
        smoothed = self.ewma_cell_temp_delta.update(val)
        return {
            "cell_delta_mean": self.welford_cell_temp_delta.mean,
            "cell_delta_std": self.welford_cell_temp_delta.standard_deviation,
            "cell_delta_z_score": self.welford_cell_temp_delta.z_score(val),
            "cell_delta_smoothed": smoothed,
        }


class StreamingStatsRegistry:
    """Registry managing streaming stats for all active vehicles."""

    def __init__(self):
        self._stats: Dict[str, VehicleStreamingStats] = {}

    def get_or_create(self, vin: str) -> VehicleStreamingStats:
        if vin not in self._stats:
            self._stats[vin] = VehicleStreamingStats()
        return self._stats[vin]
