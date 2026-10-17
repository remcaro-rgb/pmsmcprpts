import type { TableResult } from "@/lib/chat";

const NUMERIC_TYPES = new Set(["int2", "int4", "int8", "numeric", "float4", "float8"]);
const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return numberFormat.format(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function DataTable({ table }: { table: TableResult }) {
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
                    {formatCell(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1.5 text-xs text-stone-500">
        {table.rows.length < table.row_count
          ? `Showing ${table.rows.length} of ${numberFormat.format(table.row_count)} rows`
          : `${numberFormat.format(table.row_count)} ${table.row_count === 1 ? "row" : "rows"}`}
        {table.truncated ? " (result capped at 50,000 rows)" : ""}
        {" · "}
        <span className="font-mono">{table.dataset_id}</span>
      </p>
    </div>
  );
}
