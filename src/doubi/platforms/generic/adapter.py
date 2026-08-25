"""Generic platform adapter — 任意 URL 的兜底嗅探。

注册到 :class:`doubi.core.registry.PlatformRegistry` 时 ``priority=-1``，
让 ``registry.detect()`` 在所有 normal-priority 适配器（douyin / bilibili
/ youtube）都不匹配后才走 generic。``match_url()`` 对任何 ``http(s)://``
URL 返回 True，触发 Sniffer 跑 headless Chromium + catch_lite.js 嗅探。

返回形态：COLLECTION 容器，N 个 child（每个 sniffed URL 一个）。复用
抖音合集 / B 站合集的现有 pipeline.expand() 路径——UI 表格已支持层级展开。

详见 docs/superpowers/specs/2026-08-25-generic-sniffer-design.md。
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

from ...core.config import AppConfig, load_config
from ...core.models import (
    Author,
    MediaItem,
    MediaType,
    Platform,
)
from ...core.sniffer import (
    Sniffer,
    SniffResult,
    is_dash_url,
    is_direct_video_url,
    is_hls_mime,
    is_hls_url,
    sniff_options_from_config,
)
from ..base import PlatformAdapter

logger = logging.getLogger("doubi.platforms.generic")

# 任意 http(s) URL 都匹配；空串 / about:/javascript:/file:// 不匹配。
# priority=-1 保证具体平台先匹配，generic 永远是最后兜底。
_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


class GenericAdapter(PlatformAdapter):
    """任意 URL 的兜底嗅探适配器。"""

    name = "generic"
    platform = Platform.GENERIC
    display_name = "通用嗅探"
    url_patterns = [_URL_PATTERN]
    priority = -1   # 兜底；normal 适配器优先匹配

    # 类级别 config 缓存：app 启动时调用 ``set_config(cfg)`` 注入；不调
    # 用就 ``parse()`` 时 lazy 调 ``load_config()`` 读默认 YAML。后者会
    # 多一次磁盘读，但 parse() 不是热路径，可接受。
    _config: Optional[AppConfig] = None

    @classmethod
    def set_config(cls, cfg: AppConfig) -> None:
        """App 启动时调用，注入当前 AppConfig 实例。

        避免 ``parse()`` 每次都 ``load_config()`` 读 YAML。如果不调用，
        ``parse()`` 会 lazy 加载，功能正确但每次多一次磁盘读。
        """
        cls._config = cfg

    def match_url(self, url: str) -> bool:
        """永真（对任意 http(s) URL）。priority=-1 保证其他适配器先匹配。"""
        if not url:
            return False
        return bool(_URL_PATTERN.match(url))

    def supported_media_types(self) -> list[str]:
        return [MediaType.VIDEO.value]

    # ---- parse ------------------------------------------------------

    async def parse(self, url: str) -> Optional[MediaItem]:
        """对任意 URL 跑嗅探，返回 COLLECTION 容器（N 个 child）。

        失败情况（Playwright 缺失 / 超时 / 0 个 URL）返回**单个错误
        MediaItem**，不抛异常——pipeline 不该因为嗅探失败而崩，UI 上
        用户能看到明确报错。
        """
        cfg = self._config or load_config()
        options = sniff_options_from_config(cfg)
        sniffer = Sniffer(options)
        result: SniffResult = await sniffer.sniff(url)

        page_url = result.page_url or url
        page_title = result.page_title or _domain_from_url(url)

        if result.error or not result.items:
            err_msg = result.error or "未嗅探到任何视频 URL"
            logger.warning("generic sniff 失败 for %s: %s", url, err_msg)
            return _build_error_item(url, err_msg, page_title)

        # ---- 构造 COLLECTION 容器 + N 个 child ----
        children: list[MediaItem] = []
        seen_targets: set[str] = set()  # 已经见过的「真实视频目标 URL」

        def _video_target(url: str) -> str:
            """计算 URL 的「真实目标」——用于代理 m3u8 去重。

            某些站点会把相同的 m3u8 URL 通过 query 参数包装成代理 URL
            （如 `https://proxy.example/?url=URL.m3u8`），我们把嵌入的
            m3u8/mp4 目标当成「真实目标」。
            """
            from urllib.parse import parse_qs, unquote, urlparse
            try:
                parsed = urlparse(url)
            except Exception:
                return url

            # 1. 先扫 query 字符串：是否有内嵌的视频 URL
            #   （注意：代理 URL 的 query 里有 .m3u8，而它整个 URL 也匹配
            #    is_hls_url，所以这一步必须放在「直接匹配」之前）
            if parsed.query:
                q_decoded = unquote(parsed.query)
                if ".m3u8" in q_decoded.lower() or ".mp4" in q_decoded.lower():
                    import re as _re
                    m = _re.search(
                        r"https?://[^\"'&\s]+?\.(?:m3u8|m3u|mp4|webm|flv|mkv|ts)",
                        q_decoded,
                        _re.IGNORECASE,
                    )
                    if m:
                        return m.group(0).split("?", 1)[0]
                # parse_qs 再补一次（处理多参数 / 非标准 key）
                try:
                    qs = parse_qs(parsed.query)
                    for key in ("url", "src", "video", "play", "id", "vid"):
                        if key in qs:
                            for val in qs[key]:
                                decoded = unquote(val)
                                if is_hls_url(decoded) or is_direct_video_url(decoded):
                                    return decoded.split("?", 1)[0]
                except Exception:
                    pass

            # 2. 直接是视频 URL，目标就是自己（去 query，因为可能有时间戳）
            if is_hls_url(url) or is_direct_video_url(url):
                return url.split("?", 1)[0]

            return url

        for idx, item in enumerate(result.items):
            target = _video_target(item.url)
            if target in seen_targets:
                logger.info("generic dedup: skip %s (target already seen: %s)",
                            item.url[:80], target[:80])
                continue
            seen_targets.add(target)
            child = _build_child_item(
                sniffed_url=item.url,
                page_url=page_url,
                page_title=page_title,
                index=len(children),  # 用实际追加的下标，保持连续
                mime=item.mime,
                size=item.size,
                initiator=item.initiator,
            )
            children.append(child)

        # 用 page_url 的 hash 作为容器 item_id，保证稳定可重试。
        container_id = hashlib.md5(page_url.encode("utf-8")).hexdigest()[:16]
        container = MediaItem(
            platform=self.platform,
            item_id=container_id,
            title=page_title,
            author=Author(),
            media_type=MediaType.COLLECTION,
            source_url=page_url,
            children=children,
            extra={
                "sniffed_from": url,
                "sniff_item_count": len(children),
                "sniff_page_title": page_title,
            },
        )
        logger.info("generic sniff %s -> %d 个 URL", url, len(children))
        return container

    async def post_download(self, item: MediaItem, options) -> None:  # type: ignore[override]
        """Generic: 无平台特定后处理。

        sniffed 出的多为直链 / m3u8，下载后无需 danmaku / NFO / 字幕的
        平台特化处理——这些侧车文件如果用户开了，由通用模板走。
        """
        return None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<GenericAdapter platform={self.platform.value} priority={self.priority}>"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _domain_from_url(url: str) -> str:
    """从 URL 抽域名作为 fallback 标题。"""
    try:
        # 简单抽取：http(s):// 之后的 host[:port]/...
        m = re.match(r"^https?://([^/]+)/?", url, re.IGNORECASE)
        if m:
            return m.group(1)
    except Exception:  # pragma: no cover
        pass
    return url


def _build_child_item(
    *,
    sniffed_url: str,
    page_url: str,
    page_title: str,
    index: int,
    mime: str = "",
    size: Optional[int] = None,
    initiator: str = "",
) -> MediaItem:
    """构造单个 sniffed URL 的 child MediaItem。

    字段填充规则：

    - ``item_id``: sniffed_url 的 md5 前 16 位，保证 TaskManager 去重
      正确（per memory: 「TaskManager requires unique item_id per child
      video to prevent deduplication of collection entries」）
    - ``title``: ``<page_title> - 视频 <i+1>``，让用户在表格里能区分
    - ``source_url``: sniffed_url 本身（pipeline 会喂给引擎）
    - ``extra.direct_url``: sniffed_url（Aria2 现有契约）
    - ``extra.collection_title`` / ``extra.collection_item_id``: per
      memory 硬约束「Child video items from collections must include
      collection_title and collection_item_id in extra metadata」
    - ``extra.sniffed_from``: 原始用户输入 URL（追溯用）
    - ``extra.mime`` / ``extra.ext`` / ``extra.size``: sniff 元数据
    """
    item_id = hashlib.md5(sniffed_url.encode("utf-8")).hexdigest()[:16]
    ext = _ext_from_url_or_mime(sniffed_url, mime)
    return MediaItem(
        platform=Platform.GENERIC,
        item_id=item_id,
        title=f"{page_title} - 视频 {index + 1}",
        author=Author(),
        media_type=MediaType.VIDEO,
        source_url=sniffed_url,
        extra={
            # ---- Aria2Engine 契约 ----
            "direct_url": sniffed_url,
            # ---- 容器归属（per 硬约束）----
            "collection_title": page_title,
            "collection_item_id": index,
            # ---- sniff 元数据 ----
            "sniffed_from": page_url,
            "sniff_initiator": initiator,
            "sniff_mime": mime,
            "sniff_ext": ext,
            "sniff_size": size,
            # ---- 引擎路由提示（pipeline 用）----
            "is_hls": is_hls_url(sniffed_url) or is_hls_mime(mime),
            "is_dash": is_dash_url(sniffed_url) or mime == "application/dash+xml",
            "is_direct_video": is_direct_video_url(sniffed_url),
        },
    )


def _build_error_item(original_url: str, error_msg: str, page_title: str) -> MediaItem:
    """嗅探失败时构造单个错误 MediaItem。

    pipeline 不会因为这是「错误」item 而崩——它会被当作 VIDEO 类型入队，
    下载阶段引擎会立刻报「URL 不可达」失败，UI 上显示明确状态。比抛
    异常对用户友好。
    """
    item_id = hashlib.md5(original_url.encode("utf-8")).hexdigest()[:16]
    return MediaItem(
        platform=Platform.GENERIC,
        item_id=item_id,
        title=f"[嗅探失败] {page_title} — {error_msg}",
        author=Author(),
        media_type=MediaType.VIDEO,
        source_url=original_url,
        extra={
            "sniff_error": error_msg,
            "sniffed_from": original_url,
        },
    )


def _ext_from_url_or_mime(url: str, mime: str) -> str:
    """从 URL 扩展名或 MIME 推断文件扩展名（无 ``.`` 前缀）。"""
    # 1. URL 扩展名
    m = re.search(r"\.([a-zA-Z0-9]{2,5})(?:$|\?)", url)
    if m:
        return m.group(1).lower()
    # 2. MIME 反查
    mime_to_ext = {
        "video/mp4": "mp4",
        "video/webm": "webm",
        "video/mp2t": "ts",
        "application/vnd.apple.mpegurl": "m3u8",
        "application/dash+xml": "mpd",
        "video/x-flv": "flv",
        "video/x-matroska": "mkv",
    }
    return mime_to_ext.get(mime.lower(), "")
