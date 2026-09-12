"""Versioned prompt registry: loads frontmatter-versioned templates from package resources."""

from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

import yaml

from rfq_copilot.ports.errors import ConfigError


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: int
    locale: str
    capability: str | None
    body: str


class PromptRegistry:
    """Loads ``*.md`` prompt templates (YAML frontmatter + body) from ``rfq_copilot.prompts``."""

    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}
        root = files("rfq_copilot") / "prompts"
        for entry in root.iterdir():
            self._walk(entry)

    def _walk(self, entry: Traversable) -> None:
        if entry.is_dir():
            for child in entry.iterdir():
                self._walk(child)
        elif entry.name.endswith(".md"):
            raw = entry.read_text(encoding="utf-8")
            tpl = self._parse(raw)
            self._templates[tpl.name] = tpl

    @staticmethod
    def _parse(raw: str) -> PromptTemplate:
        if not raw.startswith("---"):
            raise ConfigError("prompt template missing YAML frontmatter")
        _, fm, body = raw.split("---", 2)
        meta: dict[str, Any] = yaml.safe_load(fm)
        return PromptTemplate(
            name=str(meta["name"]),
            version=int(meta["version"]),
            locale=str(meta.get("locale", "zh-CN")),
            capability=meta.get("capability"),
            body=body.strip(),
        )

    def get(self, name: str) -> PromptTemplate:
        try:
            return self._templates[name]
        except KeyError as exc:
            raise ConfigError(f"prompt template not found: {name}") from exc

    def render(self, name: str, **variables: str | list[str] | None) -> str:
        tpl = self.get(name)
        out = tpl.body
        for key, value in variables.items():
            out = out.replace("{{" + key + "}}", _stringify(value))
        return out


def _stringify(value: str | list[str] | None) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "、".join(value)
    return value
