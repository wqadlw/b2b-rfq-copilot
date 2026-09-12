"""Shared fixtures: demo manifest + GraphDeps with FakeLLM + in-memory ports."""

from pathlib import Path
from typing import Any

import pytest

from rfq_copilot.adapters.demo.adapter import build_demo_ports
from rfq_copilot.core.agent.graph import GraphDeps
from rfq_copilot.core.agent.llm import FakeLLM
from rfq_copilot.core.manifest import Manifest, load_manifest
from rfq_copilot.core.memory import SessionStore
from rfq_copilot.core.policies.refusal import derive_refusal_policies
from rfq_copilot.core.prompts import PromptRegistry
from rfq_copilot.core.rag.retriever import KeywordRetriever

ADAPTER_DIR = Path(__file__).resolve().parents[1] / "src" / "rfq_copilot" / "adapters" / "demo"
POISONED = frozenset({"demo-kb-poison-001", "demo-kb-poison-002", "demo-kb-poison-003"})


@pytest.fixture()
def demo_manifest() -> Manifest:
    return load_manifest(ADAPTER_DIR)


def make_deps(scripted: list[dict[str, Any]] | None = None, manifest: Manifest | None = None) -> tuple[GraphDeps, Any]:
    ports = build_demo_ports()
    m = manifest or load_manifest(ADAPTER_DIR)
    deps = GraphDeps(
        manifest=m,
        llm=FakeLLM(scripted or []),
        prompts=PromptRegistry(),
        refusal_policies=derive_refusal_policies(m),
        store=SessionStore(),
        catalog=ports.catalog,
        suppliers=ports.suppliers,
        retriever=KeywordRetriever(ports.knowledge),
        inquiry_sink=ports.inquiry_sink,
        lead_distribution=ports.lead_distribution,
        poisoned_ids=POISONED,
    )
    return deps, ports


def understanding(intent: str, route: str, confidence: float = 0.9, **extra: Any) -> dict[str, Any]:
    return {
        "intent": intent,
        "confidence": confidence,
        "entities": {},
        "missing_fields": [],
        "route": route,
        "needs_clarification": False,
        "needs_human": False,
        "human_reason": None,
        "refusal_reason": None,
        **extra,
    }
