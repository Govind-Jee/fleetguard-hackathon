import { ReactNode } from 'react';

interface KPICardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: ReactNode;
  trend?: string;
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info';
}

export function KPICard({ title, value, subtitle, icon, variant = 'default' }: KPICardProps) {
  const variantStyles = {
    default: 'border-gray-800 bg-gray-900/60 text-gray-100',
    success: 'border-emerald-800/60 bg-emerald-950/20 text-emerald-400',
    warning: 'border-amber-800/60 bg-amber-950/20 text-amber-400',
    danger: 'border-red-800/60 bg-red-950/20 text-red-400',
    info: 'border-blue-800/60 bg-blue-950/20 text-blue-400',
  }[variant];

  return (
    <div className={`p-5 rounded-xl border backdrop-blur transition-all duration-200 hover:border-gray-700 ${variantStyles}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">{title}</span>
        {icon && <div className="p-2 rounded-lg bg-gray-800/80 text-gray-300">{icon}</div>}
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <span className="text-3xl font-extrabold tracking-tight text-white">{value}</span>
      </div>
      {subtitle && <p className="mt-1 text-xs text-gray-400">{subtitle}</p>}
    </div>
  );
}
