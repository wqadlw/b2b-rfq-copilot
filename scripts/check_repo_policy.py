"""Repo policy scanner (authority: docs/policies/repo-policy.md). CI gate — exit 1 on hit.

Scans git-tracked files only (respects .gitignore). Files on disk that are
properly gitignored (like .env for local development) are NOT flagged.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Internal (gitignored) locations — outside the public repo surface by ADR-007
INTERNAL_PATHS = frozenset({".ai", "AGENTS.md", "PROJECT.md"})
# The scanner itself holds detection signatures; exclude it from content matching
SELF_EXEMPT = "scripts/check_repo_policy.py"

# Files that must never be tracked by git
FORBIDDEN_TRACKED: frozenset[str] = frozenset({".env", "02-vacuum-adapter-spec.md"})

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
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ts",
    ".tsx",
    ".js",
    ".css",
    ".html",
    ".example",
    ".cfg",
    ".txt",
}


def _git_tracked_files() -> list[str]:
    """Return all files tracked by git (respects .gitignore automatically)."""
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            cwd=str(ROOT),
        )
        return [f for f in out.stdout.splitlines() if f.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def _git_is_tracked(rel_path: str) -> bool:
    """Check if a specific path is tracked by git."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel_path],
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
            cwd=str(ROOT),
        )
        return out.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main() -> int:
    hits: list[str] = []
    tracked = _git_tracked_files()

    # --- Forbidden tracked files ---
    for rel in tracked:
        if rel in FORBIDDEN_TRACKED:
            hits.append(f"TRACKED  {rel}: forbidden file is tracked by git")

    # --- Content pattern scan on tracked text files ---
    for rel in tracked:
        if rel in INTERNAL_PATHS or rel == SELF_EXEMPT:
            continue
        path = ROOT / rel
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
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
                hits.append(f"TEXT    {rel}:{line}: {name} ({token[:12]}…)")

    if hits:
        print(f"REPO POLICY VIOLATIONS ({len(hits)}):")
        for hit in hits:
            print(f"  {hit}")
        return 1
    print(f"repo policy check: clean ({len(tracked)} tracked files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
