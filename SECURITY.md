# 安全、隐私与服务条款 | Security, privacy and service terms

适用于 **Antigravity 本地账号切换器 / Antigravity Local Switcher**。这是独立的非官方 Windows 工具，不是 Google 产品或获批集成。

## 本地运行与隐私（中文）

本版本不包含后门、隐蔽上传、遥测或远程控制功能。没有作者服务器，不向作者或其他第三方发送登录凭据、账号快照、项目文件、聊天记录。账号管理在本机完成；快照、恢复备份和额度缓存使用 Windows 当前用户 DPAPI 加密，存于 `%LOCALAPPDATA%\AntigravityLocalSwitcher`。卸载保留这些本机数据。

界面仅监听 `127.0.0.1`，网页不会接收 access token 或 refresh token。修改操作核对 Host、Origin、HttpOnly / SameSite Cookie 和随机控制令牌。没有远程字体、CDN、广告、分析上报、自动下载执行代码或模型请求反代。

**本地运行不等于完全离线。** 确认新账号身份、查询额度及刷新授权时，必要令牌只发送到固定允许的 Google HTTPS 接口，保留证书校验并拒绝重定向。“无上传”指没有隐蔽收集和向作者/第三方上传数据，不是说 Google 身份验证无需联网。

允许的服务域名：`www.googleapis.com`（身份确认）、`oauth2.googleapis.com`（刷新授权）、`cloudcode-pa.googleapis.com`、`daily-cloudcode-pa.googleapis.com`、`daily-cloudcode-pa.sandbox.googleapis.com`（额度）。系统配置的网络代理仍属于用户的网络信任边界。

OAuth 桌面客户端配置从本机官方 Antigravity 安装中读取；源码与分发包不内置客户端 ID 或密钥，也不包含用户登录授权。仅兼容指纹匹配时使用，未知版本停止刷新。扫描只读取 `gemini:antigravity` 这一条凭据，不枚举浏览器或其他 Windows 登录；用户确认命名后才入库，保存前再次检查当前登录。

**安全边界：** 以上是本版本实现说明，不是独立安全认证，也不是绝对安全保证。具有同一 Windows 用户权限的恶意软件仍可能访问凭据或调用 DPAPI。请从本仓库获取程序，不公开账号文件、原始接口数据、未脱敏日志或截图。

## Google 服务条款（中文）

2026-10-08 核对的 [官方附加条款](https://antigravity.google/terms) 第 6 条禁止第三方工具访问服务，可能导致 Antigravity / Gemini CLI 账号暂停或终止。本工具的内部额度查询和 OAuth 刷新存在该风险；仅恢复本地登录快照是否允许没有单独澄清。串行查询、低频、加密和开源均不代表 Google 授权。企业订阅可能适用其他协议。

安全问题请优先使用已启用的 GitHub 私密漏洞报告；否则先提交不含凭据和实际账号利用信息的描述。

---

# Security and service terms (English)

This is an independent Windows utility, not a Google product or an approved Antigravity integration.

## Local execution and privacy

Account management and credential storage run locally. This version contains no backdoor, covert upload, telemetry or remote-control functionality. There is no author-operated server, and credentials, snapshots, project files and chat histories are not uploaded to the author or other third parties.

Identity verification, quota queries and OAuth refresh connect directly to allowlisted Google HTTPS endpoints and send the tokens required by those protocols. Local execution does not mean offline operation. "No uploads" refers to the absence of covert collection and transfers to the author or third parties, not the absence of Google authentication requests. There are no ads, remote fonts/CDNs, automatic code-download execution, or model-request proxies.

These are implementation statements, not an independent security certification or an absolute guarantee. Review the source, obtain builds from this repository, and protect the Windows account. Software running as the same Windows user can still access the vault or DPAPI; service-terms risks remain separate.

## Google service terms

The [Google Antigravity Additional Terms of Service](https://antigravity.google/terms), checked on 2026-10-08, clause 6, prohibit using third-party software, tools or services to access the Service and state that this may lead to Antigravity and/or Gemini CLI account suspension or termination. Enterprise subscriptions may be governed by different applicable agreements.

This application directly calls Antigravity internal quota endpoints and refreshes OAuth grants. Those functions carry a material service-terms risk even without proxying model requests. The terms do not separately clarify whether restoring local login snapshots is permitted. Open source publication and this MIT license do not grant permission from Google or override its terms. This repository makes no claim of being compliant or safe from enforcement. It does not provide a model-request proxy or alter device identifiers to evade enforcement.

## Credential boundary

- The current Windows credential target is `gemini:antigravity`. Scanning reads that current login; it does not enumerate all browser accounts or other Windows credentials.
- For an unmatched login, scanning uses the existing access token with Google's user-info endpoint to confirm email/subject, with token refresh when necessary. Scan candidates remain in backend memory until the user names and confirms enrollment. The current login is checked again before saving.
- Exact refresh-grant matches or previously verified Google subject metadata prevent duplicate enrollment. Older snapshots without subject metadata primarily match by their refresh grant. Independently reauthorizing an older account with a new grant can require manual review/update.
- Persistent account snapshots, recovery snapshots and quota cache files use Windows DPAPI for the current Windows user. The browser UI receives safe account/scan status and quota projections, never access tokens or refresh tokens.
- Same-user malware can still read the Windows vault or invoke DPAPI. Encryption is not isolation from software running as the same user.
- The runtime directory is `%LOCALAPPDATA%\AntigravityLocalSwitcher`, separate from this repository and the installation directory. Do not publish it. Uninstall leaves this directory in place.
- OAuth refresh reads the compatible desktop client configuration from the locally installed official Antigravity binary. No client ID or client secret is embedded in the source or release. A SHA-256 compatibility fingerprint selects the verified pair when multiple clients are present; unrecognized versions stop refresh. This installed-client configuration is not a user's Google access/refresh token and does not independently grant account access. No additional scopes are requested.

## Network and local control

Google requests use a fixed HTTPS endpoint allowlist and reject redirects. Quota requests share a serialized rate limiter. Account refreshes are sequential, and HTTP 429 pauses the batch and preserves a cooldown. These are ordinary load controls, not a guarantee about Google's detection or policy enforcement.

The local web server binds only to `127.0.0.1`. State-changing requests validate Host, Origin, an HttpOnly SameSite cookie and a random control token. Credentials do not cross the local browser boundary. The application does not use remote fonts, analytics, CDNs or a vendor-operated credential service.

## Reporting issues

Do not attach account snapshots, recovery files, OAuth grants, raw provider traffic, unredacted logs or personal screenshots to public issues. Use synthetic examples. For a security issue, use GitHub's private vulnerability reporting if enabled; otherwise describe the issue without disclosing credentials or a live exploit against an account.
