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
   生产部署必须显式配置宿主站点源（如 `https://zhaozhenkong.com,https://www.zhaozhenkong.com`）。
3. **本机开发豁免**：无论是否配置白名单，`http(s)://(localhost|127.0.0.1)(:port)?` 恒放行
   （widget 本机联调必需；不构成生产暴露面）。
4. 未配置白名单 + 非本机源 = 拒绝跨域（默认拒绝）。

## 后果

- 部署清单新增一项：生产 env 必须设置 `CORS_ALLOW_ORIGINS`（已同步 .env.example）。
- 嵌入方的源必须登记，新增宿主站点 = 改配置，无需改码。
