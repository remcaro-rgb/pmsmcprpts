"use client";

import { shortDate, type ConversationSummary } from "@/lib/chat";
import { useI18n } from "./I18n";

type Props = {
  conversations: ConversationSummary[] | null; // null while loading
  activeId: string | null;
  disabled: boolean;
  open: boolean; // on phones the list is a drawer
  onSelect: (id: string) => void;
  onDelete: (c: ConversationSummary) => void;
  onClose: () => void;
};

/** Saved conversations, newest first. */
export default function Sidebar({ conversations, activeId, disabled, open, onSelect, onDelete, onClose }: Props) {
  const { locale, t } = useI18n();
  return (
    <>
      {open && <div className="fixed inset-0 z-20 bg-black/30 md:hidden" onClick={onClose} aria-hidden="true" />}
      <aside
        aria-label={t.conversations}
        className={`${open ? "fixed inset-y-0 left-0 z-30 flex w-72 shadow-xl" : "hidden"} flex-col border-r border-stone-200 bg-stone-50 md:static md:flex md:w-64 md:shadow-none dark:border-stone-800 dark:bg-stone-900`}
      >
        <div className="flex items-center justify-between px-4 pb-2 pt-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-stone-500">{t.conversations}</h2>
          <button onClick={onClose} className="rounded-md px-2 py-1 text-sm text-stone-500 hover:bg-stone-200 md:hidden dark:hover:bg-stone-800">
            {t.close}
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 pb-4">
          {conversations === null ? (
            <p className="px-2 py-1 text-sm text-stone-500">{t.loading}</p>
          ) : conversations.length === 0 ? (
            <p className="px-2 py-1 text-sm text-stone-500">{t.noConversations}</p>
          ) : (
            <ul className="space-y-0.5">
              {conversations.map((c) => (
                <li key={c.id} className="group relative">
                  <button
                    onClick={() => onSelect(c.id)}
                    disabled={disabled}
                    aria-current={c.id === activeId ? "true" : undefined}
                    className="flex w-full items-baseline gap-2 rounded-lg py-2 pl-2.5 pr-9 text-left text-sm hover:bg-stone-200/70 disabled:opacity-50 aria-[current]:bg-stone-200 dark:hover:bg-stone-800 dark:aria-[current]:bg-stone-800"
                  >
                    <span className="min-w-0 flex-1 truncate">{c.title}</span>
                    <span className="shrink-0 text-xs text-stone-500">{shortDate(c.updated, undefined, locale)}</span>
                  </button>
                  <button
                    onClick={() => onDelete(c)}
                    disabled={disabled}
                    aria-label={t.deleteNamed(c.title)}
                    title={t.delete}
                    className="absolute right-1 top-1/2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-stone-500 opacity-100 hover:bg-stone-300 hover:text-stone-900 disabled:opacity-30 md:opacity-0 md:group-hover:opacity-100 md:focus:opacity-100 dark:hover:bg-stone-700 dark:hover:text-stone-100"
                  >
                    <svg viewBox="0 0 16 16" aria-hidden="true" className="size-3.5">
                      <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>
      </aside>
    </>
  );
}
