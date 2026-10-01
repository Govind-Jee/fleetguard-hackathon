import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertRecord } from '../../types/api';
import { SeverityBadge } from '../common/Badge';
import { Search, ArrowUpRight, Clock } from 'lucide-react';

interface AlertsListProps {
  alerts: AlertRecord[];
  isLoading?: boolean;
  total?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number) => void;
  selectedSeverity?: string;
  onSeverityChange?: (severity: string) => void;
  showFilters?: boolean;
}

export const AlertsList: React.FC<AlertsListProps> = ({
  alerts,
  isLoading = false,
  total,
  page = 1,
  pageSize = 20,
  onPageChange,
  selectedSeverity = '',
  onSeverityChange,
  showFilters = true,
}) => {
  const [searchTerm, setSearchTerm] = useState('');

  const filteredAlerts = alerts.filter((alert) => {
    const matchesSearch =
      !searchTerm.trim() ||
      alert.vin.toLowerCase().includes(searchTerm.toLowerCase()) ||
      alert.fault_type.toLowerCase().includes(searchTerm.toLowerCase()) ||
      alert.message.toLowerCase().includes(searchTerm.toLowerCase());

    const matchesSeverity =
      !selectedSeverity || alert.severity === selectedSeverity;

    return matchesSearch && matchesSeverity;
  });

  const totalCount = total !== undefined ? total : filteredAlerts.length;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      {/* Controls Bar */}
      {showFilters && (
        <div className="p-4 border-b border-slate-800 bg-slate-950/70 flex flex-wrap gap-3 items-center justify-between">
          <div className="relative min-w-[220px] flex-1 max-w-sm">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Filter by VIN, fault code, message..."
              className="w-full pl-9 pr-3 py-1.5 text-sm bg-slate-950 border border-slate-750 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
            />
          </div>

          {onSeverityChange && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 font-medium">Severity:</span>
              <select
                value={selectedSeverity}
                onChange={(e) => onSeverityChange(e.target.value)}
                className="bg-slate-950 border border-slate-750 text-xs text-slate-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              >
                <option value="">All Severities</option>
                <option value="CRITICAL">CRITICAL</option>
                <option value="WARNING">WARNING</option>
                <option value="INFO">INFO</option>
              </select>
            </div>
          )}
        </div>
      )}

      {/* Alerts Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm text-slate-300">
          <thead className="bg-slate-950/80 text-xs uppercase tracking-wider text-slate-400 border-b border-slate-800">
            <tr>
              <th scope="col" className="px-4 py-3 font-semibold">Severity</th>
              <th scope="col" className="px-4 py-3 font-semibold">Fault Type</th>
              <th scope="col" className="px-4 py-3 font-semibold">Message & Context</th>
              <th scope="col" className="px-4 py-3 font-semibold">Vehicle VIN</th>
              <th scope="col" className="px-4 py-3 font-semibold">Timestamp</th>
              <th scope="col" className="px-4 py-3 font-semibold text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {isLoading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <tr key={i} className="animate-pulse">
                  <td className="px-4 py-3"><div className="h-4 bg-slate-800 rounded w-16"></div></td>
                  <td className="px-4 py-3"><div className="h-4 bg-slate-800 rounded w-24"></div></td>
                  <td className="px-4 py-3"><div className="h-4 bg-slate-800 rounded w-48"></div></td>
                  <td className="px-4 py-3"><div className="h-4 bg-slate-800 rounded w-28"></div></td>
                  <td className="px-4 py-3"><div className="h-4 bg-slate-800 rounded w-20"></div></td>
                  <td className="px-4 py-3"><div className="h-6 bg-slate-800 rounded w-16 ml-auto"></div></td>
                </tr>
              ))
            ) : filteredAlerts.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                  No alerts found matching the criteria.
                </td>
              </tr>
            ) : (
              filteredAlerts.map((alert) => (
                <tr
                  key={alert.alert_id}
                  className={`hover:bg-slate-850/50 transition-colors ${
                    alert.severity === 'CRITICAL' ? 'bg-rose-950/10' : ''
                  }`}
                >
                  <td className="px-4 py-3">
                    <SeverityBadge severity={alert.severity} />
                  </td>
                  <td className="px-4 py-3">
                    <span className="font-mono text-xs font-semibold text-slate-200">
                      {alert.fault_type}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-xs text-slate-200">{alert.message}</div>
                    {alert.sequence_number !== undefined && alert.sequence_number !== null && (
                      <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                        Seq #{alert.sequence_number}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      to={`/vehicles/${alert.vin}`}
                      className="font-mono text-xs text-cyan-400 hover:text-cyan-300 hover:underline flex items-center gap-1"
                    >
                      {alert.vin}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-400">
                    <div className="flex items-center gap-1">
                      <Clock className="w-3 h-3 text-slate-500" />
                      {new Date(alert.created_at).toLocaleTimeString()}
                    </div>
                    <div className="text-[10px] text-slate-500">
                      {new Date(alert.created_at).toLocaleDateString()}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      to={`/vehicles/${alert.vin}`}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg bg-slate-800 text-slate-200 hover:bg-cyan-950/60 hover:text-cyan-300 border border-slate-700 transition-colors"
                    >
                      Inspect
                      <ArrowUpRight className="w-3 h-3" />
                    </Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer if callback is supplied */}
      {onPageChange && (
        <div className="px-4 py-3 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between text-xs text-slate-400">
          <div>
            Total <span className="font-semibold text-slate-200">{totalCount}</span> alerts
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 1 || isLoading}
              className="px-2.5 py-1 rounded bg-slate-800 text-slate-200 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <span>
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages || isLoading}
              className="px-2.5 py-1 rounded bg-slate-800 text-slate-200 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
