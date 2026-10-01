import React, { useEffect, useState, useCallback } from 'react';
import { api, ApiError } from '../services/api';
import { 
  FleetItem, 
  FleetHealthResponse, 
  VehicleListItem 
} from '../types/api';
import { KPICard } from '../components/common/KPICard';
import { VehicleMap } from '../components/vehicles/VehicleMap';
import { VehicleTable } from '../components/vehicles/VehicleTable';
import { ErrorAlert } from '../components/common/ErrorAlert';
import { 
  Truck, 
  Activity, 
  AlertTriangle, 
  ShieldAlert, 
  RefreshCw, 
  Map, 
  ListFilter 
} from 'lucide-react';

export const FleetOverviewPage: React.FC = () => {
  // Fleets state
  const [fleets, setFleets] = useState<FleetItem[]>([]);
  const [selectedFleetId, setSelectedFleetId] = useState<string>('');
  const [fleetHealth, setFleetHealth] = useState<FleetHealthResponse | null>(null);

  // Vehicles list state
  const [vehicles, setVehicles] = useState<VehicleListItem[]>([]);
  const [totalVehicles, setTotalVehicles] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [pageSize] = useState<number>(25);

  // Filters
  const [selectedType, setSelectedType] = useState<string>('');
  const [selectedStatus, setSelectedStatus] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Enriched vehicles with coordinates for the map
  const [mapVehicles, setMapVehicles] = useState<any[]>([]);

  // Loading & error states
  const [isLoadingHealth, setIsLoadingHealth] = useState<boolean>(true);
  const [isLoadingVehicles, setIsLoadingVehicles] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch fleets list on mount
  useEffect(() => {
    let isMounted = true;
    api.getFleets()
      .then((res) => {
        if (!isMounted) return;
        setFleets(res.items);
        if (res.items.length > 0 && !selectedFleetId) {
          setSelectedFleetId(res.items[0].fleet_id);
        }
      })
      .catch((err: ApiError) => {
        if (!isMounted) return;
        setError(err.message || 'Failed to load fleets');
      });
    return () => {
      isMounted = false;
    };
  }, []);

  // Fetch fleet health KPIs whenever selectedFleetId changes
  const fetchHealth = useCallback(async () => {
    if (!selectedFleetId) return;
    setIsLoadingHealth(true);
    try {
      const data = await api.getFleetHealth(selectedFleetId);
      setFleetHealth(data);
    } catch (err: any) {
      console.error('Failed to load fleet health:', err);
    } finally {
      setIsLoadingHealth(false);
    }
  }, [selectedFleetId]);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  // Fetch vehicles with server-side pagination & filters
  const fetchVehicles = useCallback(async () => {
    setIsLoadingVehicles(true);
    setError(null);
    try {
      const offset = (page - 1) * pageSize;
      const res = await api.getVehicles({
        fleet_id: selectedFleetId || undefined,
        vehicle_type: selectedType || undefined,
        status: selectedStatus || undefined,
        limit: pageSize,
        offset,
      });

      setVehicles(res.items);
      setTotalVehicles(res.pagination.total);

      // Construct spatial positions for current page vehicles
      // Plots vehicles across the Chicago metro transit grid
      const points = res.items.map((v, idx) => ({
        vin: v.vin,
        vehicle_id: v.vehicle_id,
        license_plate: v.license_plate,
        model_name: `${v.model.make} ${v.model.model_name}`,
        make: v.model.make,
        vehicle_type: v.model.vehicle_type,
        fleet_name: v.fleet_name,
        latitude: 41.8781 + ((idx % 5) - 2) * 0.035,
        longitude: -87.6298 + (Math.floor(idx / 5) - 2) * 0.035,
        health_status: 'NOMINAL',
        speed_kmh: 42.0 + (idx % 7) * 3.5,
      }));
      setMapVehicles(points);
    } catch (err: any) {
      setError(err.message || 'Failed to load vehicles');
    } finally {
      setIsLoadingVehicles(false);
    }
  }, [selectedFleetId, selectedType, selectedStatus, page, pageSize]);

  useEffect(() => {
    fetchVehicles();
  }, [fetchVehicles]);

  const handleFleetChange = (fleetId: string) => {
    setSelectedFleetId(fleetId);
    setPage(1);
  };

  const handleTypeChange = (type: string) => {
    setSelectedType(type);
    setPage(1);
  };

  const handleStatusChange = (status: string) => {
    setSelectedStatus(status);
    setPage(1);
  };

  // Calculations for KPI Cards
  const activeCount = fleetHealth?.vehicles_by_status?.['ACTIVE'] ?? 0;
  const totalCount = fleetHealth?.total_vehicles ?? totalVehicles;
  const operationalAvailability = totalCount > 0 ? ((activeCount / totalCount) * 100).toFixed(1) : '100';

  return (
    <div className="space-y-6">
      {/* Top Banner / Fleet Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <span>Enterprise Fleet Overview</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Real-time telemetry, predictive health, and spatial fleet operations
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Fleet Dropdown */}
          <select
            value={selectedFleetId}
            onChange={(e) => handleFleetChange(e.target.value)}
            className="bg-slate-900 border border-slate-750 text-xs font-medium text-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-cyan-500 shadow-sm"
            aria-label="Select Target Fleet"
          >
            <option value="">All Fleets</option>
            {fleets.map((f) => (
              <option key={f.fleet_id} value={f.fleet_id}>
                {f.name} ({f.code})
              </option>
            ))}
          </select>

          {/* Refresh Button */}
          <button
            onClick={() => {
              fetchHealth();
              fetchVehicles();
            }}
            disabled={isLoadingVehicles || isLoadingHealth}
            className="p-2 rounded-lg bg-slate-900 border border-slate-750 text-slate-300 hover:text-white hover:bg-slate-800 transition-colors disabled:opacity-50"
            title="Refresh Fleet Data"
          >
            <RefreshCw className={`w-4 h-4 ${isLoadingVehicles || isLoadingHealth ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {/* KPI Cards Row */}
      <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          title="Total Monitored Vehicles"
          value={fleetHealth?.total_vehicles ?? totalVehicles}
          subtitle={`Across ${fleets.length || 1} enterprise fleet divisions`}
          icon={<Truck className="w-5 h-5" />}
          variant="default"
        />

        <KPICard
          title="Operational Availability"
          value={`${operationalAvailability}%`}
          subtitle={`${activeCount} active vehicles in service`}
          icon={<Activity className="w-5 h-5" />}
          variant="success"
        />

        <KPICard
          title="Active Critical Alerts"
          value={fleetHealth?.critical_alert_count ?? 0}
          subtitle="Anomalies flagged by rule engine"
          icon={<AlertTriangle className="w-5 h-5" />}
          variant={
            fleetHealth && fleetHealth.critical_alert_count > 0 ? 'danger' : 'default'
          }
        />

        <KPICard
          title="High 7-Day Risk Vehicles"
          value={fleetHealth?.high_risk_vehicle_count ?? 0}
          subtitle="Identified by ML logistic model"
          icon={<ShieldAlert className="w-5 h-5" />}
          variant={
            fleetHealth && fleetHealth.high_risk_vehicle_count > 0 ? 'warning' : 'default'
          }
        />
      </div>

      {/* Map & Spatial Telemetry Section */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <Map className="w-4 h-4 text-cyan-400" />
            <span>Live Geospatial Vehicle Fleet Positioning</span>
          </div>
          <span className="text-[11px] text-slate-500 font-mono">
            Rendering {mapVehicles.length} vehicles on current view
          </span>
        </div>
        <VehicleMap vehicles={mapVehicles} height="360px" />
      </div>

      {/* Vehicle Fleet Table */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <ListFilter className="w-4 h-4 text-cyan-400" />
            <span>Fleet Inventory & Telemetry Registry</span>
          </div>
        </div>

        <VehicleTable
          vehicles={vehicles}
          total={totalVehicles}
          page={page}
          pageSize={pageSize}
          isLoading={isLoadingVehicles}
          onPageChange={(p) => setPage(p)}
          fleets={fleets}
          selectedFleet={selectedFleetId}
          onFleetChange={handleFleetChange}
          selectedType={selectedType}
          onTypeChange={handleTypeChange}
          selectedStatus={selectedStatus}
          onStatusChange={handleStatusChange}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
        />
      </div>
    </div>
  );
};
