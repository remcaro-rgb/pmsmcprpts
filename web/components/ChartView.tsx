"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { fileUrl, type ChartPayload, type FileInfo, type LegacyChart } from "@/lib/chat";
import { useI18n } from "./I18n";
import { Icon } from "./Icons";

/** Follows the light/dark switch (the `dark` class on <html>). */
function subscribeTheme(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}
const isDark = () => document.documentElement.classList.contains("dark");

/** Draws the Vega-Lite spec with vega-embed, loaded on first use. Expressions run in Vega's
 * interpreter (no generated code) and nothing is loaded from the network: the data is in the spec. */
function VegaChart({ chart, onError }: { chart: ChartPayload; onError: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const dark = useSyncExternalStore(subscribeTheme, isDark, () => false);

  useEffect(() => {
    let finalize: (() => void) | undefined;
    let cancelled = false;
    (async () => {
      const [{ default: embed }, vega, { expressionInterpreter }] = await Promise.all([
        import("vega-embed"),
        import("vega"),
        import("vega-interpreter"),
      ]);
      if (cancelled || !ref.current) return;
      const loader = vega.loader();
      loader.sanitize = async () => {
        throw new Error("Charts don't load anything from the network.");
      };
      const result = await embed(ref.current, chart.spec as never, {
        renderer: "svg",
        actions: false,
        ast: true,
        expr: expressionInterpreter,
        loader,
        config: (dark ? chart.config.dark : chart.config.light) as never,
        formatLocale: chart.locale.number,
        timeFormatLocale: chart.locale.time,
        tooltip: { theme: dark ? "dark" : "light" },
      });
      if (cancelled) result.finalize();
      else finalize = result.finalize;
    })().catch((e) => {
      console.error("chart", e);
      if (!cancelled) onError();
    });
    return () => {
      cancelled = true;
      finalize?.();
    };
  }, [chart, dark, onError]);

  return <div ref={ref} className="w-full [&_svg]:max-w-full" data-testid="chart-canvas" role="figure" aria-label={chart.title} />;
}

function DataTable({ table }: { table: ChartPayload["table"] }) {
  return (
    <div className="max-h-72 overflow-auto border-t border-black/5 dark:border-white/5">
      <table className="w-full text-[13px]">
        <thead className="sticky top-0 bg-stone-100 dark:bg-stone-900">
          <tr>
            {table.columns.map((c, i) => (
              <th
                key={i}
                className={`px-3 py-1.5 font-medium text-stone-600 dark:text-stone-300 ${table.numeric[i] ? "text-right" : "text-left"}`}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {table.rows.map((row, r) => (
            <tr key={r} className="border-t border-black/5 dark:border-white/5">
              {row.map((cell, i) => (
                <td key={i} className={`whitespace-nowrap px-3 py-1 ${table.numeric[i] ? "text-right" : ""}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ChartView({ chart, file }: { chart: ChartPayload | LegacyChart; file: FileInfo | null }) {
  const { t } = useI18n();
  const [showData, setShowData] = useState(false);
  const [failed, setFailed] = useState(false);
  const [full, setFull] = useState(false);
  const [kind, setKind] = useState<string | null>(null);
  const onError = useCallback(() => setFailed(true), []);
  const original = "kind" in chart ? chart : null;
  // The chart as the type picked in the switch: the server built each one; they share the data.
  const vega = useMemo(() => {
    const variant = kind && original?.variants?.[kind];
    return original && variant ? { ...original, spec: { ...variant, data: original.spec.data } } : original;
  }, [original, kind]);
  const types = original?.type && original.variants ? [original.type, ...Object.keys(original.variants)] : [];

  useEffect(() => {
    if (!full) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setFull(false);
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [full]);

  return (
    <figure
      className="overflow-hidden rounded-xl border border-black/10 bg-[#fcfcfb] dark:border-white/10 dark:bg-[#1a1a19]"
      data-testid="chart"
    >
      {vega && !failed ? (
        <VegaChart chart={vega} onError={onError} />
      ) : "svg_light" in chart ? (
        <>
          {/* Charts saved before the Vega-Lite charts: server-rendered SVGs (labels XML-escaped). */}
          <div className="dark:hidden [&_svg]:h-auto [&_svg]:w-full" dangerouslySetInnerHTML={{ __html: chart.svg_light }} />
          <div className="hidden dark:block [&_svg]:h-auto [&_svg]:w-full" dangerouslySetInnerHTML={{ __html: chart.svg_dark }} />
        </>
      ) : (
        <p className="px-4 py-6 text-sm text-stone-500">{t.chartFailed}</p>
      )}

      <figcaption className="flex items-center gap-3 border-t border-black/5 px-4 py-2 text-xs dark:border-white/5">
        {types.length > 1 && !failed && (
          <div role="group" aria-label={t.chartType} className="flex overflow-hidden rounded-lg border border-stone-200 dark:border-stone-700">
            {types.map((k) => {
              const on = (kind ?? original?.type) === k;
              const icon = k.includes("bar") ? "bars" : k.includes("area") ? "area" : "line";
              return (
                <button
                  key={k}
                  type="button"
                  onClick={() => setKind(k === original?.type ? null : k)}
                  aria-pressed={on}
                  aria-label={t.chartTypes[icon]}
                  title={t.chartTypes[icon]}
                  className="flex h-6 w-7 items-center justify-center text-stone-500 hover:bg-stone-100 aria-pressed:bg-stone-900 aria-pressed:text-white dark:hover:bg-stone-800 dark:aria-pressed:bg-stone-100 dark:aria-pressed:text-stone-900"
                >
                  <Icon name={icon} className="size-3.5" />
                </button>
              );
            })}
          </div>
        )}
        {vega && (
          <button
            type="button"
            onClick={() => setShowData((v) => !v)}
            aria-expanded={showData}
            className="font-medium text-stone-600 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
          >
            {showData ? t.hideData : t.showData}
          </button>
        )}
        {file && (
          <a href={fileUrl(file)} download={file.filename} className="ml-auto font-medium text-accent hover:underline">
            {t.downloadPng}
          </a>
        )}
        {vega && !failed && (
          <button
            type="button"
            onClick={() => setFull(true)}
            aria-label={t.fullScreen}
            title={t.fullScreen}
            className={`${file ? "" : "ml-auto "}flex size-7 items-center justify-center rounded-md text-stone-500 hover:bg-stone-100 hover:text-stone-900 dark:hover:bg-stone-800 dark:hover:text-stone-100`}
          >
            <Icon name="expand" className="size-4" />
          </button>
        )}
      </figcaption>
      {full && vega && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={vega.title}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 sm:p-8"
          onClick={(e) => e.target === e.currentTarget && setFull(false)}
        >
          <div className="max-h-full w-full max-w-6xl overflow-auto rounded-2xl bg-[#fcfcfb] p-4 shadow-2xl dark:bg-[#1a1a19]">
            <div className="mb-2 flex justify-end">
              <button
                type="button"
                onClick={() => setFull(false)}
                aria-label={t.close}
                className="flex size-8 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800"
              >
                <Icon name="close" />
              </button>
            </div>
            <VegaChart chart={vega} onError={onError} />
            <DataTable table={vega.table} />
          </div>
        </div>
      )}

      {vega && showData && <DataTable table={vega.table} />}
    </figure>
  );
}
