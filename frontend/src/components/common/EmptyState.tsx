import { ReactNode } from 'react';
import { Inbox } from 'lucide-react';

interface EmptyStateProps {
  title?: string;
  message?: string;
  actionText?: string;
  onAction?: () => void;
  icon?: ReactNode;
}

export function EmptyState({
  title = 'No Records Found',
  message = 'There are no items matching the selected criteria.',
  actionText,
  onAction,
  icon,
}: EmptyStateProps) {
  return (
    <div className="py-12 px-4 text-center rounded-xl border border-gray-800/80 bg-gray-900/30 flex flex-col items-center justify-center">
      <div className="p-3 rounded-full bg-gray-800/60 text-gray-400 mb-3">
        {icon || <Inbox className="w-6 h-6" />}
      </div>
      <h3 className="text-sm font-semibold text-gray-200">{title}</h3>
      <p className="mt-1 text-xs text-gray-400 max-w-sm">{message}</p>
      {actionText && onAction && (
        <button
          onClick={onAction}
          className="mt-4 px-4 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition"
        >
          {actionText}
        </button>
      )}
    </div>
  );
}
