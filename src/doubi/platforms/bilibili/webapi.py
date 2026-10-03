"""Bilibili search / hot / popular webapi (0.3.4).

Three endpoints the GUI / CLI / MCP / REST all want to share:

* **search_type** — ``/x/web-interface/wbi/search/type`` with
  ``search_type`` ∈ ``video`` / ``bili_user``. WBI-signed + ``buvid3``
  cookie required (anonymous requests return -412).
* **hotword** — ``https://s.search.bilibili.com/main/hotword`` returns
  the top 10 trending keywords. No WBI required.
* **popular** — ``/x/web-interface/popular?pn=1&ps=20`` returns the
  top 20 most-popular videos on B 站 (works anonymously, no WBI).
* **ranking** — ``/x/web-interface/ranking/v2?rid=0&type=all`` returns
  the full ranking list with view / like / coin counts.

Why a separate module: :mod:`platforms.bilibili.api` is built around
``yt_dlp.YoutubeDL`` for actual download flows. The endpoints here don't
download anything — they're JSON feeds the GUI wants to render. Putting
them in ``api.py`` would dilute that module's contract (and force every
import path to also drag in yt-dlp).

Record schema (deliberately aligned with :func:`doubi.platforms.douyin
.webapi.DouyinWebAPI.search_general` output so the GUI's table renderer
can stay platform-agnostic):

* ``title`` — display title (or ``nickname`` for user search)
* ``author`` — ``{"name": ..., "mid": ...}`` (or ``nickname`` for users)
* ``item_id`` — bvid / mid / hot_word
* ``share_url`` — canonical / rich share URL
* ``platform`` — ``"bilibili"``
* ``channel`` — echo of the ``channel`` arg (for GUI to render correctly)

All entries also carry ``result_type`` (``video`` / ``user`` / ``hot`` /
``popular``) so the GUI can show a platform badge if it wants to.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Optional
from urllib.parse import urlencode, quote

import httpx

from .wbi import fetch_wbi_keys, sign_query

logger = logging.getLogger("doubi.platforms.bilibili.webapi")


# -----------------------------------------------------------------------
# Endpoints — module-level constants so the tests can stub them out.
# 0.3.4 ships the *exact* URLs B 站 documents. Anything more aggressive
# (signed feed endpoints, web-nav lookup) is left for a future version.
# -----------------------------------------------------------------------

SEARCH_TYPE_URL = (
    "https://api.bilibili.com/x/web-interface/wbi/search/type"
)
HOTWORD_URL = "https://s.search.bilibili.com/main/hotword"
POPULAR_URL = "https://api.bilibili.com/x/web-interface/popular"
RANKING_URL = "https://api.bilibili.com/x/web-interface/ranking/v2"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# -----------------------------------------------------------------------
# Cookie + buvid3 helpers
# -----------------------------------------------------------------------


def _read_cookie_dicts(cookies_file: Optional[str]) -> list[dict[str, Any]]:
    """Load cookies.txt into the dict shape httpx wants.

    0.3.6 — ``cookies_file=None`` now falls back to
    :func:`doubi.platforms.bilibili.auth.default_cookie_path` instead of
    returning ``[]``. This mirrors :class:`DouyinWebAPI`, which has
    always resolved the default path itself.

    Before the fix the asymmetry was a silent dead end: the GUI / REST /
    MCP layers all pass ``cfg.cookies_file`` straight through, and that
    field is ``None`` in a stock ``~/.doubi/config.yml`` — the user logs
    in via the settings page (writing ``~/.doubi/cookies/bilibili.txt``)
    but never edits ``config.yml``. B 站 then received an empty cookie
    jar, ``wbi`` search answered ``code=-101``, and 搜索 showed
    「暂无结果」 even though the cookie file was right there.
    """
    from pathlib import Path
    from .auth import default_cookie_path, has_cookie_file, parse_netscape_file

    path: Optional[Path] = None
    if cookies_file:
        # 显式传入的路径：即使存在性存疑也按它读，保持调用方语义。
        path = Path(cookies_file)
    else:
        candidate = default_cookie_path()
        if has_cookie_file(candidate):
            path = candidate
    if path is None:
        return []

    try:
        return parse_netscape_file(path)
    except Exception as exc:   # noqa: BLE001
        logger.debug("BilibiliWebAPI: failed to read cookie file: %s", exc)
        return []


def _to_httpx_cookies(
    cookie_dicts: Iterable[dict[str, Any]],
    *,
    domain_filter: str = ".bilibili.com",
) -> dict[str, str]:
    """Pick the cookies relevant for the domain so httpx sends them.

    Netscape files contain entries for every domain the browser has ever
    visited; without this filter httpx would attach dozens of irrelevant
    cookies (Google, GitHub, …) and B 站 starts to refuse them.
    """
    out: dict[str, str] = {}
    for c in cookie_dicts:
        name = c.get("name")
        value = c.get("value")
        domain = c.get("domain", "")
        if not name or value is None:
            continue
        if domain_filter and domain_filter not in domain:
            continue
        out[name] = str(value)
    return out


# -----------------------------------------------------------------------
# The client
# -----------------------------------------------------------------------


class BilibiliWebAPI:
    """Async client for B 站 search / hot / popular JSON endpoints.

    Lifecycle: one instance per call site. The wrapper fetches / caches
    the (img_key, sub_key) pair on first use; reuse the same instance
    within a single GUI session so the keys are hit once. ``close()``
    shuts down the underlying httpx client.
    """

    def __init__(
        self,
        *,
        cookies_file: Optional[str] = None,
        proxy: Optional[str] = None,
        timeout: float = 15.0,
        http_client: Any = None,
    ):
        self.cookies_file = cookies_file
        self.proxy = proxy
        self.timeout = timeout
        # 允许测试注入假 httpx 客户端（production = None ⇒ 自行创建）。
        self._client: Optional[httpx.AsyncClient] = http_client
        self._owns_client: bool = http_client is None
        # WBI keys are fetched on demand and cached for the instance's life.
        self._wbi_keys: Optional[tuple[str, str]] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            kwargs: dict[str, Any] = {
                "timeout": self.timeout,
                "headers": {"User-Agent": _USER_AGENT},
            }
            cookie_dicts = _read_cookie_dicts(self.cookies_file)
            cookies = _to_httpx_cookies(cookie_dicts)
            if cookies:
                kwargs["cookies"] = cookies
            if self.proxy:
                kwargs["proxy"] = self.proxy
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "BilibiliWebAPI":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ---- WBI keys -------------------------------------------------

    async def _get_wbi_keys(self) -> Optional[tuple[str, str]]:
        if self._wbi_keys is not None:
            return self._wbi_keys
        # httpx 比手工 headers 简单；如果 cookies 已经挂在 client 上，
        # ``fetch_wbi_keys`` 仍然会自己 new 一个 client 用自己的 UA；
        # 这里直接走它内置的。
        try:
            cookies = _to_httpx_cookies(_read_cookie_dicts(self.cookies_file))
        except Exception:   # noqa: BLE001
            cookies = {}
        self._wbi_keys = await fetch_wbi_keys(cookies=list(cookies.items()))
        return self._wbi_keys

    # ---- search ---------------------------------------------------

    async def search(
        self,
        keyword: str,
        *,
        channel: str = "video",   # "video" / "user"
        max_count: int = 20,
        error_sink: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """Search B 站 by keyword.

        :param channel: ``video`` → ``/x/web-interface/wbi/search/type?search_type=video``;
            ``user`` → ``search_type=bili_user``.
        :param max_count: max results to return (clamped to 50 by B 站).
        :param error_sink: optional dict; on failure ``error`` is written here
            and ``[]`` is returned. CLI/GUI can render this without try/except.
        """
        if channel not in {"video", "user"}:
            raise ValueError(
                f"unknown bilibili search channel: {channel!r} "
                "(expected 'video' or 'user')"
            )
        keys = await self._get_wbi_keys()
        if keys is None:
            # 没拿到 wbi keys 几乎总是「网络问题」，把它当成 fetch 失败。
            if error_sink is not None:
                error_sink["error"] = "fetch_wbi_keys failed"
            return []

        page_size = max(1, min(int(max_count), 50))
        params = {
            "keyword": keyword,
            "search_type": "video" if channel == "video" else "bili_user",
            "page": 1,
            "pagesize": page_size,
        }
        signed = sign_query(params, keys)
        url = f"{SEARCH_TYPE_URL}?{urlencode(signed)}"
        client = await self._ensure_client()
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("bilibili search failed: %s", exc)
            if error_sink is not None:
                error_sink["error"] = str(exc)
            return []

        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if payload.get("code") not in (0, None):
            code = payload.get("code")
            message = payload.get("message") or "unknown"
            if error_sink is not None:
                error_sink["error"] = f"code={code} {message}"
            logger.debug(
                "bilibili search non-zero code: %s %s", code, message,
            )
            return []

        rows = (payload.get("data") or {}).get("result") or []
        records: list[dict[str, Any]] = []
        for raw in rows[:page_size]:
            rec = self._adapt_search_hit(raw, channel)
            if rec:
                records.append(rec)
        return records

    @staticmethod
    def _adapt_search_hit(raw: dict, channel: str) -> Optional[dict]:
        """Normalize a B 站 search hit into the platform-agnostic schema."""
        # 视频通道的 hit 是 dict 里有 ``title`` / ``bvid`` / ``aid`` / ``author``。
        # 用户通道是 ``uname`` / ``mid``。两者 result_type 字段不同。
        if channel == "video":
            title = raw.get("title") or ""
            # B 站用 ``<em class="keyword">`` 包搜索词；剥掉，保留纯文本。
            title = re.sub(r"</?em[^>]*>", "", title)
            bvid = raw.get("bvid") or ""
            aid = raw.get("id")  # int
            author = raw.get("author") or ""
            mid = raw.get("mid")
            share_url = (
                f"https://www.bilibili.com/video/{bvid}" if bvid
                else f"https://www.bilibili.com/video/av{aid}" if aid else ""
            )
            return {
                "title": title,
                "author": {"name": author, "mid": mid},
                "item_id": bvid or str(aid or ""),
                "share_url": share_url,
                "platform": "bilibili",
                "channel": "video",
                "result_type": "video",
                "duration": raw.get("duration") or "",
                "play": raw.get("play") or 0,
                "pubdate": raw.get("pubdate") or 0,
            }
        # user
        uname = raw.get("uname") or ""
        mid = raw.get("mid")
        usign = raw.get("usign") or ""
        share_url = (
            f"https://space.bilibili.com/{mid}" if mid else ""
        )
        return {
            "title": uname,
            "author": {"name": uname, "mid": mid},
            "item_id": str(mid) if mid is not None else "",
            "share_url": share_url,
            "platform": "bilibili",
            "channel": "user",
            "result_type": "user",
            "fans": raw.get("fans") or 0,
            "level": raw.get("level") or 0,
            "usign": usign,
        }

    # ---- hotword (top 10) ----------------------------------------

    async def get_hotword(
        self,
        *,
        max_count: int = 50,
        error_sink: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """Top trending search keywords on B 站.

        Uses ``https://s.search.bilibili.com/main/hotword`` — public,
        no auth, returns up to ~100. Default ``max_count`` is 50 so the
        GUI's table view doesn't go to 100 rows.
        """
        client = await self._ensure_client()
        try:
            resp = await client.get(HOTWORD_URL)
        except httpx.HTTPError as exc:
            logger.warning("bilibili hotword failed: %s", exc)
            if error_sink is not None:
                error_sink["error"] = str(exc)
            return []
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if payload.get("code") not in (0, None):
            if error_sink is not None:
                error_sink["error"] = (
                    f"code={payload.get('code')} {payload.get('message') or ''}"
                )
            return []

        rows = payload.get("list") or []
        out: list[dict[str, Any]] = []
        for i, raw in enumerate(rows[: max_count], start=1):
            word = raw.get("keyword") or raw.get("show_name") or ""
            show_name = raw.get("show_name") or word
            word_type = raw.get("word_type")
            icon = raw.get("icon") or ""
            out.append({
                "word": word,
                "show_name": show_name,
                "position": i,
                "word_type": word_type,
                "icon": icon,
                "share_url": (
                    f"https://search.bilibili.com/all?keyword={quote(word)}"
                ),
                "platform": "bilibili",
                "channel": "hotword",
                "result_type": "hot",
                "hot_value": 0,
            })
        return out

    # ---- popular videos ------------------------------------------

    async def get_popular(
        self,
        *,
        max_count: int = 20,
        error_sink: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """``https://api.bilibili.com/x/web-interface/popular?ps=N``.

        1 page worth of ``popular`` videos. Anonymous works, but with
        cookies attached the list is personalised. Default 20 = B 站's
        page size.
        """
        page_size = max(1, min(int(max_count), 50))
        params = {"pn": 1, "ps": page_size}
        url = f"{POPULAR_URL}?{urlencode(params)}"
        client = await self._ensure_client()
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("bilibili popular failed: %s", exc)
            if error_sink is not None:
                error_sink["error"] = str(exc)
            return []
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if payload.get("code") not in (0, None):
            if error_sink is not None:
                error_sink["error"] = (
                    f"code={payload.get('code')} {payload.get('message') or ''}"
                )
            return []
        rows = (payload.get("data") or {}).get("list") or []
        return [self._adapt_popular_hit(raw, i + 1) for i, raw in enumerate(rows[:page_size])]

    @staticmethod
    def _adapt_popular_hit(raw: dict, position: int) -> dict[str, Any]:
        bvid = raw.get("bvid") or ""
        title = re.sub(r"</?em[^>]*>", "", raw.get("title") or "")
        author = raw.get("owner") or {}
        return {
            "title": title,
            "author": {"name": author.get("name", ""), "mid": author.get("mid")},
            "item_id": bvid or str(raw.get("aid") or ""),
            "share_url": (
                f"https://www.bilibili.com/video/{bvid}" if bvid else ""
            ),
            "platform": "bilibili",
            "channel": "popular",
            "result_type": "video",
            "position": position,
            "play": raw.get("stat", {}).get("view", 0) or 0,
            "danmaku": raw.get("stat", {}).get("danmaku", 0) or 0,
            "like": raw.get("stat", {}).get("like", 0) or 0,
            "duration": raw.get("duration") or 0,
            "pubdate": raw.get("pubdate") or 0,
        }

    # ---- ranking v2 ----------------------------------------------

    async def get_ranking(
        self,
        *,
        rid: int = 0,            # 0 = 全站；其他 rid 见 B 站分区字典
        max_count: int = 50,
        error_sink: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """``/x/web-interface/ranking/v2`` — 按 rid 取的分区榜单。

        默认全站榜 ``rid=0``。返回字段比 ``popular`` 多几分、收藏、弹幕。
        """
        page_size = max(1, min(int(max_count), 100))
        params = {"rid": rid, "type": "all", "pn": 1, "ps": page_size}
        url = f"{RANKING_URL}?{urlencode(params)}"
        client = await self._ensure_client()
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("bilibili ranking failed: %s", exc)
            if error_sink is not None:
                error_sink["error"] = str(exc)
            return []
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if payload.get("code") not in (0, None):
            if error_sink is not None:
                error_sink["error"] = (
                    f"code={payload.get('code')} {payload.get('message') or ''}"
                )
            return []
        rows = (payload.get("data") or {}).get("list") or []
        return [self._adapt_ranking_hit(raw, i + 1) for i, raw in enumerate(rows[:page_size])]

    @staticmethod
    def _adapt_ranking_hit(raw: dict, position: int) -> dict[str, Any]:
        bvid = raw.get("bvid") or ""
        title = re.sub(r"</?em[^>]*>", "", raw.get("title") or "")
        author = raw.get("owner") or {}
        score = raw.get("score") or 0
        stat = raw.get("stat") or {}
        return {
            "title": title,
            "author": {"name": author.get("name", ""), "mid": author.get("mid")},
            "item_id": bvid or str(raw.get("aid") or ""),
            "share_url": (
                f"https://www.bilibili.com/video/{bvid}" if bvid else ""
            ),
            "platform": "bilibili",
            "channel": "ranking",
            "result_type": "video",
            "position": position,
            "score": score,
            "hot_value": score,
            "play": stat.get("view", 0) or 0,
            "danmaku": stat.get("danmaku", 0) or 0,
            "like": stat.get("like", 0) or 0,
            "duration": raw.get("duration") or 0,
            "pubdate": raw.get("pubdate") or 0,
        }