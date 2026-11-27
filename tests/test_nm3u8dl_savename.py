"""--saveName 契约守护：v3.0.2 不接受含目录链的 saveName。

用户实锤报障（silidm.com 嗅探视频，0.4.3 仍未修）：引擎把
``out_dir\\<basename>`` 整条路径塞进 --saveName，N_m3u8DL-CLI v3.0.2
把 ``\\`` 扁平化成 ``.``，在 workDir 顶层产出一个怪名 .ts 文件；
引擎按预期 stem 顶层找 ``.mp4`` 找不到 → 判失败 → 管线重试 →
"下载到 100% 后重新下载"。CLI 侧日志（任务结束 + File: xxx.ts）
证明每次下载其实都成功了，纯粹是引擎认不出自己的产出。

契约（以 CLI 日志实锤为准）：
* ``--saveName`` 只传 basename——最终文件落在 ``workDir/<basename>.<CLI自选扩展名>``
* ``--workDir`` 传绝对路径（决定论，不依赖继承的 CWD）
* 引擎收尾按 stem 递归匹配产出文件，扩展名不同（.ts vs .mp4）不算失败
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import doubi.engines.nm3u8dl as nm3u8dl_mod
from doubi.engines.base import safe_basename_for_item


def _make_hls_item():
    from doubi.core.models import Author, MediaItem, MediaType, Platform

    return MediaItem(
        platform=Platform.GENERIC,
        item_id="probe42",
        title="silidm.com_-_视频_1",
        author=Author(),
        media_type=MediaType.VIDEO,
        source_url="https://cdn.example.com/video.m3u8",
        extra={"is_hls": True},
    )


def _make_download_options(tmp_path: Path):
    from doubi.core.models import DownloadOptions

    return DownloadOptions(output_root=tmp_path)


def _run_engine(tmp_path: Path, monkeypatch, *, cli_side_effect) -> list[list[str]]:
    """跑一次引擎下载，桩掉监督器；返回每次调用的 argv 列表。

    ``cli_side_effect(work_dir)`` 在监督器"返回 rc=0"前被调用——work_dir
    从 argv 里的 --workDir 解析，即引擎真正交给 CLI 的输出目录。
    返回列表末尾追加引擎的返回值 ok。
    """
    argvs: list[list[str]] = []

    async def fake_supervise(args, **kwargs):
        argv = [str(a) for a in args]
        argvs.append(argv)
        if cli_side_effect is not None:
            wd = argv[argv.index("--workDir") + 1]
            cli_side_effect(Path(wd))
        return 0, b""

    monkeypatch.setattr(nm3u8dl_mod, "run_supervised_subprocess", fake_supervise)
    engine = nm3u8dl_mod.Nm3u8dlEngine(cli_path=str(tmp_path / "fake-cli.exe"))
    ok = asyncio.run(engine.download(
        _make_hls_item(), _make_download_options(tmp_path),
    ))
    assert argvs, "supervisor was never called"
    argvs.append(ok)  # type: ignore[arg-type]
    return argvs


def test_savename_is_plain_basename(tmp_path: Path, monkeypatch):
    """--saveName 的值不得含任何路径分隔符——v3.0.2 会把它扁平化成怪名。"""
    argvs = _run_engine(tmp_path, monkeypatch, cli_side_effect=None)
    argv = argvs[0]
    idx = argv.index("--saveName")
    save_name = argv[idx + 1]
    assert "\\" not in save_name, f"--saveName 携带目录链: {save_name}"
    assert "/" not in save_name, f"--saveName 携带目录链: {save_name}"
    assert save_name == safe_basename_for_item(_make_hls_item())


def test_workdir_is_absolute(tmp_path: Path, monkeypatch):
    """--workDir 必须是绝对路径，文件核对不依赖继承的 CWD。"""
    argvs = _run_engine(tmp_path, monkeypatch, cli_side_effect=None)
    argv = argvs[0]
    idx = argv.index("--workDir")
    from pathlib import Path as P

    assert P(argv[idx + 1]).is_absolute()


def test_ts_output_with_different_ext_counts_as_success(tmp_path: Path, monkeypatch):
    """CLI 二进制合并产 .ts（我们要 .mp4）：stem 相同即认领，判成功。"""
    basename = safe_basename_for_item(_make_hls_item())

    def cli_wrote_ts(root: Path) -> None:
        # 模拟 v3.0.2 行为：最终文件落在 workDir 根，扩展名自选 .ts。
        (root / f"{basename}.ts").write_bytes(b"\x47" * 64)

    argvs = _run_engine(tmp_path, monkeypatch, cli_side_effect=cli_wrote_ts)
    assert argvs[-1] is True, "CLI 明明产出了文件（扩展名不同），引擎却判失败"


def test_missing_output_still_fails(tmp_path: Path, monkeypatch):
    """rc=0 但 workDir 里没有任何 stem 匹配的文件 → 仍判失败（不放过真异常）。"""
    argvs = _run_engine(tmp_path, monkeypatch, cli_side_effect=None)
    assert argvs[-1] is False


def test_nested_output_found_by_recursive_stem_match(tmp_path: Path, monkeypatch):
    """产出文件藏在子目录里也能被递归 stem 匹配认领。"""
    basename = safe_basename_for_item(_make_hls_item())
    def cli_wrote_nested(work_dir: Path) -> None:
        nested = work_dir / "unexpected" / "subdir"
        nested.mkdir(parents=True)
        (nested / f"{basename}.ts").write_bytes(b"\x47" * 32)

    argvs = _run_engine(tmp_path, monkeypatch, cli_side_effect=cli_wrote_nested)
    assert argvs[-1] is True


def test_mp4_container_skips_binary_merge(tmp_path: Path, monkeypatch):
    """目标容器 mp4 → 不得传 --enableBinaryMerge（二进制拼接只能产 .ts，
    必须走 ffmpeg 合并才能直接产 .mp4，尊重设置里的容器格式）。"""
    argvs = _run_engine(tmp_path, monkeypatch, cli_side_effect=None)
    argv = argvs[0]
    assert "--enableBinaryMerge" not in argv
    assert "--enableMuxFastStart" in argv


def test_non_mp4_ext_keeps_binary_merge(tmp_path: Path, monkeypatch):
    """非 mp4 容器（如嗅探声明 flv）保留二进制合并。"""
    from doubi.core.models import Author, MediaItem, MediaType, Platform

    item = MediaItem(
        platform=Platform.GENERIC,
        item_id="probe43",
        title="probe43",
        author=Author(),
        media_type=MediaType.VIDEO,
        source_url="https://cdn.example.com/video.m3u8",
        extra={"is_hls": True, "sniff_ext": "flv"},
    )

    argvs: list[list[str]] = []

    async def fake_supervise(args, **kwargs):
        argvs.append([str(a) for a in args])
        return 0, b""

    monkeypatch.setattr(nm3u8dl_mod, "run_supervised_subprocess", fake_supervise)
    engine = nm3u8dl_mod.Nm3u8dlEngine(cli_path=str(tmp_path / "fake-cli.exe"))
    asyncio.run(engine.download(item, _make_download_options(tmp_path)))
    assert argvs, "supervisor was never called"
    assert "--enableBinaryMerge" in argvs[0]
