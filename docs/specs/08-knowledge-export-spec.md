# 08 · KNOWLEDGE EXPORT SPEC · 知识导出契约

> 密级：公开 · 版本 v1.1 · 2026-09-20 · 上位文档：`01-port-spec.md`（信任分级 §6）。
> 本文定义"站点 seeder → 知识快照"导出产物的机器可读契约：清单（manifest）、内容哈希、差异报告与新鲜度语义。
> 动机（2026-09-19 知识管道研究）：数据停更是无声失败——必须有哈希（增量 diff）、时间戳（保鲜指标）、阈值（过期告警）。
> v1.1 变更：新增 §6 引擎内置每日兜底刷新（热加载免重启）；验收标准顺移 §7。

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

## 6. 引擎内置每日兜底刷新（2026-09-20 新增，热加载免重启）

数据停更是无声失败；webhook 覆盖运行期实时增量，本节定义**防事件丢失的定时兜底通道**。

### 6.1 触发与门禁

| 设置 | 默认 | 语义 |
|---|---|---|
| `KNOWLEDGE_REFRESH_ENABLED` | `false` | 总开关（显式 opt-in；测试/CI 不启用） |
| `KNOWLEDGE_SOURCE_DIR` | 空 | 站点 `database/seeders` 目录；**缺失则禁用并 WARN**（半配置不静默、不崩溃） |
| `KNOWLEDGE_REFRESH_INTERVAL_HOURS` | `24` | 刷新间隔；启动后 60s 宽限先跑一轮（兜住停机期间的变化），此后按间隔循环 |

### 6.2 流程（复用 §1~§3 契约，单事实源）

1. 重导出到临时目录（`--diff-from` 现网目录）；
2. `diff_manifests(old_manifest, new_manifest)` 取 **doc_id 全量**三类差异（不走 samples 截断）；
3. 无变化 → 丢弃临时目录，报 unchanged；有变化 → 原子替换现网目录三件套
   （knowledge.json / export_manifest.json / etl_filtered.log）。

### 6.3 热加载（免重启，对齐 webhook 同一族替换语义）

- **RAG store 差量补丁**：removed/changed → `remove_doc(doc_id)`（家族语义，QA-0002 立的
  替换规矩）；added/changed → `chunk_document` + `ingest`。与 POST /api/v1/knowledge 走同一条
  remove→ingest 路径，不得另造第二套语义。
- **离线端口重建**：`OfflineProductCatalog`/`OfflineSupplierDirectory`/`OfflineCaseDirectory`/
  `OfflineSolutionDirectory` 构造时一次性装载——刷新后必须重建并热换
  `deps.catalog/suppliers/cases/solutions`（GraphDeps 节点每次调用读取字段，热换安全）。
- **freshness 重算**：`corpus_freshness` 按新 manifest 重新加载。

### 6.4 可观测

- `runtime.last_refresh` 落 `/api/v1/health` 的 `knowledge_refresh` 字段（向后兼容，缺省 None）：
  `{enabled, last_run_at, refreshed, added, removed, changed, error}`。
- 任何一轮失败：结构化 WARN + 计入 last_refresh.error，**循环继续**（下一轮自愈）。

### 6.5 CLI 手工通道

`scripts/daily_knowledge_refresh.py` 保留为人工触发入口，实现为 §6.2 核心的薄壳（共用单一实现）。

## 7. 验收标准

1. 两次导出同一未变数据源：manifest 中全部 content_hash 相同（幂等）。
2. 单条源数据变化 → diff 恰好报 1 条 changed；新增/删除同理。
3. freshness 三条路径（manifest / mtime / missing）均有单元测试；stale 边界（==阈值不告警，>阈值告警）有测试。
4. health 在离线数据模式下携带语料字段，demo 模式不携带。
5. 刷新核心（§6.2）：无变化轮不触碰现网目录（幂等）；有变化轮 diff 恰好覆盖全部 doc_id。
6. 热加载（§6.3）：刷新后**无需重启**——检索立即可见新增/变更文档、已删文档不再命中；离线端口数据同步更新。
7. 门禁（§6.1）：开关关闭 / 源目录缺失时调度器不启动；一轮异常不影响后续轮次。
