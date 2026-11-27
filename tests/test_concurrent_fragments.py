"""``concurrent_fragments``（单任务分片并发）贯通守护。

一个旋钮四处生效：yt-dlp ``concurrent_fragment_downloads`` / aria2
``split`` / m3u8 分片并发（既有行为，不重测）+ 本次新增的设置页入口
（AppConfig 字段 + nm3u8dl ``--maxThreads``）。设置页 UI 存取与
``_build_options`` 搬运链由同名的 coverage 守护测试把守，这里只补
``load_config`` 三层来源与 nm3u8dl 命令透传。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from doubi.core.config import AppConfig, DEFAULTS, load_config
from doubi.core.models import Author, DownloadOptions, MediaItem, MediaType, Platform


# ---------------------------------------------------------------------------
# config：默认值 / YAML / 环境变量 三层来源
# ---------------------------------------------------------------------------


def test_default_is_4():
    cfg = AppConfig()
    assert cfg.concurrent_fragments == DEFAULTS["concurrent_fragments"] == 4


def test_load_config_reads_yaml_value(tmp_path):
    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text("concurrent_fragments: 8\n", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.concurrent_fragments == 8


def test_load_config_coerces_bad_value_to_default(tmp_path):
    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text("concurrent_fragments: abc\n", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.concurrent_fragments == DEFAULTS["concurrent_fragments"]


def test_env_override_beats_yaml(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text("concurrent_fragments: 8\n", encoding="utf-8")
    monkeypatch.setenv("DOUBI_CONCURRENT_FRAGMENTS", "6")
    cfg = load_config(cfg_file)
    assert cfg.concurrent_fragments == 6


# ---------------------------------------------------------------------------
# nm3u8dl：--maxThreads 透传（--maxThreads 是 v3.0.2 的分片线程参数）
# ---------------------------------------------------------------------------


def _make_item() -> MediaItem:
    return MediaItem(
        platform=Platform.GENERIC,
        item_id="test123",
        title="test item",
        author=Author(),
        media_type=MediaType.VIDEO,
        source_url="https://example.com/video.m3u8",
        extra={"is_hls": True},
    )


def _capture_supervisor(monkeypatch, captured: list) -> None:
    """把 run_supervised_subprocess 换成记录 argv 的桩，立刻返回成功。

    nm3u8dl 是 ``from ._subproc import run_supervised_subprocess``——
    from-import 把名字拷进了自己的命名空间，桩必须打在
    ``doubi.engines.nm3u8dl`` 上，打在 _subproc 上拦不住。
    """
    import doubi.engines.nm3u8dl as nm

    async def fake_supervise(args, **kwargs):
        captured.append(list(args))
        return 0, b""

    monkeypatch.setattr(nm, "run_supervised_subprocess", fake_supervise)


def _run_download(tmp_path, options: DownloadOptions, captured: list) -> bool:
    import doubi.engines.nm3u8dl as nm

    engine = nm.Nm3u8dlEngine()
    assert engine._cli is None or Path(engine._cli).exists() or True
    # CLI / ffmpeg 找不到时 download() 提前 return，cmd 就不会构造——
    # 两个路径都钉上假二进制，保证走到命令构造这一步。
    fake_cli = tmp_path / "N_m3u8DL-CLI_v3.0.2.exe"
    fake_cli.write_bytes(b"stub")
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_bytes(b"stub")
    engine._cli = str(fake_cli)
    engine._ffmpeg = str(fake_ffmpeg)

    return asyncio.run(engine.download(_make_item(), options))


def test_nm3u8dl_passes_concurrent_fragments_as_max_threads(tmp_path, monkeypatch):
    captured: list = []
    _capture_supervisor(monkeypatch, captured)
    options = DownloadOptions(output_root=tmp_path, concurrent_fragments=8)
    _run_download(tmp_path, options, captured)

    assert captured, "supervisor must be reached with the CLI argv"
    argv = captured[0]
    idx = argv.index("--maxThreads")
    assert argv[idx + 1] == "8"


def test_nm3u8dl_clamps_fragments_to_at_least_1(tmp_path, monkeypatch):
    captured: list = []
    _capture_supervisor(monkeypatch, captured)
    options = DownloadOptions(output_root=tmp_path, concurrent_fragments=0)
    _run_download(tmp_path, options, captured)

    argv = captured[0]
    idx = argv.index("--maxThreads")
    assert argv[idx + 1] == "1"
