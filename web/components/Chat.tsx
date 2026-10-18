"use client";

import { useEffect, useRef, useState } from "react";
import {
  applyEvent,
  httpErrorMessage,
  messagesFromSaved,
  type AssistantMessage,
  type ConversationSummary,
  type Message,
  type SavedConversation,
} from "@/lib/chat";
import { isLocale } from "@/lib/i18n";
import { readSse } from "@/lib/sse";
import AssistantMessageView from "./AssistantMessageView";
import { useI18n } from "./I18n";
import Sidebar from "./Sidebar";

export default function Chat({ user = null }: { user?: string | null }) {
  const { locale, t, setLocale } = useI18n();
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  async function refreshConversations() {
    try {
      const res = await fetch("/api/conversations", { cache: "no-store" });
      if (res.ok) setConversations((await res.json()).conversations);
      else setConversations((c) => c ?? []);
    } catch {
      setConversations((c) => c ?? []);
    }
  }

  // The open conversation is kept in the address (?c=…) so reloading or sharing the tab keeps it.
  function showInAddressBar(id: string | null) {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("c", id);
    else url.searchParams.delete("c");
    window.history.replaceState(null, "", url);
  }

  async function openConversation(id: string) {
    setSidebarOpen(false);
    if (busy || id === conversationId) return;
    try {
      const res = await fetch(`/api/conversations/${id}`, { cache: "no-store" });
      if (!res.ok) {
        if (res.status === 404) showInAddressBar(null);
        return;
      }
      const saved: SavedConversation = await res.json();
      stickToBottom.current = true;
      setMessages(messagesFromSaved(saved));
      setConversationId(saved.id);
      showInAddressBar(saved.id);
    } catch {
      // keep the current view
    }
  }

  async function deleteConversation(c: ConversationSummary) {
    if (!window.confirm(t.confirmDelete(c.title))) return;
    const res = await fetch(`/api/conversations/${c.id}`, { method: "DELETE" }).catch(() => null);
    if (res?.ok || res?.status === 404) {
      setConversations((list) => list?.filter((x) => x.id !== c.id) ?? null);
      if (c.id === conversationId) newChat();
    }
  }

  useEffect(() => {
    refreshConversations();
    const id = new URL(window.location.href).searchParams.get("c");
    if (id) openConversation(id);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  async function send(text: string) {
    text = text.trim();
    if (!text || busy) return;
    const assistantId = crypto.randomUUID();
    setMessages((m) => [
      ...m,
      { role: "user", id: crypto.randomUUID(), text },
      { role: "assistant", id: assistantId, parts: [], status: "streaming" },
    ]);
    setInput("");
    setBusy(true);
    stickToBottom.current = true;
    const update = (fn: (m: AssistantMessage) => AssistantMessage) =>
      setMessages((ms) => ms.map((m) => (m.id === assistantId ? fn(m as AssistantMessage) : m)));

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: text, conversation_id: conversationId, language: locale }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        const body = await res.text();
        update((m) => ({ ...m, status: "error", error: httpErrorMessage(res.status, body, t) }));
        return;
      }
      for await (const ev of readSse(res.body)) {
        if (ev.event === "conversation") {
          const id = (ev.data as { id: string }).id;
          setConversationId(id);
          showInAddressBar(id);
        }
        else update((m) => applyEvent(m, ev));
      }
      update((m) =>
        m.status === "streaming"
          ? { ...m, status: "error", error: t.connectionClosed }
          : m,
      );
    } catch {
      if (controller.signal.aborted) update((m) => ({ ...m, status: "stopped" }));
      else update((m) => ({ ...m, status: "error", error: t.assistantUnreachable }));
    } finally {
      abortRef.current = null;
      setBusy(false);
      refreshConversations();
    }
  }

  function newChat() {
    setMessages([]);
    setConversationId(null);
    setSidebarOpen(false);
    showInAddressBar(null);
  }

  return (
    <div className="flex h-dvh">
      <Sidebar
        conversations={conversations}
        activeId={conversationId}
        disabled={busy}
        open={sidebarOpen}
        onSelect={openConversation}
        onDelete={deleteConversation}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-stone-200 bg-white/80 px-4 py-3 backdrop-blur dark:border-stone-800 dark:bg-stone-950/80">
          <button
            onClick={() => setSidebarOpen(true)}
            aria-label={t.showConversations}
            className="-ml-1 flex size-8 shrink-0 items-center justify-center rounded-lg text-stone-600 hover:bg-stone-100 md:hidden dark:text-stone-300 dark:hover:bg-stone-900"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true" className="size-4">
              <path d="M2.5 4h11M2.5 8h11M2.5 12h11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent text-sm font-bold text-white">P</div>
          <div className="min-w-0">
            <h1 className="text-[15px] font-semibold leading-tight">{t.appName}</h1>
            <p className="truncate text-xs text-stone-500">{t.tagline}</p>
          </div>
          <select
            value={locale}
            onChange={(e) => isLocale(e.target.value) && setLocale(e.target.value)}
            aria-label={t.language}
            title={t.language}
            className="ml-auto shrink-0 cursor-pointer rounded-lg border border-stone-200 bg-transparent px-1.5 py-1.5 text-sm hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-900"
          >
            <option value="en">EN</option>
            <option value="es">ES</option>
          </select>
          <button
            onClick={newChat}
            disabled={busy || messages.length === 0}
            className="shrink-0 whitespace-nowrap rounded-lg border border-stone-200 px-3 py-1.5 text-sm hover:bg-stone-100 disabled:opacity-40 dark:border-stone-700 dark:hover:bg-stone-900"
          >
            {t.newChat}
          </button>
          {user && (
            <form action="/auth/logout" method="post" className="flex shrink-0 items-center gap-2">
              <span className="hidden max-w-48 truncate text-xs text-stone-500 sm:inline" title={user}>{user}</span>
              <button className="whitespace-nowrap rounded-lg px-2 py-1.5 text-sm text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-900">
                {t.signOut}
              </button>
            </form>
          )}
        </header>

        <div
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
          className="flex-1 overflow-y-auto"
        >
          <div className="mx-auto max-w-3xl px-4 py-6">
            {messages.length === 0 ? (
              <div className="pt-[12vh]">
                <h2 className="text-2xl font-semibold tracking-tight">{t.emptyTitle}</h2>
                <p className="mt-2 text-stone-500">
                  {t.emptyBody}
                </p>
                <div className="mt-6 grid gap-2 sm:grid-cols-2">
                  {t.starters.map((s) => (
                    <button
                      key={s}
                      onClick={() => send(s)}
                      className="rounded-xl border border-stone-200 bg-white p-3 text-left text-sm hover:border-stone-300 hover:bg-stone-50 dark:border-stone-800 dark:bg-stone-900 dark:hover:bg-stone-800"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-6">
                {messages.map((m) =>
                  m.role === "user" ? (
                    <div key={m.id} className="flex justify-end">
                      <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-stone-200/80 px-4 py-2 text-[15px] dark:bg-stone-800">
                        {m.text}
                      </p>
                    </div>
                  ) : (
                    <AssistantMessageView key={m.id} message={m} />
                  ),
                )}
              </div>
            )}
          </div>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="border-t border-stone-200 bg-white px-4 py-3 dark:border-stone-800 dark:bg-stone-950"
        >
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={1}
              placeholder={t.placeholder}
              aria-label={t.message}
              className="field-sizing-content max-h-40 min-h-11 flex-1 resize-none rounded-xl border border-stone-300 bg-white px-3.5 py-2.5 text-[15px] outline-none focus:border-accent dark:border-stone-700 dark:bg-stone-900"
            />
            {busy ? (
              <button
                type="button"
                onClick={() => abortRef.current?.abort()}
                className="h-11 rounded-xl border border-stone-300 px-4 text-sm font-medium hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-900"
              >
                {t.stop}
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                className="h-11 rounded-xl bg-accent px-4 text-sm font-medium text-white disabled:opacity-40"
              >
                {t.send}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
