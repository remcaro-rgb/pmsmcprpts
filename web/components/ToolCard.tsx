"use client";

import { chartOf, fileOf, isTableResult, type ToolPart } from "@/lib/chat";
import { formatNumber, type Locale, type Messages } from "@/lib/i18n";
import Chevron from "./Chevron";
import DataTable from "./DataTable";
import { useI18n } from "./I18n";

function Status({ status }: { status: ToolPart["status"] }) {
  const { t } = useI18n();
  if (status === "running") {
    return <span className="size-3.5 animate-spin rounded-full border-2 border-stone-300 border-t-accent" aria-label={t.running} />;
  }
  if (status === "error") return <span className="text-red-600" aria-label={t.failed}>✕</span>;
  return <span className="text-emerald-600" aria-label={t.done}>✓</span>;
}

function summary(part: ToolPart, t: Messages, locale: Locale): string | null {
  const file = fileOf(part.result);
  if (file && !chartOf(part.result)) return file.filename;
  if (isTableResult(part.result)) {
    const n = part.result.row_count;
    return t.rows(formatNumber(n, locale), n === 1);
  }
  if (part.status === "error") return t.failed;
  return null;
}

function Input({ part }: { part: ToolPart }) {
  const input = part.input;
  if (!input) return null;
  if (typeof input.query === "string") {
    return (
      <pre className="overflow-x-auto rounded-md bg-stone-900 p-3 font-mono text-[12.5px] leading-5 text-stone-100">
        {input.query.trim()}
      </pre>
    );
  }
  const entries = Object.entries(input);
  if (!entries.length) return null;
  const simple = entries.filter(([, v]) => typeof v !== "object" || v === null || JSON.stringify(v).length <= 80);
  const nested = entries.filter((e) => !simple.includes(e));
  return (
    <>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[13px]">
        {simple.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-stone-500">{k}</dt>
            <dd className="break-all font-mono">{typeof v === "string" ? v : JSON.stringify(v)}</dd>
          </div>
        ))}
      </dl>
      {nested.map(([k, v]) => (
        <div key={k}>
          <p className="mb-1 text-[13px] text-stone-500">{k}</p>
          <pre className="max-h-60 overflow-auto rounded-md bg-stone-100 p-3 font-mono text-[12px] dark:bg-stone-900">
            {JSON.stringify(v, null, 2)}
          </pre>
        </div>
      ))}
    </>
  );
}

function Result({ part }: { part: ToolPart }) {
  const { t } = useI18n();
  const result = part.result;
  if (part.status === "running" || result === undefined) return null;
  if (part.status === "error") {
    return (
      <pre className="whitespace-pre-wrap rounded-md bg-red-50 p-3 font-mono text-[12.5px] text-red-800 dark:bg-red-950/40 dark:text-red-300">
        {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
      </pre>
    );
  }
  if (isTableResult(result)) return <DataTable table={result} />;
  if (fileOf(result)) return null; // shown as a chart or download card below the step
  const r = result as { relations?: unknown[]; business_date?: string };
  if (Array.isArray(r?.relations)) {
    return (
      <p className="text-[13px] text-stone-600 dark:text-stone-400">
        {t.schemaSummary(r.relations.length, String(r.business_date))}
      </p>
    );
  }
  return (
    <pre className="max-h-60 overflow-auto rounded-md bg-stone-100 p-3 font-mono text-[12px] dark:bg-stone-900">
      {JSON.stringify(result, null, 2)}
    </pre>
  );
}

export default function ToolCard({ part }: { part: ToolPart }) {
  const { locale, t } = useI18n();
  const extra = summary(part, t, locale);
  return (
    <details className="group rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900/60">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[13px] text-stone-700 select-none dark:text-stone-300">
        <Status status={part.status} />
        <span className="font-medium">{t.tools[part.name] ?? part.name}</span>
        {extra && <span className="text-stone-500">· {extra}</span>}
        <Chevron className="ml-auto text-stone-400" />
      </summary>
      <div className="space-y-3 border-t border-stone-200 p-3 dark:border-stone-800">
        <Input part={part} />
        <Result part={part} />
      </div>
    </details>
  );
}
