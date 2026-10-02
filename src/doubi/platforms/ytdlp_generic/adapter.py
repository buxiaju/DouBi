"""YtDlpGenericAdapter — 把任意 URL 丢给 yt-dlp 自身 extractor。

兜底链（M6.17+）：

1. 具体平台（douyin / bilibili / youtube，priority=0）—— 拿自家 API 增强元数据
2. **本适配器**（priority=-1）—— yt-dlp 内置 1800+ extractor，覆盖 Twitter /
   Instagram / Vimeo / Reddit / Pixiv / AcFun / 网易云 / QQ 音乐 / 喜马拉雅 /
   央视频 / 虎牙 / 斗鱼 / 西瓜视频 / 优酷 / AcFun 等国内站点，以及大多数国外
   媒体站。解析失败时返回 None，由 generic (priority=-2) Playwright 嗅探接管
3. generic（priority=-2）—— 应对 yt-dlp 不识别的国产 HLS / 自建 CMS

为什么 priority=-1 而不是 0：保持具体平台（priority=0）优先——它们拿到的
元数据通常更丰富（B 站弹幕 / 抖音合集列表等 yt-dlp 没有的信息）。只有具体
平台不匹配时才进 ytdlp_generic。

为什么不用 priority=0 + match_url 永真：那样会**优先**于具体平台匹配，
导致 B 站/抖音/YouTube 的 URL 也走通用路径，丢失平台特化能力。

``parse()`` 走 ``yt_dlp.YoutubeDL.extract_info(url, download=False)`` 默认
行为——yt-dlp 自己决定要不要展开 playlist（``process=True``）。失败时
**不抛异常**，返回 None 让 pipeline 当作「解析失败」处理（不会自动 chain
到 generic 嗅探；GUI「重试/换解析方式」按钮可手动触发）。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import yt_dlp

from ...core.config import AppConfig, load_config
from ...core.models import (
    Author,
    MediaItem,
    MediaType,
    Platform,
)
from ...engines.yt_dlp import DEFAULT_USER_AGENT
from ..base import PlatformAdapter
from .strategies import (
    entries_to_children,
    info_to_media_item,
    is_playlist_info,
)

logger = logging.getLogger("doubi.platforms.ytdlp_generic")

#: 任意 http(s) URL 都匹配；具体平台（douyin / bilibili / youtube）先匹配，
#: 因为它们的 priority=0 > 本适配器 priority=-1。
_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


class YtDlpGenericAdapter(PlatformAdapter):
    """把任意 URL 丢给 yt-dlp 自身 extractor 的兜底适配器。"""

    name = "ytdlp"
    platform = Platform.YT_DLP_GENERIC
    display_name = "yt-dlp 通用 (1800+ 站点)"
    url_patterns = [_URL_PATTERN]
    #: priority=-1 让具体平台 (priority=0) 先匹配；generic (priority=-2) 后匹配。
    priority = -1

    #: 类级别 config 缓存，遵循 GenericAdapter 的 set_config 契约。
    #: App 启动时 4 个入口（CLI / GUI / REST / MCP）各自负责 ``set_config``。
    #: 不调也能跑——parse() 时 lazy load_config() 走默认 YAML。
    _config: Optional[AppConfig] = None

    @classmethod
    def set_config(cls, cfg: AppConfig) -> None:
        cls._config = cfg

    # ---- match / supported types -------------------------------------

    def match_url(self, url: str) -> bool:
        if not url:
            return False
        return bool(_URL_PATTERN.match(url))

    def supported_media_types(self) -> list[str]:
        # yt-dlp 支持 video / live / audio / image 等；保守地只列 VIDEO 和 LIVE
        # 是因为 MediaItem.media_type 在我们内部只细到这层。
        return [MediaType.VIDEO.value, MediaType.LIVE.value]

    # ---- parse -------------------------------------------------------

    async def parse(self, url: str) -> Optional[MediaItem]:
        """单条 URL → 单条 MediaItem（playlist URL → 容器 MediaItem）。

        ``extract_info`` 在 worker thread 里跑（阻塞 IO）；失败时返回
        None，不让 pipeline 崩。
        """
        info = await self._extract_info(url)
        if info is None:
            return None

        # playlist / multi_video / url 型 → 容器
        if is_playlist_info(info):
            children = entries_to_children(
                info.get("entries") or [],
                fallback_url=url,
            )
            container_id = str(info.get("id") or url)
            return MediaItem(
                platform=self.platform,
                item_id=container_id,
                title=str(info.get("title") or ""),
                author=Author(
                    name=str(info.get("uploader") or info.get("channel") or ""),
                ),
                cover_url=None,
                duration=None,
                publish_time=None,
                media_type=MediaType.COLLECTION,
                source_url=url,
                children=children,
                extra={
                    "extractor": info.get("extractor"),
                    "extractor_key": info.get("extractor_key"),
                    "entry_count": len(children),
                },
            )

        # 单条 video / image_album / live
        return info_to_media_item(info, source_url=url, platform=self.platform)

    # ---- internals ---------------------------------------------------

    async def _extract_info(self, url: str) -> Optional[dict]:
        """线程池里跑 ``yt_dlp.YoutubeDL.extract_info``。

        捕获 yt-dlp 所有已知异常（``DownloadError``、``ExtractorError``、
        ``YoutubeDL`` 解构异常）+ 兜底 ``Exception``——永远不抛给 caller。
        """
        opts = self._build_opts()

        def _do_extract() -> Optional[dict]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                # 默认 process=True：yt-dlp 自己决定要不要展开 playlist
                return ydl.extract_info(url, download=False)

        try:
            return await _do_extract_thread(_do_extract)
        except Exception as exc:  # noqa: BLE001 - 兜底：所有 yt-dlp / 网络异常
            # 主失败类型 yt_dlp.utils.DownloadError 已包含完整原因（地区限制 /
            # 私有视频 / 格式不可用 / 登录失效等）；其他异常也一并吞掉，
            # 让 generic 嗅探有机会接管（如果上层触发 chain fallback）。
            logger.info(
                "ytdlp_generic 解析失败 for %s: %s: %s",
                url, type(exc).__name__, exc,
            )
            return None

    def _build_opts(self) -> dict:
        """构造 yt-dlp 调用 opts（解析阶段用，不下载）。

        复用 ``engines/yt_dlp.py`` 的 ``DEFAULT_USER_AGENT`` —— 否则
        YouTube / Instagram 等会因 UA 不一致返回 403（解析能过、下载挂
        或反过来）。cookie / proxy 从 set_config 注入的 AppConfig 读，
        与 DownloadOptions 同一来源。
        """
        cfg = self._config or load_config(None)
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "ignoreerrors": False,
            "noplaylist": False,    # 让 yt-dlp 自己决定 playlist 展开
            "user_agent": DEFAULT_USER_AGENT,
        }
        if cfg.cookies_file:
            opts["cookiefile"] = str(cfg.cookies_file)
        if cfg.proxy:
            opts["proxy"] = cfg.proxy
        if cfg.rate_limit:
            opts["ratelimit"] = cfg.rate_limit
        return opts

    # ---- post_download -----------------------------------------------

    async def post_download(self, item: MediaItem, options) -> None:  # type: ignore[override]
        """无平台特化后处理。yt-dlp 引擎已经写了 info.json / 缩略图（用户开了的话）。

        字幕和 NFO 由 engine 全权处理；本适配器没有额外的 sidecar 需求。
        """
        return None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<YtDlpGenericAdapter platform={self.platform.value} "
            f"priority={self.priority}>"
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _do_extract_thread(fn):  # pragma: no cover - trivial wrapper
    """``asyncio.to_thread`` 的单点入口——便于测试 monkeypatch 替换。"""
    import asyncio
    return await asyncio.to_thread(fn)
