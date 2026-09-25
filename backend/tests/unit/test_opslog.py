"""运营观测存储单元测试（spec 02-engine-read-api-spec §1.0/§1.1/§1.2/§2.5）。"""

from rfq_copilot.app.opslog import FeedbackStore, HitStatsRegistry, JsonlStore, NoMatchStore


def test_jsonl_store_memory_only_roundtrip() -> None:
    store = JsonlStore("feedback", data_dir="")
    store.append({"id": "a", "feedback": "helpful"})
    store.append({"id": "b", "feedback": "not_helpful"})
    items, total = store.items()
    assert total == 2
    assert [i["id"] for i in items] == ["b", "a"]  # ts 倒序
    assert all("ts" in i for i in items)


def test_jsonl_store_filters_and_pagination() -> None:
    store = JsonlStore("no_match_events", data_dir="")
    for i in range(5):
        store.append({"id": str(i), "route": "product_flow" if i % 2 else "knowledge_flow"})
    items, total = store.items(filters={"route": "product_flow"})
    assert total == 2 and all(i["route"] == "product_flow" for i in items)
    page1, total = store.items(limit=2, offset=0)
    page2, _ = store.items(limit=2, offset=2)
    assert len(page1) == 2 and len(page2) == 2 and page1[0]["id"] != page2[0]["id"]


def test_jsonl_store_persists_and_replays(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data_dir = str(tmp_path)
    store = JsonlStore("feedback", data_dir=data_dir)
    store.append({"id": "p1", "feedback": "helpful"})
    store.append({"id": "p2", "feedback": "not_helpful"})
    # 新实例 = 模拟重启：回放 JSONL 恢复
    reborn = JsonlStore("feedback", data_dir=data_dir)
    items, total = reborn.items()
    assert total == 2 and {i["id"] for i in items} == {"p1", "p2"}


def test_jsonl_store_replay_skips_corrupt_lines(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path
    (data_dir / "feedback.jsonl").write_text('{"id": "good"}\n{corrupt half line\n', encoding="utf-8")
    reborn = JsonlStore("feedback", data_dir=str(data_dir))
    items, total = reborn.items()
    assert total == 1 and items[0]["id"] == "good"


def test_feedback_stats_by_day(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = FeedbackStore(data_dir=str(tmp_path))
    store.append({"id": "1", "feedback": "helpful"})
    store.append({"id": "2", "feedback": "not_helpful"})
    store.append({"id": "3", "feedback": "not_helpful"})
    stats = store.stats("month")
    assert stats["helpful"] == 1 and stats["not_helpful"] == 2 and stats["total"] == 3
    assert len(stats["by_day"]) == 1
    assert stats["by_day"][0]["helpful"] == 1 and stats["by_day"][0]["not_helpful"] == 2


def test_no_match_stats_routes_and_top_questions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = NoMatchStore(data_dir=str(tmp_path))
    store.append({"question": "磁悬浮泵是什么", "route": "knowledge_flow"})
    store.append({"question": "zzz型号xyz", "route": "product_flow", "keyword": "zzz"})
    store.append({"question": "zzz型号xyz", "route": "product_flow", "keyword": "zzz"})
    stats = store.stats("week")
    assert stats["total"] == 3
    assert stats["by_route"] == {"knowledge_flow": 1, "product_flow": 2}
    assert stats["top_questions"][0]["count"] == 2


def test_hit_stats_record_and_summary(tmp_path) -> None:  # type: ignore[no-untyped-def]
    registry = HitStatsRegistry(data_dir=str(tmp_path))
    registry.record(["doc-a", "doc-b", "doc-a"], day="2026-09-25")
    registry.record(["doc-a"], day="2026-09-26")
    summary = registry.summary(days=30)
    assert summary["days"] == 30
    # doc-a 首现去重后每次检索计 1：两次检索 = 2 命中
    totals = {e["doc_id"]: e["hits"] for e in summary["total_by_doc"]}
    assert totals == {"doc-a": 2, "doc-b": 1}
    assert summary["series"][0] == {"date": "2026-09-25", "doc_id": "doc-a", "hits": 1}


def test_hit_stats_persist_across_restart(tmp_path) -> None:  # type: ignore[no-untyped-def]
    registry = HitStatsRegistry(data_dir=str(tmp_path))
    registry.record(["doc-x"], day="2026-09-25")
    reborn = HitStatsRegistry(data_dir=str(tmp_path))
    summary = reborn.summary(days=30)
    assert {e["doc_id"]: e["hits"] for e in summary["total_by_doc"]} == {"doc-x": 1}


def test_hit_stats_window_excludes_old_days(tmp_path) -> None:  # type: ignore[no-untyped-def]
    registry = HitStatsRegistry(data_dir=str(tmp_path))
    registry.record(["old-doc"], day="2020-01-01")
    registry.record(["new-doc"], day="2026-09-25")
    docs = {e["doc_id"] for e in registry.summary(days=30)["total_by_doc"]}
    assert "old-doc" not in docs and "new-doc" in docs
