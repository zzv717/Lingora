"use client";
/** Lightweight hand-rolled SVG charts (no external deps — always render, even offline). */

export function BarChart({ data, height = 160, unit = "daqiqa", goal }: {
  data: { label: string; value: number }[];
  height?: number;
  unit?: string;
  goal?: number;
}) {
  const max = Math.max(...data.map((d) => d.value), goal || 0, 1);
  return (
    <div className="w-full">
      <div className="flex items-end gap-1.5" style={{ height }}>
        {data.map((d, i) => (
          <div key={i} className="group relative flex h-full flex-1 flex-col justify-end">
            {goal !== undefined && i === 0 && (
              <div className="absolute left-0 right-0 border-t border-dashed border-emerald-400"
                style={{ bottom: `${(goal / max) * 100}%` }} />
            )}
            <div
              className="w-full rounded-t-md bg-brand-500/80 transition-all group-hover:bg-brand-600"
              style={{ height: `${Math.max((d.value / max) * 100, d.value > 0 ? 4 : 1)}%` }}
            />
            <div className="pointer-events-none absolute -top-8 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-md bg-slate-800 px-2 py-1 text-xs text-white opacity-0 transition group-hover:opacity-100">
              {d.value} {unit}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex gap-1.5 text-[10px] text-slate-400">
        {data.map((d, i) => (
          <div key={i} className="flex-1 text-center">{d.label}</div>
        ))}
      </div>
    </div>
  );
}

export function DonutStat({ value, max, label, size = 120, tone = "#6366f1" }: {
  value: number;
  max: number;
  label: string;
  size?: number;
  tone?: string;
}) {
  const pct = max > 0 ? Math.min(1, value / max) : 0;
  const r = size / 2 - 10;
  const c = 2 * Math.PI * r;
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={10}
          className="stroke-slate-200 dark:stroke-slate-700" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={10} stroke={tone}
          strokeDasharray={`${c * pct} ${c}`} strokeLinecap="round" />
      </svg>
      <div className="-mt-[calc(50%+8px)] mb-[calc(50%-14px)] text-center">
        <div className="text-xl font-bold text-slate-800 dark:text-slate-100">{Math.round(pct * 100)}%</div>
      </div>
      <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
    </div>
  );
}

export function StatCard({ title, value, sub, icon, tone = "brand" }: {
  title: string;
  value: string | number;
  sub?: string;
  icon?: React.ReactNode;
  tone?: "brand" | "green" | "amber" | "red" | "blue";
}) {
  const tones = {
    brand: "bg-brand-100 text-brand-600 dark:bg-brand-900/40 dark:text-brand-300",
    green: "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/40 dark:text-emerald-300",
    amber: "bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-300",
    red: "bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-300",
    blue: "bg-sky-100 text-sky-600 dark:bg-sky-900/40 dark:text-sky-300",
  };
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-500 dark:text-slate-400">{title}</span>
        {icon && <span className={`rounded-lg p-1.5 ${tones[tone]}`}>{icon}</span>}
      </div>
      <div className="mt-1 text-2xl font-bold text-slate-800 dark:text-slate-100">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

export function TopicBar({ topic, accuracy, attempts, weak }: {
  topic: string;
  accuracy: number;
  attempts: number;
  weak: boolean;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="font-medium text-slate-700 dark:text-slate-300">{topic}</span>
        <span className={`text-xs ${weak ? "text-red-500" : "text-emerald-600 dark:text-emerald-400"}`}>
          {accuracy}% · {attempts} urinish
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <div className={`h-full rounded-full ${weak ? "bg-red-500" : "bg-emerald-500"}`}
          style={{ width: `${accuracy}%` }} />
      </div>
    </div>
  );
}
