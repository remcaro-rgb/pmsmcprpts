"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FnsHotel, FnsLogEntry, FnsLogLevel, FnsLogPage } from "@/lib/fns";
import { LOG_LEVELS, logQuery } from "@/lib/fns";
import { formatNumber, INTL_LOCALE } from "@/lib/i18n";
import { useI18n } from "./I18n";

type Api = (path: string, method?: string, body?: unknown) => Promise<any>;

const input =
  "mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm outline-none focus:border-accent dark:border-stone-700 dark:bg-stone-900";
const button = "rounded-lg border border-stone-200 px-3 py-1.5 text-sm hover:bg-stone-100 disabled:opacity-50 dark:border-stone-700 dark:hover:bg-stone-900";
const BADGE: Record<FnsLogLevel, string> = {
  error: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200",
  warning: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
  info: "bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300",
};

const day = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** The importer's log, newest first: filter by dates, hotel, status and text; open a line to see the
 * API command that made it and what FNS answered. */
export default function FnsLog({ api }: { api: Api }) {
  const { t, locale } = useI18n();
  const today = new Date();
  const [from, setFrom] = useState(day(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6)));
  const [to, setTo] = useState(day(today));
  const [hotel, setHotel] = useState("");
  const [levels, setLevels] = useState<FnsLogLevel[]>([...LOG_LEVELS]);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState(""); // the search, once typing pauses
  const [hotels, setHotels] = useState<FnsHotel[]>([]);
  const [page, setPage] = useState<FnsLogPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [details, setDetails] = useState<Record<number, FnsLogEntry>>({});
  const asked = useRef(0);

  useEffect(() => {
    api("fns/hotels").then((d) => d && setHotels(d.hotels));
  }, [api]);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 400);
    return () => clearTimeout(timer);
  }, [search]);

  const load = useCallback(
    async (before?: number) => {
      const n = ++asked.current;
      if (!levels.length) {
        // No status chosen: nothing to show (the agent would read none as all).
        setPage((p) => (p ? { ...p, entries: [], next_before_id: null } : p));
        return;
      }
      setBusy(true);
      const data: FnsLogPage | null = await api(`fns/log${logQuery({ from, to, hotel, levels, q: query, before })}`);
      setBusy(false);
      if (!data || n !== asked.current) return; // a newer search replaced this one
      setPage((p) => (before && p ? { ...data, entries: [...p.entries, ...data.entries] } : data));
    },
    [api, from, to, hotel, levels, query],
  );

  useEffect(() => {
    load();
  }, [load]);

  const toggle = async (id: number) => {
    setOpen((o) => (o === id ? null : id));
    if (!details[id]) {
      const d = await api(`fns/log/${id}`);
      if (d) setDetails((all) => ({ ...all, [id]: d }));
    }
  };

  const when = (iso: string) =>
    new Intl.DateTimeFormat(INTL_LOCALE[locale], { dateStyle: "short", timeStyle: "medium" }).format(new Date(iso));
  const total = page ? levels.reduce((sum, lv) => sum + (page.counts[lv] ?? 0), 0) : 0;

  return (
    <section className="mt-4" data-testid="fns-log">
      <p className="text-sm text-stone-500">{t.logIntro}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block text-sm">
          <span className="font-medium">{t.logFrom}</span>
          <input type="date" value={from} max={to} onChange={(e) => e.target.value && setFrom(e.target.value)} className={input} />
        </label>
        <label className="block text-sm">
          <span className="font-medium">{t.logTo}</span>
          <input type="date" value={to} min={from} onChange={(e) => e.target.value && setTo(e.target.value)} className={input} />
        </label>
        <label className="block text-sm">
          <span className="font-medium">{t.logHotel}</span>
          <select value={hotel} onChange={(e) => setHotel(e.target.value)} className={input}>
            <option value="">{t.allHotels}</option>
            {hotels.filter((h) => h.hotel_id).map((h) => (
              <option key={h.id} value={h.hotel_id!}>{h.code} · {h.name}</option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="font-medium">{t.logSearch}</span>
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t.logSearchHint} maxLength={200} className={input} />
        </label>
      </div>
      <fieldset className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <legend className="sr-only">{t.logStatus}</legend>
        {LOG_LEVELS.map((lv) => (
          <label key={lv} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={levels.includes(lv)}
              onChange={(e) => setLevels((all) => (e.target.checked ? [...all, lv] : all.filter((x) => x !== lv)))}
            />
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${BADGE[lv]}`}>{t.logLevels[lv]}</span>
            <span className="tabular-nums text-stone-500" data-testid={`log-count-${lv}`}>{formatNumber(page?.counts[lv] ?? 0, locale)}</span>
          </label>
        ))}
        <button className={`${button} ml-auto`} onClick={() => load()} disabled={busy}>{t.logRefresh}</button>
      </fieldset>

      {page && (
        <p className="mt-3 text-xs text-stone-500">{t.logShowing(formatNumber(page.entries.length, locale), formatNumber(total, locale))}</p>
      )}
      {page && page.entries.length === 0 && <p className="mt-3 text-sm text-stone-500">{t.logEmpty}</p>}
      <ul className="mt-2 divide-y divide-stone-100 rounded-xl border border-stone-200 dark:divide-stone-900 dark:border-stone-800">
        {page?.entries.map((e) => (
          <li key={e.id} data-testid="log-line">
            <button
              onClick={() => toggle(e.id)}
              aria-expanded={open === e.id}
              className="flex w-full flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2 text-left text-sm hover:bg-stone-50 dark:hover:bg-stone-900"
            >
              <span className="shrink-0 tabular-nums text-xs text-stone-500">{when(e.at)}</span>
              <span className="w-14 shrink-0 text-xs font-semibold">{e.code ?? t.logService}</span>
              <span className={`w-24 shrink-0 rounded-full px-2 py-0.5 text-center text-xs font-medium ${BADGE[e.level]}`}>{t.logLevels[e.level]}</span>
              <span className="min-w-0 flex-1 basis-64 break-words">{e.message}</span>
            </button>
            {open === e.id && <Detail entry={details[e.id]} summary={e} />}
          </li>
        ))}
      </ul>
      {page?.next_before_id && (
        <button className={`${button} mt-3`} disabled={busy} onClick={() => load(page.next_before_id!)}>{t.logMore}</button>
      )}
    </section>
  );
}

function Detail({ entry, summary }: { entry: FnsLogEntry | undefined; summary: FnsLogEntry }) {
  const { t } = useI18n();
  if (!entry) return <p className="px-3 pb-3 text-sm text-stone-500">{t.loading}</p>;
  return (
    <div className="space-y-3 px-3 pb-3" data-testid="log-detail">
      {summary.run_id && <p className="text-xs text-stone-500">{t.logRun(summary.run_id)}</p>}
      {!entry.command && !entry.output ? (
        <p className="text-sm text-stone-500">{t.logNoCommand}</p>
      ) : (
        <>
          {entry.command && <Block title={t.logCommand} text={entry.command} hint={t.logCommandHint} />}
          <Block title={t.logOutput} text={entry.output ?? t.logNoOutput} />
        </>
      )}
    </div>
  );
}

function Block({ title, text, hint }: { title: string; text: string; hint?: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <div className="flex items-center gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-stone-500">{title}</h4>
        <button
          className="ml-auto rounded-md border border-stone-200 px-2 py-0.5 text-xs hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-800"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(text);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            } catch {}
          }}
        >
          {copied ? t.copied : t.copy}
        </button>
      </div>
      <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-stone-100 p-2 font-mono text-xs dark:bg-stone-900">{text}</pre>
      {hint && <p className="mt-1 text-xs text-stone-500">{hint}</p>}
    </div>
  );
}
