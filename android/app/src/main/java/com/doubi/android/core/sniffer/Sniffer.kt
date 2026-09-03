package com.doubi.android.core.sniffer

/**
 * 阶段 8 通用嗅探接口。1:1 对拍桌面版 `src/doubi/core/sniffer.py:Sniffer`。
 *
 * **v0.4.0 范围**：HTTP Content-Type 嗅探（GET URL 看 response header 判定 media 类型），
 * 覆盖直链 m3u8 / mp4 / webm / 任意"浏览器访问会被 inline 播放"的视频。
 *
 * **v0.5.0 范围（不做）**：headless browser 嗅探（WebView load URL + 拦截 m3u8 请求），
 * 覆盖"页面 JS 异步加载"的网站（B 站 / 抖音主页 / Twitter 视频页等）。这需要 WebView
 * 集成 + 跨进程 JS 桥接 + 风险评估（headless 嗅探可能触发网站反爬）——单版本太大，
 * 留 v0.5.0 跟 B 站 / 抖音 adapter 一起做。
 *
 * **嗅探** 跟 Engine 关系：
 * - Engine 是 "已知 URL → 嗅探出 MediaItem → 真下载"
 * - Sniffer 是 "未知 URL → 嗅探出是不是 m3u8/mp4 → 给 Engine 喂"
 * - v0.4.0 范围：ParseAndExpandUseCase 收到非 YouTube URL，先调 Sniffer；
 *   若嗅探到 m3u8/mp4 → DirectLink 让 Engine 走原下载；否则 → Unsupported
 */
interface Sniffer {
    /**
     * 嗅探一个 URL，判定是不是 m3u8 / mp4 等可下载的 media。
     *
     * @return [SniffResult] sealed：
     *   - [SniffResult.Media] —— 嗅探到可下载的 media
     *   - [SniffResult.NotMedia] —— 响应不是 media（如 HTML 页面、404、403）
     *   - [SniffResult.Error] —— 网络错误 / 超时
     */
    suspend fun sniff(url: String): SniffResult
}
