import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chartOf, fileOf, type AssistantMessage, type Usage } from "@/lib/chat";
import type { Messages } from "@/lib/i18n";
import ArtifactCard from "./ArtifactCard";
import ChartView from "./ChartView";
import { useI18n } from "./I18n";
import Chevron from "./Chevron";
import ToolCard from "./ToolCard";

function formatUsage(u: Usage, t: Messages): string {
  const cached = u.cache_read_input_tokens ?? 0;
  const input = u.input_tokens + cached + (u.cache_creation_input_tokens ?? 0);
  const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
  const pct = input ? Math.round((cached / input) * 100) : 0;
  return t.usage(k(input), pct, k(u.output_tokens));
}

function Working() {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-2 text-sm text-stone-500" role="status">
      <span className="flex gap-1">
        <span className="size-1.5 animate-bounce rounded-full bg-stone-400 [animation-delay:-0.3s]" />
        <span className="size-1.5 animate-bounce rounded-full bg-stone-400 [animation-delay:-0.15s]" />
        <span className="size-1.5 animate-bounce rounded-full bg-stone-400" />
      </span>
      {t.working}
    </div>
  );
}

export default function AssistantMessageView({ message }: { message: AssistantMessage }) {
  const { t } = useI18n();
  const last = message.parts[message.parts.length - 1];
  const showWorking = message.status === "streaming" && (!last || last.kind !== "text");
  return (
    <div className="space-y-3" data-testid="assistant-message">
      {message.parts.map((part, i) => {
        if (part.kind === "thinking") {
          return (
            <details key={i} className="group text-[13px] text-stone-500">
              <summary className="flex cursor-pointer list-none items-center gap-1 select-none">
                <Chevron /> {t.thinking}
              </summary>
              <p className="mt-1 whitespace-pre-wrap border-l-2 border-stone-200 pl-3 dark:border-stone-800">
                {part.text}
              </p>
            </details>
          );
        }
        if (part.kind === "tool") {
          const chart = part.status === "done" ? chartOf(part.result) : null;
          const file = part.status === "done" ? fileOf(part.result) : null;
          return (
            <div key={part.id} className="space-y-3">
              <ToolCard part={part} />
              {chart ? <ChartView chart={chart} file={file} /> : file && <ArtifactCard file={file} />}
            </div>
          );
        }
        return (
          <div key={i} className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.text}</ReactMarkdown>
          </div>
        );
      })}
      {showWorking && <Working />}
      {message.status === "stopped" && <p className="text-sm text-stone-500">{t.stopped}</p>}
      {(message.status === "error" || message.status === "refused") && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
        >
          {message.error ?? t.somethingWrong} {t.notAdded}
        </div>
      )}
      {message.status === "done" && message.usage && (
        <p className="text-xs text-stone-400">{formatUsage(message.usage, t)}</p>
      )}
    </div>
  );
}
