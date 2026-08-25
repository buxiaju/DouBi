"""YouTube platform adapter.

YouTube 是「最低成本扩张」场景：

* yt-dlp 原生支持所有 YouTube URL 形态（watch / shorts / embed / youtu.be），
  不需要任何平台特有签名 / Web API / cookie。
* adapter 因此只需两件事：识别 URL，调一次 ``extract_info(download=False)``
  拿标题与作者（用于在 GUI 解析表里显示；网络失败时降级为只含 URL 的最小
  item，把元数据拉取完全交给下载阶段）。
* 不实现容器展开：channel / playlist 用户用 yt-dlp 自己的 playlist 处理，
  不在 adapter 里抄一份列表展开逻辑——这是抖音 / B 站 adapter 的复杂来源，
  YouTube 不抄那条路径。

**架构验真意义**：这一节的实现是「adapter 极简化」的样本——之前 B 站 / 抖
音各自的容器策略、签名、cookie 注入都堆在 adapter 里，导致 adapter 文件
动辄上千行；YouTube adapter 总量不到 200 行，能跑通即证明架构允许「按平台
复杂度调整 adapter 厚度」。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ...core.models import (
    Author,
    DownloadOptions,
    MediaItem,
    MediaType,
    Platform,
)
from ..base import PlatformAdapter
from .url import (
    YouTubeURLType,
    classify_youtube_url,
    to_watch_url,
)

logger = logging.getLogger("doubi.platforms.youtube")


class YouTubeAdapter(PlatformAdapter):
    name = "youtube"
    platform = Platform.YOUTUBE
    display_name = "YouTube"
    url_patterns = [
        # 一个正则覆盖所有 youtube.com 形态；短链 youtu.be 单独配。
        __import__("re").compile(r"https?://(?:www\.|m\.)?youtube\.com/"),
        __import__("re").compile(r"https?://youtu\.be/"),
    ]

    # ---- introspection ----------------------------------------------

    def supported_media_types(self) -> list[str]:
        # 不列 LIVE_REPLAY：B 站的「直播回放」在 YouTube 不存在；YouTube
        # 的 live 流被归类到 VIDEO（含 live metadata），由 yt-dlp 区分。
        return [
            MediaType.VIDEO.value,
            MediaType.AUDIO.value,   # Music 类别
            MediaType.LIVE.value,
        ]

    # ---- parse -------------------------------------------------------

    async def parse(self, url: str) -> Optional[MediaItem]:
        """Return a single-video ``MediaItem`` for any YouTube video URL.

        Non-video URLs (channel / playlist) return ``None`` — the user
        message says so explicitly, and ``pipeline.parse`` won't keep
        guessing. Downstream callers (CLI / GUI) see ``None`` and show
        a "not a single video" toast.
        """
        classified = classify_youtube_url(url)
        if classified.type is YouTubeURLType.UNKNOWN:
            logger.error("Unrecognized YouTube URL: %s", url)
            return None
        if classified.type in (
            YouTubeURLType.CHANNEL,
            YouTubeURLType.PLAYLIST,
        ):
            logger.error(
                "%s 容器不支持（YouTube 容器请直接交给 yt-dlp --yes-playlist）",
                classified.type.value,
            )
            return None

        watch_url = to_watch_url(classified)
        item = MediaItem(
            platform=self.platform,
            item_id=classified.item_id,
            title="",                 # filled below if network reachable
            author=Author(),
            media_type=MediaType.VIDEO,
            source_url=watch_url,
            extra={
                "url_type": classified.type.value,
                # 标记 original：原始用户输入形态。下载阶段 yt-dlp 自己会
                # 归一化，但保留原始值有助于排查「为什么这条 watch?v=ID
                # 没拿到 1080p」这类问题（maybe 是 /shorts/ 形态自带限制）。
                "raw_url": url,
            },
        )
        try:
            title, channel, duration = await self._extract_meta(watch_url)
        except Exception as exc:  # noqa: BLE001 - defensive net
            # ``_extract_meta`` 自身已有 ``except Exception``，但任何「未来
            # 加新代码时漏掉一层」的回归都不该让 ``parse`` 抛异常穿过
            # 到 pipeline——pipeline 会吞掉它返回 None，然后用户看到
            #「解析失败」弹窗，可 URL 是合法的、网络只是临时不通。降级
            # 到 placeholder 是更诚实的反应。
            logger.warning("YouTube extract_meta raised for %s: %s", watch_url, exc)
            title, channel, duration = "", "", None
        if title:
            item.title = title
            item.author = Author(name=channel or "")
            item.duration = duration
        else:
            # 网络失败 / 限流 / SSL 重试用完 —— 不阻塞，GUI 仍能入队；engine
            # 在下载阶段会用同一 URL 调 yt-dlp，再失败再报。占位标题让
            # 用户至少看得出是哪一类失败。
            item.title = f"YouTube {classified.item_id}"
            item.extra["meta_extract_failed"] = True
        return item

    async def _extract_meta(self, watch_url: str) -> tuple[str, str, Optional[float]]:
        """Run ``yt_dlp.YoutubeDL.extract_info(download=False)`` in a thread.

        Returns ``(title, channel, duration_seconds)``. Any failure
        (SSL / network / DNS / rate limit) returns ``("", "", None)`` and
        the caller falls back to a placeholder item.

        Threaded because ``YoutubeDL.extract_info`` is synchronous and
        blocking; using a worker thread here is consistent with how the
        engine itself wraps the actual download.
        """
        def _do_extract() -> dict:
            import yt_dlp
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                # 仿浏览器 UA——YouTube 对裸 Python UA 越来越严格。
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(watch_url, download=False) or {}

        try:
            info = await asyncio.to_thread(_do_extract)
        except Exception as exc:  # noqa: BLE001
            # 网 / SSL / 解析失败一概吞掉——engine 会重试。
            logger.warning("YouTube extract_info failed for %s: %s", watch_url, exc)
            return "", "", None

        title = str(info.get("title") or "")
        # yt-dlp 不同 extractor 用的字段名不同（channel / uploader / creator）。
        # ``channel`` 是 YouTube 专用字段；``uploader`` 是兜底。
        channel = str(info.get("channel") or info.get("uploader") or "")
        duration = info.get("duration")
        try:
            duration = float(duration) if duration else None
        except (TypeError, ValueError):
            duration = None
        return title, channel, duration

    # ---- post-download ----------------------------------------------

    async def post_download(self, item: MediaItem, options: DownloadOptions) -> None:
        """YouTube: no platform-specific post-processing needed.

        B 站的 danmaku / 字幕需要 cid + 鉴权 API，YouTube 的字幕 yt-dlp 自
        己拉（``writesubtitles`` 选项），NFO 模板与 B 站 / 抖音通用。所以
        默认实现 ``return`` 就是正确行为——保留这个空方法只为文档可读性：
        让读 adapter 的人知道「这里我**特意**没做事」而不是「忘了写」。
        """
        return None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<YouTubeAdapter platform={self.platform.value}>"
