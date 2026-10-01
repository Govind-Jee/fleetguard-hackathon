"""
FleetGuard Pulse - Vehicle Model & Physical State Simulation

Compact memory-conscious representation of 100K+ vehicles with deterministic
wear progression, sensor correlation, and noise injection.
"""

import math
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from services.simulator.schema import TelemetryEvent, VehicleHealthState, VehicleType


# Popular synthetic vehicle models
ICE_MODELS = ["Freightliner Cascadia", "Volvo VNL 860", "Peterbilt 579", "Kenworth T680", "Ford F-750"]
HEV_MODELS = ["Hino 195h", "Fuso Canter Eco Hybrid", "Volvo FE Hybrid", "Peterbilt 220EV-Hybrid"]
BEV_MODELS = ["Freightliner eCascadia", "Volvo VNR Electric", "BYD 8TT", "Lion6 Electric", "Tesla Semi"]

# Baseline geographic bounds for commercial depots (North American corridors)
DEPOTS = [
    {"depot_id": "DEPOT-ATL-01", "lat": 33.7490, "lon": -84.3880, "name": "Atlanta Logistics Hub"},
    {"depot_id": "DEPOT-CHI-02", "lat": 41.8781, "lon": -87.6298, "name": "Chicago Freight Center"},
    {"depot_id": "DEPOT-DFW-03", "lat": 32.7767, "lon": -96.7970, "name": "Dallas-Fort Worth Hub"},
    {"depot_id": "DEPOT-LAX-04", "lat": 34.0522, "lon": -118.2437, "name": "Los Angeles Inland Depot"},
    {"depot_id": "DEPOT-NYC-05", "lat": 40.7128, "lon": -74.0060, "name": "New York Metro Depot"},
]


@dataclass(slots=True)
class VehicleState:
    """
    Ultra-compact in-memory state representation for a single vehicle.
    Uses slots to minimize memory consumption over 100K+ concurrent simulated instances.
    """
    vehicle_id: int
    vin: str
    vehicle_type: VehicleType
    model: str
    model_year: int
    fleet_id: str
    depot_id: str
    maintenance_age_days: int
    vehicle_state_seed: int
    health_state: VehicleHealthState
    sequence_number: int
    latitude: float
    longitude: float
    odometer_km: float
    speed_kmh: float
    step: int


def generate_synthetic_vin(index: int, vehicle_type: VehicleType) -> str:
    """
    Generates a deterministic, standard 17-character synthetic VIN.
    Starts with '1FL' (FleetGuard Synthetic WMI) ensuring it cannot collide with real OEM VINs.
    """
    type_code = {"ICE": "C", "HEV": "H", "BEV": "E"}[vehicle_type.value]
    # Format: 1FL (3 chars) + Type (1 char) + Serial padded to 13 chars = 17 chars total
    serial = f"{index:013d}"
    return f"1FL{type_code}{serial}"


def create_initial_vehicle(index: int, seed: int = 42) -> VehicleState:
    """
    Deterministically initializes a single vehicle metadata and operational state.
    """
    rng = random.Random(seed + index * 31)
    
    # Powertrain distribution: 60% ICE, 20% HEV, 20% BEV
    roll = rng.random()
    if roll < 0.60:
        v_type = VehicleType.ICE
        model = rng.choice(ICE_MODELS)
    elif roll < 0.80:
        v_type = VehicleType.HEV
        model = rng.choice(HEV_MODELS)
    else:
        v_type = VehicleType.BEV
        model = rng.choice(BEV_MODELS)
        
    vin = generate_synthetic_vin(index, v_type)
    model_year = rng.randint(2018, 2024)
    fleet_id = f"FLEET-{(index % 25) + 1:03d}"
    depot = DEPOTS[index % len(DEPOTS)]
    depot_id = depot["depot_id"]
    maintenance_age_days = rng.randint(5, 180)
    vehicle_state_seed = rng.randint(100000, 999999)
    
    # Initial health state distribution: 82% Healthy, 12% Degradation, 4% Warning, 2% Failure
    health_roll = rng.random()
    if health_roll < 0.82:
        health = VehicleHealthState.HEALTHY
    elif health_roll < 0.94:
        health = VehicleHealthState.DEGRADATION
    elif health_roll < 0.98:
        health = VehicleHealthState.WARNING
    else:
        health = VehicleHealthState.FAILURE
        
    # Initial location placed within a 25 km radius of depot
    angle = rng.uniform(0, 2 * math.pi)
    dist_km = rng.uniform(0.5, 25.0)
    lat_offset = (dist_km / 111.0) * math.cos(angle)
    lon_offset = (dist_km / (111.0 * math.cos(math.radians(depot["lat"])))) * math.sin(angle)
    
    return VehicleState(
        vehicle_id=index,
        vin=vin,
        vehicle_type=v_type,
        model=model,
        model_year=model_year,
        fleet_id=fleet_id,
        depot_id=depot_id,
        maintenance_age_days=maintenance_age_days,
        vehicle_state_seed=vehicle_state_seed,
        health_state=health,
        sequence_number=1,
        latitude=round(depot["lat"] + lat_offset, 6),
        longitude=round(depot["lon"] + lon_offset, 6),
        odometer_km=round(rng.uniform(10000.0, 250000.0), 2),
        speed_kmh=round(rng.uniform(40.0, 95.0), 1),
        step=0,
    )


def simulate_telemetry_step(
    vehicle: VehicleState,
    rng: random.Random,
    noise_enabled: bool = True,
    dt_seconds: float = 1.0,
) -> TelemetryEvent:
    """
    Advances the vehicle state by one time step and generates a validated TelemetryEvent.
    Correlates sensor physics with vehicle health state and powertrain type.
    """
    vehicle.step += 1
    vehicle.sequence_number += 1
    
    # Kinematic movement
    # Speed perturbation around cruising speed
    target_speed = vehicle.speed_kmh + rng.uniform(-2.5, 2.5)
    vehicle.speed_kmh = max(0.0, min(120.0, round(target_speed, 1)))
    
    # Distance travelled in step
    dist_km = (vehicle.speed_kmh * (dt_seconds / 3600.0))
    vehicle.odometer_km = round(vehicle.odometer_km + dist_km, 3)
    
    # Spatial displacement (heading gently drifting)
    bearing_rad = (vehicle.step * 0.05 + vehicle.vehicle_id) % (2 * math.pi)
    lat_delta = (dist_km / 111.0) * math.cos(bearing_rad)
    lon_delta = (dist_km / (111.0 * math.cos(math.radians(vehicle.latitude)))) * math.sin(bearing_rad)
    
    if noise_enabled:
        lat_delta += rng.gauss(0.0, 0.00001)
        lon_delta += rng.gauss(0.0, 0.00001)
        
    vehicle.latitude = round(max(-89.9, min(89.9, vehicle.latitude + lat_delta)), 6)
    vehicle.longitude = round(max(-179.9, min(179.9, vehicle.longitude + lon_delta)), 6)
    
    # Health progression: 0.1% chance for a degrading vehicle to transition to warning or failure
    if vehicle.health_state == VehicleHealthState.DEGRADATION and rng.random() < 0.001:
        vehicle.health_state = VehicleHealthState.WARNING
    elif vehicle.health_state == VehicleHealthState.WARNING and rng.random() < 0.0005:
        vehicle.health_state = VehicleHealthState.FAILURE

    # Physical Sensor Correlation by Health State
    h = vehicle.health_state
    
    # 1. Vibration
    if h == VehicleHealthState.HEALTHY:
        base_vib = rng.uniform(0.15, 0.35)
    elif h == VehicleHealthState.DEGRADATION:
        base_vib = rng.uniform(0.55, 1.10)
    elif h == VehicleHealthState.WARNING:
        base_vib = rng.uniform(1.20, 2.10)
    else:  # FAILURE
        base_vib = rng.uniform(2.50, 4.20)
    if noise_enabled:
        base_vib += rng.gauss(0.0, 0.03)
    vibration = max(0.05, round(base_vib, 3))
    
    # Engine / Motor RPM correlated with speed
    engine_rpm = None
    motor_rpm = None
    if vehicle.vehicle_type in (VehicleType.ICE, VehicleType.HEV):
        if vehicle.speed_kmh < 5.0:
            engine_rpm = round(rng.uniform(650.0, 800.0), 1)  # Idle
        else:
            engine_rpm = round(1200.0 + (vehicle.speed_kmh / 100.0) * 1600.0 + rng.gauss(0.0, 30.0), 1)
            
    if vehicle.vehicle_type == VehicleType.BEV:
        motor_rpm = round((vehicle.speed_kmh / 100.0) * 6500.0 + rng.gauss(0.0, 40.0), 1)

    # Coolant Temperature & Oil Pressure (ICE / HEV)
    coolant_temp_c = None
    oil_pressure_kpa = None
    dtc_codes: List[str] = []
    
    if vehicle.vehicle_type in (VehicleType.ICE, VehicleType.HEV):
        if h == VehicleHealthState.HEALTHY:
            base_temp = rng.uniform(88.0, 93.0)
            base_oil = rng.uniform(320.0, 420.0)
        elif h == VehicleHealthState.DEGRADATION:
            base_temp = rng.uniform(95.0, 102.0)
            base_oil = rng.uniform(210.0, 280.0)
            if rng.random() < 0.2:
                dtc_codes.append("P0420")  # Catalyst System Efficiency Below Threshold
        elif h == VehicleHealthState.WARNING:
            base_temp = rng.uniform(103.0, 112.0)
            base_oil = rng.uniform(130.0, 190.0)
            dtc_codes.append("P0117")  # Engine Coolant Temperature Circuit Low
            if rng.random() < 0.5:
                dtc_codes.append("P0171")  # System Too Lean
        else:  # FAILURE
            base_temp = rng.uniform(116.0, 128.0)  # Severe overheating
            base_oil = rng.uniform(40.0, 75.0)     # Catastrophic pressure loss
            dtc_codes.extend(["P0524", "P0300"])   # Engine Oil Pressure Too Low, Random Misfire
            
        if noise_enabled:
            base_temp += rng.gauss(0.0, 0.4)
            base_oil += rng.gauss(0.0, 3.0)
            
        coolant_temp_c = round(base_temp, 2)
        oil_pressure_kpa = round(max(10.0, base_oil), 2)

    # Battery Signals (HEV / BEV)
    battery_voltage_v = None
    soc_pct = None
    pack_voltage_v = None
    cell_temp_delta_c = None
    
    if vehicle.vehicle_type == VehicleType.ICE:
        battery_voltage_v = round(13.8 + rng.gauss(0.0, 0.2), 2)
        
    elif vehicle.vehicle_type == VehicleType.HEV:
        battery_voltage_v = round(13.8 + rng.gauss(0.0, 0.2), 2)
        soc_pct = round(max(15.0, min(95.0, 65.0 + rng.uniform(-10.0, 10.0))), 1)
        
    elif vehicle.vehicle_type == VehicleType.BEV:
        # BEV State
        soc_pct = round(max(5.0, min(100.0, 75.0 - (vehicle.step * 0.01) % 70.0)), 1)
        pack_voltage_v = round(370.0 + (soc_pct / 100.0) * 50.0 + rng.gauss(0.0, 1.0), 1)
        
        if h == VehicleHealthState.HEALTHY:
            base_delta = rng.uniform(0.4, 1.6)
        elif h == VehicleHealthState.DEGRADATION:
            base_delta = rng.uniform(2.2, 4.2)
        elif h == VehicleHealthState.WARNING:
            base_delta = rng.uniform(5.0, 8.5)
            dtc_codes.append("P0A80")  # Replace Hybrid/EV Battery Pack Warning
        else:  # FAILURE
            base_delta = rng.uniform(11.0, 18.5)  # Thermal imbalance
            dtc_codes.extend(["P0A80", "P0A7F"])  # Battery Pack Deterioration
            
        if noise_enabled:
            base_delta += rng.gauss(0.0, 0.1)
        cell_temp_delta_c = round(max(0.1, base_delta), 2)

    now_iso = datetime.now(timezone.utc).isoformat()
    event_id = str(uuid.uuid4())

    return TelemetryEvent(
        schema_version="1.0",
        event_id=event_id,
        vin=vehicle.vin,
        timestamp=now_iso,
        sequence_number=vehicle.sequence_number,
        vehicle_type=vehicle.vehicle_type,
        latitude=vehicle.latitude,
        longitude=vehicle.longitude,
        speed_kmh=vehicle.speed_kmh,
        odometer_km=vehicle.odometer_km,
        vibration=vibration,
        dtc_codes=dtc_codes,
        oil_pressure_kpa=oil_pressure_kpa,
        coolant_temp_c=coolant_temp_c,
        engine_rpm=engine_rpm,
        battery_voltage_v=battery_voltage_v,
        soc_pct=soc_pct,
        pack_voltage_v=pack_voltage_v,
        motor_rpm=motor_rpm,
        cell_temp_delta_c=cell_temp_delta_c,
    )
