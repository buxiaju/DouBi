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
# 通用嗅探注入页面的 JS。它是 .js 而不是 .py，所以 --collect-submodules
# 收不到它（那个只管 Python 模块），必须单独 --add-data。
CATCH_LITE_JS = ROOT / "src" / "doubi" / "platforms" / "generic" / "catch_lite.js"
# N_m3u8DL 自带的 ffmpeg 构建（10.91 MB）——发布版的 ffmpeg 来源，
# 用来替掉 imageio_ffmpeg 轮子里那个 83.6 MB 的等效二进制。
FFMPEG_EXE = ROOT / "tools" / "nm3u8dl" / "ffmpeg.exe"


# ---------------------------------------------------------------------------
# 体积精简：--exclude-module 白名单之外的一切
# ---------------------------------------------------------------------------
# 为什么必须显式排除，而不是靠 PyInstaller 自己「按需收集」：
#
# 上面的 ``--collect-all qfluentwidgets`` / ``--collect-all qframelesswindow``
# 是**强制全收**，它会把包里每一个子模块都拖进依赖图，哪怕本项目从没
# import 过。这两个包里恰好藏着三个重量级子模块：
#
#   qfluentwidgets/multimedia/media_player.py   -> PySide6.QtMultimedia
#   qfluentwidgets/multimedia/video_widget.py   -> PySide6.QtMultimedia
#   qframelesswindow/webengine/__init__.py      -> PySide6.QtWebEngineWidgets
#   qfluentwidgets/common/image_utils.py        -> PIL
#
# 一旦 QtWebEngineCore 进了依赖图，PyInstaller 的 per-module Qt hook 就会
# 连带收进 Qt6WebEngineCore.dll(194 MB) + qtwebengine_devtools_resources
# .debug.pak(72 MB) + .pak(11 MB) + translations/qtwebengine_locales(44 MB)，
# 合计约 321 MB —— 全是死重量。
#
# 排除的安全性是**实测**的，不是推断的：
#   1. grep 全 src 确认除 QtCore/QtGui/QtWidgets/QtSvg 外没有任何 Qt 模块被 import；
#   2. 探针 ``import doubi.ui.app`` 后检查 sys.modules，QtWebEngine /
#      QtMultimedia / QtQuick / QtQml / PIL 全部未加载；
#   3. 探针 ``import qfluentwidgets`` 单独跑，同样一个都没加载——说明这三个
#      重子模块不在任何 ``__init__.py`` 的导入链上，排掉不会让包本身崩。
#
# 判据是「sys.modules 里有没有」，而不是「文件在不在包里」：只要它不在
# 任何 import 链上，PyInstaller 排掉它，运行时就永远碰不到那行 import。
EXCLUDE_MODULES = [
    # --- Qt WebEngine 全家（约 321 MB，最大单笔） ---
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    # --- Qt 多媒体（qfluentwidgets.multimedia 唯一来源，本项目不播视频） ---
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    # --- QML / Quick 运行时（本项目是纯 Widgets） ---
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    # --- 其余从未 import 的 Qt 模块 ---
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGLFunctions",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtUiTools",
    "PySide6.QtWebSockets",
    # --- PIL（12.8 MB）：唯一消费者是 qfluentwidgets 的 AcrylicLabel，
    #     而 grep 确认本项目从没用过 Acrylic* 任何控件 ---
    "PIL",
    # --- imageio_ffmpeg（83.6 MB）：整个包就是一个 ffmpeg-win-x86_64.exe
    #     的壳。改用 tools/nm3u8dl/ffmpeg.exe（10.91 MB）打包，三个引擎的
    #     _find_ffmpeg / _resolve_ffmpeg 都已加上 bundled 分支优先查找 ---
    "imageio_ffmpeg",
    "imageio",
    # --- 打包期工具链，绝不该进运行时 ---
    "PyInstaller",
    "pytest",
    "setuptools",
    "pip",
    # --- 科学计算栈：Qt / playwright 的可选依赖会顺手把它们拖进来 ---
    "numpy",
    "scipy",
    "matplotlib",
    "pandas",
    "tkinter",
]


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


# ``chromium_headless_shell-*``：Playwright 1.4x+ 把 headless 模式拆成了一个
# **独立的** 270.7 MB 二进制（chrome-headless-shell.exe），和完整的
# ``chromium-*``（426.7 MB）并存。默认 ``chromium.launch(headless=True)``
# 会去找这个独立二进制，找不到就直接抛
# ``Executable doesn't exist at ...chrome-headless-shell.exe``。
#
# 但完整 Chromium 自带 Chrome 的「new headless」模式，指定
# ``channel="chromium"`` 就会走完整二进制的 headless 分支，不再需要
# headless_shell。实测方式（负向+正向双跑，而不是只看文档）：
#
#   1. 造一个只含 chromium-1234 / ffmpeg-1011 / winldd-1007 的探针目录
#      （用 junction 链过去，不复制 700 MB）；
#   2. ``launch(headless=True)``      -> 报错，证明它确实依赖 headless_shell；
#   3. ``launch(channel="chromium", headless=True)``  -> 成功，
#      UA = HeadlessChrome/151.0.0.0，证明完整二进制能顶上；
#   4. ``channel="chromium", headless=False`` 也跑一遍 -> 成功，
#      证明有头登录（browser_login）不会被这个改动打坏。
#
# 所以 core/sniffer.py 和 core/auth/browser_login.py 两处 launch 都加了
# ``channel="chromium"``——这是本排除项的**前置条件**，两边必须同时成立。
_BROWSER_SKIP_PREFIXES = ("chromium_headless_shell",)


def _browser_add_data(browsers_dir: Path, sep: str) -> list[str]:
    """把 ms-playwright 目录按子项展开成 --add-data 参数，跳过 headless_shell。

    不整目录一把梭的原因：``--add-data src;dst`` 没有排除语法，想少收
    一个子目录就只能自己逐项列。目标路径保持
    ``playwright_browsers/<子目录名>``，与启动壳设的
    ``PLAYWRIGHT_BROWSERS_PATH`` 布局一致。
    """
    args: list[str] = []
    for child in sorted(browsers_dir.iterdir()):
        if child.name.startswith(_BROWSER_SKIP_PREFIXES):
            print(f"跳过（体积精简）：{child.name}")
            continue
        if child.is_dir():
            dst = f"playwright_browsers/{child.name}"
        else:
            dst = "playwright_browsers"
        args.append("--add-data")
        args.append(f"{child}{sep}{dst}")
    return args

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
    if not CATCH_LITE_JS.is_file():
        # 同 FFMPEG_EXE 的理由：漏了它构建照样成功，但通用嗅探会在用户
        # 机上报「catch_lite.js 加载失败；安装包可能损坏」。
        print(f"缺少 {CATCH_LITE_JS}。它是通用嗅探注入页面的脚本。", file=sys.stderr)
        return 1
    if not FFMPEG_EXE.is_file():
        # 早失败而不是让 --add-data 静默丢一个不存在的路径：那样构建会
        # 成功，但发布版里没有 ffmpeg，问题要等到用户下载 HLS 才暴露。
        print(
            f"缺少 {FFMPEG_EXE}。它是发布版唯一的 ffmpeg 来源，"
            "从 N_m3u8DL-CLI 发布包解压到 tools/nm3u8dl/ 后重试。",
            file=sys.stderr,
        )
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
        # 通用嗅探的注入脚本。core/sniffer.py 用
        # ``importlib.resources.files("doubi.platforms.generic")`` 读它——
        # importlib 让**路径**在冻结后仍正确，但文件本身还是得靠这行进包。
        # 下面的 --collect-submodules doubi 只收 .py，不收 .js。
        "--add-data", f"{CATCH_LITE_JS}{sep}doubi/platforms/generic",
        # 第三方 Qt 库的隐藏资源 / 插件
        "--collect-all", "qframelesswindow",
        "--collect-all", "qfluentwidgets",
        # ---- Playwright + Chromium 浏览器二进制 ----
        # generic adapter 的 Sniffer 调 ``playwright.chromium.launch()``
        # 需要浏览器二进制，所以整个 ms-playwright 目录随包分发（除
        # headless_shell，见 _browser_add_data）。启动壳在运行时设
        # ``PLAYWRIGHT_BROWSERS_PATH`` 指向它。
        "--collect-all", "playwright",
        # ---- aiohttp（HLS 下载的唯一可行路径） ----
        # 捆绑的 tools/nm3u8dl/ffmpeg.exe 编译时未启用任何 TLS 后端，
        # 喂它 https 播放列表会直接 "Protocol not found" 退出。现实中
        # 几乎所有 m3u8 都是 https，所以 aiohttp 分片下载器不是「降级
        # 备选」而是**主路径**，缺了它 HLS 就完全不可用。
        #
        # 必须显式收集的两个原因：
        # 1. m3u8.py / direct_http.py 里是函数内 ``import aiohttp``
        #    的延迟导入，PyInstaller 静态分析对这种形式并不可靠；
        # 2. multidict / yarl / propcache / frozenlist 都带 C 扩展
        #    (.pyd)，靠模块级依赖推导容易漏。
        "--collect-all", "aiohttp",
        "--collect-all", "multidict",
        "--collect-all", "yarl",
        # ---- ffmpeg ----
        # 三个引擎（m3u8 / yt_dlp / nm3u8dl）都要 ffmpeg 合流。发布版里
        # **只有 dist/doubi-gui/ 会进安装包**（installer/doubi.nsi 就一句
        # ``File /r "${SRC_DIR}\\*.*"``），所以 ffmpeg 必须显式打进来，
        # 否则用户机上没装 ffmpeg 就只能退化到 aiohttp fallback。
        #
        # 用 tools/nm3u8dl/ffmpeg.exe（10.91 MB，N_m3u8DL 专用构建，已实测
        # ``-version`` 可跑）而不是 imageio_ffmpeg 轮子里的那个（83.6 MB）：
        # 同样一个可执行文件，省 72.7 MB。imageio_ffmpeg 随之进排除列表。
        "--add-data", f"{FFMPEG_EXE}{sep}tools/nm3u8dl",
        # 自己写的进 src 目录的代码
        "--paths", str(ROOT / "src"),
        # 平台适配器靠 import 副作用自注册，PyInstaller 静态分析
        # 追不到「谁 import 了它们」，必须整包收进来
        "--collect-submodules", "doubi",
        str(launcher),
    ]

    for mod in EXCLUDE_MODULES:
        cmd.insert(4, mod)
        cmd.insert(4, "--exclude-module")

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
        cmd.extend(_browser_add_data(browsers_dir, sep))
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
