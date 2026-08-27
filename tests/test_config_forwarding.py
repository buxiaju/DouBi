"""``AppConfig`` → ``SniffOptions`` 的搬运守卫（M6.16，硬约束 #4）。

这条搬运线和 ``AppConfig`` → ``DownloadOptions`` 是**两条独立的线**：

- 下载期参数（``output_root`` / ``proxy`` / ``rate_limit`` …）同时长在
  ``AppConfig`` 和 ``DownloadOptions`` 上，所以能用「取两个 dataclass 的共有
  字段」自动守卫，就是各入口里的
  ``test_build_options_covers_every_shared_config_field``。
- 解析期参数（``sniff_*``）**只**长在 ``AppConfig`` 上，``DownloadOptions``
  上根本没有对应字段。于是上面那个自动守卫对它们完全无感——漏搬也不会红。

所以 ``sniff_*`` 需要这份单独的守卫，钉死两件事：

1. 字段值真的抵达 ``Sniffer`` 实例（把 ``sniff_duration_sec`` 推离默认值
   15 到 42 再断言，否则「两边都是默认值」会让漏搬的字段恰好相等而隐身，
   ``output_dir_template`` 和 ``resume`` 当年就是这样长期隐身的）。
2. 四个入口（CLI / GUI / REST / MCP）**各自**都调了
   :meth:`GenericAdapter.set_config`。这是唯一注入口，少一个入口，那个入口
   的嗅探设置就是纯摆设：适配器会 lazy 回落到默认 YAML，用户改的值静默丢失，
   而且没有任何报错。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.config import AppConfig
from doubi.core.sniffer import SniffResult
from doubi.platforms.generic.adapter import GenericAdapter


@pytest.fixture(autouse=True)
def _restore_adapter_config():
    """``GenericAdapter._config`` 是类级缓存，测试之间必须还原。

    不还原的话，先跑的用例注入的 42 会漏给后面的用例，让「没注入时回落默认」
    这类断言假绿。
    """
    saved = GenericAdapter._config
    yield
    GenericAdapter._config = saved


# ---------------------------------------------------------------------------
# 1. 字段真的抵达 Sniffer 实例
# ---------------------------------------------------------------------------


class _CapturingSniffer:
    """替身：只记下拿到的 ``SniffOptions``，不起浏览器。"""

    last_options = None

    def __init__(self, options):
        type(self).last_options = options
        self.options = options

    async def sniff(self, url: str) -> SniffResult:
        return SniffResult(page_url=url, page_title="stub", items=[], error="stub")


async def test_sniff_options_forwarded_to_sniffer(monkeypatch):
    """spec 点名的守卫：``sniff_duration_sec=42`` 必须抵达 Sniffer 实例。

    走的是真实路径 ``GenericAdapter.parse()`` → ``sniff_options_from_config()``
    → ``Sniffer(options)``，而不是直接调搬运函数——这样连「adapter 忘了用注入的
    cfg、又去 lazy 读了一遍 YAML」这种错也能抓到。
    """
    monkeypatch.setattr(
        "doubi.platforms.generic.adapter.Sniffer", _CapturingSniffer
    )
    GenericAdapter.set_config(
        AppConfig(
            sniff_duration_sec=42,
            sniff_headless=False,
            sniff_user_agent="probe-agent",
            sniff_auto_play=False,
            sniff_capture_types=("video/mp4",),
        )
    )

    await GenericAdapter().parse("https://example.com/whatever")

    opts = _CapturingSniffer.last_options
    assert opts is not None, "parse() 没有构造 Sniffer，搬运线断了"
    assert opts.duration_sec == 42, "sniff_duration_sec 没抵达 Sniffer"
    assert opts.headless is False, "sniff_headless 没抵达 Sniffer"
    assert opts.user_agent == "probe-agent", "sniff_user_agent 没抵达 Sniffer"
    assert opts.auto_play is False, "sniff_auto_play 没抵达 Sniffer"
    assert opts.capture_types == ("video/mp4",), "sniff_capture_types 没抵达 Sniffer"


async def test_sniff_disabled_short_circuits_before_launching_browser(monkeypatch):
    """``sniff_enabled=False`` 必须在起浏览器**之前**短路。

    只断言「返回了错误项」不够——那样即使白起了一个无头 Chromium 再报错也会
    绿。这里断言 Sniffer 压根没被构造。
    """
    _CapturingSniffer.last_options = None
    monkeypatch.setattr(
        "doubi.platforms.generic.adapter.Sniffer", _CapturingSniffer
    )
    GenericAdapter.set_config(AppConfig(sniff_enabled=False))

    item = await GenericAdapter().parse("https://example.com/whatever")

    assert _CapturingSniffer.last_options is None, "禁用后仍然构造了 Sniffer"
    assert item is not None, "禁用时也要返回错误项，不能返回 None"


# ---------------------------------------------------------------------------
# 2. 四个入口各自都注入了
# ---------------------------------------------------------------------------


_ENTRY_SOURCES = {
    "CLI": SRC / "doubi" / "cli" / "main.py",
    "GUI": SRC / "doubi" / "ui" / "app.py",
    "REST": SRC / "doubi" / "server" / "app.py",
    "MCP": SRC / "doubi" / "mcp" / "server.py",
}


def test_every_entry_calls_set_config():
    """四个入口都必须出现 ``GenericAdapter.set_config``。

    这是源码级断言而不是行为级断言，因为 GUI / MCP 的入口函数一个要真起 Qt
    事件循环、一个要真占 stdio，都不适合在单测里跑。真正要防的失效模式是
    「新加了第五个入口、或重构时把某个入口的注入行删了」，源码级足够钉住。
    """
    missing = [
        name
        for name, path in _ENTRY_SOURCES.items()
        if "GenericAdapter.set_config" not in path.read_text(encoding="utf-8")
    ]
    assert not missing, f"这些入口没有注入嗅探配置（硬约束 #4）: {missing}"


def test_cli_applies_sniff_overrides():
    """CLI：``--sniff-duration`` 压过配置文件，并注入到适配器。"""
    from doubi.cli.main import _apply_sniff_overrides, _build_parser

    args = _build_parser().parse_args(
        ["download", "-u", "https://example.com/x", "--sniff-duration", "7"]
    )
    cfg = _apply_sniff_overrides(args, AppConfig(sniff_duration_sec=42))

    assert cfg.sniff_duration_sec == 7, "命令行没压过配置文件"
    assert GenericAdapter._config is cfg, "CLI 没把叠好的 cfg 注入适配器"


def test_cli_keeps_config_value_when_flag_absent():
    """CLI：不传 ``--sniff-duration`` 时配置文件的值必须留下。

    所有下载参数的 ``default=None`` + ``_pick`` 就是为这条服务的；哪天有人给
    ``--sniff-duration`` 补了个「合理的」argparse 默认值，配置文件就会被那个
    默认值悄悄盖掉，这条会红。
    """
    from doubi.cli.main import _apply_sniff_overrides, _build_parser

    args = _build_parser().parse_args(["download", "-u", "https://example.com/x"])
    cfg = _apply_sniff_overrides(args, AppConfig(sniff_duration_sec=42))

    assert cfg.sniff_duration_sec == 42
    assert cfg.sniff_enabled is True


def test_cli_no_sniff_disables():
    """CLI：``--no-sniff`` 要能显式关掉（布尔的「显式 False」不能被当成没传）。"""
    from doubi.cli.main import _apply_sniff_overrides, _build_parser

    args = _build_parser().parse_args(
        ["download", "-u", "https://example.com/x", "--no-sniff"]
    )
    cfg = _apply_sniff_overrides(args, AppConfig(sniff_enabled=True))

    assert cfg.sniff_enabled is False


def test_rest_applies_sniff_config(monkeypatch):
    """REST：``_apply_sniff_config()`` 读到的 cfg 要原样注入并回传。"""
    from doubi.server import app as app_mod

    probe = AppConfig(sniff_duration_sec=42, sniff_enabled=False)
    monkeypatch.setattr(app_mod, "load_config", lambda _=None: probe)

    cfg = app_mod._apply_sniff_config()

    assert cfg is probe
    assert GenericAdapter._config is probe, "REST 没把 cfg 注入适配器"


def test_mcp_sniff_status_reports_config(monkeypatch):
    """MCP：``sniff_status`` 工具要回报当前 cfg，而不是硬编码的默认值。"""
    from doubi.mcp import server as mcp_mod

    monkeypatch.setattr(
        mcp_mod,
        "load_config",
        lambda _=None: AppConfig(sniff_duration_sec=42, sniff_enabled=False),
    )

    out = mcp_mod._tool_sniff_status({})

    assert out["duration_sec"] == 42
    assert out["enabled"] is False
    assert "available" in out, "缺少 Playwright 可用性自检字段"
