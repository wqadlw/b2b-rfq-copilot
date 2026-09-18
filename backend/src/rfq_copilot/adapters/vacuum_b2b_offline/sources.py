"""Loaders that turn site seeder files into plain Python structures.

Anti-corruption layer rules:
- stdlib only; imports nothing from rfq_copilot (import-linter: adapters must not import core/app).
- every loader returns RAW dicts/lists; conversion to KnowledgeDocument happens in the
  ETL script (scripts/), which is outside the import-linter boundary.
- loaders never follow symlinks outside the given seeders directory and never write files.
"""

from __future__ import annotations

import re
from pathlib import Path

from rfq_copilot.adapters.vacuum_b2b_offline.php_array import (
    PhpParseError,
    extract_literal_span,
    parse_php_value,
)

SeederDir = Path


def _read(seeders_dir: Path, filename: str) -> str:
    path = Path(seeders_dir) / filename
    if not path.is_file():
        raise FileNotFoundError(f"seeder file not found: {path}")
    return path.read_text(encoding="utf-8", errors="strict")


def _parse_file(seeders_dir: Path, filename: str) -> object:
    text = _read(seeders_dir, filename)
    return parse_php_value(text)


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------


def load_products(seeders_dir: SeederDir) -> list[dict[str, object]]:
    """product_data.php -> list of product dicts (var_export long-array syntax)."""
    data = _parse_file(seeders_dir, "product_data.php")
    if not isinstance(data, list):
        raise PhpParseError("product_data.php: expected a top-level list", 0)
    return [item for item in data if isinstance(item, dict)]


# ---------------------------------------------------------------------------
# three-tier process library (industries -> process_categories -> varieties)
# ---------------------------------------------------------------------------


def load_process_library(seeders_dir: SeederDir) -> list[dict[str, object]]:
    """ProcessLibrarySeeder.php -> industries() return literal (nested tree)."""
    text = _read(seeders_dir, "ProcessLibrarySeeder.php")
    literal = extract_literal_span(text, "private function industries(): array")
    data = parse_php_value(literal)
    if not isinstance(data, list):
        raise PhpParseError("ProcessLibrarySeeder: industries() is not a list", 0)
    return [item for item in data if isinstance(item, dict)]


def _iter_php_array_literals(text: str) -> list[str]:
    """All `return [...]` / `$var = [...]` / `array(...)` literals, in file order."""
    spans: list[str] = []
    for match in re.finditer(r"(?:return\s+\[|=)\s*\[|\barray\s*\(", text):
        start = match.end() - 1
        if text[start] != "[" and not text[max(0, start - 5) : start + 1].lower().endswith("array"):
            continue
        opener = "[" if text[start] == "[" else "("
        try:
            from rfq_copilot.adapters.vacuum_b2b_offline.php_array import _match_bracket

            end = (
                _match_bracket(text, start)
                if opener == "["
                else _match_bracket(text, text.rindex("(", start, start + 8))
            )
        except (PhpParseError, ValueError):
            continue
        spans.append(text[start : end + 1])
    return spans


def load_variety_content(seeders_dir: SeederDir) -> dict[str, dict[str, object]]:
    """VarietyContentSeeder.php -> {variety_slug: content_json}.

    The seeder embeds content_json inside updateOrCreate($attrs) arrays; we walk every
    array literal in the file and keep dicts that carry both `slug` and `content_json`.
    """
    text = _read(seeders_dir, "VarietyContentSeeder.php")
    found: dict[str, dict[str, object]] = {}
    for literal in _iter_php_array_literals(text):
        try:
            value = parse_php_value(literal)
        except PhpParseError:
            continue
        _collect_slug_content(value, found)
    return found


def _collect_slug_content(value: object, found: dict[str, dict[str, object]]) -> None:
    if isinstance(value, dict):
        slug = value.get("slug")
        content = value.get("content_json")
        if isinstance(slug, str) and isinstance(content, dict):
            found.setdefault(slug, content)
        for child in value.values():
            _collect_slug_content(child, found)
    elif isinstance(value, list):
        for child in value:
            _collect_slug_content(child, found)


def load_pain_nav(seeders_dir: SeederDir) -> dict[str, list[dict[str, object]]]:
    """IndustryPainNavSeeder.php -> {industry_slug: [{"tag": ..., "target_slug": ...}]}."""
    text = _read(seeders_dir, "IndustryPainNavSeeder.php")
    found: dict[str, list[dict[str, object]]] = {}
    # painNavMap(): return [ 'industry-slug' => [ [ 'tag' => ..., 'target_slug' => ... ], ... ] ]
    marker = "private function painNavMap(): array"
    if marker in text:
        literal = extract_literal_span(text, marker)
        data = parse_php_value(literal)
        if isinstance(data, dict):
            for slug, items in data.items():
                if isinstance(items, list):
                    found[str(slug)] = [item for item in items if isinstance(item, dict)]
            return found
    for literal in _iter_php_array_literals(text):
        try:
            value = parse_php_value(literal)
        except PhpParseError:
            continue
        if isinstance(value, dict):
            for slug, items in value.items():
                is_tag_map = (
                    isinstance(items, list)
                    and bool(items)
                    and all(isinstance(i, dict) for i in items)
                    and any("tag" in item for item in items if isinstance(item, dict))
                )
                if is_tag_map:
                    found.setdefault(str(slug), [item for item in items if isinstance(item, dict)])
    return found


# ---------------------------------------------------------------------------
# solutions / questions (QA-pair sources)
# ---------------------------------------------------------------------------


def load_solutions(seeders_dir: SeederDir) -> list[dict[str, object]]:
    """SolutionSeeder.php -> list of solution dicts (pain_points_json / faq_json ...)."""
    return _load_list_seeder(seeders_dir, "SolutionSeeder.php")


def load_questions(seeders_dir: SeederDir) -> list[dict[str, object]]:
    """QuestionSeeder.php -> Q&A dicts (title 索引 + acceptedAnswers 拼合).

    该 seeder 的数据形态是「问题索引 + 采纳答案字典」分离：
    $questions = [['title'..., 'slug' => 'q-1', ...], ...]
    $acceptedAnswers = ['q-1' => '完整答案文本', ...]
    """
    text = _read(seeders_dir, "QuestionSeeder.php")
    questions: list[dict[str, object]] = []
    answers: dict[str, str] = {}
    for marker in ("$questions =", "$acceptedAnswers ="):
        if marker not in text:
            continue
        try:
            literal = extract_literal_span(text, marker)
            value = parse_php_value(literal)
        except PhpParseError:
            continue
        if marker.startswith("$questions") and isinstance(value, list):
            questions = [item for item in value if isinstance(item, dict)]
        elif marker.startswith("$acceptedAnswers") and isinstance(value, dict):
            answers = {str(k): str(v) for k, v in value.items()}
    merged: list[dict[str, object]] = []
    for item in questions:
        slug = str(item.get("slug", ""))
        merged.append({**item, "answer": answers.get(slug, "")})
    return merged


def load_cases(seeders_dir: SeederDir) -> list[dict[str, object]]:
    """CaseSeeder.php -> list of case dicts."""
    return _load_list_seeder(seeders_dir, "CaseSeeder.php")


def load_articles(seeders_dir: SeederDir) -> list[dict[str, object]]:
    """ArticleSeeder.php -> list of article dicts (supplier submissions carry supplier_id)."""
    return _load_list_seeder(seeders_dir, "ArticleSeeder.php")


def load_services(seeders_dir: SeederDir) -> list[dict[str, object]]:
    """ServiceSeeder.php -> list of service dicts."""
    return _load_list_seeder(seeders_dir, "ServiceSeeder.php")


def load_insights(seeders_dir: SeederDir) -> list[dict[str, object]]:
    """InsightSeeder.php -> list of insight dicts."""
    return _load_list_seeder(seeders_dir, "InsightSeeder.php")


def _load_list_seeder(seeders_dir: SeederDir, filename: str) -> list[dict[str, object]]:
    """Extract the file's data array.

    Content seeders declare their payload in a class method (`private function x(): array
    { return [...] }`) or a local variable (`$items = [...]`). We try a prioritized list of
    markers first, then fall back to the largest top-level list literal found in the file.
    """
    text = _read(seeders_dir, filename)
    candidates: list[list[dict[str, object]]] = []

    markers = (
        "private function solutions(): array",
        "private function questions(): array",
        "private function cases(): array",
        "private function insights(): array",
        "private function articles(): array",
        "private function services(): array",
        "$questions =",
        "$solutions =",
        "$cases =",
        "$insights =",
        "$articles =",
        "$services =",
    )
    for marker in markers:
        if marker not in text:
            continue
        try:
            literal = extract_literal_span(text, marker)
            value = parse_php_value(literal)
        except PhpParseError:
            continue
        rows = _top_level_rows(value)
        if rows:
            candidates.append(rows)

    if not candidates:
        for literal in _iter_php_array_literals(text):
            try:
                value = parse_php_value(literal)
            except PhpParseError:
                continue
            rows = _top_level_rows(value)
            if rows:
                candidates.append(rows)

    if not candidates:
        return []
    return max(candidates, key=len)


def _top_level_rows(value: object) -> list[dict[str, object]]:
    """Rows = direct dict entries of the payload list (no deep recursion)."""
    rows: list[dict[str, object]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                rows.append(item)
    elif isinstance(value, dict) and ("slug" in value or "name" in value or "title" in value):
        rows.append(value)
    return rows
