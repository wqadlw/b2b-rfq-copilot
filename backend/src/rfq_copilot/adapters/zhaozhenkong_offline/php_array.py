"""PHP array literal parser for 找真空 seeder files (stdlib only, no eval/exec).

Supports both PHP array syntaxes used across the site seeders:
- long form:  array ( 'k' => 'v', 0 => array ( ... ) )   (product_data.php)
- short form: [ 'slug' => 'x', 'priority' => true ]      (ProcessLibrarySeeder.php)

Value kinds: single/double-quoted strings (PHP escaping rules), ints, floats,
NULL/null, true/false, nested arrays. PHP comments (/* */ and //) are skipped.

This module is part of the anti-corruption layer: it must stay dependency-free and
must never be imported by core/ (import-linter forbids adapters -> core, and core -> adapters).
"""

from __future__ import annotations

_WS = " \t\r\n"
_CLOSERS = {"(": ")", "[": "]"}
_OPENERS = {")": "(", "]": "["}


class PhpParseError(ValueError):
    """Raised when a PHP literal cannot be parsed; carries the failing offset."""

    def __init__(self, message: str, pos: int) -> None:
        super().__init__(f"{message} (at offset {pos})")
        self.pos = pos


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    # ---- low level helpers -------------------------------------------------
    def _peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _skip_ignorable(self) -> None:
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch in _WS:
                self.pos += 1
                continue
            if self.text.startswith("/*", self.pos):
                end = self.text.find("*/", self.pos + 2)
                if end == -1:
                    raise PhpParseError("unterminated block comment", self.pos)
                self.pos = end + 2
                continue
            if self.text.startswith("//", self.pos):
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end == -1 else end + 1
                continue
            break

    def _expect(self, literal: str) -> None:
        if not self.text.startswith(literal, self.pos):
            raise PhpParseError(f"expected {literal!r}", self.pos)
        self.pos += len(literal)

    # ---- values -----------------------------------------------------------

    def _skip_to_separator(self) -> None:
        """From current pos, skip until the next `,` or array closer at depth 0 of this call."""
        depth = 0
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == "'":
                self.pos = self._skip_quoted(self.text, self.pos, "'")
                continue
            if ch == '"':
                self.pos = self._skip_quoted(self.text, self.pos, '"')
                continue
            if ch in "([":
                depth += 1
            elif ch in ")]":
                if depth == 0:
                    return
                depth -= 1
            elif ch == "," and depth == 0:
                return
            self.pos += 1

    @staticmethod
    def _skip_quoted(text: str, start: int, quote: str) -> int:
        pos = start + 1
        while pos < len(text):
            if text[pos] == "\\":
                pos += 2
                continue
            if text[pos] == quote:
                return pos + 1
            pos += 1
        return pos

    def parse_value(self) -> object:
        self._skip_ignorable()
        ch = self._peek()
        if ch == "":
            raise PhpParseError("unexpected end of input", self.pos)
        if ch == "'":
            return self._parse_single_quoted()
        if ch == '"':
            return self._parse_double_quoted()
        if ch == "[":
            return self._parse_array("[", "]")
        if ch == "(":  # tolerate a stray paren group
            return self._parse_array("(", ")")
        lower = self.text[self.pos : self.pos + 5].lower()
        if lower.startswith("array"):
            self.pos += 5
            self._skip_ignorable()
            return self._parse_array("(", ")")
        if lower.startswith("null"):
            self.pos += 4
            return None
        if self.text[self.pos : self.pos + 4].lower() == "true":
            self.pos += 4
            return True
        if self.text[self.pos : self.pos + 5].lower() == "false":
            self.pos += 5
            return False
        if ch in "+-" or ch.isdigit():
            return self._parse_number()
        raise PhpParseError(f"unexpected character {ch!r}", self.pos)

    def _parse_single_quoted(self) -> str:
        # PHP single quotes: only \' and \\ are escapes.
        self._expect("'")
        out: list[str] = []
        while True:
            if self.pos >= len(self.text):
                raise PhpParseError("unterminated single-quoted string", self.pos)
            ch = self.text[self.pos]
            if ch == "\\":
                nxt = self.text[self.pos + 1 : self.pos + 2]
                if nxt in {"'", "\\"}:
                    out.append(nxt)
                    self.pos += 2
                    continue
                out.append(ch)
                self.pos += 1
                continue
            if ch == "'":
                self.pos += 1
                return "".join(out)
            out.append(ch)
            self.pos += 1

    def _parse_double_quoted(self) -> str:
        self._expect('"')
        out: list[str] = []
        escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "$": "$"}
        while True:
            if self.pos >= len(self.text):
                raise PhpParseError("unterminated double-quoted string", self.pos)
            ch = self.text[self.pos]
            if ch == "\\":
                nxt = self.text[self.pos + 1 : self.pos + 2]
                out.append(escapes.get(nxt, nxt))
                self.pos += 2
                continue
            if ch == '"':
                self.pos += 1
                return "".join(out)
            out.append(ch)
            self.pos += 1

    def _parse_number(self) -> object:
        start = self.pos
        if self._peek() in "+-":
            self.pos += 1
        while self._peek().isdigit():
            self.pos += 1
        is_float = False
        if self._peek() == ".":
            is_float = True
            self.pos += 1
            while self._peek().isdigit():
                self.pos += 1
        if self._peek() in "eE":
            is_float = True
            self.pos += 1
            if self._peek() in "+-":
                self.pos += 1
            while self._peek().isdigit():
                self.pos += 1
        raw = self.text[start : self.pos]
        try:
            return float(raw) if is_float else int(raw)
        except ValueError as exc:  # pragma: no cover - defensive
            raise PhpParseError(f"invalid number {raw!r}", start) from exc

    def _parse_array(self, opener: str, closer: str) -> object:
        self._expect(opener)
        pairs: list[tuple[object, object]] = []
        bare: list[object] = []
        while True:
            self._skip_ignorable()
            if self._peek() == closer:
                self.pos += 1
                break
            if self._peek() == "":
                raise PhpParseError(f"unterminated array, expected {closer!r}", self.pos)
            try:
                first = self.parse_value()
            except PhpParseError:
                # PHP constant/expression (e.g. Solution::STATUS_PUB, now()) — skip the
                # token up to the next separator and treat as None.
                self._skip_to_separator()
                first = None
            self._skip_ignorable()
            if self.text.startswith("=>", self.pos):
                self.pos += 2
                try:
                    second = self.parse_value()
                except PhpParseError:
                    self._skip_to_separator()
                    second = None
                pairs.append((first, second))
            else:
                bare.append(first)
            self._skip_ignorable()
            if self._peek() == ",":
                self.pos += 1
                continue
            if self._peek() == closer:
                self.pos += 1
                break
            raise PhpParseError(f"expected ',' or {closer!r} in array", self.pos)
        if pairs and bare:
            raise PhpParseError("mixed keyed and bare array entries", self.pos)
        if bare:
            return bare
        if not pairs:
            return []
        keys = [key for key, _ in pairs]
        if all(isinstance(k, int) for k in keys) and keys == list(range(len(keys))):
            return [value for _, value in pairs]
        return {str(key): value for key, value in pairs}


def parse_php_value(text: str) -> object:
    """Parse the first PHP literal found in *text*.

    Tolerates a leading `<?php` tag, any number of comments, an optional `return`
    keyword, class/method scaffolding is NOT tolerated here — use extract_literal_span
    for literals nested inside class bodies.
    """
    stripped = text.lstrip()
    if stripped.startswith("<?php"):
        stripped = stripped[len("<?php") :]
    parser = _Parser(stripped)
    parser._skip_ignorable()
    # After comments/whitespace, skip an optional `return` keyword.
    if parser.text[parser.pos :].lower().startswith("return"):
        parser.pos += 6
    parser._skip_ignorable()
    return parser.parse_value()


def extract_literal_span(text: str, marker: str, occurrence: int = 1) -> str:
    """Return the raw literal (array/string/number) starting after *marker*.

    Uses string-aware bracket matching so brackets inside quoted strings or comments
    do not terminate the literal early. Raises PhpParseError when the marker or a
    well-formed literal cannot be located.
    """
    idx = -1
    for _ in range(occurrence):
        idx = text.find(marker, idx + 1)
        if idx == -1:
            raise PhpParseError(f"marker {marker!r} not found (occurrence {occurrence})", 0)
    cursor = idx + len(marker)
    # Skip whitespace AND arbitrary tokens (e.g. `) {` / `return`) until the first
    # array opener — string/comment aware so quoted braces never confuse the scan.
    while cursor < len(text):
        ch = text[cursor]
        if ch in _WS:
            cursor += 1
            continue
        if ch == "'":
            cursor = _skip_quoted(text, cursor, "'")
            continue
        if ch == '"':
            cursor = _skip_quoted(text, cursor, '"')
            continue
        if ch in _CLOSERS or text.startswith("array", cursor):
            break
        cursor += 1
    start = cursor
    if text.startswith("array", start):
        paren = text.find("(", start)
        if paren == -1:
            raise PhpParseError("'array' without '('", start)
        end = _match_bracket(text, paren)
    elif start < len(text) and text[start] in _CLOSERS:
        end = _match_bracket(text, start)
    else:
        raise PhpParseError("no array literal after marker", start)
    return text[start : end + 1]


def _match_bracket(text: str, open_pos: int) -> int:
    depth = 0
    pos = open_pos
    while pos < len(text):
        ch = text[pos]
        if ch == "'":
            pos = _skip_quoted(text, pos, "'")
            continue
        if ch == '"':
            pos = _skip_quoted(text, pos, '"')
            continue
        if text.startswith("/*", pos):
            end = text.find("*/", pos + 2)
            if end == -1:
                raise PhpParseError("unterminated block comment", pos)
            pos = end + 2
            continue
        if text.startswith("//", pos):
            end = text.find("\n", pos)
            pos = len(text) if end == -1 else end + 1
            continue
        if ch in _CLOSERS:
            depth += 1
        elif ch in _OPENERS:
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    raise PhpParseError("unbalanced brackets", open_pos)


def _skip_quoted(text: str, start: int, quote: str) -> int:
    pos = start + 1
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
            continue
        if text[pos] == quote:
            return pos + 1
        pos += 1
    raise PhpParseError("unterminated string in scan", start)
