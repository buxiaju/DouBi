"""把豆比下载打成 Windows 单文件 .exe。

用法（项目根目录）::

    python scripts/build_exe.py            # 默认 onefile 模式
    python scripts/build_exe.py --onedir   # 拆目录（启动快，调试用）
    python scripts/build_exe.py --console  # 带控制台窗口（默认 GUI 模式）

产物：

* ``dist/doubi-gui.exe`` —— PyInstaller onefile
* ``dist/doubi-gui/`` —— PyInstaller onedir（NSIS 安装包用这个）
* ``build/doubi-gui/<...>`` —— 临时构建目录

要点：

* ``--icon``: 让任务栏 / 资源管理器读到 .exe 资源里的图标。
  ``setWindowIcon`` 只能改标题栏 / Alt+Tab，**改不了任务栏的
  「应用分组」图标**——这个图标只从 .exe 资源里读。
* ``--add-data``: PySide6 / qfluentwidgets 的资源是 frozen 包
  形式（QRC 编译进 .pyd），不需要 --add-data。但项目自己的
  ``icon_template.svg`` 走文件系统读取（不是 QRC），需要打包。
* ``--collect-all qframelesswindow``: 第三方库有隐藏的 Qt 资源
  / 插件文件，PyInstaller 默认钩子抓不全，显式补一遍最稳。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ENTRY = ROOT / "src" / "doubi" / "ui" / "app.py"
ICON = ROOT / "src" / "doubi" / "ui" / "resources" / "icon.ico"
SVG_TEMPLATE = ROOT / "src" / "doubi" / "ui" / "resources" / "icon_template.svg"
LOCALES_DIR = ROOT / "src" / "doubi" / "ui" / "locales"


def _find_playwright_browsers_dir() -> Path | None:
    """定位 Playwright 安装的 Chromium 浏览器目录。

    查找顺序：

    1. ``PLAYWRIGHT_BROWSERS_PATH`` 环境变量
    2. 默认安装位置：
       - Windows: ``%USERPROFILE%\\AppData\\Local\\ms-playwright``
       - POSIX:   ``~/.cache/ms-playwright``

    返回目录本身（含 ``chromium-XXXX`` 等子目录）。如果没找到，返回 None。
    """
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    # 默认位置
    if sys.platform == "win32":
        candidates = [
            Path.home() / "AppData" / "Local" / "ms-playwright",
            Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright",
        ]
    else:
        candidates = [Path.home() / ".cache" / "ms-playwright"]
    for c in candidates:
        try:
            if c.is_dir():
                # 至少要有一个 chromium-* 子目录才算是真的 ms-playwright
                if any(c.glob("chromium-*")):
                    return c
        except OSError:
            continue
    return None

# PyInstaller 只接受「脚本文件路径」作为入口，没有 --module 选项
# （历史上也没有；6.x 直接报 unrecognized arguments）。而直接把
# src/doubi/ui/app.py 当入口会触发 BUILD.md §5.1 的相对导入崩溃：
# onefile 把它当顶层 __main__ 解包，doubi 父包不存在。
#
# 解法是生成一层极薄的启动壳：它在包外面，用**绝对导入**进包，
# 于是包结构完整保留，`from .theme import ...` 正常工作。
#
# 同时：壳里把 ``PLAYWRIGHT_BROWSERS_PATH`` 指向打包进去的 Chromium
# 二进制位置（onefile 下 ``sys._MEIPASS`` 是解压临时目录）——否则
# 运行时 Sniffer 调 ``playwright.chromium.launch()`` 会找不到浏览器。
LAUNCHER_SOURCE = '''"""PyInstaller 入口壳——由 scripts/build_exe.py 自动生成，勿手工编辑。"""

import os
import sys

# Playwright 浏览器二进制位置：onefile/onedir 解压后，浏览器文件夹在
# 临时目录的 ``playwright_browsers`` 子目录下（由 build_exe.py 的
# ``--add-data`` 注入）。设环境变量让 Playwright 找到。
try:
    _base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    _browsers = os.path.join(_base, "playwright_browsers")
    if os.path.isdir(_browsers):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browsers
except Exception:
    pass

from doubi.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--onedir", action="store_true", help="拆目录（默认 onefile）",
    )
    parser.add_argument(
        "--console", action="store_true", help="带控制台窗口（默认 GUI）",
    )
    args = parser.parse_args()

    if not ICON.is_file():
        print(f"缺少 .ico，先跑 scripts/build_ico.py 生成 {ICON}", file=sys.stderr)
        return 1
    if not SVG_TEMPLATE.is_file():
        print(f"缺少 {SVG_TEMPLATE}", file=sys.stderr)
        return 1

    # PyInstaller CLI 命令行参数——用列表比 subprocess.run + shell=True 安全。
    # 注意：--add-data 的分隔符在 Windows 下是 ';'、POSIX 下是 ':'。
    sep = ";" if sys.platform == "win32" else ":"
    # 入口用自动生成的启动壳（见 LAUNCHER_SOURCE 注释）：放在项目根，
    # 以绝对导入 ``from doubi.ui.app import main`` 进包，保住包结构。
    launcher = ROOT / "_doubi_gui_launcher.py"
    launcher.write_text(LAUNCHER_SOURCE, encoding="utf-8")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "doubi-gui",
        "--specpath", str(ROOT),
        "--icon", str(ICON),
        "--add-data", f"{SVG_TEMPLATE}{sep}doubi/ui/resources",
        # i18n JSON 词表（和上面 icon_template 一样，走读 JSON 文件不是 QRC）
        "--add-data", f"{LOCALES_DIR}{sep}doubi/ui/locales",
        # 第三方 Qt 库的隐藏资源 / 插件
        "--collect-all", "qframelesswindow",
        "--collect-all", "qfluentwidgets",
        # ---- Playwright + Chromium 浏览器二进制 ----
        # generic adapter 的 Sniffer 调 ``playwright.chromium.launch()``
        # 需要浏览器二进制；用户要求「全打进安装包」，所以把整个
        # ms-playwright 目录收进来。启动壳在运行时设
        # ``PLAYWRIGHT_BROWSERS_PATH`` 指向它。
        "--collect-all", "playwright",
        # 自己写的进 src 目录的代码
        "--paths", str(ROOT / "src"),
        # 平台适配器靠 import 副作用自注册，PyInstaller 静态分析
        # 追不到「谁 import 了它们」，必须整包收进来
        "--collect-submodules", "doubi",
        str(launcher),
    ]

    # ---- Chromium 浏览器二进制 ----
    # ms-playwright 目录位置：
    #   Windows: %USERPROFILE%\AppData\Local\ms-playwright
    #   POSIX:   ~/.cache/ms-playwright
    # 该目录下有 chromium-XXXX / ffmpeg-XXXX 等子目录，整目录打包进去。
    browsers_dir = _find_playwright_browsers_dir()
    if browsers_dir is None:
        print(
            "警告：未找到 Playwright 浏览器目录（ms-playwright）。generic adapter"
            " 的嗅探功能在运行时不可用。如要完整功能：pip install doubi[gui] "
            "&& playwright install chromium，然后重新构建。",
            file=sys.stderr,
        )
    else:
        cmd.append("--add-data")
        cmd.append(f"{browsers_dir}{sep}playwright_browsers")
        print(f"打包 Playwright 浏览器：{browsers_dir}")
    if args.onedir:
        cmd.insert(4, "--onedir")
    else:
        cmd.insert(4, "--onefile")
    if not args.console:
        # GUI 应用不带控制台窗口（启动更干净）
        cmd.insert(4, "--windowed")

    print(">>>", " ".join(cmd))
    import subprocess
    try:
        rc = subprocess.run(cmd, cwd=ROOT).returncode
    finally:
        # 启动壳是构建期临时文件，无论成败都不留在仓库里
        launcher.unlink(missing_ok=True)
    if rc != 0:
        return rc

    # 清理临时构建目录，节省磁盘
    build = ROOT / "build" / "doubi-gui"
    if build.is_dir():
        shutil.rmtree(build, ignore_errors=True)
    spec = ROOT / "doubi-gui.spec"
    if spec.is_file():
        spec.unlink()
    if args.onedir:
        print(f"OK → {ROOT / 'dist' / 'doubi-gui'}")
    else:
        print(f"OK → {ROOT / 'dist' / 'doubi-gui.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
