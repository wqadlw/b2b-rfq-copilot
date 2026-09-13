"""Faithfulness judge (ragas 思想，--live 专用): 回答的每个陈述是否被资料支持。

CI 环境无 LLM Key 时不启用——程序化断言（06-eval-spec）继续兜底。
"""

from __future__ import annotations

import json
from typing import Any

JUDGE_SYSTEM = (
    "你是评测裁判。给定【问题】【回答】【资料】，判断回答中的陈述是否全部被资料支持。"
    '只输出 JSON：{"faithful": true/false, "unsupported": ["不被支持的陈述", ...]}。'
    "资料中不存在的数字、型号、承诺一律视为不被支持。"
)

QUESTION_LABEL = "【问题】"
ANSWER_LABEL = "【回答】"
CONTEXT_LABEL = "【资料】"
SEP = "\n\n"


def render_judge_user(question: str, answer: str, context: str) -> str:
    parts = [QUESTION_LABEL + question, ANSWER_LABEL + answer, CONTEXT_LABEL + context[:3000]]
    return SEP.join(parts)


def parse_verdict(raw: dict[str, Any]) -> dict[str, Any]:
    faithful = bool(raw.get("faithful"))
    unsupported = [str(x) for x in raw.get("unsupported", []) if x]
    if faithful and unsupported:
        faithful = False  # 一致性硬校验：存在不支持陈述即不忠实
    return {"faithful": faithful, "unsupported": unsupported}


async def judge(llm: Any, question: str, answer: str, context: str) -> dict[str, Any]:
    raw = await llm.complete_json(JUDGE_SYSTEM, render_judge_user(question, answer, context))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {"faithful": False, "unsupported": ["<judge output unparseable>"]}
    if not isinstance(raw, dict):
        return {"faithful": False, "unsupported": ["<judge output not a dict>"]}
    return parse_verdict(raw)
