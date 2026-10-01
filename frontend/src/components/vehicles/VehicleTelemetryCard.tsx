import React from 'react';
import { TransientVehicleState, VehicleType } from '../../types/api';
import { HealthBadge } from '../common/Badge';
import { 
  Activity, 
  Gauge, 
  Thermometer, 
  Zap, 
  AlertTriangle, 
  Radio, 
  Clock, 
  MapPin, 
  Compass 
} from 'lucide-react';

interface VehicleTelemetryCardProps {
  state?: TransientVehicleState | null;
  vehicleType: VehicleType;
}

export const VehicleTelemetryCard: React.FC<VehicleTelemetryCardProps> = ({
  state,
  vehicleType,
}) => {
  if (!state) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 text-center text-slate-400">
        <Radio className="w-8 h-8 text-slate-600 mx-auto mb-2 animate-pulse" />
        <h4 className="font-semibold text-slate-300">Transient Telemetry Pending</h4>
        <p className="text-xs text-slate-500 mt-1">
          No live Redis telemetry frame received yet for this vehicle.
        </p>
      </div>
    );
  }

  const dtcCodes = state.dtc_codes || [];

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      {/* Header */}
      <div className="px-5 py-3.5 border-b border-slate-800 bg-slate-950/70 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-cyan-400" />
          <h3 className="font-semibold text-sm text-slate-100">Live CAN-Bus Telemetry Stream</h3>
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-950/70 text-emerald-400 border border-emerald-800/40">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping"></span>
            LIVE REDIS CACHE
          </span>
        </div>
        <div className="flex items-center gap-3">
          {state.health_status && <HealthBadge status={state.health_status} />}
        </div>
      </div>

      {/* Main Gauges Grid */}
      <div className="p-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {/* Speed */}
        <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
            <span className="flex items-center gap-1">
              <Gauge className="w-3.5 h-3.5 text-cyan-400" /> Speed
            </span>
            <span className="text-[10px] text-slate-500">km/h</span>
          </div>
          <div className="text-xl font-bold font-mono text-slate-100">
            {state.speed_kmh !== undefined && state.speed_kmh !== null
              ? state.speed_kmh.toFixed(1)
              : '—'}
          </div>
        </div>

        {/* Vibration */}
        <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
            <span className="flex items-center gap-1">
              <Activity className="w-3.5 h-3.5 text-indigo-400" /> Vibration
            </span>
            <span className="text-[10px] text-slate-500">g</span>
          </div>
          <div className="text-xl font-bold font-mono text-slate-100">
            {state.vibration !== undefined && state.vibration !== null
              ? state.vibration.toFixed(3)
              : '—'}
          </div>
        </div>

        {/* Odometer */}
        <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
            <span className="flex items-center gap-1">
              <Compass className="w-3.5 h-3.5 text-slate-400" /> Odometer
            </span>
            <span className="text-[10px] text-slate-500">km</span>
          </div>
          <div className="text-xl font-bold font-mono text-slate-100">
            {state.odometer_km !== undefined && state.odometer_km !== null
              ? state.odometer_km.toLocaleString(undefined, { maximumFractionDigits: 1 })
              : '—'}
          </div>
        </div>

        {/* Powertrain Specific: ICE / HEV */}
        {(vehicleType === 'ICE' || vehicleType === 'HEV') && (
          <>
            <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
              <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                <span className="flex items-center gap-1">
                  <Thermometer className="w-3.5 h-3.5 text-rose-400" /> Coolant Temp
                </span>
                <span className="text-[10px] text-slate-500">°C</span>
              </div>
              <div className="text-xl font-bold font-mono text-slate-100">
                {state.coolant_temp_c !== undefined && state.coolant_temp_c !== null
                  ? state.coolant_temp_c.toFixed(1)
                  : '—'}
              </div>
            </div>

            <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
              <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                <span className="flex items-center gap-1">
                  <Gauge className="w-3.5 h-3.5 text-amber-400" /> Oil Pressure
                </span>
                <span className="text-[10px] text-slate-500">kPa</span>
              </div>
              <div className="text-xl font-bold font-mono text-slate-100">
                {state.oil_pressure_kpa !== undefined && state.oil_pressure_kpa !== null
                  ? state.oil_pressure_kpa.toFixed(1)
                  : '—'}
              </div>
            </div>

            <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
              <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                <span className="flex items-center gap-1">
                  <Activity className="w-3.5 h-3.5 text-cyan-400" /> Engine RPM
                </span>
                <span className="text-[10px] text-slate-500">rpm</span>
              </div>
              <div className="text-xl font-bold font-mono text-slate-100">
                {state.engine_rpm !== undefined && state.engine_rpm !== null
                  ? Math.round(state.engine_rpm)
                  : '—'}
              </div>
            </div>
          </>
        )}

        {/* Powertrain Specific: BEV / HEV */}
        {(vehicleType === 'BEV' || vehicleType === 'HEV') && (
          <>
            <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
              <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                <span className="flex items-center gap-1">
                  <Zap className="w-3.5 h-3.5 text-emerald-400" /> Battery SOC
                </span>
                <span className="text-[10px] text-slate-500">%</span>
              </div>
              <div className="text-xl font-bold font-mono text-slate-100">
                {state.soc_pct !== undefined && state.soc_pct !== null
                  ? `${state.soc_pct.toFixed(1)}%`
                  : '—'}
              </div>
            </div>

            <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
              <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                <span className="flex items-center gap-1">
                  <Zap className="w-3.5 h-3.5 text-cyan-400" /> Pack Voltage
                </span>
                <span className="text-[10px] text-slate-500">V</span>
              </div>
              <div className="text-xl font-bold font-mono text-slate-100">
                {state.pack_voltage_v !== undefined && state.pack_voltage_v !== null
                  ? state.pack_voltage_v.toFixed(1)
                  : '—'}
              </div>
            </div>

            <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
              <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                <span className="flex items-center gap-1">
                  <Thermometer className="w-3.5 h-3.5 text-rose-400" /> Cell Temp Delta
                </span>
                <span className="text-[10px] text-slate-500">Δ°C</span>
              </div>
              <div className="text-xl font-bold font-mono text-slate-100">
                {state.cell_temp_delta_c !== undefined && state.cell_temp_delta_c !== null
                  ? `${state.cell_temp_delta_c.toFixed(2)}°C`
                  : '—'}
              </div>
            </div>
          </>
        )}
      </div>

      {/* DTC Diagnostic Codes & Sequence Metadata */}
      <div className="px-5 py-3 border-t border-slate-800/80 bg-slate-950/40 flex flex-wrap items-center justify-between gap-3 text-xs">
        {/* DTCs */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-slate-400 font-medium flex items-center gap-1">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400" /> Active DTCs:
          </span>
          {dtcCodes.length > 0 ? (
            dtcCodes.map((dtc) => (
              <span
                key={dtc}
                className="font-mono px-2 py-0.5 rounded bg-rose-950/80 text-rose-300 border border-rose-800/60 font-semibold"
              >
                {dtc}
              </span>
            ))
          ) : (
            <span className="text-emerald-400 font-mono text-xs">None (Healthy)</span>
          )}
        </div>

        {/* Telemetry frame details */}
        <div className="flex items-center gap-4 text-slate-500">
          {state.sequence_number !== undefined && state.sequence_number !== null && (
            <span className="font-mono">Seq #{state.sequence_number}</span>
          )}
          {state.timestamp && (
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {new Date(state.timestamp).toLocaleTimeString()}
            </span>
          )}
          {typeof state.latitude === 'number' && typeof state.longitude === 'number' && (
            <span className="flex items-center gap-1 font-mono text-[11px]">
              <MapPin className="w-3 h-3" />
              {state.latitude.toFixed(4)}, {state.longitude.toFixed(4)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
