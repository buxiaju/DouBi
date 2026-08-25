"""aria2 引擎测试。

用 Mock RPC 客户端验证：
1. ``supports`` 只认有 direct_url/source_url 的 item；
2. ``_build_options`` 把 DownloadOptions 正确映射成 aria2 参数；
3. ``download`` 成功路径（complete）；
4. ``download`` 失败路径（error）；
5. ``download`` 取消路径（cancel_check → remove）；
6. engine_loader 按配置选择引擎；
7. 未知引擎名回退 yt-dlp。

不依赖真实 aria2 二进制——所有 RPC 调用用 Mock 模拟。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from doubi.core.config import AppConfig
from doubi.core.models import Author, DownloadOptions, MediaItem, MediaType, Platform
from doubi.engines.aria2 import Aria2Engine, _parse_rate_limit, _parse_byte_str
from doubi.core.engine_loader import build_default_engine, build_default_pipeline


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _make_item(*, direct_url: Optional[str] = None, source_url: str = "https://example.com/v/1"):
    extra = {}
    if direct_url:
        extra["direct_url"] = direct_url
    return MediaItem(
        platform=Platform.BILIBILI,
        item_id="test123",
        title="测试视频",
        author=Author(name="UP主"),
        media_type=MediaType.VIDEO,
        source_url=source_url,
        extra=extra,
    )


def _make_options(**overrides):
    defaults = dict(
        output_root=Path("/tmp/doubi_test"),
        output_dir_template="{platform}/{author}",
        filename_template="{title}_{item_id}",
        concurrent_fragments=4,
        resume=True,
        rate_limit=None,
        proxy=None,
        user_agent=None,
    )
    defaults.update(overrides)
    return DownloadOptions(**defaults)


class _MockRpcClient:
    """内存 Mock RPC 客户端，按脚本驱动 tellStatus 返回序列。"""

    def __init__(self, *, add_uri_result="gid-1", status_sequence=None):
        self.add_uri_calls = []
        self.remove_calls = []
        self._add_uri_result = add_uri_result
        self._status_seq = list(status_sequence or [])
        self._status_idx = 0

    async def add_uri(self, uris, options):
        self.add_uri_calls.append((uris, options))
        return self._add_uri_result

    async def tell_status(self, gid):
        if self._status_idx < len(self._status_seq):
            s = self._status_seq[self._status_idx]
            self._status_idx += 1
            return s
        # 默认返回 active 状态，避免无限循环
        return {"status": "active", "completedLength": "0", "totalLength": "100"}

    async def remove(self, gid):
        self.remove_calls.append(gid)


# ---------------------------------------------------------------------------
# supports
# ---------------------------------------------------------------------------


def test_supports_true_when_direct_url_present():
    engine = Aria2Engine()
    item = _make_item(direct_url="https://cdn.example.com/v.mp4")
    assert engine.supports(item) is True


def test_supports_true_when_source_url_present():
    """没有 direct_url 但有 source_url 也算支持（回退下载）。"""
    engine = Aria2Engine()
    item = _make_item(source_url="https://example.com/v/1")
    assert engine.supports(item) is True


def test_supports_false_when_no_url():
    engine = Aria2Engine()
    item = MediaItem(
        platform=Platform.BILIBILI, item_id="x", title="", author=Author(),
        media_type=MediaType.VIDEO, source_url="",
    )
    assert engine.supports(item) is False


# ---------------------------------------------------------------------------
# _build_options
# ---------------------------------------------------------------------------


def test_build_options_maps_concurrent_fragments():
    engine = Aria2Engine()
    item = _make_item()
    opts = _make_options(concurrent_fragments=8)
    aria2_opts = engine._build_options(item, opts)
    assert aria2_opts["split"] == "8"
    assert aria2_opts["max-connection-per-server"] == "8"


def test_build_options_maps_rate_limit():
    engine = Aria2Engine()
    item = _make_item()
    opts = _make_options(rate_limit="5M")
    aria2_opts = engine._build_options(item, opts)
    assert aria2_opts["max-download-limit"] == "5M"


def test_build_options_maps_proxy_and_ua():
    engine = Aria2Engine()
    item = _make_item()
    opts = _make_options(
        proxy="http://127.0.0.1:7890",
        user_agent="Mozilla/5.0",
    )
    aria2_opts = engine._build_options(item, opts)
    assert aria2_opts["all-proxy"] == "http://127.0.0.1:7890"
    assert aria2_opts["user-agent"] == "Mozilla/5.0"


def test_build_options_resume_flag():
    engine = Aria2Engine()
    item = _make_item()
    opts_on = _make_options(resume=True)
    opts_off = _make_options(resume=False)
    assert engine._build_options(item, opts_on)["continue"] == "true"
    assert engine._build_options(item, opts_off)["continue"] == "false"


def test_build_options_omits_unset_fields():
    """没设的字段不应出现在 aria2 options 里（避免传空值）。"""
    engine = Aria2Engine()
    item = _make_item()
    opts = _make_options()  # rate_limit/proxy/ua 全是 None
    aria2_opts = engine._build_options(item, opts)
    assert "max-download-limit" not in aria2_opts
    assert "all-proxy" not in aria2_opts
    assert "user-agent" not in aria2_opts


# ---------------------------------------------------------------------------
# download 流程
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_success():
    """complete 状态 → 返回 True，进度上报到 1.0。"""
    statuses = [
        {"status": "active", "completedLength": "0", "totalLength": "1000"},
        {"status": "active", "completedLength": "500", "totalLength": "1000"},
        {"status": "complete", "completedLength": "1000", "totalLength": "1000"},
    ]
    mock = _MockRpcClient(status_sequence=statuses)
    engine = Aria2Engine(rpc_client=mock)

    progress = []
    item = _make_item(direct_url="https://cdn.example.com/v.mp4")
    ok = await engine.download(item, _make_options(), on_progress=progress.append)

    assert ok is True
    assert mock.add_uri_calls[0][0] == ["https://cdn.example.com/v.mp4"]
    assert progress[-1].fraction == 1.0


@pytest.mark.asyncio
async def test_download_error():
    """error 状态 → 返回 False，上报错误进度。"""
    statuses = [
        {"status": "active", "completedLength": "0", "totalLength": "1000"},
        {"status": "error", "errorMessage": "connection refused", "completedLength": "0", "totalLength": "1000"},
    ]
    mock = _MockRpcClient(status_sequence=statuses)
    engine = Aria2Engine(rpc_client=mock)

    progress = []
    item = _make_item(direct_url="https://cdn.example.com/v.mp4")
    ok = await engine.download(item, _make_options(), on_progress=progress.append)

    assert ok is False
    assert "error" in progress[-1].message.lower()


@pytest.mark.asyncio
async def test_download_cancel():
    """cancel_check 触发 → 调用 remove，返回 False。"""
    statuses = [
        {"status": "active", "completedLength": "100", "totalLength": "1000"},
    ]
    mock = _MockRpcClient(status_sequence=statuses)
    engine = Aria2Engine(rpc_client=mock)

    item = _make_item(direct_url="https://cdn.example.com/v.mp4")
    # 第二次轮询时取消
    call_count = {"n": 0}
    def cancel_after_one():
        call_count["n"] += 1
        return call_count["n"] >= 2

    opts = _make_options()
    opts.cancel_check = cancel_after_one
    ok = await engine.download(item, opts)

    assert ok is False
    assert len(mock.remove_calls) == 1
    assert mock.remove_calls[0] == "gid-1"


@pytest.mark.asyncio
async def test_download_no_direct_url_returns_false():
    """没有 direct_url 也没有 source_url → 立即失败。"""
    engine = Aria2Engine()
    item = MediaItem(
        platform=Platform.BILIBILI, item_id="x", title="",
        author=Author(), media_type=MediaType.VIDEO, source_url="",
    )
    ok = await engine.download(item, _make_options())
    assert ok is False


@pytest.mark.asyncio
async def test_download_add_uri_failure_returns_false():
    """addUri 抛错 → 返回 False，不上报进度崩溃。"""
    mock = MagicMock()
    mock.add_uri = AsyncMock(side_effect=RuntimeError("RPC connection refused"))
    mock.tell_status = AsyncMock(return_value={"status": "complete"})
    mock.remove = AsyncMock()

    engine = Aria2Engine(rpc_client=mock)
    item = _make_item(direct_url="https://cdn.example.com/v.mp4")
    progress = []
    ok = await engine.download(item, _make_options(), on_progress=progress.append)

    assert ok is False
    assert "adduri" in progress[-1].message.lower() or "error" in progress[-1].message.lower()


# ---------------------------------------------------------------------------
# engine_loader 配置选择
# ---------------------------------------------------------------------------


def test_build_default_engine_yt_dlp_by_default():
    from doubi.engines.yt_dlp import YtDlpEngine
    engine = build_default_engine()
    assert isinstance(engine, YtDlpEngine)


def test_build_default_engine_aria2_when_configured():
    cfg = AppConfig(engine="aria2", aria2_rpc_url="http://localhost:6800/rpc")
    engine = build_default_engine(cfg)
    assert isinstance(engine, Aria2Engine)
    assert engine._rpc_url == "http://localhost:6800/rpc"


def test_build_default_engine_unknown_falls_back_yt_dlp():
    from doubi.engines.yt_dlp import YtDlpEngine
    cfg = AppConfig(engine="nonexistent_engine")
    engine = build_default_engine(cfg)
    assert isinstance(engine, YtDlpEngine)


def test_build_default_pipeline_passes_cfg_to_engine():
    from doubi.engines.aria2 import Aria2Engine
    cfg = AppConfig(engine="aria2")
    pipeline = build_default_pipeline(cfg=cfg)
    assert isinstance(pipeline.engine, Aria2Engine)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def test_parse_rate_limit_passthrough():
    assert _parse_rate_limit("5M") == "5M"
    assert _parse_rate_limit(None) is None
    assert _parse_rate_limit("") is None
    assert _parse_rate_limit("  ") is None


def test_parse_byte_str_handles_strings():
    assert _parse_byte_str("12345") == 12345
    assert _parse_byte_str(None) == 0
    assert _parse_byte_str("not-a-number") == 0
    assert _parse_byte_str(123) == 123
