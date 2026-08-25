"""CLI 端的配置层叠：命令行 > 配置文件 > 内置默认。

历史上 ``_cmd_download`` 里有一行 ``cfg = load_config(args.config)`` 从头到尾
没被读过，而 argparse 把 config.py 的默认值抄了一份当自己的 default，于是
``doubi download`` 是四个入口里唯一完全无视配置文件的那个——而且它抄的那份
默认值还和 ``DEFAULTS`` 不一致（``--no-thumbnail`` 反推出 ``write_thumbnail``
默认为 True，而 ``DEFAULTS["write_thumbnail"]`` 是 False）。

这组测试钉死三件事：
    1. 用户没传时，配置文件生效；
    2. 用户传了时，命令行压过配置文件（布尔的「显式关闭」也要能压过）；
    3. ``AppConfig`` 和 ``DownloadOptions`` 共有的字段一个都不能漏（结构守护，
       和 GUI / REST 两端同形）。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from doubi.cli.main import _build_options, _build_parser, _resolve_concurrency
from doubi.core.config import AppConfig
from doubi.core.models import DownloadOptions


def _args(*argv: str):
    """Parse a ``download`` invocation, mimicking real command-line entry."""
    return _build_parser().parse_args(["download", "-u", "https://example.com/x", *argv])


# ---------------------------------------------------------------------------
# 第一层：没传就用配置文件
# ---------------------------------------------------------------------------


def test_config_file_wins_when_no_flag_given():
    cfg = AppConfig(
        output_root=Path("/tmp/from-config"),
        output_dir_template="{platform}/cfg",
        filename_template="cfg_{item_id}",
        container="mkv",
        max_quality="1080p",
        write_thumbnail=True,
        write_metadata_json=True,
        write_nfo=True,
        write_danmaku=True,
        write_subtitles=True,
        resume=False,
        rate_limit="9M",
        proxy="http://127.0.0.1:1080",
    )
    options = _build_options(_args(), cfg)

    assert options.output_root == Path("/tmp/from-config")
    assert options.output_dir_template == "{platform}/cfg"
    assert options.filename_template == "cfg_{item_id}"
    assert options.container == "mkv"
    assert options.max_quality == "1080p"
    assert options.write_thumbnail is True
    assert options.write_metadata_json is True
    assert options.write_nfo is True
    assert options.write_danmaku is True
    assert options.write_subtitles is True
    assert options.resume is False
    assert options.rate_limit == "9M"
    assert options.proxy == "http://127.0.0.1:1080"


def test_concurrency_falls_back_to_config():
    cfg = AppConfig(concurrent_jobs=7)
    assert _resolve_concurrency(_args(), cfg) == 7


# ---------------------------------------------------------------------------
# 第二层：传了就压过配置文件
# ---------------------------------------------------------------------------


def test_cli_value_flags_override_config():
    cfg = AppConfig(
        output_root=Path("/tmp/from-config"),
        container="mkv",
        max_quality="1080p",
        rate_limit="9M",
        proxy="http://127.0.0.1:1080",
        concurrent_jobs=7,
    )
    args = _args(
        "-o", "/tmp/from-cli",
        "--output-template", "{platform}/cli",
        "--filename", "cli_{item_id}",
        "--container", "mp4",
        "--quality", "4k",
        "--rate-limit", "1M",
        "--proxy", "http://127.0.0.1:7890",
        "--concurrent", "2",
    )
    options = _build_options(args, cfg)

    assert options.output_root == Path("/tmp/from-cli")
    assert options.output_dir_template == "{platform}/cli"
    assert options.filename_template == "cli_{item_id}"
    assert options.container == "mp4"
    assert options.max_quality == "4k"
    assert options.rate_limit == "1M"
    assert options.proxy == "http://127.0.0.1:7890"
    assert _resolve_concurrency(args, cfg) == 2


@pytest.mark.parametrize(
    "flag, field",
    [
        ("thumbnail", "write_thumbnail"),
        ("metadata", "write_metadata_json"),
        ("nfo", "write_nfo"),
        ("danmaku", "write_danmaku"),
        ("subtitles", "write_subtitles"),
        ("resume", "resume"),
    ],
)
def test_boolean_switch_overrides_config_in_both_directions(flag: str, field: str):
    """``--x`` 和 ``--no-x`` 都必须能压过配置文件。

    「显式关闭」这一半是 ``store_true`` 表达不出来的：它的 False 和「用户没说」
    完全同形，所以叠加层只能把配置值当默认，用户永远关不掉配置里打开的东西。
    这里对每个开关正反各测一次，就是为了防止退回 ``store_true``。
    """
    # 配置说关 → 命令行 --x 打开
    cfg_off = AppConfig(**{field: False})
    assert getattr(_build_options(_args(f"--{flag}"), cfg_off), field) is True

    # 配置说开 → 命令行 --no-x 关闭
    cfg_on = AppConfig(**{field: True})
    assert getattr(_build_options(_args(f"--no-{flag}"), cfg_on), field) is False


def test_documented_negative_flag_spellings_still_parse():
    """QUICKSTART 里已经公开的写法不能因为换成 BooleanOptionalAction 而失效。"""
    args = _args("--no-resume", "--no-thumbnail", "--no-metadata",
                 "--subtitles", "--danmaku", "--nfo")
    assert args.resume is False
    assert args.thumbnail is False
    assert args.metadata is False
    assert args.subtitles is True
    assert args.danmaku is True
    assert args.nfo is True


def test_unspecified_switches_stay_none():
    """没传的开关必须是 None，否则叠加层无法分辨「没说」和「说了关」。"""
    args = _args()
    for name in ("thumbnail", "metadata", "nfo", "danmaku", "subtitles", "resume",
                 "output", "output_template", "filename", "container", "quality",
                 "concurrent", "rate_limit", "proxy", "database", "manifest"):
        assert getattr(args, name) is None, f"{name} should default to None, got {getattr(args, name)!r}"


# ---------------------------------------------------------------------------
# database / manifest 的三态
# ---------------------------------------------------------------------------


def test_database_and_manifest_come_from_config():
    cfg = AppConfig(database=True, database_path=Path("cfg.db"),
                    manifest_path=Path("cfg.jsonl"))
    options = _build_options(_args(), cfg)
    assert options.database == Path("cfg.db")
    assert options.manifest == Path("cfg.jsonl")


def test_database_disabled_in_config_yields_none():
    cfg = AppConfig(database=False, database_path=Path("cfg.db"))
    assert _build_options(_args(), cfg).database is None


def test_explicit_paths_override_config():
    cfg = AppConfig(database=True, database_path=Path("cfg.db"),
                    manifest_path=Path("cfg.jsonl"))
    options = _build_options(
        _args("--database", "cli.db", "--manifest", "cli.jsonl"), cfg)
    assert options.database == Path("cli.db")
    assert options.manifest == Path("cli.jsonl")


def test_no_database_beats_everything():
    """一次性关闭开关的优先级高于显式路径，也高于配置文件。"""
    cfg = AppConfig(database=True, database_path=Path("cfg.db"),
                    manifest_path=Path("cfg.jsonl"))
    options = _build_options(
        _args("--no-database", "--database", "cli.db", "--no-manifest"), cfg)
    assert options.database is None
    assert options.manifest is None


# ---------------------------------------------------------------------------
# 第三层：结构守护（和 GUI / REST 同形）
# ---------------------------------------------------------------------------


def test_build_options_covers_every_shared_config_field():
    """Guard against the *next* added field being dropped on the CLI side.

    与 ``tests/test_server.py`` / ``tests/test_ui_empty_parse.py`` 里的同名测试
    同形：不枚举今天的字段，而是取 ``AppConfig`` 与 ``DownloadOptions`` 的共有
    字段名，先把每个字段都推离自己的默认值，再断言它确实到达了。推离这一步是
    必需的——两个 dataclass 声明了相同默认值时，漏搬的字段比对起来恰好相等，
    ``output_dir_template`` 和 ``resume`` 当年就是这样一直隐身的。

    CLI 此前没有这层守护，是四个入口里唯一的缺口。
    """
    cfg_names = {f.name for f in dataclasses.fields(AppConfig)}
    opt_names = {f.name for f in dataclasses.fields(DownloadOptions)}
    shared = cfg_names & opt_names
    # ``database`` 是变形搬运（bool -> 路径或 None），``extra`` 只属于配置。
    shared -= {"database", "extra"}
    assert shared, "sanity: the two dataclasses must overlap"

    cfg = AppConfig()
    for name in shared:
        current = getattr(cfg, name)
        if isinstance(current, bool):
            setattr(cfg, name, not current)
        elif isinstance(current, str):
            setattr(cfg, name, current + "_probe")
        elif isinstance(current, Path):
            setattr(cfg, name, current / "probe")
        elif current is None:
            setattr(cfg, name, "probe")
        else:
            pytest.fail(f"extend this test for {name}: {type(current)!r}")

    options = _build_options(_args(), cfg)
    missing = [
        name for name in sorted(shared)
        if getattr(options, name) != getattr(cfg, name)
    ]
    assert not missing, f"_build_options drops config fields: {missing}"


def test_build_options_loads_config_when_not_passed(monkeypatch, tmp_path):
    """省略 cfg 参数时必须自己去读配置——这正是当年那行死代码的位置。"""
    import doubi.cli.main as cli_mod

    sentinel = AppConfig(container="mkv", output_root=tmp_path)
    seen: list[object] = []

    def _fake_load(path):
        seen.append(path)
        return sentinel

    monkeypatch.setattr(cli_mod, "load_config", _fake_load)

    args = _build_parser().parse_args(
        ["-c", "some/where.yml", "download", "-u", "https://example.com/x"])
    options = _build_options(args)

    assert seen == [Path("some/where.yml")], "must honour the global -c/--config"
    assert options.container == "mkv"
