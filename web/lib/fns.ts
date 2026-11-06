// Hotels imported from FNSrooms, as the agent's /api/admin/fns API returns them.

export type FnsProgress = {
  step?: string;
  steps_done?: number;
  steps_total?: number;
  method?: string;
  window?: string;
  calls?: number;
  planned?: number;
  rows?: number;
  failed?: number;
};

export type FnsRun = {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: "running" | "ok" | "partial" | "failed";
  backfill: boolean;
  calls: number;
  rows: number;
  failed_calls: number;
  errors: string[];
};

export type FnsHotel = {
  id: number;
  alojamiento_id: number;
  central_id: number;
  pms_id: number | null;
  code: string;
  name: string;
  city: string;
  country: string;
  timezone: string;
  moneda_id: number | null;
  currency: string | null;
  sync_time: string; // HH:MM, hotel time
  backfill_days: number;
  enabled: boolean;
  fns_user: string | null;
  has_password: boolean;
  hotel_id: number | null;
  state: "running" | "queued" | "scheduled" | "paused";
  service_silent: boolean;
  current: { id: number; started_at: string; backfill: boolean; progress: FnsProgress } | null;
  last: FnsRun | null;
  history: { loaded: number; total: number; from: string | null };
  next_at: string | null;
};

export type FnsList = {
  hotels: FnsHotel[];
  default_account: boolean;
  can_save_passwords: boolean;
  history_steps: number;
};

/** How far a running import is, 0–100: API calls made of those planned (a range the API rejects is
 * read again in parts, so it stays below 100 until the import finishes). */
export function percent(p: FnsProgress | undefined): number {
  if (!p?.planned) return 0;
  return Math.max(1, Math.min(99, Math.round(((p.calls ?? 0) / p.planned) * 100)));
}

export const LOG_LEVELS = ["error", "warning", "info"] as const;
export type FnsLogLevel = (typeof LOG_LEVELS)[number];

export type FnsLogEntry = {
  id: number;
  at: string;
  level: FnsLogLevel;
  message: string;
  hotel_id: number | null;
  code: string | null;
  run_id: number | null;
  command?: string | null; // a single line's, with its output
  output?: string | null;
};

export type FnsLogPage = {
  entries: FnsLogEntry[];
  counts: Record<FnsLogLevel, number>;
  next_before_id: number | null;
};

/** The import log's query string: whole local days from..to, a hotel, the statuses and a search. */
export function logQuery(f: { from: string; to: string; hotel?: string; levels: readonly FnsLogLevel[]; q?: string; before?: number }): string {
  const p = new URLSearchParams();
  const start = new Date(`${f.from}T00:00:00`);
  const end = new Date(`${f.to}T00:00:00`);
  end.setDate(end.getDate() + 1); // through the end of the last day
  if (!Number.isNaN(start.getTime())) p.set("since", start.toISOString());
  if (!Number.isNaN(end.getTime())) p.set("until", end.toISOString());
  if (f.hotel) p.set("hotel", f.hotel);
  for (const lv of f.levels) p.append("level", lv);
  if (f.q) p.set("q", f.q);
  if (f.before) p.set("before", String(f.before));
  return `?${p.toString()}`;
}
