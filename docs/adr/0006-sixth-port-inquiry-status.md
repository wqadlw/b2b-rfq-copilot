# ADR-0006 · 第 6 端口 InquiryStatusPort 正式纳管（修订"封顶 5"）

- 状态：Accepted（2026-09-18）
- 关联：QA-0005 · ADR-0002（端口与能力清单）· ADR-0004（"封顶 5" 出处）
- 决策人：人类授权执行席（Hy4）落地，QA 席复验

## 背景

QA-0005：`ports/inquiry_status.py` 已实现并被 `app/runtime.py` 接线（阶段三·三，
询盘状态查询：session_id 即游客凭证查本会话询盘进展），但未在 `ports/__init__`
导出、无 Schema 契约登记，违反 ADR-0004 的"引擎端口封顶 5"约束且处于无主状态。

## 决策

**纳管，不撤销**。理由：
1. 端口有真实业务消费方（状态查询流 `status_flow`，agent takeover 场景依赖）；
2. 职责与既有 5 端口正交（只读状态查询，无写路径）；
3. 撤销等于砍功能，收益仅为教条式守约。

具体动作：
- `ports/__init__.py` 导出 `InquiryStatusPort`，`__all__` 对齐；
- ADR-0004 的"封顶 5" 修订为"封顶 6，新增端口须 ADR"；
- 端口 docstring 补纳管记录。

## 后果

- 新增第 7 个端口必须走 ADR + 人类批准（本 ADR 确立该流程先例）。
