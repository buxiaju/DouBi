"""Generic sniffer tests (M6.16).

覆盖三个层面：

1. **Config 转发**：``AppConfig.sniff_*`` 字段 → ``SniffOptions`` 实例
   的搬运点正确（per 硬约束 #4 + memory 教训「Structural tests for
   configuration forwarding must push values away from defaults」）。
2. **Sniffer 合并逻辑**：``Sniffer._merge_sources`` 三路数据源去重
   + URL/MIME 推断，离线（不启 Playwright）。
3. **GenericAdapter 行为**：mock Sniffer 返回值，验证 COLLECTION 容器
   + child MediaItem 字段填充 + 错误降级路径。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.config import AppConfig, DEFAULTS
from doubi.core.models import MediaType, Platform
from doubi.core.sniffer import (
    SniffOptions,
    Sniffer,
    SniffResult,
    SniffedItem,
    extract_video_urls_from_text,
    infer_mime_from_url,
    is_dash_url,
    is_direct_video_url,
    is_hls_mime,
    is_hls_url,
    is_non_video_mime,
    sniff_options_from_config,
)
from doubi.platforms.generic.adapter import GenericAdapter


# ===========================================================================
# 1. Config 转发：AppConfig.sniff_* → SniffOptions
# ===========================================================================


class TestSniffConfigForwarding:
    """硬约束 #4：CLI/GUI/REST → AppConfig → SniffOptions 唯一搬运点。"""

    def test_default_values_round_trip(self):
        """默认值应该从 DEFAULTS 流到 Sniffer 实例。"""
        cfg = AppConfig()
        opts = sniff_options_from_config(cfg)
        assert opts.duration_sec == DEFAULTS["sniff_duration_sec"]
        assert opts.headless == DEFAULTS["sniff_headless"]
        assert opts.auto_play == DEFAULTS["sniff_auto_play"]
        assert opts.capture_types == DEFAULTS["sniff_capture_types"]

    def test_pushed_away_from_defaults_reach_sniffer(self):
        """memory 教训：把字段推离默认值才能检测漏转发。

        如果某个字段在 sniff_options_from_config 里没透传，默认值测试
        会通过（因为两边都是默认值），但这种漏掉在生产环境会被用户
        改设置后才发现。这里把所有可改字段都推离默认值。
        """
        cfg = AppConfig(
            sniff_duration_sec=42,             # 默认 15
            sniff_headless=False,              # 默认 True
            sniff_user_agent="Mozilla/5.0 TestAgent",  # 默认 ""
            sniff_auto_play=False,             # 默认 True
            sniff_capture_types=("video/mp4",), # 默认 5 个 MIME
        )
        opts = sniff_options_from_config(cfg)
        assert opts.duration_sec == 42, "sniff_duration_sec 未透传"
        assert opts.headless is False, "sniff_headless 未透传"
        assert opts.user_agent == "Mozilla/5.0 TestAgent", "sniff_user_agent 未透传"
        assert opts.auto_play is False, "sniff_auto_play 未透传"
        assert opts.capture_types == ("video/mp4",), "sniff_capture_types 未透传"

    def test_sniffer_uses_forwarded_options(self):
        """Sniffer 构造时拿到的 options 就是 forwarding 的结果。"""
        opts = SniffOptions(duration_sec=99, headless=False)
        sniffer = Sniffer(opts)
        assert sniffer.options.duration_sec == 99
        assert sniffer.options.headless is False


# ===========================================================================
# 2. Sniffer 合并 / 推断逻辑（离线，无 Playwright）
# ===========================================================================


class TestSnifferMerge:
    """``Sniffer._merge_sources`` 三路数据源合并去重 + URL/MIME 推断。"""

    def setup_method(self):
        self.sniffer = Sniffer(SniffOptions())

    def test_infer_mime_from_url(self):
        """URL 扩展名 → MIME 推断。"""
        assert infer_mime_from_url("https://x.com/a.m3u8") == "application/vnd.apple.mpegurl"
        assert infer_mime_from_url("https://x.com/a.m3u") == "application/vnd.apple.mpegurl"
        assert infer_mime_from_url("https://x.com/a.mpd") == "application/dash+xml"
        assert infer_mime_from_url("https://x.com/a.mp4") == "video/mp4"
        assert infer_mime_from_url("https://x.com/a.webm") == "video/webm"
        assert infer_mime_from_url("https://x.com/a.ts") == "video/mp2t"
        # 无扩展名 / 未知扩展名 → 空串
        assert infer_mime_from_url("https://x.com/no_ext") == ""
        assert infer_mime_from_url("https://x.com/a.xyz") == ""

    def test_infer_mime_with_query_string(self):
        """URL 带查询串时仍能正确抽扩展名。"""
        assert infer_mime_from_url("https://x.com/a.m3u8?token=abc&exp=123") == "application/vnd.apple.mpegurl"
        assert infer_mime_from_url("https://x.com/a.mp4?signature=xxx") == "video/mp4"

    def test_engine_routing_predicates(self):
        """引擎路由谓词：HLS / DASH / 直链视频。"""
        assert is_hls_url("https://x.com/a.m3u8") is True
        assert is_hls_url("https://x.com/a.m3u") is True
        assert is_hls_url("https://x.com/a.m3u8?token=1") is True
        # m3u8 关键字在路径或 query 中
        assert is_hls_url("https://x.com/m3u8/stream") is True
        assert is_hls_url("https://x.com/stream?type=m3u8") is True
        # HLS 加密 key
        assert is_hls_url("https://x.com/segment.key") is True
        assert is_hls_url("https://x.com/playlist?key=abc") is True
        assert is_hls_url("https://x.com/a.mp4") is False

    def test_hls_mime_detection(self):
        assert is_hls_mime("application/vnd.apple.mpegurl") is True
        assert is_hls_mime("application/x-mpegurl") is True
        assert is_hls_mime("video/mp4") is False
        assert is_hls_mime("") is False

        assert is_dash_url("https://x.com/a.mpd") is True
        assert is_dash_url("https://x.com/a.mpd?x=1") is True
        assert is_dash_url("https://x.com/a.mp4") is False

        assert is_direct_video_url("https://x.com/a.mp4") is True
        assert is_direct_video_url("https://x.com/a.webm") is True
        assert is_direct_video_url("https://x.com/a.ts") is False   # 分片不视为独立视频
        assert is_direct_video_url("https://x.com/a.m3u8") is False  # HLS 不是直链
        assert is_direct_video_url("https://x.com/a.mpd") is False   # DASH 不是直链

    def test_merge_dedup_by_url(self):
        """同一 URL 多次出现只保留第一次。"""
        catch_media = [
            {"url": "https://x.com/a.mp4", "type": "xhr", "mime": "", "size": None, "ts": 100},
            {"url": "https://x.com/a.mp4", "type": "fetch", "mime": "", "size": None, "ts": 200},
        ]
        network_meta = {
            "https://x.com/a.mp4": {"mime": "video/mp4", "size": 12345, "initiator": "https://x.com/page"},
        }
        items = self.sniffer._merge_sources(catch_media, network_meta, static_scan=[])
        assert len(items) == 1
        # network 拿到的更准 mime/size 应该补进去
        assert items[0].mime == "video/mp4"
        assert items[0].size == 12345

    def test_merge_keeps_url_only_in_network(self):
        """network_meta 里有但 catch_lite 漏抓的 URL 也要进列表。"""
        catch_media: list[dict] = []
        network_meta = {
            "https://x.com/missed.m3u8": {
                "mime": "application/vnd.apple.mpegurl",
                "size": None,
                "initiator": "https://x.com/page",
            }
        }
        items = self.sniffer._merge_sources(catch_media, network_meta, static_scan=[])
        assert len(items) == 1
        assert items[0].url == "https://x.com/missed.m3u8"
        assert items[0].type == "network"
        assert items[0].mime == "application/vnd.apple.mpegurl"

    def test_merge_sorts_by_ts_ascending(self):
        """按 ts 升序：早抓到的排前面（通常是更重要的主视频流）。"""
        catch_media = [
            {"url": "https://x.com/late.mp4", "type": "xhr", "mime": "", "size": None, "ts": 5000},
            {"url": "https://x.com/early.m3u8", "type": "xhr", "mime": "", "size": None, "ts": 100},
            {"url": "https://x.com/mid.mp4", "type": "xhr", "mime": "", "size": None, "ts": 1000},
        ]
        items = self.sniffer._merge_sources(catch_media, network_meta={}, static_scan=[])
        assert [i.url for i in items] == [
            "https://x.com/early.m3u8",
            "https://x.com/mid.mp4",
            "https://x.com/late.mp4",
        ]

    def test_merge_skips_empty_url(self):
        """空 / 非 http(s) URL 跳过。"""
        catch_media = [
            {"url": "", "type": "xhr", "mime": "", "size": None, "ts": 1},
            {"url": "javascript:void(0)", "type": "xhr", "mime": "", "size": None, "ts": 2},
            {"url": "about:blank", "type": "xhr", "mime": "", "size": None, "ts": 3},
        ]
        items = self.sniffer._merge_sources(catch_media, network_meta={}, static_scan=[])
        assert items == []

    def test_merge_url_mime_inferred_when_missing(self):
        """catch_lite 没拿到 mime 时从 URL 扩展名推断。"""
        catch_media = [
            {"url": "https://x.com/a.m3u8", "type": "xhr", "mime": "", "size": None, "ts": 1},
        ]
        items = self.sniffer._merge_sources(catch_media, network_meta={}, static_scan=[])
        assert items[0].mime == "application/vnd.apple.mpegurl"

    def test_mime_filter_removes_non_video_types(self):
        """非视频 MIME（application/json / text/html）被过滤掉。"""
        catch_media = [
            {"url": "https://x.com/api.json", "type": "xhr", "mime": "application/json", "size": None, "ts": 1},
            {"url": "https://x.com/page.html", "type": "xhr", "mime": "text/html", "size": None, "ts": 2},
            {"url": "https://x.com/video.m3u8", "type": "xhr", "mime": "application/vnd.apple.mpegurl", "size": None, "ts": 3},
        ]
        items = self.sniffer._merge_sources(catch_media, network_meta={}, static_scan=[])
        assert len(items) == 1
        assert items[0].url == "https://x.com/video.m3u8"

    def test_mime_filter_keeps_content_verified_urls(self):
        """即使 MIME 是非视频类型，content_verified 的 URL 仍保留。"""
        json_extracted = {
            "https://x.com/embed.m3u8": {
                "mime": "application/json",
                "size": None,
                "initiator": "https://x.com/api",
            }
        }
        items = self.sniffer._merge_sources(
            catch_media=[], network_meta={}, static_scan=[],
            json_extracted=json_extracted,
        )
        assert len(items) == 1
        assert items[0].url == "https://x.com/embed.m3u8"
        assert items[0].type == "json_extract"

    def test_json_extract_plus_network_merge(self):
        """JSON 解析 + network 拦截合并。"""
        json_extracted = {
            "https://x.com/from_json.m3u8": {
                "mime": "",
                "size": None,
                "initiator": "https://x.com/api",
            }
        }
        network_meta = {
            "https://x.com/direct.mp4": {
                "mime": "video/mp4",
                "size": 5000,
                "initiator": "https://x.com/page",
            }
        }
        items = self.sniffer._merge_sources(
            catch_media=[], network_meta=network_meta, static_scan=[],
            json_extracted=json_extracted,
        )
        assert len(items) == 2
        urls = {i.url for i in items}
        assert "https://x.com/from_json.m3u8" in urls
        assert "https://x.com/direct.mp4" in urls

    def test_page_scan_adds_urls(self):
        """JS 页面扫描结果也被合并。"""
        page_scan = {
            "https://x.com/from_scan.m3u8": {
                "mime": "",
                "size": None,
                "initiator": "https://x.com/page",
            }
        }
        items = self.sniffer._merge_sources(
            catch_media=[], network_meta={}, static_scan=[],
            page_scan=page_scan,
        )
        assert len(items) == 1
        assert items[0].type == "page_scan"

    def test_ext_whitelist_drops_ts_aac_mpd(self):
        """用户可见扩展名白名单：.ts / .aac / .m4s / .mpd 不进入列表。"""
        catch_media = [
            {"url": "https://x.com/vid/index.m3u8", "type": "xhr", "mime": "", "size": None, "ts": 100},
            {"url": "https://x.com/vid/0000000.ts", "type": "xhr", "mime": "video/mp2t", "size": None, "ts": 200},
            {"url": "https://x.com/vid/0000000.aac", "type": "xhr", "mime": "audio/aac", "size": None, "ts": 210},
            {"url": "https://x.com/vid/seg1.m4s", "type": "xhr", "mime": "video/iso.segment", "size": None, "ts": 220},
            {"url": "https://x.com/vid/manifest.mpd", "type": "xhr", "mime": "application/dash+xml", "size": None, "ts": 230},
            {"url": "https://x.com/vid/movie.mp4", "type": "xhr", "mime": "video/mp4", "size": None, "ts": 240},
            {"url": "https://x.com/vid/movie.mkv", "type": "xhr", "mime": "", "size": None, "ts": 250},
            {"url": "https://x.com/vid/movie.flv", "type": "xhr", "mime": "", "size": None, "ts": 260},
            {"url": "https://x.com/vid/movie.webm", "type": "xhr", "mime": "", "size": None, "ts": 270},
            {"url": "https://x.com/vid/movie.mov", "type": "xhr", "mime": "", "size": None, "ts": 280},
            {"url": "https://x.com/vid/movie.avi", "type": "xhr", "mime": "", "size": None, "ts": 290},
            {"url": "https://x.com/vid/movie.m4v", "type": "xhr", "mime": "", "size": None, "ts": 300},
            {"url": "https://x.com/vid/pl.m3u", "type": "xhr", "mime": "", "size": None, "ts": 310},
        ]
        items = self.sniffer._merge_sources(catch_media=catch_media, network_meta={}, static_scan=[])
        urls = [i.url for i in items]
        # 被丢弃的
        assert not any(u.endswith(".ts") for u in urls)
        assert not any(u.endswith(".aac") for u in urls)
        assert not any(u.endswith(".m4s") for u in urls)
        assert not any(u.endswith(".mpd") for u in urls)
        # 被保留的
        assert "https://x.com/vid/index.m3u8" in urls
        assert "https://x.com/vid/pl.m3u" in urls
        assert "https://x.com/vid/movie.mp4" in urls
        assert "https://x.com/vid/movie.mkv" in urls
        assert "https://x.com/vid/movie.flv" in urls
        assert "https://x.com/vid/movie.webm" in urls
        assert "https://x.com/vid/movie.mov" in urls
        assert "https://x.com/vid/movie.avi" in urls
        assert "https://x.com/vid/movie.m4v" in urls
        assert len(items) == 9


class TestMimeFilter:
    """非视频 MIME 过滤函数。"""

    def test_is_non_video_mime_true(self):
        assert is_non_video_mime("application/json") is True
        assert is_non_video_mime("text/html; charset=utf-8") is True
        assert is_non_video_mime("image/png") is True
        assert is_non_video_mime("image/jpeg") is True
        assert is_non_video_mime("text/css") is True
        assert is_non_video_mime("application/javascript") is True

    def test_is_non_video_mime_false(self):
        assert is_non_video_mime("video/mp4") is False
        assert is_non_video_mime("audio/mpeg") is False
        assert is_non_video_mime("application/vnd.apple.mpegurl") is False
        assert is_non_video_mime("") is False
        assert is_non_video_mime("application/octet-stream") is False  # HLS 场景保留

    def test_extract_video_urls_from_text(self):
        text = '{"url": "https://cdn.example.com/stream.m3u8?token=abc", "other": "value"}'
        urls = extract_video_urls_from_text(text)
        assert "https://cdn.example.com/stream.m3u8?token=abc" in urls

    def test_extract_video_urls_from_text_multiple(self):
        text = '''
        "video1": "https://a.com/hls/master.m3u8",
        "video2": "https://b.com/dash/manifest.mpd",
        "not_a_video": "https://c.com/page.html"
        '''
        urls = extract_video_urls_from_text(text)
        assert "https://a.com/hls/master.m3u8" in urls
        assert "https://b.com/dash/manifest.mpd" in urls
        assert all(".html" not in u for u in urls)

    def test_extract_video_urls_from_text_empty(self):
        assert extract_video_urls_from_text("") == []
        assert extract_video_urls_from_text("no urls here") == []

    def test_extract_video_urls_deduplicates(self):
        text = '"a": "https://x.com/v.m3u8", "b": "https://x.com/v.m3u8"'
        urls = extract_video_urls_from_text(text)
        assert len(urls) == 1


# ===========================================================================
# 3. Sniffer 不可用降级
# ===========================================================================


class TestSnifferUnavailable:
    """Playwright 没装时 Sniffer 必须降级返回错误，不抛异常。"""

    def test_sniff_returns_error_when_playwright_missing(self, monkeypatch):
        """模拟 Playwright 不可用，sniff() 返回带 error 的 SniffResult。"""
        sniffer = Sniffer(SniffOptions())
        # 强制把 _HAS_PLAYWRIGHT 看作 False
        monkeypatch.setattr("doubi.core.sniffer._HAS_PLAYWRIGHT", False)

        result = asyncio.run(sniffer.sniff("https://example.com/page"))
        assert result.error is not None
        assert "Playwright" in result.error
        assert result.items == []

    def test_is_available_returns_false_when_playwright_missing(self, monkeypatch):
        monkeypatch.setattr("doubi.core.sniffer._HAS_PLAYWRIGHT", False)
        assert Sniffer.is_available() is False


# ===========================================================================
# 4. GenericAdapter 行为（mock Sniffer）
# ===========================================================================


class TestGenericAdapter:
    """GenericAdapter 的 URL 匹配、parse() 容器构造、错误降级。"""

    def test_match_url_any_http(self):
        adapter = GenericAdapter()
        assert adapter.match_url("https://example.com/any/page") is True
        assert adapter.match_url("http://foo.bar/baz") is True

    def test_match_url_rejects_non_http(self):
        adapter = GenericAdapter()
        assert adapter.match_url("") is False
        assert adapter.match_url("javascript:void(0)") is False
        assert adapter.match_url("about:blank") is False
        assert adapter.match_url("file:///etc/passwd") is False

    def test_priority_is_lowest(self):
        """generic 的 priority 是 -1，让其他适配器先匹配。"""
        assert GenericAdapter.priority == -1

    @pytest.mark.asyncio
    async def test_parse_returns_collection_with_children(self, monkeypatch):
        """mock Sniffer 返回 N 个 URL，parse() 返回 COLLECTION + N 个 child。"""
        adapter = GenericAdapter()
        # 给 adapter 注入空 config（避免 lazy load_config 读磁盘）
        GenericAdapter.set_config(AppConfig())

        # mock Sniffer 类的 sniff 方法
        fake_result = SniffResult(
            page_url="https://example.com/page",
            page_title="示例页面",
            items=[
                SniffedItem(url="https://example.com/a.m3u8", type="xhr",
                            mime="application/vnd.apple.mpegurl", size=None, ts=100),
                SniffedItem(url="https://example.com/b.mp4", type="fetch",
                            mime="video/mp4", size=12345, ts=200),
            ],
        )
        async def _fake_sniff(self, url):
            return fake_result
        # patch Sniffer.__init__ 让它直接返回，避免真创建 Playwright
        monkeypatch.setattr(Sniffer, "sniff", _fake_sniff)

        result = await adapter.parse("https://example.com/page")

        assert result is not None
        assert result.platform == Platform.GENERIC
        assert result.media_type == MediaType.COLLECTION
        assert len(result.children) == 2
        # child 字段填充
        child0 = result.children[0]
        assert child0.source_url == "https://example.com/a.m3u8"
        assert child0.platform == Platform.GENERIC
        assert child0.media_type == MediaType.VIDEO
        assert "示例页面" in child0.title
        # 容器归属（per 硬约束）
        assert child0.extra["collection_title"] == "示例页面"
        assert child0.extra["collection_item_id"] == 0
        # Aria2 契约
        assert child0.extra["direct_url"] == "https://example.com/a.m3u8"
        # 引擎路由提示
        assert child0.extra["is_hls"] is True
        assert child0.extra["is_direct_video"] is False
        # item_id 唯一（防 TaskManager dedup）
        ids = {c.item_id for c in result.children}
        assert len(ids) == 2

    @pytest.mark.asyncio
    async def test_parse_returns_error_item_when_sniff_fails(self, monkeypatch):
        """Sniffer 返回 error，parse() 返回单个错误 MediaItem。"""
        adapter = GenericAdapter()
        GenericAdapter.set_config(AppConfig())

        async def _fake_sniff(self, url):
            return SniffResult(
                page_url=url,
                error="Playwright 未安装",
            )
        monkeypatch.setattr(Sniffer, "sniff", _fake_sniff)

        result = await adapter.parse("https://example.com/page")
        assert result is not None
        assert result.platform == Platform.GENERIC
        assert result.media_type == MediaType.VIDEO  # 错误降级为 VIDEO
        assert result.children == []  # 无 children
        assert "嗅探失败" in result.title
        assert result.extra.get("sniff_error") == "Playwright 未安装"

    @pytest.mark.asyncio
    async def test_parse_returns_error_item_when_zero_urls(self, monkeypatch):
        """Sniffer 抓到 0 个 URL，parse() 也降级为错误 item。"""
        adapter = GenericAdapter()
        GenericAdapter.set_config(AppConfig())

        async def _fake_sniff(self, url):
            return SniffResult(page_url=url, page_title="空页面", items=[])
        monkeypatch.setattr(Sniffer, "sniff", _fake_sniff)

        result = await adapter.parse("https://example.com/empty")
        assert result is not None
        assert result.children == []
        assert "嗅探失败" in result.title
        # error 字段：mock 没设 error，adapter 用 fallback 文案
        # 「未嗅探到任何视频 URL」
        assert "未嗅探" in result.extra.get("sniff_error", "")


# ===========================================================================
# 5. Registry 兜底逻辑
# ===========================================================================


class TestRegistryPriorityFallback:
    """registry.detect() 应该让 generic 在所有 normal-priority 之后匹配。"""

    def test_known_platform_wins_over_generic(self):
        """YouTube URL 应该匹配 YouTube adapter，不走 generic。"""
        # 触发 platforms 包导入注册所有 adapter
        import doubi.platforms  # noqa: F401

        from doubi.core.registry import PlatformRegistry
        adapter = PlatformRegistry.detect("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert adapter is not None
        assert adapter.name == "youtube"
        assert adapter.name != "generic"

    def test_unknown_url_falls_back_to_generic(self):
        """不认识的平台 URL 走 generic 兜底。"""
        import doubi.platforms  # noqa: F401

        from doubi.core.registry import PlatformRegistry
        adapter = PlatformRegistry.detect("https://random-site.example.com/article/123")
        assert adapter is not None
        assert adapter.name == "generic"

    def test_generic_registered_with_lowest_priority(self):
        """generic adapter priority=-1，最低。"""
        import doubi.platforms  # noqa: F401

        from doubi.core.registry import PlatformRegistry
        generic = PlatformRegistry.get_by_name("generic")
        assert generic.priority == -1
        # 所有其他适配器 priority 应该 >= 0
        for adapter in PlatformRegistry.all():
            if adapter.name == "generic":
                continue
            assert adapter.priority >= 0, f"{adapter.name} priority 异常: {adapter.priority}"
