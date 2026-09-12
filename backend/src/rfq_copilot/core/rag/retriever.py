"""M0 keyword retriever over KnowledgeDocuments (replaced by pgvector hybrid in M1)."""

from rfq_copilot.ports.knowledge_source import KnowledgeDocument, KnowledgeSourcePort


class KeywordRetriever:
    """Term-overlap scoring; trust metadata always carried through for isolation."""

    def __init__(self, source: KnowledgeSourcePort) -> None:
        self._docs: list[KnowledgeDocument] = list(source.iter_documents())

    def retrieve(
        self, query: str, top_k: int = 3, poisoned_ids: frozenset[str] = frozenset()
    ) -> list[KnowledgeDocument]:
        terms = [t for t in query.replace("，", " ").replace("？", " ").split() if t]
        scored: list[tuple[int, KnowledgeDocument]] = []
        for doc in self._docs:
            hay = doc.title + doc.content
            score = sum(hay.count(term) for term in terms)
            if doc.doc_id in poisoned_ids:
                score += 1  # poisoned content competes normally: isolation must hold at the policy layer
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]
