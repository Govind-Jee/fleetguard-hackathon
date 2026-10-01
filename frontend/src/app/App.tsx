import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Navbar } from '../components/common/Navbar';
import { LiveAlertBanner } from '../components/alerts/LiveAlertBanner';
import { useAlertsWebSocket } from '../hooks/useAlertsWebSocket';
import { FleetOverviewPage } from '../pages/FleetOverviewPage';
import { VehicleDetailsPage } from '../pages/VehicleDetailsPage';
import { AlertsPage } from '../pages/AlertsPage';
import { DiagnosticsPage } from '../pages/DiagnosticsPage';

export const AppContent = () => {
  const { status, latestCriticalAlert, dismissAlert } = useAlertsWebSocket();

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100 overflow-x-hidden">
      {/* Top Navigation */}
      <Navbar wsStatus={status} />

      {/* Global Live Alert Banner for immediate push critical anomalies */}
      <LiveAlertBanner alert={latestCriticalAlert} onDismiss={dismissAlert} />

      {/* Main Page Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <Routes>
          <Route path="/" element={<FleetOverviewPage />} />
          <Route path="/vehicles/:vin" element={<VehicleDetailsPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/diagnostics" element={<DiagnosticsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      {/* Enterprise Footer */}
      <footer className="border-t border-slate-900 bg-slate-950/80 py-4 text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-400">FleetGuard Pulse</span>
            <span>•</span>
            <span>High-Throughput Telemetry & Predictive Maintenance</span>
          </div>
          <div className="font-mono text-[11px] text-slate-600">
            PostgreSQL 16 • pgvector • Redis 7 • Redpanda • FastAPI • React
          </div>
        </div>
      </footer>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
};

export default App;
