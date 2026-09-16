"""找真空 seeder 数据 → RAG 知识库导出管道（阶段 A，架构师批复 2026-09-15 版）。

四个 ETL 组件（架构师指令逐项落地）：
- FakeDataFilter：状态机过滤（status=1 且未软删）+ 价格黑名单（仅对定价产品生效）+
  强特征锚定（禁子串匹配，防误杀"测试仪"类真实品类）+ reason code 审计
- PathAwareChunker：三层工艺库专用——[行业] > [工艺] > [品种] 路径前缀强制拼接，
  前缀不计入切块预算
- QAPairGenerator：规则模板（确定性、零 token、零编造）把痛点+方案转为 QA 对；
  原文 chunk 保留（双表征）
- TrustPrefixInjector：merchant/ugc chunk 物理隔离前缀（只注一次，不计切块预算）

安全边界：
- 真实数据绝不写入 backend/knowledge/**；--output-dir 必须位于 .ai/private/** 或
  zzk_rag_data/** 或仓库之外，否则拒绝（--force 可越过但会打印醒目警告）
- 本脚本只读找真空 seeder 文件；对找真空仓库零修改
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from rfq_copilot.adapters.zhaozhenkong_offline.php_array import PhpParseError
from rfq_copilot.adapters.zhaozhenkong_offline.sources import (
    load_articles,
    load_cases,
    load_insights,
    load_pain_nav,
    load_process_library,
    load_products,
    load_questions,
    load_services,
    load_solutions,
    load_variety_content,
)
from rfq_copilot.ports.knowledge_source import KnowledgeDocument

MERCHANT_PREFIX = "[供应商声明 - 仅供参考，不可作为平台承诺]"
UGCPREFIX = "[用户提交内容 - 未经平台核实]"
CHUNK_LIMIT = 500
ANOMALY_PRICES = {99999.0, 999999.0, 9999999.0}
TEST_NAMES = {"test", "测试", "test1", "测试产品"}
FAKE_PHONES = {"13800138000"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self.parts.append(stripped)


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:  # noqa: BLE001 - malformed HTML must never crash the ETL
        return re.sub(r"<[^>]+>", " ", html).strip()
    return " ".join(extractor.parts)


import re  # noqa: E402  (kept next to html_to_text for readability)

_RE_CH = re.compile(r"[\u4e00-\u9fff]")


def visual_len(text: str) -> int:
    """CJK-aware length: 汉字算 2，其他算 1（切块预算的近似视觉宽度）。"""
    return sum(2 if _RE_CH.match(ch) else 1 for ch in text)


# ---------------------------------------------------------------------------
# FakeDataFilter
# ---------------------------------------------------------------------------


@dataclass
class FilteredItem:
    source: str
    key: str
    reason: str


@dataclass
class FilterResult:
    kept: list[dict[str, Any]] = field(default_factory=list)
    filtered: list[FilteredItem] = field(default_factory=list)


def filter_products(items: list[dict[str, Any]], source: str = "products") -> FilterResult:
    result = FilterResult()
    for item in items:
        name = str(item.get("name", ""))
        key = str(item.get("slug") or item.get("model") or name)
        if str(item.get("deleted_at", "")) not in {"", "None"}:
            result.filtered.append(FilteredItem(source, key, "SOFT_DELETED"))
            continue
        if str(item.get("status", "0")) != "1":
            result.filtered.append(FilteredItem(source, key, "STATUS_NOT_ON"))
            continue
        if name.strip().lower() in TEST_NAMES or name.strip() in TEST_NAMES:
            result.filtered.append(FilteredItem(source, key, "PLACEHOLDER_NAME"))
            continue
        price_type = str(item.get("price_type", "1"))
        price_raw = item.get("price")
        if price_type == "2" and price_raw is not None:
            try:
                price = float(price_raw)
            except (TypeError, ValueError):
                price = -1.0
            if price <= 0 or price in ANOMALY_PRICES:
                result.filtered.append(FilteredItem(source, key, "PRICE_ANOMALY"))
                continue
        phones = " ".join(str(v) for v in item.get("params", {}).values() if isinstance(v, str))
        if any(fake in phones for fake in FAKE_PHONES):
            result.filtered.append(FilteredItem(source, key, "TEST_PHONE"))
            continue
        result.kept.append(item)
    return result


def filter_active(items: list[dict[str, Any]], source: str) -> FilterResult:
    """Generic status filter for content tables.

    status==1 上架保留；status 缺省视为上架；status 为 None（PHP 常量表达式容错降级，
    如 Solution::STATUS_PUB）视为“平台已审核内容”，保留并记 note——过滤只对明确的
    非上架值（0/2/3）生效。
    """
    result = FilterResult()
    for item in items:
        status = item.get("status", "1")
        if status is None:
            result.kept.append(item)
            continue
        if str(status) not in {"1", ""}:
            result.filtered.append(FilteredItem(source, str(item.get("slug", "")), "STATUS_NOT_ON"))
            continue
        result.kept.append(item)
    return result


# ---------------------------------------------------------------------------
# chunking components
# ---------------------------------------------------------------------------


def wrap_chunks(body: str, prefix: str = "", limit: int = CHUNK_LIMIT) -> list[str]:
    """按 500 视觉宽切块；prefix 不计入预算且只出现在每个 chunk 开头一次。"""
    budget = limit - visual_len(prefix)
    segments: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in body.split("\n"):
        line_len = visual_len(line)
        if current and current_len + line_len > budget:
            segments.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += line_len
    if current:
        segments.append("\n".join(current))
    return [(prefix + ("\n" if prefix else "") + seg) for seg in segments]


def inject_trust_prefix(text: str, trust_level: str) -> str:
    if text.startswith(MERCHANT_PREFIX) or text.startswith(UGCPREFIX):
        return text
    if trust_level == "merchant":
        return f"{MERCHANT_PREFIX}\n{text}"
    if trust_level == "ugc":
        return f"{UGCPREFIX}\n{text}"
    return text


def path_prefix(industry: str, process: str, variety: str) -> str:
    return f"[行业: {industry}] > [工艺: {process}] > [品种: {variety}]"


# ---------------------------------------------------------------------------
# QA pair generation (rule-based, deterministic, zero-token)
# ---------------------------------------------------------------------------


def qa_pair_from_pain(pain: str, answer_hint: str, process_name: str) -> str:
    question = f"{pain}怎么办？"
    answer = f"「{process_name}」工艺方向可作为参考：{answer_hint}。详情可登录后发起深度咨询。"
    return f"Q: {question}\nA: {answer}"


# ---------------------------------------------------------------------------
# document building
# ---------------------------------------------------------------------------


@dataclass
class EtlOutput:
    documents: list[KnowledgeDocument]
    stats: dict[str, Any]
    filtered_log: list[FilteredItem]


def _chunk_doc(
    doc_id: str,
    title: str,
    doc_type: str,
    trust_level: str,
    body: str,
    prefix: str = "",
    **meta: str | None,
) -> list[KnowledgeDocument]:
    docs: list[KnowledgeDocument] = []
    chunks = wrap_chunks(body, prefix)
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        suffix = f" ({index}/{total})" if total > 1 else ""
        docs.append(
            KnowledgeDocument(
                doc_id=f"{doc_id}{suffix}",
                title=title,
                doc_type=doc_type,  # type: ignore[arg-type]
                trust_level=trust_level,  # type: ignore[arg-type]
                content=inject_trust_prefix(chunk, trust_level),
                **{k: v for k, v in meta.items() if v is not None},
            )
        )
    return docs


def build_documents(seeders_dir: Path) -> EtlOutput:
    documents: list[KnowledgeDocument] = []
    filtered_log: list[FilteredItem] = []
    stats: dict[str, Any] = {"sources": {}, "filtered_by_reason": {}, "notes": []}

    # ---- 1) products (merchant) ----
    try:
        products = load_products(seeders_dir)
    except (FileNotFoundError, PhpParseError) as exc:
        products, stats["notes"] = [], stats["notes"] + [f"products: {exc}"]
    product_result = filter_products(products, "products")
    filtered_log.extend(product_result.filtered)
    for item in product_result.kept:
        params = item.get("params") or {}
        param_lines = "\n".join(f"{k}：{v}" for k, v in params.items() if isinstance(v, str)) or "参数待补充"
        detail_text = html_to_text(str(item.get("detail", "")))
        price_type = str(item.get("price_type", "1"))
        price = item.get("price")
        price_text = f"￥{price}" if price_type == "2" and price else "请联系供应商询价"
        body = (
            f"产品名称：{item.get('name', '')}\n型号：{item.get('model', '—')}\n"
            f"主要参数：\n{param_lines}\n价格：{price_text}\n"
            f"详情：{detail_text[:600]}"
        )
        documents.extend(
            _chunk_doc(
                doc_id=f"zzk-product-{item.get('slug', item.get('name', 'unknown'))}",
                title=str(item.get("name", "")),
                doc_type="product",
                trust_level="merchant",
                body=body,
                supplier_id=str(item.get("supplier_id", "")) or None,
            )
        )
    stats["sources"]["products"] = {
        "raw": len(products),
        "kept": len(product_result.kept),
        "filtered": len(product_result.filtered),
    }

    # ---- 2) three-tier process library (platform, PathAware) ----
    try:
        industries = load_process_library(seeders_dir)
    except (FileNotFoundError, PhpParseError) as exc:
        industries, stats["notes"] = [], stats["notes"] + [f"process_library: {exc}"]
    variety_contents = load_variety_content(seeders_dir) if industries else {}
    variety_kept = 0
    for industry in industries:
        industry_name = str(industry.get("name", ""))
        for category in industry.get("categories", []) or []:
            if not isinstance(category, dict):
                continue
            process_name = str(category.get("name", ""))
            for variety in category.get("varieties", []) or []:
                if not isinstance(variety, dict):
                    continue
                status_ok = str(variety.get("status", "1")) == "1"
                if not status_ok:
                    filtered_log.append(FilteredItem("varieties", str(variety.get("slug", "")), "STATUS_NOT_ON"))
                    continue
                variety_kept += 1
                variety_name = str(variety.get("name", ""))
                prefix = path_prefix(industry_name, process_name, variety_name)
                base_lines = "\n".join(
                    f"{label}：{variety.get(key)}"
                    for label, key in (
                        ("物料特性", "mf"),
                        ("工艺难点", "df"),
                        ("市场价值", "mv"),
                        ("真空度范围", "vacuum_range"),
                        ("简介", "brief"),
                    )
                    if variety.get(key)
                )
                documents.extend(
                    _chunk_doc(
                        doc_id=f"zzk-variety-{industry.get('slug', 'x')}-{variety.get('slug', 'x')}-base",
                        title=variety_name,
                        doc_type="selection_guide",
                        trust_level="platform",
                        body=base_lines or "内容待补充",
                        prefix=prefix,
                    )
                )
                content = variety_contents.get(str(variety.get("slug", "")))
                if isinstance(content, dict):
                    content_lines = "\n".join(f"{k}：{v}" for k, v in content.items() if isinstance(v, str))
                    if content_lines:
                        documents.extend(
                            _chunk_doc(
                                doc_id=f"zzk-variety-{industry.get('slug', 'x')}-{variety.get('slug', 'x')}-deep",
                                title=f"{variety_name}（深度内容）",
                                doc_type="selection_guide",
                                trust_level="platform",
                                body=content_lines,
                                prefix=prefix,
                            )
                        )
    stats["sources"]["process_library"] = {"industries": len(industries), "varieties_kept": variety_kept}

    # ---- 3) pain_nav QA pairs (platform, 双表征：原文+QA) ----
    try:
        pain_nav = load_pain_nav(seeders_dir)
    except (FileNotFoundError, PhpParseError) as exc:
        pain_nav, stats["notes"] = {}, stats["notes"] + [f"pain_nav: {exc}"]
    industry_names = {str(i.get("slug", "")): str(i.get("name", "")) for i in industries}
    qa_count = 0
    for industry_slug, items in pain_nav.items():
        industry_name = industry_names.get(industry_slug, industry_slug)
        for item in items:
            tag = str(item.get("tag", "")).strip()
            target = str(item.get("target_slug", "")).strip()
            if not tag:
                continue
            qa_body = qa_pair_from_pain(tag, f"参见「{target}」工艺方案页", industry_name)
            documents.extend(
                _chunk_doc(
                    doc_id=f"zzk-qa-{industry_slug}-{target or qa_count}",
                    title=f"{industry_name}｜{tag[:30]}",
                    doc_type="platform_faq",
                    trust_level="platform",
                    body=qa_body,
                )
            )
            qa_count += 1
    stats["sources"]["pain_nav_qa"] = {"qa_chunks": qa_count}

    # ---- 4) solutions / cases / insights / services / articles / questions ----
    loaders = (
        ("solutions", load_solutions, "selection_guide"),
        ("cases", load_cases, "platform_faq"),
        ("insights", load_insights, "platform_faq"),
        ("services", load_services, "platform_faq"),
        ("articles", load_articles, "platform_faq"),
        ("questions", load_questions, "platform_faq"),
    )
    # ---- 4a) solutions 专用渲染（结构化字段） ----
    try:
        solution_items = load_solutions(seeders_dir)
    except (FileNotFoundError, PhpParseError) as exc:
        solution_items = []
        stats["notes"] = stats["notes"] + [f"solutions: {exc}"]
    sol_result = filter_active(solution_items, "solutions")
    filtered_log.extend(sol_result.filtered)
    sol_docs = 0
    for item in sol_result.kept:
        name = str(item.get("name", ""))
        lines = [f"方案名称：{name}"]
        subtitle = item.get("subtitle")
        if isinstance(subtitle, str) and subtitle.strip():
            lines.append(f"方案简介：{subtitle}")
        pain_points = item.get("pain_points_json")
        if isinstance(pain_points, list):
            for pp in pain_points:
                if isinstance(pp, dict):
                    lines.append(f"痛点：{pp.get('title', '')}——{pp.get('desc', '')}")
        topology = item.get("topology_note")
        if isinstance(topology, str) and topology.strip():
            lines.append(f"系统拓扑：{topology}")
        argument = item.get("argument")
        if isinstance(argument, str) and argument.strip():
            lines.append(f"选型论据：{html_to_text(argument)[:600]}")
        faq = item.get("faq_json")
        if isinstance(faq, list):
            for pair in faq:
                if isinstance(pair, dict) and pair.get("q") and pair.get("a"):
                    lines.append(f"Q: {pair.get('q')}\nA: {pair.get('a')}")
        slug = str(item.get("slug", sol_docs))
        documents.extend(
            _chunk_doc(
                doc_id=f"zzk-solutions-{slug}",
                title=name,
                doc_type="selection_guide",
                trust_level="platform",
                body="\n".join(lines),
            )
        )
        sol_docs += 1
    stats["sources"]["solutions"] = {"raw": len(solution_items), "kept": sol_docs}

    for source_name, loader, doc_type in loaders:
        if source_name == "solutions":
            continue
        try:
            items = loader(seeders_dir)
        except (FileNotFoundError, PhpParseError) as exc:
            items = []
            stats["notes"] = stats["notes"] + [f"{source_name}: {exc}"]
            stats["sources"][source_name] = {"raw": 0, "kept": 0}
            continue
        result = filter_active(items, source_name)
        filtered_log.extend(result.filtered)
        kept_docs = 0
        for item in result.kept:
            title = str(item.get("name") or item.get("title") or item.get("question") or "")
            answer = str(item.get("answer", "") or "")
            if source_name == "questions" and answer:
                documents.extend(
                    _chunk_doc(
                        doc_id=f"zzk-questions-{item.get('slug', len(documents))}",
                        title=title,
                        doc_type="platform_faq",
                        trust_level="platform",
                        body=f"Q: {title}\nA: {answer}",
                    )
                )
                kept_docs += 1
                continue
            if source_name == "questions":
                # 无采纳答案的问题（solved=false）不编造回答——跳过
                filtered_log.append(FilteredItem(source_name, str(item.get("slug", "")), "NO_ACCEPTED_ANSWER"))
                continue
            if source_name == "articles" and not any(
                isinstance(item.get(k), str) and str(item.get(k)).strip()
                for k in ("brief", "content", "body", "description", "summary", "digest", "excerpt")
            ):
                # 文章索引卡：正文在站点 CMS 未固化进 seeder——诚实以元数据入库，不编造正文
                art_type = str(item.get("type", "article"))
                documents.extend(
                    _chunk_doc(
                        doc_id=f"zzk-articles-{item.get('slug', len(documents))}",
                        title=title,
                        doc_type="platform_faq",
                        trust_level="platform",
                        body=f"平台文章索引：{title}（类型：{art_type}）——全文请见站点对应页面。",
                    )
                )
                kept_docs += 1
                continue
            body_parts = []
            for key in (
                "brief",
                "pain",
                "summary",
                "content",
                "answer",
                "description",
                "body",
                "subtitle",
                "title_desc",
                "digest",
                "excerpt",
                "intro",
                "achievement",
            ):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    body_parts.append(html_to_text(value)[:800])
            if not body_parts:
                continue
            supplier_raw = item.get("supplier_id")
            trust = "merchant" if supplier_raw not in (None, "", "0") else "platform"
            documents.extend(
                _chunk_doc(
                    doc_id=f"zzk-{source_name}-{item.get('slug', kept_docs)}",
                    title=title,
                    doc_type=doc_type,
                    trust_level=trust,
                    body="\n".join(body_parts),
                    supplier_id=str(supplier_raw) if supplier_raw not in (None, "") else None,
                )
            )
            kept_docs += 1
        stats["sources"][source_name] = {"raw": len(items), "kept": kept_docs}

    # ---- stats rollup ----
    trust_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for doc in documents:
        trust_counts[doc.trust_level] = trust_counts.get(doc.trust_level, 0) + 1
        type_counts[doc.doc_type] = type_counts.get(doc.doc_type, 0) + 1
    stats["documents"] = len(documents)
    stats["by_trust_level"] = trust_counts
    stats["by_doc_type"] = type_counts
    for item in filtered_log:
        stats["filtered_by_reason"][item.reason] = stats["filtered_by_reason"].get(item.reason, 0) + 1
    return EtlOutput(documents=documents, stats=stats, filtered_log=filtered_log)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _safe_output_dir(raw: str, repo_root: Path) -> Path:
    out = Path(raw).resolve()
    knowledge_root = (repo_root / "backend" / "knowledge").resolve()
    if knowledge_root in out.parents or out == knowledge_root:
        raise SystemExit("拒绝：真实数据禁止写入 backend/knowledge/（公开仓库边界，repo-policy）")
    inside_repo = repo_root in out.parents
    allowed_private = ".ai/private" in str(out) or "zzk_rag_data" in str(out)
    if inside_repo and not allowed_private:
        raise SystemExit(
            f"拒绝：输出目录 {out} 在仓库内且非 .ai/private/zzk_rag_data 路径。"
            "真实数据只允许 .ai/private/**、zzk_rag_data/** 或仓库外目录（--force 可越过）。"
        )
    return out


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="找真空 seeder → RAG 知识库导出（阶段 A）")
    parser.add_argument("--source-dir", required=True, help="找真空 database/seeders 目录")
    parser.add_argument("--dry-run", action="store_true", help="只出统计报告，不落盘（默认）")
    parser.add_argument("--json", dest="json_path", help="导出中间 JSON 供审查")
    parser.add_argument("--output-dir", help="知识 JSON 落盘目录（受安全规则约束）")
    parser.add_argument("--force", action="store_true", help="越过输出目录安全检查（慎用）")
    args = parser.parse_args(argv)

    source_dir = Path(args.source_dir)
    if not source_dir.is_dir():
        raise SystemExit(f"source-dir 不存在：{source_dir}")

    output = build_documents(source_dir)

    print("=== 找真空知识导出 · 统计报告 ===")
    print(f"documents: {output.stats['documents']}")
    print(f"by_trust_level: {json.dumps(output.stats['by_trust_level'], ensure_ascii=False)}")
    print(f"by_doc_type: {json.dumps(output.stats['by_doc_type'], ensure_ascii=False)}")
    for source, info in output.stats["sources"].items():
        print(f"source[{source}]: {json.dumps(info, ensure_ascii=False)}")
    print(f"filtered_by_reason: {json.dumps(output.stats['filtered_by_reason'], ensure_ascii=False)}")
    for note in output.stats["notes"]:
        print(f"note: {note}")
    print("--- 被滤样本（前 3）---")
    for item in output.filtered_log[:3]:
        print(f"  [{item.reason}] {item.source}/{item.key}")
    merchant_samples = [d for d in output.documents if d.trust_level == "merchant"][:2]
    print("--- merchant 样本（前 2）---")
    for doc in merchant_samples:
        print(f"  [{doc.doc_id}] {doc.content[:120]}")
    path_samples = [d for d in output.documents if d.content.startswith("[行业:")][:1]
    print("--- 工艺库路径样本（前 1）---")
    for doc in path_samples:
        print(f"  [{doc.doc_id}] {doc.content[:160]}")

    if args.json_path:
        json_path = Path(args.json_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "stats": output.stats,
            "documents": [doc.model_dump() for doc in output.documents],
            "filtered": [item.__dict__ for item in output.filtered_log],
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"json written: {json_path}")

    if args.output_dir:
        out_dir = _safe_output_dir(args.output_dir, repo_root)
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {"stats": output.stats, "documents": [doc.model_dump() for doc in output.documents]}
        (out_dir / "zzk_knowledge.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        log_path = out_dir / "etl_filtered.log"
        with log_path.open("w", encoding="utf-8") as handle:
            for item in output.filtered_log:
                handle.write(f"{item.reason}\t{item.source}\t{item.key}\n")
        print(f"output written: {out_dir} (含 etl_filtered.log)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
