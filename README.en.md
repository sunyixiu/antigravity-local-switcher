# Antigravity Local Switcher | Antigravity 本地账号切换器

[简体中文](README.md) · [English](README.en.md)

An independent Windows account manager and quota dashboard for Antigravity. Scan the official client's current Google login, verify the email, name and save it, view saved accounts' Gemini / Claude / GPT quota, and switch the local login.

**Unofficial software with service-terms risks.** Clause 6 of the [Google Antigravity Additional Terms](https://antigravity.google/terms) prohibits third-party tools accessing the service and describes possible suspension or termination of Antigravity / Gemini CLI accounts. This tool's internal quota queries and OAuth refresh carry that risk. The terms do not separately clarify local snapshot restoration. Open source is not Google authorization. See the bilingual [security and service-terms notice](SECURITY.md).

## Local execution and privacy

**Account management and credential storage run locally. This version contains no backdoor, covert upload, telemetry or remote-control functionality. There is no author-operated server. Login credentials, snapshots, project files and chat histories are not uploaded to the author or other third parties.**

- Snapshots, recovery backups and quota caches use Windows DPAPI encryption for the current Windows user. Data stays in `%LOCALAPPDATA%\AntigravityLocalSwitcher`.
- The UI connects only to the local `127.0.0.1` server. It receives account and quota projections, never Google access or refresh tokens. Local actions validate the session and request origin.
- Identity verification, quota queries and OAuth refresh connect directly to allowlisted Google HTTPS endpoints, sending only the tokens required by those protocols. **Local does not mean offline**: "no uploads" means no covert collection or transfers to the author or third parties; it does not exclude Google authentication requests.
- No ads, analytics, remote fonts, CDNs, automatic code-download execution, or model-request reverse proxy.
- The implementation is open for review. These statements are not an independent security certification or an absolute safety guarantee. Malware running as the same Windows user may still access credentials or DPAPI. Service-terms risks are separate.

## Download

Get the Windows x64 installer, portable ZIP or standalone EXE from [GitHub Releases](https://github.com/sunyixiu/antigravity-local-switcher/releases). The EXE includes its runtime; no Python installation is needed. The installer can create desktop and Start menu shortcuts. Install, upgrade and uninstall preserve local account data.

Current version: **0.7.1**. Windows binaries are not publisher code-signed.

## Usage

1. Sign into your Google account in the official Antigravity desktop client.
2. Open the switcher; it scans the current login automatically. You can also click **扫描账号** (Scan account).
3. For a new login, verify the displayed email, enter a name, and click **命名并添加** (Name and add). Scanning alone does not save a snapshot. An already-saved login is explicitly reported as **未检测到新账号** (No new account detected).
4. The currently matched account has a **当前使用** (Currently in use) label and highlighted card. This checks the actual local credential, not the last account clicked. External login changes are checked during the UI's five-second polling. Unmatched or unreadable logins are shown explicitly; scan to confirm them.
5. Click **刷新额度** (Refresh quota) on one card, or **刷新全部** (Refresh all) to query saved accounts sequentially. Quota can be queried while another account is active.
6. Save your work and click **切换账号** (Switch account). The tool requests normal Antigravity exit, restores the chosen login and relaunches the official client. It aborts if the client cannot exit normally.
7. Card menus support renaming and updating the login snapshot. Renaming preserves credentials and quota history. **删除账号** (Delete account) asks for confirmation and removes the selected snapshot, quota cache, schedule records and a matching pre-switch recovery backup. Deletion is irreversible and does not sign out the official client.

Scanning checks only the official client's current local login, not all browser Google accounts. The current login is rechecked before enrollment to prevent saving a different account after a login change. Older snapshots are primarily matched by their refresh grant; reauthorization with a different grant may require scanning or updating the snapshot.

## Quota and scheduling

Gemini and Claude/GPT weekly and five-hour windows are displayed separately, with reset countdowns and UTC+8 reset dates. Model details are available separately. Shared quotas are not added together or translated into precise request counts.

Choose automatic checks every three or four hours, or turn them off. At a reset deadline, the UI shows pending confirmation and queries again; it never invents a 100% recovery. Failed requests retain the previous values and timestamp. Queries are serialized, repeated clicks have cooldowns, and HTTP 429 triggers backoff. These controls do not eliminate service-terms risks.

The quota interfaces are unpublished and can change. Missing data is shown as unknown. Expired authorization requires signing in through the official client and updating the snapshot. OAuth client configuration is read from the locally installed official binary rather than embedded in this source or releases; unknown configurations stop refresh.

## Run, test and build

```powershell
python local_switcher.py
python -m unittest discover -s tests
python -m pip install -r requirements-build.txt
python packaging/build_windows.py
```

Runtime uses the Python standard library and native Windows APIs. The local UI prefers an Edge app window and otherwise uses the default browser. This version supports the Windows `gemini:antigravity` credential storage, not older SQLite login storage or other CLI credentials.

For an installer, provide Inno Setup 6, including `ChineseSimplified.isl`:

```powershell
python packaging/build_windows.py --iscc 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

Tests use synthetic accounts. Native DPAPI integration tests skip when the environment cannot support them. Build outputs are in `dist/` and contain no account data.

## License and credits

Original implementation under the [MIT License](LICENSE). The Google icon comes from [SVG Logos](https://github.com/gilbarbara/logos), licensed under CC0 1.0; notices are bundled in `assets/`. Google trademarks belong to Google. This project does not represent Google.

Internal quota protocol formats reference [Draculabo/AntigravityManager](https://github.com/Draculabo/AntigravityManager); its implementation code and dependencies are not copied or integrated.
