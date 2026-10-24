"use client";

import { useEffect, useState } from "react";
import type { Locale } from "@/lib/i18n";
import { useI18n } from "./I18n";

export type Recommendation = { title: string; detail: string; hotel: string; question: string };

// One request per language while the page is open; the agent makes them once a day.
const loaded = new Map<Locale, Promise<Recommendation[]>>();

function load(locale: Locale): Promise<Recommendation[]> {
  let p = loaded.get(locale);
  if (!p) {
    p = fetch(`/api/recommendations?language=${locale}`, { cache: "no-store" }).then(async (r) => {
      if (!r.ok) throw new Error(`recommendations ${r.status}`);
      return (await r.json()).recommendations as Recommendation[];
    });
    // A failure is retried next time the welcome screen shows.
    p.catch(() => loaded.delete(locale));
    loaded.set(locale, p);
  }
  return p;
}

/** "Recomendaciones del día" on the welcome screen; choosing one asks the agent for its analysis. */
export default function Recommendations({ onAsk }: { onAsk: (question: string) => void }) {
  const { locale, t } = useI18n();
  const [state, setState] = useState<{ locale: Locale; items: Recommendation[] | null; failed: boolean }>({
    locale,
    items: null,
    failed: false,
  });

  useEffect(() => {
    let cancelled = false;
    load(locale).then(
      (items) => !cancelled && setState({ locale, items, failed: false }),
      () => !cancelled && setState({ locale, items: null, failed: true }),
    );
    return () => {
      cancelled = true;
    };
  }, [locale]);

  const current = state.locale === locale ? state : { items: null, failed: false };

  return (
    <section className="mt-8" aria-labelledby="recommendations-title" data-testid="recommendations">
      <h3 id="recommendations-title" className="text-lg font-semibold tracking-tight">
        {t.recommendationsTitle}
      </h3>
      {current.failed ? (
        <p className="mt-2 text-sm text-stone-500">{t.recommendationsFailed}</p>
      ) : !current.items ? (
        <div className="mt-3 space-y-2" aria-busy="true">
          <p className="text-sm text-stone-500">{t.recommendationsLoading}</p>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-xl bg-stone-200/70 dark:bg-stone-800/70" />
          ))}
        </div>
      ) : (
        <ol className="mt-3 space-y-2">
          {current.items.map((r, i) => (
            <li key={i}>
              <button
                onClick={() => onAsk(r.question || r.title)}
                className="flex w-full gap-3 rounded-xl border border-stone-200 bg-white p-3 text-left hover:border-stone-300 hover:bg-stone-50 dark:border-stone-800 dark:bg-stone-900 dark:hover:bg-stone-800"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-white">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-sm font-semibold">{r.title}</span>
                    {r.hotel && <span className="text-xs text-stone-500">{r.hotel}</span>}
                  </span>
                  <span className="mt-1 block text-sm text-stone-600 dark:text-stone-400">{r.detail}</span>
                  <span className="mt-1 block text-xs font-medium text-accent">{t.recommendationAsk} →</span>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
