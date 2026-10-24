"use client";

import { useState } from "react";
import { groupConversations, shortDate, type ConversationSummary } from "@/lib/chat";
import { Icon } from "./Icons";
import { useI18n } from "./I18n";

type Props = {
  conversations: ConversationSummary[] | null; // null while loading
  activeId: string | null;
  disabled: boolean;
  open: boolean; // on phones the list is a drawer
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onDelete: (c: ConversationSummary) => void;
  onPin: (c: ConversationSummary) => void;
  onRename: (c: ConversationSummary) => void;
  onClose: () => void;
};

/** New chat, search, and the saved conversations: pinned first, then by day. Before the first
 * conversation, a short guide to what the assistant can do. */
export default function Sidebar(props: Props) {
  const { conversations, activeId, disabled, open, onSelect, onNewChat, onDelete, onPin, onRename, onClose } = props;
  const { locale, t } = useI18n();
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const matching = conversations?.filter((c) => !q || c.title.toLowerCase().includes(q)) ?? null;
  const groups = matching ? groupConversations(matching) : [];
  const action =
    "flex size-7 items-center justify-center rounded-md text-stone-500 hover:bg-stone-300 hover:text-stone-900 disabled:opacity-30 dark:hover:bg-stone-700 dark:hover:text-stone-100";

  return (
    <>
      {open && <div className="fixed inset-0 z-20 bg-black/30 md:hidden" onClick={onClose} aria-hidden="true" />}
      <aside
        aria-label={t.conversations}
        className={`${open ? "fixed inset-y-0 left-0 z-30 flex w-72 shadow-xl" : "hidden"} flex-col gap-3 border-r border-stone-200 bg-stone-100 p-3 md:static md:flex md:w-64 md:shadow-none dark:border-stone-800 dark:bg-stone-900`}
      >
        <div className="flex items-center gap-2">
          <button
            onClick={onNewChat}
            disabled={disabled}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            <Icon name="plus" />
            {t.newChat}
          </button>
          <button onClick={onClose} aria-label={t.close} className="rounded-lg p-2 text-stone-500 hover:bg-stone-200 md:hidden dark:hover:bg-stone-800">
            <Icon name="close" />
          </button>
        </div>
        {!!conversations?.length && (
          <label className="flex items-center gap-2 rounded-xl border border-stone-200 bg-white px-2.5 py-1.5 text-sm focus-within:border-accent dark:border-stone-700 dark:bg-stone-950">
            <Icon name="search" className="size-4 text-stone-400" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t.searchConversations}
              aria-label={t.searchConversations}
              className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-stone-400"
            />
          </label>
        )}
        <nav className="-mx-1 flex-1 overflow-y-auto px-1">
          {conversations === null ? (
            <p className="px-2 py-1 text-sm text-stone-500">{t.loading}</p>
          ) : conversations.length === 0 ? (
            <div className="rounded-xl border border-blue-100 bg-gradient-to-b from-blue-50 to-white p-3 text-sm text-stone-700 dark:border-blue-950 dark:from-blue-950/50 dark:to-stone-900 dark:text-stone-300" data-testid="guide">
              <p className="flex items-center gap-1.5 font-semibold text-stone-900 dark:text-stone-100">
                <Icon name="bulb" />
                {t.guideTitle}
              </p>
              <ul className="mt-2 space-y-1.5">
                {t.guideItems.map((g) => (
                  <li key={g}>{g}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-stone-500">{t.noConversations}</p>
            </div>
          ) : groups.length === 0 ? (
            <p className="px-2 py-1 text-sm text-stone-500">{t.noMatches}</p>
          ) : (
            groups.map((g) => (
              <div key={g.key} className="mb-3">
                <h3 className="px-2 pb-1 text-[11px] font-bold uppercase tracking-wider text-stone-500">{t.groups[g.key]}</h3>
                <ul className="space-y-0.5">
                  {g.items.map((c) => (
                    <li key={c.id} className="group relative">
                      <button
                        onClick={() => onSelect(c.id)}
                        disabled={disabled}
                        aria-current={c.id === activeId ? "true" : undefined}
                        className="flex w-full items-baseline gap-2 rounded-lg py-1.5 pl-2.5 pr-24 text-left text-sm hover:bg-stone-200/70 disabled:opacity-50 aria-[current]:bg-stone-200 aria-[current]:font-medium md:pr-2 md:group-focus-within:pr-24 md:group-hover:pr-24 dark:hover:bg-stone-800 dark:aria-[current]:bg-stone-800"
                      >
                        {c.pinned && <Icon name="pin" className="size-3.5 self-center text-stone-400" />}
                        <span className="min-w-0 flex-1 truncate">{c.title}</span>
                        <span className="hidden shrink-0 text-xs text-stone-500 md:inline md:group-focus-within:hidden md:group-hover:hidden">{shortDate(c.updated, undefined, locale)}</span>
                      </button>
                      <div className="absolute right-1 top-1/2 flex -translate-y-1/2 gap-0.5 md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100">
                        <button onClick={() => onPin(c)} disabled={disabled} aria-label={`${c.pinned ? t.unpin : t.pin} “${c.title}”`} title={c.pinned ? t.unpin : t.pin} className={action}>
                          <Icon name="pin" className="size-3.5" />
                        </button>
                        <button onClick={() => onRename(c)} disabled={disabled} aria-label={`${t.rename} “${c.title}”`} title={t.rename} className={action}>
                          <Icon name="edit" className="size-3.5" />
                        </button>
                        <button onClick={() => onDelete(c)} disabled={disabled} aria-label={t.deleteNamed(c.title)} title={t.delete} className={action}>
                          <Icon name="trash" className="size-3.5" />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </nav>
      </aside>
    </>
  );
}
