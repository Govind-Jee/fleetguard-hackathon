import React, { useEffect, useState, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../services/api';
import { 
  VehicleDetailResponse, 
  VehicleRiskResponse, 
  AlertRecord 
} from '../types/api';
import { PowertrainBadge, HealthBadge } from '../components/common/Badge';
import { VehicleTelemetryCard } from '../components/vehicles/VehicleTelemetryCard';
import { PredictiveRiskPanel } from '../components/vehicles/PredictiveRiskPanel';
import { VehicleMap } from '../components/vehicles/VehicleMap';
import { WorkOrderModal } from '../components/maintenance/WorkOrderModal';
import { AlertsList } from '../components/alerts/AlertsList';
import { ErrorAlert } from '../components/common/ErrorAlert';
import { 
  ArrowLeft, 
  Wrench, 
  RefreshCw, 
  Building2, 
  MapPin, 
  FileText,
  AlertTriangle 
} from 'lucide-react';

export const VehicleDetailsPage: React.FC = () => {
  const { vin } = useParams<{ vin: string }>();

  const [detail, setDetail] = useState<VehicleDetailResponse | null>(null);
  const [riskData, setRiskData] = useState<VehicleRiskResponse | null>(null);
  const [alerts, setAlerts] = useState<AlertRecord[]>([]);

  const [isLoadingDetail, setIsLoadingDetail] = useState<boolean>(true);
  const [isLoadingRisk, setIsLoadingRisk] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Work order modal state
  const [isWorkOrderOpen, setIsWorkOrderOpen] = useState<boolean>(false);

  const fetchVehicleData = useCallback(async () => {
    if (!vin) return;
    setIsLoadingDetail(true);
    setIsLoadingRisk(true);
    setError(null);

    // 1. Authoritative & Transient Details
    try {
      const detailRes = await api.getVehicleDetail(vin);
      setDetail(detailRes);
    } catch (err: any) {
      setError(err.message || `Failed to fetch vehicle detail for VIN ${vin}`);
    } finally {
      setIsLoadingDetail(false);
    }

    // 2. Predictive Risk Assessment
    try {
      const riskRes = await api.getVehicleRisk(vin);
      setRiskData(riskRes);
    } catch (err: any) {
      console.warn('Risk prediction unavailable for vehicle:', err);
    } finally {
      setIsLoadingRisk(false);
    }

    // 3. Vehicle Alerts
    try {
      const alertRes = await api.getAlerts({ vin, limit: 10 });
      setAlerts(alertRes.items);
    } catch (err: any) {
      console.warn('Failed to load vehicle alerts:', err);
    }
  }, [vin]);

  useEffect(() => {
    fetchVehicleData();
  }, [fetchVehicleData]);

  if (!vin) {
    return <div className="text-slate-400 p-8">No VIN specified in URL.</div>;
  }

  const authoritative = detail?.authoritative;
  const transient = detail?.transient_state;

  // Coordinate fallback: transient GPS -> depot GPS -> default
  const vehicleLat = transient?.latitude ?? authoritative?.depot?.latitude ?? 37.7749;
  const vehicleLng = transient?.longitude ?? authoritative?.depot?.longitude ?? -122.4194;

  const mapVehicles = [
    {
      vin,
      license_plate: authoritative?.license_plate || '',
      model_name: authoritative?.model ? `${authoritative.model.make} ${authoritative.model.model_name}` : vin,
      latitude: vehicleLat,
      longitude: vehicleLng,
      health_status: transient?.health_status || 'NOMINAL',
      speed_kmh: transient?.speed_kmh,
    },
  ];

  return (
    <div className="space-y-6">
      {/* Top Breadcrumb & Action Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <Link
            to="/"
            className="p-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-850 transition-colors"
            title="Back to Fleet Overview"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold font-mono text-slate-100">{vin}</h1>
              {authoritative?.model?.vehicle_type && (
                <PowertrainBadge type={authoritative.model.vehicle_type} />
              )}
              {transient?.health_status && (
                <HealthBadge status={transient.health_status} />
              )}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Plate:{' '}
              <span className="font-semibold text-slate-300">
                {authoritative?.license_plate || '—'}
              </span>{' '}
              • {authoritative?.model?.make} {authoritative?.model?.model_name} (
              {authoritative?.manufacture_year})
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setIsWorkOrderOpen(true)}
            className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold shadow-sm transition-colors"
          >
            <Wrench className="w-3.5 h-3.5" />
            Dispatch Work Order
          </button>

          <button
            onClick={fetchVehicleData}
            disabled={isLoadingDetail}
            className="p-2 rounded-lg bg-slate-900 border border-slate-750 text-slate-300 hover:text-white hover:bg-slate-800 transition-colors disabled:opacity-50"
            title="Refresh Vehicle Data"
          >
            <RefreshCw className={`w-4 h-4 ${isLoadingDetail ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {/* Main Grid: Telemetry & Specs on left; Risk Assessment & Map on right */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column (7 cols): Telemetry Card & Specs */}
        <div className="lg:col-span-7 space-y-6">
          {/* Live CAN-Bus Gauge Card */}
          <VehicleTelemetryCard
            state={transient}
            vehicleType={authoritative?.model?.vehicle_type || 'ICE'}
          />

          {/* Authoritative Relational Metadata Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
            <div className="px-5 py-3 border-b border-slate-800 bg-slate-950/70 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
                <FileText className="w-4 h-4 text-cyan-400" />
                <span>3NF Relational Specifications & Assignment</span>
              </div>
              <span className="text-[11px] font-mono text-slate-500">
                Status: {authoritative?.status || 'ACTIVE'}
              </span>
            </div>

            <div className="p-5 grid grid-cols-2 sm:grid-cols-3 gap-4 text-xs">
              <div>
                <span className="text-slate-400 block mb-0.5">Fleet Assignment</span>
                <span className="font-semibold text-slate-200 flex items-center gap-1">
                  <Building2 className="w-3.5 h-3.5 text-cyan-400" />
                  {authoritative?.fleet?.name || '—'}
                </span>
                <span className="text-[10px] text-slate-500 font-mono">
                  Code: {authoritative?.fleet?.code}
                </span>
              </div>

              <div>
                <span className="text-slate-400 block mb-0.5">Home Depot</span>
                <span className="font-semibold text-slate-200 flex items-center gap-1">
                  <MapPin className="w-3.5 h-3.5 text-indigo-400" />
                  {authoritative?.depot?.name || '—'}
                </span>
                <span className="text-[10px] text-slate-500">
                  {authoritative?.depot?.city}, {authoritative?.depot?.state}
                </span>
              </div>

              <div>
                <span className="text-slate-400 block mb-0.5">Baseline Odometer</span>
                <span className="font-semibold font-mono text-slate-200">
                  {authoritative?.initial_odometer_km?.toLocaleString()} km
                </span>
              </div>

              {authoritative?.model?.engine_displacement_l && (
                <div>
                  <span className="text-slate-400 block mb-0.5">Displacement</span>
                  <span className="font-semibold text-slate-200">
                    {authoritative.model.engine_displacement_l} L
                  </span>
                </div>
              )}

              {authoritative?.model?.battery_capacity_kwh && (
                <div>
                  <span className="text-slate-400 block mb-0.5">Battery Capacity</span>
                  <span className="font-semibold text-slate-200">
                    {authoritative.model.battery_capacity_kwh} kWh
                  </span>
                </div>
              )}

              {authoritative?.model?.curb_weight_kg && (
                <div>
                  <span className="text-slate-400 block mb-0.5">Curb Weight</span>
                  <span className="font-semibold text-slate-200">
                    {authoritative.model.curb_weight_kg.toLocaleString()} kg
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Vehicle Recent Alerts */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-300">
              <span className="flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                Recent Vehicle Alerts ({alerts.length})
              </span>
            </div>
            <AlertsList alerts={alerts} showFilters={false} />
          </div>
        </div>

        {/* Right Column (5 cols): Predictive Risk & Map */}
        <div className="lg:col-span-5 space-y-6">
          {/* Predictive Maintenance Risk Panel */}
          <PredictiveRiskPanel
            riskData={riskData}
            isLoading={isLoadingRisk}
            onOpenWorkOrder={() => setIsWorkOrderOpen(true)}
          />

          {/* Individual Vehicle Map Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm space-y-2">
            <div className="px-4 py-2.5 border-b border-slate-800 bg-slate-950/70 flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5 text-cyan-400" />
                Live Spatial Position
              </span>
              <span className="font-mono text-[10px] text-slate-400">
                {vehicleLat.toFixed(4)}, {vehicleLng.toFixed(4)}
              </span>
            </div>
            <VehicleMap vehicles={mapVehicles} height="280px" />
          </div>
        </div>
      </div>

      {/* Work Order Modal */}
      <WorkOrderModal
        isOpen={isWorkOrderOpen}
        onClose={() => setIsWorkOrderOpen(false)}
        vin={vin}
        initialPriority={riskData?.risk_level === 'CRITICAL' ? 'CRITICAL' : 'HIGH'}
        initialNotes={
          riskData?.predicted_maintenance_required
            ? `Predictive maintenance dispatch: 7-day risk estimate is ${(riskData.probability_7d * 100).toFixed(1)}%. Primary risk factor: ${riskData.top_risk_factors[0]?.feature_name || 'anomalous telemetry'}.`
            : ''
        }
        onSuccess={() => {
          fetchVehicleData();
        }}
      />
    </div>
  );
};
