import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import { AlertRecord } from '../types/api';
import { useAlertsWebSocket } from '../hooks/useAlertsWebSocket';
import { AlertsList } from '../components/alerts/AlertsList';
import { SeverityBadge } from '../components/common/Badge';
import { ErrorAlert } from '../components/common/ErrorAlert';
import { 
  Bell, 
  Radio, 
  History, 
  Trash2, 
  RefreshCw, 
  ArrowUpRight 
} from 'lucide-react';
import { Link } from 'react-router-dom';

export const AlertsPage: React.FC = () => {
  // Live WebSocket alerts
  const { alerts: liveAlerts, isConnected, clearAlerts } = useAlertsWebSocket();

  // Historical alerts from PostgreSQL
  const [historicalAlerts, setHistoricalAlerts] = useState<AlertRecord[]>([]);
  const [totalAlerts, setTotalAlerts] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [pageSize] = useState<number>(20);
  const [severityFilter, setSeverityFilter] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHistoricalAlerts = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * pageSize;
      const res = await api.getAlerts({
        limit: pageSize,
        offset,
        severity: severityFilter || undefined,
      });
      setHistoricalAlerts(res.items);
      setTotalAlerts(res.pagination.total);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch historical alerts');
    } finally {
      setIsLoading(false);
    }
  }, [page, pageSize, severityFilter]);

  useEffect(() => {
    fetchHistoricalAlerts();
  }, [fetchHistoricalAlerts]);

  const handleSeverityChange = (newSev: string) => {
    setSeverityFilter(newSev);
    setPage(1);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-3 border-b border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Bell className="w-5 h-5 text-cyan-400" />
            <span>Alerts & Telemetry Anomaly Monitoring</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Real-time WebSocket event ingestion and persistent relational alert records
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchHistoricalAlerts}
            disabled={isLoading}
            className="p-2 rounded-lg bg-slate-900 border border-slate-750 text-slate-300 hover:text-white hover:bg-slate-800 transition-colors disabled:opacity-50"
            title="Refresh Alert Registry"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {/* Live Ingestion Stream Card */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="px-5 py-3 border-b border-slate-800 bg-slate-950/70 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Radio className="w-4 h-4 text-rose-400 animate-pulse" />
            <h3 className="font-semibold text-xs text-slate-200">
              Live Ingestion WebSocket Feed (/ws/alerts)
            </h3>
            <span
              className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono ${
                isConnected
                  ? 'bg-emerald-950/70 text-emerald-400 border border-emerald-800/40'
                  : 'bg-rose-950/70 text-rose-400 border border-rose-800/40'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isConnected ? 'bg-emerald-400 animate-ping' : 'bg-rose-400'
                }`}
              ></span>
              {isConnected ? 'STREAMING ACTIVE' : 'RECONNECTING'}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-400 font-mono">
              Buffer: {liveAlerts.length} events
            </span>
            {liveAlerts.length > 0 && (
              <button
                onClick={clearAlerts}
                className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1 hover:underline"
              >
                <Trash2 className="w-3 h-3" />
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Live Stream Body */}
        <div className="p-4">
          {liveAlerts.length === 0 ? (
            <div className="text-center py-6 text-slate-400 text-xs bg-slate-950/30 rounded-lg">
              No live critical alerts pushed in the current session. Monitoring Redpanda Kafka stream...
            </div>
          ) : (
            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
              {liveAlerts.map((alert) => (
                <div
                  key={alert.alert_id}
                  className="p-3 rounded-lg border border-rose-900/60 bg-rose-950/20 flex items-center justify-between gap-3 text-xs"
                >
                  <div className="flex items-center gap-3">
                    <SeverityBadge severity={alert.severity} />
                    <span className="font-mono font-semibold text-rose-300">
                      {alert.fault_type}
                    </span>
                    <span className="text-slate-300">{alert.message}</span>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <Link
                      to={`/vehicles/${alert.vin}`}
                      className="font-mono text-cyan-400 hover:text-cyan-300 hover:underline flex items-center gap-1"
                    >
                      {alert.vin}
                      <ArrowUpRight className="w-3 h-3" />
                    </Link>
                    <span className="text-[10px] text-slate-500 font-mono">
                      {new Date(alert.created_at || alert.timestamp || Date.now()).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Historical Relational Alerts Table */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-400">
          <span className="flex items-center gap-1.5">
            <History className="w-4 h-4 text-cyan-400" />
            Historical Relational Alert Registry
          </span>
        </div>

        <AlertsList
          alerts={historicalAlerts}
          isLoading={isLoading}
          total={totalAlerts}
          page={page}
          pageSize={pageSize}
          onPageChange={(p) => setPage(p)}
          selectedSeverity={severityFilter}
          onSeverityChange={handleSeverityChange}
          showFilters={true}
        />
      </div>
    </div>
  );
};
