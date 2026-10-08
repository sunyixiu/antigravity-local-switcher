"""Build the Windows executable and optionally an Inno Setup installer."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc", type=Path, help="Path to Inno Setup 6 ISCC.exe")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    packaging = root / "packaging"
    build = root / "build"
    portable = root / "dist" / "portable"
    env = os.environ.copy()
    env["PYINSTALLER_CONFIG_DIR"] = str(build / "cache")
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "AntigravityLocalSwitcher", "--icon", str(root / "assets/app-icon.ico"),
        "--add-data", str(root / "ui.html") + ";.", "--add-data", str(root / "assets") + ";assets",
        "--version-file", str(packaging / "windows-version.txt"),
        "--specpath", str(build), "--workpath", str(build / "pyinstaller"),
        "--distpath", str(portable), str(root / "local_switcher.py"),
    ]
    subprocess.run(command, cwd=root, env=env, check=True)
    licenses = portable / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python-LICENSE.txt")
    for name in ["SVG-Logos-LICENSE.txt", "NOTICE.md"]:
        shutil.copy2(root / "assets" / name, licenses / name)
    import importlib.metadata
    distribution = importlib.metadata.distribution("pyinstaller")
    for entry in distribution.files or []:
        if entry.name.lower() == "copying.txt":
            shutil.copy2(distribution.locate_file(entry), licenses / "PyInstaller-COPYING.txt")
            break
    shutil.copy2(root / "使用说明.md", portable / "使用说明.md")
    for name in ["LICENSE", "SECURITY.md", "README.md", "README.en.md"]:
        if (root / name).is_file():
            shutil.copy2(root / name, portable / name)
    (portable / "安装说明.txt").write_text(
        "Antigravity 本地账号切换器 0.8.0\n\n无需安装 Python。安装和卸载程序都保留本机账号快照。"
        "\n真实账号数据：%LOCALAPPDATA%\\AntigravityLocalSwitcher\n"
        "本工具为独立本地工具，不是 Google 官方应用。\n账号管理与加密存储在本机完成，无后门、隐蔽上传、遥测或作者服务器。\n仅当前运行且已匹配的登录账号查询 Google；离线额度按缓存时间预计恢复，不联网查询。工具不自行续期授权。\nLocal account management; no backdoor, covert uploads, telemetry or author server. Only the active official-client account is queried. Offline quotas are local estimates. OAuth renewal is left to the official client.\n"
        "Google Antigravity 条款第 6 条禁止第三方工具访问服务。本工具身份和额度查询仍存在账号暂停或终止风险。\n"
        "官方条款：https://antigravity.google/terms 。开源不代表官方许可。\n",
        encoding="utf-8-sig",
    )
    if args.iscc:
        subprocess.run([str(args.iscc.resolve()), str(packaging / "installer.iss")], cwd=root, check=True)
    print("Build complete:", portable / "AntigravityLocalSwitcher.exe")


if __name__ == "__main__":
    main()
