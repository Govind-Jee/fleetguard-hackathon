
export function LoadingSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="w-full space-y-3 animate-pulse p-4">
      <div className="h-6 bg-gray-800 rounded w-1/4 mb-4"></div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 items-center">
          <div className="h-4 bg-gray-800 rounded w-1/5"></div>
          <div className="h-4 bg-gray-800 rounded w-1/6"></div>
          <div className="h-4 bg-gray-800 rounded w-1/4"></div>
          <div className="h-4 bg-gray-800 rounded w-1/6"></div>
          <div className="h-4 bg-gray-800 rounded w-1/6"></div>
        </div>
      ))}
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="p-6 rounded-xl border border-gray-800 bg-gray-900/40 animate-pulse space-y-4">
      <div className="h-4 bg-gray-800 rounded w-1/3"></div>
      <div className="h-8 bg-gray-800 rounded w-1/2"></div>
      <div className="h-3 bg-gray-800 rounded w-2/3"></div>
    </div>
  );
}
