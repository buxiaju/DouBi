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
import sys
import uuid
from typing import Any, Awaitable, Callable

from .. import __version__
from ..core.engine_loader import build_default_pipeline
from ..core.models import DownloadOptions
from ..core.config import load_config
from ..core.registry import PlatformRegistry
from .. import platforms  # noqa: F401  -- ensure all platform adapters are registered on startup

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
    return {
        "platform": item.platform.value,
        "item_id": item.item_id,
        "title": item.title,
        "author": item.author.name if item.author else None,
        "media_type": item.media_type.value,
        "source_url": item.source_url,
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
# Registry
# ---------------------------------------------------------------------------


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
}

_HANDLERS: dict[str, Callable[[dict], Any]] = {
    "platforms": _tool_platforms,
    "parse_url": _tool_parse_url,
    "add_to_queue": _tool_add_to_queue,
    "get_status": _tool_get_status,
    "list_jobs": _tool_list_jobs,
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
