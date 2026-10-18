"use client";

import type { TableResult } from "@/lib/chat";
import { formatNumber, type Locale, type Messages } from "@/lib/i18n";
import { useI18n } from "./I18n";

const NUMERIC_TYPES = new Set(["int2", "int4", "int8", "numeric", "float4", "float8"]);

function formatCell(value: unknown, t: Messages, locale: Locale): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return formatNumber(value, locale, 4);
  if (typeof value === "boolean") return value ? t.yes : t.no;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function DataTable({ table }: { table: TableResult }) {
  const { locale, t } = useI18n();
  const count = (n: number) => formatNumber(n, locale);
  const numeric = table.columns.map((c) => NUMERIC_TYPES.has(c.type));
  return (
    <div>
      <div className="max-h-80 overflow-auto rounded-md border border-stone-200 dark:border-stone-800">
        <table className="w-full border-collapse text-[13px]">
          <thead className="sticky top-0 bg-stone-100 dark:bg-stone-900">
            <tr>
              {table.columns.map((c, i) => (
                <th
                  key={c.name + i}
                  className={`whitespace-nowrap px-2.5 py-1.5 font-medium text-stone-600 dark:text-stone-300 ${numeric[i] ? "text-right" : "text-left"}`}
                >
                  {c.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {table.rows.map((row, r) => (
              <tr key={r} className="border-t border-stone-100 dark:border-stone-800/70">
                {row.map((cell, i) => (
                  <td key={i} className={`whitespace-nowrap px-2.5 py-1 ${numeric[i] ? "text-right" : "text-left"}`}>
                    {formatCell(cell, t, locale)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1.5 text-xs text-stone-500">
        {table.rows.length < table.row_count
          ? t.showingRows(count(table.rows.length), count(table.row_count))
          : t.rows(count(table.row_count), table.row_count === 1)}
        {table.truncated ? t.rowsCapped : ""}
        {" · "}
        <span className="font-mono">{table.dataset_id}</span>
      </p>
    </div>
  );
}
