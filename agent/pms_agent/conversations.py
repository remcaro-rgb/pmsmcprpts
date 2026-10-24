"""Saved conversations (SQLite): the Messages API history that continues a conversation, and the
streamed events of each turn so the website can show it again exactly as it was answered."""

import asyncio
import json
import secrets
import sqlite3
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

TITLE_CHARS = 80
SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,          -- signed-in website user, or '' when sign-in is off
    title TEXT NOT NULL,
    created REAL NOT NULL,
    updated REAL NOT NULL,
    messages TEXT NOT NULL        -- Messages API history (JSON)
);
CREATE INDEX IF NOT EXISTS conversations_owner ON conversations (owner, updated DESC);
CREATE TABLE IF NOT EXISTS turns (
    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    user_text TEXT NOT NULL,
    events TEXT NOT NULL,         -- UI events of the answer (JSON), deltas merged
    PRIMARY KEY (conversation_id, seq)
);
CREATE TABLE IF NOT EXISTS feedback (
    owner TEXT NOT NULL,
    kind TEXT NOT NULL,           -- 'answer' or 'recommendation'
    ref TEXT NOT NULL,            -- conversation id and turn, or the day, hotel and position
    value TEXT NOT NULL,          -- 'up', 'down' or 'done'
    note TEXT NOT NULL DEFAULT '',
    updated REAL NOT NULL,
    PRIMARY KEY (owner, kind, ref)
);
CREATE TABLE IF NOT EXISTS prefs (
    owner TEXT PRIMARY KEY,       -- the signed-in user's email
    digest INTEGER NOT NULL DEFAULT 0,  -- the daily email is on
    language TEXT NOT NULL DEFAULT 'en',
    hotel TEXT NOT NULL DEFAULT '',     -- hotel code; '' for the first one they see
    last_sent TEXT NOT NULL DEFAULT '', -- the day the last daily email went out
    updated REAL NOT NULL
);
"""


@dataclass
class Conversation:
    id: str
    owner: str | None = None  # signed-in website user; None when sign-in is off
    # Messages API history. Append-only: earlier turns are never edited, which keeps the
    # prompt cache warm and keeps replayed thinking blocks valid.
    messages: list[dict[str, Any]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    turns: int = 0  # saved turns


def compact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merges consecutive text and thinking deltas; replaying the result renders the same answer."""
    out: list[dict[str, Any]] = []
    for ev in events:
        last = out[-1] if out else None
        if last and ev["event"] in ("text", "thinking") and last["event"] == ev["event"]:
            out[-1] = {"event": ev["event"], "data": {"text": last["data"]["text"] + ev["data"]["text"]}}
        else:
            out.append(ev)
    return out


def _title(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1].rstrip() + "…"


class ConversationStore:
    def __init__(self, path: str = ":memory:", cache_size: int = 200):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(conversations)")}
        if "pinned" not in columns:  # files saved before pinning
            self.db.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        self.cache_size = cache_size
        # Loaded conversations, with the lock that serializes their turns.
        self._live: OrderedDict[str, Conversation] = OrderedDict()

    def get_or_create(self, conversation_id: str | None, owner: str | None = None) -> Conversation:
        """A new conversation, or a saved one of this owner's. Raises LookupError otherwise."""
        if not conversation_id:
            conv = Conversation(f"conv_{secrets.token_hex(8)}", owner)
        elif (conv := self._live.get(conversation_id)) is not None:
            if conv.owner != owner:
                raise LookupError(conversation_id)
        else:
            row = self.db.execute(
                "SELECT messages, (SELECT count(*) FROM turns WHERE conversation_id = id) FROM conversations"
                " WHERE id = ? AND owner = ?", (conversation_id, owner or "")).fetchone()
            if not row:
                raise LookupError(conversation_id)
            conv = Conversation(conversation_id, owner, json.loads(row[0]), turns=row[1])
        self._live[conv.id] = conv
        self._live.move_to_end(conv.id)
        for key in list(self._live)[: max(0, len(self._live) - self.cache_size)]:
            if not self._live[key].lock.locked():
                del self._live[key]
        return conv

    def save_turn(self, conv: Conversation, user_text: str, events: list[dict[str, Any]]) -> None:
        """Saves a completed turn: the history so far and the turn's UI events."""
        now = time.time()
        with self.db:
            self.db.execute("BEGIN")
            self.db.execute(
                "INSERT INTO conversations (id, owner, title, created, updated, messages)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (id) DO UPDATE SET updated = excluded.updated, messages = excluded.messages",
                (conv.id, conv.owner or "", _title(user_text), now, now, json.dumps(conv.messages)))
            self.db.execute("INSERT INTO turns (conversation_id, seq, user_text, events) VALUES (?, ?, ?, ?)",
                            (conv.id, conv.turns, user_text, json.dumps(compact_events(events), default=str)))
        conv.turns += 1

    def list(self, owner: str | None, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT id, title, updated, pinned FROM conversations WHERE owner = ?"
            " ORDER BY pinned DESC, updated DESC LIMIT ?", (owner or "", limit)).fetchall()
        return [{"id": r[0], "title": r[1], "updated": r[2], "pinned": bool(r[3])} for r in rows]

    def update(self, conversation_id: str, owner: str | None, title: str | None = None,
               pinned: bool | None = None) -> bool:
        """Renames or pins one of the owner's conversations."""
        sets, args = [], []
        if title is not None and title.strip():
            sets.append("title = ?")
            args.append(_title(title))
        if pinned is not None:
            sets.append("pinned = ?")
            args.append(int(pinned))
        if not sets:
            return self.db.execute("SELECT 1 FROM conversations WHERE id = ? AND owner = ?",
                                   (conversation_id, owner or "")).fetchone() is not None
        return self.db.execute(f"UPDATE conversations SET {', '.join(sets)} WHERE id = ? AND owner = ?",
                               (*args, conversation_id, owner or "")).rowcount > 0

    def set_feedback(self, owner: str | None, kind: str, ref: str, value: str | None, note: str = "") -> None:
        """Records a thumbs up or down, or "done"; None clears it."""
        with self.db:
            self.db.execute("BEGIN")
            if value is None:
                self.db.execute("DELETE FROM feedback WHERE owner = ? AND kind = ? AND ref = ?",
                                (owner or "", kind, ref))
            else:
                self.db.execute(
                    "INSERT INTO feedback (owner, kind, ref, value, note, updated) VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (owner, kind, ref) DO UPDATE SET value = excluded.value,"
                    " note = excluded.note, updated = excluded.updated",
                    (owner or "", kind, ref, value, note, time.time()))

    def feedback(self, owner: str | None, kind: str, prefix: str = "") -> dict[str, str]:
        rows = self.db.execute("SELECT ref, value FROM feedback WHERE owner = ? AND kind = ?"
                               " AND substr(ref, 1, length(?)) = ?", (owner or "", kind, prefix, prefix)).fetchall()
        return dict(rows)

    def load(self, conversation_id: str, owner: str | None) -> dict[str, Any] | None:
        row = self.db.execute("SELECT title, updated FROM conversations WHERE id = ? AND owner = ?",
                              (conversation_id, owner or "")).fetchone()
        if not row:
            return None
        turns = self.db.execute("SELECT user_text, events FROM turns WHERE conversation_id = ? ORDER BY seq",
                                (conversation_id,)).fetchall()
        votes = self.feedback(owner, "answer", f"{conversation_id}:")
        return {"id": conversation_id, "title": row[0], "updated": row[1],
                "turns": [{"user": t[0], "events": json.loads(t[1]),
                           "feedback": votes.get(f"{conversation_id}:{i}")} for i, t in enumerate(turns)]}

    def delete(self, conversation_id: str, owner: str | None) -> bool:
        """Raises RuntimeError while the conversation is answering."""
        conv = self._live.get(conversation_id)
        if conv is not None and conv.owner == owner and conv.lock.locked():
            raise RuntimeError(conversation_id)
        with self.db:
            self.db.execute("BEGIN")
            deleted = self.db.execute("DELETE FROM conversations WHERE id = ? AND owner = ?",
                                      (conversation_id, owner or "")).rowcount
        if deleted:
            self._live.pop(conversation_id, None)
        return bool(deleted)

    def prefs(self, owner: str) -> dict[str, Any]:
        row = self.db.execute("SELECT digest, language, hotel, last_sent FROM prefs WHERE owner = ?", (owner,)).fetchone()
        digest, language, hotel, last_sent = row or (0, "en", "", "")
        return {"digest": bool(digest), "language": language, "hotel": hotel or None, "last_sent": last_sent or None}

    def set_prefs(self, owner: str, **changes: Any) -> dict[str, Any]:
        """Changes some of digest, language, hotel and last_sent."""
        current = self.prefs(owner)
        current.update({k: v for k, v in changes.items() if v is not None})
        self.db.execute(
            "INSERT INTO prefs (owner, digest, language, hotel, last_sent, updated) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (owner) DO UPDATE SET digest = excluded.digest, language = excluded.language,"
            " hotel = excluded.hotel, last_sent = excluded.last_sent, updated = excluded.updated",
            (owner, int(current["digest"]), current["language"], current["hotel"] or "", current["last_sent"] or "",
             time.time()))
        return current

    def subscribers(self) -> "list[tuple[str, dict[str, Any]]]":
        rows = self.db.execute("SELECT owner FROM prefs WHERE digest = 1 ORDER BY owner").fetchall()
        return [(r[0], self.prefs(r[0])) for r in rows]
