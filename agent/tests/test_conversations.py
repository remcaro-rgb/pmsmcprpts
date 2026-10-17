import pytest

from pms_agent.conversations import ConversationStore, compact_events


def ev(kind, **data):
    return {"event": kind, "data": data}


def test_compact_merges_deltas_only():
    events = [ev("thinking", text="a"), ev("thinking", text="b"), ev("tool_start", id="t", name="x"),
              ev("text", text="Hel"), ev("text", text="lo"), ev("done", stop_reason="end_turn")]
    assert compact_events(events) == [ev("thinking", text="ab"), ev("tool_start", id="t", name="x"),
                                      ev("text", text="Hello"), ev("done", stop_reason="end_turn")]


def test_saved_conversations_survive_a_restart_and_stay_private(tmp_path):
    path = str(tmp_path / "c.sqlite")
    store = ConversationStore(path)
    conv = store.get_or_create(None, "ann@hotel.example")
    conv.messages += [{"role": "user", "content": "Occupancy " * 20}, {"role": "assistant", "content": "Fine."}]
    store.save_turn(conv, "Occupancy " * 20, [ev("text", text="Fi"), ev("text", text="ne."), ev("done")])
    conv.messages += [{"role": "user", "content": "And ADR?"}, {"role": "assistant", "content": "Up."}]
    store.save_turn(conv, "And ADR?", [ev("text", text="Up."), ev("done")])

    store = ConversationStore(path)  # a restart
    [item] = store.list("ann@hotel.example")
    assert item["id"] == conv.id and item["title"].startswith("Occupancy Occupancy") and len(item["title"]) == 80
    saved = store.load(conv.id, "ann@hotel.example")
    assert [t["user"] for t in saved["turns"]] == ["Occupancy " * 20, "And ADR?"]
    assert saved["turns"][0]["events"] == [ev("text", text="Fine."), ev("done")]

    again = store.get_or_create(conv.id, "ann@hotel.example")
    assert len(again.messages) == 4 and again.turns == 2
    store.save_turn(again, "More?", [ev("done")])
    assert len(store.load(conv.id, "ann@hotel.example")["turns"]) == 3

    assert store.list("bob@hotel.example") == [] and store.list(None) == []
    assert store.load(conv.id, "bob@hotel.example") is None
    with pytest.raises(LookupError):
        store.get_or_create(conv.id, "bob@hotel.example")
    with pytest.raises(LookupError):
        store.get_or_create("conv_unknown", "ann@hotel.example")
    assert not store.delete(conv.id, "bob@hotel.example")
    assert store.delete(conv.id, "ann@hotel.example")
    assert store.list("ann@hotel.example") == []
    assert store.db.execute("SELECT count(*) FROM turns").fetchone()[0] == 0
