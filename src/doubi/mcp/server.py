"""MCP stdio JSON-RPC 2.0 server.

Protocol summary (the bits we implement):

* Transport: newline-delimited JSON over stdin/stdout. One JSON
  object per line. **No** framing beyond ``\n``.
* Requests::

      {"jsonrpc": "2.0", "id": <int|str>, "method": "tools/list"}

      {"jsonrpc": "2.0", "id": <int|str>, "method": "tools/call",
       "params": {"name": "tool_name", "arguments": {...}}}

* Responses::

      {"jsonrpc": "2.0", "id": <id>, "result": <obj>}

      {"jsonrpc": "2.0", "id": <id>, "error": {"code": <int>, "message": "..."}}

* Notifications (no ``id``) are accepted and ignored.

Why we don't use the official ``mcp`` SDK:

* Keeps the CLI dependency-free (the mcp SDK pulls in pydantic, httpx, etc.)
* The protocol is small enough to implement cleanly
* Stdout is exclusively reserved for JSON-RPC frames so we can detect
  if the host closes the pipe
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import uuid
from collections.abc import Callable
from typing import Any, Optional

from .. import (
    __version__,
    platforms,  # noqa: F401  -- ensure all platform adapters are registered on startup
)
from ..core.config import load_config
from ..core.engine_loader import build_default_pipeline
from ..core.models import DownloadOptions
from ..core.registry import PlatformRegistry

logger = logging.getLogger("doubi.mcp.server")


# ---------------------------------------------------------------------------
# In-memory job store (separate from the REST one — kept tiny on purpose)
# ---------------------------------------------------------------------------


_JOBS: dict[str, dict[str, Any]] = {}


def _record_job(url: str, result: Any) -> str:
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {
        "job_id": job_id,
        "url": url,
        "status": "completed" if result is not None else "failed",
        "item_id": result.item_id if result is not None else None,
        "item_title": result.title if result is not None else None,
        "item_author": result.author.name if result is not None and result.author else None,
    }
    return job_id


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _tool_platforms(arguments: dict) -> dict:
    items = [
        {
            "name": a.name,
            "display_name": a.display_name,
            "media_types": a.supported_media_types(),
        }
        for a in PlatformRegistry.all()
    ]
    return {"platforms": items}


def _tool_parse_url(arguments: dict):
    """Sync check + async parse. The async part is awaited by the dispatcher."""
    url = (arguments.get("url") or "").strip()
    if not url:
        return {"error": "the 'url' argument is required"}
    adapter = PlatformRegistry.detect(url)
    if adapter is None:
        return {"error": f"no platform matches the URL: {url}"}
    # Return a coroutine that the dispatcher will await.
    return _do_parse_url(adapter, url)


async def _do_parse_url(adapter, url: str) -> dict:
    item = await adapter.parse(url)
    if item is None:
        return {"error": f"failed to parse {url}"}
    # 通用嗅探的正常产出是一个 COLLECTION（N 条 sniffed 直链），只回顶层
    # 字段的话 MCP 客户端拿到的是「解析成功但什么都没有」。递归一层把
    # children 也摊出来。
    children = [
        {
            "item_id": c.item_id,
            "title": c.title,
            "media_type": c.media_type.value,
            "source_url": c.source_url,
            "direct_url": c.extra.get("direct_url"),
            "mime": c.extra.get("mime"),
        }
        for c in (item.children or [])
    ]
    return {
        "platform": item.platform.value,
        "item_id": item.item_id,
        "title": item.title,
        "author": item.author.name if item.author else None,
        "media_type": item.media_type.value,
        "source_url": item.source_url,
        "child_count": len(children),
        "children": children,
    }


def _tool_sniff_status(arguments: dict) -> dict:
    """通用嗅探能力自检：装没装 Playwright、开没开、等多久。

    MCP 客户端（模型）拿到「解析失败」时无法自己去翻日志，给它一个可调用
    的自检口，才能自主判断是「这个站抓不到」还是「嗅探器根本没装起来」。
    """
    from ..core.sniffer import Sniffer

    cfg = load_config(None)
    return {
        "available": Sniffer.is_available(),
        "enabled": cfg.sniff_enabled,
        "duration_sec": cfg.sniff_duration_sec,
        "headless": cfg.sniff_headless,
        "auto_play": cfg.sniff_auto_play,
    }


# ---------------------------------------------------------------------------
# list_supported_sites — yt-dlp 1800+ extractor 列表查询
# ---------------------------------------------------------------------------


#: 进程级缓存：``yt_dlp.list_extractors()`` 返回的是 generator，遍历后
#: 即耗尽；同一进程多次调用必须缓存。版本/路径不变时缓存命中。
_YT_EXTRACTORS_CACHE: Optional[list[dict[str, Any]]] = None


def _load_ytdlp_extractors() -> list[dict[str, Any]]:
    """遍历 ``yt_dlp.list_extractors()`` 并序列化成 dict 列表。

    每个 extractor dict 包含：``ie_key``（yt-dlp 内部标识）、
    ``name``（人类可读） 、``host``（主域名，可能为空）、
    ``valid_url``（示例 URL，可能为空）、``age_limit``、``description``。

    字段值通过 :func:`_safe_scalar` 强转标量——某些 extractor 子类定义了
    额外属性（如 bound method、class reference），直接 json.dumps 会抛
    ``TypeError: Object of type method is not JSON serializable``。
    """
    global _YT_EXTRACTORS_CACHE
    if _YT_EXTRACTORS_CACHE is not None:
        return _YT_EXTRACTORS_CACHE
    import yt_dlp
    extractors: list[dict[str, Any]] = []
    for ie in yt_dlp.list_extractors():
        valid_url = getattr(ie, "_VALID_URL", None)
        host = _first_host(valid_url)
        desc = _safe_scalar(getattr(ie, "IE_DESC", None), "")
        # 一些 extractor 把 IE_DESC 定义成 bool / int（非字符串），下游
        # ``[:200]`` 切片会炸——统一 str() 一下再截断。
        desc = str(desc)[:200] if desc else ""
        extractors.append({
            "ie_key": _safe_scalar(getattr(ie, "ie_key", None), type(ie).__name__),
            "name": _safe_scalar(getattr(ie, "name", None), type(ie).__name__),
            "host": host,
            "valid_url": host,
            "age_limit": _safe_scalar(getattr(ie, "AGE_LIMIT", None), None),
            "description": desc,
            "working": bool(getattr(ie, "_WORKING", True)),
        })
    _YT_EXTRACTORS_CACHE = extractors
    return extractors


def _safe_scalar(value: Any, fallback: Any = None) -> Any:
    """把任意值归一成 JSON 友好的标量（str / int / bool / None / list / tuple）。

    yt-dlp extractor 子类偶尔定义 ``_VALID_URL = some_callable`` 或
    ``age_limit = property(...)`` 这类非标量属性——直接 json.dumps 会抛
    ``TypeError``。这里把 method / property / function 等「非数据」对象
    替换成 fallback，避免缓存结果里出现不可序列化的字段。

    注意：``value is None`` 时仍走 fallback 路径——上层调用方通常传
    ``fallback=str()`` 之类，避免下游 ``[:200]`` 切片 / ``.lower()`` 失败。
    """
    if isinstance(value, (str, int, bool, float)):
        return value
    if value is None:
        return fallback
    if isinstance(value, (list, tuple)):
        return [
            _safe_scalar(v, None) for v in value
            if not callable(v)
        ]
    # callable（method / function / class）/ 自定义对象 → fallback
    return fallback


def _first_host(urls: Any) -> Optional[str]:
    """``_VALID_URL`` 通常是 list[str] | str（regex pattern），抽第一条
    URL 的 host 段返回。空 / 非 str 时返回 None。
    """
    if isinstance(urls, str):
        candidates = [urls]
    elif isinstance(urls, (list, tuple)):
        candidates = [u for u in urls if isinstance(u, str)]
    else:
        return None
    for u in candidates:
        if not u:
            continue
        m = re.match(r"https?://(?:www\.)?([^/]+)", u, re.IGNORECASE)
        if m:
            return m.group(1)
        return u
    return None


def _first(urls) -> Optional[str]:  # pragma: no cover - kept for compat
    """``_VALID_URL`` 是 list[str] | str，取第一个 host 段。"""
    if not urls:
        return None
    if isinstance(urls, str):
        urls = [urls]
    for u in urls:
        if not u:
            continue
        # ``_VALID_URL`` 通常是 ``https?://(?:www\.)?example\.com/...``
        m = re.match(r"https?://(?:www\.)?([^/]+)", u, re.IGNORECASE)
        if m:
            return m.group(1)
        return u
    return None


def _tool_list_supported_sites(arguments: dict) -> dict:
    """MCP 客户端（AI agent）查询 DouBi 真正支持的下载站点。

    返回两类信息：

    * ``builtin_adapters``：4 个内置适配器（douyin / bilibili / youtube / ytdlp）
    * ``ytdlp_extractors``：yt-dlp 内置的全部 extractor（1800+ 站）

    可选参数 ``filter`` 关键字匹配 ``name`` 或 ``host``，agent 排查「这个站
    能不能下」时不用读完整列表。
    """
    filter_kw = (arguments.get("filter") or "").strip().lower()
    from ..core.registry import PlatformRegistry
    builtin = [
        {
            "name": a.name,
            "display_name": a.display_name,
            "platform": a.platform.value,
            "priority": a.priority,
            "media_types": a.supported_media_types(),
        }
        for a in PlatformRegistry.all()
    ]
    extractors = _load_ytdlp_extractors()
    if filter_kw:
        extractors = [
            e for e in extractors
            if filter_kw in (e.get("name") or "").lower()
            or filter_kw in (e.get("host") or "").lower()
            or filter_kw in (e.get("description") or "").lower()
        ]
    return {
        "builtin_adapters": builtin,
        "ytdlp_extractor_count": len(extractors),
        "ytdlp_extractors": extractors,
        "note": (
            "Call parse_url with the URL directly — ytdlp_generic will route "
            "to the matching extractor automatically. This list is for "
            "discovery / debugging only."
        ),
    }


async def _tool_add_to_queue(arguments: dict) -> dict:
    url = (arguments.get("url") or "").strip()
    if not url:
        return {"error": "the 'url' argument is required"}
    cfg = load_config(None)
    options = DownloadOptions(
        output_root=cfg.output_root,
        filename_template=cfg.filename_template,
        container=cfg.container,
        max_quality=cfg.max_quality,
        database=cfg.database_path if cfg.database else None,
        manifest=cfg.manifest_path,
    )
    pipeline = build_default_pipeline()
    item = await pipeline.process_url(url, options)
    job_id = _record_job(url, item)
    return {
        "job_id": job_id,
        "status": "completed" if item is not None else "failed",
        "title": item.title if item else None,
    }


def _tool_get_status(arguments: dict) -> dict:
    job_id = (arguments.get("job_id") or "").strip()
    if not job_id:
        return {"error": "the 'job_id' argument is required"}
    job = _JOBS.get(job_id)
    if job is None:
        return {"error": f"job not found: {job_id}"}
    return job


def _tool_list_jobs(arguments: dict) -> dict:
    limit = int(arguments.get("limit", 20))
    items = list(_JOBS.values())[:limit]
    return {"jobs": items}


# ---------------------------------------------------------------------------
# 0.3.3 P1-4 — collection tools (search / hot) shared with the CLI.
# ---------------------------------------------------------------------------
async def _tool_collect_search(arguments: dict) -> dict:
    """MCP wrapper around ``doubi search``.

    Returns the same JSON records the CLI emits (``aweme`` /
    ``user`` / ``room`` dicts for 抖音; ``video`` / ``user`` for B 站).
    Logged-in users get stable results; logged-out callers will see
    empty results and should rely on the ``need_login`` convention
    surfaced elsewhere.
    """
    from doubi.cli.main import collect_search_async

    keyword = (arguments.get("keyword") or "").strip()
    if not keyword:
        return {"error": "the 'keyword' argument is required"}
    platform = (arguments.get("platform") or "douyin").lower()
    if platform not in {"douyin", "bilibili"}:
        return {"error": f"unknown platform: {platform!r}"}
    channel = arguments.get("channel") or _DEFAULT_SEARCH_CHANNEL[platform]
    allowed_channels = _ALLOWED_SEARCH_CHANNELS[platform]
    if channel not in allowed_channels:
        return {
            "error": (
                f"channel {channel!r} not valid for platform {platform!r}; "
                f"expected one of {sorted(allowed_channels)}"
            ),
        }
    try:
        max_count = int(arguments.get("max", 20))
    except (TypeError, ValueError):
        return {"error": "the 'max' argument must be an integer"}
    cfg = load_config(None)
    try:
        rows = await collect_search_async(
            keyword=keyword,
            channel=channel,
            platform=platform,
            max_count=max_count,
            cookies_file=cfg.cookies_file,
            proxy=cfg.proxy,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"search failed: {exc}"}
    return {
        "keyword": keyword, "platform": platform,
        "channel": channel, "results": rows,
    }


async def _tool_collect_hot(arguments: dict) -> dict:
    """MCP wrapper around ``doubi hot``."""
    from doubi.cli.main import collect_hot_async

    platform = (arguments.get("platform") or "douyin").lower()
    if platform not in {"douyin", "bilibili"}:
        return {"error": f"unknown platform: {platform!r}"}
    board = arguments.get("board") or "all"
    try:
        max_count = int(arguments.get("max", 50))
    except (TypeError, ValueError):
        return {"error": "the 'max' argument must be an integer"}
    cfg = load_config(None)
    try:
        rows = await collect_hot_async(
            board=board,
            platform=platform,
            max_count=max_count,
            cookies_file=cfg.cookies_file,
            proxy=cfg.proxy,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"hot fetch failed: {exc}"}
    return {
        "board": board, "platform": platform, "results": rows,
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


# 0.3.4 — allow-list per platform + sensible default channel. Keeping the
# pair in one place so the same constants back MCP / REST / GUI.
_DEFAULT_SEARCH_CHANNEL: dict[str, str] = {
    "douyin": "general",
    "bilibili": "video",
}
_ALLOWED_SEARCH_CHANNELS: dict[str, set[str]] = {
    "douyin": {"general", "video", "user", "live"},
    "bilibili": {"video", "user"},
}


TOOLS: dict[str, dict[str, Any]] = {
    "platforms": {
        "description": "List all registered platform adapters with their supported media types.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "parse_url": {
        "description": (
            "Parse a media URL into a structured item (title, author, item_id, etc.) "
            "without downloading. Use this to inspect a URL before queuing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to parse."},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    "add_to_queue": {
        "description": (
            "Submit a URL for download. Returns a job_id you can poll with "
            "get_status. Supports 抖音, B 站, and any URL yt-dlp can handle."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to download."},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    "get_status": {
        "description": "Look up a previously-submitted job by job_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The job_id returned by add_to_queue."},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    "list_jobs": {
        "description": "List recent jobs (most recent first).",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max jobs to return (default 20)."},
            },
            "additionalProperties": False,
        },
    },
    "sniff_status": {
        "description": (
            "Report generic-sniffer capability: whether Playwright is available, "
            "whether sniffing is enabled, and how long an unknown URL will take. "
            "Call this when parse_url fails on an unrecognized site."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "list_supported_sites": {
        "description": (
            "List every site DouBi can download from: the 4 built-in adapters "
            "(douyin / bilibili / youtube / ytdlp_generic) plus the full "
            "yt-dlp extractor list (~1800 sites — Twitter, Instagram, Vimeo, "
            "Reddit, Pixiv, AcFun, 网易云, QQ音乐, 喜马拉雅, 央视频, 虎牙, 斗鱼, "
            "西瓜视频, 优酷, …). Optional `filter` keyword narrows the list "
            "by name/host. Call parse_url with the URL directly to download — "
            "ytdlp_generic routes to the matching extractor automatically. "
            "Use this list for discovery / debugging."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "Optional keyword; matches against extractor name, "
                        "host, or description (case-insensitive)."
                    ),
                },
            },
            "additionalProperties": False,
        },
    },
    "collect_search": {
        "description": (
            "0.3.3 P1-4 — search a platform by keyword. ``platform=douyin`` "
            "(default) covers general / video / user / live channels (aweme / "
            "user / room records); ``platform=bilibili`` covers video / user "
            "channels (video / bili_user records, WBI-signed). "
            "Returns the same JSON records the CLI emits. Logged-in "
            "callers get stable results; logged-out callers may get empty "
            "lists — surface a login hint in that case."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["douyin", "bilibili"],
                    "description": "Which platform to search (default: douyin).",
                },
                "keyword": {
                    "type": "string",
                    "description": "Search keyword (Chinese / English / mixed).",
                },
                "channel": {
                    "type": "string",
                    "description": (
                        "Channel depends on platform — see collect_search doc. "
                        "Defaults: douyin→general, bilibili→video."
                    ),
                },
                "max": {
                    "type": "integer",
                    "description": "Max records to return (default: 20).",
                },
            },
            "required": ["keyword"],
            "additionalProperties": False,
        },
    },
    "collect_hot": {
        "description": (
            "0.3.3 P1-4 — fetch trending entries. ``platform=douyin`` returns "
            "the four named hot boards (aggregated when board=all). "
            "``platform=bilibili`` returns the top 50 hot-search keywords + "
            "the top 20 popular videos. Records carry ``board`` / "
            "``board_name`` so downstream consumers can render the row without "
            "re-mapping the key."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["douyin", "bilibili"],
                    "description": "Which platform to fetch (default: douyin).",
                },
                "board": {
                    "type": "string",
                    "description": (
                        "Board key. 抖音 has all/positive/entertainment/society/challenge. "
                        "Ignored when platform=bilibili."
                    ),
                },
                "max": {
                    "type": "integer",
                    "description": "Max rows per source (default: 50).",
                },
            },
            "additionalProperties": False,
        },
    },
}

_HANDLERS: dict[str, Callable[[dict], Any]] = {
    "platforms": _tool_platforms,
    "parse_url": _tool_parse_url,
    "add_to_queue": _tool_add_to_queue,
    "get_status": _tool_get_status,
    "list_jobs": _tool_list_jobs,
    "sniff_status": _tool_sniff_status,
    "list_supported_sites": _tool_list_supported_sites,
    "collect_search": _tool_collect_search,
    "collect_hot": _tool_collect_hot,
}


# ---------------------------------------------------------------------------
# JSON-RPC dispatch
# ---------------------------------------------------------------------------


def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _dispatch(req: dict) -> dict | None:
    """Handle a single JSON-RPC request. Returns the response dict,
    or ``None`` for notifications (no ``id`` field)."""
    if req.get("jsonrpc") != "2.0":
        return _err(req.get("id"), -32600, "invalid jsonrpc version")
    method = req.get("method")
    req_id = req.get("id")
    if req_id is None:
        # Notification: don't reply
        return None

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "doubi", "version": __version__},
            "capabilities": {"tools": {}},
        })

    if method == "tools/list":
        return _ok(req_id, {
            "tools": [
                {"name": name, "description": meta["description"],
                 "inputSchema": meta["input_schema"]}
                for name, meta in TOOLS.items()
            ],
        })

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = _HANDLERS.get(name)
        if handler is None:
            return _err(req_id, -32601, f"unknown tool: {name}")
        try:
            result = handler(args)
            # Some handlers return a coroutine (deferring async work
            # to the dispatcher); await it transparently.
            if asyncio.iscoroutine(result):
                result = await result
            return _ok(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            })
        except Exception as exc:
            logger.exception("tool %s failed", name)
            return _ok(req_id, {
                "content": [{"type": "text",
                              "text": json.dumps({"error": str(exc)}, ensure_ascii=False)}],
                "isError": True,
            })

    return _err(req_id, -32601, f"method not found: {method}")


# ---------------------------------------------------------------------------
# stdio loop
# ---------------------------------------------------------------------------


async def run_stdio() -> None:
    """Run the JSON-RPC server on stdin/stdout.

    This is a long-running coroutine: it reads lines from stdin,
    dispatches each one, and writes the response to stdout. Logging
    goes to stderr so it never interferes with the JSON-RPC stream.

    Note: we read stdin via a worker thread (``asyncio.to_thread``)
    because Windows' ``connect_read_pipe`` is unreliable for console
    stdin — a blocking readline in the executor is the portable
    approach.
    """
    loop = asyncio.get_running_loop()

    # Ensure stdout is line-buffered
    writer = sys.stdout
    if hasattr(writer, "reconfigure"):
        try:
            writer.reconfigure(line_buffering=True)
        except Exception:  # pragma: no cover
            pass

    logger.info("DouBi MCP server started (pid=%d)", __import__("os").getpid())

    # 通用嗅探（M6.16）：把 AppConfig 注入兜底适配器。这是 MCP 侧唯一的
    # ``AppConfig → Sniffer`` 注入口，四个入口（CLI/GUI/REST/MCP）各自负责
    # 调一次，漏掉哪个那个入口的嗅探配置就静默失效（硬约束 #4）。
    from ..platforms.generic import GenericAdapter
    GenericAdapter.set_config(load_config(None))
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            logger.info("MCP stdin closed; shutting down")
            return
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("invalid JSON on stdin: %s", exc)
            writer.write(json.dumps(_err(None, -32700, f"parse error: {exc}")) + "\n")
            writer.flush()
            continue
        resp = await _dispatch(req)
        if resp is not None:
            writer.write(json.dumps(resp, ensure_ascii=False) + "\n")
            writer.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doubi-mcp",
        description="DouBi MCP stdio bridge. Reads JSON-RPC on stdin, writes to stdout.",
    )
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stderr,    # never mix with stdout JSON-RPC
    )
    asyncio.run(run_stdio())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
