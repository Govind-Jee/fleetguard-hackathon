import { Link } from 'react-router-dom';
import { AlertCircle, ArrowRight, X } from 'lucide-react';
import { WSAlertPayload } from '../../types/ws';
import { SeverityBadge } from '../common/Badge';

interface LiveAlertBannerProps {
  alert: WSAlertPayload | null;
  onDismiss: () => void;
}

export function LiveAlertBanner({ alert, onDismiss }: LiveAlertBannerProps) {
  if (!alert) return null;

  return (
    <div className="w-full bg-gradient-to-r from-red-950/90 via-red-900/60 to-red-950/90 border-b border-red-700/80 px-4 py-3 text-red-100 shadow-lg shadow-red-950/50 animate-slide-down">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded-lg bg-red-600/30 border border-red-500/50 text-red-200 animate-pulse">
            <AlertCircle className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wider text-red-300">CRITICAL ALERT DISPATCHED</span>
              <SeverityBadge severity={alert.severity} />
              <span className="text-xs font-mono font-bold text-white bg-red-900/80 px-2 py-0.5 rounded border border-red-700">
                {alert.vin}
              </span>
            </div>
            <p className="text-xs text-red-200 mt-0.5">
              <span className="font-semibold text-white mr-1.5">[{alert.fault_type}]</span>
              {alert.message}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 self-end sm:self-center">
          <Link
            to={`/vehicles/${alert.vin}`}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-white text-xs font-semibold shadow transition"
          >
            Inspect Vehicle
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
          <button
            onClick={onDismiss}
            aria-label="Dismiss alert banner"
            className="p-1 rounded-lg text-red-300 hover:text-white hover:bg-red-800/50 transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
