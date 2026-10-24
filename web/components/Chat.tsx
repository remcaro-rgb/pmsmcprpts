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
import type { HotelOverview } from "@/lib/home";
import { INTL_LOCALE } from "@/lib/i18n";
import { readSse } from "@/lib/sse";
import type { Theme } from "@/lib/theme";
import AssistantMessageView from "./AssistantMessageView";
import Home from "./Home";
import { Icon } from "./Icons";
import { useI18n } from "./I18n";
import Sidebar from "./Sidebar";
import UserMenu from "./UserMenu";

const HOTEL_KEY = "pms_hotel";

type Recognition = { lang: string; interimResults: boolean; start: () => void; stop: () => void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onend: (() => void) | null };
type RecognitionCtor = new () => Recognition;

function speechRecognition(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export default function Chat({
  user = null,
  name = null,
  isAdmin = false,
  theme = "light",
}: {
  user?: string | null;
  name?: string | null; // the account's name, for the greeting
  isAdmin?: boolean;
  theme?: Theme;
}) {
  const { locale, t } = useI18n();
  const [overview, setOverview] = useState<HotelOverview[] | null>(null);
  const [overviewFailed, setOverviewFailed] = useState(false);
  const [hotel, setHotel] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const [canDictate, setCanDictate] = useState(false);
  const recognitionRef = useRef<Recognition | null>(null);
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

  async function loadOverview() {
    setOverviewFailed(false);
    try {
      const res = await fetch("/api/overview", { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const hotels: HotelOverview[] = (await res.json()).hotels ?? [];
      let saved: string | null = null;
      try {
        saved = localStorage.getItem(HOTEL_KEY);
      } catch {}
      setOverview(hotels);
      setHotel(hotels.find((h) => h.hotel_code === saved)?.hotel_code ?? hotels[0]?.hotel_code ?? null);
    } catch {
      setOverviewFailed(true);
    }
  }

  function pickHotel(code: string) {
    setHotel(code);
    try {
      localStorage.setItem(HOTEL_KEY, code);
    } catch {}
  }

  function dictate() {
    const Ctor = speechRecognition();
    if (!Ctor) return;
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    const rec = new Ctor();
    rec.lang = INTL_LOCALE[locale];
    rec.interimResults = false;
    rec.onresult = (e) => {
      const said = Array.from(e.results).map((r) => r[0].transcript).join(" ").trim();
      if (said) setInput((v) => (v.trim() ? `${v.trim()} ${said}` : said));
    };
    rec.onend = () => setListening(false);
    recognitionRef.current = rec;
    setListening(true);
    rec.start();
  }

  useEffect(() => {
    setCanDictate(!!speechRecognition());
    loadOverview();
    refreshConversations();
    const id = new URL(window.location.href).searchParams.get("c");
    if (id) openConversation(id);
  }, []);

  async function changeConversation(c: ConversationSummary, change: { title?: string; pinned?: boolean }) {
    const res = await fetch(`/api/conversations/${c.id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(change),
    }).catch(() => null);
    if (res?.ok) refreshConversations();
  }

  function renameConversation(c: ConversationSummary) {
    const title = window.prompt(t.renamePrompt, c.title)?.trim();
    if (title && title !== c.title) changeConversation(c, { title });
  }

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  async function send(text: string) {
    text = text.trim();
    if (!text || busy) return;
    const assistantId = crypto.randomUUID();
    // Saved turns are numbered from 0; failed turns aren't saved.
    const turn = messages.filter((m) => m.role === "assistant" && m.status === "done").length;
    setMessages((m) => [
      ...m,
      { role: "user", id: crypto.randomUUID(), text },
      { role: "assistant", id: assistantId, parts: [], status: "streaming", turn, feedback: null },
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
        body: JSON.stringify({ message: text, conversation_id: conversationId, language: locale, hotel }),
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

  function answerFeedback(message: AssistantMessage, value: "up" | "down" | null) {
    if (!conversationId || message.turn == null) return;
    setMessages((ms) => ms.map((m) => (m.id === message.id ? { ...(m as AssistantMessage), feedback: value } : m)));
    fetch("/api/feedback", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ kind: "answer", ref: `${conversationId}:${message.turn}`, value }),
    }).catch(() => {});
  }

  function newChat() {
    setMessages([]);
    setConversationId(null);
    setSidebarOpen(false);
    showInAddressBar(null);
  }

  const current = overview?.find((h) => h.hotel_code === hotel) ?? null;
  const placeholder = current ? t.placeholderHotel(current.name) : t.placeholder;

  return (
    <div className="flex h-dvh">
      <Sidebar
        conversations={conversations}
        activeId={conversationId}
        disabled={busy}
        open={sidebarOpen}
        onSelect={openConversation}
        onNewChat={newChat}
        onDelete={deleteConversation}
        onPin={(c) => changeConversation(c, { pinned: !c.pinned })}
        onRename={renameConversation}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-stone-200 bg-white/80 px-3 backdrop-blur sm:gap-3 sm:px-4 dark:border-stone-800 dark:bg-stone-950/80">
          <button
            onClick={() => setSidebarOpen(true)}
            aria-label={t.showConversations}
            className="flex size-8 shrink-0 items-center justify-center rounded-lg text-stone-600 hover:bg-stone-100 md:hidden dark:text-stone-300 dark:hover:bg-stone-900"
          >
            <Icon name="menu" className="size-5" />
          </button>
          <div className="flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-gradient-to-br from-blue-700 to-sky-500 text-[13px] font-extrabold tracking-tight text-white">
            HS
          </div>
          <h1 className="hidden truncate text-[15px] font-semibold lg:block">{t.appName}</h1>
          {overview && overview.length > 1 ? (
            <label className="flex min-w-0 items-center gap-1.5 rounded-xl border border-stone-200 bg-white py-1 pl-2.5 pr-1 text-sm font-medium dark:border-stone-700 dark:bg-stone-900">
              <Icon name="building" className="size-4 text-stone-500" />
              <select
                value={hotel ?? ""}
                onChange={(e) => pickHotel(e.target.value)}
                aria-label={t.hotel}
                className="min-w-0 max-w-44 cursor-pointer truncate bg-transparent py-0.5 outline-none"
              >
                {overview.map((h) => (
                  <option key={h.hotel_code} value={h.hotel_code}>
                    {h.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            current && (
              <span className="flex min-w-0 items-center gap-1.5 truncate rounded-xl border border-stone-200 px-2.5 py-1 text-sm font-medium dark:border-stone-700">
                <Icon name="building" className="size-4 text-stone-500" />
                {current.name}
              </span>
            )
          )}
          <div className="ml-auto" />
          <button
            onClick={newChat}
            disabled={busy || messages.length === 0}
            aria-label={t.newChat}
            title={t.newChat}
            className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-stone-200 text-stone-600 hover:bg-stone-100 disabled:opacity-40 md:hidden dark:border-stone-700 dark:text-stone-300 dark:hover:bg-stone-900"
          >
            <Icon name="edit" />
          </button>
          <UserMenu name={name} user={user} isAdmin={isAdmin} theme={theme} />
        </header>

        <div
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
          className="flex-1 overflow-y-auto"
        >
          {messages.length === 0 ? (
            <Home name={name} hotel={current} failed={overviewFailed} onAsk={send} onRetry={loadOverview} />
          ) : (
            <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
              {messages.map((m, i) =>
                m.role === "user" ? (
                  <div key={m.id} className="flex justify-end">
                    <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-stone-200/80 px-4 py-2 text-[15px] dark:bg-stone-800">
                      {m.text}
                    </p>
                  </div>
                ) : (
                  <AssistantMessageView
                    key={m.id}
                    message={m}
                    isLast={i === messages.length - 1 && !busy}
                    onAsk={send}
                    onFeedback={conversationId ? (v) => answerFeedback(m, v) : undefined}
                  />
                ),
              )}
            </div>
          )}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="border-t border-stone-200 bg-white px-3 pb-2 pt-3 sm:px-4 dark:border-stone-800 dark:bg-stone-950"
        >
          <div className="mx-auto flex max-w-3xl items-end gap-1.5 rounded-2xl border border-stone-300 bg-white py-1.5 pl-3.5 pr-1.5 shadow-sm focus-within:border-accent dark:border-stone-700 dark:bg-stone-900">
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
              placeholder={listening ? t.listening : placeholder}
              aria-label={t.message}
              className="field-sizing-content max-h-40 min-h-9 flex-1 resize-none bg-transparent py-1.5 text-[15px] outline-none placeholder:text-stone-400"
            />
            {canDictate && !busy && (
              <button
                type="button"
                onClick={dictate}
                aria-label={t.dictate}
                title={t.dictate}
                aria-pressed={listening}
                className="flex size-9 shrink-0 items-center justify-center rounded-xl text-stone-500 hover:bg-stone-100 aria-pressed:bg-red-50 aria-pressed:text-red-600 dark:hover:bg-stone-800"
              >
                <Icon name="mic" className="size-5" />
              </button>
            )}
            {busy ? (
              <button
                type="button"
                onClick={() => abortRef.current?.abort()}
                className="flex h-9 shrink-0 items-center gap-1.5 rounded-xl border border-stone-300 px-3 text-sm font-medium hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-800"
              >
                <Icon name="stop" className="size-3.5" />
                {t.stop}
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                aria-label={t.send}
                title={t.send}
                className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-accent text-white disabled:bg-stone-300 disabled:text-stone-500 dark:disabled:bg-stone-700 dark:disabled:text-stone-400"
              >
                <Icon name="send" className="size-5" />
              </button>
            )}
          </div>
          <p className="mx-auto mt-1.5 hidden max-w-3xl gap-4 text-[11.5px] text-stone-500 sm:flex">
            <span>{t.hintKeys}</span>
            <span>{t.hintCan}</span>
          </p>
        </form>
      </div>
    </div>
  );
}
