"""REST 鉴权与监听地址安全审查——刻意不依赖 FastAPI。

放在独立模块而不是 :mod:`doubi.server.app` 里，有两个原因：

1. :func:`doubi.server.app.build_app` 把 fastapi / pydantic 做成惰性导入，
   目的是让没装 ``doubi[server]`` 的机器仍能 import 整个 doubi。鉴权逻辑
   如果写在 ``build_app`` 内部的闭包里，就只能靠起一个真实 app 才能测到，
   而那又要求装上可选依赖——安全相关的判断不该有这种测试门槛。
2. ``doubi serve``（CLI）和 :func:`doubi.server.app.main` 两条入口都要做
   同一套「绑到哪、要不要 token」的审查，共用一份实现才不会各写一遍然后
   逐渐跑偏。

安全模型（只有一句话）：**能被别的机器连上的端口，必须有 token。**

    绑回环 + 无 token → 放行。只有本机进程能连，这不叫敞口。
    任意地址 + 有 token → 放行，并记一条 warning 说明已对外暴露。
    非回环 + 无 token → 拒绝启动，除非调用方显式说了 allow_insecure。
"""

from __future__ import annotations

import ipaddress
import os
import secrets
from typing import Mapping, Optional

#: 提供 token 的环境变量。选环境变量而不是配置文件字段，是因为 token 属于
#: 凭据：``AppConfig`` 会被 GUI 设置页 ``to_dict()`` 整体写回
#: ``~/.doubi/config.yml``，凭据一旦进了那条链路就等于落盘明文，还会被
#: 用户随手分享配置文件时一起泄露。
TOKEN_ENV_VAR = "DOUBI_API_TOKEN"

#: 不是 IP 字面量、但确定指向本机的主机名。
_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})

#: ``Authorization: Bearer <token>`` 的前缀，按 RFC 6750 大小写不敏感比较。
_BEARER_PREFIX = "bearer "

#: 备用请求头。curl / 简单脚本里比拼 Bearer 串方便，语义与 Bearer 等价。
_TOKEN_HEADER = "x-api-token"


class InsecureBindingError(RuntimeError):
    """监听地址对外可达却没有任何鉴权，且调用方没有显式同意。"""


def generate_token(nbytes: int = 32) -> str:
    """生成一个可直接放进 URL / 请求头的随机 token。"""
    return secrets.token_urlsafe(nbytes)


def resolve_token(explicit: Optional[str] = None) -> Optional[str]:
    """定出本次运行实际生效的 token。

    优先级：显式参数 > 环境变量 > 无。

    空串一律视作「没有」：``DOUBI_API_TOKEN=`` 这种写法在 shell 里太常见，
    如果当成一个长度为 0 的合法 token，:func:`token_matches` 会对任何请求
    都比对成功，鉴权就形同虚设——这正是最危险的那种失败方式（看起来开了，
    实际全放行）。
    """
    if explicit:
        stripped = explicit.strip()
        if stripped:
            return stripped
    from_env = os.environ.get(TOKEN_ENV_VAR, "")
    stripped_env = from_env.strip()
    return stripped_env or None


def is_loopback(host: Optional[str]) -> bool:
    """判断 ``host`` 是否只有本机能连上。

    只在**确定**是本机时返回 True。所有拿不准的输入（解析不出的主机名、
    空串、``0.0.0.0``、``::``）都返回 False，这样审查会倒向「要求 token」
    而不是倒向放行。
    """
    h = (host or "").strip()
    if not h:
        # uvicorn 把空 host 当作监听全部网卡，等价于 0.0.0.0。
        return False
    if h.lower() in _LOOPBACK_NAMES:
        return True
    # IPv6 字面量在命令行里常带方括号（``[::1]``），ipaddress 不认。
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    # ``::1%lo0`` 这类带 scope id 的写法同样要先剥掉。
    if "%" in h:
        h = h.split("%", 1)[0]
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        # 是个主机名。这里刻意**不**做 DNS 解析：解析结果取决于运行时的
        # hosts / DNS，同一份配置在两台机器上能得出不同的安全结论，而
        # 「安全审查的结果不确定」本身就不可接受。当作对外暴露处理。
        return False


def extract_request_token(headers: Mapping[str, str]) -> Optional[str]:
    """从请求头里取出调用方提供的 token。

    支持 ``Authorization: Bearer <token>`` 与 ``X-API-Token: <token>``。

    刻意不支持从 query string 取 token：URL 会被 uvicorn 的 access log、
    反向代理日志、浏览器历史一路记下来，凭据放在那里等于长期泄露。

    ``headers`` 的键按小写查找——starlette 的 ``request.headers`` 转成 dict
    后就是小写键，标准 HTTP 头本身也大小写不敏感。
    """
    raw_auth = headers.get("authorization") or headers.get("Authorization") or ""
    if raw_auth[: len(_BEARER_PREFIX)].lower() == _BEARER_PREFIX:
        candidate = raw_auth[len(_BEARER_PREFIX):].strip()
        if candidate:
            return candidate
    fallback = headers.get(_TOKEN_HEADER) or headers.get("X-API-Token") or ""
    fallback = fallback.strip()
    return fallback or None


def token_matches(expected: Optional[str], provided: Optional[str]) -> bool:
    """常数时间比较两个 token。

    用 :func:`secrets.compare_digest` 而不是 ``==``：后者一旦发现首个不同
    字节就返回，耗时随「猜对了几位前缀」变化，攻击者可以据此逐字节爆破。

    ``expected`` 为 None 表示本次运行没开鉴权，由调用方决定语义，这里直接
    返回 False，不让「没配 token」意外变成「任何 token 都算对」。
    """
    if not expected or not provided:
        return False
    return secrets.compare_digest(expected, provided)


def audit_binding(
    host: Optional[str],
    *,
    token: Optional[str],
    allow_insecure: bool = False,
) -> Optional[str]:
    """启动前审查监听地址，返回需要记录的 warning（没有则返回 None）。

    返回字符串而不是自己写日志：调用方是 CLI 时该打到 stderr，是
    :func:`doubi.server.app.run_server` 时该走 logger，把输出方式留给调用方
    决定，这个函数才能在测试里被直接断言。

    Raises:
        InsecureBindingError: 地址对外可达、没有 token、且没有显式豁免。
    """
    if is_loopback(host):
        return None

    shown = host or "0.0.0.0"

    if token:
        return (
            f"REST 服务监听 {shown}，已对本机之外开放。token 鉴权已启用，"
            "但请确认这个端口不该直接暴露在公网上。"
        )

    if allow_insecure:
        return (
            f"REST 服务监听 {shown} 且**未启用任何鉴权**——任何能连上这个端口的人"
            "都可以让本机下载任意 URL 并写入磁盘。这是因为显式传了 "
            "--allow-insecure 才被允许的，仅可用于隔离网络内的临时调试。"
        )

    raise InsecureBindingError(
        f"拒绝启动：监听 {shown} 会让本机之外的人也能连上，而当前没有配置任何鉴权。\n"
        "任何能连上该端口的人都可以驱动本机下载任意 URL 并写入磁盘。\n"
        "\n"
        "三种解决办法，任选其一：\n"
        f"  1. 只给本机用（推荐）：去掉 --host，或写 --host 127.0.0.1\n"
        f"  2. 配置 token：设置环境变量 {TOKEN_ENV_VAR}，或传 --token <TOKEN>\n"
        f"     生成一个：python -c \"import secrets; print(secrets.token_urlsafe(32))\"\n"
        "  3. 明知风险仍要裸奔：加 --allow-insecure\n"
    )
