"""aria2 多线程下载引擎。

设计取舍
========

aria2 是一个独立的多线程下载器，通过 JSON-RPC 控制一个 aria2 守护进程。
与 yt-dlp 的本质区别：

* **yt-dlp** 是「解析器 + 下载器」一体：给网页 URL，自己提取直链再下载。
* **aria2** 是纯下载器：只接受**直接媒体 URL**（直链），不做网页解析。

因此 aria2 引擎在本项目的角色是**加速下载后端**：

1. 平台适配器仍然用 yt-dlp 解析网页，拿到直链和元数据。
2. 对那些 ``item.extra["direct_url"]`` 存在的 item，aria2 引擎可以接手
   多线程分片下载（aria2 的多连接下载对大文件 / 慢源效果显著）。
3. 如果 item 没有直链，``supports()`` 返回 False，pipeline 自动回退到
   yt-dlp 引擎。

这意味着 aria2 引擎不会单独使用——它要么由 pipeline 按配置选择（此时
适配器需提前注入 ``direct_url``），要么根本不启用（默认）。

RPC 协议
--------

aria2 RPC 用 JSON-RPC 2.0 over HTTP。核心方法：

* ``aria2.addUri(uris, options)`` → 返回 GID（任务 ID）
* ``aria2.tellStatus(gid)`` → 查询进度（``completedLength`` / ``totalLength``）
* ``aria2.pause(gid)`` / ``aria2.unpause(gid)``
* ``aria2.remove(gid)`` → 删除任务（取消）

轮询 ``tellStatus`` 拿进度，``cancel_check`` 触发时 ``remove`` 任务。

测试策略
--------

RPC 客户端是注入的（``rpc_client`` 参数），测试用 Mock 客户端验证
``addUri`` 参数构造、进度轮询、取消逻辑，不需要真实 aria2 二进制。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional, Protocol

from ..core.models import DownloadOptions, MediaItem
from ..core.storage.file_layout import resolve_item_dir
from .base import Engine, EngineProgress, EngineProgressCallback

logger = logging.getLogger("doubi.engines.aria2")


#: aria2 RPC 默认地址。本机守护进程的标准端口。
DEFAULT_RPC_URL = "http://127.0.0.1:6800/jsonrpc"

#: 进度轮询间隔（秒）。aria2 的 ``tellStatus`` 很轻量，1 秒足够。
_POLL_INTERVAL = 1.0

#: aria2 任务终态。``complete`` 是成功，其余视为失败。
_TERMINAL_STATES = {"complete", "error", "removed"}


class Aria2RpcClient(Protocol):
    """aria2 JSON-RPC 客户端的最小协议。

    实现可以是真实的 ``aria2p`` / ``httpx`` 封装，测试用 Mock。
    所有方法都是 async——真实客户端内部用 ``asyncio.to_thread``
    包装同步调用即可。
    """

    async def add_uri(self, uris: list[str], options: dict) -> str:
        """``aria2.addUri``，返回 GID。"""
        ...

    async def tell_status(self, gid: str) -> dict:
        """``aria2.tellStatus``，返回状态字典。

        必含字段：``status``（active/waiting/complete/error/removed）、
        ``completedLength``（字符串字节数）、``totalLength``、
        ``errorCode`` / ``errorMessage``（失败时）。
        """
        ...

    async def remove(self, gid: str) -> None:
        """``aria2.remove``，取消任务。"""
        ...


class _HttpxAria2Client:
    """基于 ``httpx.AsyncClient`` 的真实 aria2 RPC 客户端。

    不依赖 ``aria2p`` 等第三方封装，直接发 JSON-RPC 请求。
    一个实例对应一个 aria2 守护进程。
    """

    def __init__(self, rpc_url: str, secret: Optional[str] = None):
        self._rpc_url = rpc_url
        # aria2 RPC token：``secret`` 前面要加 ``token:`` 前缀（aria2 协议规定）。
        self._token_param = [f"token:{secret}"] if secret else []
        self._client: Any = None

    async def _ensure_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def _call(self, method: str, params: list) -> Any:
        client = await self._ensure_client()
        resp = await client.post(
            self._rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": "doubi",
                "method": method,
                "params": self._token_param + params,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"aria2 RPC error: {data['error']}")
        return data.get("result")

    async def add_uri(self, uris: list[str], options: dict) -> str:
        return await self._call("aria2.addUri", [uris, options])

    async def tell_status(self, gid: str) -> dict:
        return await self._call("aria2.tellStatus", [gid])

    async def remove(self, gid: str) -> None:
        await self._call("aria2.remove", [gid])

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _parse_rate_limit(value: Optional[str]) -> Optional[str]:
    """``"5M"`` → aria2 的 ``"5M"``（单位兼容）。

    aria2 接受 ``K`` / ``M`` / ``G`` 后缀，和我们的配置格式一致，
    所以直接透传。``None`` 表示不限速。
    """
    if not value:
        return None
    return value.strip() or None


def _parse_byte_str(value: Any) -> int:
    """aria2 返回的字节数是字符串，转成 int。"""
    if value is None:
        return 0
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


class Aria2Engine(Engine):
    """aria2 多线程下载引擎。

    与 :class:`YtDlpEngine` 不同，aria2 不解析网页——它只下载
    ``item.extra["direct_url"]`` 指向的直链。没有直链的 item
    ``supports()`` 返回 False，pipeline 自动回退到 yt-dlp。

    典型用法是作为「加速后端」：yt-dlp 解析出直链后，把 item 交给
    aria2 引擎多线程下载。本引擎不取代 yt-dlp，而是补充它。
    """

    name = "aria2"

    def __init__(
        self,
        *,
        rpc_url: str = DEFAULT_RPC_URL,
        secret: Optional[str] = None,
        rpc_client: Optional[Aria2RpcClient] = None,
    ):
        self._rpc_url = rpc_url
        self._secret = secret
        # 注入客户端：测试用 Mock，生产用 _HttpxAria2Client。
        self._client = rpc_client

    async def _get_client(self) -> Aria2RpcClient:
        if self._client is None:
            self._client = _HttpxAria2Client(self._rpc_url, self._secret)
        return self._client

    def supports(self, item: MediaItem) -> bool:
        """只支持有 ``direct_url`` 的 item。

        直链来自 yt-dlp 解析阶段的 ``item.extra["direct_url"]``。
        没有直链的 item（网页 URL）交给 yt-dlp 引擎。
        """
        return bool(item.extra.get("direct_url") or item.source_url)

    def _build_options(self, item: MediaItem, options: DownloadOptions) -> dict:
        """构造 aria2 ``addUri`` 的 options 参数。"""
        out_dir = resolve_item_dir(item, options)
        # aria2 的 ``dir`` 是目标目录，``out`` 是文件名。
        # 不带扩展名——aria2 会按 URL 后缀或 ``--out`` 决定。
        base = item.output_template or options.filename_template or "{title}_{item_id}"
        # item.output_template 已渲染（pipeline 渲染过），直接用作文件名。
        filename = base.format(
            title=item.title or item.item_id,
            item_id=item.item_id,
        ) if "{" in base else base

        aria2_opts: dict[str, Any] = {
            "dir": str(out_dir),
            "out": filename,
            # 多连接下载：``split`` 是分片数，``max-connection-per-server`` 是
            # 对单服务器的并发连接数。两者都取 ``concurrent_fragments``。
            "split": str(max(1, options.concurrent_fragments)),
            "max-connection-per-server": str(max(1, options.concurrent_fragments)),
            # 续传：aria2 默认开，显式设上。
            "continue": "true" if options.resume else "false",
        }
        # 限速：直接透传 ``"5M"`` 格式。
        rate = _parse_rate_limit(options.rate_limit)
        if rate:
            aria2_opts["max-download-limit"] = rate
        # 代理：aria2 接受 ``http://host:port`` 格式。
        if options.proxy:
            aria2_opts["all-proxy"] = options.proxy
        # UA
        if options.user_agent:
            aria2_opts["user-agent"] = options.user_agent
        return aria2_opts

    async def download(
        self,
        item: MediaItem,
        options: DownloadOptions,
        *,
        on_progress: Optional[EngineProgressCallback] = None,
    ) -> bool:
        client = await self._get_client()

        # 直链优先从 extra 拿，回退到 source_url。
        direct_url = item.extra.get("direct_url") or item.source_url
        if not direct_url:
            logger.error("aria2: no direct_url for %s", item.item_id)
            return False

        # 预创建输出目录（aria2 不会自动建父目录）。
        try:
            resolve_item_dir(item, options).mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            logger.debug("aria2: pre-create output dir failed", exc_info=True)

        aria2_opts = self._build_options(item, options)
        try:
            gid = await client.add_uri([direct_url], aria2_opts)
        except Exception as exc:  # noqa: BLE001
            logger.error("aria2: addUri failed for %s: %s", item.source_url, exc)
            if on_progress is not None:
                on_progress(EngineProgress(
                    fraction=0.0, message=f"aria2 addUri error: {exc}",
                ))
            return False

        # 轮询进度直到终态或取消。
        cancel_check = options.cancel_check
        last_fraction = -1.0
        try:
            while True:
                if cancel_check is not None and cancel_check():
                    logger.info("aria2: cancelling %s (gid=%s)", item.item_id, gid)
                    try:
                        await client.remove(gid)
                    except Exception:  # noqa: BLE001
                        logger.debug("aria2: remove failed", exc_info=True)
                    if on_progress is not None:
                        on_progress(EngineProgress(
                            fraction=0.0, message="cancelled",
                            extra={"cancelled": True},
                        ))
                    return False

                status = await client.tell_status(gid)
                state = status.get("status", "")

                if state == "complete":
                    if on_progress is not None:
                        on_progress(EngineProgress(
                            fraction=1.0, message="aria2 download complete",
                        ))
                    return True

                if state in ("error", "removed"):
                    err_msg = status.get("errorMessage") or status.get("errorCode") or state
                    logger.error("aria2: %s failed: %s", item.item_id, err_msg)
                    if on_progress is not None:
                        on_progress(EngineProgress(
                            fraction=0.0, message=f"aria2 error: {err_msg}",
                        ))
                    return False

                # active / waiting → 上报进度
                total = _parse_byte_str(status.get("totalLength"))
                done = _parse_byte_str(status.get("completedLength"))
                if total > 0 and done is not None:
                    frac = max(0.0, min(1.0, done / total))
                    if frac - last_fraction >= 0.005 or frac >= 1.0:
                        last_fraction = frac
                        if on_progress is not None:
                            speed = _parse_byte_str(status.get("downloadSpeed"))
                            on_progress(EngineProgress(
                                fraction=frac,
                                message=f"aria2 {int(frac * 100)}%",
                                extra={"speed": speed},
                            ))

                await asyncio.sleep(_POLL_INTERVAL)
        except Exception as exc:  # noqa: BLE001
            logger.exception("aria2: polling failed for %s: %s", item.item_id, exc)
            # 尽力取消残留任务。
            try:
                await client.remove(gid)
            except Exception:  # noqa: BLE001
                pass
            if on_progress is not None:
                on_progress(EngineProgress(
                    fraction=0.0, message=f"aria2 error: {exc}",
                ))
            return False
