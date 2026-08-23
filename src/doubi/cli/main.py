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
from ..core.config import load_config
from ..core.logger import quiet_external_loggers, setup_logger
from ..core.models import DownloadOptions
from ..core.pipeline import DownloadPipeline, ProgressEvent
from ..core.registry import PlatformRegistry
from ..engines.yt_dlp import YtDlpEngine

# Trigger platform adapter registration
from .. import platforms  # noqa: F401
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
    p_dl.add_argument("-o", "--output", type=Path, default=Path("./Downloaded"),
                      help="output root directory (default: ./Downloaded)")
    p_dl.add_argument("--output-template", default="{platform}/{author}/{media_type}",
                      help="directory template relative to --output (default: '{platform}/{author}/{media_type}')")
    p_dl.add_argument("--format", default=None,
                      help="yt-dlp format selector (e.g. 'bestvideo*+bestaudio/best')")
    p_dl.add_argument("--quality", default="best",
                      help="quality preset: best | 4k | 1080p | ... (default: best)")
    p_dl.add_argument("--container", default="mp4", choices=["mp4", "mkv"],
                      help="output container (default: mp4)")
    p_dl.add_argument("--filename", default="{title}_{item_id}",
                      help="output filename template (default: '{title}_{item_id}')")
    p_dl.add_argument("--concurrent", type=int, default=3,
                      help="max concurrent downloads (default: 3)")
    p_dl.add_argument("--rate-limit", default=None, help="rate limit, e.g. 5M")
    p_dl.add_argument("--proxy", default=None, help="HTTP proxy, e.g. http://127.0.0.1:7890")
    p_dl.add_argument("--no-thumbnail", action="store_true")
    p_dl.add_argument("--no-metadata", action="store_true")
    p_dl.add_argument("--nfo", action="store_true", help="emit NFO sidecar (M5)")
    p_dl.add_argument("--danmaku", action="store_true", help="download danmaku (M5)")
    p_dl.add_argument("--subtitles", action="store_true", help="download subtitles (M5)")
    p_dl.add_argument("--no-resume", action="store_true",
                      help="restart partial downloads from scratch instead of resuming")
    p_dl.add_argument("--strategy", default=None,
                      help="for container URLs, choose strategy (e.g. post, like, space, favlist)")
    p_dl.add_argument("--database", type=Path, default=Path("doubi.db"),
                      help="SQLite database for dedup/history (default: doubi.db; pass empty string to disable)")
    p_dl.add_argument("--no-database", action="store_true",
                      help="disable SQLite dedup/history (shorthand for --database '')")
    p_dl.add_argument("--manifest", type=Path, default=Path("download_manifest.jsonl"),
                      help="JSONL manifest path (default: download_manifest.jsonl; pass empty string to disable)")
    p_dl.add_argument("--no-manifest", action="store_true",
                      help="disable manifest writing (shorthand for --manifest '')")
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
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
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
    db_path = None if args.no_database else args.database
    manifest_path = None if args.no_manifest else args.manifest
    options = DownloadOptions(
        output_root=args.output.expanduser().resolve(),
        output_dir_template=args.output_template,
        filename_template=args.filename,
        container=args.container,
        max_quality=args.quality,
        format_id=args.format,
        write_thumbnail=not args.no_thumbnail,
        write_metadata_json=not args.no_metadata,
        write_nfo=args.nfo,
        write_danmaku=args.danmaku,
        write_subtitles=args.subtitles,
        resume=not args.no_resume,
        rate_limit=args.rate_limit,
        proxy=args.proxy,
        database=db_path,
        manifest=manifest_path,
    )
    options.output_root.mkdir(parents=True, exist_ok=True)

    return asyncio.run(_run_downloads(urls, options, args.concurrent, args.verbose, args.strategy))


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
    """Run the REST API server."""
    from ..server.app import main as server_main
    return server_main(["--host", args.host, "--port", str(args.port)])


def _cmd_mcp(args: argparse.Namespace) -> int:
    """Run the MCP stdio bridge."""
    from ..mcp.server import main as mcp_main
    return mcp_main([])


async def _run_downloads(urls: Iterable[str], options: DownloadOptions, concurrent: int, verbose: bool,
                          strategy: str | None) -> int:
    engine = YtDlpEngine()
    pipeline = DownloadPipeline(engine=engine, max_concurrent=concurrent)

    def on_progress(ev: ProgressEvent) -> None:
        pct = ev.fraction * 100
        if ev.phase == "done":
            print(f"  [done]      {ev.item.source_url}")
        elif ev.phase == "failed":
            print(f"  [failed]    {ev.item.source_url} -- {ev.message}", file=sys.stderr)
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
