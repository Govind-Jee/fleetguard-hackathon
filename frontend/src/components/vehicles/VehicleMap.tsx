import { useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Link } from 'react-router-dom';
import { HealthStatus } from '../../types/api';
import { HealthBadge } from '../common/Badge';

// Fix Leaflet default icon paths in bundler environments
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// Custom colored SVG pin markers for health states
function createHealthIcon(status?: HealthStatus | string | null) {
  let color = '#10B981'; // Green for NOMINAL
  if (status === 'WARNING') color = '#F59E0B'; // Amber
  if (status === 'CRITICAL') color = '#EF4444'; // Red

  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="28" height="28">
      <circle cx="12" cy="12" r="10" fill="${color}" fill-opacity="0.25" stroke="${color}" stroke-width="2"/>
      <circle cx="12" cy="12" r="5" fill="${color}"/>
    </svg>
  `;

  return L.divIcon({
    html: svg,
    className: 'custom-leaflet-marker',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

export interface MapVehiclePoint {
  vin: string;
  vehicle_id?: string;
  license_plate: string;
  make?: string;
  model_name: string;
  vehicle_type?: string;
  fleet_name?: string;
  health_status?: HealthStatus | string | null;
  latitude: number;
  longitude: number;
  speed_kmh?: number | null;
}

interface VehicleMapProps {
  vehicles: MapVehiclePoint[];
  center?: [number, number];
  zoom?: number;
  height?: string;
  isLoading?: boolean;
}

// Helper to auto-fit bounds when vehicle points update
function MapBoundsUpdater({ vehicles }: { vehicles: MapVehiclePoint[] }) {
  const map = useMap();

  useEffect(() => {
    if (vehicles.length > 0) {
      const bounds = L.latLngBounds(vehicles.map((v) => [v.latitude, v.longitude]));
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 13 });
    }
  }, [map, vehicles]);

  return null;
}

export function VehicleMap({
  vehicles,
  center = [41.8781, -87.6298], // Chicago Metro default
  zoom = 11,
  height = '420px',
  isLoading = false,
}: VehicleMapProps) {
  if (isLoading) {
    return (
      <div
        style={{ height }}
        className="w-full rounded-xl border border-gray-800 bg-gray-900/60 flex items-center justify-center animate-pulse text-gray-500 text-xs"
      >
        Loading geospatial telemetry...
      </div>
    );
  }

  if (vehicles.length === 0) {
    return (
      <div
        style={{ height }}
        className="w-full rounded-xl border border-gray-800 bg-gray-900/40 flex flex-col items-center justify-center text-center p-6"
      >
        <span className="text-sm font-medium text-gray-300">No telemetry GPS coordinates available</span>
        <span className="text-xs text-gray-500 mt-1">Vehicle fleet currently inactive or filtered out</span>
      </div>
    );
  }

  return (
    <div className="w-full rounded-xl border border-gray-800 overflow-hidden relative shadow-lg">
      <MapContainer
        center={center}
        zoom={zoom}
        style={{ height, width: '100%' }}
        className="z-10"
        scrollWheelZoom={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapBoundsUpdater vehicles={vehicles} />
        {vehicles.map((v) => (
          <Marker
            key={v.vin}
            position={[v.latitude, v.longitude]}
            icon={createHealthIcon(v.health_status)}
          >
            <Popup className="custom-popup">
              <div className="p-2 space-y-1.5 text-gray-900 text-xs">
                <div className="flex items-center justify-between gap-3 border-b pb-1">
                  <span className="font-mono font-bold text-sm text-gray-950">{v.vin}</span>
                  <HealthBadge status={v.health_status} />
                </div>
                <div className="text-[11px] text-gray-600">
                  <p className="font-medium text-gray-800">
                    {v.make ? `${v.make} ` : ''}{v.model_name}
                  </p>
                  {v.fleet_name && <p>Fleet: {v.fleet_name}</p>}
                  {v.speed_kmh !== undefined && v.speed_kmh !== null && (
                    <p className="font-mono font-semibold text-blue-700">Speed: {v.speed_kmh.toFixed(1)} km/h</p>
                  )}
                </div>
                <div className="pt-1">
                  <Link
                    to={`/vehicles/${v.vin}`}
                    className="inline-block w-full text-center py-1 px-2 rounded bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs transition"
                  >
                    View Vehicle Telemetry
                  </Link>
                </div>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>

      {/* Map Legend Overlay */}
      <div className="absolute bottom-3 right-3 z-[400] bg-gray-950/90 border border-gray-800 backdrop-blur rounded-lg px-3 py-2 text-[10px] space-y-1 shadow-md">
        <span className="font-bold uppercase tracking-wider text-gray-400 block mb-1">Fleet Status</span>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
          <span className="text-gray-200">Nominal Telemetry</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-amber-400"></span>
          <span className="text-gray-200">Warning Anomaly</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-red-400 animate-pulse"></span>
          <span className="text-gray-200">Critical Breakdown Risk</span>
        </div>
      </div>
    </div>
  );
}
