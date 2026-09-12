"""Repo policy scanner (authority: docs/policies/repo-policy.md). CI gate — exit 1 on hit."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Internal (gitignored) locations — outside the public repo surface by ADR-007
INTERNAL_PATHS = frozenset({".ai", "AGENTS.md", "PROJECT.md"})
# The scanner itself holds detection signatures; exclude it from content matching
SELF_EXEMPT = "scripts/check_repo_policy.py"

# Files that must never exist in the repo
FORBIDDEN_PATHS: tuple[str, ...] = (
    ".env",
    "02-vacuum-adapter-spec.md",
)

# Content patterns that indicate leaked secrets or private-site markers
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai-style key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9-]{20,}")),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("aws key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("private site name", re.compile(r"zhaozhenkong|昊志机械", re.IGNORECASE)),
    ("real-looking phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
)

ALLOWED_STRINGS = frozenset(
    {"13800000000", "13900000000"}  # demo dataset contact numbers (clearly fictional)
)
SKIP_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", ".ruff_cache", ".mypy_cache", "dist"})
TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".yaml", ".yml", ".toml", ".ts", ".tsx", ".js", ".css",
    ".html", ".example", ".cfg", ".txt",
}


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(ROOT)
        if any(part in INTERNAL_PATHS for part in rel.parts):
            continue  # internal governance surface (gitignored, ADR-007)
        if rel.as_posix() == SELF_EXEMPT:
            continue
        if rel.as_posix() in FORBIDDEN_PATHS:
            files.append(path)  # keep so main() can flag the forbidden file itself
            continue
        if path.is_file():
            files.append(path)
    return files


def main() -> int:
    hits: list[str] = []
    for path in _iter_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in FORBIDDEN_PATHS:
            hits.append(f"PATH  {rel}: forbidden file present")
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        for name, pattern in PATTERNS:
            for match in pattern.finditer(text):
                token = match.group(0)
                if token in ALLOWED_STRINGS:
                    continue
                line = text[: match.start()].count("\n") + 1
                hits.append(f"TEXT  {rel}:{line}: {name} ({token[:12]}…)")

    if hits:
        print(f"REPO POLICY VIOLATIONS ({len(hits)}):")
        for hit in hits:
            print(f"  {hit}")
        return 1
    print("repo policy check: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
