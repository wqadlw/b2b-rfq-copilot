"""Ingest demo knowledge docs into the demo adapter store (M0: counts + fingerprint stub)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src"))

from rfq_copilot.adapters.demo.data import DOCS, POISON_DOCS  # noqa: E402


def main() -> int:
    all_docs = DOCS + POISON_DOCS
    by_trust: dict[str, int] = {}
    for doc in all_docs:
        by_trust[doc.trust_level] = by_trust.get(doc.trust_level, 0) + 1
    print(f"demo knowledge ingest: {len(all_docs)} documents")
    for trust, count in sorted(by_trust.items()):
        print(f"  trust={trust:8s} {count}")
    poisoned = ", ".join(d.doc_id for d in POISON_DOCS)
    print(f"  poisoned samples kept for C-family evals: {poisoned}")
    print("note: M1 replaces this stub with pgvector ingestion + hybrid retrieval.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
