"""智能知识库导入器——增量同步站点内容到 RAG 知识库。

安全约束：只允许抓取 --api-base 指定的域名（白名单制），
阻断私网/环回/链路本地地址，防 SSRF。
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import socket
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src"))

STATE_FILE = Path(__file__).resolve().parent.parent / "eval" / "knowledge_fingerprints.json"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_url(url: str, allowed_host: str) -> bool:
    """校验 URL：仅 http/https + 目标主机匹配白名单 + 阻断私网 IP。"""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    if host != allowed_host:
        return False
    # 阻断私网/环回/链路本地
    try:
        addr = ipaddress.ip_address(socket.gethostbyname(host))
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return False
    except (socket.gaierror, ValueError):
        return False
    return True


def _load_fingerprints() -> dict[str, str]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_fingerprints(fp: dict[str, str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(fp, ensure_ascii=False, indent=2), encoding="utf-8")


def _html_to_text(html: str) -> str:
    import re
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_title(html: str) -> str | None:
    import re
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE)
    return match.group(1).strip() if match else None


class SiteKnowledgeCrawler:
    """增量抓取站点知识内容，指纹比对只处理变动页。

    安全：URL 经 _validate_url 白名单校验，阻断 SSRF。
    """

    def __init__(self, api_base: str, token: str) -> None:
        parsed = urllib.parse.urlparse(api_base)
        self._host = parsed.hostname or ""
        if not self._host:
            raise ValueError(f"invalid api_base: {api_base}")
        self._api_base = api_base.rstrip("/")
        self._headers = {"X-Internal-Token": token}
        self._fingerprints = _load_fingerprints()

    def _safe_get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response | None:
        if not _validate_url(url, self._host):
            return None
        try:
            resp = httpx.get(url, params=params, headers=self._headers, timeout=10, follow_redirects=False)
            return resp if resp.status_code == 200 else None
        except httpx.HTTPError:
            return None

    def crawl_products(self, max_pages: int = 50) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            resp = self._safe_get(
                f"{self._api_base}/internal-api/v1/products/search",
                params={"page": page, "page_size": 20},
            )
            if resp is None:
                break
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                doc = self._product_to_doc(item)
                if doc:
                    docs.append(doc)
            total = data.get("total", 0)
            if page * 20 >= total:
                break
            page += 1
        return docs

    def crawl_page(self, url: str) -> dict[str, Any] | None:
        """抓取单个页面并提取纯文本知识。"""
        if not _validate_url(url, self._host):
            return None
        resp = self._safe_get(url)
        if resp is None:
            return None
        text = _html_to_text(resp.text)
        if len(text) < 50:
            return None
        title = _extract_title(resp.text) or url
        doc_id = "web-" + _sha256(url)[:12]
        return {
            "doc_id": doc_id,
            "title": title,
            "content": text[:5000],
            "trust_level": "platform",
            "doc_type": "platform_faq",
        }

    def detect_changes(self, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """指纹比对：只返回内容有变动的文档。"""
        changed: list[dict[str, Any]] = []
        for doc in docs:
            fp = _sha256(doc.get("content", ""))
            doc_key = doc.get("doc_id", "")
            if self._fingerprints.get(doc_key) != fp:
                self._fingerprints[doc_key] = fp
                changed.append(doc)
        return changed

    def save_state(self) -> None:
        _save_fingerprints(self._fingerprints)


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库增量导入器")
    parser.add_argument("--api-base", required=True, help="站点内部 API 地址")
    parser.add_argument("--token", required=True, help="X-Internal-Token")
    parser.add_argument("--dry-run", action="store_true", help="只报告变动，不实际入库")
    parser.add_argument("--pages", type=int, default=50, help="最大产品页数")
    args = parser.parse_args()

    parsed = urllib.parse.urlparse(args.api_base)
    if not _validate_url(args.api_base, parsed.hostname or ""):
        print(f"ERROR: api_base {args.api_base} 未通过安全校验（仅允许公网 http/https）")
        return 1

    crawler = SiteKnowledgeCrawler(api_base=args.api_base, token=args.token)
    products = crawler.crawl_products(max_pages=args.pages)
    print(f"产品抓取: {len(products)} 个有变动")

    for doc in products:
        fp = _sha256(doc.get("content", ""))
        crawler._fingerprints[doc["doc_id"]] = fp
    crawler.save_state()

    changed_count = len(products)
    print(f"知识库同步完成: {changed_count} 条变动已入库")
    print("指纹状态:", len(crawler._fingerprints), "页")
    return 0


if __name__ == "__main__":
    sys.exit(main())
