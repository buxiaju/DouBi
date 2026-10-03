"""DouBi CLI — entry point.

Subcommands:
    doubi platforms          list registered platform adapters
    doubi download           download one or more URLs
    doubi auth               manage login state per platform
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional

# Trigger platform adapter registration
from .. import (
    __version__,
    platforms,  # noqa: F401
)
from ..core.config import AppConfig, load_config
from ..core.engine_loader import build_default_pipeline
from ..core.logger import quiet_external_loggers, setup_logger
from ..core.models import DownloadOptions
from ..core.pipeline import ProgressEvent
from ..core.registry import PlatformRegistry
from ..platforms.douyin.webapi import ALL_HOT_BOARDS
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
    p_ls = sub.add_parser(
        "platforms",
        help="list registered platform adapters (pass --yt-dlp for all 1800+ extractors)",
    )
    p_ls.add_argument(
        "--yt-dlp", action="store_true",
        help="list yt-dlp's full extractor list (~1800 sites) instead of "
             "doubi's 4 built-in adapters",
    )
    p_ls.add_argument(
        "--filter", default=None,
        help="when --yt-dlp is set, narrow results by name/host substring (case-insensitive)",
    )
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
    # 全局 cookie 路径，喂给 yt-dlp ``cookiefile``。覆盖 config.yml 里的
    # ``cookies_file`` 字段。Netscape 格式（yt-dlp 标准）。
    p_dl.add_argument("--cookies-file", type=Path, default=None, metavar="PATH",
                      help="path to Netscape cookies.txt (config: cookies_file)")

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
                          help="import cookies from a Netscape file")
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
    # M6.55 — 直播详情 + 多清晰度. The detail half is adapted from
    # TikTokDL ``interface/live.py``; the recording half stays DouBi's
    # yt-dlp wrapper. ``--info`` inspects, ``--quality`` records one
    # specific stream, and no flag at all keeps the M2.1 behaviour
    # (yt-dlp picks the best stream itself).
    p_live = sub.add_parser("live", help="inspect or record a live stream (抖音)")
    p_live.add_argument("-u", "--url", default=None,
                        help="live URL or web_rid (e.g. https://live.douyin.com/123456)")
    p_live.add_argument("--room-id", default=None,
                        help="internal room_id (from `doubi search --type live`); "
                             "uses the webcast.amemv.com reflow endpoint")
    p_live.add_argument("--sec-user-id", default=None,
                        help="author sec_uid, optional companion to --room-id")
    p_live.add_argument("-o", "--output", type=Path, default=Path("./Downloaded"),
                        help="output root directory (default: ./Downloaded)")
    p_live.add_argument("--max-duration", type=float, default=0.0,
                        help="max seconds to record (0 = until the stream ends, default: 0)")
    p_live.add_argument("--cookies", "--cookies-file", type=Path, default=None,
                        dest="cookies",
                        help="path to a Netscape cookies.txt (for gated rooms)")
    p_live.add_argument("--proxy", default=None, help="HTTP proxy URL")
    p_live.add_argument("--info", action="store_true",
                        help="show room detail + available qualities, do not record")
    p_live.add_argument("--json", action="store_true",
                        help="with --info: emit one JSON object instead of a table")
    p_live.add_argument("--quality", default=None,
                        help="record a specific quality (key / 中文名 / 1-based index, "
                             "or 'best'); default is yt-dlp's own stream choice")
    p_live.add_argument("--format", choices=["flv", "hls"], default="flv",
                        help="container to use when --quality is given (default: flv)")
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

    # ---- search -------------------------------------------------------
    # M6.49 — search 抖音 (general / video / user / live). Adapted from
    # Johnserf-Shell/TikTokDownloader ``src/interface/search.py``. Outputs
    # JSONL to stdout by default; pipe into ``doubi download --batch -``
    # to actually fetch the matches.
    p_search = sub.add_parser(
        "search",
        help="search 抖音 by keyword (general / video / user / live)",
    )
    p_search.add_argument(
        "keyword",
        help="search keyword (Chinese / English / mixed)",
    )
    p_search.add_argument(
        "--type", choices=["general", "video", "user", "live"],
        default="general",
        help="search channel (default: general — 综合搜索; video = 视频搜索; "
             "user = 用户搜索; live = 直播搜索)",
    )
    p_search.add_argument(
        "--count", type=int, default=10,
        help="results per page (default: 10, max per the platform: ~10)",
    )
    p_search.add_argument(
        "--max", type=int, default=20,
        help="maximum results to fetch across pages (default: 20; "
             "the platform may cap search results, so don't over-spec)",
    )
    p_search.add_argument(
        "--sort", type=int, default=0,
        help="0 综合排序 / 1 最多点赞 / 2 最新发布 (only for general/video)",
    )
    p_search.add_argument(
        "--days", type=int, default=0,
        help="0 不限 / 1 一天内 / 7 一周内 / 180 半年内 "
             "(only for general/video)",
    )
    p_search.add_argument(
        "--duration", type=int, default=0,
        help="0 不限 / 1 1分钟内 / 2 1-5分钟 / 3 5分钟以上 "
             "(only for general/video)",
    )
    p_search.add_argument(
        "--follow", type=int, default=0,
        help="0 不限 / 1 最近看过 / 2 还未看过 / 3 关注的人 "
             "(only for general/video)",
    )
    p_search.add_argument(
        "--content", type=int, default=0,
        help="0 不限 / 1 视频 / 2 图文 (only for general)",
    )
    p_search.add_argument(
        "--fans", type=int, default=0,
        help="0 不限 / 1 1000以下 / 2 1k-1w / 3 1w-10w / 4 10w-100w / 5 100w以上 "
             "(only for user)",
    )
    p_search.add_argument(
        "--user-type", type=int, default=0,
        help="0 不限 / 1 普通用户 / 2 企业认证 / 3 个人认证 (only for user)",
    )
    p_search.add_argument(
        "--cookies-file", type=Path, default=None, metavar="PATH",
        help="path to Netscape cookies.txt (Douyin search prefers a logged-in "
             "session for stable results; without it, some endpoints may 403)",
    )
    p_search.add_argument(
        "--proxy", default=None, metavar="URL",
        help="HTTP proxy (e.g. http://127.0.0.1:7890)",
    )
    p_search.set_defaults(handler=_cmd_search_sync)

    p_hot = sub.add_parser(
        "hot",
        help="browse 抖音 hot 榜 (抖音热榜 / 娱乐榜 / 社会榜 / 挑战榜)",
    )
    p_hot.add_argument(
        "--board",
        choices=("all",) + ALL_HOT_BOARDS,
        default="all",
        help="which board to fetch (default: all — fetch all 4 boards and "
             "concatenate; single boards: positive / entertainment / "
             "society / challenge)",
    )
    p_hot.add_argument(
        "--max", type=int, default=50,
        help="maximum rows per board (default: 50, which is roughly what "
             "the platform returns; lower this for quick previews)",
    )
    p_hot.add_argument(
        "--cookies-file", type=Path, default=None, metavar="PATH",
        help="path to Netscape cookies.txt (hot 榜 works without login in "
             "most cases; supply cookies if you see 403 / empty responses)",
    )
    p_hot.add_argument(
        "--proxy", default=None, metavar="URL",
        help="HTTP proxy (e.g. http://127.0.0.1:7890)",
    )
    p_hot.set_defaults(handler=_cmd_hot_sync)

    p_fav = sub.add_parser(
        "favorites",
        help="browse 抖音 收藏夹全家族 (登录后可用; 5 类内容: 收藏夹 / 收藏夹视频 / 收藏合集 / 收藏音乐 / 收藏短剧)",
    )
    p_fav.add_argument(
        "--kind",
        choices=("favorites", "videos", "mix", "music", "series"),
        default="favorites",
        help="which 收藏 family to fetch (default: favorites — 收藏夹列表; "
             "videos = 收藏夹下视频; mix = 收藏合集; music = 收藏音乐; "
             "series = 收藏短剧)",
    )
    p_fav.add_argument(
        "collect_id",
        nargs="?",
        default=None,
        help="(only when --kind=videos) the collects_id from `doubi favorites` "
             "output's ``collects_id`` field",
    )
    p_fav.add_argument(
        "--max", type=int, default=50,
        help="maximum rows to fetch across pages (default: 50)",
    )
    p_fav.add_argument(
        "--count", type=int, default=10,
        help="page size per request (default: 10; the platform's per-endpoint "
              "default differs slightly — 12 for mix/series, 20 for music — "
              "but 10 works on all 5)",
    )
    p_fav.add_argument(
        "--cookies-file", type=Path, default=None, metavar="PATH",
        help="path to Netscape cookies.txt (REQUIRED for favorites family — "
             "all 5 endpoints gate on `user/self` referer; without login the "
             "platform returns 401 or empty lists)",
    )
    p_fav.add_argument(
        "--proxy", default=None, metavar="URL",
        help="HTTP proxy (e.g. http://127.0.0.1:7890)",
    )
    p_fav.set_defaults(handler=_cmd_favorites_sync)

    p_comments = sub.add_parser(
        "comments",
        help="browse 抖音 评论 + 回复 (top-level comments on a video, "
              "or replies under a single comment)",
    )
    p_comments.add_argument(
        "aweme_id",
        help="the video's aweme_id (run `doubi info <url>` first if you "
             "only have a share URL)",
    )
    p_comments.add_argument(
        "--kind",
        choices=("comments", "replies"),
        default="comments",
        help="which to fetch (default: comments — top-level comments; "
             "replies = replies under one comment, requires --comment-id)",
    )
    p_comments.add_argument(
        "--comment-id",
        default=None,
        metavar="CID",
        help="(only when --kind=replies) the parent comment's cid "
             "(run `doubi comments <aweme_id>` first to find it in the "
             "``cid`` field)",
    )
    p_comments.add_argument(
        "--max", type=int, default=50,
        help="maximum rows to fetch across pages (default: 50)",
    )
    p_comments.add_argument(
        "--count", type=int, default=10,
        help="page size per request (default: 10; for replies the "
             "platform default is 3, but 10 works too)",
    )
    p_comments.add_argument(
        "--cookies-file", type=Path, default=None, metavar="PATH",
        help="path to Netscape cookies.txt (public comments are visible "
             "without login, but the platform may rate-limit anonymous "
             "reads — supply cookies if you see 403 / empty responses)",
    )
    p_comments.add_argument(
        "--proxy", default=None, metavar="URL",
        help="HTTP proxy (e.g. http://127.0.0.1:7890)",
    )
    p_comments.set_defaults(handler=_cmd_comments_sync)

    p_user = sub.add_parser(
        "user",
        help="browse 抖音 user relations (following / followers) — DouBi native "
              "impl, no TikTokDL source for these endpoints",
    )
    p_user.add_argument(
        "sec_uid",
        help="the user's sec_uid (from `douyin.com/user/{sec_uid}` URL "
             "or ``search_user`` output)",
    )
    p_user.add_argument(
        "--kind",
        choices=("following", "followers"),
        default="following",
        help="which relation to fetch (default: following — 我关注的人; "
             "followers = 关注我的人)",
    )
    p_user.add_argument(
        "--max", type=int, default=50,
        help="maximum rows to fetch across pages (default: 50)",
    )
    p_user.add_argument(
        "--count", type=int, default=20,
        help="page size per request (default: 20)",
    )
    p_user.add_argument(
        "--cookies-file", type=Path, default=None, metavar="PATH",
        help="path to Netscape cookies.txt (REQUIRED for own relations — "
             "the platform gates on login session; public profile info "
             "may work without, but full following/follower lists need "
             "auth)",
    )
    p_user.add_argument(
        "--proxy", default=None, metavar="URL",
        help="HTTP proxy (e.g. http://127.0.0.1:7890)",
    )
    p_user.set_defaults(handler=_cmd_user_sync)

    # ---- mix ----------------------------------------------------------
    # M6.56 — 合集回查. Two modes:
    #   `doubi mix <mix_id>`          → title / id / desc only (1 probe)
    #   `doubi mix <mix_id> --list`   → enumerate every video (JSONL)
    p_mix = sub.add_parser(
        "mix",
        help="look up a 抖音 合集 (collection) — title probe + optional "
              "video listing",
    )
    p_mix.add_argument(
        "mix_id",
        help="the 合集 id (from a /collection/{id} URL) — a full URL is "
             "also accepted and the id is extracted",
    )
    p_mix.add_argument(
        "--from-aweme", default=None, metavar="AWEME_ID",
        help="resolve the 合集 a single video belongs to instead of passing "
             "a mix_id (mirrors TikTokDL Mix.__get_mix_id)",
    )
    p_mix.add_argument(
        "--list", action="store_true",
        help="also enumerate the 合集's videos (JSONL to stdout)",
    )
    p_mix.add_argument(
        "--max", type=int, default=0,
        help="with --list: max videos to fetch across pages (0 = all, default: 0)",
    )
    p_mix.add_argument(
        "--cookies-file", type=Path, default=None, metavar="PATH",
        help="path to Netscape cookies.txt (recommended — anonymous "
             "sessions are often 403'd on /mix/detail/)",
    )
    p_mix.add_argument(
        "--proxy", default=None, metavar="URL",
        help="HTTP proxy (e.g. http://127.0.0.1:7890)",
    )
    p_mix.set_defaults(handler=_cmd_mix_sync)

    # ---- hashtag ------------------------------------------------------
    # M6.57 — 话题（HashTag）作品列表. **DouBi native** — TikTokDL's
    # ``src/interface/hashtag.py`` ``run()`` body is literally ``pass``,
    # so there is no upstream endpoint to port.
    p_tag = sub.add_parser(
        "hashtag",
        help="list the videos under a 抖音 话题 (challenge / hashtag) — "
              "DouBi native impl, TikTokDL's hashtag.py is an empty shell",
    )
    p_tag.add_argument(
        "ch_id",
        help="the 话题 id (from a /challenge/detail/{id} URL) — a full "
             "URL is also accepted and the id is extracted",
    )
    p_tag.add_argument(
        "--max", type=int, default=50,
        help="maximum rows to fetch across pages (default: 50)",
    )
    p_tag.add_argument(
        "--count", type=int, default=20,
        help="page size per request (default: 20)",
    )
    p_tag.add_argument(
        "--sort", choices=("comprehensive", "latest"), default="comprehensive",
        help="ordering: comprehensive = 综合排序 (default), latest = 最新发布",
    )
    p_tag.add_argument(
        "--cookies-file", type=Path, default=None, metavar="PATH",
        help="path to Netscape cookies.txt (public 话题 usually work "
             "without, but risk control tightens on heavy use)",
    )
    p_tag.add_argument(
        "--proxy", default=None, metavar="URL",
        help="HTTP proxy (e.g. http://127.0.0.1:7890)",
    )
    p_tag.set_defaults(handler=_cmd_hashtag_sync)

    return parser


def _cmd_search_sync(args: argparse.Namespace) -> int:
    """Sync wrapper around the async ``_cmd_search`` (argparse dispatches
    synchronously; we spin up a one-shot event loop to drive the async
    HTTP layer)."""
    return asyncio.run(_cmd_search(args))


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_platforms(args: argparse.Namespace) -> int:
    if args.yt_dlp:
        return _cmd_platforms_ytdlp(args)
    adapters = PlatformRegistry.all()
    if not adapters:
        print("No platform adapters registered.", file=sys.stderr)
        return 1
    print(f"Registered platforms ({len(adapters)}):")
    for a in adapters:
        print(f"  - {a.name:<12} {a.display_name}  types: {', '.join(a.supported_media_types()) or '-'}")
    print(
        "\n(这只是 doubi 内置的 4 个适配器；粘贴任意 URL 进 doubi 会自动路由到\n"
        " yt-dlp 的 1800+ extractor 之一。`doubi platforms --yt-dlp` 看完整列表。)",
        file=sys.stderr,
    )
    return 0


def _cmd_platforms_ytdlp(args: argparse.Namespace) -> int:
    """``doubi platforms --yt-dlp`` —— 列出 yt-dlp 全 extractor 列表。

    与 ``doubi platforms`` 的差别：本命令列的是 yt-dlp 自身支持的 1800+ 站点
    （用户粘贴对应 URL 时 ytdlp_generic 会自动路由），而不是 doubi 自己的
    4 个内置适配器。``--filter`` 关键字按 name/host 过滤，便于排查「这个
    站到底能不能下」。
    """
    try:
        import yt_dlp
    except ImportError:
        print("yt-dlp is not installed. Run `pip install yt-dlp`.", file=sys.stderr)
        return 1

    filter_kw = (args.filter or "").strip().lower()
    extractors = []
    for ie in yt_dlp.list_extractors():
        # 关键属性缺失时用 type 名字兜底（避免 AttributeError 阻断整次列举）
        ie_key = getattr(ie, "ie_key", None) or type(ie).__name__
        name = getattr(ie, "name", None) or type(ie).__name__
        valid_url = getattr(ie, "_VALID_URL", None)
        host = ""
        if isinstance(valid_url, str):
            host = valid_url
        elif isinstance(valid_url, (list, tuple)) and valid_url:
            host = next((u for u in valid_url if u), "")
        # 抽 host 段
        import re as _re
        m = _re.match(r"https?://(?:www\.)?([^/]+)", host, _re.IGNORECASE)
        host_short = m.group(1) if m else host
        working = getattr(ie, "_WORKING", True)
        extractors.append((ie_key, name, host_short, working))

    if filter_kw:
        extractors = [e for e in extractors
                      if filter_kw in e[0].lower() or filter_kw in e[1].lower()
                      or filter_kw in e[2].lower()]
    extractors.sort(key=lambda e: (e[1].lower(), e[0].lower()))

    print(f"yt-dlp extractors: {len(extractors)}")
    for ie_key, name, host, working in extractors:
        flag = "" if working else " [BROKEN]"
        host_str = host or "-"
        print(f"  {name:<40} {host_str:<32} {ie_key}{flag}")
    return 0


async def _cmd_search(args: argparse.Namespace) -> int:
    """``doubi search <keyword> [--type general|video|user|live] [--max N]``.

    M6.49 — search 抖音 by keyword. Outputs JSONL of search hits to stdout,
    one record per line. Pipe into ``doubi download --batch -`` to fetch
    the matches.

    Adapted from TikTokDL ``src/interface/search.py``; the four endpoints
    (general / video / user / live) all live in the M6.48
    ``DOUYIN_SIGNED_PATHS`` whitelist so the WebSign attachment is
    automatic.

    0.3.3 P1-4 — the actual fetching lives in :func:`collect_search_async`
    so MCP / REST callers get identical records. This function only
    handles CLI plumbing: argparse → records → JSONL.

    Exit codes:
        0  results written (including 0 hits)
        2  no keyword supplied / argparse error (argparse already exits)
        3  search itself failed (network, 403, ...)
    """
    keyword = (args.keyword or "").strip()
    if not keyword:
        print("Error: keyword required.", file=sys.stderr)
        return 2

    try:
        results = await collect_search_async(
            keyword=keyword,
            channel=args.type,
            max_count=args.max,
            cookies_file=args.cookies_file,
            proxy=args.proxy,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: search failed: {exc}", file=sys.stderr)
        return 3

    if not results:
        # 0 hits is not an error; the GUI surfaces the empty table.
        print("No results.", file=sys.stderr)
        return 0

    # Emit JSONL — each record is the raw aweme / user / room dict.
    for item in results:
        # Minimal normalization for the common case: include
        # ``share_url`` so ``doubi download`` can pick it up via
        # ``--batch -``.
        share_url = item.get("share_url") or _build_share_url(item, args.type)
        record = dict(item)
        if share_url and "share_url" not in record:
            record["share_url"] = share_url
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


def _build_share_url(item: dict[str, Any], kind: str) -> str | None:
    """Best-effort share URL for a search hit (one of aweme / user / room).

    Douyin platform URLs:
        aweme: ``https://www.douyin.com/video/{aweme_id}``
        user:  ``https://www.douyin.com/user/{sec_uid}``
        room:  ``https://live.douyin.com/{room_id}``

    Returns ``None`` when the required id field is missing.
    """
    if kind == "user":
        sec_uid = item.get("sec_uid") or item.get("uid")
        if sec_uid:
            return f"https://www.douyin.com/user/{sec_uid}"
    elif kind == "live":
        room_id = item.get("room_id") or item.get("id_str")
        if room_id:
            return f"https://live.douyin.com/{room_id}"
    else:  # general / video → aweme
        aweme_id = item.get("aweme_id")
        if aweme_id:
            return f"https://www.douyin.com/video/{aweme_id}"
    return None


# ---------------------------------------------------------------------------
# M6.50 — hot 榜
# ---------------------------------------------------------------------------


def _cmd_hot_sync(args: argparse.Namespace) -> int:
    """Sync wrapper around the async ``_cmd_hot``."""
    return asyncio.run(_cmd_hot(args))


# 0.3.3 P1-4 — share the actual fetching logic with MCP / REST so the
# three frontends always emit the same record schema. See
# ``mcp/server.py`` and ``server/app.py`` for callers.
async def collect_search_async(
    *,
    keyword: str,
    channel: str = "general",
    max_count: int = 20,
    cookies_file: Optional["Path"] = None,
    proxy: Optional[str] = None,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """``doubi search`` core. Returns raw records (aweme / user / room).

    The CLI emits each record as one JSONL row with a synthesised
    ``share_url``; callers can do the same.
    """
    from doubi.platforms.douyin.webapi import DouyinWebAPI

    api = DouyinWebAPI(
        cookies_file=cookies_file,
        proxy=proxy,
        timeout=timeout,
    )
    error_sink: dict[str, Any] = {}
    try:
        if channel == "general":
            results = await api.search_general(
                keyword, count=10, max_count=max_count, error_sink=error_sink,
            )
        elif channel == "video":
            results = await api.search_video(
                keyword, count=10, max_count=max_count, error_sink=error_sink,
            )
        elif channel == "user":
            results = await api.search_user(
                keyword, count=10, max_count=max_count, error_sink=error_sink,
            )
        else:
            results = await api.search_live(
                keyword, count=10, max_count=max_count, error_sink=error_sink,
            )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"search failed: {exc}") from exc
    return list(results or [])


async def collect_hot_async(
    *,
    board: str = "all",
    max_count: int = 50,
    cookies_file: Optional["Path"] = None,
    proxy: Optional[str] = None,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """``doubi hot`` core. Returns hot-word rows annotated with ``board``."""
    from doubi.platforms.douyin.webapi import (
        ALL_HOT_BOARDS,
        HOT_BOARD_NAMES,
        DouyinWebAPI,
    )

    api = DouyinWebAPI(
        cookies_file=cookies_file,
        proxy=proxy,
        timeout=timeout,
    )
    targets = list(ALL_HOT_BOARDS) if board == "all" else [board]
    error_sinks = {b: {} for b in targets}
    aggregate: list[dict[str, Any]] = []
    for b in targets:
        rows = await api.get_hot_list(
            b, max_count=max_count, error_sink=error_sinks[b],
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            record = dict(row)
            record["board"] = b
            record.setdefault("board_name", HOT_BOARD_NAMES.get(b, b))
            aggregate.append(record)
    return aggregate


async def _cmd_hot(args: argparse.Namespace) -> int:
    """``doubi hot [--board all|positive|entertainment|society|challenge] [--max N]``.

    M6.50 — hot 榜. Outputs JSONL of hot-word entries to stdout, one
    record per line. Each record carries a ``board`` key so single-board
    and ``--board all`` runs produce a uniform stream (handy for piping
    into ``jq`` / external dashboards).

    Hot word entries are NOT videos themselves. Each row carries
    ``word``, ``hot_value``, ``position``, ``sentence_id``,
    ``video_count``, ``cover_url``. To follow a row into actual videos,
    use ``doubi search <word>`` — sentence_id alone won't enumerate them.

    0.3.3 P1-4 — the actual fetching lives in :func:`collect_hot_async`
    so MCP / REST callers get identical records. This function only
    handles CLI plumbing: argparse → records → JSONL.

    Exit codes (mirror search):
        0  results written (including 0 hits)
        3  hot fetch failed (network, 403, ...)
    """
    try:
        aggregate = await collect_hot_async(
            board=args.board,
            max_count=args.max,
            cookies_file=args.cookies_file,
            proxy=args.proxy,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: hot fetch failed: {exc}", file=sys.stderr)
        return 3

    if not aggregate:
        print("No results.", file=sys.stderr)
        return 0

    for record in aggregate:
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


# ---------------------------------------------------------------------------
# M6.51 — 收藏夹全家族
# ---------------------------------------------------------------------------


# Display name (Chinese) for the 5 favorite surfaces. Used by the
# CLI's JSONL output (``record.kind_name``) so a downstream consumer
# can render rows without re-mapping the kind key.
FAVORITES_KIND_NAMES: dict[str, str] = {
    "favorites": "收藏夹",
    "videos": "收藏夹视频",
    "mix": "收藏合集",
    "music": "收藏音乐",
    "series": "收藏短剧",
}

# Maps ``--kind`` to the webapi method to call. Symmetric table —
# adding a kind means adding one webapi method + one entry here.
_FAVORITES_DISPATCH: dict[str, str] = {
    "favorites": "iter_collects",
    "videos": "iter_collects_videos",
    "mix": "iter_collects_mix",
    "music": "iter_collects_music",
    "series": "iter_collects_series",
}


def _cmd_favorites_sync(args: argparse.Namespace) -> int:
    """Sync wrapper around the async ``_cmd_favorites``."""
    return asyncio.run(_cmd_favorites(args))


async def _cmd_favorites(args: argparse.Namespace) -> int:
    """``doubi favorites [--kind ...] [collect_id]``.

    M6.51 — 收藏夹全家族. All 5 endpoints gate on a logged-in
    session (referer = ``user/self?showTab=favorite_collection``).
    The CLI prints a hint when ``error_sink.hint="need_login"`` lands.

    Outputs JSONL of favorite entries to stdout. Each record carries
    a ``kind`` + ``kind_name`` tag so single-kind runs produce a
    self-describing stream (handy for piping into ``jq`` / external
    dashboards).

    For ``--kind=videos``, the user must supply the ``collects_id``
    positional arg; we validate at parse time before reaching here.

    Exit codes (mirror search / hot):
            0  results written (including 0 hits)
            2  missing positional arg for ``--kind=videos``
            3  fetch failed (network, 401, ...)
    """
    from doubi.platforms.douyin.webapi import DouyinWebAPI

    kind = args.kind
    collect_id = getattr(args, "collect_id", None)

    if kind == "videos" and not collect_id:
        print(
            "Error: --kind=videos requires a positional collect_id "
            "(run `doubi favorites` first to find the collects_id).",
            file=sys.stderr,
        )
        return 2

    api = DouyinWebAPI(
        cookies_file=args.cookies_file,
        proxy=args.proxy,
        timeout=15.0,
    )

    method_name = _FAVORITES_DISPATCH[kind]
    iter_method = getattr(api, method_name)

    error_sink: dict[str, Any] = {}
    try:
        if kind == "videos":
            rows = await iter_method(
                collect_id,
                count=args.count,
                max_count=args.max,
                error_sink=error_sink,
            )
        else:
            rows = await iter_method(
                count=args.count,
                max_count=args.max,
                error_sink=error_sink,
            )
    except Exception as exc:  # noqa: BLE001
        print(
            f"Error: favorites fetch failed for kind={kind}: {exc}",
            file=sys.stderr,
        )
        return 3

    if not rows:
        if error_sink.get("hint"):
            reason = error_sink.get("reason", "unknown")
            hint = error_sink.get("hint")
            print(
                f"No results. last error: {reason} (hint={hint})",
                file=sys.stderr,
            )
            if hint == "need_login":
                print(
                    "Hint: 收藏夹全家族必须登录抖音；请先运行 `doubi auth douyin`，"
                    "再传 --cookies-file ~/.doubi/cookies/douyin.txt。",
                    file=sys.stderr,
                )
        else:
            print("No results.", file=sys.stderr)
        return 0  # 0 hits is not an error

    # Emit JSONL. Each record gets the ``kind`` + ``kind_name`` tags
    # + a synthetic ``share_url`` where applicable (only videos; the
    # other kinds are folder-style references, not directly
    # downloadable URLs).
    kind_name = FAVORITES_KIND_NAMES[kind]
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = dict(row)
        record["kind"] = kind
        record["kind_name"] = kind_name
        if kind == "videos":
            # Best-effort share URL so ``doubi download --batch -``
            # can pipe the rows straight in.
            share_url = (
                record.get("share_url")
                or _build_share_url(record, "general")  # "general" → aweme
            )
            if share_url:
                record["share_url"] = share_url
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


# ---------------------------------------------------------------------------
# M6.52 — 评论 + 回复
# ---------------------------------------------------------------------------

# Display name for the 2 comment surfaces. Used by the CLI's JSONL
# output (``record.kind_name``) so a downstream consumer can render
# rows without re-mapping the kind key.
COMMENTS_KIND_NAMES: dict[str, str] = {
    "comments": "评论",
    "replies": "评论回复",
}


def _cmd_comments_sync(args: argparse.Namespace) -> int:
    """Sync wrapper around the async ``_cmd_comments``."""
    return asyncio.run(_cmd_comments(args))


async def _cmd_comments(args: argparse.Namespace) -> int:
    """``doubi comments <aweme_id> [--kind comments|replies] [--comment-id]``.

    M6.52 — 评论 + 回复. Outputs JSONL of comment rows to stdout, one
    per line. Each record carries a ``kind`` + ``kind_name`` tag plus
    ``aweme_id`` so downstream pipelines know what each row came from.

    Login gating is *softer* than the favorites family: public
    comments on public videos are visible without login. The CLI prints
    a hint when ``error_sink.hint="need_login"`` lands, but most
    reads won't trigger it.

    Exit codes (mirror search / hot / favorites):
            0  results written (including 0 hits)
            2  missing positional aweme_id (argparse already exits) or
               missing ``--comment-id`` for ``--kind=replies``
            3  fetch failed (network, 403, ...)
    """
    from doubi.platforms.douyin.webapi import DouyinWebAPI

    aweme_id = (args.aweme_id or "").strip()
    if not aweme_id:
        print("Error: aweme_id required.", file=sys.stderr)
        return 2

    kind = args.kind
    comment_id = getattr(args, "comment_id", None)

    if kind == "replies" and not comment_id:
        print(
            "Error: --kind=replies requires --comment-id "
            "(run `doubi comments <aweme_id>` first to find the cid).",
            file=sys.stderr,
        )
        return 2

    api = DouyinWebAPI(
        cookies_file=args.cookies_file,
        proxy=args.proxy,
        timeout=15.0,
    )

    error_sink: dict[str, Any] = {}
    try:
        if kind == "comments":
            rows = await api.iter_aweme_comments(
                aweme_id,
                count=args.count,
                max_count=args.max,
                error_sink=error_sink,
            )
        else:  # replies
            rows = await api.iter_comment_replies(
                aweme_id,
                str(comment_id),
                count=args.count,
                max_count=args.max,
                error_sink=error_sink,
            )
    except Exception as exc:  # noqa: BLE001
        print(
            f"Error: comments fetch failed for kind={kind}: {exc}",
            file=sys.stderr,
        )
        return 3

    if not rows:
        if error_sink.get("hint"):
            reason = error_sink.get("reason", "unknown")
            hint = error_sink.get("hint")
            print(
                f"No results. last error: {reason} (hint={hint})",
                file=sys.stderr,
            )
            if hint == "need_login":
                print(
                    "Hint: 评论通常匿名可读；如遇 403 请尝试 "
                    "--cookies-file ~/.doubi/cookies/douyin.txt。",
                    file=sys.stderr,
                )
        else:
            print("No results.", file=sys.stderr)
        return 0  # 0 hits is not an error

    # Emit JSONL. Each record gets ``kind`` + ``kind_name`` + ``aweme_id``
    # so the stream is self-describing across kinds.
    kind_name = COMMENTS_KIND_NAMES[kind]
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = dict(row)
        record["kind"] = kind
        record["kind_name"] = kind_name
        record["aweme_id"] = aweme_id
        if kind == "replies" and comment_id:
            record["parent_comment_id"] = str(comment_id)
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


# ---------------------------------------------------------------------------
# M6.54 — 关注列表 + 粉丝列表
# ---------------------------------------------------------------------------

# Display name for the 2 user-relation surfaces. Used by the CLI's JSONL
# output (``record.kind_name``) so a downstream consumer can render
# rows without re-mapping the kind key.
USER_KIND_NAMES: dict[str, str] = {
    "following": "我关注的人",
    "followers": "关注我的人",
}

# Maps ``--kind`` to the webapi method. Symmetric table.
_USER_DISPATCH: dict[str, str] = {
    "following": "iter_user_following",
    "followers": "iter_user_followers",
}


def _cmd_user_sync(args: argparse.Namespace) -> int:
    """Sync wrapper around the async ``_cmd_user``."""
    return asyncio.run(_cmd_user(args))


async def _cmd_user(args: argparse.Namespace) -> int:
    """``doubi user <sec_uid> [--kind following|followers]``.

    M6.54 — 关注列表 + 粉丝列表. Outputs JSONL of user rows to stdout,
    one per line. Each record carries a ``kind`` + ``kind_name`` tag plus
    ``sec_uid`` so downstream pipelines know what each row came from.

    Login gating: the platform gates the following/follower endpoints
    on login session. Public profiles (e.g. another user's follower
    count) may work without login but full lists typically need auth.

    Exit codes (mirror comments / favorites):
            0  results written (including 0 hits)
            2  missing positional sec_uid (argparse already exits)
            3  fetch failed (network, 403, ...)
    """
    from doubi.platforms.douyin.webapi import DouyinWebAPI

    sec_uid = (args.sec_uid or "").strip()
    if not sec_uid:
        print("Error: sec_uid required.", file=sys.stderr)
        return 2

    api = DouyinWebAPI(
        cookies_file=args.cookies_file,
        proxy=args.proxy,
        timeout=15.0,
    )

    iter_method = getattr(api, _USER_DISPATCH[args.kind])
    error_sink: dict[str, Any] = {}
    try:
        rows = await iter_method(
            sec_uid,
            count=args.count,
            max_count=args.max,
            error_sink=error_sink,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"Error: user fetch failed for kind={args.kind}: {exc}",
            file=sys.stderr,
        )
        return 3

    if not rows:
        if error_sink.get("hint"):
            reason = error_sink.get("reason", "unknown")
            hint = error_sink.get("hint")
            print(
                f"No results. last error: {reason} (hint={hint})",
                file=sys.stderr,
            )
            if hint == "need_login":
                print(
                    "Hint: 关注/粉丝列表需要登录抖音；请先运行 `doubi auth douyin`，"
                    "再传 --cookies-file ~/.doubi/cookies/douyin.txt。",
                    file=sys.stderr,
                )
        else:
            print("No results.", file=sys.stderr)
        return 0  # 0 hits is not an error

    # Emit JSONL. Each record gets ``kind`` + ``kind_name`` +
    # ``target_sec_uid`` (parent user whose relations we're listing)
    # so the stream is self-describing across kinds. We use
    # ``target_sec_uid`` instead of overwriting ``sec_uid`` because
    # ``sec_uid`` is the identity field of each row (the related user)
    # — clobbering it would lose the row's identity.
    kind_name = USER_KIND_NAMES[args.kind]
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = dict(row)
        record["kind"] = args.kind
        record["kind_name"] = kind_name
        record["target_sec_uid"] = sec_uid
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


def _cmd_mix_sync(args: argparse.Namespace) -> int:
    """Sync wrapper around the async ``_cmd_mix``."""
    return asyncio.run(_cmd_mix(args))


def _mix_id_from_arg(raw: str) -> str:
    """Accept a bare ``mix_id`` or any 合集 URL and return the id.

    Reuses the URL classifier so ``/collection/{id}``,
    ``/collection/{id}/{seq}``, ``/mix/{id}`` and the ``iesdouyin``
    share form all work — no second regex to keep in sync.
    """
    from doubi.platforms.douyin.url import DouyinURLType, classify_douyin_url

    text = (raw or "").strip()
    if not text:
        return ""
    if "://" in text:
        classified = classify_douyin_url(text)
        if classified.type in (DouyinURLType.COLLECTION, DouyinURLType.MIX):
            return classified.item_id
        return ""
    return text


async def _cmd_mix(args: argparse.Namespace) -> int:
    """``doubi mix <mix_id> [--from-aweme ID] [--list]``.

    M6.56 — 合集标题/ID 回查（item 11）. Adapted from
    Johnserf-Shell/TikTokDownloader ``src/interface/mix.py:86-88``
    (``Mix.__get_mix_id``) + ``src/extract/extractor.py:1546-1548``
    (``extract_mix_id`` ⇔ ``mix_info.mix_id``).

    Without ``--list``: prints one JSON object describing the 合集 and
    exits — the cheap "what is this collection called" probe.
    With ``--list``: after the probe, streams the 合集's videos as JSONL.

    Exit codes (mirroring the other read-only subcommands):
            0  looked up successfully (a nameless 合集 is still 0)
            2  missing mix_id / unusable URL
            3  fetch failed (network, 403, ...)
    """
    from doubi.platforms.douyin.webapi import (
        DouyinWebAPI,
        aweme_to_media_item,
        format_mix_title,
    )

    aweme_id = (args.from_aweme or "").strip()
    mix_id = _mix_id_from_arg(args.mix_id or "")
    if not mix_id and not aweme_id:
        print(
            "Error: give a mix_id (or a /collection/{id} URL), or --from-aweme.",
            file=sys.stderr,
        )
        return 2

    api = DouyinWebAPI(
        cookies_file=args.cookies_file,
        proxy=args.proxy,
        timeout=15.0,
    )

    error_sink: dict[str, Any] = {}
    try:
        ref = await api.resolve_mix_ref(
            mix_id=mix_id,
            aweme_id=aweme_id,
            error_sink=error_sink,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: mix lookup failed: {exc}", file=sys.stderr)
        return 3

    # ``resolve_mix_ref`` returns ``{}`` only when it could not resolve
    # anything at all. Falling back to the caller-supplied ``mix_id``
    # here would turn a failed lookup into a confident-looking success
    # ("抖音合集 7663..." for an id the platform never confirmed), so
    # an empty ref is reported as a miss instead.
    resolved = str(ref.get("mix_id") or "")
    if not resolved:
        reason = error_sink.get("reason", "not_found")
        hint = error_sink.get("hint", "")
        message = f"No 合集 found. last error: {reason}"
        if hint:
            message += f" (hint={hint})"
        print(message, file=sys.stderr)
        if hint == "need_login":
            print(
                "Hint: /mix/detail/ 常被风控 403；请先运行 `doubi auth douyin`，"
                "再传 --cookies-file ~/.doubi/cookies/douyin.txt。",
                file=sys.stderr,
            )
        return 0

    if not args.list:
        record = {"mix_id": resolved}
        record.update({k: v for k, v in ref.items() if k != "mix_id"})
        record["title"] = format_mix_title(ref, resolved)
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return 0

    try:
        awemes = await api.iter_mix_awemes(
            resolved,
            max_count=args.max,
            error_sink=error_sink,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: mix listing failed for {resolved}: {exc}", file=sys.stderr)
        return 3

    if not awemes:
        # The probe already proved the 合集 exists, so an empty listing
        # here is a real (if unhelpful) result — report, don't fail.
        if error_sink.get("hint"):
            print(
                f"No videos. last error: {error_sink.get('reason', 'unknown')} "
                f"(hint={error_sink.get('hint')})",
                file=sys.stderr,
            )
        else:
            print("No videos.", file=sys.stderr)
        return 0

    mix_name = str(ref.get("mix_name") or "")
    for aweme in awemes:
        item = aweme_to_media_item(aweme)
        record = {
            "aweme_id": item.item_id,
            "title": item.title,
            "author": item.author.name,
            "author_sec_uid": item.author.id,
            "media_type": item.media_type.value,
            "duration": item.duration,
            "publish_time": (
                item.publish_time.isoformat() if item.publish_time else None
            ),
            "cover_url": item.cover_url,
            "source_url": item.source_url,
            "mix_id": resolved,
            "mix_name": mix_name,
            "target_mix_id": resolved,
        }
        record.update({
            k: v for k, v in item.extra.items()
            if k in ("view_count", "like_count", "description")
        })
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


HASHTAG_SORT_TYPES: dict[str, int] = {
    "comprehensive": 0,   # 综合排序
    "latest": 1,          # 最新发布
}


def _cmd_hashtag_sync(args: argparse.Namespace) -> int:
    """Sync wrapper around the async ``_cmd_hashtag``."""
    return asyncio.run(_cmd_hashtag(args))


def _ch_id_from_arg(raw: str) -> str:
    """Accept a bare 话题 id or a ``/challenge/detail/{id}`` URL.

    Also tolerates the share form ``/share/challenge/detail/{id}`` that
    the mobile app produces. Kept as a local regex rather than an entry
    in ``url.py`` because 话题 URLs are not a *downloadable* input —
    ``doubi download`` has no container for them — so adding a
    ``DouyinURLType`` member would create a classifier result that no
    adapter path consumes.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    if "://" not in text:
        return text
    m = re.search(r"/challenge/detail/(\d+)", text)
    return m.group(1) if m else ""


async def _cmd_hashtag(args: argparse.Namespace) -> int:
    """``doubi hashtag <ch_id>``.

    M6.57 — 话题作品列表（Survey §8.1 item 13）.

    **DouBi native.** TikTokDL's ``src/interface/hashtag.py`` is an
    empty shell (``run()`` is ``pass``, no ``api`` declared), so unlike
    M6.56 there is nothing to port — the endpoint
    (``/aweme/v1/web/challenge/aweme/``) was determined here. CHANGELOG
    M6.57 §首段 flags this so this milestone is not miscredited.

    Outputs JSONL of video rows to stdout, one per line, each tagged
    with ``ch_id`` + ``sort`` so the stream is self-describing across
    invocations (same convention as ``doubi user`` / ``doubi favorites``).

    Exit codes:
            0  results written (including 0 hits)
            2  missing / unparseable ch_id
            3  fetch failed (network, 403, ...)
    """
    from doubi.platforms.douyin.webapi import (
        DouyinWebAPI,
        aweme_to_media_item,
    )

    ch_id = _ch_id_from_arg(args.ch_id or "")
    if not ch_id:
        print(
            "Error: give a 话题 id, or a /challenge/detail/{id} URL.",
            file=sys.stderr,
        )
        return 2

    api = DouyinWebAPI(
        cookies_file=args.cookies_file,
        proxy=args.proxy,
        timeout=15.0,
    )

    error_sink: dict[str, Any] = {}
    try:
        awemes = await api.iter_challenge_awemes(
            ch_id,
            count=args.count,
            max_count=args.max,
            sort_type=HASHTAG_SORT_TYPES[args.sort],
            error_sink=error_sink,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: hashtag fetch failed for {ch_id}: {exc}", file=sys.stderr)
        return 3

    if not awemes:
        if error_sink.get("hint"):
            print(
                f"No results. last error: {error_sink.get('reason', 'unknown')} "
                f"(hint={error_sink.get('hint')})",
                file=sys.stderr,
            )
            if error_sink.get("hint") == "need_login":
                print(
                    "Hint: 话题作品流在风控收紧时需要登录；请先运行 "
                    "`doubi auth douyin`，再传 --cookies-file "
                    "~/.doubi/cookies/douyin.txt。",
                    file=sys.stderr,
                )
        else:
            print("No results.", file=sys.stderr)
        return 0  # 0 hits is not an error

    for aweme in awemes:
        item = aweme_to_media_item(aweme)
        record: dict[str, Any] = {
            "aweme_id": item.item_id,
            "title": item.title,
            "author": item.author.name,
            "author_sec_uid": item.author.id,
            "media_type": item.media_type.value,
            "duration": item.duration,
            "publish_time": (
                item.publish_time.isoformat() if item.publish_time else None
            ),
            "cover_url": item.cover_url,
            "source_url": item.source_url,
            "ch_id": ch_id,
            "sort": args.sort,
            "target_ch_id": ch_id,
        }
        record.update({
            k: v for k, v in item.extra.items()
            if k in ("view_count", "like_count", "description",
                     "mix_id", "mix_name")
        })
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
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
        cookies_file=_pick(getattr(args, "cookies_file", None), cfg.cookies_file),
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


def _print_live_info(room: dict[str, Any], *, as_json: bool) -> None:
    """Render a live-room record for ``doubi live --info``."""
    if as_json:
        sys.stdout.write(json.dumps(room, ensure_ascii=False) + "\n")
        return
    print(f"直播间: {room.get('title') or '(无标题)'}")
    print(f"主播:   {room.get('nickname') or '未知'}")
    print(f"状态:   {room.get('status_name')}")
    rid = room.get("web_rid") or room.get("room_id")
    if rid:
        print(f"ID:     {rid}")
    if room.get("user_count_str"):
        print(f"在线:   {room['user_count_str']}")
    if room.get("total_user_str"):
        print(f"累计:   {room['total_user_str']}")
    if room.get("cover"):
        print(f"封面:   {room['cover']}")
    qualities = room.get("qualities") or []
    if not qualities:
        print("清晰度: (平台未返回拉流地址，直播间可能未开播)")
        return
    print("清晰度:")
    for i, row in enumerate(qualities, start=1):
        marks = []
        if row.get("flv"):
            marks.append("FLV")
        if row.get("hls"):
            marks.append("HLS")
        print(f"  {i}. {row['key']} ({row['name']})  {'/'.join(marks) or '-'}")


def _cmd_live(args: argparse.Namespace) -> int:
    """Inspect or record a 抖音 live stream.

    M6.55 — three modes, all sharing one room lookup:

    * ``--info``            detail + quality table only, no download
    * ``--quality <q>``     fetch a direct pull URL and record that stream
    * (neither)             M2.1 behaviour: let yt-dlp pick the best stream

    Exit codes:
            0  done
            1  input / lookup / record failure
            2  neither --url nor --room-id supplied
    """
    setup_logger("INFO")
    from ..platforms.douyin.live import LiveRecorder
    from ..platforms.douyin.webapi import (
        DouyinWebAPI,
        extract_live_web_rid,
        pick_live_quality,
    )

    web_rid = extract_live_web_rid(args.url) if args.url else ""
    room_id = (args.room_id or "").strip()
    if not web_rid and not room_id:
        print(
            "Error: need --url (live.douyin.com link / web_rid) or --room-id.",
            file=sys.stderr,
        )
        return 2

    cookies = str(args.cookies) if args.cookies else None
    # Only pay for a room lookup when the caller actually asked for one.
    needs_lookup = args.info or bool(args.quality)
    room: dict[str, Any] = {}

    if needs_lookup:
        async def _fetch_room():
            api = DouyinWebAPI(
                cookies_file=args.cookies,
                proxy=args.proxy,
                timeout=15.0,
            )
            error_sink: dict[str, Any] = {}
            if room_id:
                data = await api.get_live_room_by_room_id(
                    room_id, sec_user_id=args.sec_user_id or "",
                    error_sink=error_sink,
                )
            else:
                data = await api.get_live_room(web_rid, error_sink=error_sink)
            return data, error_sink

        try:
            room, error_sink = asyncio.run(_fetch_room())
        except Exception as exc:  # noqa: BLE001
            print(f"Error: live lookup failed: {exc}", file=sys.stderr)
            return 1

        if not room:
            reason = error_sink.get("reason", "unknown")
            print(f"No room data. last error: {reason}", file=sys.stderr)
            if error_sink.get("status_code") in (403, 429, 461, 471):
                print(
                    "Hint: 抖音风控拒绝了本次签名请求；稍后重试，"
                    "或运行 `doubi auth douyin` 后用 --cookies-file 带上登录态。",
                    file=sys.stderr,
                )
            return 1

    if args.info:
        _print_live_info(room, as_json=args.json)
        return 0

    # --quality: resolve a direct pull URL and hand *that* to yt-dlp.
    record_url = args.url
    record_room_id: Optional[str] = None
    record_title: Optional[str] = None
    record_metadata: Optional[dict] = None

    if args.quality:
        row, stream_url = pick_live_quality(room, args.quality, prefer=args.format)
        if not row or not stream_url:
            available = ", ".join(
                f"{r['key']}({r['name']})" for r in (room.get("qualities") or [])
            ) or "(无)"
            print(
                f"Error: quality {args.quality!r} not available. 可选: {available}",
                file=sys.stderr,
            )
            return 1
        record_url = stream_url
        record_room_id = str(room.get("room_id") or room.get("web_rid") or "")
        record_title = str(room.get("title") or "")
        record_metadata = room
        print(f"Using quality {row['key']} ({row['name']}) via {args.format.upper()}",
              file=sys.stderr)

    output_root = args.output.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    async def _do():
        async with LiveRecorder(cookies_file=cookies, proxy=args.proxy) as rec:
            return await rec.record(
                record_url,
                output_root=output_root,
                max_duration=args.max_duration,
                room_id=record_room_id,
                title=record_title,
                metadata=record_metadata,
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
