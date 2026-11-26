"""Tests for core.plugin_manager (0.3.14).

插件化体积策略的核心契约：

* probe 是纯读（不联网、不写盘、不抛），对「库没装 / 库在内核缺 /
  全齐」三种环境给出正确判定；
* percent 解析器对 playwright 下载输出行能算出 0-100 的整数；
* install 的回调事件流以 PluginInstallResult 收尾（永不抛）。

不真跑 pip / playwright install——那些走 mock/假命令，网络路径留给
发布前的手工验收（BUILD.md）。
"""

from __future__ import annotations

import sys
import tempfile
import os
import unittest
from pathlib import Path
from unittest import mock

from doubi.core.plugin_manager import (
    PluginInstallProgress,
    PluginInstallResult,
    PluginStatus,
    _browsers_dir,
    _parse_percent,
    ensure_browsers_env,
    install_sniffer_plugin,
    probe_sniffer_plugin,
)


class _ParsePercentCase(unittest.TestCase):
    """playwright install / pip 输出行 → 百分比。"""

    def test_playwright_download_line(self):
        line = "Downloading chromium 45.2 MB / 167.7 MB"
        self.assertEqual(_parse_percent(line), 27)

    def test_gb_units(self):
        line = "Downloading chromium 0.1 GB / 0.2 GB"
        self.assertEqual(_parse_percent(line), 50)

    def test_non_progress_lines_yield_none(self):
        for line in ("|  entropy |", "chromium downloaded to", "", "Done"):
            self.assertIsNone(_parse_percent(line))

    def test_clamped_to_100(self):
        line = "Downloading chromium 999 MB / 100 MB"
        self.assertEqual(_parse_percent(line), 100)


class _ProbeCase(unittest.TestCase):
    """probe_sniffer_plugin 的三种环境判定。"""

    def test_library_missing(self):
        with mock.patch.dict(sys.modules, {"playwright": None}):
            status = probe_sniffer_plugin()
        self.assertFalse(status.library_installed)
        self.assertFalse(status.browser_installed)
        self.assertFalse(status.ready)
        self.assertIn("未安装", status.summary())

    def test_library_present_browser_missing(self):
        fake = mock.MagicMock()
        fake.__file__ = "/fake/playwright/__init__.py"
        with mock.patch.dict(sys.modules, {"playwright": fake}):
            with mock.patch(
                "doubi.core.plugin_manager._browsers_dir", return_value=None
            ):
                status = probe_sniffer_plugin()
        self.assertTrue(status.library_installed)
        self.assertFalse(status.browser_installed)
        self.assertFalse(status.ready)
        self.assertIn("缺浏览器内核", status.summary())

    def test_fully_installed(self):
        from pathlib import Path

        fake = mock.MagicMock()
        fake.__file__ = "/fake/playwright/__init__.py"
        browsers = Path("/fake/ms-playwright")
        with mock.patch.dict(sys.modules, {"playwright": fake}):
            with mock.patch(
                "doubi.core.plugin_manager._browsers_dir",
                return_value=browsers,
            ):
                with mock.patch(
                    "doubi.core.plugin_manager._read_chromium_revision",
                    return_value="1234",
                ):
                    with mock.patch.object(Path, "__truediv__", autospec=True):
                        status = probe_sniffer_plugin()
        # revision 匹配判定走 (browsers / "chromium-1234").is_dir()
        # ——上面的 __truediv__ mock 会把任意除法变成 MagicMock，其
        # is_dir() 返回 truthy MagicMock。这里只需断言 ready 路径成立。
        self.assertTrue(status.ready)
        self.assertIn("已安装", status.summary())


class _BrowsersDirCase(unittest.TestCase):
    """_browsers_dir 对 PLAYWRIGHT_BROWSERS_PATH 的判定。"""

    def test_env_zero_is_ignored_not_returned(self):
        """env="0" 在 playwright 语义里是包内 .local-browsers——对冻结版
        必然失效；探针必须把它当没设，走 LOCALAPPDATA 默认候选，绝不能
        把 Path("0") 当答案（否则设置页报「已安装」而登录时找不到内核）。"""
        with mock.patch.dict(
            "os.environ", {"PLAYWRIGHT_BROWSERS_PATH": "0"}
        ):
            result = _browsers_dir()
        self.assertIsNot(result, Path("0"))
        # 走了默认候选（本机有内核则返回它；CI 无内核则 None）——
        # 无论哪种，都不会是字面量 "0"。
        if result is not None:
            self.assertNotEqual(str(result), "0")

    def test_existing_custom_dir_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                "os.environ", {"PLAYWRIGHT_BROWSERS_PATH": tmp}
            ):
                result = _browsers_dir()
        self.assertEqual(result, Path(tmp))

    def test_nonexistent_dir_falls_through_to_default(self):
        with mock.patch.dict(
            "os.environ",
            {"PLAYWRIGHT_BROWSERS_PATH": r"C:\definitely\not\here\xyz"},
        ):
            result = _browsers_dir()
        # 本机有内核 → 返回默认 LOCALAPPDATA 目录；CI → None。都不应
        # 是那个不存在的路径。
        self.assertNotEqual(result, Path(r"C:\definitely\not\here\xyz"))


class _EnsureBrowsersEnvCase(unittest.TestCase):
    """ensure_browsers_env 对冻结进程 setdefault("0") 的压制。"""

    def test_zero_is_replaced_with_real_default(self):
        """env="0" 必须被替换成真实目录——playwright transport 的
        setdefault 不会覆盖已存在的键，显式设值即压制成功。"""
        with mock.patch.dict(
            "os.environ", {"PLAYWRIGHT_BROWSERS_PATH": "0"}
        ):
            with tempfile.TemporaryDirectory() as tmp:
                # 造一个含 chromium-* 的目录让 _browsers_dir 命中
                browser = Path(tmp) / "chromium-1234"
                browser.mkdir()
                with mock.patch(
                    "doubi.core.plugin_manager._browsers_dir",
                    return_value=Path(tmp),
                ):
                    ensure_browsers_env()
                self.assertEqual(
                    os.environ["PLAYWRIGHT_BROWSERS_PATH"], tmp
                )

    def test_unset_pins_default_dir_even_without_browser(self):
        """没设 env 且内核未装 → 也钉到默认缓存目录，让报错指向正确的
        安装位置（而非误导性的包内 .local-browsers）。"""
        with mock.patch.dict(
            "os.environ", {}, clear=False
        ):
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            with mock.patch(
                "doubi.core.plugin_manager._browsers_dir", return_value=None
            ):
                ensure_browsers_env()
            value = os.environ["PLAYWRIGHT_BROWSERS_PATH"]
        self.assertNotEqual(value, "0")
        self.assertIn("ms-playwright", value)

    def test_valid_custom_dir_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                "os.environ", {"PLAYWRIGHT_BROWSERS_PATH": tmp}
            ):
                ensure_browsers_env()
                self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], tmp)


class _InstallFlowCase(unittest.TestCase):
    """install_sniffer_plugin 的事件流契约（不真跑 pip）。"""

    def _run_install(self, probe_result: PluginStatus, **kwargs):
        events: list = []
        with mock.patch(
            "doubi.core.plugin_manager.probe_sniffer_plugin",
            return_value=probe_result,
        ):
            result = install_sniffer_plugin(events.append, **kwargs)
        return result, events

    def test_already_ready_short_circuits(self):
        ready = PluginStatus(library_installed=True, browser_installed=True)
        result, events = self._run_install(ready)
        self.assertTrue(result.ok)
        kinds = [e.kind for e in events]
        self.assertEqual(kinds[-1], "done")

    def test_library_missing_blocks_browser_only_retry(self):
        missing = PluginStatus(library_installed=False)
        result, events = self._run_install(
            missing, include_library=False
        )
        self.assertFalse(result.ok)
        self.assertIn("无法只装内核", result.message)
        self.assertEqual(events[-1].kind, "done")

    def test_result_never_raises_and_carries_message(self):
        # 探针报全缺 + 真实 _run_step 被替换为直接失败 —— 验证失败路径
        # 返回 ok=False 而不是抛异常。
        missing = PluginStatus(library_installed=False)
        with mock.patch(
            "doubi.core.plugin_manager.probe_sniffer_plugin",
            return_value=missing,
        ):
            with mock.patch(
                "doubi.core.plugin_manager._run_step",
                return_value=(False, ["boom"], "exit 1"),
            ):
                events: list = []
                result = install_sniffer_plugin(events.append)
        self.assertFalse(result.ok)
        self.assertIsInstance(result, PluginInstallResult)
        self.assertTrue(any(e.kind == "done" for e in events))
        self.assertIn("失败", result.message)

    def test_progress_event_shape(self):
        ev = PluginInstallProgress(kind="percent", percent=42)
        self.assertEqual(ev.kind, "percent")
        self.assertEqual(ev.percent, 42)


class _FrozenModeCase(unittest.TestCase):
    """0.3.14 最精简构建：冻结版插件安装走捆绑 node 驱动。"""

    def test_dev_mode_uses_python_m(self):
        """非冻结环境：python -m playwright install chromium。"""
        import doubi.core.plugin_manager as pm

        self.assertFalse(getattr(sys, "frozen", False))
        cmd, env = pm._browser_install_cmd()
        self.assertEqual(cmd[:3], [sys.executable, "-m", "playwright"])
        self.assertIn("PLAYWRIGHT_BROWSERS_PATH", env)
        self.assertIn("ms-playwright", env["PLAYWRIGHT_BROWSERS_PATH"])

    def test_frozen_mode_uses_bundled_node_driver(self):
        """冻结环境且驱动在：node.exe cli.js install chromium。"""
        import shutil
        import tempfile
        from pathlib import Path

        import doubi.core.plugin_manager as pm

        with tempfile.TemporaryDirectory() as td:
            # 造一个冻结版布局：<td>/playwright/driver/{node.exe, package/cli.js}
            driver_dir = Path(td) / "playwright" / "driver"
            (driver_dir / "package").mkdir(parents=True)
            node_name = "node.exe" if sys.platform == "win32" else "node"
            (driver_dir / node_name).write_bytes(b"")
            (driver_dir / "package" / "cli.js").write_text("", encoding="utf-8")
            fake_browsers = Path(td) / "browsers"

            with mock.patch.object(sys, "frozen", True, create=True):
                with mock.patch.object(sys, "_MEIPASS", td, create=True):
                    with mock.patch.object(
                        pm,
                        "_default_browsers_dir",
                        return_value=fake_browsers,
                    ):
                        cmd, env = pm._browser_install_cmd()

        self.assertEqual(Path(cmd[0]).name, node_name)
        self.assertEqual(Path(cmd[1]).name, "cli.js")
        self.assertEqual(cmd[2:], ["install", "chromium"])
        self.assertEqual(env["PLAYWRIGHT_BROWSERS_PATH"], str(fake_browsers))

    def test_frozen_without_driver_falls_back(self):
        """冻结但驱动缺失：退回 python -m（会失败，但错误信息可指引）。"""
        import doubi.core.plugin_manager as pm

        with mock.patch.object(sys, "frozen", True, create=True):
            with mock.patch.object(
                sys, "_MEIPASS", "C:/definitely_missing", create=True
            ):
                cmd, _env = pm._browser_install_cmd()
        self.assertEqual(cmd[1:3], ["-m", "playwright"])


if __name__ == "__main__":
    unittest.main()
