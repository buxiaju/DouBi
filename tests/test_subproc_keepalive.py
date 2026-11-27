"""看门狗 keepalive 通道守护：合并阶段静默 ≠ 冻结。

用户实锤报障（silidm.com 嗅探视频）：分片下载到 100% 后 N_m3u8DL-CLI
进入合并/faststart 阶段，stdout 零输出但输出文件在持续变大。180s 无
输出看门狗把它当冻结杀掉 → 管线自动重试 → 整个下载从零再来。

修法：``run_supervised_subprocess`` 新增 ``keepalive`` 参数——stdout
静默超过阈值时轮询一次；返回真值（文件系统有活动）就重置计时器，
真冻结（磁盘无任何变化）才杀。引擎侧用 ``make_dir_activity_keepalive``
盯输出目录。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

import doubi.engines._subproc as sp
from doubi.engines._subproc import make_dir_activity_keepalive

# 真实子进程：完全不写 stdout，静默 5 秒后正常退出。
_SILENT_CHILD = [sys.executable, "-c", "import time; time.sleep(5)"]


# ===========================================================================
# make_dir_activity_keepalive 单元
# ===========================================================================

def test_keepalive_seeds_then_detects_change(tmp_path: Path):
    ka = make_dir_activity_keepalive(tmp_path)
    # 第一次调用只建基线，不算"活动"。
    assert ka() is False
    # 目录里出现新文件 → 活动为真。
    (tmp_path / "merged.mp4").write_bytes(b"x" * 100)
    assert ka() is True
    # 文件继续长大（合并中的铁证）→ 仍是活动。
    (tmp_path / "merged.mp4").write_bytes(b"x" * 200)
    assert ka() is True
    # 磁盘纹丝不动（真冻结）→ 不是活动。
    assert ka() is False
    assert ka() is False


def test_keepalive_detects_deletion(tmp_path: Path):
    f = tmp_path / "seg.ts"
    f.write_bytes(b"abc")
    ka = make_dir_activity_keepalive(tmp_path)
    ka()  # seed
    f.unlink()
    # --enableDelAfterDone 清理临时分片也是活动。
    assert ka() is True


def test_keepalive_multiple_roots(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    ka = make_dir_activity_keepalive(a, b)
    ka()  # seed
    (b / "part_0.ts").write_bytes(b"z")
    assert ka() is True


def test_keepalive_missing_root_is_not_fatal(tmp_path: Path):
    ka = make_dir_activity_keepalive(tmp_path / "nope")
    # 根目录不存在：快照为空，不抛错。
    assert ka() is False


# ===========================================================================
# 监督器 × keepalive 行为（真实子进程）
# ===========================================================================

def test_watchdog_spares_silent_process_when_keepalive_true():
    """stdout 静默超过阈值 + keepalive 报活 → 不杀，等它自己跑完。"""
    ka_calls: list[int] = []

    def keepalive() -> bool:
        ka_calls.append(1)
        return True

    rc, _ = asyncio.run(sp.run_supervised_subprocess(
        _SILENT_CHILD,
        watchdog_seconds=1.0,
        keepalive=keepalive,
    ))
    assert rc == 0
    # 静默 5s / 看门狗 1s → 至少被咨询过一次；有它在，进程活到了自然退出。
    assert ka_calls


def test_watchdog_spares_with_async_keepalive():
    """keepalive 返回 Awaitable（协程）同样被尊重。"""

    async def keepalive() -> bool:
        return True

    rc, _ = asyncio.run(sp.run_supervised_subprocess(
        _SILENT_CHILD,
        watchdog_seconds=1.0,
        keepalive=keepalive,
    ))
    assert rc == 0


def test_watchdog_kills_when_keepalive_false():
    """keepalive 恒报不活 + stdout 静默 → 照杀（冻结检测不失效）。"""
    with pytest.raises(sp.SubprocessTimeout):
        asyncio.run(sp.run_supervised_subprocess(
            _SILENT_CHILD,
            watchdog_seconds=1.0,
            keepalive=lambda: False,
        ))


def test_watchdog_kills_when_keepalive_raises():
    """keepalive 抛异常 → 视同"无生命证据"，不得卡死监督。"""
    def broken() -> bool:
        raise RuntimeError("probe exploded")

    with pytest.raises(sp.SubprocessTimeout):
        asyncio.run(sp.run_supervised_subprocess(
            _SILENT_CHILD,
            watchdog_seconds=1.0,
            keepalive=broken,
        ))


def test_watchdog_still_kills_without_keepalive():
    """不传 keepalive 时行为不变（回归保障）。"""
    with pytest.raises(sp.SubprocessTimeout):
        asyncio.run(sp.run_supervised_subprocess(
            _SILENT_CHILD,
            watchdog_seconds=1.0,
        ))


# ===========================================================================
# 引擎接线守护：两个 m3u8 引擎必须传 keepalive
# ===========================================================================

def _capture_supervisor(monkeypatch, mod, captured: list[dict]) -> None:
    """把引擎命名空间里的 run_supervised_subprocess 换成记录 kwargs 的桩。

    注意打在 *mod* 上而非 _subproc 上——引擎是 from-import，拷贝了名字。
    """
    async def fake_supervise(args, **kwargs):
        captured.append(kwargs)
        return 0, b""

    monkeypatch.setattr(mod, "run_supervised_subprocess", fake_supervise)


def _make_hls_item():
    from doubi.core.models import Author, MediaItem, MediaType, Platform

    return MediaItem(
        platform=Platform.GENERIC,
        item_id="probe42",
        title="probe",
        author=Author(),
        media_type=MediaType.VIDEO,
        source_url="https://cdn.example.com/video.m3u8",
        extra={"is_hls": True},
    )


def _make_download_options(tmp_path: Path):
    from doubi.core.models import DownloadOptions

    return DownloadOptions(output_root=tmp_path)


def test_nm3u8dl_passes_keepalive(tmp_path: Path, monkeypatch):
    """nm3u8dl 引擎必须把 out_dir 的活动探针交给监督器。"""
    import doubi.engines.nm3u8dl as mod

    captured: list[dict] = []
    _capture_supervisor(monkeypatch, mod, captured)
    engine = mod.Nm3u8dlEngine(cli_path=str(tmp_path / "fake-cli.exe"))
    asyncio.run(engine.download(
        _make_hls_item(), _make_download_options(tmp_path),
    ))
    assert captured, "supervisor was never called"
    assert "keepalive" in captured[0]
    # 探针必须是可调用对象（绑定在 out_dir 上）。
    assert callable(captured[0]["keepalive"])


def test_m3u8_passes_keepalive(tmp_path: Path, monkeypatch):
    """m3u8(ffmpeg) 引擎同款保护——faststart 第二遍也静默。"""
    import doubi.engines.m3u8 as mod

    captured: list[dict] = []
    _capture_supervisor(monkeypatch, mod, captured)
    engine = mod.M3u8Engine(ffmpeg_path=str(tmp_path / "fake-ffmpeg.exe"))
    # 绕过 TLS 探测（fake 二进制探不了），直接走 ffmpeg 路径。
    monkeypatch.setattr(engine, "_can_ffmpeg_fetch", lambda url: True)
    asyncio.run(engine.download(
        _make_hls_item(), _make_download_options(tmp_path),
    ))
    assert captured, "supervisor was never called"
    assert callable(captured[0]["keepalive"])
