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
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ENTRY = ROOT / "src" / "doubi" / "ui" / "app.py"
ICON = ROOT / "src" / "doubi" / "ui" / "resources" / "icon.ico"
SVG_TEMPLATE = ROOT / "src" / "doubi" / "ui" / "resources" / "icon_template.svg"

# PyInstaller 只接受「脚本文件路径」作为入口，没有 --module 选项
# （历史上也没有；6.x 直接报 unrecognized arguments）。而直接把
# src/doubi/ui/app.py 当入口会触发 BUILD.md §5.1 的相对导入崩溃：
# onefile 把它当顶层 __main__ 解包，doubi 父包不存在。
#
# 解法是生成一层极薄的启动壳：它在包外面，用**绝对导入**进包，
# 于是包结构完整保留，`from .theme import ...` 正常工作。
LAUNCHER_SOURCE = '''"""PyInstaller 入口壳——由 scripts/build_exe.py 自动生成，勿手工编辑。"""

import sys

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
        # 第三方 Qt 库的隐藏资源 / 插件
        "--collect-all", "qframelesswindow",
        "--collect-all", "qfluentwidgets",
        # 自己写的进 src 目录的代码
        "--paths", str(ROOT / "src"),
        # 平台适配器靠 import 副作用自注册，PyInstaller 静态分析
        # 追不到「谁 import 了它们」，必须整包收进来
        "--collect-submodules", "doubi",
        str(launcher),
    ]
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
