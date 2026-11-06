"use client";

import { useCallback, useEffect, useState } from "react";
import { percent, type FnsHotel, type FnsList, type FnsRun } from "@/lib/fns";
import { formatNumber, INTL_LOCALE } from "@/lib/i18n";
import { useI18n } from "./I18n";

type Api = (path: string, method?: string, body?: unknown) => Promise<any>;

type Form = {
  alojamiento_id: string;
  central_id: string;
  pms_id: string;
  code: string;
  name: string;
  city: string;
  country: string;
  timezone: string;
  moneda_id: string;
  currency: string;
  sync_time: string;
  backfill_days: string;
  fns_user: string;
  fns_password: string;
  enabled: boolean;
};

const browserZone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Madrid";
  } catch {
    return "Europe/Madrid";
  }
};

const EMPTY = (): Form => ({
  alojamiento_id: "", central_id: "", pms_id: "", code: "", name: "", city: "", country: "", timezone: browserZone(),
  moneda_id: "", currency: "", sync_time: "03:00", backfill_days: "365", fns_user: "", fns_password: "", enabled: true,
});

const input =
  "mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-accent dark:border-stone-700 dark:bg-stone-900";
const button = "rounded-lg border border-stone-200 px-3 py-1.5 text-sm hover:bg-stone-100 disabled:opacity-50 dark:border-stone-700 dark:hover:bg-stone-900";
const primary = "rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50";

const ID = /^[1-9][0-9]{0,9}$/;

/** The body the agent expects: numbers as numbers, empty optional fields left out (or cleared). */
function body(form: Form, editing: boolean): Record<string, unknown> {
  const num = (v: string) => (v.trim() ? Number(v) : null);
  const out: Record<string, unknown> = {
    alojamiento_id: num(form.alojamiento_id), central_id: num(form.central_id), pms_id: num(form.pms_id),
    code: form.code.trim().toUpperCase(), name: form.name.trim(), city: form.city.trim(), country: form.country.trim(),
    timezone: form.timezone.trim(), moneda_id: num(form.moneda_id), currency: form.currency.trim().toUpperCase(),
    sync_time: form.sync_time, backfill_days: num(form.backfill_days), fns_user: form.fns_user.trim(), enabled: form.enabled,
  };
  if (form.fns_password) out.fns_password = form.fns_password;
  if (!editing) for (const k of Object.keys(out)) if (out[k] === null || out[k] === "") delete out[k];
  return out;
}

export default function FnsPanel({ api, onNotice }: { api: Api; onNotice: (text: string) => void }) {
  const { t } = useI18n();
  const [data, setData] = useState<FnsList | null>(null);
  const [editing, setEditing] = useState<FnsHotel | "new" | null>(null);

  const load = useCallback(async () => {
    const d = await api("fns/hotels");
    if (d) setData(d);
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  // Every few seconds while something imports or waits to, else every minute.
  const busy = data?.hotels.some((h) => h.state === "running" || h.state === "queued");
  useEffect(() => {
    if (editing) return;
    const timer = setInterval(load, busy ? 4000 : 60000);
    return () => clearInterval(timer);
  }, [busy, editing, load]);

  if (editing) {
    return (
      <HotelForm
        hotel={editing === "new" ? null : editing}
        list={data}
        api={api}
        onCancel={() => setEditing(null)}
        onSaved={async (isNew) => {
          setEditing(null);
          onNotice(isNew ? t.fnsAdded : t.saved);
          await load();
        }}
      />
    );
  }

  return (
    <section className="mt-4" data-testid="fns-panel">
      <p className="text-sm text-stone-500">{t.fnsIntro}</p>
      <button className={`${primary} mt-3`} onClick={() => setEditing("new")}>{t.fnsAdd}</button>
      {data && data.hotels.length === 0 && <p className="mt-4 text-sm text-stone-500">{t.fnsNoHotels}</p>}
      <ul className="mt-4 space-y-3">
        {data?.hotels.map((h) => (
          <HotelCard
            key={h.id}
            hotel={h}
            api={api}
            onEdit={() => setEditing(h)}
            onChanged={async (notice) => {
              if (notice) onNotice(notice);
              await load();
            }}
          />
        ))}
      </ul>
    </section>
  );
}

function HotelCard({
  hotel: h,
  api,
  onEdit,
  onChanged,
}: {
  hotel: FnsHotel;
  api: Api;
  onEdit: () => void;
  onChanged: (notice?: string) => Promise<void>;
}) {
  const { t, locale } = useI18n();
  const [runs, setRuns] = useState<FnsRun[] | null>(null);
  const n = (v: number | undefined) => formatNumber(v ?? 0, locale);
  // In the hotel's time, as its import time is set.
  const when = (iso: string) =>
    new Intl.DateTimeFormat(INTL_LOCALE[locale], { dateStyle: "medium", timeStyle: "short", timeZone: h.timezone }).format(new Date(iso));
  const p = h.current?.progress;
  const pct = percent(p);
  const badge = {
    running: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200",
    queued: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
    scheduled: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
    paused: "bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300",
  }[h.state];

  const showRuns = async () => {
    if (runs) return setRuns(null);
    const d = await api(`fns/hotels/${h.id}/runs`);
    if (d) setRuns(d.runs);
  };

  return (
    <li className="rounded-xl border border-stone-200 p-4 dark:border-stone-800" data-testid={`fns-hotel-${h.code}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{h.code}</span>
        <span>{h.name}</span>
        {h.city && <span className="text-sm text-stone-500">{h.city}</span>}
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badge}`} data-testid="fns-state">{t.fnsState[h.state]}</span>
        <span className="ml-auto flex flex-wrap gap-2">
          <button
            className={button}
            disabled={h.state !== "scheduled"}
            onClick={async () => {
              if (await api(`fns/hotels/${h.id}/run`, "POST")) await onChanged(t.fnsImportAsked);
            }}
          >
            {t.fnsImportNow}
          </button>
          <button
            className={button}
            onClick={async () => {
              if (await api(`fns/hotels/${h.id}`, "PATCH", { enabled: !h.enabled })) await onChanged();
            }}
          >
            {h.enabled ? t.fnsPause : t.fnsResume}
          </button>
          <button className={button} aria-label={`${t.edit} ${h.code}`} onClick={onEdit}>{t.edit}</button>
        </span>
      </div>
      <p className="mt-1 text-xs text-stone-500">
        {t.fnsAlojamientoId} {h.alojamiento_id} · {t.fnsCentralId} {h.central_id} · {h.timezone} · {h.currency ?? "—"}
      </p>

      {h.current && (
        <div className="mt-3" data-testid="fns-progress">
          <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
            <span className="font-medium">{h.current.backfill ? t.fnsLoadingHistory : t.fnsDaily}</span>
            <span className="text-stone-500">· {t.fnsSteps[p?.step ?? ""] ?? p?.step}</span>
            {p?.steps_total ? <span className="text-stone-500">({t.fnsStepOf(Math.min((p.steps_done ?? 0) + 1, p.steps_total), p.steps_total)})</span> : null}
            <span className="ml-auto font-semibold tabular-nums">{pct}%</span>
          </div>
          <div
            className="mt-1.5 h-2 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={h.current.backfill ? t.fnsLoadingHistory : t.fnsDaily}
          >
            <div className="h-full rounded-full bg-accent transition-[width] duration-700" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-1 text-xs text-stone-500">
            {t.fnsCalls(n(p?.calls), n(p?.planned))} · {t.fnsRows(n(p?.rows))}
            {p?.failed ? <span className="text-red-700 dark:text-red-400"> · {t.fnsFailedCalls(p.failed)}</span> : null}
            {p?.window ? ` · ${p.window}` : ""} · {t.fnsStarted(when(h.current.started_at))}
          </p>
        </div>
      )}

      <div className="mt-3 grid gap-1 text-sm sm:grid-cols-2">
        <p>
          {t.fnsHistory(h.history.loaded, h.history.total)}
          {h.history.from && (
            <span className="text-stone-500">
              {" "}· {t.fnsHistoryFrom(new Intl.DateTimeFormat(INTL_LOCALE[locale], { dateStyle: "medium", timeZone: "UTC" }).format(new Date(h.history.from)))}
            </span>
          )}
        </p>
        {h.state !== "running" && (
          <p className="sm:text-right">
            {h.next_at === null ? t.fnsState.paused : h.state === "queued" || new Date(h.next_at) <= new Date() ? t.fnsNextNow : t.fnsNext(when(h.next_at))}
          </p>
        )}
      </div>
      {h.service_silent && (
        <p role="alert" className="mt-2 text-sm text-amber-700 dark:text-amber-400">{t.fnsServiceSilent}</p>
      )}
      {h.last && <RunLine run={h.last} when={when} label={t.fnsLast} />}

      <button className="mt-2 text-sm text-accent hover:underline" onClick={showRuns}>{runs ? t.fnsHideRuns : t.fnsShowRuns}</button>
      {runs && (
        <ul className="mt-2 space-y-1 border-l-2 border-stone-200 pl-3 dark:border-stone-800">
          {runs.length === 0 && <li className="text-sm text-stone-500">{t.fnsNoRuns}</li>}
          {runs.map((r) => <li key={r.id}><RunLine run={r} when={when} /></li>)}
        </ul>
      )}
    </li>
  );
}

function RunLine({ run, when, label }: { run: FnsRun; when: (iso: string) => string; label?: string }) {
  const { t, locale } = useI18n();
  const color = { ok: "text-emerald-700 dark:text-emerald-400", partial: "text-amber-700 dark:text-amber-400", failed: "text-red-700 dark:text-red-400", running: "text-blue-700 dark:text-blue-300" }[run.status];
  return (
    <div className="mt-2 text-sm">
      <p>
        {label && <span className="font-medium">{label}: </span>}
        <span className={`font-medium ${color}`}>{t.fnsRunStatus[run.status]}</span>
        <span className="text-stone-500">
          {" "}· {when(run.started_at)}
          {run.backfill ? ` · ${t.fnsFirst}` : ""} · {t.fnsRows(formatNumber(run.rows, locale))}
          {run.failed_calls ? ` · ${t.fnsFailedCalls(run.failed_calls)}` : ""}
        </span>
      </p>
      {run.errors.length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer text-xs text-stone-500">{t.fnsRetry}</summary>
          <ul className="mt-1 space-y-0.5 text-xs text-red-700 dark:text-red-400">
            {run.errors.map((e, i) => <li key={i} className="break-words">{e}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}

function HotelForm({
  hotel,
  list,
  api,
  onCancel,
  onSaved,
}: {
  hotel: FnsHotel | null;
  list: FnsList | null;
  api: Api;
  onCancel: () => void;
  onSaved: (isNew: boolean) => Promise<void>;
}) {
  const { t } = useI18n();
  const [form, setForm] = useState<Form>(
    hotel
      ? {
          alojamiento_id: String(hotel.alojamiento_id), central_id: String(hotel.central_id), pms_id: hotel.pms_id ? String(hotel.pms_id) : "",
          code: hotel.code, name: hotel.name, city: hotel.city, country: hotel.country, timezone: hotel.timezone,
          moneda_id: hotel.moneda_id ? String(hotel.moneda_id) : "", currency: hotel.currency ?? "", sync_time: hotel.sync_time,
          backfill_days: String(hotel.backfill_days), fns_user: hotel.fns_user ?? "", fns_password: "", enabled: hotel.enabled,
        }
      : EMPTY(),
  );
  const [busy, setBusy] = useState(false);
  const [check, setCheck] = useState<{ ok: boolean; message: string } | null>(null);
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));
  const field = (key: keyof Omit<Form, "enabled">, label: string, extra: Record<string, unknown> = {}, hint?: string) => (
    <div className="text-sm">
      <label className="block">
        <span className="font-medium">{label}</span>
        <input
          name={key}
          value={form[key]}
          onChange={(e) => set(key, e.target.value)}
          className={input}
          aria-describedby={hint ? `fns-${key}-hint` : undefined}
          {...extra}
        />
      </label>
      {hint && <span id={`fns-${key}-hint`} className="mt-1 block text-xs text-stone-500">{hint}</span>}
    </div>
  );
  const id = { inputMode: "numeric", pattern: ID.source, maxLength: 10 };
  const ownAccount = form.fns_user.trim() !== "";
  const accountHint = list?.default_account ? t.fnsAccountDefault : t.fnsAccountRequired;

  return (
    <form
      className="mt-4 max-w-2xl space-y-5"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        const saved = hotel ? await api(`fns/hotels/${hotel.id}`, "PATCH", body(form, true)) : await api("fns/hotels", "POST", body(form, false));
        setBusy(false);
        if (saved) await onSaved(!hotel);
      }}
    >
      <h2 className="text-base font-semibold">{hotel ? t.fnsEdit : t.fnsAdd}</h2>

      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-stone-600 dark:text-stone-300">{t.fnsSectionIds}</legend>
        <div className="grid gap-4 sm:grid-cols-3">
          {field("alojamiento_id", t.fnsAlojamientoId, { ...id, required: true })}
          {field("central_id", t.fnsCentralId, { ...id, required: true })}
          {field("pms_id", t.fnsPmsId, id)}
        </div>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-stone-600 dark:text-stone-300">{t.fnsSectionAccount}</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          {field("fns_user", t.fnsUser, { autoComplete: "off", maxLength: 200, required: !list?.default_account })}
          {field("fns_password", t.fnsPassword, {
            type: "password", autoComplete: "new-password", maxLength: 200,
            required: ownAccount && !(hotel?.has_password && hotel.fns_user === form.fns_user.trim()),
            disabled: !ownAccount && !!list?.default_account,
          }, hotel?.has_password && ownAccount ? t.fnsPasswordKeep : undefined)}
        </div>
        <p className="text-xs text-stone-500">{accountHint}</p>
        {ownAccount && list && !list.can_save_passwords && <p className="text-xs text-amber-700 dark:text-amber-400">{t.fnsNoSecretKey}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className={button}
            disabled={!ID.test(form.alojamiento_id) || check?.message === t.fnsChecking}
            onClick={async () => {
              setCheck({ ok: true, message: t.fnsChecking });
              const r = await api("fns/check", "POST", {
                alojamiento_id: Number(form.alojamiento_id),
                pms_id: form.pms_id ? Number(form.pms_id) : undefined,
                fns_user: form.fns_user.trim() || undefined,
                fns_password: form.fns_password || undefined,
                hotel: hotel?.id,
              });
              setCheck(r ?? null);
            }}
          >
            {t.fnsCheck}
          </button>
          {check && (
            <span role="status" data-testid="fns-check" className={`text-sm ${check.ok ? "text-emerald-700 dark:text-emerald-400" : "text-red-700 dark:text-red-400"}`}>
              {check.message}
            </span>
          )}
        </div>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-stone-600 dark:text-stone-300">{t.fnsSectionHotel}</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          {field("name", t.fieldName, { required: true, maxLength: 200 })}
          {field("code", t.fnsCode, { required: true, pattern: "[A-Za-z0-9_\\-]{2,12}", maxLength: 12 }, t.fnsCodeHint)}
          {field("city", t.colCity, { maxLength: 100 })}
          {field("country", t.fnsCountry, { maxLength: 100 })}
          {field("timezone", t.fnsTimezone, { required: true, maxLength: 64, list: "fns-zones" }, t.fnsTimezoneHint)}
        </div>
        <datalist id="fns-zones">
          {["America/Bogota", "America/Mexico_City", "America/Lima", "America/Santiago", "America/Argentina/Buenos_Aires", "America/New_York", "Europe/Madrid", "Europe/Lisbon", "Atlantic/Canary", "UTC"].map((z) => (
            <option key={z} value={z} />
          ))}
        </datalist>
        <div className="grid gap-4 sm:grid-cols-2">
          {field("moneda_id", t.fnsMonedaId, id)}
          {field("currency", t.fnsCurrency, { pattern: "[A-Za-z]{3}", maxLength: 3 })}
        </div>
        <p className="text-xs text-stone-500">{t.fnsCurrencyHint}</p>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-stone-600 dark:text-stone-300">{t.fnsSectionImport}</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          {field("sync_time", t.fnsSyncTime, { type: "time", required: true })}
          {field("backfill_days", t.fnsBackfill, { type: "number", min: 1, max: 3660, required: true })}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="enabled" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          {t.fnsEnabled}
        </label>
      </fieldset>

      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy} className={primary}>{hotel ? t.save : t.fnsSaveNew}</button>
        <button type="button" onClick={onCancel} className={button}>{t.cancel}</button>
      </div>
    </form>
  );
}
