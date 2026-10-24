"use client";

import { useEffect, useRef, useState } from "react";
import type { Schedule } from "@/lib/reports";
import { useI18n } from "./I18n";

export type ReportDraft = { title: string; question: string; schedule: Schedule; weekday: number };

/** Saves an answer's question as a report (or edits one): its name and whether it's emailed. */
export default function ReportDialog({
  draft,
  schedulingAvailable,
  sendTime,
  onSave,
  onClose,
}: {
  draft: ReportDraft;
  schedulingAvailable: boolean;
  sendTime: string;
  onSave: (draft: ReportDraft) => Promise<string | null>; // an error to show, or null when saved
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [value, setValue] = useState(draft);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    titleRef.current?.select();
    const close = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [onClose]);

  const field = "w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-accent dark:border-stone-700 dark:bg-stone-950";
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t.saveReport}
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-3 sm:items-center"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setSaving(true);
          setError(await onSave({ ...value, title: value.title.trim() || draft.title }));
          setSaving(false);
        }}
        className="w-full max-w-md space-y-4 rounded-2xl bg-white p-5 shadow-2xl dark:bg-stone-900"
      >
        <h2 className="text-lg font-semibold">{t.saveReport}</h2>
        <label className="block space-y-1 text-sm">
          <span className="font-medium">{t.reportName}</span>
          <input ref={titleRef} value={value.title} maxLength={200} onChange={(e) => setValue({ ...value, title: e.target.value })} className={field} />
        </label>
        <div className="text-sm">
          <p className="text-stone-500">{t.reportQuestion}</p>
          <p className="mt-1 rounded-lg bg-stone-100 px-3 py-2 dark:bg-stone-800">{value.question}</p>
        </div>
        <fieldset className="space-y-1.5 text-sm">
          <legend className="mb-1 font-medium">{t.emailIt}</legend>
          {(["none", "daily", "weekly", "monthly"] as Schedule[]).map((s) => (
            <label key={s} className={`flex items-center gap-2 ${s !== "none" && !schedulingAvailable ? "opacity-50" : ""}`}>
              <input
                type="radio"
                name="schedule"
                value={s}
                checked={value.schedule === s}
                disabled={s !== "none" && !schedulingAvailable}
                onChange={() => setValue({ ...value, schedule: s })}
                className="accent-blue-600"
              />
              {t.schedules[s](sendTime)}
              {s === "weekly" && value.schedule === "weekly" && (
                <select
                  value={value.weekday}
                  onChange={(e) => setValue({ ...value, weekday: Number(e.target.value) })}
                  aria-label={t.weekdayLabel}
                  className="ml-1 rounded-md border border-stone-300 bg-transparent px-1.5 py-0.5 dark:border-stone-700"
                >
                  {t.weekdays.map((d, i) => (
                    <option key={d} value={i}>
                      {d}
                    </option>
                  ))}
                </select>
              )}
            </label>
          ))}
          {!schedulingAvailable && <p className="pt-1 text-xs text-stone-500">{t.scheduleNeedsEmail}</p>}
        </fieldset>
        {error && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-stone-200 px-4 py-1.5 text-sm dark:border-stone-700">
            {t.cancel}
          </button>
          <button type="submit" disabled={saving} className="rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50">
            {t.save}
          </button>
        </div>
      </form>
    </div>
  );
}
