"""Unit: 检索关键词优选（实体子串优先 / 防陈旧实体劫持）。"""

from rfq_copilot.core.agent.routing_guards import select_search_keyword


def test_entity_substring_of_message_wins() -> None:
    u = {"entities": {"product_category": "旋片式真空泵"}}
    assert select_search_keyword("旋片式真空泵有哪些？", u) == "旋片式真空泵"


def test_message_substring_of_entity_also_accepted() -> None:
    u = {"entities": {"product_category": "无油旋片真空泵"}}
    assert select_search_keyword("无油旋片真空泵", u) == "无油旋片真空泵"


def test_stale_entity_ignored() -> None:
    """多轮合并留下的陈旧实体不得劫持新问题。"""
    u = {"entities": {"product_category": "旋片泵"}}
    assert select_search_keyword("干泵推荐", u) == "干泵推荐"


def test_list_entity_supported() -> None:
    u = {"entities": {"product_category": ["旋片真空泵", "罗茨真空泵"]}}
    assert select_search_keyword("旋片真空泵怎么样", u) == "旋片真空泵"


def test_no_entity_falls_back_to_message_truncated() -> None:
    assert select_search_keyword("真空泵", None) == "真空泵"
    long = "一" * 60
    assert select_search_keyword(long, {}) == long[:40]


def test_empty_entity_skipped() -> None:
    u = {"entities": {"product_category": "   "}}
    assert select_search_keyword("真空泵有哪些", u) == "真空泵有哪些"
