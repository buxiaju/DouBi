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
# N_m3u8DL-CLI 主程序（1.37 MB）。0.3.13 之前只带 ffmpeg 不带 CLI，
# 发布版 nm3u8dl 引擎永远「binary not found」降级到 m3u8 引擎——
# 开发机上能跑是因为引擎按 cwd 找到了仓库 tools/ 里的那份。
NMCCLI_EXE = ROOT / "tools" / "nm3u8dl" / "N_m3u8DL-CLI_v3.0.2.exe"


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
    # --- imageio_ffmpeg（83.6 MB）：整个包就是一个 ffmpeg-win-x86_64.exe
    #     的壳。改用 tools/nm3u8dl/ffmpeg.exe（10.91 MB）打包，三个引擎的
    #     _find_ffmpeg / _resolve_ffmpeg 都已加上 bundled 分支优先查找 ---
    "imageio_ffmpeg",
    "imageio",
    # --- PIL：M6.16 起 B 站登录对话框用 QR 码真实图片替代了 ASCII,
    #     ``qrcode.make_image(image_factory=PilImage)`` 必须用 PIL
    #     才能输出 8-bit grayscale 图像给 ``QImage`` 吃(QImage.Format_Grayscale8)。
    #     见 docs/CHANGELOG.md M6.16 段。Pillow 始终是 ``qrcode`` 的
    #     运行时依赖,排了 PIL 等于隐式把 qfluentwidgets 的 image_utils
    #     也连带排掉——12.8 MB 体积换不回来,反而引入运行时 ImportError。
    #     这条"曾经是 12.8 MB 精简"的注释留在历史记录里,实际已被撤销 ---
    # "PIL",
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
    # --- 0.3.14 实测的死重（旧 dist 里有、运行时永不加载） ---
    # mypy + ast_serialize：mypy 的编译扩展（.pyd 约 4MB），来源是某
    #     个 hook 的依赖推导；GUI 全量 import 后 sys.modules 里没有它们。
    # Cryptodome：pycryptodome。m3u8 的 AES-128 解密走 cryptography
    #     （延迟导入），yt-dlp 对 pycryptodome 也只有可选路径 + 纯 Python
    #     回退。两个加密库留一个就够，留被真正 import 的那个。
    "mypy",
    "ast_serialize",
    "Cryptodome",
]

#: 仅 GUI 构建排除的模块。
#:
#: 与 EXCLUDE_MODULES 的区别：EXCLUDE_MODULES 是「整个 src 都不许
#: import」的硬禁令（test_packaging_slim 会扫全源码）；这里的模块
#: 被 src 里的**非 GUI 入口**合法使用（doubi/server/schemas.py 用
#: pydantic 定义 REST 模型），只是冻结 GUI 进程永不走到那条 import
#: 路径——GUI exe 只跑 ui，REST/MCP 服务走 pip 安装形态。
#: pydantic + pydantic_core 合计约 11MB。
GUI_ONLY_EXCLUDES = [
    "pydantic",
    "pydantic_core",
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


def _required_browser_revisions() -> dict[str, str]:
    """读**已装** Playwright 的 browsers.json，拿各二进制的目标 revision。

    本机 ``ms-playwright`` 目录里经常同时躺着多个 ``chromium-XXXX`` /
    ``ffmpeg-XXXX``——Playwright 升级过、旧 revision 没被清掉（实测：
    1.62.0 要 chromium 1234 + ffmpeg 1011，目录里还残留一个 451 MB 的
    chromium-1254 和一个 ffmpeg-1013）。打包脚本原先把整个目录逐项
    收进包，残留 revision 就是纯死重，光 chromium-1254 就吃掉安装包
    1/3 体积。

    Playwright 是 collect-all 进包的（含自带的 driver），所以以
    ``playwright/driver/package/browsers.json`` 为准；读不到（文件
    缺失 / JSON 坏 / 结构变了）就返回空表——调用方对空表的处理是
    **不过滤**，宁可打包退回旧行为，也不冒少收运行时必需二进制的险。
    """
    import json

    import playwright

    manifest = (
        Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
    )
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    revisions: dict[str, str] = {}
    for browser in data.get("browsers", []):
        name = browser.get("name", "")
        revision = browser.get("revision")
        # 只认会在磁盘上落成 <name>-<revision> 目录的条目；
        # chromium_headless_shell 已被 _BROWSER_SKIP_PREFIXES 整类排除。
        if name in ("chromium", "ffmpeg", "winldd") and revision:
            revisions[name] = str(revision)
    return revisions


def _browser_add_data(browsers_dir: Path, sep: str) -> list[str]:
    """把 ms-playwright 目录按子项展开成 --add-data 参数，跳过死重。

    两类跳过：

    - ``chromium_headless_shell-*``（独立 headless 二进制，sniffer /
      browser_login 都走 ``channel="chromium"`` 用不到，见上方注释）；
    - **revision 不匹配的** ``chromium-*`` / ``ffmpeg-*`` / ``winldd-*``：
      以已装 Playwright 的 browsers.json 为准
      （见 :func:`_required_browser_revisions`），映射为空就不过滤——
      宁可多收也不少收。

    不整目录一把梭的原因：``--add-data src;dst`` 没有排除语法，想少收
    一个子目录就只能自己逐项列。目标路径保持
    ``playwright_browsers/<子目录名>``，与启动壳设的
    ``PLAYWRIGHT_BROWSERS_PATH`` 布局一致。
    """
    required = _required_browser_revisions()
    args: list[str] = []
    for child in sorted(browsers_dir.iterdir()):
        if child.name.startswith(_BROWSER_SKIP_PREFIXES):
            print(f"跳过（体积精简）：{child.name}")
            continue
        if required:
            stale = False
            for name, revision in required.items():
                prefix = f"{name}-"
                if child.name.startswith(prefix) and child.name != prefix + revision:
                    print(
                        f"跳过（revision 不匹配，已装 Playwright 要 "
                        f"{prefix}{revision}）：{child.name}"
                    )
                    stale = True
                    break
            if stale:
                continue
        if child.is_dir():
            dst = f"playwright_browsers/{child.name}"
        else:
            dst = "playwright_browsers"
        args.append("--add-data")
        args.append(f"{child}{sep}{dst}")
    return args

#: 构建后修剪：按文件名删除的 Qt DLL（大小写敏感，与 dist 实际文件名一致）。
#: 只删「纯 Widgets 应用确定用不到」的运行时 DLL；QtCore/Gui/Widgets/Svg/
#: Network/Xml 及所有 MSVC 运行库绝不进名单。
_PRUNE_DLLS = (
    "Qt6Quick.dll",
    "Qt6Qml.dll",
    "Qt6QmlMeta.dll",
    "Qt6QmlModels.dll",
    "Qt6QmlWorkerScript.dll",
    "Qt6QmlCompilerPlus.dll",     # 部分版本会带
    "Qt6QuickWidgets.dll",
    "Qt6QuickControls2.dll",
    "Qt6QuickControls2Impl.dll",
    "Qt6QuickTemplates2.dll",
    "Qt6Quick3D.dll",
    "Qt6Quick3DRuntimeRender.dll",
    "Qt6Quick3DUtils.dll",
    "Qt6Pdf.dll",
    "Qt6PdfWidgets.dll",
    "Qt6OpenGL.dll",
    "Qt6OpenGLWidgets.dll",
    "Qt6VirtualKeyboard.dll",
    "opengl32sw.dll",             # Mesa 软件渲染回退（20 MB）
    "d3dcompiler_47.dll",         # Qt 自带的 shader 编译器（Quick/3D 才用）
    "chrome_elf.dll",             # WebEngine 残留（若钩子拉了它）
    "libEGL.dll",                 # 仅 WebEngine/Quick 需要；Widgets 走系统 GDI
    "libGLESv2.dll",
)

#: 修剪后保留的翻译文件（Qt 自身 UI 文案：对话框按钮 / 菜单右键项等）。
#: zh_CN 之外留 en 作为回退——Qt 在 .qm 缺 key 时自动落回英文源串。
_KEEP_TRANSLATIONS = ("qt_zh_CN.qm", "qtbase_zh_CN.qm", "qt_en.qm", "qtbase_en.qm")


def _prune_qt_dead_weight(pyside_dir: Path) -> None:
    """删除 dist 里 PySide6 的死重 DLL 与多余翻译。

    存在才删、逐项打印体积，最后汇总省了多少。目录不存在（onefile /
    结构变化）时静默跳过——修剪是锦上添花，不能让构建失败。
    """
    if not pyside_dir.is_dir():
        return
    saved = 0
    for name in _PRUNE_DLLS:
        f = pyside_dir / name
        if f.is_file():
            size = f.stat().st_size
            f.unlink()
            saved += size
            print(f"修剪 Qt 死重：{name}（{size / 1048576:.1f} MB）")

    trans = pyside_dir / "translations"
    if trans.is_dir():
        for f in sorted(trans.rglob("*.qm")):
            if f.name in _KEEP_TRANSLATIONS:
                continue
            size = f.stat().st_size
            f.unlink()
            saved += size
        # 删空的子目录（categories/help 等）
        for sub in sorted(trans.iterdir(), reverse=True):
            if sub.is_dir() and not any(sub.iterdir()):
                sub.rmdir()
        print(f"翻译文件保留：{', '.join(_KEEP_TRANSLATIONS)}")

    if saved:
        print(f"Qt 死重修剪完成：共省 {saved / 1048576:.1f} MB")


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
#
# 0.4.0 补丁（实锤案例：用户机器登录报「Executable doesn't exist at
# _internal\\playwright\\driver\\package\\.local-browsers\\...」）：node
# driver 只在 ``PLAYWRIGHT_BROWSERS_PATH="0"`` 时才找包内 .local-browsers
# ——精简构建没有捆绑内核，这个目录必然不存在；而 "0" 可能来自用户
# 终端会话里为别的项目设的临时环境变量，应用不该被它拖死。规则：
#   * 包内有捆绑内核 → 钉死到包内目录（优先级最高）
#   * 否则 env 为 "0" / 相对路径 / 指向不存在的目录 → 清掉，
#     回落 node 默认 %LOCALAPPDATA%\\ms-playwright——正好是功能插件
#     安装内核的目录（plugin_manager._default_browsers_dir）
#   * env 指向真实存在的绝对目录 → 尊重用户，不动
try:
    _base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    _browsers = os.path.join(_base, "playwright_browsers")
    if os.path.isdir(_browsers):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browsers
    else:
        _env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
        if not _env or _env == "0" or not os.path.isdir(_env):
            # playwright/_impl/_transport.py 在冻结进程里会对 driver 子进程
            # env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")——迫使 node
            # driver 找包内 .local-browsers（为捆绑内核的构建设计）。精简
            # 构建没捆绑内核，"0" 必然失败。setdefault 不覆盖已有键，所以
            # 这里必须【显式设值】为 node 默认缓存目录（也是功能插件安装
            # 内核的目录），而不是清掉。
            if sys.platform == "win32":
                _local = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
                    "~/AppData/Local"
                )
                _default = os.path.join(_local, "ms-playwright")
            elif sys.platform == "darwin":
                _default = os.path.expanduser("~/Library/Caches/ms-playwright")
            else:
                _default = os.path.expanduser("~/.cache/ms-playwright")
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _default
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
    parser.add_argument(
        "--with-sniffer", action="store_true",
        help="捆绑 playwright 与 Chromium 内核（0.3.14 起默认**不**捆绑——"
             "最精简安装包，通用嗅探降级为可选插件，用户在设置页一键安装，"
             "内核落在用户 LOCALAPPDATA。本开关用于回退旧行为或特殊分发）。",
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
    if not NMCCLI_EXE.is_file():
        # 同上：缺 CLI 时构建照样成功，但发布版 nm3u8dl 引擎会静默
        # 「binary not found」降级，HLS 下载少一条主力路径。
        print(
            f"缺少 {NMCCLI_EXE}。它是发布版 nm3u8dl 引擎的主程序，"
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
        # ---- N_m3u8DL-CLI 主程序 ----
        # 引擎 _find_cli 的 script_dir 候选（__file__ 上溯三级 =
        # _internal）会在这里找到它。0.3.13 之前漏打，发布版
        # nm3u8dl 引擎永远「binary not found」降级。
        "--add-data", f"{NMCCLI_EXE}{sep}tools/nm3u8dl",
        # 自己写的进 src 目录的代码
        "--paths", str(ROOT / "src"),
        # 平台适配器靠 import 副作用自注册，PyInstaller 静态分析
        # 追不到「谁 import 了它们」，必须整包收进来
        "--collect-submodules", "doubi",
        str(launcher),
    ]
    if args.with_sniffer:
        # ---- Playwright + Chromium 浏览器二进制（--with-sniffer 才捆绑） ----
        # 0.3.14 起默认最精简：不收 Chromium 内核（430 MB），保留
        # playwright 客户端 + 自带 node 驱动（约 107 MB）——驱动既是
        # 运行时执行器，也是插件安装器的下载器（冻结版没有 python -m，
        # core/plugin_manager._browser_install_cmd 调驱动 cli.js 装内核）。
        # --with-sniffer 用于回退旧行为 / 特殊分发。
        cmd += [
            "--collect-all", "playwright",
        ]
        # 捆绑模式额外收内核
        cmd.extend(_browser_add_data(browsers_dir, sep))
        print(f"捆绑 Playwright 浏览器内核：{browsers_dir}")
    else:
        # 最精简（默认）：仍要 --collect-all playwright（客户端 5MB +
        # node 驱动 102MB），只跳过内核 --add-data。
        cmd += [
            "--collect-all", "playwright",
        ]
        print(
            "体积精简：不捆绑 Chromium 内核（通用嗅探降级为可选插件，"
            "用户在设置页一键安装；playwright 客户端 + node 驱动保留，"
            "它们是插件安装的执行器）"
        )

    for mod in EXCLUDE_MODULES:
        cmd.insert(4, mod)
        cmd.insert(4, "--exclude-module")

    # GUI 构建专属排除（server 栈；见 GUI_ONLY_EXCLUDES 注释）
    for mod in GUI_ONLY_EXCLUDES:
        cmd.insert(4, mod)
        cmd.insert(4, "--exclude-module")

    # ---- Chromium 浏览器二进制（仅 --with-sniffer 捆绑模式） ----
    # ms-playwright 目录位置：
    #   Windows: %USERPROFILE%\AppData\Local\ms-playwright
    #   POSIX:   ~/.cache/ms-playwright
    # 该目录下有 chromium-XXXX / ffmpeg-XXXX 等子目录，整目录打包进去。
    # 默认（最精简）跳过：内核由插件安装器在用户机上按需下载。
    browsers_dir = _find_playwright_browsers_dir() if args.with_sniffer else None
    if args.with_sniffer and browsers_dir is None:
        print(
            "警告：未找到 Playwright 浏览器目录（ms-playwright），"
            "捆绑模式将没有内核，运行时嗅探不可用。",
            file=sys.stderr,
        )
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

    # ---- 构建后修剪（0.3.14）：EXCLUDE_MODULES 拦不到的 Qt 死重 ----
    # PyInstaller 的 Qt 钩子按「插件依赖」工作：platforms 插件引用
    # Qt6Gui，imageformats 引用 Qt6Pdf，virtualkeyboard 插件引用
    # Qt6Quick/Qml……于是这些 DLL 连带 96 个语言的翻译文件被硬拉进
    # dist，哪怕 Python 导入图里根本没有它们（EXCLUDE_MODULES 只作用于
    # 导入图）。实测 dist/doubi-gui/_internal/PySide6 里躺着：
    #   Qt6Quick/Qml/QmlMeta/QmlModels/QmlWorkerScript (约 13.6 MB)
    #   Qt6Pdf (4.5 MB) / Qt6OpenGL (1.9 MB) / Qt6VirtualKeyboard
    #   opengl32sw.dll (20 MB，Mesa 软件渲染回退)
    #   translations/ 96 个 .qm（约 6.7 MB，中文用户只需要 2 个）
    # 修剪安全性依据（同 EXCLUDE_MODULES 的「sys.modules 判据」）：
    #   1. grep 全 src 无任何 Quick/Qml/Pdf/VirtualKeyboard import；
    #   2. 探针 import doubi.ui.app 后 sys.modules 无上述模块；
    #   3. 纯 Widgets 应用不发起 OpenGL 调用，软件渲染回退永远走不到
    #      （qfluentwidgets 的圆角/模糊是 QPainter + QSS，不依赖 QSurface）。
    # 误删兜底：修剪名单与 EXCLUDE_MODULES 同源维护，删错模块会在
    # 首次启动/切换主题时立刻崩溃——发版前的隔离静默验收
    # （NSIS /S + 手工开 GUI）就是这道闸。
    dist_dir = ROOT / "dist" / "doubi-gui"
    if args.onedir:
        _prune_qt_dead_weight(dist_dir / "_internal" / "PySide6")

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
