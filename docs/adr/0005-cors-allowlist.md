# ADR-0005 · CORS 收紧：永不通配 + 凭证，显式白名单 + 本机开发豁免

- 状态：Accepted（2026-09-18）
- 关联：QA-0001（P0）· DEEP-DIVE-security-architecture
- 决策人：人类授权执行席（Hy4）落地，QA 席复验

## 背景

`app/main.py` CORS 配置为 `allow_origin_regex=r"https?://.*"` + `allow_credentials=True`：
任意互联网页面都可携凭证跨域调用引擎 API。叠加 E1 票据机制，恶意嵌入页可诱导已登录
用户的浏览器携带身份调用引擎（CSRF/票据盗用面）。

## 决策

1. **永不通配源 + 凭证**：删除 `https?://.*` 正则。
2. **生产白名单**：新增 `Settings.cors_allow_origins`（逗号分隔，env `CORS_ALLOW_ORIGINS`），
   生产部署必须显式配置宿主站点源（如 `https://your-domain.com,https://www.your-domain.com`）。
3. **本机开发豁免**：无论是否配置白名单，`http(s)://(localhost|127.0.0.1)(:port)?` 恒放行
   （widget 本机联调必需；不构成生产暴露面）。
4. 未配置白名单 + 非本机源 = 拒绝跨域（默认拒绝）。

## 后果

- 部署清单新增一项：生产 env 必须设置 `CORS_ALLOW_ORIGINS`（已同步 .env.example）。
- 嵌入方的源必须登记，新增宿主站点 = 改配置，无需改码。

## 收紧补充（2026-09-20，同 ADR 延伸）

源白名单落地后复查发现方法/头/暴露头仍为通配，按最小权限原则补齐：

1. **方法收敛**：`allow_methods` 从 `["*"]` 收敛为 `["GET", "POST"]`——浏览器侧 widget
   只调 `GET /ui-config`、`POST /sessions|chat/stream|feedback`；`DELETE /knowledge` 等
   内部端点走 X-Internal-Token 的服务器间调用，不经浏览器 CORS，无需放行预检。
2. **请求头收敛**：`allow_headers` 从 `["*"]` 收敛为 `["Content-Type"]`——
   `application/json` 请求体是唯一触发预检的非简单头；`Accept` 等简单头无需登记。
   副作用收益：携带 `X-Internal-Token` 的浏览器预检会被直接拒绝，
   内部端点对浏览器侧双保险（401 + 预检拒绝）。
3. **暴露头收敛**：删除 `expose_headers=["*"]`——SSE 事件从响应流解析，
   前端不读取任何自定义响应头。
4. **凭证关闭**：`allow_credentials` 从 `True` 改为 `False`——鉴权走请求体
   `ai_ticket`（E1 票据桥），不依赖 cookies；关闭后 `Access-Control-Allow-Credentials`
   不再下发，配合源白名单彻底关死"诱导已登录浏览器携凭证跨域调用"的攻击面。
5. **预检缓存**：新增 `max_age=600`——预检结果缓存 10 分钟，省去 SSE 每次连接的
   OPTIONS 往返；短窗口保证白名单变更快速生效。

回归测试：`backend/tests/api/test_cors_policy.py`（源白名单语义不变 + 预检方法/头/凭证断言）。
