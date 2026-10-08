# 安全、隐私与服务条款 | Security, privacy and service terms

适用于 Antigravity 本地账号切换器 / Antigravity Local Switcher **0.8.0**。独立非官方工具，不代表 Google。

## 中文：本地与联网边界

账号管理、快照和额度缓存使用 Windows 当前用户 DPAPI 加密，保存在 `%LOCALAPPDATA%\AntigravityLocalSwitcher`。本版本没有后门、隐蔽上传、遥测、远程控制、作者服务器、远程字体、CDN、广告或自动下载执行代码。不把凭据、快照、项目或聊天内容上传给作者或第三方。

界面仅连接本机 `127.0.0.1`，不接收 access token / refresh token。修改操作校验 Host、Origin、HttpOnly / SameSite 会话 Cookie 和随机控制令牌。

**仅当前运行的官方 Antigravity 登录账号允许身份和额度查询。** 离线账号、客户端关闭时、未匹配登录不发起额度请求。手动、定时、恢复到期与切换对齐共享此规则。每次限频等待后重读凭据与进程状态，换号或关闭后停止后续请求；已发出的请求无法撤回，返回时换号的结果不保存。

当前版本的应用流程不调用 OAuth 刷新接口，不用离线 refresh token 维持授权，不写入自行生成的新令牌。令牌续期交给官方客户端；工具读取官方更新并仅在可靠匹配同一账号时保存快照。未知授权需扫描确认，不使用未验证 JWT 声明证明账号身份。

身份查询使用 `www.googleapis.com`；额度查询使用 `cloudcode-pa.googleapis.com`、`daily-cloudcode-pa.googleapis.com`、`daily-cloudcode-pa.sandbox.googleapis.com` 固定允许的 HTTPS 路径，校验证书且拒绝重定向。系统代理仍属于用户网络信任边界。身份确认发送已有访问令牌，只用于当前登录的账号，确认前再次核对登录。

**本地不等于离线。** 当前身份与额度请求仍由 Python 网络实现发出，不是借官方程序代发，不保证指纹一致或不可识别。

## 中文：离线预计值与快照边界

离线额度到已知恢复时间可显示“100% · 预计已恢复”。这是根据缓存的恢复规则在本机计算，不是 Google 确认。原始百分比、查询时间、重置时间不被预计值覆盖；缺失字段保持未知，再次登录后以实际查询核对。账号在其他设备使用或规则变化可能影响准确性。

后台约每五秒检查登录区，工具控制的正常切换还会在退出后读取最终凭据。外部退出、崩溃或工具未运行期间不能保证捕捉瞬时变化。普通访问令牌更新保持账号授权匹配时自动同步；无法确认新的刷新授权归属时要求扫描。

当前仅操作 `gemini:antigravity`，不枚举浏览器账号或其他 Windows 凭据。旧快照依赖刷新授权匹配，已验证的新快照可利用 Google subject 识别重复账号。删除操作移除所选快照、缓存及匹配恢复备份，保持官方客户端登录不变。卸载保留用户数据。

这些是实现说明，不是独立安全认证或绝对安全保证。同一 Windows 用户权限的软件仍可能读取凭据或调用 DPAPI。切换写入检查 Windows 2560 字节容量，并核对写入；失败时尝试恢复并明确报告结果。

## 中文：Google 服务条款

2026-10-08 核对的 [Antigravity 附加条款](https://antigravity.google/terms) 第 6 条限制第三方工具访问服务，可能暂停或终止 Antigravity / Gemini CLI 访问。虽然 0.8.0 停止工具自行 OAuth 续期和离线查询，当前账号身份与额度访问仍有条款风险。仅本地恢复快照是否允许没有单独澄清。开源、低频和使用当前账号不代表官方许可。企业订阅可能适用其他协议。

不要在公开 issue 上传账号文件、原始接口数据、凭据、未脱敏日志或截图。优先使用启用的 GitHub 私密漏洞报告；否则提交不包含凭据或实际账号利用信息的描述。

---

## English: local execution and network boundary

This independent Windows utility stores account snapshots and quota caches locally with current-user DPAPI encryption. No backdoor, covert uploads, telemetry, remote control, author-operated servers, ads, remote fonts/CDNs or automatic code-download execution. Account grants, snapshots, projects and chat histories are not uploaded to the author or third parties.

The UI uses only a loopback server and never receives access/refresh grants. Local actions validate Host, Origin, HttpOnly/SameSite cookies and a random control token.

Only the matched account in the running official Antigravity client is eligible for identity and quota queries. Manual/scheduled/reset-time/switch-alignment requests share that boundary. Each dispatch rechecks state after request pacing. Subsequent requests stop when the login changes or the client closes; already-sent requests cannot be recalled, and results from a changed account are discarded.

The application flow does not call OAuth refresh or keep inactive grants alive. The official client owns renewal. The utility reads its updates and synchronizes only reliably matched snapshots. Unknown grants require explicit scanning, never identity inference from unverified JWT claims or the last selected account.

Identity queries go to fixed allowlisted HTTPS paths on www.googleapis.com; quota requests use cloudcode-pa.googleapis.com, daily-cloudcode-pa.googleapis.com and daily-cloudcode-pa.sandbox.googleapis.com. TLS certificate checks remain enabled and redirects are rejected. System proxies remain part of the user's trust boundary.

Local execution is not offline operation. Current-account requests still originate from this tool's Python network implementation, not from the official client. Matching its complete network fingerprint or avoiding identification is not guaranteed.

## English: estimates, synchronization and limitations

Offline recovery can display estimated 100% at a cached reset deadline, without a network request. Confirmed percentages, query timestamps and reset times remain unchanged in encrypted storage. Unknown data is not invented. Real results replace projections on the next login. Other-device use and provider rule changes can invalidate estimates.

The backend observes credentials about every five seconds. Controlled switches also capture final credentials after normal exit. External closes, crashes and periods when this utility is not running cannot guarantee every transition is observed. New refresh grants that cannot be reliably matched require scanning.

Only the gemini:antigravity credential is read; browser and unrelated Windows logins are not enumerated. Deletion removes the selected snapshot/cache and matching recovery backup, without signing out the official client. Uninstall preserves local data.

Implementation statements are not independent security certification or an absolute guarantee. Same-user malware can still access credentials or DPAPI. Native writes check Windows' 2560-byte limit, read back for verification and attempt rollback on failure.

## English: service terms and reporting

Clause 6 of the Antigravity Additional Terms, checked 2026-10-08, restricts third-party service access and describes potential Antigravity / Gemini CLI suspension or termination. Version 0.8.0 removes utility-driven OAuth renewal and inactive-account queries, but current-account identity and quota requests still carry service-terms risks. Local snapshot restoration is not separately clarified. Open source, low frequency and querying only the current account do not grant Google permission. Enterprise agreements may differ.

Do not attach credentials, snapshots, raw provider traffic, unredacted logs or personal screenshots to public issues. Use GitHub private vulnerability reporting when enabled, or begin with a credential-free description.
