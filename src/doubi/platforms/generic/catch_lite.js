/*
 * catch_lite.js — cat-catch catch.js 裁剪版（无 UI / MediaRecorder / popup 消息）
 *
 * 由 doubi.core.sniffer.Sniffer 通过 Playwright page.add_init_script() 注入
 * 到目标页面，在所有页面脚本之前运行。抓到的 URL 列表挂到
 * window.__catchLite.media[]，供 page.evaluate() 读取。
 *
 * 来源：cat-catch-master/catch-script/catch.js，保留 iframe 脱沙盒 /
 * TrustedTypes 策略 / MediaSource.appendBuffer 代理 / XHR + fetch 钩子 /
 * video.src setter 钩子 / MutationObserver，去掉 UI 面板 / popup /
 * MediaRecorder / 用户配置读取（用 SniffOptions 注入）。
 *
 * 详见 docs/superpowers/specs/2026-08-25-generic-sniffer-design.md。
 */
(function () {
    if (window.__catchLite && window.__catchLite.ready) {
        return; // 已经注入过，避免重复
    }

    const media = [];           // 抓到的 URL 列表
    const seen = new Set();     // 去重 key 集合（url + "|" + mime）

    function addEntry(url, type, mime, size, initiator) {
        if (!url) return;
        // 只关注 http(s) / blob / data URI；过滤掉 about: / javascript:
        if (!/^(https?|blob|data):/i.test(url)) return;
        const key = url + "|" + (mime || "");
        if (seen.has(key)) return;
        seen.add(key);
        media.push({
            url: url,
            type: type,           // "xhr" | "fetch" | "media_source" | "video_src" | "iframe"
            mime: mime || "",
            size: size || null,
            initiator: initiator || location.href,
            ts: Date.now(),
        });
    }

    // ---- 1. iframe 脱沙盒（cat-catch issues #576） -------------------------
    // 让我们的钩子能穿透 sandbox 属性的 iframe（部分站点用 sandbox 限制
    // 脚本执行，导致嗅探漏抓）。只在 DOMContentLoaded 后处理已存在的 iframe。
    function processIframe(iframe) {
        if (iframe && iframe.hasAttribute && iframe.hasAttribute("sandbox")) {
            const cloned = iframe.cloneNode(true);
            cloned.removeAttribute("sandbox");
            if (iframe.parentNode) {
                iframe.parentNode.replaceChild(cloned, iframe);
            }
        }
    }
    document.addEventListener("DOMContentLoaded", () => {
        try {
            document.querySelectorAll("iframe").forEach(processIframe);
            const observer = new MutationObserver((mutations) => {
                for (const m of mutations) {
                    if (m.type !== "childList") continue;
                    m.addedNodes.forEach((node) => {
                        if (node.nodeName === "IFRAME") {
                            processIframe(node);
                        } else if (node.querySelectorAll) {
                            node.querySelectorAll("iframe").forEach(processIframe);
                        }
                    });
                }
            });
            observer.observe(document.body || document.documentElement, {
                childList: true, subtree: true,
            });
        } catch (e) {
            // 沙盒/跨域限制可能让 MutationObserver 失败，吞掉即可
        }
    });

    // ---- 2. TrustedTypes 策略（部分站点要求） -------------------------------
    // Chromium 93+ 的 Trusted Types API 强制 innerHTML 走 policy，否则抛
    // 异常。我们注入一个宽松 policy，让 catch_lite 自己不会触发违规。
    try {
        if (typeof trustedTypes !== "undefined" && typeof trustedTypes.createPolicy === "function") {
            trustedTypes.createPolicy("catchLitePolicy", {
                createHTML: (s) => s,
                createScript: (s) => s,
                createScriptURL: (s) => s,
            });
        }
    } catch (e) {
        // 重复 create policy 会抛，吞掉
    }

    // ---- 3. MediaSource.appendBuffer 代理（抓 blob: URL 内部数据） ---------
    // 一些站点用 MSE 把视频分片 appendBuffer 到一个 blob: URL，blob 本身
    // 无法直接下载。我们拦截 appendBuffer 抓出原始分片 URL（如果 init
    // segment 里有 URL 信息）。这个钩子还能抓到 SourceBuffer 的 mimeType。
    try {
        const origAppend = SourceBuffer.prototype.appendBuffer;
        SourceBuffer.prototype.appendBuffer = function (data) {
            try {
                // SourceBuffer 的 mimeType 透露流类型（mp4/webm/mpegurl）
                const mime = this.mimeType || "";
                if (mime) {
                    // blob URL 由 media element 引用，去 URL 对象查
                    const elem = this.mediaElement || this.mediaSource && this.mediaSource.mediaElement;
                    if (elem && elem.src) {
                        addEntry(elem.src, "media_source", mime, null, location.href);
                    }
                }
            } catch (e) {
                // 钩子本身不能让 appendBuffer 失败
            }
            return origAppend.call(this, data);
        };
    } catch (e) {
        // SourceBuffer 不可用（无 MSE 支持），跳过
    }

    // ---- 4. XHR / fetch 钩子（抓所有网络请求） -----------------------------
    try {
        const origOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function (method, url, ...rest) {
            this.__catchUrl = url;
            this.__catchMethod = method;
            return origOpen.call(this, method, url, ...rest);
        };
        const origSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.send = function (body) {
            // 在 onreadystatechange 后拿 response 的 mime + size
            const self = this;
            const origOnReady = this.onreadystatechange;
            this.onreadystatechange = function () {
                if (self.readyState === 4 && self.__catchUrl) {
                    try {
                        const mime = self.getResponseHeader("Content-Type") || "";
                        const size = parseInt(self.getResponseHeader("Content-Length") || "0", 10) || null;
                        addEntry(self.__catchUrl, "xhr", mime, size, location.href);
                    } catch (e) {}
                }
                if (origOnReady) return origOnReady.apply(self, arguments);
            };
            return origSend.call(this, body);
        };
    } catch (e) {
        // XHR 不可用，跳过
    }

    try {
        const origFetch = window.fetch;
        window.fetch = async function (input, init) {
            const response = await origFetch.call(this, input, init);
            try {
                const url = (typeof input === "string") ? input : (input && input.url) || "";
                if (url && response && response.headers) {
                    const mime = response.headers.get("Content-Type") || "";
                    const size = parseInt(response.headers.get("Content-Length") || "0", 10) || null;
                    addEntry(url, "fetch", mime, size, location.href);
                }
            } catch (e) {}
            return response;
        };
    } catch (e) {
        // fetch 不可用或被站点重定义，跳过
    }

    // ---- 5. video.src / currentSrc setter 钩子 -----------------------------
    // 一些站点直接给 <video src="..."> 赋值，不经过 XHR。Hook HTMLMediaElement
    // 的 src 属性 setter 拿到这个赋值。
    try {
        const elem = HTMLMediaElement.prototype;
        const srcDesc = Object.getOwnPropertyDescriptor(elem, "src");
        if (srcDesc && srcDesc.set) {
            Object.defineProperty(elem, "src", {
                set: function (v) {
                    try {
                        addEntry(String(v), "video_src", "", null, location.href);
                    } catch (e) {}
                    return srcDesc.set.call(this, v);
                },
                get: srcDesc.get,
                configurable: true,
            });
        }
    } catch (e) {
        // 跨域 / 不可访问 prototype，跳过
    }

    // ---- 6. 静态扫描（兜底，万一前面钩子全失效） --------------------------
    // DOMContentLoaded 后扫一次 video / source / iframe[src]。
    document.addEventListener("DOMContentLoaded", () => {
        try {
            document.querySelectorAll("video[src], video > source[src], iframe[src]").forEach((el) => {
                const src = el.src || el.getAttribute("src") || "";
                if (src) {
                    const tag = el.tagName.toLowerCase();
                    const type = tag === "iframe" ? "iframe" : "video_src";
                    addEntry(String(src), type, "", null, location.href);
                }
            });
        } catch (e) {}
    });

    // ---- 暴露给 Playwright 读取 -------------------------------------------
    window.__catchLite = {
        media: media,
        ready: true,
        pageUrl: location.href,
        pageTitle: document.title || "",
    };
})();
