# Antigravity 本地账号切换器 | Antigravity Local Switcher

[简体中文](README.md) · [English](README.en.md)

Windows 本地多账号切换与额度看板。**只查询当前运行的 Antigravity 登录账号，其他账号使用加密缓存和本地恢复推算。** 当前版本：**0.8.0**。

**独立非官方工具，仍有服务条款风险。** [Google Antigravity 附加条款](https://antigravity.google/terms)第 6 条限制第三方工具访问服务，可能导致 Antigravity / Gemini CLI 账号暂停或终止。当前身份和额度查询仍由本工具向 Google 发出；仅查询当前账号不代表请求指纹与官方一致，也不代表 Google 授权。详见 [中英文安全说明](SECURITY.md)。

## 本地运行与隐私

账号管理、登录快照和额度缓存保存在本机，使用 Windows 当前用户 DPAPI 加密。项目不包含后门、隐蔽上传、遥测、远程控制或作者服务器，不向作者或第三方发送凭据、快照、项目文件或聊天记录。界面只连接本机 `127.0.0.1`，不接收 Google 令牌，没有远程字体、CDN 或广告。

当前账号的身份确认和额度查询会直接连接固定允许的 Google HTTPS 接口，发送必要访问令牌。**本地不等于离线，公开源码和加密也不等于绝对安全。** 同一 Windows 用户权限的恶意软件仍属于安全边界。

## 下载与使用

从 [GitHub Releases](https://github.com/sunyixiu/antigravity-local-switcher/releases) 下载 Windows x64 安装包、免安装 ZIP 或 EXE，无需 Python。程序尚未进行发布者代码签名。

1. 在官方 Antigravity 客户端正常登录。
2. 打开工具自动扫描当前登录；也可点 **扫描账号**。
3. 新账号显示邮箱，用户命名确认后才入库；已有账号提示 **未检测到新账号，当前登录已入库**。
4. 当前运行账号显示 **当前使用**；它的卡片和顶部 **刷新当前账号** 可以查询。
5. 其他账号显示 **离线缓存**，只能查看本地结果和预计恢复，切换后再查询。旧版本的批量刷新 API 也只查询当前账号。
6. 保存编辑中的工作后点 **切换账号**。工具正常关闭官方客户端、保存最终匹配快照、恢复目标凭据并重新启动。客户端没打开时也会启动。
7. 卡片 **···** 支持重命名、手动更新快照、确认删除。删除清除快照、额度缓存、查询记录和匹配的恢复备份，不退出官方客户端登录，无法撤销。

## 当前账号查询与快照同步

- 手动、定时、恢复到期、登录后和工具控制的切换前对齐，都只查询当前正在运行且与快照匹配的账号。
- 定时查询可设为每 3 或 4 小时，或关闭。关闭后不自动联网对齐；仍在本地同步匹配快照、计算离线恢复。
- 每次请求在限频等待结束后再次核对当前登录和客户端运行状态。外部换号、退出登录或关闭客户端后停止后续请求；已发出的请求无法撤回，返回时已换号的结果不会入库。
- 工具不自行续期 OAuth，不使用离线快照的 refresh token 去 Google 换取 access token。当前访问令牌过期或被拒绝时等待官方 Antigravity 更新，再读取最新授权。
- 后台约每 5 秒检查登录区，匹配同一刷新授权时自动更新快照。新授权无法可靠确认身份时要求扫描，绝不根据“最后点击账号”猜测归属。
- 工具控制的切换会在退出前同步，并在正常退出后再次读取最终凭据；外部关闭或强制结束只能保留最后一次观察到的状态，不能承诺捕捉每个瞬间。

## 离线额度计算

Gemini 和 Claude/GPT 的五小时、每周窗口独立处理，直接使用上次 Google 返回的 `resetTime`，不从点击时间猜起点。

例如：账号离线时剩余 **35%**、一小时后重置。到该时间显示 **100% · 预计已恢复**，不查询 Google；详情保留 **上次确认 35%**、查询时间和原恢复时间。再次登录后以实际查询覆盖预计值。

预计值只存在于界面投影，不覆盖原始加密额度缓存。未知额度或缺失恢复时间保持未知；当前在线账号到期仍等待查询确认。不会在原时间上循环添加 5 小时或 7 天来虚构后续窗口。若同一账号在其他设备使用、Google 调整规则，实际额度可能与预计不同。

## 数据位置与兼容性

数据在 `%LOCALAPPDATA%\AntigravityLocalSwitcher`，与源码和安装目录分离。升级和卸载保留数据，除非用户在工具中明确删除账号。

支持使用 Windows 凭据目标 `gemini:antigravity` 的官方桌面版本，不覆盖旧 SQLite 登录、其他 CLI、项目或聊天目录。额度接口未公开且可能变化；缺失值显示未知，查询失败保留上次结果。历史大快照切换前按需压缩并移除多余 `id_token`，保持 access/refresh token 不变，以满足 Windows 2560 字节限制。

## 源码、测试与构建

运行时仅使用 Python 标准库及 Windows 原生 API，界面优先 Edge 应用窗口，缺失时使用默认浏览器。

```powershell
python local_switcher.py
python -m unittest discover -s tests
python -m pip install -r requirements-build.txt
python packaging/build_windows.py
```

安装包需 Inno Setup 6 和 ChineseSimplified.isl：

```powershell
python packaging/build_windows.py --iscc 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

测试使用虚构账号；不支持原生 DPAPI 的环境会跳过对应检查。输出在 `dist/`，不包含账号数据。

## 许可与致谢

原创代码使用 [MIT](LICENSE)。Google 图标来自 [SVG Logos](https://github.com/gilbarbara/logos)，CC0 1.0 许可和来源放在 `assets/`。Google 商标属于 Google，项目不代表 Google。

内部额度协议参考 [Draculabo/AntigravityManager](https://github.com/Draculabo/AntigravityManager) 披露的格式，未复制其实现代码或集成依赖。
