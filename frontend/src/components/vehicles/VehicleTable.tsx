import React from 'react';
import { Link } from 'react-router-dom';
import { VehicleListItem, VehicleType, FleetItem } from '../../types/api';
import { PowertrainBadge } from '../common/Badge';
import { ChevronLeft, ChevronRight, Search, Filter, ArrowUpRight } from 'lucide-react';

interface VehicleTableProps {
  vehicles: VehicleListItem[];
  total: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  onPageChange: (page: number) => void;
  fleets: FleetItem[];
  selectedFleet: string;
  onFleetChange: (fleetId: string) => void;
  selectedType: string;
  onTypeChange: (type: string) => void;
  selectedStatus: string;
  onStatusChange: (status: string) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
}

export const VehicleTable: React.FC<VehicleTableProps> = ({
  vehicles,
  total,
  page,
  pageSize,
  isLoading,
  onPageChange,
  fleets,
  selectedFleet,
  onFleetChange,
  selectedType,
  onTypeChange,
  selectedStatus,
  onStatusChange,
  searchQuery,
  onSearchChange,
}) => {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Client-side search filtering on current page items for quick responsiveness
  const filteredVehicles = searchQuery.trim()
    ? vehicles.filter(
        (v) =>
          v.vin.toLowerCase().includes(searchQuery.toLowerCase()) ||
          v.license_plate.toLowerCase().includes(searchQuery.toLowerCase()) ||
          v.model.make.toLowerCase().includes(searchQuery.toLowerCase()) ||
          v.model.model_name.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : vehicles;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      {/* Table Header / Filters Bar */}
      <div className="p-4 border-b border-slate-800 bg-slate-900/60 flex flex-wrap gap-3 items-center justify-between">
        {/* Search */}
        <div className="relative min-w-[240px] flex-1 max-w-sm">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search by VIN, Plate, Make..."
            className="w-full pl-9 pr-3 py-1.5 text-sm bg-slate-950 border border-slate-750 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500"
          />
        </div>

        {/* Filter controls */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <Filter className="w-3.5 h-3.5" />
            <span className="font-medium">Filter:</span>
          </div>

          {/* Fleet Filter */}
          <select
            value={selectedFleet}
            onChange={(e) => onFleetChange(e.target.value)}
            className="bg-slate-950 border border-slate-750 text-xs text-slate-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-cyan-500"
            aria-label="Filter by Fleet"
          >
            <option value="">All Fleets</option>
            {fleets.map((f) => (
              <option key={f.fleet_id} value={f.fleet_id}>
                {f.name}
              </option>
            ))}
          </select>

          {/* Powertrain Type Filter */}
          <select
            value={selectedType}
            onChange={(e) => onTypeChange(e.target.value)}
            className="bg-slate-950 border border-slate-750 text-xs text-slate-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-cyan-500"
            aria-label="Filter by Powertrain"
          >
            <option value="">All Powertrains</option>
            <option value="ICE">ICE (Internal Combustion)</option>
            <option value="HEV">HEV (Hybrid Electric)</option>
            <option value="BEV">BEV (Battery Electric)</option>
          </select>

          {/* Status Filter */}
          <select
            value={selectedStatus}
            onChange={(e) => onStatusChange(e.target.value)}
            className="bg-slate-950 border border-slate-750 text-xs text-slate-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-cyan-500"
            aria-label="Filter by Status"
          >
            <option value="">All Statuses</option>
            <option value="ACTIVE">ACTIVE</option>
            <option value="MAINTENANCE">MAINTENANCE</option>
            <option value="INACTIVE">INACTIVE</option>
          </select>
        </div>
      </div>

      {/* Table Content */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm text-slate-300">
          <thead className="bg-slate-950/80 text-xs uppercase tracking-wider text-slate-400 border-b border-slate-800">
            <tr>
              <th scope="col" className="px-4 py-3 font-semibold">Vehicle / VIN</th>
              <th scope="col" className="px-4 py-3 font-semibold">Model</th>
              <th scope="col" className="px-4 py-3 font-semibold">Powertrain</th>
              <th scope="col" className="px-4 py-3 font-semibold">Fleet & Depot</th>
              <th scope="col" className="px-4 py-3 font-semibold">Status</th>
              <th scope="col" className="px-4 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {isLoading ? (
              // Loading skeleton rows
              Array.from({ length: 5 }).map((_, idx) => (
                <tr key={idx} className="animate-pulse">
                  <td className="px-4 py-3">
                    <div className="h-4 bg-slate-800 rounded w-28 mb-1"></div>
                    <div className="h-3 bg-slate-850 rounded w-20"></div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="h-4 bg-slate-800 rounded w-32"></div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="h-4 bg-slate-800 rounded w-12"></div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="h-4 bg-slate-800 rounded w-24 mb-1"></div>
                    <div className="h-3 bg-slate-850 rounded w-16"></div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="h-4 bg-slate-800 rounded w-16"></div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="h-7 bg-slate-800 rounded w-16 ml-auto"></div>
                  </td>
                </tr>
              ))
            ) : filteredVehicles.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                  No vehicles match the selected criteria.
                </td>
              </tr>
            ) : (
              filteredVehicles.map((vehicle) => (
                <tr
                  key={vehicle.vehicle_id}
                  className="hover:bg-slate-850/50 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="font-mono font-medium text-slate-100 text-xs">
                      {vehicle.vin}
                    </div>
                    <div className="text-xs text-slate-400">
                      Plate: <span className="font-semibold text-slate-300">{vehicle.license_plate}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-200">
                      {vehicle.model.make} {vehicle.model.model_name}
                    </div>
                    <div className="text-xs text-slate-500">
                      Year: {vehicle.manufacture_year}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <PowertrainBadge type={vehicle.model.vehicle_type as VehicleType} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-slate-200 text-xs font-medium">{vehicle.fleet_name}</div>
                    <div className="text-xs text-slate-400">{vehicle.depot_name}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                        vehicle.status === 'ACTIVE'
                          ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-800/60'
                          : vehicle.status === 'MAINTENANCE'
                          ? 'bg-amber-950/80 text-amber-300 border border-amber-800/60'
                          : 'bg-slate-800 text-slate-400 border border-slate-700'
                      }`}
                    >
                      {vehicle.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      to={`/vehicles/${vehicle.vin}`}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg bg-slate-800 text-cyan-400 hover:bg-cyan-950/50 hover:text-cyan-300 border border-slate-700 hover:border-cyan-800/60 transition-colors"
                    >
                      Inspect
                      <ArrowUpRight className="w-3.5 h-3.5" />
                    </Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div className="px-4 py-3 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between text-xs text-slate-400">
        <div>
          Showing{' '}
          <span className="font-semibold text-slate-200">
            {total === 0 ? 0 : (page - 1) * pageSize + 1}
          </span>{' '}
          to{' '}
          <span className="font-semibold text-slate-200">
            {Math.min(page * pageSize, total)}
          </span>{' '}
          of <span className="font-semibold text-slate-200">{total}</span> vehicles
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1 || isLoading}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 text-slate-200 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-750 transition-colors"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            Previous
          </button>
          <span className="text-slate-400 px-1">
            Page <span className="font-semibold text-slate-200">{page}</span> of{' '}
            <span className="font-semibold text-slate-200">{totalPages}</span>
          </span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages || isLoading}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 text-slate-200 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-750 transition-colors"
          >
            Next
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
