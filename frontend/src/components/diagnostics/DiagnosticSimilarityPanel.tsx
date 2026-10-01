import React, { useState } from 'react';
import { api } from '../../services/api';
import { DiagnosticSimilarityResponse } from '../../types/api';
import { PowertrainBadge } from '../common/Badge';
import { Binary, Search, AlertCircle } from 'lucide-react';

// Preset 16-D normalized diagnostic vectors for quick demonstration
const PRESET_VECTORS = [
  {
    name: 'Engine Overheating (ICE)',
    vehicleType: 'ICE',
    description: 'High coolant temp variance, low oil pressure trend, moderate vibration',
    vector: [0.85, 0.12, 0.05, 0.92, -0.45, 0.22, 0.0, 0.0, 0.0, 0.15, 0.08, 0.0, 0.0, 0.1, 0.05, 0.3],
  },
  {
    name: 'Inverter Thermal Stress (BEV)',
    vehicleType: 'BEV',
    description: 'Elevated pack voltage fluctuation, high cell temp delta, abnormal SOC rate',
    vector: [0.1, 0.05, 0.02, 0.0, 0.0, 0.0, 0.88, 0.76, 0.91, 0.0, 0.0, 0.82, 0.74, 0.05, 0.12, 0.65],
  },
  {
    name: 'Severe Bearing Vibration (ICE/HEV)',
    vehicleType: 'HEV',
    description: 'Atypical vibration amplitude, speed oscillation, engine RPM instability',
    vector: [0.25, 0.89, 0.78, 0.3, -0.1, 0.72, 0.4, 0.35, 0.3, 0.81, 0.65, 0.2, 0.1, 0.45, 0.5, 0.4],
  },
  {
    name: 'Battery Cell Degradation (BEV)',
    vehicleType: 'BEV',
    description: 'High internal resistance signature, abnormal cell temp delta during discharge',
    vector: [0.05, 0.08, 0.02, 0.0, 0.0, 0.0, 0.65, 0.94, 0.89, 0.0, 0.0, 0.78, 0.88, 0.02, 0.05, 0.7],
  },
  {
    name: 'Nominal Operating Profile',
    vehicleType: '',
    description: 'Standard baseline across all 16 normalized feature channels',
    vector: [0.05, 0.02, 0.01, 0.05, 0.0, 0.02, 0.04, 0.03, 0.02, 0.01, 0.02, 0.05, 0.03, 0.02, 0.01, 0.05],
  },
];

export const DiagnosticSimilarityPanel: React.FC = () => {
  const [vectorInput, setVectorInput] = useState<string>(
    JSON.stringify(PRESET_VECTORS[0].vector)
  );
  const [vehicleTypeFilter, setVehicleTypeFilter] = useState<string>('');
  const [limit, setLimit] = useState<number>(5);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [result, setResult] = useState<DiagnosticSimilarityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSelectPreset = (preset: typeof PRESET_VECTORS[0]) => {
    setVectorInput(JSON.stringify(preset.vector));
    if (preset.vehicleType) {
      setVehicleTypeFilter(preset.vehicleType);
    }
  };

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      // Validate vector format
      let parsed: any;
      try {
        parsed = JSON.parse(vectorInput);
      } catch {
        throw new Error('Vector must be valid JSON array of numbers, e.g. [0.1, 0.2, ...]');
      }

      if (!Array.isArray(parsed) || parsed.length !== 16) {
        throw new Error(`Vector must be exactly 16 dimensions (received ${Array.isArray(parsed) ? parsed.length : 'non-array'})`);
      }

      // Check numbers
      const isAllNumbers = parsed.every((n) => typeof n === 'number' && !isNaN(n));
      if (!isAllNumbers) {
        throw new Error('All elements of the 16-D vector must be valid numbers');
      }

      const response = await api.getSimilarDiagnostics({
        vector: parsed.join(','),
        limit,
        vehicle_type: vehicleTypeFilter || undefined,
      });

      setResult(response);
    } catch (err: any) {
      setError(err.message || 'Failed to query vector similarity');
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      {/* Header */}
      <div className="px-5 py-3.5 border-b border-slate-800 bg-slate-950/70 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Binary className="w-4 h-4 text-cyan-400" />
          <h3 className="font-semibold text-sm text-slate-100">
            pgvector Diagnostic Signature Search
          </h3>
          <span className="text-[11px] font-mono text-cyan-400 bg-cyan-950/60 border border-cyan-800/50 px-2 py-0.5 rounded">
            16-Dimensional Cosine Metric
          </span>
        </div>
      </div>

      <div className="p-5 space-y-6">
        {/* Preset Selector */}
        <div>
          <label className="block text-xs font-semibold text-slate-300 mb-2">
            Load Preset Diagnostic Signatures:
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {PRESET_VECTORS.map((p, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => handleSelectPreset(p)}
                className="text-left p-2.5 rounded-lg border border-slate-800 bg-slate-950/60 hover:bg-slate-850 hover:border-slate-700 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-200">{p.name}</span>
                  {p.vehicleType && <PowertrainBadge type={p.vehicleType as any} />}
                </div>
                <div className="text-[11px] text-slate-400 mt-1 line-clamp-1">
                  {p.description}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Query Configuration Form */}
        <form onSubmit={handleSearch} className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-1">
              <label htmlFor="vector-input-area" className="text-xs font-semibold text-slate-300">
                16-D Query Vector (JSON Array):
              </label>
              <span className="text-[11px] text-slate-500 font-mono">
                16 float channels
              </span>
            </div>
            <textarea
              id="vector-input-area"
              rows={2}
              value={vectorInput}
              onChange={(e) => setVectorInput(e.target.value)}
              className="w-full bg-slate-950 border border-slate-750 rounded-lg p-2.5 font-mono text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              placeholder="[0.1, 0.2, 0.3, ...]"
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <label htmlFor="filter-type-select" className="text-xs text-slate-400 font-medium">Vehicle Type:</label>
              <select
                id="filter-type-select"
                value={vehicleTypeFilter}
                onChange={(e) => setVehicleTypeFilter(e.target.value)}
                className="bg-slate-950 border border-slate-750 text-xs text-slate-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              >
                <option value="">All Powertrains</option>
                <option value="ICE">ICE</option>
                <option value="HEV">HEV</option>
                <option value="BEV">BEV</option>
              </select>
            </div>

            <div className="flex items-center gap-2">
              <label htmlFor="limit-select" className="text-xs text-slate-400 font-medium">Top K:</label>
              <select
                id="limit-select"
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="bg-slate-950 border border-slate-750 text-xs text-slate-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              >
                <option value={3}>3 Matches</option>
                <option value={5}>5 Matches</option>
                <option value={10}>10 Matches</option>
              </select>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="ml-auto inline-flex items-center gap-2 px-4 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold shadow-sm disabled:opacity-50 transition-colors"
            >
              {isLoading ? (
                <>Searching...</>
              ) : (
                <>
                  <Search className="w-3.5 h-3.5" />
                  Find Nearest Signatures
                </>
              )}
            </button>
          </div>
        </form>

        {/* Error message */}
        {error && (
          <div className="p-3 rounded-lg bg-rose-950/60 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="space-y-3 pt-2 border-t border-slate-800">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span className="font-semibold text-slate-300">
                Found {result.matches.length} Nearest Fault Signatures
              </span>
              <span className="font-mono text-[11px] text-slate-500">
                {result.methodology}
              </span>
            </div>

            {result.matches.length === 0 ? (
              <div className="text-center py-6 text-slate-400 text-xs bg-slate-950/40 rounded-lg">
                No matching fault signatures found for this criteria.
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {result.matches.map((match) => (
                  <div
                    key={match.signature_id}
                    className="p-3.5 rounded-lg border border-slate-800 bg-slate-950/80 hover:border-cyan-800/50 transition-colors space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-semibold text-xs text-slate-100">
                          {match.fault_type}
                        </span>
                        <PowertrainBadge type={match.vehicle_type as any} />
                      </div>
                      <div className="text-right">
                        <span className="font-mono text-xs font-bold text-cyan-400">
                          {(match.similarity_score * 100).toFixed(1)}% match
                        </span>
                      </div>
                    </div>

                    <p className="text-xs text-slate-400 leading-relaxed">
                      {match.description}
                    </p>

                    <div className="flex items-center justify-between pt-1 border-t border-slate-850 text-[10px] text-slate-500 font-mono">
                      <span>Cosine Distance: {match.cosine_distance.toFixed(4)}</span>
                      <span>Schema: {match.feature_schema_version}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
