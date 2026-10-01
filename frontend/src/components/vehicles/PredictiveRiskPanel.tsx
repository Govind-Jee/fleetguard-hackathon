import React from 'react';
import { VehicleRiskResponse } from '../../types/api';
import { RiskBadge } from '../common/Badge';
import { 
  ShieldAlert, 
  TrendingUp, 
  TrendingDown, 
  Cpu, 
  Calendar, 
  Wrench,
  Info 
} from 'lucide-react';

interface PredictiveRiskPanelProps {
  riskData?: VehicleRiskResponse | null;
  isLoading: boolean;
  onOpenWorkOrder?: () => void;
}

export const PredictiveRiskPanel: React.FC<PredictiveRiskPanelProps> = ({
  riskData,
  isLoading,
  onOpenWorkOrder,
}) => {
  if (isLoading) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 animate-pulse">
        <div className="h-5 bg-slate-800 rounded w-48 mb-4"></div>
        <div className="h-16 bg-slate-850 rounded mb-4"></div>
        <div className="space-y-3">
          <div className="h-4 bg-slate-800 rounded w-full"></div>
          <div className="h-4 bg-slate-800 rounded w-5/6"></div>
          <div className="h-4 bg-slate-800 rounded w-3/4"></div>
        </div>
      </div>
    );
  }

  if (!riskData) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 text-center text-slate-400">
        <ShieldAlert className="w-8 h-8 text-slate-600 mx-auto mb-2" />
        <h4 className="font-semibold text-slate-300">Risk Assessment Unavailable</h4>
        <p className="text-xs text-slate-500 mt-1">
          Unable to compute 7-day maintenance probability for this vehicle.
        </p>
      </div>
    );
  }

  const probPercent = (riskData.probability_7d * 100).toFixed(1);
  const thresholdPercent = (riskData.decision_threshold * 100).toFixed(0);

  // Color mapping based on risk level
  const riskColor =
    riskData.risk_level === 'CRITICAL'
      ? 'text-rose-400'
      : riskData.risk_level === 'HIGH'
      ? 'text-orange-400'
      : riskData.risk_level === 'MEDIUM'
      ? 'text-amber-400'
      : 'text-emerald-400';

  const progressBg =
    riskData.risk_level === 'CRITICAL'
      ? 'bg-rose-500'
      : riskData.risk_level === 'HIGH'
      ? 'bg-orange-500'
      : riskData.risk_level === 'MEDIUM'
      ? 'bg-amber-500'
      : 'bg-emerald-500';

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      {/* Header */}
      <div className="px-5 py-3.5 border-b border-slate-800 bg-slate-950/70 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-cyan-400" />
          <h3 className="font-semibold text-sm text-slate-100">
            Predictive Maintenance — 7-Day Failure Risk
          </h3>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-mono text-slate-400 flex items-center gap-1">
            <span className="text-slate-500">Model:</span>
            {riskData.model_version}
          </span>
          <RiskBadge level={riskData.risk_level} />
        </div>
      </div>

      <div className="p-5 space-y-6">
        {/* Main Risk Score Card */}
        <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="text-xs uppercase font-semibold tracking-wider text-slate-400">
              Estimated 7-Day Maintenance Risk
            </div>
            <div className="flex items-baseline gap-2">
              <span className={`text-4xl font-extrabold font-mono ${riskColor}`}>
                {probPercent}%
              </span>
              <span className="text-xs text-slate-400">
                (Decision Threshold: {thresholdPercent}%)
              </span>
            </div>
            <div className="text-xs text-slate-300">
              Action Required:{' '}
              {riskData.predicted_maintenance_required ? (
                <span className="text-rose-400 font-semibold">
                  YES — Exceeds dispatch threshold
                </span>
              ) : (
                <span className="text-emerald-400 font-semibold">
                  NO — Within nominal bounds
                </span>
              )}
            </div>
          </div>

          {/* Quick Action Button */}
          {onOpenWorkOrder && (
            <div>
              <button
                onClick={onOpenWorkOrder}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white shadow-sm transition-colors"
              >
                <Wrench className="w-4 h-4" />
                Dispatch Work Order
              </button>
            </div>
          )}
        </div>

        {/* Probability Progress Bar */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs text-slate-400">
            <span>0% (Low Risk)</span>
            <span className="text-slate-300 font-mono">
              Threshold: {thresholdPercent}%
            </span>
            <span>100% (Imminent)</span>
          </div>
          <div className="relative w-full h-3 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
            <div
              className={`h-full ${progressBg} transition-all duration-500 rounded-full`}
              style={{ width: `${Math.min(100, Math.max(0, riskData.probability_7d * 100))}%` }}
            ></div>
            {/* Threshold indicator line */}
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-white shadow-sm"
              style={{ left: `${riskData.decision_threshold * 100}%` }}
              title={`Decision Threshold: ${thresholdPercent}%`}
            ></div>
          </div>
        </div>

        {/* Local Factor Explanations Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Top Risk Increasing Factors */}
          <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3.5 space-y-2.5">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-rose-300">
              <TrendingUp className="w-4 h-4 text-rose-400" />
              <span>Top Risk-Increasing Telemetry Factors</span>
            </div>
            {riskData.top_risk_factors.length === 0 ? (
              <p className="text-xs text-slate-500 italic">No significant risk drivers detected.</p>
            ) : (
              <div className="space-y-2">
                {riskData.top_risk_factors.map((factor) => (
                  <div key={factor.feature_name} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="font-mono text-slate-300 font-medium">
                        {factor.feature_name}
                      </span>
                      <span className="font-mono text-rose-400 font-semibold">
                        +{factor.contribution.toFixed(3)}
                      </span>
                    </div>
                    <div className="flex justify-between text-[11px] text-slate-500">
                      <span>Val: {factor.feature_value !== null && factor.feature_value !== undefined ? factor.feature_value.toFixed(2) : '—'}</span>
                      <span>z-score: {factor.standardized_value.toFixed(2)}</span>
                      <span>coef: {factor.coefficient.toFixed(2)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Top Protective Factors */}
          <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3.5 space-y-2.5">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-300">
              <TrendingDown className="w-4 h-4 text-emerald-400" />
              <span>Top Protective / Mitigating Factors</span>
            </div>
            {riskData.protective_factors.length === 0 ? (
              <p className="text-xs text-slate-500 italic">No mitigating factors found.</p>
            ) : (
              <div className="space-y-2">
                {riskData.protective_factors.map((factor) => (
                  <div key={factor.feature_name} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="font-mono text-slate-300 font-medium">
                        {factor.feature_name}
                      </span>
                      <span className="font-mono text-emerald-400 font-semibold">
                        {factor.contribution.toFixed(3)}
                      </span>
                    </div>
                    <div className="flex justify-between text-[11px] text-slate-500">
                      <span>Val: {factor.feature_value !== null && factor.feature_value !== undefined ? factor.feature_value.toFixed(2) : '—'}</span>
                      <span>z-score: {factor.standardized_value.toFixed(2)}</span>
                      <span>coef: {factor.coefficient.toFixed(2)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Mandatory Probabilistic Disclaimer (Domain Requirement) */}
        <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 flex items-start gap-2.5 text-xs text-slate-400">
          <Info className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <span className="font-semibold text-slate-300">
              Predictive Maintenance Model Notice:
            </span>
            <p className="leading-relaxed">
              {riskData.disclaimer ||
                'Estimated 7-day maintenance risk probability based on historical telemetry patterns. This prediction is probabilistic and does not constitute a guaranteed mechanical failure.'}
            </p>
            <div className="text-[10px] text-slate-500 flex items-center gap-2 pt-1 font-mono">
              <Calendar className="w-3 h-3" />
              Evaluated at: {new Date(riskData.prediction_timestamp).toLocaleString()}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
