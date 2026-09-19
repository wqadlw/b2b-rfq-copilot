# 08 · KNOWLEDGE EXPORT SPEC · 知识导出契约

> 密级：公开 · 版本 v1.0 · 2026-09-19 · 上位文档：`01-port-spec.md`（信任分级 §6）。
> 本文定义"站点 seeder → 知识快照"导出产物的机器可读契约：清单（manifest）、内容哈希、差异报告与新鲜度语义。
> 动机（2026-09-19 知识管道研究）：数据停更是无声失败——必须有哈希（增量 diff）、时间戳（保鲜指标）、阈值（过期告警）。

## 1. 导出产物清单（export manifest）

导出脚本落盘 `knowledge.json` 时，**必须**在同目录写入 `export_manifest.json`：

```json
{
  "manifest_version": 1,
  "generated_at": "2026-09-19T12:00:00+00:00",
  "source_dir": "<导出时的站点 seeders 目录（绝对路径）>",
  "document_count": 1234,
  "documents": {
    "<doc_id>": { "title": "…", "content_hash": "<sha256 hex>" }
  }
}
```

- `generated_at`：UTC ISO 8601（`datetime.now(UTC).isoformat()`）。
- `document_count` 必须等于 `documents` 键数，且等于 `knowledge.json` 的 `documents` 数组长度。

## 2. 内容哈希（content_hash）

```
content_hash = sha256( f"{doc_id}\n{title}\n{doc_type}\n{trust_level}\n{content}" ) hex
```

- 哈希覆盖**全部参与检索语义的字段**——任何字段变化都表现为哈希变化。
- 哈希不包含生成时间等非语义字段（重跑未变数据必须得到相同哈希——幂等性是增量 diff 的前提）。

## 3. 差异报告（--diff-from）

`vacuum_b2b_export.py --diff-from <dir>` 读取 `<dir>/export_manifest.json`，与本次构建对比：

| 类别 | 判定 |
|---|---|
| `added` | 新 manifest 有、旧 manifest 无的 doc_id |
| `removed` | 旧有新无 |
| `changed` | 两侧都有但 `content_hash` 不同 |

- 输出 `diff_report.json`（统计 + 各类别样本 doc_id 至多 20 个）写入本次 `--output-dir`；stdout 打印摘要。
- `--diff-from` 是**纯信息性**操作：不改变退出码、不阻断落盘（增量嵌入的执行属后续阶段，见推进计划阶段 3）。
- 旧 manifest 缺失/损坏：报错退出（明确失败优于静默全量误报）。

## 4. 新鲜度（corpus freshness）——Runtime 侧

- 设置：`RAG_STALE_DAYS`（默认 14）。
- `seed_demo` 在 `KNOWLEDGE_DATA_DIR` 非空时计算 `CorpusFreshness`：

| 字段 | 语义 |
|---|---|
| `doc_count` | 文档数（manifest 优先，回退 knowledge.json 解析） |
| `generated_at` | manifest 时间戳；manifest 缺失回退 knowledge.json 文件 mtime |
| `age_days` | (now − generated_at) / 86400；无法取得时间戳则为 None |
| `stale` | `age_days is not None and age_days > RAG_STALE_DAYS` |
| `source` | `"manifest" \| "mtime" \| "missing"` |

- `stale=True` 时启动日志输出 WARN（含年龄与阈值）；**只告警不阻断**——旧知识仍可用，禁答不是运行时的职责。
- `KNOWLEDGE_DATA_DIR` 为空（demo 数据）：freshness 为 None，health 不携带语料字段。

## 5. Health 契约扩展

`GET /api/v1/health` 增加两个可选字段（向后兼容，缺省 None/False）：

```json
{ "status": "ok", "adapter": "demo", "profile": "demo",
  "corpus_age_days": 0.5, "corpus_stale": false }
```

## 6. 验收标准

1. 两次导出同一未变数据源：manifest 中全部 content_hash 相同（幂等）。
2. 单条源数据变化 → diff 恰好报 1 条 changed；新增/删除同理。
3. freshness 三条路径（manifest / mtime / missing）均有单元测试；stale 边界（==阈值不告警，>阈值告警）有测试。
4. health 在离线数据模式下携带语料字段，demo 模式不携带。
