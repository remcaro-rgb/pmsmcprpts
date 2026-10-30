// The home screen's key figures (the agent's /api/overview) and how they're written.

import { INTL_LOCALE, type Locale } from "./i18n";

export type HotelOverview = {
  hotel_code: string;
  name: string;
  currency: string;
  data_as_of: string | null; // when FNSrooms data was last imported; null for the sample hotels
  today: string;
  period: { key: Period; start: string; end: string };
  occupancy_today: number | null;
  occupancy_today_change_pp: number | null;
  arrivals_today: number | null;
  departures_today: number | null;
  adr_period: number | null;
  adr_period_change: number | null;
  revpar_period: number | null;
  revpar_period_change: number | null;
  revenue_period: number;
  revenue_period_change: number | null;
  gross_revenue_period: number;
  gross_revenue_period_change: number | null;
  occupancy_next_30: number | null;
  revenue_next_30: number;
  series: Record<string, (number | null)[]>;
  alerts: { key: AlertKey; value: number }[];
};

export const PERIODS = ["mtd", "last_month", "last_7", "last_30", "ytd"] as const;
export type Period = (typeof PERIODS)[number];
export type AlertKey = "occupancy_today" | "adr" | "revenue" | "next_30";

export type Recommendation = {
  title: string;
  detail: string;
  hotel: string;
  question: string;
  impact: string;
  kind: "money" | "risk" | "info";
  ref: string;
  feedback: "up" | "down" | null;
  done: boolean;
};

const MINUS = "−";

const fmt = (locale: Locale, options: Intl.NumberFormatOptions) => new Intl.NumberFormat(INTL_LOCALE[locale], options);

/** 0.784 -> "78.4%". */
export function pct(v: number | null, locale: Locale): string {
  return v == null ? "–" : fmt(locale, { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(v);
}

/** Occupancy points: 0.061 -> "+6.1 pp". */
export function pp(v: number | null, locale: Locale): string | null {
  if (v == null) return null;
  const n = fmt(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(Math.abs(v * 100));
  return `${v < 0 ? MINUS : "+"}${n} pp`;
}

/** Relative change: 0.082 -> "+8.2%". */
export function change(v: number | null, locale: Locale): string | null {
  if (v == null) return null;
  const n = fmt(locale, { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(Math.abs(v));
  return `${v < 0 ? MINUS : "+"}${n}`;
}

// Currencies written with their symbol (as the charts do); the rest with their code ("COP").
const SYMBOLS = new Set(["EUR", "GBP"]);

/** Money in the hotel's currency, shortened from `shortFrom` up: "COP 412,300", "COP 186.4 M", "€147". */
export function money(v: number | null, currency: string, locale: Locale, shortFrom = 1_000_000): string {
  if (v == null) return "–";
  const short = Math.abs(v) >= shortFrom;
  return fmt(locale, {
    style: "currency",
    currency,
    currencyDisplay: SYMBOLS.has(currency) ? "narrowSymbol" : "code",
    notation: short ? "compact" : "standard",
    minimumFractionDigits: 0,
    maximumFractionDigits: short ? 1 : 0,
  }).format(v);
}

/** "sábado, 24 de octubre" for a YYYY-MM-DD date. */
export function longDate(day: string, locale: Locale): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Intl.DateTimeFormat(INTL_LOCALE[locale], { weekday: "long", day: "numeric", month: "long" }).format(
    new Date(y, m - 1, d),
  );
}

/** "24 oct, 03:00" for an import time. */
export function stamp(iso: string, locale: Locale): string {
  return new Intl.DateTimeFormat(INTL_LOCALE[locale], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

/** "up", "down" or "flat" for a change. */
export const trend = (v: number | null): "up" | "down" | "flat" => (v == null || v === 0 ? "flat" : v > 0 ? "up" : "down");
