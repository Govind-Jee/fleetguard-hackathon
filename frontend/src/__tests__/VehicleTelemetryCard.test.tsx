import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { VehicleTelemetryCard } from '../components/vehicles/VehicleTelemetryCard';
import { TransientVehicleState } from '../types/api';

const mockIceState: TransientVehicleState = {
  vin: '1HGCR2F83HA000001',
  speed_kmh: 65.4,
  odometer_km: 12543.2,
  vibration: 0.082,
  health_status: 'NOMINAL',
  coolant_temp_c: 88.5,
  oil_pressure_kpa: 310.2,
  engine_rpm: 2150.0,
  dtc_codes: ['P0115', 'P0300'],
  sequence_number: 1042,
  timestamp: '2026-03-31T12:00:00Z',
  latitude: 37.7749,
  longitude: -122.4194,
};

const mockBevState: TransientVehicleState = {
  vin: '1HGCR2F83HA000002',
  speed_kmh: 45.0,
  odometer_km: 8430.0,
  vibration: 0.025,
  health_status: 'NOMINAL',
  soc_pct: 78.4,
  pack_voltage_v: 395.2,
  cell_temp_delta_c: 1.45,
  dtc_codes: [],
  sequence_number: 502,
  timestamp: '2026-03-31T12:00:00Z',
};

describe('VehicleTelemetryCard', () => {
  it('renders pending placeholder when telemetry state is not provided', () => {
    render(<VehicleTelemetryCard state={null} vehicleType="ICE" />);
    expect(screen.getByText('Transient Telemetry Pending')).toBeInTheDocument();
  });

  it('renders ICE telemetry gauges and active DTC codes', () => {
    render(<VehicleTelemetryCard state={mockIceState} vehicleType="ICE" />);

    expect(screen.getByText('65.4')).toBeInTheDocument(); // Speed
    expect(screen.getByText('0.082')).toBeInTheDocument(); // Vibration
    expect(screen.getByText('88.5')).toBeInTheDocument(); // Coolant temp
    expect(screen.getByText('310.2')).toBeInTheDocument(); // Oil pressure
    expect(screen.getByText('2150')).toBeInTheDocument(); // Engine RPM
    expect(screen.getByText('P0115')).toBeInTheDocument(); // DTC 1
    expect(screen.getByText('P0300')).toBeInTheDocument(); // DTC 2
  });

  it('renders BEV electric gauges and healthy status when no DTCs', () => {
    render(<VehicleTelemetryCard state={mockBevState} vehicleType="BEV" />);

    expect(screen.getByText('78.4%')).toBeInTheDocument(); // Battery SOC
    expect(screen.getByText('395.2')).toBeInTheDocument(); // Pack Voltage
    expect(screen.getByText('1.45°C')).toBeInTheDocument(); // Cell Temp Delta
    expect(screen.getByText('None (Healthy)')).toBeInTheDocument();
  });
});
