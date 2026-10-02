"""Smoke test for YtDlpGenericAdapter against real-world URLs.

跑真实 URL 看 ytdlp_generic 在国内 / 国外平台上的解析效果。每个 URL
30 秒超时（避免某个站 hang 整个 smoke），结果分 PASS / FAIL 两种：

* PASS: parse() 返回 MediaItem（带 title）
* FAIL: parse() 返回 None（yt-dlp 抛异常：登录失效 / 地区限制 / 站点下线 等）

**用法**::

    python scripts/smoke_ytdlp_generic.py                # 跑全部
    python scripts/smoke_ytdlp_generic.py --region cn   # 只跑国内
    python scripts/smoke_ytdlp_generic.py --region intl # 只跑国外

不是 pytest 用例——真实 URL 不稳定，单测 / CI 里无法复现。这只是开发期
smoke 工具，不进 tests/ 也不进 CI。

URLs 列表是「截止 2026-09 已知可访问的公开页」——任何失效都是合理的，
加新 URL 时挑仍在线的。URLs 注释里标了来源便于追溯。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

# 把 src/ 加入 path（仓库 root 运行，不需要 ``pip install -e .``）
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.config import load_config
from doubi.platforms.ytdlp_generic import YtDlpGenericAdapter


# ---------------------------------------------------------------------------
# URLs 列表：每个 tuple = (平台名, URL, 来源备注)
# 优先用「搜索引擎能查到、URL 形态完整」的真实公开页
# ---------------------------------------------------------------------------

CN_URLS: list[tuple[str, str, str]] = [
    # 网易云音乐 — 真实公开歌曲（搜索结果验证可访问）
    ("网易云音乐 公开歌曲",     "https://music.163.com/song?id=1491760", "已验证可访问（Boyfriend 试听页）"),
    ("网易云音乐 公开歌曲 2",   "https://music.163.com/song?id=65927",   "Xiaomusic 歌单收录"),

    # AcFun — 真实视频 ID（web_search 验证）
    ("AcFun 公开视频",           "https://www.acfun.cn/v/ac46176257",      "塞尔达 UP 推荐系列文章引用"),

    # 知乎视频 — 公开 zvideo URL
    ("知乎 视频",                "https://www.zhihu.com/zvideo/1579795012560351232", "网络编辑发稿平台引用"),

    # 西瓜视频 — 公开视频 ID
    ("西瓜视频",                 "https://www.ixigua.com/7357697654392160795",       "网络编辑发稿平台引用"),

    # 央视频 — 公开 post
    ("央视频",                   "https://m.yangshipin.cn/static/moment/detail.html?post_id=f01cml54fan72", "网络编辑发稿平台引用"),

    # 好看视频（百度）— 公开 vid
    ("好看视频",                 "https://haokan.baidu.com/v?vid=12657028155065319547", "网络编辑发稿平台引用"),

    # 优酷 — 公开 id
    ("优酷 视频",                "https://v.youku.com/v_show/id_XNjM5ODcyNTcwOA==.html", "网络编辑发稿平台引用"),

    # 腾讯视频 — 公开 page id
    ("腾讯视频",                 "https://v.qq.com/x/page/h3553rpl344.html", "网络编辑发稿平台引用"),

    # 爱奇艺 — 公开 v_id
    ("爱奇艺 视频",              "https://www.iqiyi.com/v_1dgjwmhkrm0.html", "网络编辑发稿平台引用"),

    # 搜狐视频 — 公开 vid
    ("搜狐视频",                 "https://tv.sohu.com/v/dXMvMjc0OTA3NjUzLzUzMzUzNzY4Ny5zaHRtbA==.html", "网络编辑发稿平台引用"),

    # 微博视频 — 公开 status URL（模板）
    ("微博视频",                 "https://weibo.com/7207262816/O70aCbjnd", "video parser 文档引用"),

    # 喜马拉雅 — 失效 ID（已知 yt-dlp extractor bug）
    ("喜马拉雅 失效 ID",         "https://www.ximalaya.com/album/2948347", "KeyError('data') — yt-dlp extractor bug"),
]


async def _try_parse(
    adapter: YtDlpGenericAdapter,
    url: str,
    timeout_sec: int = 15,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """单条 URL smoke：跑 parse()，带 timeout + retry-on-rate-limit。

    网易云 / Twitter 这类站对短时间高频请求会直接断连（WinError 10054），
    隔几秒重试通常就能恢复。retry 间隔默认 3 秒 + exponential backoff。

    返回 dict 形如 ``{"ok": bool, "title": ..., "extractor": ..., "error": ..., "duration_sec": ...}``。
    """
    started = time.monotonic()
    last_error = "unknown"
    for attempt in range(1, max_attempts + 1):
        try:
            item = await asyncio.wait_for(adapter.parse(url), timeout=timeout_sec)
        except asyncio.TimeoutError:
            last_error = f"timeout after {timeout_sec}s"
            # timeout 不重试
            break
        except Exception as exc:  # noqa: BLE001 - 兜底
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < max_attempts:
                wait = 2 ** (attempt - 1) * 3   # 3, 6, 12s
                await asyncio.sleep(wait)
                continue
            break
        duration = time.monotonic() - started
        if item is None:
            last_error = "parse() returned None (yt-dlp DownloadError)"
            if attempt < max_attempts:
                wait = 2 ** (attempt - 1) * 3
                await asyncio.sleep(wait)
                continue
            break
        return {
            "ok": True, "url": url,
            "title": item.title, "platform": item.platform.value,
            "extractor": item.extra.get("extractor") if item.extra else None,
            "duration_sec": round(duration, 2),
            "attempts": attempt,
        }
    return {
        "ok": False, "url": url, "error": last_error,
        "duration_sec": time.monotonic() - started,
        "attempts": attempt,
    }


async def _run_region(name: str, urls: list[tuple[str, str, str]]) -> tuple[int, int]:
    """跑一个 region 的 smoke，返回 (pass_count, fail_count)。"""
    print(f"\n=== {name} ({len(urls)} URLs) ===")
    adapter = YtDlpGenericAdapter()
    YtDlpGenericAdapter.set_config(load_config(None))

    passed = 0
    failed = 0
    for label, url, note in urls:
        result = await _try_parse(adapter, url)
        if result["ok"]:
            passed += 1
            ext = result.get("extractor") or "?"
            attempts = result.get("attempts", 1)
            print(f"  [PASS] {label:<24} ext={ext:<20} ({result['duration_sec']}s, attempt {attempts})")
            print(f"           {result['title'][:70]!r}")
            print(f"           {result['url']}")
        else:
            failed += 1
            err = result["error"][:90]
            attempts = result.get("attempts", 1)
            print(f"  [FAIL] {label:<24} ({result['duration_sec']}s, attempt {attempts})")
            print(f"           {err}")
            print(f"           {result['url']}")
        if note:
            print(f"           备注：{note}")
        # 每条之间 1s 间隔，避免被网易云/Twitter 这类站限频
        await asyncio.sleep(1.0)
    return passed, failed


async def main_async(args: argparse.Namespace) -> int:
    total_pass = total_fail = 0
    if args.region in ("cn", "all"):
        p, f = await _run_region("国内平台", CN_URLS)
        total_pass += p
        total_fail += f
    if args.region in ("intl", "all"):
        p, f = await _run_region("国外平台", INTL_URLS)
        total_pass += p
        total_fail += f
    total = total_pass + total_fail
    print(f"\nTotal: {total_pass} passed / {total_fail} failed / {total} URLs")
    return 0 if total_fail == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test ytdlp_generic against real URLs.")
    parser.add_argument("--region", choices=["cn", "intl", "all"], default="all",
                        help="which region to smoke (default: all)")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())