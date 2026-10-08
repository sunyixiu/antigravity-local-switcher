# Antigravity Local Switcher | Antigravity 本地账号切换器

[简体中文](README.md) · [English](README.en.md)

A Windows local account switcher and quota dashboard. **Only the account currently signed into a running official Antigravity client is queried. Other accounts use encrypted caches and local recovery estimates.** Version: **0.8.0**.

**Unofficial, with service-terms risks.** Clause 6 of the [Antigravity Additional Terms](https://antigravity.google/terms) restricts third-party access and describes potential Antigravity / Gemini CLI suspension or termination. Identity and quota calls still originate from this utility. Limiting them to the current account does not make its network fingerprint identical to the official client or grant Google authorization. See [SECURITY.md](SECURITY.md).

## Local execution and privacy

Account snapshots and quota caches stay on this computer, encrypted with current-user Windows DPAPI. There are no backdoors, covert uploads, telemetry, remote control, ads, remote fonts/CDNs or author-operated servers. Credentials, snapshots, projects and chat histories are not sent to the author or third parties.

The browser UI connects only to the loopback server and never receives Google tokens. Current-account identity and quota requests connect directly to allowlisted Google HTTPS endpoints using the necessary access token. Local does not mean offline; open source and encryption are not absolute security guarantees against same-user malware.

## Download and use

Download the Windows x64 installer, portable ZIP or EXE from [Releases](https://github.com/sunyixiu/antigravity-local-switcher/releases). No Python installation is required. Binaries are not publisher code-signed.

1. Sign in through the official Antigravity client.
2. Open this tool; it scans the current login, or click **扫描账号** (Scan account).
3. New accounts show the verified email and are saved only after naming and confirmation. Existing accounts report **未检测到新账号** (No new account detected).
4. The running current account has a **当前使用** label. Its card or **刷新当前账号** (Refresh current account) can query quota.
5. Inactive cards show **离线缓存** (Offline cache). They never query Google; switch to them before refreshing. Legacy batch-refresh routes also query only the current account.
6. Save your work and click **切换账号**. The tool closes the official client normally, captures its final matching credentials, restores the target snapshot and relaunches the client. It can launch a closed client too.
7. Card menus support renaming, explicit snapshot update and confirmed deletion. Deletion removes the chosen snapshot/cache/schedule records and matching recovery backup, is irreversible, and does not sign out the official client.

## Queries and snapshot synchronization

Manual, scheduled, reset-time, post-login and tool-controlled pre-switch checks target only the matched account in the running client. Scheduling supports three/four hours or off. Off disables automatic network alignment while local snapshot sync and recovery projection continue.

After request pacing and immediately before dispatch, the utility rechecks the login and process state. An external switch, sign-out or close stops subsequent requests. A request already sent cannot be recalled; its result is discarded if the account has changed before storage.

The utility does not renew OAuth grants. It never refreshes inactive accounts to keep them alive. Missing, expired or rejected access tokens wait for the official client to update authorization. Latest official credentials are read rather than writing utility-generated tokens back to Windows.

The backend observes local credentials about every five seconds. A uniquely matched refresh grant permits updating that snapshot; unknown/rotated grants require explicit scanning, never guessing from the last clicked account. A controlled switch reads again after normal client exit. External shutdowns can only retain the last observed state, not every instantaneous change.

## Offline recovery estimates

Gemini and Claude/GPT weekly and five-hour windows use their separate cached Google resetTime values.

Example: the last confirmed quota is 35% with a reset in one hour. At that deadline, the inactive card displays **100% — estimated recovery**, without a Google request. Details retain the last confirmed 35%, query time and reset time. On the next login, the actual result replaces the estimate.

Estimates are presentation only and do not overwrite encrypted confirmed caches. Unknown values remain unknown. Online accounts wait for an actual query after reset. Future windows are not invented by repeatedly adding five hours or seven days. Other-device usage and provider rule changes can make actual quota differ.

## Data, compatibility and builds

Data stays in `%LOCALAPPDATA%\AntigravityLocalSwitcher`. Upgrade/uninstall preserve it unless an account is explicitly deleted. Current support targets official Windows `gemini:antigravity` credentials, not old SQLite storage, other CLIs, project files or chat histories. Unpublished quota endpoints can change. Failed requests preserve prior data. Legacy oversized snapshots are compacted and stripped of optional id_token when necessary before writes, preserving access/refresh grants within Windows' 2560-byte limit.

Runtime uses Python's standard library and native Windows APIs, with an Edge app window or default browser.

```powershell
python local_switcher.py
python -m unittest discover -s tests
python -m pip install -r requirements-build.txt
python packaging/build_windows.py
```

Installers require Inno Setup 6 and ChineseSimplified.isl:

```powershell
python packaging/build_windows.py --iscc 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

Tests use synthetic accounts and skip unsupported native integration checks. Build output is in dist and contains no account data.

Original implementation under [MIT](LICENSE). Google icons come from [SVG Logos](https://github.com/gilbarbara/logos), CC0 1.0, with notices in assets. Google owns its trademarks; this project is independent. Internal protocol formats reference [Draculabo/AntigravityManager](https://github.com/Draculabo/AntigravityManager), without copying its implementation or integrating its dependencies.
