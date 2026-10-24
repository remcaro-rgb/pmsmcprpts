"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { answerText, chartOf, fileOf, splitSuggestions, type AssistantMessage, type ToolPart, type Usage } from "@/lib/chat";
import type { Messages } from "@/lib/i18n";
import ArtifactCard from "./ArtifactCard";
import ChartView from "./ChartView";
import { useI18n } from "./I18n";
import { Icon } from "./Icons";
import Chevron from "./Chevron";
import ToolCard from "./ToolCard";

function formatUsage(u: Usage, t: Messages): string {
  const cached = u.cache_read_input_tokens ?? 0;
  const input = u.input_tokens + cached + (u.cache_creation_input_tokens ?? 0);
  const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
  const pct = input ? Math.round((cached / input) * 100) : 0;
  return t.usage(k(input), pct, k(u.output_tokens));
}

/** While the answer is being worked out: what it's doing, in plain words, and for how long. */
function Progress({ tools }: { tools: ToolPart[] }) {
  const { t } = useI18n();
  const started = useRef(0);
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    started.current = Date.now();
    const timer = setInterval(() => setSeconds(Math.round((Date.now() - started.current) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);
  const words = (name: string) => t.progress[name] ?? t.progressStep;
  const running = tools.find((p) => p.status === "running");
  const headline = running ? words(running.name)[0] : tools.length ? t.progressWriting : t.progressThinking;
  return (
    <div className="rounded-2xl border border-stone-200 bg-white px-4 py-3 dark:border-stone-800 dark:bg-stone-900" role="status" data-testid="progress">
      <div className="flex items-center gap-2.5">
        <span className="size-4 animate-spin rounded-full border-2 border-blue-200 border-t-accent" aria-hidden="true" />
        <span className="font-medium">{headline}</span>
        {seconds > 2 && <span className="ml-auto text-xs tabular-nums text-stone-500">{t.seconds(seconds)}</span>}
      </div>
      {tools.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm text-stone-600 dark:text-stone-400">
          {tools.map((p) => (
            <li key={p.id} className="flex items-center gap-2">
              {p.status === "running" ? (
                <span className="size-3.5 animate-spin rounded-full border-2 border-blue-200 border-t-accent" aria-hidden="true" />
              ) : p.status === "error" ? (
                <span className="w-3.5 text-center text-red-600" aria-hidden="true">✕</span>
              ) : (
                <Icon name="check" className="size-3.5 text-green-600" />
              )}
              {p.status === "running" ? words(p.name)[0] : words(p.name)[1]}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Actions({
  message,
  onAsk,
  onFeedback,
  onSave,
}: {
  message: AssistantMessage;
  onAsk: (q: string) => void;
  onFeedback?: (value: "up" | "down" | null) => void;
  onSave?: () => void;
}) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const button =
    "inline-flex items-center gap-1.5 rounded-lg border border-stone-200 px-2.5 py-1 text-[13px] text-stone-600 hover:bg-stone-50 aria-pressed:border-blue-200 aria-pressed:bg-blue-50 aria-pressed:text-blue-700 dark:border-stone-700 dark:text-stone-300 dark:hover:bg-stone-800 dark:aria-pressed:border-blue-900 dark:aria-pressed:bg-blue-950 dark:aria-pressed:text-blue-300";
  async function copy() {
    try {
      await navigator.clipboard.writeText(answerText(message));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  }
  const vote = (v: "up" | "down") => onFeedback?.(message.feedback === v ? null : v);
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="answer-actions">
      <button onClick={copy} className={button}>
        <Icon name={copied ? "check" : "copy"} className="size-3.5" />
        {copied ? t.copied : t.copy}
      </button>
      <button onClick={() => onAsk(t.askExcel)} className={button}>
        <Icon name="sheet" className="size-3.5" />
        {t.toExcel}
      </button>
      <button onClick={() => onAsk(t.askPdf)} className={button}>
        <Icon name="doc" className="size-3.5" />
        {t.toPdf}
      </button>
      {onSave && (
        <button onClick={onSave} className={button}>
          <Icon name="save" className="size-3.5" />
          {t.saveReport}
        </button>
      )}
      {onFeedback && (
        <>
          <span className="flex-1" />
          <button onClick={() => vote("up")} aria-pressed={message.feedback === "up"} aria-label={t.useful} title={t.useful} className={button}>
            <Icon name="up" className="size-3.5" />
          </button>
          <button onClick={() => vote("down")} aria-pressed={message.feedback === "down"} aria-label={t.notUseful} title={t.notUseful} className={button}>
            <Icon name="down" className="size-3.5" />
          </button>
        </>
      )}
    </div>
  );
}

export default function AssistantMessageView({
  message,
  isLast = false,
  onAsk = () => {},
  onFeedback,
  onSave,
}: {
  message: AssistantMessage;
  isLast?: boolean;
  onAsk?: (q: string) => void;
  onFeedback?: (value: "up" | "down" | null) => void;
  onSave?: () => void; // saves the question behind this answer as a report
}) {
  const { t } = useI18n();
  const streaming = message.status === "streaming";
  const last = message.parts[message.parts.length - 1];
  const tools = message.parts.filter((p): p is ToolPart => p.kind === "tool");
  const hasSteps = message.parts.some((p) => p.kind !== "text");
  let suggestions: string[] = [];

  // The answer itself: its text, charts and files, in order. The steps behind it (reasoning and
  // tool calls) are folded away below.
  const content = message.parts.map((part, i) => {
    if (part.kind === "thinking") return null;
    if (part.kind === "tool") {
      const chart = part.status === "done" ? chartOf(part.result) : null;
      const file = part.status === "done" ? fileOf(part.result) : null;
      if (chart) return <ChartView key={part.id} chart={chart} file={file} />;
      return file ? <ArtifactCard key={part.id} file={file} /> : null;
    }
    const split = splitSuggestions(part.text);
    if (split.suggestions.length) suggestions = split.suggestions;
    return split.text ? (
      <div key={i} className="markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{split.text}</ReactMarkdown>
      </div>
    ) : null;
  });

  return (
    <div className="space-y-3" data-testid="assistant-message">
      {content}
      {streaming && (!last || last.kind !== "text") && <Progress tools={tools} />}
      {message.status === "stopped" && <p className="text-sm text-stone-500">{t.stopped}</p>}
      {(message.status === "error" || message.status === "refused") && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
        >
          {message.error ?? t.somethingWrong} {t.notAdded}
        </div>
      )}
      {!streaming && (hasSteps || message.usage) && (
        <details className="group text-sm" data-testid="how">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[13px] text-stone-500 select-none hover:text-stone-700 dark:hover:text-stone-300">
            <Chevron /> {t.howWorked(tools.length)}
          </summary>
          <div className="mt-2 space-y-2 border-l-2 border-stone-200 pl-3 dark:border-stone-800">
            {message.parts.map((part, i) =>
              part.kind === "thinking" ? (
                <p key={i} className="whitespace-pre-wrap text-[13px] text-stone-500">{part.text}</p>
              ) : part.kind === "tool" ? (
                <ToolCard key={part.id} part={part} />
              ) : null,
            )}
            {message.usage && <p className="text-xs text-stone-400">{formatUsage(message.usage, t)}</p>}
          </div>
        </details>
      )}
      {message.status === "done" && <Actions message={message} onAsk={onAsk} onFeedback={onFeedback} onSave={onSave} />}
      {message.status === "done" && isLast && suggestions.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-semibold text-stone-500">{t.keepExploring}</p>
          <div className="flex flex-wrap gap-2" data-testid="suggestions">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => onAsk(s)}
                className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-left text-sm font-medium text-blue-800 hover:bg-blue-100 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200 dark:hover:bg-blue-900"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
