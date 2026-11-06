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
