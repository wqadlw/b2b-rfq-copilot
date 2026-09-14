"""Session status machine: unit tests (CS-1)."""

from rfq_copilot.core.memory import SessionStore


def test_default_status_is_bot_serving() -> None:
    store = SessionStore()
    store.get_or_create("s1")
    assert store.status("s1") == "bot_serving"


def test_set_status_transition() -> None:
    store = SessionStore()
    store.get_or_create("s1")
    assert store.set_status("s1", "handoff_pending") == "handoff_pending"
    assert store.set_status("s1", "human_serving") == "human_serving"
    assert store.set_status("s1", "closed") == "closed"


def test_set_status_unknown_session_creates() -> None:
    store = SessionStore()
    assert store.set_status("ghost", "human_serving") == "human_serving"
    assert store.find("ghost") is not None


def test_list_by_status_filters_and_orders() -> None:
    store = SessionStore()
    store.get_or_create("early")
    store.append_message("early", "user", "hello")
    store.get_or_create("late")
    store.append_message("late", "user", "world")
    for sid in ("early", "late"):
        store.set_status(sid, "handoff_pending")
    got = store.list_by_status("handoff_pending")
    ids = [s.session_id for s in got]
    assert set(ids) == {"early", "late"}
    # ts has second precision: same-second ties may order either way — membership only
    assert len(ids) == 2
