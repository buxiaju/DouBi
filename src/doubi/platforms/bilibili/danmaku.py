"""Bilibili danmaku (弹幕) sidecar download.

**Why this lives in ``platforms/bilibili/`` and not in the engine**

yt-dlp's ``writesubtitles`` cannot fetch danmaku. Danmaku is not a
subtitle track: it is addressed by the *page*'s ``cid`` (an internal
numeric id, **not** the ``BVxxxx`` id), served from a separate endpoint,
and returned as deflate-compressed XML. Nothing about that is
expressible as a yt-dlp option, and the ``cid`` lookup needs the same
cookie/UA/buvid3 dance as the rest of :class:`BilibiliAPI` (see the
412 notes there). That makes it platform knowledge, so it is reached
through :meth:`PlatformAdapter.post_download`.

**Output format**

The raw B 站 XML pool is written verbatim as ``<basename>.danmaku.xml``
next to the media file. It is deliberately *not* converted to ASS:
the XML is the lossless original that every downstream danmaku player
(dandanplay, PotPlayer plugins, ASS converters) accepts, and burning a
styling decision into the download step would throw information away.

**Known limitation**

``/x/v1/dm/list.so`` returns the *current* danmaku pool, which B 站
caps and samples for long videos. Full history requires the paginated
protobuf endpoint plus a logged-in account; that is out of scope here
and would still not be complete.
"""

from __future__ import annotations

import logging
import re
import zlib
from pathlib import Path
from typing import Any, Optional

from ...core.models import DownloadOptions, MediaItem

logger = logging.getLogger("doubi.platforms.bilibili.danmaku")

DANMAKU_SUFFIX = ".danmaku.xml"

_DANMAKU_URL = "https://api.bilibili.com/x/v1/dm/list.so"

_BVID_RE = re.compile(r"(BV[0-9A-Za-z]{8,})")
_PAGE_RE = re.compile(r"[?&]p=(\d+)")


# ---------------------------------------------------------------------------
# cid resolution
# ---------------------------------------------------------------------------

def _coerce_cid(value: Any) -> Optional[int]:
    try:
        cid = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return cid if cid > 0 else None


def extract_bvid(item: MediaItem) -> str:
    """Best-effort ``BVxxxx`` for *item*.

    Children of a multi-page container get synthetic ids such as
    ``BV1xx_p3`` / ``BV1xx#p3``, so the id cannot be used raw. The
    parent bvid recorded in ``extra`` is authoritative when present;
    otherwise we pattern-match, which also covers the source URL.
    """
    parent = item.extra.get("parent_bvid")
    if parent:
        found = _BVID_RE.search(str(parent))
        if found:
            return found.group(1)
    for candidate in (item.item_id, item.source_url):
        if not candidate:
            continue
        found = _BVID_RE.search(str(candidate))
        if found:
            return found.group(1)
    return ""


def extract_page_index(item: MediaItem) -> int:
    """1-based page number for *item*; ``1`` when it is not a 分P child."""
    recorded = item.extra.get("page_index")
    if recorded is not None:
        try:
            page = int(recorded)
            if page > 0:
                return page
        except (TypeError, ValueError):
            pass
    if item.source_url:
        found = _PAGE_RE.search(item.source_url)
        if found:
            try:
                page = int(found.group(1))
                if page > 0:
                    return page
            except ValueError:
                pass
    return 1


async def resolve_cid(api: Any, item: MediaItem) -> Optional[int]:
    """Find the ``cid`` of the page *item* represents.

    ``extra["cid"]`` is used when the adapter already knows it (the
    official view/season payloads carry it). Otherwise we fall back to
    one ``/x/web-interface/view`` call and pick the matching page, which
    is the only way to learn the ``cid`` of a plain single video.
    """
    direct = _coerce_cid(item.extra.get("cid"))
    if direct is not None:
        return direct

    bvid = extract_bvid(item)
    if not bvid:
        logger.debug("danmaku: no bvid derivable from %s", item.item_id)
        return None

    pages = await api.fetch_view_pages(bvid)
    if not pages:
        return None

    wanted = extract_page_index(item)
    # Prefer the declared page number: 分P numbering is not guaranteed to
    # be dense (deleted pages leave gaps), so positional indexing alone
    # would silently grab the wrong page's danmaku.
    for page in pages:
        if not isinstance(page, dict):
            continue
        if _coerce_cid(page.get("page")) == wanted:
            cid = _coerce_cid(page.get("cid"))
            if cid is not None:
                return cid
    if 0 < wanted <= len(pages):
        entry = pages[wanted - 1]
        if isinstance(entry, dict):
            return _coerce_cid(entry.get("cid"))
    return None


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def _decode_body(raw: bytes) -> Optional[str]:
    """Decode a danmaku response body into XML text.

    ``list.so`` historically answers with *raw* deflate and no
    ``Content-Encoding`` header, which no HTTP client decompresses for
    us; sometimes it answers with plain XML. Both shapes are handled,
    and the raw-deflate attempt uses a negative window size because the
    payload has no zlib wrapper.
    """
    if not raw:
        return None
    head = raw[:8].lstrip()
    if head.startswith(b"<"):
        return raw.decode("utf-8", errors="replace")
    for wbits in (-zlib.MAX_WBITS, zlib.MAX_WBITS | 32):
        try:
            return zlib.decompress(raw, wbits).decode("utf-8", errors="replace")
        except zlib.error:
            continue
    logger.debug("danmaku: unrecognised response body (%d bytes)", len(raw))
    return None


async def fetch_danmaku_xml(api: Any, cid: int, *, bvid: str = "") -> Optional[str]:
    """Download the danmaku XML pool for *cid*, or ``None`` on any failure.

    Mirrors :meth:`BilibiliAPI.fetch_view_data`'s header recipe: a
    desktop UA plus a matching ``Referer``, and the cookie header only
    when we actually have cookies.
    """
    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Referer": (
            f"https://www.bilibili.com/video/{bvid}/"
            if bvid else "https://www.bilibili.com/"
        ),
    }
    cookie_header = api.build_cookie_header()
    if cookie_header:
        headers["Cookie"] = cookie_header

    try:
        async with httpx.AsyncClient(
            headers=headers, timeout=getattr(api, "timeout", 30)
        ) as client:
            resp = await client.get(_DANMAKU_URL, params={"oid": cid})
            if resp.status_code != 200:
                logger.debug("danmaku: HTTP %s for cid=%s", resp.status_code, cid)
                return None
            body = resp.content
    except Exception as exc:   # noqa: BLE001
        logger.debug("danmaku: httpx error for cid=%s: %s", cid, exc)
        return None

    xml = _decode_body(body)
    if not xml or "<i" not in xml:
        # An empty pool still returns a well-formed <i> document, so a
        # missing root means we got an error page rather than "0 danmaku".
        logger.debug("danmaku: no XML document for cid=%s", cid)
        return None
    return xml


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------

def write_danmaku(
    item: MediaItem, options: DownloadOptions, xml_text: str
) -> Optional[Path]:
    """Write *xml_text* beside the media file. Returns the path, or ``None``.

    The directory comes from :func:`resolve_item_dir` and the stem from
    ``item.output_template`` — the same two inputs the engine used — so
    the sidecar always pairs with the file that was just downloaded.
    """
    basename = item.output_template
    if not basename:
        return None
    from ...core.storage.file_layout import resolve_item_dir

    target = resolve_item_dir(item, options) / (basename + DANMAKU_SUFFIX)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(xml_text, encoding="utf-8")
    except OSError as exc:
        logger.warning("danmaku: cannot write %s: %s", target, exc)
        return None
    return target


async def download_danmaku(
    api: Any, item: MediaItem, options: DownloadOptions
) -> Optional[Path]:
    """Resolve the cid, fetch the pool and write the sidecar.

    Never raises: the media file is already on disk by the time this
    runs, so a danmaku failure must not turn a successful download into
    a failed one.
    """
    try:
        cid = await resolve_cid(api, item)
        if cid is None:
            logger.info("danmaku: no cid for %s; skipped", item.item_id)
            return None
        xml = await fetch_danmaku_xml(api, cid, bvid=extract_bvid(item))
        if xml is None:
            logger.info("danmaku: fetch failed for cid=%s; skipped", cid)
            return None
        return write_danmaku(item, options, xml)
    except Exception as exc:   # noqa: BLE001
        logger.warning("danmaku: unexpected failure for %s: %s", item.item_id, exc)
        return None
