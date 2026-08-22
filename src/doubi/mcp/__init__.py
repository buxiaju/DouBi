"""MCP (Model Context Protocol) surface for DouBi.

A minimal stdio JSON-RPC 2.0 bridge that exposes the platform /
pipeline / DB layers as a set of *tools* an LLM can call. Designed
to be launched by Claude Desktop, Cursor, or any other MCP client
that supports the stdio transport.

Why stdlib-only:

* Zero dependencies → the user can run ``doubi mcp`` without
  installing fastmcp or any other package, which matters for
  Claude Desktop's plugin sandbox.
* Full control over framing (each JSON object is one line on stdin
  and one line on stdout) so it's easy to log and debug.

Tools exposed:

* ``platforms``     — list registered platform adapters
* ``parse_url``     — parse a URL into a MediaItem (no download)
* ``add_to_queue``   — submit a URL for download (returns a job_id)
* ``get_status``     — query a job's status / counts
* ``list_jobs``      — list recent jobs

Run via ``doubi mcp`` (or ``python -m doubi.mcp.server``).
"""

from __future__ import annotations

from .server import main, run_stdio

__all__ = ["main", "run_stdio"]
