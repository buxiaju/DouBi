"""DouBi CLI — entry point.

Subcommands:
    doubi platforms          list registered platform adapters
    doubi download           download one or more URLs
    doubi auth               manage login state per platform
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Iterable

from .. import __version__
from ..core.config import AppConfig, load_config
from ..core.engine_loader import build_default_pipeline
from ..core.logger import quiet_external_loggers, setup_logger
from ..core.models import DownloadOptions
from ..core.pipeline import ProgressEvent
from ..core.registry import PlatformRegistry

# Trigger platform adapter registration
from .. import platforms  # noqa: F401
from ..platforms.generic import GenericAdapter
from . import auth_cmd


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doubi",
        description="DouBi - Multi-platform media downloader (yt-dlp backed).",
    )
    parser.add_argument("-V", "--version", action="version", version=f"doubi {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    parser.add_argument(
        "-c", "--config", type=Path, default=None,
        help="path to YAML config (see config.example.yml)",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # ---- platforms --------------------------------------------------
    p_ls = sub.add_parser("platforms", help="list registered platform adapters")
    p_ls.set_defaults(handler=_cmd_platforms)

    # ---- download ---------------------------------------------------
    p_dl = sub.add_parser("download", help="download one or more URLs")
    p_dl.add_argument("-u", "--url", action="append", default=[],
                      help="URL to download (can be passed multiple times)")
    p_dl.add_argument("--batch", type=Path, default=None,
                      help="path to a text file with one URL per line")
    # 下面这些下载选项一律 default=None，含义是「用户没说」。
    #
    # 不能把 config.py 的默认值抄成 argparse 的默认值：那样 argparse 会在解析时
    # 就把它填上，运行时再也分不清「用户显式传了 --container mp4」和「这是默认
    # 值」，于是配置文件要么永远赢（命令行失效），要么永远输（配置文件失效）。
    # 用 None 占位，真正的三层优先级（命令行 > 配置文件 > 内置默认）交给
    # ``_build_options()`` 去叠。
    p_dl.add_argument("-o", "--output", type=Path, default=None,
                      help="output root directory (config: output_root, default: ./Downloaded)")
    p_dl.add_argument("--output-template", default=None,
                      help="directory template relative to --output "
                           "(config: output_dir_template, default: '{platform}/{author}/{media_type}')")
    p_dl.add_argument("--format", default=None,
                      help="yt-dlp format selector (e.g. 'bestvideo*+bestaudio/best')")
    p_dl.add_argument("--quality", default=None,
                      help="quality preset: best | 4k | 1080p | ... (config: max_quality, default: best)")
    p_dl.add_argument("--container", default=None, choices=["mp4", "mkv"],
                      help="output container (config: container, default: mp4)")
    p_dl.add_argument("--filename", default=None,
                      help="output filename template (config: filename_template, "
                           "default: '{title}_{item_id}')")
    p_dl.add_argument("--concurrent", type=int, default=None,
                      help="max concurrent downloads (config: concurrent_jobs, default: 3)")
    p_dl.add_argument("--rate-limit", default=None, help="rate limit, e.g. 5M")
    p_dl.add_argument("--proxy", default=None, help="HTTP proxy, e.g. http://127.0.0.1:7890")

    # BooleanOptionalAction 同时生成 ``--x`` 和 ``--no-x``，所以 --no-thumbnail /
    # --no-metadata / --no-resume 这些已经写进文档的写法全部保持可用，同时多出了
    # 显式打开的那一半（配置文件关掉了、只想这一次开）。default=None 才能表达
    # 「没说」——store_true 的 False 和「用户明确要关」无法区分。
    p_dl.add_argument("--thumbnail", action=argparse.BooleanOptionalAction, default=None,
                      help="write cover image sidecar (config: write_thumbnail)")
    p_dl.add_argument("--metadata", action=argparse.BooleanOptionalAction, default=None,
                      help="write .info.json sidecar (config: write_metadata_json)")
    p_dl.add_argument("--nfo", action=argparse.BooleanOptionalAction, default=None,
                      help="emit NFO sidecar (config: write_nfo)")
    p_dl.add_argument("--danmaku", action=argparse.BooleanOptionalAction, default=None,
                      help="download danmaku (config: write_danmaku)")
    p_dl.add_argument("--subtitles", action=argparse.BooleanOptionalAction, default=None,
                      help="download subtitles (config: write_subtitles)")
    p_dl.add_argument("--resume", action=argparse.BooleanOptionalAction, default=None,
                      help="resume partial downloads instead of restarting (config: resume)")

    # 通用嗅探（generic 兜底适配器）。未知 URL 会走 Playwright 嗅探，这两个
    # 开关控制它的时长和总开关。--no-sniff 由 BooleanOptionalAction 生成。
    p_dl.add_argument("--sniff-duration", type=int, default=None, metavar="N",
                      help="seconds to sniff an unknown URL for media (5-60, "
                           "config: sniff_duration_sec, default: 15)")
    p_dl.add_argument("--sniff", action=argparse.BooleanOptionalAction, default=None,
                      help="enable generic sniffing for unknown URLs; use --no-sniff "
                           "to skip the headless browser entirely (config: sniff_enabled)")

    p_dl.add_argument("--strategy", default=None,
                      help="for container URLs, choose strategy (e.g. post, like, space, favlist)")
    p_dl.add_argument("--database", type=Path, default=None,
                      help="SQLite database for dedup/history "
                           "(config: database_path, default: doubi.db; use --no-database to disable)")
    p_dl.add_argument("--no-database", action="store_true",
                      help="disable SQLite dedup/history for this run")
    p_dl.add_argument("--manifest", type=Path, default=None,
                      help="JSONL manifest path (config: manifest_path, "
                           "default: download_manifest.jsonl; use --no-manifest to disable)")
    p_dl.add_argument("--no-manifest", action="store_true",
                      help="disable manifest writing for this run")
    p_dl.set_defaults(handler=_cmd_download)

    # ---- auth -------------------------------------------------------
    p_auth = sub.add_parser("auth", help="manage platform login state")
    auth_sub = p_auth.add_subparsers(dest="auth_command", required=True, metavar="PLATFORM")

    # auth status
    p_auth_st = auth_sub.add_parser("status", help="show current login state for all platforms")
    p_auth_st.set_defaults(handler=auth_cmd.cmd_auth_status)

    # auth bilibili
    p_auth_b = auth_sub.add_parser("bilibili", help="log in to B 站")
    p_auth_b.add_argument("--import", dest="import_file", type=Path, default=None,
                          help="import cookies from a Netscape / JSON file instead of scanning a QR")
    p_auth_b.add_argument("-o", "--output", type=Path, default=None,
                          help="destination cookie file (default: ~/.doubi/cookies/bilibili.txt)")
    p_auth_b.add_argument("--poll-interval", type=float, default=2.0,
                          help="seconds between poll requests (default: 2)")
    p_auth_b.add_argument("--timeout", type=float, default=180.0,
                          help="max seconds to wait for the QR scan (default: 180)")
    p_auth_b.add_argument("--no-browser", action="store_true",
                          help="skip the Playwright auto-extract (manual cookie import only)")
    p_auth_b.add_argument("--headless", action="store_true",
                          help="run the Playwright browser headless (you'll need a way to display the QR)")
    p_auth_b.set_defaults(handler=auth_cmd.cmd_auth_bilibili)

    # auth douyin
    p_auth_d = auth_sub.add_parser("douyin", help="log in to 抖音 (Playwright auto-login)")
    p_auth_d.add_argument("--import", dest="import_file", type=Path, default=None,
                          help="import cookies from a Netscape / JSON file")
    p_auth_d.add_argument("--legacy-json", dest="legacy_json", type=Path, default=None,
                          help="import a douyin-downloader cookies.json")
    p_auth_d.add_argument("-o", "--output", type=Path, default=None,
                          help="destination cookie file (default: ~/.doubi/cookies/douyin.txt)")
    p_auth_d.add_argument("--timeout", type=float, default=180.0,
                          help="max seconds to wait for the browser login (default: 180)")
    p_auth_d.add_argument("--headless", action="store_true",
                          help="run the Playwright browser headless")
    p_auth_d.set_defaults(handler=auth_cmd.cmd_auth_douyin)

    # ---- migrate ----------------------------------------------------
    p_mig = sub.add_parser("migrate", help="one-shot migration from a legacy database")
    p_mig.add_argument("--from", dest="source", choices=["douyin", "bilibili"], required=True,
                       help="source format")
    p_mig.add_argument("--path", dest="src_path", type=Path, required=True,
                       help="path to the legacy .db file")
    p_mig.add_argument("--into", dest="dest", type=Path, default=Path("doubi.db"),
                       help="destination doubi.db (default: ./doubi.db)")
    p_mig.set_defaults(handler=_cmd_migrate)

    # ---- live --------------------------------------------------------
    p_live = sub.add_parser("live", help="record a live stream (currently 抖音)")
    p_live.add_argument("-u", "--url", required=True,
                        help="live URL (e.g. https://live.douyin.com/123456)")
    p_live.add_argument("-o", "--output", type=Path, default=Path("./Downloaded"),
                        help="output root directory (default: ./Downloaded)")
    p_live.add_argument("--max-duration", type=float, default=0.0,
                        help="max seconds to record (0 = until the stream ends, default: 0)")
    p_live.add_argument("--cookies", type=Path, default=None,
                        help="path to a Netscape cookies.txt (for gated rooms)")
    p_live.add_argument("--proxy", default=None, help="HTTP proxy URL")
    p_live.set_defaults(handler=_cmd_live)

    # ---- serve -------------------------------------------------------
    p_serve = sub.add_parser("serve", help="run the REST API server")
    p_serve.add_argument("--host", default="127.0.0.1",
                         help="监听地址（默认 127.0.0.1，仅本机可连）")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--token", default=None,
                         help="API token；留空则读环境变量 DOUBI_API_TOKEN")
    p_serve.add_argument("--allow-insecure", action="store_true",
                         help="允许在没有 token 的情况下监听非回环地址（危险）")
    p_serve.set_defaults(handler=_cmd_serve)

    # ---- mcp ---------------------------------------------------------
    p_mcp = sub.add_parser("mcp", help="run the MCP stdio bridge")
    p_mcp.set_defaults(handler=_cmd_mcp)

    return parser


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_platforms(args: argparse.Namespace) -> int:
    adapters = PlatformRegistry.all()
    if not adapters:
        print("No platform adapters registered.", file=sys.stderr)
        return 1
    print(f"Registered platforms ({len(adapters)}):")
    for a in adapters:
        print(f"  - {a.name:<12} {a.display_name}  types: {', '.join(a.supported_media_types()) or '-'}")
    return 0


def _pick(cli_value, cfg_value):
    """Return the command-line value when the user actually supplied one.

    ``None`` 是解析器约定的「用户没说」，此时回落到配置文件。布尔开关必须用
    ``is not None`` 判断而不是真值判断——``--no-resume`` 传进来是 ``False``，
    用真值判断会把它当成「没说」，于是显式关闭永远失效。
    """
    return cfg_value if cli_value is None else cli_value


def _build_options(args: argparse.Namespace, cfg: AppConfig | None = None) -> DownloadOptions:
    """Assemble :class:`DownloadOptions` for the CLI surface.

    这是 CLI 端唯一的 ``AppConfig → DownloadOptions`` 搬运点，和 GUI 的
    ``ParsePage._build_options`` / REST 的 ``server.app._build_options``
    地位相同：引擎、file_layout、pipeline 都只读 ``DownloadOptions``，任何
    在这里漏掉的字段都会静默回落到 dataclass 默认值，表现为「配置文件在
    命令行下不生效」。新增配置项时这里是最容易忘的第五处。

    优先级：命令行 > 配置文件 > 内置默认（内置默认由 ``load_config`` 保证，
    所以这里只需要叠前两层）。

    这里只做「搬运」，不做路径规范化：``expanduser()`` / ``resolve()`` 留给
    调用方（见 :func:`_cmd_download`）。混进来会让本函数的输出不再逐字段等于
    配置值，守护测试就没法用「字段是否原样到达」这一条判据了。
    """
    if cfg is None:
        cfg = load_config(args.config)

    # --no-database / --no-manifest 是「本次运行关掉」的一次性开关，优先级
    # 高于 --database/--manifest 显式给的路径，也高于配置文件里的开关。
    if args.no_database:
        database = None
    else:
        database = _pick(args.database, cfg.database_path if cfg.database else None)

    manifest = None if args.no_manifest else _pick(args.manifest, cfg.manifest_path)

    return DownloadOptions(
        output_root=_pick(args.output, cfg.output_root),
        output_dir_template=_pick(args.output_template, cfg.output_dir_template),
        filename_template=_pick(args.filename, cfg.filename_template),
        container=_pick(args.container, cfg.container),
        max_quality=_pick(args.quality, cfg.max_quality),
        format_id=args.format,
        write_thumbnail=_pick(args.thumbnail, cfg.write_thumbnail),
        write_metadata_json=_pick(args.metadata, cfg.write_metadata_json),
        write_nfo=_pick(args.nfo, cfg.write_nfo),
        write_danmaku=_pick(args.danmaku, cfg.write_danmaku),
        write_subtitles=_pick(args.subtitles, cfg.write_subtitles),
        resume=_pick(args.resume, cfg.resume),
        duplicate_policy=cfg.duplicate_policy,
        rate_limit=_pick(args.rate_limit, cfg.rate_limit),
        proxy=_pick(args.proxy, cfg.proxy),
        database=database,
        manifest=manifest,
    )


def _resolve_concurrency(args: argparse.Namespace, cfg: AppConfig) -> int:
    """并发数不在 DownloadOptions 上（它是调度参数，不是下载参数），单独叠。"""
    return int(_pick(args.concurrent, cfg.concurrent_jobs))


def _apply_sniff_overrides(args: argparse.Namespace, cfg: AppConfig) -> AppConfig:
    """把 ``--sniff-duration`` / ``--no-sniff`` 叠到 ``cfg``，并注入 GenericAdapter。

    ``sniff_*`` 字段**不在** :class:`DownloadOptions` 上——它们是解析期参数
    （怎么找到媒体 URL），不是下载期参数（怎么把文件搬下来），所以走不了
    ``_build_options`` 那条搬运线，``test_build_options_covers_every_shared_config_field``
    也看不见它们。:meth:`GenericAdapter.set_config` 是 ``AppConfig → Sniffer``
    的唯一注入口，四个入口（CLI/GUI/REST/MCP）各自负责调用它，漏掉哪个，
    那个入口的嗅探设置就静默失效（硬约束 #4）。

    优先级同其他下载参数：命令行 > 配置文件 > 内置默认。
    """
    cfg.sniff_enabled = bool(_pick(getattr(args, "sniff", None), cfg.sniff_enabled))
    cfg.sniff_duration_sec = int(
        _pick(getattr(args, "sniff_duration", None), cfg.sniff_duration_sec)
    )
    GenericAdapter.set_config(cfg)
    return cfg


def _cmd_download(args: argparse.Namespace) -> int:
    setup_logger("DEBUG" if args.verbose else "INFO", verbose=args.verbose)
    quiet_external_loggers()

    urls = list(args.url)
    if args.batch:
        urls.extend(_read_url_file(args.batch))
    if not urls:
        print("Error: no URLs provided. Use -u or --batch.", file=sys.stderr)
        return 2

    cfg = load_config(args.config)
    _apply_sniff_overrides(args, cfg)
    options = _build_options(args, cfg)
    # 路径规范化在这里做而不是在 _build_options 里，理由见那边的 docstring。
    options.output_root = Path(options.output_root).expanduser().resolve()
    options.output_root.mkdir(parents=True, exist_ok=True)

    concurrent = _resolve_concurrency(args, cfg)
    return asyncio.run(_run_downloads(urls, options, concurrent, args.verbose, args.strategy))


def _cmd_migrate(args: argparse.Namespace) -> int:
    """One-shot legacy DB → doubi.db migration."""
    setup_logger("INFO")
    if not args.src_path.exists():
        print(f"Error: source not found: {args.src_path}", file=sys.stderr)
        return 1

    async def _do() -> int:
        from ..core.storage.database import Database
        db = Database(args.dest)
        await db.initialize()
        if args.source == "douyin":
            n = await db.migrate_from_legacy(args.src_path)
        elif args.source == "bilibili":
            from ..core.storage.migrate import migrate_bili23_to_doubi
            n = await migrate_bili23_to_doubi(args.src_path, db)
        else:
            return 1
        await db.close()
        return n

    n = asyncio.run(_do())
    print(f"Migrated {n} rows from {args.src_path} → {args.dest}")
    return 0


def _cmd_live(args: argparse.Namespace) -> int:
    """Record a 抖音 live stream."""
    setup_logger("INFO")
    from ..platforms.douyin.live import LiveRecorder

    output_root = args.output.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    cookies = str(args.cookies) if args.cookies else None

    async def _do():
        async with LiveRecorder(cookies_file=cookies, proxy=args.proxy) as rec:
            return await rec.record(
                args.url,
                output_root=output_root,
                max_duration=args.max_duration,
            )

    try:
        result = asyncio.run(_do())
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if result.output_path:
        print(f"Saved: {result.output_path}  ({result.bytes_written:,} bytes)")
    else:
        print("No output file was produced.", file=sys.stderr)
    print(f"Duration: {result.elapsed:.1f}s   End reason: {result.ended_reason}")
    return 0 if result.ended_reason != "error" else 1


def _cmd_serve(args: argparse.Namespace) -> int:
    """Run the REST API server.

    透传成 ``doubi-serve`` 的参数而不是直接调 ``build_app``：安全审查
    （监听地址是否对外可达、有没有 token）住在 ``server.app.main`` 里，
    绕过它就等于让 ``doubi serve`` 成为一条无检查的后门。
    """
    from ..server.app import main as server_main

    argv = ["--host", args.host, "--port", str(args.port)]
    if args.token:
        argv += ["--token", args.token]
    if args.allow_insecure:
        argv.append("--allow-insecure")
    return server_main(argv)


def _cmd_mcp(args: argparse.Namespace) -> int:
    """Run the MCP stdio bridge."""
    from ..mcp.server import main as mcp_main
    return mcp_main([])


async def _run_downloads(urls: Iterable[str], options: DownloadOptions, concurrent: int, verbose: bool,
                          strategy: str | None) -> int:
    # build_default_pipeline() rather than a bare DownloadPipeline(...):
    # it is the single place that wires the default engine, guarantees the
    # platform adapters are registered, and switches on automatic retry.
    # A hand-rolled pipeline here is how the CLI silently drifts away from
    # the GUI / REST behavior (DEVELOPMENT.md pitfall 5).
    pipeline = build_default_pipeline(max_concurrent=concurrent)

    def on_progress(ev: ProgressEvent) -> None:
        pct = ev.fraction * 100
        if ev.phase == "done":
            print(f"  [done]      {ev.item.source_url}")
        elif ev.phase == "failed":
            print(f"  [failed]    {ev.item.source_url} -- {ev.message}", file=sys.stderr)
        elif ev.extra.get("retry"):
            # Needs its own branch: a retry notice carries phase="downloading"
            # and fraction=0.0, so the plain-progress branches below would
            # drop it entirely outside --verbose -- leaving the user staring
            # at a stalled line during the backoff with no explanation.
            print(f"  [retry]     {ev.item.source_url} -- {ev.message}", file=sys.stderr)
        elif verbose and ev.phase == "downloading":
            print(f"  [dl {pct:5.1f}%] {ev.item.source_url}")
        elif ev.phase == "downloading" and pct >= 99.0:
            print(f"  [merging]   {ev.item.source_url}")

    successes = 0
    failures = 0
    for url in urls:
        result = await pipeline.process_url(
            url, options, on_progress=on_progress,
            container_strategy=strategy or "post",
        )
        if result is not None:
            successes += 1
        else:
            failures += 1

    print(f"\nFinished: {successes} ok, {failures} failed")
    return 0 if failures == 0 else 1


def _read_url_file(path: Path) -> list[str]:
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        urls.append(s)
    return urls


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
