import type { SseEvent } from "./sse";

export type Column = { name: string; type: string };

/** Result shape of the table-producing MCP tools (run_sql, get_kpis, get_dataset). */
export type TableResult = {
  dataset_id: string;
  columns: Column[];
  rows: unknown[][];
  row_count: number;
  truncated?: boolean;
};

export type ToolPart = {
  kind: "tool";
  id: string;
  name: string;
  input?: Record<string, unknown>;
  status: "running" | "done" | "error";
  result?: unknown;
};

export type Part = { kind: "thinking"; text: string } | { kind: "text"; text: string } | ToolPart;

export type Usage = {
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens?: number | null;
  cache_creation_input_tokens?: number | null;
};

export type AssistantMessage = {
  role: "assistant";
  id: string;
  parts: Part[];
  status: "streaming" | "done" | "error" | "refused" | "stopped";
  error?: string;
  usage?: Usage;
};

export type UserMessage = { role: "user"; id: string; text: string };

export type Message = UserMessage | AssistantMessage;

export function isTableResult(value: unknown): value is TableResult {
  const v = value as TableResult | null;
  return !!v && typeof v === "object" && Array.isArray(v.columns) && Array.isArray(v.rows);
}

function appendText(parts: Part[], kind: "text" | "thinking", text: string): Part[] {
  const last = parts[parts.length - 1];
  if (last && last.kind === kind) {
    return [...parts.slice(0, -1), { kind, text: last.text + text }];
  }
  return [...parts, { kind, text }];
}

function updateTool(parts: Part[], id: string, name: string, patch: Partial<ToolPart>): Part[] {
  const index = parts.findIndex((p) => p.kind === "tool" && p.id === id);
  if (index < 0) return [...parts, { kind: "tool", id, name, status: "running", ...patch }];
  return parts.map((p, i) => (i === index ? { ...(p as ToolPart), ...patch } : p));
}

/** Folds one agent stream event into the assistant message being streamed. */
export function applyEvent(msg: AssistantMessage, ev: SseEvent): AssistantMessage {
  const d = (ev.data ?? {}) as Record<string, any>;
  switch (ev.event) {
    case "text":
      return { ...msg, parts: appendText(msg.parts, "text", d.text) };
    case "thinking":
      return { ...msg, parts: appendText(msg.parts, "thinking", d.text) };
    case "tool_start":
      return { ...msg, parts: updateTool(msg.parts, d.id, d.name, {}) };
    case "tool_call":
      return { ...msg, parts: updateTool(msg.parts, d.id, d.name, { input: d.input }) };
    case "tool_result":
      return {
        ...msg,
        parts: updateTool(msg.parts, d.id, d.name, { status: d.is_error ? "error" : "done", result: d.result }),
      };
    case "done":
      return { ...msg, status: "done", usage: d.usage };
    case "refusal":
      return { ...msg, status: "refused", error: d.message };
    case "error":
      return { ...msg, status: "error", error: d.message };
    default:
      return msg;
  }
}

/** Turns a non-2xx response from /api/chat into a readable message. */
export function httpErrorMessage(status: number, body: string): string {
  try {
    const detail = JSON.parse(body).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  } catch {
    // not JSON
  }
  return `Request failed (${status}).`;
}
