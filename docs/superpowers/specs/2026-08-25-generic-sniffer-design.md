# Generic Sniffer 适配器 — 任意 URL 视频嗅探

**日期**: 2026-08-25
**状态**: design / in-progress
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

URL 扩展名 + MIME 双判：

| 特征 | 引擎 | 理由 |
|---|---|---|
| `.m3u8` / `.m3u` 或 `application/vnd.apple.mpegurl` | YtDlpEngine | HLS 解析+合并 TS，Aria2 不支持 |
| `.mpd` 或 `application/dash+xml` | YtDlpEngine | DASH 同上 |
| `.mp4` / `.webm` / `.ts` 直链 | Aria2Engine 优先，YtDlpEngine 兜底 | Aria2 多线程加速更优 |
| 其他 / 未知扩展名 | YtDlpEngine | yt-dlp generic extractor 自识别 |

sniffed child 在 `extra.direct_url` 塞直链（Aria2 现有契约）。

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

## GUI / CLI / REST 集成

- **GUI**：解析页零改动（COLLECTION + child 模式 UI 已有）。进度对话框加
  generic URL 分支文案：「嗅探中… (15s)」。settings.py 加「嗅探」卡片。
- **CLI**：`doubi download <unknown-url>` 自动生效（registry 兜底）。新增
  `--sniff-duration N` 和 `--no-sniff` flag。
- **REST**：`POST /api/parse` 接受任意 URL。新增 `GET /api/sniff/status/<task_id>`
  供前端轮询嗅探进度。

## 错误处理

- Playwright 未安装 / Chromium 二进制缺失：generic adapter 返回**单个错误
  MediaItem**（`title="[嗅探失败] Playwright 未安装"`），不抛异常。
- 嗅探超时 / 0 个 URL：返回单个错误 MediaItem，UI 显示明确报错。
- 单个 child 下载失败：pipeline 现有错误处理路径不变。

## 测试策略

- `test_config_forwarding.py`：sniff_* 字段从 AppConfig → Sniffer 转发
- `test_sniffer.py`：用 monkeypatch 替换 `async_playwright()`，离线测试
  `_merge_sources()` 去重 + 排序逻辑、`_capture_meta()` 过滤逻辑
- `test_generic_adapter.py`：monkeypatch Sniffer，验证 COLLECTION 容器
  生成、child MediaItem 字段填充、Playwright 不可用时降级路径
- `test_registry.py`：加 priority 顺序测试，generic 兜底逻辑

## 已知限制（写入 spec）

- 强 user-gesture 校验站点：自动 `play()` 被浏览器拦截，m3u8 不加载
- WebSocket 直播推流：catch_lite 不抓 WS 帧
- DRM 加密内容（Widevine/PlayReady）：嗅到 URL 但下载无法解密
