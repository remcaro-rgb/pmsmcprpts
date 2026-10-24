"use client";

import { useState } from "react";
import { change, longDate, money, pct, pp, stamp, trend, type HotelOverview } from "@/lib/home";
import type { StarterCategory } from "@/lib/i18n";
import { Sparkline } from "./Icons";
import { useI18n } from "./I18n";
import Recommendations from "./Recommendations";

type Tile = {
  key: string;
  label: string;
  value: string;
  sub: string | null;
  tone: "up" | "down" | "flat";
  series?: (number | null)[];
  ask: string;
};

function KpiGrid({ hotel, onAsk }: { hotel: HotelOverview; onAsk: (q: string) => void }) {
  const { locale, t } = useI18n();
  const year = Number(hotel.today.slice(0, 4)) - 1;
  const vs = (s: string | null) => (s ? t.vsYear(s, year) : null);
  const m = (v: number | null) => money(v, hotel.currency, locale);
  const h = hotel.name;
  const tiles: Tile[] = [
    {
      key: "occupancy", label: t.kpiOccupancyToday, value: pct(hotel.occupancy_today, locale),
      sub: vs(pp(hotel.occupancy_today_change_pp, locale)), tone: trend(hotel.occupancy_today_change_pp),
      series: hotel.series.occupancy, ask: t.kpiAsk.occupancy(h),
    },
    {
      key: "moves", label: t.kpiMoves, value: `${hotel.arrivals_today ?? "–"} · ${hotel.departures_today ?? "–"}`,
      sub: t.kpiMovesSub, tone: "flat", ask: t.kpiAsk.moves(h),
    },
    {
      key: "adr", label: t.kpiAdr, value: m(hotel.adr_month), sub: vs(change(hotel.adr_month_change, locale)),
      tone: trend(hotel.adr_month_change), series: hotel.series.adr, ask: t.kpiAsk.adr(h),
    },
    {
      key: "revpar", label: t.kpiRevpar, value: m(hotel.revpar_month), sub: vs(change(hotel.revpar_month_change, locale)),
      tone: trend(hotel.revpar_month_change), series: hotel.series.revpar, ask: t.kpiAsk.revpar(h),
    },
    {
      key: "revenue", label: t.kpiRevenue, value: m(hotel.revenue_month), sub: vs(change(hotel.revenue_month_change, locale)),
      tone: trend(hotel.revenue_month_change), series: hotel.series.revenue_month, ask: t.kpiAsk.revenue(h),
    },
    {
      key: "next30", label: t.kpiNext30, value: pct(hotel.occupancy_next_30, locale), sub: t.kpiOnBooks(money(hotel.revenue_next_30, hotel.currency, locale, 100_000)),
      tone: "flat", series: hotel.series.occupancy_next_30, ask: t.kpiAsk.next30(h),
    },
  ];
  const badge = { up: "bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-400", down: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-400", flat: "bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300" };
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-2.5 xl:grid-cols-6" aria-label={t.kpis} data-testid="kpis">
      {tiles.map((k) => (
        <li key={k.key}>
          <button
            onClick={() => onAsk(k.ask)}
            title={k.ask}
            className="flex h-full w-full flex-col items-start gap-0.5 rounded-2xl border border-stone-200 bg-white px-3 py-2.5 text-left hover:border-blue-300 dark:border-stone-800 dark:bg-stone-900 dark:hover:border-blue-800"
          >
            <span className="w-full truncate text-xs font-medium text-stone-500">{k.label}</span>
            <span className="whitespace-nowrap text-lg font-bold tracking-tight tabular-nums sm:text-xl">{k.value}</span>
            {k.sub && <span className={`rounded-md px-1.5 text-[11px] font-semibold ${badge[k.tone]}`}>{k.sub}</span>}
            {k.series && (
              <span className="hidden w-full sm:block">
                <Sparkline values={k.series} tone={k.tone === "flat" ? "flat" : k.tone} />
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

function KpiSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6" aria-busy="true">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="h-[88px] animate-pulse rounded-2xl bg-stone-200/70 sm:h-[112px] dark:bg-stone-800/70" />
      ))}
    </div>
  );
}

function Questions({ hotelName, onAsk }: { hotelName: string; onAsk: (q: string) => void }) {
  const { t } = useI18n();
  const [cat, setCat] = useState<StarterCategory | "all">("all");
  const all = t.starters(hotelName);
  const shown = cat === "all" ? all : all.filter((s) => s.cat === cat);
  const cats = (Object.keys(t.categories) as (StarterCategory | "all")[]).filter(
    (c) => c === "all" || all.some((s) => s.cat === c),
  );
  return (
    <section aria-labelledby="questions-title">
      <h2 id="questions-title" className="text-lg font-semibold tracking-tight">{t.emptyTitle}</h2>
      <div className="mt-2 flex gap-2 overflow-x-auto pb-1 sm:flex-wrap" role="tablist">
        {cats.map((c) => (
          <button
            key={c}
            role="tab"
            aria-selected={c === cat}
            onClick={() => setCat(c)}
            className="shrink-0 rounded-full border border-stone-200 bg-white px-3 py-1 text-sm hover:bg-stone-50 aria-selected:border-stone-900 aria-selected:bg-stone-900 aria-selected:text-white dark:border-stone-700 dark:bg-stone-900 dark:aria-selected:border-stone-100 dark:aria-selected:bg-stone-100 dark:aria-selected:text-stone-900"
          >
            {t.categories[c]}
          </button>
        ))}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {shown.map((s, i) => (
          <button
            key={s.text}
            onClick={() => onAsk(s.text)}
            // Phones show four; the topic tabs reach the rest.
            className={`${cat === "all" && i >= 4 ? "hidden sm:flex" : "flex"} flex-col gap-1 rounded-xl border border-stone-200 bg-white px-3 py-2.5 text-left text-sm hover:border-stone-300 hover:bg-stone-50 sm:p-3 dark:border-stone-800 dark:bg-stone-900 dark:hover:bg-stone-800`}
          >
            <span className="hidden text-xs font-semibold text-stone-500 sm:block">
              {s.kind ? `${s.kind} ` : ""}
              {t.categories[s.cat]}
            </span>
            {s.text}
          </button>
        ))}
      </div>
    </section>
  );
}

/** The welcome screen: the day's key figures, recommendations and questions to start from. */
export default function Home({
  name,
  hotel,
  failed,
  onAsk,
  onRetry,
}: {
  name: string | null;
  hotel: HotelOverview | null; // null while loading
  failed: boolean;
  onAsk: (q: string) => void;
  onRetry: () => void;
}) {
  const { locale, t } = useI18n();
  const hour = new Date().getHours();
  const hotelName = hotel?.name ?? "";
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-5 sm:py-7">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-1">
        <div className="min-w-0">
          <h2 className="text-xl font-bold tracking-tight sm:text-2xl">{t.greeting(hour, name)}</h2>
          {hotel && <p className="mt-0.5 hidden text-stone-500 sm:block">{t.todayLine(hotel.name, longDate(hotel.today, locale))}</p>}
        </div>
        {hotel && (
          <span className="ml-auto inline-flex items-center gap-2 text-xs text-stone-500" data-testid="data-freshness">
            <span className="size-2 rounded-full bg-green-500 ring-4 ring-green-100 dark:ring-green-950" />
            {hotel.data_as_of ? t.dataAsOf(stamp(hotel.data_as_of, locale)) : t.sampleData(hotel.today)}
          </span>
        )}
      </div>

      {failed ? (
        <p className="flex items-center gap-3 text-sm text-stone-500">
          {t.kpisFailed}
          <button onClick={onRetry} className="rounded-lg border border-stone-200 px-2.5 py-1 font-medium dark:border-stone-700">
            {t.retry}
          </button>
        </p>
      ) : hotel ? (
        <KpiGrid hotel={hotel} onAsk={onAsk} />
      ) : (
        <KpiSkeleton />
      )}

      <Recommendations hotel={hotel?.hotel_code ?? null} ready={!!hotel || failed} onAsk={onAsk} />

      {(hotel || failed) && <Questions hotelName={hotelName || t.hotel} onAsk={onAsk} />}
    </div>
  );
}
