import { AlertTriangle, RefreshCw, X } from 'lucide-react';

export interface ErrorAlertProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export function ErrorAlert({ title = 'Operation Failed', message, onRetry, onDismiss }: ErrorAlertProps) {
  return (
    <div className="p-4 rounded-xl border border-red-800/80 bg-red-950/30 text-red-300 flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-red-400 mt-0.5 shrink-0" />
        <div>
          <h4 className="text-sm font-semibold text-red-200">{title}</h4>
          <p className="mt-0.5 text-xs text-red-300/90">{message}</p>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {onRetry && (
          <button
            onClick={onRetry}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-red-900/60 hover:bg-red-800 text-red-100 transition border border-red-700"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Retry
          </button>
        )}
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="p-1 rounded-lg text-red-400 hover:text-red-200 hover:bg-red-900/40 transition"
            title="Dismiss"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}
