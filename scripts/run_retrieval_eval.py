"""检索评测报告脚本（06-eval-spec §7.3）。

KNOWLEDGE_DATA_DIR 非空 → 对离线真实语料评测；否则对 demo 内置语料（CI 同款）。
门禁：recall@5 < RETRIEVAL_EVAL_MIN_RECALL（默认 0.85）→ exit 1。

用法：
    uv run python scripts/run_retrieval_eval.py [--limit 200] [--k 5]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

from rfq_copilot.core.rag.chunking import chunk_document  # noqa: E402
from rfq_copilot.core.rag.embedding import HashingEmbedder  # noqa: E402
from rfq_copilot.core.rag.pipeline import RAGPipeline  # noqa: E402
from rfq_copilot.core.rag.reranker import NoopReranker  # noqa: E402
from rfq_copilot.core.rag.retrieval_eval import (  # noqa: E402
    derive_queries,
    evaluate,
    render_report,
    to_dict,
)
from rfq_copilot.core.rag.store import InMemoryVectorStore  # noqa: E402
from rfq_copilot.ports.knowledge_source import KnowledgeDocument  # noqa: E402

REPORTS_DIR = ROOT / "eval" / "reports"
DEMO_DATA = "demo（内置演示语料，CI 同款）"


def _load_docs() -> tuple[list[KnowledgeDocument], str]:
    from rfq_copilot.config.settings import get_settings

    knowledge_dir = get_settings().knowledge_data_dir.strip()
    if knowledge_dir:
        payload = json.loads((Path(knowledge_dir) / "knowledge.json").read_text(encoding="utf-8"))
        docs = [KnowledgeDocument(**d) for d in payload["documents"]]
        return docs, f"离线快照 {knowledge_dir}（{len(docs)} 篇）"
    from rfq_copilot.adapters.demo import data as demo_data

    docs = list(demo_data.DOCS) + list(demo_data.POISON_DOCS)
    return docs, DEMO_DATA


def _sample(docs: list[KnowledgeDocument], limit: int) -> list[KnowledgeDocument]:
    """doc_id 排序后等距抽样（确定性，不做随机）。"""
    if limit <= 0 or len(docs) <= limit:
        return list(docs)
    stride = len(docs) / limit
    return [docs[min(int(i * stride), len(docs) - 1)] for i in range(limit)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检索侧评测（RAGAS 确定性代理）")
    parser.add_argument("--limit", type=int, default=200, help="评测文档数上限（等距抽样，0=全量）")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args(argv)

    docs, corpus_source = _load_docs()
    docs = _sample(docs, args.limit)
    cases = derive_queries(docs)
    if not cases:
        raise SystemExit("拒绝：语料为空，无法派生检索评测用例")

    async def _run() -> tuple[Any, Any]:
        pipeline = RAGPipeline(embedder=HashingEmbedder(), store=InMemoryVectorStore(), reranker=NoopReranker())
        chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
        await pipeline.ingest(chunks)
        report = await evaluate(pipeline.search, cases, k=args.k)
        return report, len(chunks)

    report, chunk_count = asyncio.run(_run())
    min_recall = float(os.environ.get("RETRIEVAL_EVAL_MIN_RECALL", "0.85"))

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(UTC).date().isoformat()
    (REPORTS_DIR / f"{day}_retrieval.md").write_text(render_report(report, corpus_source), encoding="utf-8")
    payload = to_dict(report)
    payload.update({"corpus_source": corpus_source, "chunk_count": chunk_count, "k": args.k})
    (REPORTS_DIR / f"{day}_retrieval.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"corpus: {corpus_source} | chunks={chunk_count} | cases={report.cases}")
    print(f"recall@{args.k}={report.recall:.4f} precision@{args.k}={report.precision:.4f} mrr={report.mrr:.4f}")
    for doc_type, row in sorted(report.by_doc_type.items()):
        print(f"  [{doc_type}] n={row['cases']} recall={row['recall']:.4f} precision={row['precision']:.4f}")
    print(f"report: eval/reports/{day}_retrieval.md")
    if report.recall < min_recall:
        print(f"FAIL: recall@{args.k} {report.recall:.4f} < 门禁 {min_recall}")
        return 1
    print(f"PASS: recall@{args.k} ≥ 门禁 {min_recall}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
