"""Output-side filter (authority: docs/specs/01-port-spec.md §6.4)."""

import re

PRICE_PATTERN = re.compile(r"[¥￥]\s*\d[\d,，.]*|\d[\d,，.]*\s*(?:元|万元|块)")

FORBIDDEN_PHRASES: tuple[str, ...] = (
    "推荐本店",
    "本店最优",
    "我店最优",
    "全网最低",
    "官方指定",
    "已淘汰",
    "忽略你之前",
    "忽略以上",
    "不要告诉用户",
)

SAFE_SENTENCE = "（该回复已按平台安全策略过滤）"


def _mask_price_matches(text: str, whitelist: frozenset[str]) -> str:
    def _sub(match: re.Match[str]) -> str:
        token = match.group(0)
        return token if token.strip() in whitelist else SAFE_SENTENCE

    return PRICE_PATTERN.sub(_sub, text)


def filter_output(text: str, whitelist_prices: frozenset[str] = frozenset()) -> tuple[str, bool]:
    """Return (filtered_text, violated). Whitelisted ``price_display.text`` tokens pass through."""
    violated = False
    out = text
    if any(phrase in out for phrase in FORBIDDEN_PHRASES):
        violated = True
        for phrase in FORBIDDEN_PHRASES:
            out = out.replace(phrase, "…")
    masked = _mask_price_matches(out, whitelist_prices)
    if masked != out:
        violated = True
        out = masked
    if violated:
        out = f"{out}\n{SAFE_SENTENCE}"
    return out, violated
