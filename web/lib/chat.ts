import { INTL_LOCALE, messages, type Locale, type Messages } from "./i18n";
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

export type FileInfo = { file_id: string; filename: string; mime: string; size: number };

/** Chart payload from make_chart: a Vega-Lite spec with its data, light and dark themes, number
 * and date locales, and the table behind "Show data". */
export type ChartPayload = {
  kind: "vega-lite";
  title: string;
  spec: Record<string, unknown>;
  config: { light: Record<string, unknown>; dark: Record<string, unknown> };
  locale: { number: Record<string, unknown>; time: Record<string, unknown> };
  table: { columns: string[]; rows: string[][]; numeric: boolean[] };
};

/** Charts saved before the Vega-Lite charts: a static SVG per theme. */
export type LegacyChart = { title: string; svg_light: string; svg_dark: string };

export function fileOf(result: unknown): FileInfo | null {
  const f = (result as { file?: FileInfo } | null)?.file;
  return f && typeof f.file_id === "string" ? f : null;
}

export function chartOf(result: unknown): ChartPayload | LegacyChart | null {
  const c = (result as { chart?: ChartPayload | LegacyChart } | null)?.chart;
  if (!c) return null;
  if ("kind" in c && c.kind === "vega-lite" && c.spec) return c;
  return "svg_light" in c && typeof c.svg_light === "string" ? c : null;
}

export const fileUrl = (f: FileInfo) => `/api/files/${f.file_id}`;

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
  turn?: number; // the turn's position in its saved conversation, for feedback
  feedback?: "up" | "down" | null;
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

const FENCE = "```suggestions";

/** Splits the follow-up questions the model ends an answer with (a ```suggestions block of
 * "- question" lines) from the answer's text. While streaming, a block (or the start of its
 * fence) that isn't finished yet is hidden too. */
export function splitSuggestions(text: string): { text: string; suggestions: string[] } {
  const at = text.lastIndexOf(FENCE);
  if (at < 0) {
    // A fence still arriving: "`", "``", "```sugg"...
    const tail = text.match(/\n?`{1,3}[a-z]*$/);
    if (tail && FENCE.startsWith(tail[0].trim())) return { text: text.slice(0, tail.index).trimEnd(), suggestions: [] };
    return { text, suggestions: [] };
  }
  const block = text.slice(at + FENCE.length).replace(/```[\s\S]*$/, "");
  const suggestions = block
    .split("\n")
    .map((l) => l.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").trim())
    .filter((l) => l.length > 2)
    .slice(0, 4);
  return { text: text.slice(0, at).trimEnd(), suggestions };
}

/** The answer's text without its follow-up questions, for copying. */
export function answerText(msg: AssistantMessage): string {
  return splitSuggestions(
    msg.parts.filter((p): p is { kind: "text"; text: string } => p.kind === "text").map((p) => p.text).join("\n\n"),
  ).text;
}

/** Turns a non-2xx response from /api/chat into a readable message. */
export function httpErrorMessage(status: number, body: string, t: Messages = messages("en")): string {
  try {
    const detail = JSON.parse(body).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  } catch {
    // not JSON
  }
  return t.requestFailed(status);
}

export type ConversationSummary = { id: string; title: string; updated: number; pinned?: boolean };

export type GroupKey = "pinned" | "today" | "yesterday" | "week" | "earlier";

/** Pinned conversations first, then the rest by when they were last updated (local days). */
export function groupConversations(
  list: ConversationSummary[],
  now = new Date(),
): { key: GroupKey; items: ConversationSummary[] }[] {
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  const groups: Record<GroupKey, ConversationSummary[]> = { pinned: [], today: [], yesterday: [], week: [], earlier: [] };
  for (const c of list) {
    const key: GroupKey = c.pinned
      ? "pinned"
      : c.updated >= startOfDay
        ? "today"
        : c.updated >= startOfDay - 86400
          ? "yesterday"
          : c.updated >= startOfDay - 6 * 86400
            ? "week"
            : "earlier";
    groups[key].push(c);
  }
  return (Object.keys(groups) as GroupKey[]).filter((k) => groups[k].length).map((key) => ({ key, items: groups[key] }));
}

/** A saved conversation: each turn's question and the events its answer streamed. */
export type SavedConversation = ConversationSummary & {
  turns: { user: string; events: SseEvent[]; feedback?: "up" | "down" | null }[];
};

/** Rebuilds the messages of a saved conversation by replaying each answer's events. */
export function messagesFromSaved(saved: SavedConversation): Message[] {
  return saved.turns.flatMap((turn, i): Message[] => {
    const start: AssistantMessage = {
      role: "assistant", id: `${saved.id}-${i}-a`, parts: [], status: "streaming", turn: i, feedback: turn.feedback ?? null,
    };
    const answer = turn.events.reduce(applyEvent, start);
    return [
      { role: "user", id: `${saved.id}-${i}-u`, text: turn.user },
      answer.status === "streaming" ? { ...answer, status: "done" } : answer,
    ];
  });
}

/** "14:05" today, "Mon" this week, else "12 Oct" (in the given language). */
export function shortDate(seconds: number, now = new Date(), locale: Locale = "en"): string {
  const d = new Date(seconds * 1000);
  const tag = locale === "en" ? "en-GB" : INTL_LOCALE[locale];
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString(tag, { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  if (now.getTime() - d.getTime() < 6 * 86400_000) return d.toLocaleDateString(tag, { weekday: "short" });
  return d.toLocaleDateString(tag, { day: "numeric", month: "short" });
}
