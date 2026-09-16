"""Local HuggingFace embedding (bge-small-zh-v1.5) — B4 破局：干掉外部 API 依赖。

架构师指令 2026-09-15：本地/云端混合 Embedding 架构。
- 本地（默认 CI/离线）：sentence-transformers BAAI/bge-small-zh-v1.5（512 维，CPU 可跑）
- 云端（生产可选）：SiliconFlow bge-m3（等 Key）
本模块放 adapters/（依赖 sentence-transformers 这个重依赖，懒加载避免拖累启动）。
"""

from __future__ import annotations

from typing import Any

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"


class LocalHuggingFaceEmbedding:
    """sentence-transformers 本地向量化（懒加载，进程内单例模型）。

    防腐层注意：本类不 import rfq_copilot.core（import-linter 契约：adapters 禁依赖
    core）。它以结构化鸭子类型满足 core.rag.embedding.EmbeddingClient 协议
    （async embed(list[str]) -> list[list[float]]），由组合根按协议注入。
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # 重依赖懒加载

            self._model = SentenceTransformer(self._model_name)
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]
