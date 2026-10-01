import { HealthStatus, VehicleType } from '../../types/api';

export function HealthBadge({ status }: { status?: HealthStatus | string | null }) {
  if (!status) {
    return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700">UNKNOWN</span>;
  }

  switch (status.toUpperCase()) {
    case 'NOMINAL':
    case 'NORMAL':
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          NOMINAL
        </span>
      );
    case 'WARNING':
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-semibold bg-amber-950 text-amber-400 border border-amber-800">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
          WARNING
        </span>
      );
    case 'CRITICAL':
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-semibold bg-red-950 text-red-400 border border-red-800 animate-pulse">
          <span className="w-1.5 h-1.5 rounded-full bg-red-400"></span>
          CRITICAL
        </span>
      );
    default:
      return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-300 border border-gray-700">{status}</span>;
  }
}

export function RiskBadge({ level, probability }: { level?: string | null; probability?: number | null }) {
  const probText = probability !== undefined && probability !== null ? ` ${(probability * 100).toFixed(1)}%` : '';

  switch (level?.toUpperCase()) {
    case 'LOW':
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-emerald-950/60 text-emerald-300 border border-emerald-800/60">
          LOW{probText}
        </span>
      );
    case 'MEDIUM':
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-950/60 text-amber-300 border border-amber-800/60">
          MEDIUM{probText}
        </span>
      );
    case 'HIGH':
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-orange-950/80 text-orange-300 border border-orange-800">
          HIGH{probText}
        </span>
      );
    case 'CRITICAL':
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-red-950 text-red-300 border border-red-700 animate-pulse">
          CRITICAL{probText}
        </span>
      );
    default:
      return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700">N/A</span>;
  }
}

export function PowertrainBadge({ type }: { type?: VehicleType | string | null }) {
  switch (type?.toUpperCase()) {
    case 'ICE':
      return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-950/70 text-blue-300 border border-blue-800">ICE (Diesel)</span>;
    case 'HEV':
      return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-950/70 text-purple-300 border border-purple-800">HEV (Hybrid)</span>;
    case 'BEV':
      return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-cyan-950/70 text-cyan-300 border border-cyan-800">BEV (Electric)</span>;
    default:
      return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700">{type || 'ALL'}</span>;
  }
}

export function SeverityBadge({ severity }: { severity?: string | null }) {
  switch (severity?.toUpperCase()) {
    case 'CRITICAL':
      return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-red-950 text-red-300 border border-red-700">CRITICAL</span>;
    case 'WARNING':
      return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-amber-950 text-amber-300 border border-amber-700">WARNING</span>;
    default:
      return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-950 text-blue-300 border border-blue-800">INFO</span>;
  }
}
