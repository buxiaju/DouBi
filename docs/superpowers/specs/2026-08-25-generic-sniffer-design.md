# Generic Sniffer 适配器 — 任意 URL 视频嗅探

**日期**: 2026-08-25
**状态**: implemented（2026-08-27 完成四入口接通与测试守卫）
**关联里程碑**: M6.16

## 目标

让 DouBi 接受任意 URL（非 douyin/bilibili/youtube），用 headless Chromium
+ cat-catch 风格的 JS 钩子嗅探页面里的视频直链，作为 COLLECTION 容器
返回，复用现有合集下载链路。

## 用户场景

JS 动态加载网页——静态 HTML 抓不到 m3u8/mp4，需要 headless 浏览器渲染
+ XHR/fetch 拦截。一次性后台嗅探（用户不介入），duration 默认 15s。
已知限制：强 user-gesture 校验站点、WebSocket 直播流、DRM 加密内容——
均不支持，spec 中明确标注。

## 架构

新增 4 文件、修改 3 文件：

| 新增 | 职责 |
|---|---|
| `src/doubi/platforms/generic/__init__.py` | 自注册 GenericAdapter |
| `src/doubi/platforms/generic/adapter.py` | `GenericAdapter(PlatformAdapter)`：`matches()` 永真但 priority 最低；`parse(url)` 调用 Sniffer，把 N 个 sniffed URL 包成 COLLECTION 容器返回 |
| `src/doubi/platforms/generic/catch_lite.js` | cat-catch catch.js 裁剪版（去 UI / MediaRecorder），挂到 `window.__catchLite` |
| `src/doubi/core/sniffer.py` | `Sniffer` 服务：管 Playwright lifecycle，注入 init script，跑 N 秒后 `page.evaluate()` 取回 URL 列表。三路数据源合并去重 |

| 修改 | 改动 |
|---|---|
| `src/doubi/core/models.py` | `Platform` enum 加 `GENERIC = "generic"` |
| `src/doubi/core/config.py` | 加扁平 `sniff_duration_sec` / `sniff_headless` / `sniff_user_agent` / `sniff_auto_play` / `sniff_capture_types` 字段 + DEFAULTS 条目 + `load_config` wiring |
| `src/doubi/core/registry.py` | `detect()` 改为 priority-aware：normal-priority 适配器先匹配，generic（priority=-1）兜底 |
| `pyproject.toml` | 加 `playwright` 依赖（必需，全打进安装包） |

## 数据流

```
URL → registry.detect() → (无 normal-priority 匹配) → GenericAdapter.parse(url)
   → Sniffer.sniff(url) → SniffResult(page_url, page_title, items[N])
   → MediaItem(platform=GENERIC, media_type=COLLECTION, children=[
        MediaItem(VIDEO, source_url=<sniffed_url>,
                  extra={sniffed_from, mime, ext, size,
                         collection_title, collection_item_id}),
        ...
      ])
   → pipeline.process_url() → needs_expansion()=True → expand() → N 个 child
   → engine_loader.select(child) 路由
```

## 引擎路由规则

> **实现修正（2026-08-27）**：原设计写的「HLS→YtDlp、直链→Aria2」在实现期
> 已被更专精的引擎取代。以下是**实际**行为，以代码为准。

adapter 不直接选引擎，只在 child 的 `extra` 里写路由**提示位**
（`is_hls` / `is_dash` / `is_direct_video`），真正的选择在
`pipeline._select_engine()`：按 `extra_engines` 顺序取第一个
`supports()` 为真且 `is_available` 的引擎，全不命中才落到默认引擎。

| 特征 | 实际引擎 | 理由 |
|---|---|---|
| `.m3u8` / `.m3u` / `is_hls` | `Nm3u8dlEngine`（二进制可用）→ 降级 `M3u8Engine`（ffmpeg） | 比 yt-dlp 更快，且能处理分片加密 |
| `.mp4` `.m4v` `.webm` `.flv` `.mkv` `.avi` `.mov` | `DirectHttpEngine`（aiohttp 分块） | 无需外部二进制，进度更细 |
| `.mpd` / `is_dash` | 默认引擎（yt-dlp，或 cfg.engine=aria2 时 Aria2） | 见下方「已知缺口」 |
| 其他 / 未知扩展名 | 默认引擎 | yt-dlp generic extractor 自识别 |

`.ts` **不会**作为独立条目出现：它在 `sniffer._ALLOWED_VIDEO_EXTS` 阶段
就被当作 HLS 分片过滤掉了，不是可独立下载的视频。

sniffed child 仍在 `extra.direct_url` 塞直链（Aria2 契约），同时被
REST `_item_to_dict()` 和 MCP `_do_parse_url()` 用于对外输出。

### 已知缺口（不阻塞 M6.16 收尾）

- `is_dash` 目前**无消费者**：只有写入点，没有任何引擎的 `supports()` 读它。
  DASH 靠默认 yt-dlp 兜底，行为正确但属于「歪打正着」。
- `Aria2Engine` 在 generic 场景实际不参与路由竞争：`DirectHttpEngine` 排在
  它之前且会命中所有直链，所以 `cfg.engine=aria2` 也不会让 sniffed `.mp4`
  走 aria2。

## catch_lite.js

从 cat-catch catch.js 裁剪掉 UI 面板 / popup 消息 / MediaRecorder / popup
配置读取，保留：iframe 脱沙盒、TrustedTypes 策略、MediaSource.appendBuffer
代理、XHR/fetch 钩子、video.src setter 钩子、MutationObserver、去重。
暴露 `window.__catchLite.media[]` / `.ready` / `.pageUrl` / `.pageTitle`。

## 三路 URL 来源交叉验证

1. catch_lite.js 抓的（DOM/MediaSource/XHR/fetch 钩子）—— 主源
2. Playwright `page.on("response")` 拦截的（content-type 为 video/* + mpegurl + dash+xml）—— 补 catch 漏的
3. `page.querySelectorAll("video, source, iframe")` 静态扫描 —— 兜底

按 URL 去重，按 `ts` 升序排序。

## Sniffer 流程

```python
async def sniff(self, url: str) -> SniffResult:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=self.cfg.sniff_headless)
        context = await browser.new_context(user_agent=self.cfg.sniff_user_agent or None)
        await context.add_init_script(self._catch_lite_js)
        page = await context.new_page()
        network_meta: dict[str, dict] = {}
        page.on("response", lambda r: self._capture_meta(r, network_meta))
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            if self.cfg.sniff_auto_play:
                await page.evaluate(
                    "() => document.querySelectorAll('video').forEach(v => v.play().catch(()=>{}))"
                )
            await asyncio.sleep(self.cfg.sniff_duration_sec)
            data = await page.evaluate("() => window.__catchLite")
        finally:
            await browser.close()
    items = self._merge_sources(data.get("media", []), network_meta, ...)
    return SniffResult(page_url=data["pageUrl"], page_title=data["pageTitle"], items=items)
```

## 配置字段（AppConfig 扁平）

```python
sniff_enabled: bool = True           # 总开关；False 时不启动浏览器
sniff_duration_sec: int = 15         # 5–60
sniff_headless: bool = True
sniff_user_agent: str = ""           # 空串用 Playwright 默认 UA
sniff_auto_play: bool = True
sniff_capture_types: tuple[str, ...] = (
    "video/mp4", "video/webm", "video/mp2t",
    "application/vnd.apple.mpegurl",
    "application/dash+xml",
)
```

结构性测试守卫（per 硬约束 #4）：`tests/test_config_forwarding.py` 加
`test_sniff_options_forwarded_to_sniffer`，把 `sniff_duration_sec=42` 推离
默认值，断言 Sniffer 实例拿到的是 42。

## GUI / CLI / REST / MCP 集成（已落地）

四入口都必须调 `GenericAdapter.set_config(cfg)`，否则用户改的 `sniff_*`
静默失效（硬约束 #4）。实际注入点：

| 入口 | 注入位置 | 附加改动 |
|---|---|---|
| CLI | `cli/main.py::_apply_sniff_overrides()` | `--sniff-duration N` / `--sniff` / `--no-sniff`，三层优先级（flag > 配置 > 默认） |
| GUI | `ui/app.py`（启动）+ `ui/pages/settings.py`（改设置后） | 设置页「通用嗅探」卡片（5 控件，时长 5–60 夹紧）；`sniffConfigChanged` 信号推给解析页 |
| REST | `server/app.py::_apply_sniff_config()` | `POST /api/v1/parse`、`GET /api/v1/sniff/status/{task_id}`、`GET /api/v1/sniff/status`（能力自检） |
| MCP | `mcp/server.py::run_stdio()` | `sniff_status` 工具；`parse_url` 展平 children |

**判定「这是兜底嗅探吗」的唯一谓词是 `adapter.priority < 0`**。因为
generic 让 `detect()` 对任意 http(s) URL 都返回非 None，用「detect 是否为
None」判断会永远为真。该谓词用在 GUI 剪贴板过滤、GUI 嗅探秒数提示、
REST `_expected_sniff_sec()` 三处。

REST 的 `POST /api/v1/parse` 立即返回 `task_id` 并 `asyncio.create_task`
后台解析，由 `GET /api/v1/sniff/status/{task_id}` 轮询。asyncio 只持弱引用，
所以 task 句柄存在 `_task` 键里防 GC，且从所有响应中剔除（不可 JSON 序列化）。

## 错误处理

- Playwright 未安装 / Chromium 二进制缺失：generic adapter 返回**单个错误
  MediaItem**（`title="[嗅探失败] Playwright 未安装"`），不抛异常。
- 嗅探超时 / 0 个 URL：返回单个错误 MediaItem，UI 显示明确报错。
- 单个 child 下载失败：pipeline 现有错误处理路径不变。

## 测试策略（实际文件名）

| 文件 | 覆盖 |
|---|---|
| `tests/test_config_forwarding.py` | sniff_* 从 AppConfig → Sniffer 实例（推离默认值）；四入口各自调了 `set_config`；`sniff_enabled=False` 不构造浏览器 |
| `tests/test_generic_sniffer.py` | `_merge_sources()` 去重排序、`_capture_meta()` MIME 过滤、COLLECTION 容器与 child 字段、Playwright 缺失降级、registry priority 兜底 |
| `tests/test_server.py` | 三个 REST 嗅探端点；`no_real_browser` fixture 防测试真起 Chromium |
| `tests/test_mcp.py` | 工具白名单（`==` 严格同集）+ `TOOLS`/`_HANDLERS` 同集守卫 |

守卫经变异测试验证：删掉 `sniff_options_from_config` 里的
`duration_sec=cfg.sniff_duration_sec` 后 `test_sniff_options_forwarded_to_sniffer`
确实变红（`assert 15 == 42`）。这正是「推离默认值」的价值 —— 若断言用默认
值 15，删掉搬运后仍会通过。

## 已知限制（写入 spec）

- 强 user-gesture 校验站点：自动 `play()` 被浏览器拦截，m3u8 不加载
- WebSocket 直播推流：catch_lite 不抓 WS 帧
- DRM 加密内容（Widevine/PlayReady）：嗅到 URL 但下载无法解密
