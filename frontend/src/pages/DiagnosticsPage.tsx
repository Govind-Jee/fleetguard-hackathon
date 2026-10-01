import React from 'react';
import { DiagnosticSimilarityPanel } from '../components/diagnostics/DiagnosticSimilarityPanel';
import { Binary, Database, Cpu, Compass, Sparkles } from 'lucide-react';

export const DiagnosticsPage: React.FC = () => {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="pb-3 border-b border-slate-800">
        <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
          <Binary className="w-5 h-5 text-cyan-400" />
          <span>Diagnostic Signature Vector Search</span>
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          High-dimensional failure pattern matching powered by PostgreSQL + pgvector
        </p>
      </div>

      {/* Main Diagnostic Panel */}
      <DiagnosticSimilarityPanel />

      {/* Explanatory Architecture Card */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
          <Sparkles className="w-4 h-4 text-cyan-400" />
          <span>Vector Diagnostic Methodology & Feature Representation</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-1.5 font-semibold text-slate-200">
              <Cpu className="w-4 h-4 text-indigo-400" />
              <span>16-Dimensional Embedding</span>
            </div>
            <p className="text-slate-400 text-[11px] leading-relaxed">
              Synthesized from normalized engine telemetry, thermal variances, vibration harmonic
              deviations, electrical pack fluctuation, and DTC frequency patterns.
            </p>
          </div>

          <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-1.5 font-semibold text-slate-200">
              <Database className="w-4 h-4 text-cyan-400" />
              <span>PostgreSQL + pgvector Indexing</span>
            </div>
            <p className="text-slate-400 text-[11px] leading-relaxed">
              Stored as native <code className="text-cyan-300 font-mono">vector(16)</code> types
              indexed with cosine distance (<code className="text-cyan-300 font-mono">&lt;=&gt;</code> operator)
              for sub-millisecond retrieval across enterprise fleets.
            </p>
          </div>

          <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-1.5 font-semibold text-slate-200">
              <Compass className="w-4 h-4 text-emerald-400" />
              <span>Diagnostic Remediation Matching</span>
            </div>
            <p className="text-slate-400 text-[11px] leading-relaxed">
              Matches real-time vehicle anomaly signatures against historic certified failure
              root causes to accelerate technician triage and preventive part replacement.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
