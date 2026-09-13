"""T-014 faithfulness judge 单测（FakeLLM 脚本化，无网络）。"""

import pytest

from rfq_copilot.core.agent.llm import FakeLLM
from rfq_copilot.core.eval.faithfulness import judge, render_judge_user

pytestmark = pytest.mark.asyncio


async def test_faithful_answer_passes():
    llm = FakeLLM([{"faithful": True, "unsupported": []}])
    verdict = await judge(llm, "这台泵的极限真空？", "极限真空是 0.01 Pa [1]。", "资料：极限真空 0.01 Pa")
    assert verdict["faithful"] is True


async def test_unsupported_claim_fails():
    llm = FakeLLM([{"faithful": True, "unsupported": ["最高可达 99% 效率"]}])
    verdict = await judge(llm, "效率如何？", "效率最高可达 99% 效率。", "资料：效率 80%。")
    assert verdict["faithful"] is False  # 一致性硬校验：有不支持陈述即不忠实


async def test_unparseable_judge_output_is_unfaithful():
    llm = FakeLLM([{"unexpected": "shape"}])
    verdict = await judge(llm, "q", "a", "ctx")
    assert verdict["faithful"] is False


def test_render_contains_all_sections():
    text = render_judge_user("q1", "a1", "ctx1")
    assert "【问题】q1" in text and "【回答】a1" in text and "【资料】ctx1" in text
