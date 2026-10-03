"""Row → download target resolution for the search / hot pages (0.3.6).

Both pages render *raw* upstream records — the same dicts the CLI prints
as JSONL — not :class:`~doubi.core.models.MediaItem` objects. The parse
page can hand its rows straight to the task manager because parsing
already produced models; search / hot rows need two things first:

1. **A URL.** ``doubi search`` synthesises a ``share_url`` for each hit
   (see ``cli.main._build_share_url``) and most records carry it. 抖音
   热榜 rows never do — they only have ``sentence_id``, so a ``share_url``
   has to be built here.

2. **A ``MediaItem``.** The engine takes models. Rather than duplicating
   the adapters' field mapping, the resolved URL is fed through
   ``PlatformRegistry.detect()`` + ``adapter.parse()`` — the exact path
   the parse page uses. That keeps one source of truth for
   URL → item metadata instead of a second, drifting copy in the UI.

Every function here is pure (no Qt, no network at import time) so the
rules are unit-testable without a QApplication — and therefore still run
under the ``ci`` profile, where the GUI packages are absent.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("doubi.ui.row_actions")

#: Key order used when sniffing an id out of a raw search / hot record.
#: ``aweme_id`` is first because 抖音 "general" hits are videos that also
#: carry a ``uid`` for their author — preferring ``uid`` would build a
#: profile URL for a video row.
ID_KEYS: tuple[str, ...] = (
    "aweme_id",
    "bvid",
    "item_id",
    "room_id",
    "id_str",
    "uid",
    "mid",
    "sec_uid",
)


def row_item_id(row: dict[str, Any]) -> str:
    """First non-empty id field of *row*, as a string (``""`` if none)."""
    if not isinstance(row, dict):
        return ""
    for key in ID_KEYS:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def douyin_share_url(row: dict[str, Any]) -> Optional[str]:
    """Best-effort 抖音 URL for a ``search`` / ``hot`` record.

    Mirrors ``cli.main._build_share_url`` but additionally handles the two
    shapes search / hot add on top of the CLI's ``type``-driven switch:

    * ``hot`` rows (``word`` / ``sentence_id`` / ``hot_value``, no id at
      all) → ``https://www.douyin.com/search/<word>``, which is what
      right-clicking a hot word actually means.
    * rows that are recognisably a live room or a user profile even
      though the caller does not know the channel.

    Returns ``None`` when nothing usable is present.
    """
    if not isinstance(row, dict):
        return None

    # A container / composite record may already know its own URL.
    explicit = row.get("share_url") or row.get("url")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    # Hot-word rows: no video id exists, the word *is* the query.
    word = row.get("word") or row.get("sentence")
    if isinstance(word, str) and word.strip():
        from urllib.parse import quote

        return f"https://www.douyin.com/search/{quote(word.strip())}"

    # Live rooms carry room_id / id_str; check before the video branch
    # because a live record also has ``uid`` for its host.
    room_id = row.get("room_id") or row.get("id_str")
    if room_id and not row.get("aweme_id"):
        return f"https://live.douyin.com/{room_id}"

    aweme_id = row.get("aweme_id")
    if aweme_id:
        return f"https://www.douyin.com/video/{aweme_id}"

    # User hits: ``sec_uid`` is the canonical profile handle.
    sec_uid = row.get("sec_uid")
    if sec_uid:
        return f"https://www.douyin.com/user/{sec_uid}"

    uid = row.get("uid")
    if uid and row.get("nickname"):
        return f"https://www.douyin.com/user/{uid}"

    return None


def bilibili_share_url(row: dict[str, Any]) -> Optional[str]:
    """Best-effort B 站 URL for a ``search`` / ``hot`` record.

    * video → ``https://www.bilibili.com/video/<bvid>`` (falls back to
      ``aid`` as ``/video/av<aid>``)
    * user  → ``https://space.bilibili.com/<mid>``

    Returns ``None`` when nothing usable is present.
    """
    if not isinstance(row, dict):
        return None

    explicit = row.get("share_url") or row.get("url")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    bvid = row.get("bvid")
    if bvid:
        return f"https://www.bilibili.com/video/{bvid}"

    aid = row.get("aid")
    if aid:
        return f"https://www.bilibili.com/video/av{aid}"

    # A B 站 search "user" hit is ``{mid, uname, ...}``; ``mid`` doubles
    # as the profile path.
    mid = row.get("mid")
    if mid:
        return f"https://space.bilibili.com/{mid}"

    return None


def share_url_for(row: dict[str, Any], platform: str) -> Optional[str]:
    """Platform-dispatch wrapper around the two builders above."""
    if platform == "bilibili":
        return bilibili_share_url(row)
    if platform == "douyin":
        return douyin_share_url(row)
    return None


def is_hot_word_row(row: dict[str, Any]) -> bool:
    """True when *row* is a 热搜词 entry rather than a video / user / room.

    Hot-word records are the only ones carrying ``word`` /
    ``sentence_id``; they cannot be downloaded directly, which is why the
    hot page routes them through a search instead.
    """
    if not isinstance(row, dict):
        return False
    if row.get("aweme_id") or row.get("bvid") or row.get("room_id"):
        return False
    return bool(row.get("word") or row.get("sentence_id"))


def row_label(row: dict[str, Any]) -> str:
    """Human-readable one-liner for a record, used in toasts / errors."""
    if not isinstance(row, dict):
        return ""
    for key in ("title", "word", "nickname", "uname", "sentence"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return row_item_id(row)


async def build_media_item(url: str):
    """Resolve *url* into a :class:`MediaItem` via the platform registry.

    Returns ``(item, children)`` — ``children`` is non-empty only when the
    URL turned out to be a container (user profile / collection). Returns
    ``(None, [])`` when no adapter claims the URL or parsing fails; the
    caller decides how to report that.

    A parse failure is **not** fatal: 抖音 search hits can be resolved
    from the URL alone even when metadata fetching is risk-controlled, and
    the adapter itself falls back to a minimal item in that case.
    """
    from ..core.registry import PlatformRegistry

    if not url:
        return None, []

    try:
        adapter = PlatformRegistry.detect(url)
    except Exception:  # noqa: BLE001 - defensive, registry is pure
        logger.exception("detect() raised for %r", url)
        adapter = None

    if adapter is None:
        logger.info("no adapter claims %r", url)
        return None, []

    try:
        item = await adapter.parse(url)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller
        logger.warning("parse(%r) failed: %s", url, exc)
        return None, []

    if item is None:
        logger.info("parse(%r) returned None", url)
        return None, []

    # Containers (user profile / collection URL) arrive with their
    # children attached or expandable. Hand back what we have; the
    # caller enqueues the children when there are any.
    children = list(item.children or [])
    return item, children
