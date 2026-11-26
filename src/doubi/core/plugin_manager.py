"""Plugin manager — optional heavy dependencies installed on demand.

0.3.14 起的体积策略：安装包只带**必需**依赖（yt-dlp / PySide6 / aiohttp
等），两类大型可选件降级为「插件」，用户在设置页按需一键安装：

* **通用嗅探插件**（本模块当前唯一管理的插件）：
  playwright Python 客户端（约 30 MB wheel）+ Chromium 内核
  （约 170 MB 下载 / 430 MB 磁盘）。装完后 GenericAdapter 的兜底嗅探
  与抖音浏览器自动登录恢复可用。
* （预留）其他未来插件按同一协议扩展。

设计约束（对齐 AGENTS.md）：

* **平台无关**：纯 stdlib subprocess + 回调，不碰 Qt。GUI / CLI /
  REST 都能驱动同一套安装逻辑。
* **永不抛**：安装过程的任何失败都以 :class:`PluginInstallResult`
  的 ``ok=False`` + ``message`` 收尾——插件安装是锦上添花，不能把
  主程序带崩。
* **进度反馈**：通过 :class:`PluginInstallProgress` 回调实时上报
  （阶段 / 百分比 / 原始日志行），GUI 拿它刷进度条，CLI 拿它打印。
* **检测与安装分离**：:func:`probe_sniffer_plugin` 是纯读操作
  （不联网、不写盘），随时可调；:func:`install_sniffer_plugin`
  才动网络与磁盘。

为什么不用 ``pip`` Python API（``pip._internal``）：那是私有接口，
跨版本不稳定；subprocess 调 ``sys.executable -m pip`` 是官方推荐
且发布版（PyInstaller 冻结环境）同样适用——冻结环境里
``sys.executable`` 就是 doubi-gui.exe 自己，``-m pip`` 不可用时
会明确报错并引导用户手动安装，不会半死不活。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger_name = "doubi.core.plugin_manager"


# ---------------------------------------------------------------------------
# 状态检测（纯读，不联网）
# ---------------------------------------------------------------------------


@dataclass
class PluginStatus:
    """嗅探插件的当前状态，三个布尔量各管一层。"""

    #: ``import playwright`` 成功 —— Python 客户端已装
    library_installed: bool = False
    #: Chromium 内核目录存在且含 ``chromium-*`` —— 可真正 launch
    browser_installed: bool = False
    #: 两层都齐 —— 插件完全可用
    @property
    def ready(self) -> bool:  # noqa: D102 — property docstring below
        """library + browser 都就位才算 ready。"""
        return self.library_installed and self.browser_installed

    def summary(self) -> str:
        """一行人话状态，GUI / CLI 共用。"""
        if self.ready:
            return "已安装，通用嗅探可用"
        if self.library_installed and not self.browser_installed:
            return "已装 Python 组件，缺浏览器内核（约 170 MB 下载）"
        return "未安装（约 170 MB 下载 / 430 MB 磁盘）"


def _browsers_dir() -> Optional[Path]:
    """定位 ms-playwright 目录（与 scripts/build_exe.py 同逻辑）。

    ``PLAYWRIGHT_BROWSERS_PATH="0"`` 特判：这个值在 playwright 语义里是
    「用包内 .local-browsers」，对冻结版必然失效（实锤：设置页探针据此
    报「已安装」，登录时 driver 却找不到内核——两边对 env 的解读不一致）。
    探针把它当没设，走 LOCALAPPDATA 默认目录，与登录时的实际查找保持一致。
    """
    import os

    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env != "0":
        p = Path(env)
        if p.is_dir():
            return p
    if sys.platform == "win32":
        import os as _os

        candidates = [
            Path.home() / "AppData" / "Local" / "ms-playwright",
            Path(_os.environ.get("LOCALAPPDATA", "")) / "ms-playwright",
        ]
    else:
        candidates = [Path.home() / ".cache" / "ms-playwright"]
    for c in candidates:
        try:
            if c.is_dir() and any(c.glob("chromium-*")):
                return c
        except OSError:
            continue
    return None


def _read_chromium_revision() -> Optional[str]:
    """从已装 playwright 的 browsers.json 读 chromium 目标 revision。

    用于区分「内核目录存在但是旧 revision」的场景。读不到返回 None
    （调用方退化为只查目录存在性）。
    """
    try:
        import playwright  # noqa: F401 — 只为拿包路径

        manifest = (
            Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
        )
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 探针永不抛
        return None
    for browser in data.get("browsers", []):
        if browser.get("name") == "chromium" and browser.get("revision"):
            return str(browser["revision"])
    return None


def probe_sniffer_plugin() -> PluginStatus:
    """嗅探插件状态探针。纯读：不联网、不写盘、不抛异常。"""
    status = PluginStatus()
    try:
        import playwright  # noqa: F401

        status.library_installed = True
    except ImportError:
        return status  # 库都没有，内核更无从谈起

    browsers = _browsers_dir()
    if browsers is None:
        return status

    # 目录在，还要确认 revision 匹配（playwright 升级后旧内核不算数）
    revision = _read_chromium_revision()
    if revision is not None:
        status.browser_installed = (browsers / f"chromium-{revision}").is_dir()
    else:
        status.browser_installed = any(browsers.glob("chromium-*"))
    return status


# ---------------------------------------------------------------------------
# 安装（动网络 + 磁盘）
# ---------------------------------------------------------------------------


@dataclass
class PluginInstallProgress:
    """单条进度事件。``kind`` 判别 UI 该刷什么。"""

    #: "stage"  — 进入新阶段（``stage`` / ``stage_detail`` 有值）
    #: "line"   — 安装器输出的一行日志
    #: "percent" — 总体进度百分比（0-100，估算值）
    #: "done"   — 安装结束（看外层 result）
    #: "error"  — 可恢复的中间错误提示
    kind: str
    stage: str = ""          # "library" | "browser" | ""
    stage_detail: str = ""   # 阶段说明（含体积提示）
    message: str = ""        # line / error 的文本
    percent: Optional[int] = None


@dataclass
class PluginInstallResult:
    """安装结果。``ok=False`` 时 ``message`` 是面向用户的原因。"""

    ok: bool
    message: str
    #: 已完成哪些阶段（失败时可能是部分完成：库装上了、内核没装）
    stages_completed: list[str] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        """部分成功（装了库但内核失败）——下次重试只补内核。"""
        return "library" in self.stages_completed and not self.ok


#: 进度回调签名。同步函数，从工作线程调用——GUI 侧自行 marshal 到主线程。
ProgressCallback = Callable[[PluginInstallProgress], None]

#: playwright install chromium 的输出形如「Downloading chromium 45.2 MB / 167.7 MB」
_DOWNLOAD_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(MB|GB|kB)\s*/\s*(\d+(?:\.\d+)?)\s*(MB|GB|kB)", re.I
)

_UNIT_TO_MB = {"kb": 1 / 1024, "mb": 1.0, "gb": 1024.0}


def _parse_percent(line: str) -> Optional[int]:
    """从一行安装输出里抠出百分比（无则 None）。"""
    m = _DOWNLOAD_RE.search(line)
    if not m:
        return None
    got = float(m.group(1)) * _UNIT_TO_MB[m.group(2).lower()]
    total = float(m.group(3)) * _UNIT_TO_MB[m.group(4).lower()]
    if total <= 0:
        return None
    return min(100, max(0, round(got / total * 100)))


def _run_step(
    cmd: list[str],
    *,
    stage: str,
    stage_detail: str,
    on_progress: Optional[ProgressCallback],
    base_percent: int,
    span_percent: int,
    env: Optional[dict] = None,
) -> tuple[bool, list[str], str]:
    """跑一个安装子步骤，逐行读输出并折算进度。

    返回 ``(ok, 输出行列表, 错误摘要)``。超时 30 分钟（Chromium 下载在
    慢网下可能很久，杀早了会留下损坏的半截内核）。
    """
    import os as _os

    merged_env = dict(_os.environ)
    if env:
        merged_env.update(env)
    # 禁用 pip 的缓存进度条噪声，拿干净的可解析行
    merged_env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    merged_env.setdefault("PYTHONIOENCODING", "utf-8")

    lines: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=merged_env,
        )
    except OSError as exc:
        return False, [], f"无法启动安装进程：{exc}"

    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        lines.append(line)
        if on_progress:
            on_progress(PluginInstallProgress(kind="line", message=line, stage=stage))
            percent = _parse_percent(line)
            if percent is not None:
                # 折算进总进度条：本阶段占 span_percent 个点
                total = base_percent + round(percent / 100 * span_percent)
                on_progress(
                    PluginInstallProgress(kind="percent", percent=total, stage=stage)
                )

    rc = proc.wait(timeout=60)
    ok = rc == 0
    summary = "" if ok else f"退出码 {rc}"
    return ok, lines, summary


def _default_browsers_dir() -> Path:
    """用户级持久浏览器目录（显式指定，绝不写进安装目录 / 临时目录）。

    为什么显式指定而不是让 playwright 用默认值：PyInstaller 冻结版的
    启动壳会在**捆绑了内核的旧版安装**里设 ``PLAYWRIGHT_BROWSERS_PATH``
    指向 ``_internal/playwright_browsers``；最精简构建没有这个目录、
    环境变量不设，driver 默认行为才正确。但为防「旧版升级 + 重装插件」
    场景把内核下进临时目录（onefile 的 ``_MEIPASS`` 每次启动都变），
    安装步骤统一钉死到用户持久目录。
    """
    if sys.platform == "win32":
        import os as _os

        base = Path(_os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return base / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _browser_install_cmd() -> tuple[list[str], dict[str, str]]:
    """返回执行 ``playwright install chromium`` 的命令与环境。

    两种运行形态：

    * **开发 / pip 安装**：``sys.executable -m playwright install chromium``
    * **PyInstaller 冻结版**（发布主体）：没有可用的 ``python -m``
      （onefile 里根本没有解释器语义），改调**捆绑在包内**的 playwright
      自带 node 驱动——``playwright/driver/node.exe`` 跑
      ``driver/package/cli.js install chromium``。驱动是运行时必需件，
      发布版一定带着，所以这条路径在发布版恒可用。

    环境统一钉死 ``PLAYWRIGHT_BROWSERS_PATH`` 到用户持久目录
    （见 :func:`_default_browsers_dir`），内核绝不落进临时目录。
    """
    env = {"PLAYWRIGHT_BROWSERS_PATH": str(_default_browsers_dir())}
    if getattr(sys, "frozen", False):
        # 冻结版：playwright 被 --collect-all 收进 _internal/playwright/
        import os as _os

        base = Path(getattr(sys, "_MEIPASS", None) or _os.path.dirname(sys.executable))
        driver = base / "playwright" / "driver"
        node = driver / "node.exe" if sys.platform == "win32" else driver / "node"
        cli = driver / "package" / "cli.js"
        if node.is_file() and cli.is_file():
            return [str(node), str(cli), "install", "chromium"], env
        # 结构异常时退回 python -m（大概率失败，但错误信息会指引手动安装）
        return [sys.executable, "-m", "playwright", "install", "chromium"], env
    return [sys.executable, "-m", "playwright", "install", "chromium"], env


def install_sniffer_plugin(
    on_progress: Optional[ProgressCallback] = None,
    *,
    include_library: bool = True,
) -> PluginInstallResult:
    """安装通用嗅探插件（playwright + Chromium 内核）。

    两阶段：

    1. ``library`` — ``pip install playwright``（约 30 MB）
    2. ``browser`` — ``playwright install chromium``（约 170 MB 下载）

    ``include_library=False`` 跳过阶段 1（部分成功的重试场景）。
    进度经 ``on_progress`` 回调实时上报；结果永不抛异常。
    """
    completed: list[str] = []
    emit = on_progress or (lambda p: None)

    # ---- 阶段 0：前置检查 -------------------------------------------
    status = probe_sniffer_plugin()
    if status.ready:
        emit(PluginInstallProgress(kind="done"))
        return PluginInstallResult(
            ok=True, message="插件已就绪，无需重复安装", stages_completed=["library", "browser"]
        )
    if not include_library and not status.library_installed:
        emit(PluginInstallProgress(kind="done"))
        return PluginInstallResult(
            ok=False,
            message="playwright 库未安装，无法只装内核；请执行完整安装",
        )

    # ---- 阶段 1：pip install playwright -----------------------------
    if include_library and not status.library_installed:
        emit(PluginInstallProgress(
            kind="stage", stage="library",
            stage_detail="正在安装 Python 组件（约 30 MB）…",
        ))
        emit(PluginInstallProgress(kind="percent", percent=2))
        ok, lines, err = _run_step(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir",
             "--disable-pip-version-check", "playwright>=1.40.0"],
            stage="library",
            stage_detail="pip install playwright",
            on_progress=on_progress,
            base_percent=2,
            span_percent=18,
        )
        if not ok:
            tail = "\n".join(lines[-5:]) if lines else err
            emit(PluginInstallProgress(kind="done"))
            return PluginInstallResult(
                ok=False,
                message=f"Python 组件安装失败（{err or '未知原因'}）。\n"
                        f"手动安装：pip install playwright\n\n{tail}",
                stages_completed=completed,
            )
        completed.append("library")
        emit(PluginInstallProgress(kind="percent", percent=20))

    # ---- 阶段 2：playwright install chromium ------------------------
    emit(PluginInstallProgress(
        kind="stage", stage="browser",
        stage_detail="正在下载浏览器内核（约 170 MB，视网速 1-10 分钟）…",
    ))
    browser_cmd, browser_env = _browser_install_cmd()
    ok, lines, err = _run_step(
        browser_cmd,
        stage="browser",
        stage_detail="playwright install chromium",
        on_progress=on_progress,
        base_percent=20,
        span_percent=78,
        env=browser_env,
    )
    if not ok:
        tail = "\n".join(lines[-5:]) if lines else err
        emit(PluginInstallProgress(kind="done"))
        lib_note = "Python 组件已装好，" if "library" in completed else ""
        return PluginInstallResult(
            ok=False,
            message=f"浏览器内核下载失败。{lib_note}下次重试会跳过已完成的步骤。\n"
                    f"手动安装：playwright install chromium\n\n{tail}",
            stages_completed=completed,
        )
    completed.append("browser")

    # ---- 终态复核 ----------------------------------------------------
    final = probe_sniffer_plugin()
    emit(PluginInstallProgress(kind="percent", percent=100))
    emit(PluginInstallProgress(kind="done"))
    if final.ready:
        return PluginInstallResult(
            ok=True, message="通用嗅探插件安装完成", stages_completed=completed
        )
    return PluginInstallResult(
        ok=False,
        message="安装步骤执行完毕，但插件仍未就绪（内核目录校验未通过）。"
                "请重启应用后重试，或手动执行 playwright install chromium。",
        stages_completed=completed,
    )
