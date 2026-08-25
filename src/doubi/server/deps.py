"""FastAPI dependency wiring for token authentication.

为什么鉴权闸门要单独占一个模块，而不是写在 ``build_app()`` 里面：

1. ``app.py`` 顶部有 ``from __future__ import annotations``，所有函数注解都变成
   字符串；
2. ``fastapi`` 必须懒导入——没装 ``doubi[server]`` 时 ``import doubi.server``
   不能崩，所以 ``Request`` 只能在 ``build_app()`` 内部 import。

这两条单独看都对，凑在一起就出事：FastAPI 求值字符串注解时用的是
``get_type_hints(fn, fn.__globals__)``，只看**模块全局**命名空间。写在
``build_app()`` 里的依赖函数，其 ``"Request"`` 注解在 app.py 的全局里找不到，
FastAPI 于是放弃把它当请求对象，退化成一个名叫 ``request`` 的必填 query
参数——结果是所有挂了鉴权的路由一律 422，跟有没有 token 毫无关系。

放进本模块后，``Request`` 是模块级名字，注解能正常求值；而本模块自身仍然只
在 ``build_app()`` 内被 import，懒加载的性质一点没变。

真正的判定逻辑仍在 :mod:`doubi.server.security`（不依赖 fastapi，可独立测试），
这里只负责把它接到 HTTP 语义上：取头、比对、失败翻译成 401。
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from fastapi import HTTPException, Request

from .security import extract_request_token, token_matches

__all__ = ["make_token_guard"]


def make_token_guard(
    expected_token: Optional[str],
) -> Callable[[Request], Awaitable[None]]:
    """Build the auth dependency for one app instance.

    ``expected_token`` 为 ``None`` 时返回的闸门直接放行：此时服务只允许绑回环
    （见 :mod:`doubi.server.app` 模块 docstring），单机自用不该被迫填 token。

    用工厂而不是全局依赖，是为了让 token 随 app 实例走——同一个进程里可以有一
    个开鉴权的实例和一个不开的实例（测试就是这么用的），互不干扰。
    """

    async def require_token(request: Request) -> None:
        if expected_token is None:
            return
        provided = extract_request_token(request.headers)
        if not token_matches(expected_token, provided):
            # 401 而不是 403：语义是「你没证明自己是谁」，且必须带
            # WWW-Authenticate 头，客户端才知道该用哪种方案重试。
            raise HTTPException(
                status_code=401,
                detail="invalid or missing API token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return require_token
