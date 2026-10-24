"use client";

import { useEffect, useRef, useState } from "react";
import { change, pct, pp, type HotelOverview } from "@/lib/home";
import { Icon } from "./Icons";
import { useI18n } from "./I18n";

const SEEN_KEY = "pms_alerts_seen";

function readSeen(): string[] {
  try {
    return JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]");
  } catch {
    return [];
  }
}

/** The header's bell: the hotel's alerts today (figures well below last year's, low occupancy
 * ahead). The badge counts the ones not seen yet; choosing one asks the assistant about it. */
export default function AlertsBell({ hotel, onAsk }: { hotel: HotelOverview | null; onAsk: (q: string) => void }) {
  const { locale, t } = useI18n();
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState<string[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const alerts = hotel?.alerts ?? [];
  const id = (key: string) => `${hotel?.today}:${hotel?.hotel_code}:${key}`;
  const unseen = alerts.filter((a) => !seen.includes(id(a.key))).length;

  useEffect(() => setSeen(readSeen()), []);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && unseen) {
      const all = [...new Set([...seen, ...alerts.map((a) => id(a.key))])].slice(-200);
      setSeen(all);
      try {
        localStorage.setItem(SEEN_KEY, JSON.stringify(all));
      } catch {}
    }
  }

  if (!hotel) return null;
  const value = (key: string, v: number) =>
    key === "occupancy_today" ? pp(v, locale) : key === "next_30" ? pct(v, locale) : change(v, locale);

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={toggle}
        aria-expanded={open}
        aria-label={unseen ? `${t.alertsTitle} (${unseen})` : t.alertsTitle}
        title={t.alertsTitle}
        className="relative flex size-9 items-center justify-center rounded-xl border border-stone-200 text-stone-600 hover:bg-stone-100 dark:border-stone-700 dark:text-stone-300 dark:hover:bg-stone-900"
      >
        <Icon name="bell" />
        {unseen > 0 && (
          <span className="absolute -right-1 -top-1 flex min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold leading-4 text-white" data-testid="alerts-badge">
            {unseen}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-11 z-40 w-80 rounded-xl border border-stone-200 bg-white p-1.5 shadow-lg dark:border-stone-700 dark:bg-stone-900" data-testid="alerts">
          <p className="px-3 pb-1 pt-1.5 text-xs font-bold uppercase tracking-wider text-stone-500">{t.alertsTitle} · {hotel.name}</p>
          {alerts.length === 0 ? (
            <p className="px-3 py-2 text-sm text-stone-600 dark:text-stone-400">{t.noAlerts}</p>
          ) : (
            alerts.map((a) => (
              <button
                key={a.key}
                onClick={() => {
                  setOpen(false);
                  onAsk(t.alertAsk[a.key](hotel.name));
                }}
                className="flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left text-sm hover:bg-stone-100 dark:hover:bg-stone-800"
              >
                <span className="mt-1.5 size-2 shrink-0 rounded-full bg-red-500" />
                <span>
                  {t.alertText[a.key](value(a.key, a.value) ?? "")}
                  <span className="mt-0.5 block text-xs font-medium text-blue-700 dark:text-blue-300">{t.recommendationAsk} →</span>
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
