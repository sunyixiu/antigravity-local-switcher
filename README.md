# Antigravity 本地账号切换器 | Antigravity Local Switcher

[简体中文](README.md) · [English](README.en.md)

Windows 本地多账号管理与额度看板：扫描当前 Antigravity 登录，确认命名后保存；查看已保存账号的 Gemini / Claude / GPT 额度，并在本机切换登录。

**独立非官方工具。当前实现存在 Google 服务条款风险。** [Antigravity 官方附加条款](https://antigravity.google/terms)第 6 条明确禁止第三方工具访问该服务，并说明可能暂停或终止 Antigravity / Gemini CLI 账号。本工具直接调用内部额度接口、刷新 OAuth 令牌，不能保证符合条款；仅本地恢复登录快照是否允许，条款也没有单独澄清。开源不代表 Google 许可。详情见 [SECURITY.md](SECURITY.md)。

## 本地运行与隐私承诺

**账号管理与凭据存储完全在本机完成。项目不包含后门、隐藏上传、遥测或远程控制功能，不设置作者服务器，也不把登录凭据、账号快照、项目文件或聊天记录上传给作者或第三方。**

- 账号快照和额度缓存使用 Windows 当前用户 DPAPI 加密，保存在 `%LOCALAPPDATA%\AntigravityLocalSwitcher`。
- 界面只连接本机 `127.0.0.1`，不接收 Google 登录令牌；本地操作校验会话和请求来源。
- 身份确认、额度查询和授权刷新会直接连接指定 Google HTTPS 接口，并按 Google 协议发送必要的令牌。**本地工具不等于完全离线**，这里的“无上传”指没有隐蔽收集或向作者/第三方上传数据。
- 没有远程字体、CDN、广告、使用分析、自动下载执行代码或模型请求反向代理。
- 源码公开，欢迎审查。以上描述本版本的实现；开源和加密不能保证绝对安全，同一 Windows 用户权限的恶意程序仍可能读取凭据。服务条款风险也独立存在。

详情见 [中英文安全与网络说明](SECURITY.md)。

## 下载

从 [GitHub Releases](https://github.com/sunyixiu/antigravity-local-switcher/releases) 下载 Windows x64 安装包或免安装 EXE。EXE 已包含运行时，无需 Python。安装包支持桌面和开始菜单快捷方式；安装、升级和卸载均保留本机账号数据。

当前版本：**0.7.1**。

## 使用流程

1. 在 Antigravity 官方客户端正常登录自己的 Google 账号。
2. 打开工具，自动扫描当前登录；也可以点顶部 **扫描账号**。
3. 发现未保存账号时显示确认后的邮箱，用户命名后点 **命名并添加** 才入库。
4. 已保存账号会显示 **未检测到新账号，当前账号已入库**，避免重复录入。未登录和扫描失败也有独立提示。
5. 每张卡片可独立刷新额度；顶部 **刷新全部** 按顺序查询。
6. 保存编辑中的工作，再点卡片 **切换账号**。工具请求 Antigravity 正常退出，恢复目标登录凭据并重启客户端。

扫描只检测 Antigravity 当前登录，不枚举浏览器中的所有 Google 账号。已保存账号可以在未使用时查询额度。扫描期间不会自动创建账号快照；确认入库前会重新检查当前登录，防止用户已切到其他账号。

## 功能

- **当前使用账号**：独立标签和卡片高亮，核对实际本地登录，约每 5 秒检查官方客户端换号或退出登录。未匹配或读取失败时明确提示，不把最近操作当作当前账号。

- 当前登录自动扫描、新账号确认命名、已有账号提示。
- Windows 用户 DPAPI 加密快照，切换前恢复备份及写入后核对。
- 账号重命名、登录快照更新、确认删除；删除清除所选快照、额度缓存和匹配的切换前恢复备份，Antigravity 当前登录保持不变。
- Gemini、Claude/GPT 的每周与五小时窗口分别显示，模型详情独立查看。
- 每 3/4 小时定时查询、重置倒计时、到期后排队查询确认；不会直接把旧百分比改为 100%。
- 串行请求、账号查询间隔、重复点击冷却及 429 限流退避。
- Windows 单文件 EXE、每用户安装包、透明 Google 图标。

额度接口未公开且可能变化。缺失值显示未知；查询失败保留旧时间和旧数据。账号授权失效时需要在官方客户端重新登录并更新快照。OAuth 刷新从本机官方客户端读取兼容的桌面配置，源码和发布包不内置客户端密钥；未安装或新版配置不兼容时会提示停止刷新。

## 运行源码

```powershell
python local_switcher.py
```

只使用 Python 标准库和 Windows 原生 API。界面通过本机回环地址显示，优先使用 Edge 应用窗口。当前支持使用 Windows 凭据目标 `gemini:antigravity` 的桌面版本；不覆盖旧版 SQLite 存储、远程机器或其他 CLI 的账号状态。

## 测试与构建

```powershell
python -m unittest discover -s tests
python -m pip install -r requirements-build.txt
python packaging/build_windows.py
```

生成安装包需 Inno Setup 6 编译器（以及 ChineseSimplified.isl）：

```powershell
python packaging/build_windows.py --iscc 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

测试使用虚构账号；原生 DPAPI 集成测试在当前登录环境不支持时跳过。构建输出在 `dist/`，不包含真实账号数据。

## 数据与隐私

账号数据位于 `%LOCALAPPDATA%\AntigravityLocalSwitcher`，与源码和安装目录分离。仓库忽略 `.agprofile`、`.agrecovery`、`.quota`、日志和运行配置。浏览器界面不接收令牌，没有作者服务器和分析上报。Google 查询的目的、权限边界及服务条款风险详见 [SECURITY.md](SECURITY.md)。

## 许可与致谢

独立编写的代码以 [MIT](LICENSE) 许可开源。Google 图标来自 [SVG Logos](https://github.com/gilbarbara/logos)，原许可为 CC0 1.0，许可和来源放在 `assets/`。Google 商标属于 Google，本项目不代表 Google。

内部额度协议参考 [Draculabo/AntigravityManager](https://github.com/Draculabo/AntigravityManager) 披露的接口格式；本项目未复制其实现代码，也未集成其依赖。
