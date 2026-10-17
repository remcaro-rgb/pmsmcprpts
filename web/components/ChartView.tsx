"use client";

import { useState, type CSSProperties } from "react";
import { nearestIndex } from "@/lib/chart";
import { fileUrl, type ChartLayout, type ChartPayload, type FileInfo } from "@/lib/chat";

function SeriesKey({ kind, light, dark }: { kind: ChartPayload["kind"]; light: string; dark: string }) {
  const style = { "--c-l": light, "--c-d": dark } as CSSProperties;
  return kind === "line" ? (
    <span style={style} className="inline-block h-0.5 w-3 shrink-0 rounded bg-[var(--c-l)] dark:bg-[var(--c-d)]" />
  ) : (
    <span style={style} className="inline-block size-2.5 shrink-0 rounded-sm bg-[var(--c-l)] dark:bg-[var(--c-d)]" />
  );
}

/** One layout of the chart with its hover/keyboard layer: crosshair (line) or band (bar), and
 * a tooltip listing every series at that x. */
function ChartCanvas({ chart, layout, className }: { chart: ChartPayload; layout: ChartLayout; className: string }) {
  const [index, setIndex] = useState<number | null>(null);
  const n = layout.x_positions.length;
  const pctX = (x: number) => `${(x / layout.width) * 100}%`;
  const pctY = (y: number) => `${(y / layout.height) * 100}%`;
  const band = chart.kind === "bar" ? (layout.plot.right - layout.plot.left) / n : 0;

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    setIndex(nearestIndex(chart.kind, layout, ((e.clientX - rect.left) / rect.width) * layout.width));
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "ArrowRight") setIndex((i) => (i === null ? 0 : Math.min(n - 1, i + 1)));
    else if (e.key === "ArrowLeft") setIndex((i) => (i === null ? n - 1 : Math.max(0, i - 1)));
    else if (e.key === "Escape") setIndex(null);
    else return;
    e.preventDefault();
  }

  const x = index === null ? 0 : layout.x_positions[index];
  const flip = x > layout.width * 0.62;
  const plotHeight = `${((layout.plot.bottom - layout.plot.top) / layout.height) * 100}%`;

  return (
    <div className={`relative ${className}`}>
      {/* Server-rendered SVG (labels XML-escaped by the MCP server); one variant per theme. */}
      <div className="dark:hidden [&_svg]:h-auto [&_svg]:w-full" dangerouslySetInnerHTML={{ __html: layout.svg_light }} />
      <div className="hidden dark:block [&_svg]:h-auto [&_svg]:w-full" dangerouslySetInnerHTML={{ __html: layout.svg_dark }} />
      <div
        className="absolute inset-0 cursor-crosshair outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        tabIndex={0}
        role="application"
        aria-label={`${chart.title}. Use the left and right arrow keys to read values.`}
        onPointerMove={onPointerMove}
        onPointerLeave={() => setIndex(null)}
        onBlur={() => setIndex(null)}
        onKeyDown={onKeyDown}
        data-testid="chart-hover"
      >
        {index !== null && (
          <>
            {chart.kind === "line" ? (
              <div
                className="pointer-events-none absolute w-px bg-stone-400/70"
                style={{ left: pctX(x), top: pctY(layout.plot.top), height: plotHeight }}
              />
            ) : (
              <div
                className="pointer-events-none absolute rounded bg-stone-500/10 dark:bg-white/10"
                style={{ left: pctX(x - band / 2), width: pctX(band), top: pctY(layout.plot.top), height: plotHeight }}
              />
            )}
            <div
              role="tooltip"
              className="pointer-events-none absolute z-10 min-w-36 rounded-lg border border-black/10 bg-white px-3 py-2 text-xs shadow-lg dark:border-white/10 dark:bg-stone-900"
              style={{
                top: pctY(layout.plot.top),
                ...(flip
                  ? { right: `calc(${100 - (x / layout.width) * 100}% + 12px)` }
                  : { left: `calc(${pctX(x)} + 12px)` }),
              }}
            >
              <p className="mb-1 font-medium text-stone-500 dark:text-stone-400">{chart.x_labels[index]}</p>
              {chart.series.map((s) => (
                <p key={s.name} className="flex items-center gap-2 py-0.5">
                  <SeriesKey kind={chart.kind} light={s.color_light} dark={s.color_dark} />
                  <span className="font-semibold tabular-nums text-stone-900 dark:text-stone-50">{s.values[index]}</span>
                  {chart.series.length > 1 && <span className="text-stone-500 dark:text-stone-400">{s.name}</span>}
                </p>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function ChartView({ chart, file }: { chart: ChartPayload; file: FileInfo | null }) {
  const [showData, setShowData] = useState(false);

  return (
    <figure
      className="overflow-hidden rounded-xl border border-black/10 bg-[#fcfcfb] dark:border-white/10 dark:bg-[#1a1a19]"
      data-testid="chart"
    >
      {chart.narrow ? (
        <>
          <ChartCanvas chart={chart} layout={chart} className="hidden sm:block" />
          <ChartCanvas chart={chart} layout={chart.narrow} className="sm:hidden" />
        </>
      ) : (
        <ChartCanvas chart={chart} layout={chart} className="" />
      )}

      <figcaption className="flex items-center gap-3 border-t border-black/5 px-4 py-2 text-xs dark:border-white/5">
        <button
          type="button"
          onClick={() => setShowData((v) => !v)}
          aria-expanded={showData}
          className="font-medium text-stone-600 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
        >
          {showData ? "Hide data" : "Show data"}
        </button>
        {file && (
          <a href={fileUrl(file)} download={file.filename} className="ml-auto font-medium text-accent hover:underline">
            Download PNG
          </a>
        )}
      </figcaption>

      {showData && (
        <div className="max-h-72 overflow-auto border-t border-black/5 dark:border-white/5">
          <table className="w-full text-[13px]">
            <thead className="sticky top-0 bg-stone-100 dark:bg-stone-900">
              <tr>
                <th className="px-3 py-1.5 text-left font-medium text-stone-600 dark:text-stone-300" />
                {chart.series.map((s) => (
                  <th key={s.name} className="px-3 py-1.5 text-right font-medium text-stone-600 dark:text-stone-300">
                    {chart.series.length > 1 ? s.name : chart.title}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {chart.x_labels.map((label, i) => (
                <tr key={i} className="border-t border-black/5 dark:border-white/5">
                  <td className="whitespace-nowrap px-3 py-1">{label}</td>
                  {chart.series.map((s) => (
                    <td key={s.name} className="whitespace-nowrap px-3 py-1 text-right">
                      {s.values[i]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </figure>
  );
}
