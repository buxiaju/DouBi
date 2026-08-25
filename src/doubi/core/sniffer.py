"""Generic URL sniffer — Playwright + cat-catch-style JS hooks.

由 :class:`doubi.platforms.generic.adapter.GenericAdapter` 调用，对任意
URL 启动 headless Chromium，注入 ``catch_lite.js`` 在页面脚本之前运行，
监听 XHR / fetch / MediaSource.appendBuffer / video.src setter 抓视频直链。

数据源三路交叉验证：

1. ``catch_lite.js`` 抓的（DOM/MediaSource/XHR/fetch 钩子）—— 主源
2. ``page.on("response")`` 拦截的（content-type 为 video/* + mpegurl + dash+xml）—— 补漏
3. ``page.querySelectorAll("video, source, iframe")`` 静态扫描 —— 兜底

详见 docs/superpowers/specs/2026-08-25-generic-sniffer-design.md。

Playwright 是**必需依赖**：``pyproject.toml`` 里 declared，安装包里 bundled。
如果运行时 ``import playwright`` 失败（CI 没 install，或 PyInstaller
collect 漏了），:class:`Sniffer` 构造时不抛，:meth:`sniff` 时降级返回
空列表——上层（GenericAdapter）会把这个翻译成「单个错误 MediaItem」
而不是异常，UI 上显示明确报错。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Any, Optional

from .config import AppConfig

logger = logging.getLogger("doubi.core.sniffer")

# 试过 import playwright 才能跑嗅探；导入失败时 ``sniff()`` 返回空。
try:
    from playwright.async_api import Response, async_playwright
    from playwright.async_api import TimeoutError as PWTimeout
    _HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover - CI 环境常见
    _HAS_PLAYWRIGHT = False
    async_playwright = None  # type: ignore[assignment]
    Response = None  # type: ignore[assignment]
    PWTimeout = Exception  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 数据类型
# ---------------------------------------------------------------------------


@dataclass
class SniffOptions:
    """从 :class:`AppConfig` 抽出的嗅探参数。

    与 :class:`DownloadOptions` 同设计模式：上层（CLI/GUI/REST）从
    ``AppConfig`` 构造一份，透传到 Sniffer——引擎/服务只认 options，不回
    读 config（per 硬约束 #4）。
    """

    duration_sec: int = 15
    headless: bool = True
    user_agent: str = ""
    auto_play: bool = True
    capture_types: tuple[str, ...] = ()


@dataclass
class SniffedItem:
    """单个嗅到的 URL。"""

    url: str
    type: str               # "xhr" | "fetch" | "media_source" | "video_src" | "iframe" | "network" | "static"
    mime: str = ""
    size: Optional[int] = None
    initiator: str = ""
    ts: float = 0.0         # epoch ms


@dataclass
class SniffResult:
    """Sniffer.sniff() 返回值。"""

    page_url: str = ""
    page_title: str = ""
    items: list[SniffedItem] = field(default_factory=list)
    error: Optional[str] = None   # 非空时表示嗅探失败（Playwright 缺失/超时/0 个 URL）


# ---------------------------------------------------------------------------
# Sniffer
# ---------------------------------------------------------------------------


# URL 扩展名 → 推断 MIME / ext 的启发式表
_EXT_RE = re.compile(r"\.([a-zA-Z0-9]{2,5})(?:$|\?)")
_EXT_TO_MIME: dict[str, str] = {
    "m3u8": "application/vnd.apple.mpegurl",
    "m3u": "application/vnd.apple.mpegurl",
    "mpd": "application/dash+xml",
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "webm": "video/webm",
    "ts": "video/mp2t",
    "flv": "video/x-flv",
    "mkv": "video/x-matroska",
    "avi": "video/x-msvideo",
    "mov": "video/quicktime",
}

# ---- 用户-facing 结果的扩展名白名单 ----
# 解析列表里只显示这些「真正的视频条目」扩展名：
#   1. HLS 播放列表: .m3u8 / .m3u
#   2. 常见容器格式: .mp4 .mkv .flv .webm .mov .avi .m4v
#
# 下面的扩展名一律不出现在结果中：
#   .ts  .aac  .m4s  —— HLS/DASH 分片（由播放列表代表，不应单独列出）
#   .mpd              —— MPD 文件（交给 yt-dlp 更合适，通用结果不展示）
#
# 另外：对于没有识别出扩展名但被 content_verified（JSON 内嵌 / DOM 扫描）
# 的 URL，仍然保留，因为我们从内容层面确认它是视频。
_ALLOWED_VIDEO_EXTS = frozenset({
    "m3u8", "m3u",
    "mp4", "m4v",
    "mkv", "flv", "webm", "mov", "avi",
})

# 没有扩展名时的 MIME 白名单（兜底）——避免靠 is_hls_mime 把
# application/octet-stream 当成 HLS 而其实可能是任何二进制。
_ALLOWED_VIDEO_MIMES = frozenset({
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "application/dash+xml",
    "video/mp4",
    "video/x-matroska",
    "video/webm",
    "video/x-flv",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-m4v",
    "video/mpeg",
    "video/mp2t",  # 虽然 ts 不显示，但 MIME 层保留避免误杀
})

# MIME 过滤：这些类型**不是**视频流，嗅探时应过滤掉
# 只在 _merge_sources 里应用——catch_lite.js 已做了初始过滤
_NON_VIDEO_MIME_PREFIXES = (
    "application/json",
    "text/html",
    "application/javascript",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "image/",
    "font/",
    "text/css",
    "text/plain",
    "text/javascript",
    "application/octet-stream",  # 注意：octet-stream 在 HLS 场景由 is_hls_mime 特判
)

# JSON / JS 文本中可能出现的视频 URL 关键字
_VIDEO_URL_KEYWORDS = (
    ".m3u8", ".m3u", ".mpd", ".mp4", ".webm", ".flv", ".mkv", ".ts", ".mov",
    "m3u8", "mpd",
)

# 匹配 JSON/JS 文本中 URL 的正则（http(s)://... 直到空白/引号/逗号）
_URL_RE = re.compile(r'https?://[^\s"\'\\<>]+', re.IGNORECASE)

# 页面 JS 扫描：从 DOM / script / performance / global 变量中查找视频 URL
# 由 Sniffer.sniff() 在嗅探结束后通过 page.evaluate() 执行
_PAGE_SCAN_JS = """
() => {
    const urls = new Set();
    const videoExts = ['.m3u8','.m3u','.mpd','.mp4','.webm','.flv','.mkv','.ts','.mov'];
    const urlPattern = /https?:\\/\\/[^\\s\"'<>]+/g;

    function addIfVideo(u) {
        if (!u) return;
        const lower = u.toLowerCase();
        for (const ext of videoExts) {
            if (lower.includes(ext)) {
                urls.add(u);
                return;
            }
        }
        if (lower.includes('m3u8') || lower.includes('mpd')) {
            urls.add(u);
        }
    }

    // 1. video 元素的 currentSrc / src
    try {
        document.querySelectorAll('video').forEach(v => {
            if (v.currentSrc) addIfVideo(v.currentSrc);
            if (v.src) addIfVideo(v.src);
            v.querySelectorAll('source').forEach(s => {
                if (s.src) addIfVideo(s.src);
                const srcAttr = s.getAttribute('src');
                if (srcAttr) addIfVideo(srcAttr);
            });
        });
    } catch(e) {}

    // 2. 常用全局状态对象（Next.js / Nuxt / Vue / React）
    const globalKeys = ['__INITIAL_STATE__','__NEXT_DATA__','__NUXT__','__APOLLO_STATE__',
        'config','videoConfig','playerConfig','initData','__config','__videoData'];
    for (const key of globalKeys) {
        try {
            const val = window[key];
            if (!val) continue;
            const str = typeof val === 'string' ? val : JSON.stringify(val);
            if (!str) continue;
            let m;
            while ((m = urlPattern.exec(str)) !== null) {
                addIfVideo(m[0].replace(/[.,;:)]+$/g, ''));
            }
        } catch(e) {}
    }

    // 3. performance resource entries（已加载的资源 URL）
    try {
        if (window.performance && typeof performance.getEntriesByType === 'function') {
            performance.getEntriesByType('resource').forEach(entry => {
                addIfVideo(entry.name);
            });
        }
    } catch(e) {}

    // 4. 内联 <script> 标签中的视频 URL
    try {
        document.querySelectorAll('script').forEach(script => {
            const text = script.textContent || script.innerText || '';
            if (!text) return;
            let m;
            while ((m = urlPattern.exec(text)) !== null) {
                addIfVideo(m[0].replace(/[.,;:)]+$/g, ''));
            }
        });
    } catch(e) {}

    return Array.from(urls);
}
"""


def is_non_video_mime(mime: str) -> bool:
    """判断 MIME 类型是否明确**不是**视频流（应过滤掉）。

    application/octet-stream 在 HLS 场景中可作为 m3u8 的 content-type，
    所以不在这里过滤——调用方应用 is_hls_mime() 单独判断。
    """
    if not mime:
        return False
    lower = mime.lower()
    for prefix in _NON_VIDEO_MIME_PREFIXES:
        if lower.startswith(prefix):
            # octet-stream 单独处理
            if prefix == "application/octet-stream":
                continue
            return True
    return False


def extract_video_urls_from_text(text: str) -> list[str]:
    """从任意文本（JSON / JS / HTML）中提取可能的视频 URL。

    策略：先找所有 http(s):// URL，再过滤出包含视频扩展名或关键字的。
    过滤规则见 ``_VIDEO_URL_KEYWORDS``。
    """
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:)")
        url_lower = url.lower()
        if not any(kw in url_lower for kw in _VIDEO_URL_KEYWORDS):
            continue
        if url not in seen:
            seen.add(url)
            found.append(url)
    return found


def infer_mime_from_url(url: str) -> str:
    """从 URL 扩展名推断 MIME；查不到返回空串。"""
    m = _EXT_RE.search(url)
    if not m:
        return ""
    return _EXT_TO_MIME.get(m.group(1).lower(), "")


class Sniffer:
    """Playwright + catch_lite.js 通用嗅探服务。"""

    def __init__(self, options: SniffOptions) -> None:
        self.options = options
        self._catch_lite_js: Optional[str] = None

    # ---- 资源加载 ----------------------------------------------------

    def _load_catch_lite_js(self) -> str:
        """从 ``doubi.platforms.generic.catch_lite`` 加载 JS 源码。

        第一次调用时读盘并缓存。后续调用直接返回缓存。用
        ``importlib.resources`` 而不是 ``Path(__file__)``，确保 PyInstaller
        打包后路径仍正确（resource access via importlib 是 PyInstaller
        友好的方式）。
        """
        if self._catch_lite_js is None:
            try:
                # files() API 需要 Python 3.9+；DouBi 最低 3.9
                js_path = resources.files("doubi.platforms.generic").joinpath("catch_lite.js")
                self._catch_lite_js = js_path.read_text(encoding="utf-8")
            except (AttributeError, FileNotFoundError, ModuleNotFoundError) as exc:
                # AttributeError: 旧 Python / 没有 importlib.resources.files
                # FileNotFoundError: 打包时漏 --add-data
                # ModuleNotFoundError: 平台包没注册
                logger.error("catch_lite.js 加载失败: %s", exc)
                self._catch_lite_js = ""
        return self._catch_lite_js or ""

    # ---- Playwright 不可用降级 --------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Playwright 是否可用。GenericAdapter 在 parse() 前查这个。"""
        return _HAS_PLAYWRIGHT

    # ---- 主流程 ------------------------------------------------------

    async def sniff(self, url: str) -> SniffResult:
        """对 ``url`` 跑 N 秒嗅探，返回抓到的 URL 列表。

        失败情况都通过 ``SniffResult.error`` 字段返回，**不抛异常**——
        GenericAdapter 把 ``error`` 翻译成单个错误 MediaItem，让用户
        在 GUI 上看到明确报错。
        """
        if not _HAS_PLAYWRIGHT:
            return SniffResult(
                page_url=url,
                error="Playwright 未安装；请 pip install playwright 并 "
                       "运行 playwright install chromium",
            )

        js = self._load_catch_lite_js()
        if not js:
            return SniffResult(page_url=url, error="catch_lite.js 加载失败；安装包可能损坏")

        # Playwright network 拦截拿到的 mime/size 补 catch_lite 漏的
        network_meta: dict[str, dict[str, Any]] = {}
        # 存储 JSON 响应对象，嗅探结束后解析 body 提取内嵌视频 URL
        json_responses: list[Response] = []

        def on_response(resp: Response) -> None:
            try:
                content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if not content_type:
                    return
                # 白名单过滤
                if self.options.capture_types and content_type not in self.options.capture_types:
                    return
                content_length = resp.headers.get("content-length")
                size: Optional[int] = None
                if content_length:
                    try:
                        size = int(content_length)
                    except ValueError:
                        size = None
                network_meta[resp.url] = {
                    "mime": content_type,
                    "size": size,
                    "initiator": url,
                }
                # 存 JSON 响应，后续解析 body 提取内嵌 m3u8 URL
                if content_type == "application/json":
                    json_responses.append(resp)
            except Exception:  # pragma: no cover - 防御
                pass

        initial_items: list[SniffedItem] = []
        data: dict[str, Any] = {}

        try:
            async with async_playwright() as p:  # type: ignore[misc]
                browser = await p.chromium.launch(headless=self.options.headless)
                try:
                    context_kwargs: dict[str, Any] = {}
                    if self.options.user_agent:
                        context_kwargs["user_agent"] = self.options.user_agent
                    context = await browser.new_context(**context_kwargs)
                    await context.add_init_script(js)
                    page = await context.new_page()
                    page.on("response", on_response)

                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    except PWTimeout:  # type: ignore[misc]
                        logger.warning("page.goto 超时: %s，继续嗅探已加载内容", url)
                    except Exception as exc:  # pragma: no cover - 防御
                        return SniffResult(
                            page_url=url,
                            error=f"页面加载失败: {exc}",
                        )

                    # 自动起播触发 m3u8 加载
                    if self.options.auto_play:
                        try:
                            await page.evaluate(
                                "() => document.querySelectorAll('video').forEach(v => v.play().catch(()=>{}))"
                            )
                        except Exception:  # pragma: no cover - 防御
                            pass

                    await asyncio.sleep(self.options.duration_sec)

                    data = await page.evaluate(
                        "() => (window.__catchLite || {media: [], ready: false, pageUrl: location.href, pageTitle: document.title})"
                    )

                    # ---- 后处理 1：解析 JSON 响应体，提取内嵌视频 URL ----
                    json_extracted: dict[str, dict[str, Any]] = {}
                    for resp in json_responses:
                        try:
                            body = await resp.text()
                            video_urls = extract_video_urls_from_text(body)
                            for vurl in video_urls:
                                if vurl not in json_extracted:
                                    json_extracted[vurl] = {
                                        "mime": infer_mime_from_url(vurl),
                                        "size": None,
                                        "initiator": resp.url,
                                    }
                        except Exception:  # pragma: no cover
                            pass

                    # ---- 后处理 2：JS 扫描页面 DOM/脚本中的视频 URL ----
                    page_scan_urls: dict[str, dict[str, Any]] = {}
                    try:
                        scan_result = await page.evaluate(_PAGE_SCAN_JS)
                        if scan_result:
                            for vurl in scan_result:
                                if isinstance(vurl, str) and vurl.startswith("http"):
                                    page_scan_urls[vurl] = {
                                        "mime": infer_mime_from_url(vurl),
                                        "size": None,
                                        "initiator": data.get("pageUrl", url),
                                    }
                    except Exception:  # pragma: no cover
                        pass

                    # ---- 后处理 3：SPA 回退——初始嗅探 0 项时尝试二次嗅探 ----
                    initial_items = self._merge_sources(
                        catch_media=data.get("media", []),
                        network_meta=network_meta,
                        static_scan=self._static_scan_from_init(data),
                        json_extracted=json_extracted,
                        page_scan=page_scan_urls,
                    )

                    if not initial_items:
                        logger.info("初始嗅探 0 项，尝试 SPA 回退（等待 networkidle + 点击 + 重嗅探）")
                        retry_items = await self._spa_retry(
                            page, network_meta, json_responses, data
                        )
                        if retry_items:
                            initial_items = retry_items

                finally:
                    await browser.close()
        except Exception as exc:  # pragma: no cover - 防御
            return SniffResult(page_url=url, error=f"Playwright 运行失败: {exc}")

        # ---- 合并五路数据源（已在嗅探内部完成，这里取回结果）----
        items = initial_items  # type: ignore[name-defined]

        return SniffResult(
            page_url=data.get("pageUrl") or url,
            page_title=data.get("pageTitle") or "",
            items=items,
            error=None if items else "嗅探到 0 个视频 URL",
        )

    # ---- 合并 + 去重 + 排序 ------------------------------------------

    @staticmethod
    def _static_scan_from_init(data: dict[str, Any]) -> list[dict[str, Any]]:
        """catch_lite.js 已经把静态扫描结果并到 media[] 里了，这里只提取
        出 type 为 'iframe' 或 'video_src' 的项——它们就是静态扫描来源。"""
        return [m for m in data.get("media", []) if m.get("type") in ("iframe", "video_src")]

    def _merge_sources(
        self,
        catch_media: list[dict[str, Any]],
        network_meta: dict[str, dict[str, Any]],
        static_scan: list[dict[str, Any]],
        json_extracted: Optional[dict[str, dict[str, Any]]] = None,
        page_scan: Optional[dict[str, dict[str, Any]]] = None,
    ) -> list[SniffedItem]:
        """五路数据源合并去重。

        数据源：
        1. catch_lite.js 抓的（XHR/fetch/MSE/video.src/iframe）—— 主源
        2. network response 拦截（补漏 + 补 mime/size）
        3. 静态扫描（video/source/iframe DOM）—— 已并入 1
        4. JSON 响应体解析（API 返回的 JSON 内嵌 m3u8 URL）
        5. JS 页面扫描（performance/script tag/global 变量）

        过滤规则：
        - 非视频 MIME（application/json / text/html 等）的 URL 在合并末尾被过滤
        - 但如果 URL 同时出现在 json_extracted 或 page_scan 中（即已从内容
          中验证为视频 URL），则不被过滤
        """
        seen: dict[str, SniffedItem] = {}
        # 记录哪些 URL 已被「内容解析」验证为视频（来自 json_extracted / page_scan）
        content_verified: set[str] = set()

        def _is_http_url(u: str) -> bool:
            return u.lower().startswith(("http://", "https://"))

        def _add(url: str, item: SniffedItem) -> None:
            if url in seen:
                return
            seen[url] = item

        # 1. catch_lite 抓的（主源）
        for entry in catch_media:
            url = entry.get("url", "")
            if not url or not _is_http_url(url):
                continue
            if url in seen:
                continue
            mime = entry.get("mime", "") or infer_mime_from_url(url)
            _add(url, SniffedItem(
                url=url,
                type=entry.get("type", "xhr"),
                mime=mime,
                size=entry.get("size"),
                initiator=entry.get("initiator", ""),
                ts=entry.get("ts", 0.0),
            ))

        # 2. network response 拦截（补漏 + 补 mime/size）
        for url, meta in network_meta.items():
            if not url or not _is_http_url(url):
                continue
            if url in seen:
                item = seen[url]
                if not item.mime and meta.get("mime"):
                    item.mime = meta["mime"]
                if item.size is None and meta.get("size") is not None:
                    item.size = meta["size"]
                continue
            _add(url, SniffedItem(
                url=url,
                type="network",
                mime=meta.get("mime", ""),
                size=meta.get("size"),
                initiator=meta.get("initiator", ""),
                ts=0.0,
            ))

        # 3. 静态扫描（已并入 catch_media，跳过）
        _ = static_scan

        # 4. JSON 响应体解析（API 返回的 JSON 内嵌视频 URL）
        if json_extracted:
            for url, meta in json_extracted.items():
                if not url or not _is_http_url(url):
                    continue
                content_verified.add(url)
                _add(url, SniffedItem(
                    url=url,
                    type="json_extract",
                    mime=meta.get("mime", ""),
                    size=meta.get("size"),
                    initiator=meta.get("initiator", ""),
                    ts=0.0,
                ))

        # 5. JS 页面扫描（performance/script tag/global 变量）
        if page_scan:
            for url, meta in page_scan.items():
                if not url or not _is_http_url(url):
                    continue
                content_verified.add(url)
                _add(url, SniffedItem(
                    url=url,
                    type="page_scan",
                    mime=meta.get("mime", ""),
                    size=meta.get("size"),
                    initiator=meta.get("initiator", ""),
                    ts=0.0,
                ))

        # ---- MIME 过滤：移除明确非视频 MIME 的 URL ----
        # 但保留 content_verified 中的 URL（已从内容解析验证为视频）
        filtered = [
            item for item in seen.values()
            if not is_non_video_mime(item.mime) or item.url in content_verified
        ]

        # ---- 扩展名白名单：只保留「用户可见的视频条目」后缀 ----
        #
        # 规则：
        # 1. 命中 _ALLOWED_VIDEO_EXTS → 保留
        # 2. URL 无扩展名但 MIME 命中 _ALLOWED_VIDEO_MIMES → 保留
        # 3. URL 被 content_verified（JSON/DOM 中提取到的内嵌视频）→ 保留
        # 4. 其它全部丢弃（.ts / .aac / .m4s / .mpd / 可疑无后缀 URL 等）
        def _has_allowed_ext(url: str) -> bool:
            path_only = url.lower().split("?", 1)[0]
            dot_idx = path_only.rfind(".")
            if dot_idx == -1:
                return False
            return path_only[dot_idx + 1 :] in _ALLOWED_VIDEO_EXTS

        allowed: list[SniffedItem] = []
        for item in filtered:
            if item.url in content_verified:
                allowed.append(item)
                continue
            if _has_allowed_ext(item.url):
                allowed.append(item)
                continue
            # 没有扩展名时，看 MIME 是否命中视频类
            path_only = item.url.lower().split("?", 1)[0]
            if "." not in path_only.rsplit("/", 1)[-1] and item.mime:
                if item.mime.lower().rstrip("; charset=utf-8") in _ALLOWED_VIDEO_MIMES:
                    allowed.append(item)
                    continue
                # 额外宽松：MIME 前缀是 video/ 或 vnd.apple.mpegurl 之类的
                low_mime = item.mime.lower()
                if low_mime.startswith("video/") or "mpegurl" in low_mime:
                    allowed.append(item)
                    continue
        filtered = allowed

        # ---- 移除 m3u8 播放列表对应的独立分片条目 ----
        # 如果捕获了 index.m3u8 / playlist.m3u8 之类的播放列表，那么
        # 同一个目录下的 .ts / .aac / .m4s 必定是其子分片，不能显示为独
        # 立视频（否则用户会看到 14 条只代表一个视频）。
        #
        # 注意：只移除共享**目录前缀** + **分片扩展名**的条目；.mp4 永
        # 远不被当作 m3u8 分片移除，因为它可能是一个独立视频。
        hls_dirs: set[str] = set()
        for item in filtered:
            if is_hls_url(item.url):
                hls_dirs.add(item.url.rsplit("/", 1)[0].lower() + "/")
        if hls_dirs:
            _SEG_EXTS = {".ts", ".aac", ".m4s"}  # 仅 HLS 分片扩展名
            kept: list[SniffedItem] = []
            for item in filtered:
                url = item.url
                lower = url.lower()
                # Strip query string to get path-only extension
                path_only = lower.split("?", 1)[0]
                dir_part = path_only.rsplit("/", 1)[0] + "/"
                dot_idx = path_only.rfind(".")
                ext = path_only[dot_idx:] if dot_idx != -1 else ""
                if dir_part in hls_dirs and ext in _SEG_EXTS:
                    continue
                kept.append(item)
            filtered = kept

        return sorted(filtered, key=lambda i: i.ts)

    async def _spa_retry(
        self,
        page: Any,
        network_meta: dict[str, dict[str, Any]],
        json_responses: list[Response],
        data: dict[str, Any],
    ) -> list[SniffedItem]:
        """SPA 回退嗅探：当初始嗅探 0 项时，尝试更激进的策略。

        策略：
        1. 等待 networkidle（最多 10s）
        2. 点击页面上的视频/播放相关元素
        3. 滚动页面触发懒加载
        4. 等待更多内容加载
        5. 重新嗅探 catch_lite + JSON 解析 + JS 扫描
        """
        try:
            # 1. 等待页面稳定
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            # 2. 点击常见视频/播放元素
            try:
                await page.evaluate("""() => {
                    const selectors = [
                        'video', '.video-player', '.player',
                        '[class*="play"]', '[class*="video"]',
                        'button[class*="play"]', '[data-action="play"]',
                        '.video-item', '.video-card', '.item',
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el) {
                            el.click();
                            break;
                        }
                    }
                }""")
            except Exception:
                pass

            # 3. 滚动页面触发懒加载
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass

            # 4. 等待更多内容加载
            await asyncio.sleep(5)

            # 5. 重新收集 catch_lite 数据
            retry_data = await page.evaluate(
                "() => (window.__catchLite || {media: [], ready: false, pageUrl: location.href, pageTitle: document.title})"
            )

            # 6. 重新解析 JSON 响应体
            retry_json: dict[str, dict[str, Any]] = {}
            for resp in json_responses:
                try:
                    body = await resp.text()
                    video_urls = extract_video_urls_from_text(body)
                    for vurl in video_urls:
                        if vurl not in retry_json:
                            retry_json[vurl] = {
                                "mime": infer_mime_from_url(vurl),
                                "size": None,
                                "initiator": resp.url,
                            }
                except Exception:
                    pass

            # 7. 重新运行 JS 页面扫描
            retry_scan: dict[str, dict[str, Any]] = {}
            try:
                scan_result = await page.evaluate(_PAGE_SCAN_JS)
                if scan_result:
                    for vurl in scan_result:
                        if isinstance(vurl, str) and vurl.startswith("http"):
                            retry_scan[vurl] = {
                                "mime": infer_mime_from_url(vurl),
                                "size": None,
                                "initiator": retry_data.get("pageUrl", ""),
                            }
            except Exception:
                pass

            # 8. 合并所有数据源
            return self._merge_sources(
                catch_media=retry_data.get("media", []),
                network_meta=network_meta,
                static_scan=[],
                json_extracted=retry_json,
                page_scan=retry_scan,
            )
        except Exception:  # pragma: no cover
            return []


# ---------------------------------------------------------------------------
# AppConfig → SniffOptions 搬运
# ---------------------------------------------------------------------------


def sniff_options_from_config(cfg: AppConfig) -> SniffOptions:
    """从 :class:`AppConfig` 构造 :class:`SniffOptions`。

    唯一搬运点（per 硬约束 #4）——GenericAdapter 用这个把用户在 GUI 设置
    页改的 sniff_* 字段透传给 Sniffer。结构性测试守卫在
    ``tests/test_config_forwarding.py`` 里验证字段不会被丢。
    """
    return SniffOptions(
        duration_sec=cfg.sniff_duration_sec,
        headless=cfg.sniff_headless,
        user_agent=cfg.sniff_user_agent,
        auto_play=cfg.sniff_auto_play,
        capture_types=cfg.sniff_capture_types,
    )


# ---------------------------------------------------------------------------
# 工具：从 URL 推断引擎
# ---------------------------------------------------------------------------


def is_hls_url(url: str) -> bool:
    """判断 URL 是否指向 HLS/m3u8 流。

    识别规则：
    1. URL 包含 ``.m3u8`` / ``.m3u`` 扩展名（最可靠）
    2. URL 包含 ``m3u8`` 关键字（query 参数、路径片段等）
    3. URL 包含 ``hls`` 关键字（部分 CDN 用 ``/hls/`` 路径）
    4. URL 包含 ``.key`` 或 ``key=`` 参数（HLS 加密 key）
    """
    lower = url.lower()
    if ".m3u8" in lower or ".m3u" in lower:
        return True
    # 很多 CDN 用 /m3u8/ 或 ?type=m3u8 等方式传递
    if "m3u8" in lower:
        return True
    # HLS 加密 key 请求
    if ".key" in lower or "key=" in lower:
        return True
    return False


def is_hls_mime(mime: str) -> bool:
    """判断 MIME 类型是否为 HLS。"""
    if not mime:
        return False
    lower = mime.lower()
    return (
        "mpegurl" in lower
        or "apple.mpegurl" in lower
        or "x-mpegurl" in lower
        or "octet-stream" in lower
    )


def is_dash_url(url: str) -> bool:
    """``.mpd`` 或 MIME 是 dash+xml → 走 YtDlpEngine。"""
    if ".mpd" in url.lower():
        return True
    return False


def is_direct_video_url(url: str) -> bool:
    """直链视频文件 → Aria2 优先。

    只包含「容器格式」；HLS/DASH 分片（ts / aac / m4s）不视为独立视频。
    """
    ext = (_EXT_RE.search(url) or [None, ""])[1] if _EXT_RE.search(url) else ""
    return ext.lower() in {"mp4", "m4v", "webm", "flv", "mkv", "avi", "mov"}
