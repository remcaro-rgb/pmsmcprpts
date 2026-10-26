"use client";

import { useEffect, useState } from "react";
import type { Recommendation } from "@/lib/home";
import type { Locale } from "@/lib/i18n";
import { Icon } from "./Icons";
import { useI18n } from "./I18n";

type Day = { generated_at: string; recommendations: Recommendation[] };

// One request per language and hotel while the page is open; the agent makes them once a day.
const loaded = new Map<string, Promise<Day>>();

function load(locale: Locale, hotel: string | null): Promise<Day> {
  const key = `${locale}:${hotel ?? ""}`;
  let p = loaded.get(key);
  if (!p) {
    const query = `language=${locale}${hotel ? `&hotel=${encodeURIComponent(hotel)}` : ""}`;
    p = fetch(`/api/recommendations?${query}`, { cache: "no-store" }).then(async (r) => {
      if (!r.ok) throw new Error(`recommendations ${r.status}`);
      return (await r.json()) as Day;
    });
    // A failure is tried again next time.
    p.catch(() => loaded.delete(key));
    loaded.set(key, p);
  }
  return p;
}

const IMPACT = {
  money: "bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-400",
  risk: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-400",
  info: "bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300",
};

function hhmm(iso: string): string {
  return iso.slice(11, 16);
}

/** "Recomendaciones del día": choosing one asks the agent for its analysis; each takes a thumbs up
 * or down and can be marked done. */
export default function Recommendations({
  hotel,
  ready,
  onAsk,
}: {
  hotel: string | null;
  ready: boolean; // the hotel is known (or the key figures failed)
  onAsk: (question: string) => void;
}) {
  const { locale, t } = useI18n();
  const key = `${locale}:${hotel ?? ""}`;
  const [state, setState] = useState<{ key: string; day: Day | null; failed: boolean }>({ key, day: null, failed: false });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    load(locale, hotel).then(
      (day) => !cancelled && setState({ key, day, failed: false }),
      () => !cancelled && setState({ key, day: null, failed: true }),
    );
    return () => {
      cancelled = true;
    };
  }, [locale, hotel, ready, key, attempt]);

  const current = state.key === key ? state : { day: null, failed: false };

  function save(i: number, change: Partial<Recommendation>, ref: string, value: string | null) {
    if (!current.day) return;
    const recommendations = current.day.recommendations.map((r, j) => (j === i ? { ...r, ...change } : r));
    const day = { ...current.day, recommendations };
    loaded.set(key, Promise.resolve(day));
    setState({ key, day, failed: false });
    fetch("/api/feedback", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ kind: "recommendation", ref, value, note: recommendations[i].title }),
    }).catch(() => {});
  }

  function vote(i: number, value: "up" | "down") {
    const rec = current.day?.recommendations[i];
    if (!rec) return;
    const next = rec.feedback === value ? null : value;
    save(i, { feedback: next }, rec.ref, next);
  }

  function toggleDone(i: number) {
    const rec = current.day?.recommendations[i];
    if (!rec) return;
    save(i, { done: !rec.done }, `${rec.ref}:done`, rec.done ? null : "done");
  }

  const small = "inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs";
  const plain = `${small} border-stone-200 text-stone-600 hover:bg-stone-50 dark:border-stone-700 dark:text-stone-300 dark:hover:bg-stone-800`;
  const on = `${small} border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300`;

  return (
    <section aria-labelledby="recommendations-title" data-testid="recommendations">
      <div className="mb-2 flex items-center gap-2">
        <Icon name="spark" className="size-[18px] text-accent" />
        <h2 id="recommendations-title" className="text-lg font-semibold tracking-tight">
          {t.recommendationsTitle}
        </h2>
        {current.day && (
          <span className="ml-auto hidden text-xs text-stone-500 sm:inline">{t.updatedAt(hhmm(current.day.generated_at))}</span>
        )}
      </div>
      {current.failed ? (
        <p className="flex items-center gap-3 text-sm text-stone-500">
          {t.recommendationsFailed}
          <button
            onClick={() => {
              setState({ key, day: null, failed: false });
              setAttempt((a) => a + 1);
            }}
            className="rounded-lg border border-stone-200 px-2.5 py-1 font-medium dark:border-stone-700"
          >
            {t.retry}
          </button>
        </p>
      ) : !current.day ? (
        <div className="space-y-2" aria-busy="true">
          <p className="text-sm text-stone-500">{t.recommendationsLoading}</p>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-20 animate-pulse rounded-2xl bg-stone-200/70 dark:bg-stone-800/70" />
          ))}
        </div>
      ) : (
        <ol className="divide-y divide-stone-100 overflow-hidden rounded-2xl border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
          {current.day.recommendations.map((r, i) => {
            const done = r.done;
            return (
              <li key={r.ref} className={`flex gap-3 px-4 py-3.5 ${done ? "opacity-60" : ""}`}>
                <span className={`flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white ${done ? "bg-green-600" : "bg-accent"}`}>
                  {done ? <Icon name="check" className="size-3.5" /> : i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className={`text-[15px] font-semibold ${done ? "line-through" : ""}`}>{r.title}</span>
                    {r.impact && <span className={`rounded-full px-2 py-px text-xs font-semibold ${IMPACT[r.kind] ?? IMPACT.info}`}>{r.impact}</span>}
                    {r.hotel && <span className="text-xs text-stone-500">{r.hotel}</span>}
                  </div>
                  <p className="mt-1 text-sm text-stone-600 dark:text-stone-400">{r.detail}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <button onClick={() => onAsk(r.question || r.title)} className={`${on} font-semibold`}>
                      <Icon name="chevron" className="size-3.5" />
                      {t.recommendationAsk}
                    </button>
                    <button onClick={() => toggleDone(i)} aria-pressed={done} className={done ? on : plain} title={t.markDone}>
                      <Icon name="check" className="size-3.5" />
                      {t.markedDone}
                    </button>
                    <span className="flex-1" />
                    <button onClick={() => vote(i, "up")} aria-pressed={r.feedback === "up"} aria-label={t.useful} title={t.useful} className={r.feedback === "up" ? on : plain}>
                      <Icon name="up" className="size-3.5" />
                    </button>
                    <button onClick={() => vote(i, "down")} aria-pressed={r.feedback === "down"} aria-label={t.notUseful} title={t.notUseful} className={r.feedback === "down" ? on : plain}>
                      <Icon name="down" className="size-3.5" />
                    </button>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
