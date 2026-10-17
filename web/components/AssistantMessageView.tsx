import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { AssistantMessage, Usage } from "@/lib/chat";
import Chevron from "./Chevron";
import ToolCard from "./ToolCard";

function formatUsage(u: Usage): string {
  const cached = u.cache_read_input_tokens ?? 0;
  const input = u.input_tokens + cached + (u.cache_creation_input_tokens ?? 0);
  const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
  const pct = input ? Math.round((cached / input) * 100) : 0;
  return `${k(input)} tokens in (${pct}% cached) · ${k(u.output_tokens)} out`;
}

function Working() {
  return (
    <div className="flex items-center gap-2 text-sm text-stone-500" role="status">
      <span className="flex gap-1">
        <span className="size-1.5 animate-bounce rounded-full bg-stone-400 [animation-delay:-0.3s]" />
        <span className="size-1.5 animate-bounce rounded-full bg-stone-400 [animation-delay:-0.15s]" />
        <span className="size-1.5 animate-bounce rounded-full bg-stone-400" />
      </span>
      Working…
    </div>
  );
}

export default function AssistantMessageView({ message }: { message: AssistantMessage }) {
  const last = message.parts[message.parts.length - 1];
  const showWorking = message.status === "streaming" && (!last || last.kind !== "text");
  return (
    <div className="space-y-3" data-testid="assistant-message">
      {message.parts.map((part, i) => {
        if (part.kind === "thinking") {
          return (
            <details key={i} className="group text-[13px] text-stone-500">
              <summary className="flex cursor-pointer list-none items-center gap-1 select-none">
                <Chevron /> Thinking
              </summary>
              <p className="mt-1 whitespace-pre-wrap border-l-2 border-stone-200 pl-3 dark:border-stone-800">
                {part.text}
              </p>
            </details>
          );
        }
        if (part.kind === "tool") return <ToolCard key={part.id} part={part} />;
        return (
          <div key={i} className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.text}</ReactMarkdown>
          </div>
        );
      })}
      {showWorking && <Working />}
      {message.status === "stopped" && <p className="text-sm text-stone-500">Stopped.</p>}
      {(message.status === "error" || message.status === "refused") && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
        >
          {message.error ?? "Something went wrong."} This message was not added to the conversation.
        </div>
      )}
      {message.status === "done" && message.usage && (
        <p className="text-xs text-stone-400">{formatUsage(message.usage)}</p>
      )}
    </div>
  );
}
