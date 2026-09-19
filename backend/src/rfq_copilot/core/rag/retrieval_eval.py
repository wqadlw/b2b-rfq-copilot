"""检索侧评测（06-eval-spec §7）：RAGAS context recall/precision 的确定性代理。

零 LLM token：golden 查询从语料自身规则派生（期望命中文档 = 来源文档），
judge 由"是否命中期望文档"替代——可复现、随 pytest 跑、本地可对真实语料出报告。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from rfq_copilot.core.rag.chunking import Chunk
from rfq_copilot.ports.knowledge_source import KnowledgeDocument

EVAL_K = 5
_CHUNK_SUFFIX = " ("


@dataclass(frozen=True)
class RetrievalCase:
    query: str
    expected_base: str  # 期望命中的文档基 id（doc_id 去分块后缀）
    doc_type: str
    source_doc_id: str  # 派生来源（分块后缀保留，便于排查）


@dataclass
class RetrievalReport:
    cases: int
    recall: float
    precision: float
    mrr: float
    by_doc_type: dict[str, dict[str, float]] = field(default_factory=dict)
    misses: list[str] = field(default_factory=list)  # recall 未命中的 query 样本


def base_doc_id(doc_id: str) -> str:
    """`offline-product-x (2/2)` → `offline-product-x`（分块后缀剥离）。"""
    return doc_id.split(_CHUNK_SUFFIX)[0] if _CHUNK_SUFFIX in doc_id else doc_id


def derive_queries(docs: Sequence[KnowledgeDocument], per_doc: int = 2) -> list[RetrievalCase]:
    """06-eval-spec §7.1：按 doc_type 规则模板自监督派生 golden 查询。"""
    cases: list[RetrievalCase] = []
    for doc in docs:
        title = doc.title.strip()
        if not title:
            continue
        queries: list[str]
        if doc.doc_type == "product":
            queries = [f"{title} 的参数和价格是多少", f"有没有 {title} 这款产品"]
        elif doc.doc_type == "selection_guide":
            queries = [f"{title} 怎么选型", f"{title} 的工艺难点和市场价值"]
        else:
            queries = [title, f"{title} 怎么解决"]
        expected = base_doc_id(doc.doc_id)
        for query in queries[:per_doc]:
            cases.append(
                RetrievalCase(query=query, expected_base=expected, doc_type=doc.doc_type, source_doc_id=doc.doc_id)
            )
    return cases


def _is_relevant(chunk: Chunk, expected_base: str) -> bool:
    return base_doc_id(chunk.doc_id) == expected_base


async def evaluate(
    search: Callable[[str], Awaitable[list[Chunk]]],
    cases: Sequence[RetrievalCase],
    k: int = EVAL_K,
) -> RetrievalReport:
    """§7.2：recall@k / precision@k / mrr，附 doc_type 分项与未命中样本。"""
    recalls: list[float] = []
    precisions: list[float] = []
    rr_scores: list[float] = []
    per_type: dict[str, list[tuple[float, float, float]]] = {}
    misses: list[str] = []

    for case in cases:
        chunks = (await search(case.query))[:k]
        relevance = [_is_relevant(c, case.expected_base) for c in chunks]
        hit = any(relevance)
        recall = 1.0 if hit else 0.0
        precision = sum(relevance) / k if k else 0.0
        mrr = 0.0
        for rank, rel in enumerate(relevance, start=1):
            if rel:
                mrr = 1.0 / rank
                break
        recalls.append(recall)
        precisions.append(precision)
        rr_scores.append(mrr)
        per_type.setdefault(case.doc_type, []).append((recall, precision, mrr))
        if not hit and len(misses) < 20:
            misses.append(case.query)

    n = len(cases) or 1
    by_type = {
        doc_type: {
            "cases": len(rows),
            "recall": sum(r[0] for r in rows) / len(rows),
            "precision": sum(r[1] for r in rows) / len(rows),
            "mrr": sum(r[2] for r in rows) / len(rows),
        }
        for doc_type, rows in per_type.items()
    }
    return RetrievalReport(
        cases=len(cases),
        recall=sum(recalls) / n,
        precision=sum(precisions) / n,
        mrr=sum(rr_scores) / n,
        by_doc_type=by_type,
        misses=misses,
    )


def render_report(report: RetrievalReport, corpus_source: str) -> str:
    """§7.3 markdown 渲染（报告必须注明语料来源）。"""
    lines = [
        "# 检索评测报告",
        "",
        f"- 语料来源：{corpus_source}",
        f"- 用例数：{report.cases}（自监督派生，k=5）",
        f"- **recall@5: {report.recall:.4f}** · precision@5: {report.precision:.4f} · mrr: {report.mrr:.4f}",
        "",
        "| doc_type | cases | recall@5 | precision@5 | mrr |",
        "|---|---|---|---|---|",
    ]
    for doc_type, row in sorted(report.by_doc_type.items()):
        lines.append(
            f"| {doc_type} | {row['cases']} | {row['recall']:.4f} | {row['precision']:.4f} | {row['mrr']:.4f} |"
        )
    if report.misses:
        lines += ["", "## 未命中样本（≤20）", ""]
        lines += [f"- {q}" for q in report.misses]
    lines += ["", "> precision 为下界口径（其他真实相关文档不计入相关集），不得用于对外宣传。"]
    return "\n".join(lines)


def to_dict(report: RetrievalReport) -> dict[str, Any]:
    return {
        "cases": report.cases,
        "recall_at_5": report.recall,
        "precision_at_5": report.precision,
        "mrr": report.mrr,
        "by_doc_type": report.by_doc_type,
        "misses": report.misses,
    }
