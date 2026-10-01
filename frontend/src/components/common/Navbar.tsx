import { NavLink } from 'react-router-dom';
import { Activity, AlertOctagon, BarChart3, Database, Shield, Radio } from 'lucide-react';
import { getDecodedUser } from '../../services/auth';
import { WSConnectionStatus } from '../../types/ws';

interface NavbarProps {
  wsStatus?: WSConnectionStatus;
  activeAlertCount?: number;
}

export function Navbar({ wsStatus = 'CONNECTED', activeAlertCount = 0 }: NavbarProps) {
  const user = getDecodedUser();

  const statusIndicator = {
    CONNECTED: { color: 'bg-emerald-400', ring: 'ring-emerald-400/30', text: 'Live Feed Connected' },
    CONNECTING: { color: 'bg-amber-400', ring: 'ring-amber-400/30', text: 'Connecting...' },
    RECONNECTING: { color: 'bg-amber-400', ring: 'ring-amber-400/30', text: 'Reconnecting...' },
    ERROR: { color: 'bg-red-400', ring: 'ring-red-400/30', text: 'WS Disconnected' },
    DISCONNECTED: { color: 'bg-gray-500', ring: 'ring-gray-500/30', text: 'Disconnected' },
  }[wsStatus];

  return (
    <header className="sticky top-0 z-40 w-full border-b border-gray-800 bg-[#0B0F19]/90 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between gap-4">
          {/* Brand */}
          <div className="flex items-center gap-6">
            <NavLink to="/" className="flex items-center gap-3 group">
              <div className="h-9 w-9 rounded-lg bg-blue-600/20 border border-blue-500/40 flex items-center justify-center text-blue-400 group-hover:scale-105 transition-transform">
                <Activity className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-black tracking-tight text-white text-base">FLEETGUARD</span>
                  <span className="px-1.5 py-0.2 rounded text-[10px] font-bold tracking-widest bg-blue-900/60 text-blue-300 border border-blue-700">PULSE</span>
                </div>
                <p className="text-[10px] text-gray-400 tracking-wider uppercase font-semibold">Vehicle Intelligence</p>
              </div>
            </NavLink>

            {/* Navigation tabs */}
            <nav className="hidden md:flex items-center gap-1">
              <NavLink
                to="/"
                className={({ isActive }) =>
                  `px-3.5 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition ${
                    isActive
                      ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                      : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/40'
                  }`
                }
              >
                <BarChart3 className="w-4 h-4" />
                Fleet Overview
              </NavLink>

              <NavLink
                to="/alerts"
                className={({ isActive }) =>
                  `px-3.5 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition ${
                    isActive
                      ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                      : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/40'
                  }`
                }
              >
                <AlertOctagon className="w-4 h-4" />
                Alerts
                {activeAlertCount > 0 && (
                  <span className="px-1.5 py-0.2 rounded-full text-[10px] font-bold bg-red-600 text-white animate-pulse">
                    {activeAlertCount}
                  </span>
                )}
              </NavLink>

              <NavLink
                to="/diagnostics"
                className={({ isActive }) =>
                  `px-3.5 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition ${
                    isActive
                      ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                      : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/40'
                  }`
                }
              >
                <Database className="w-4 h-4" />
                Vector Diagnostics
              </NavLink>
            </nav>
          </div>

          {/* User & Live status */}
          <div className="flex items-center gap-4">
            {/* Real-time WebSocket connection pill */}
            <div className="hidden sm:flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium bg-gray-900 border border-gray-800">
              <Radio className="w-3.5 h-3.5 text-gray-400" />
              <span className={`w-2 h-2 rounded-full ring-4 ${statusIndicator.color} ${statusIndicator.ring}`}></span>
              <span className="text-[11px] text-gray-300 font-mono">{statusIndicator.text}</span>
            </div>

            {/* Tenant badge */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-900/80 border border-gray-800 text-xs">
              <Shield className="w-3.5 h-3.5 text-blue-400" />
              <div className="text-left">
                <span className="block font-medium text-gray-200 leading-tight">Metro Transit Authority</span>
                <span className="block text-[10px] text-gray-400 leading-tight">
                  {user.roles.join(' • ')}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
