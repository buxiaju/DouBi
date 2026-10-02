"""Lock the annotation-evaluability contract of ``doubi.core.registry``.

背景（发版前体检发现的真实缺陷）：

``from __future__ import annotations`` 把所有注解变成字符串，因此导入期
永远不需要 ``PlatformAdapter`` 这个名字存在——这也是 ``registry.py`` 一直
没 import 它的原因（``platforms/base.py`` 反向依赖 registry，顶层导入会
构成循环）。

但字符串注解**一旦被显式求值**就会去本模块的 ``__globals__`` 里找名字。
``typing.get_type_hints()`` 读的就是那个 dict，所以：

* 模块级 ``__getattr__``（PEP 562）**帮不上忙**——它不参与 dict 查找；
* 缺失名字时抛 ``NameError``，而不是安静降级。

这个坑项目里已经踩过一次，根因写在 ``server/deps.py`` 的 docstring 里
（FastAPI 用 ``get_type_hints(fn, fn.__globals__)`` 求值依赖函数注解，
找不到 ``Request`` 就退化成必填 query 参数，导致所有鉴权路由 422）。

修法是在 ``registry.py`` 模块末尾调用 ``_install_adapter_annotation()``
把 ``PlatformAdapter`` 绑定进模块 globals——那时类已定义完毕，循环导入
已解除。下面的用例锁住这个行为，防止有人「清理未使用导入」时把它删掉。
"""

from __future__ import annotations

import sys
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.registry import PlatformRegistry  # noqa: E402


def test_adapter_annotation_is_bound_into_module_globals():
    """``PlatformAdapter`` 必须能在 registry 的模块 globals 里查到。

    这是 ``get_type_hints()`` 能工作的前提——它直读 ``__globals__``。
    """
    import doubi.core.registry as registry_module

    assert hasattr(registry_module, "PlatformAdapter"), (
        "registry 模块 globals 里没有 PlatformAdapter。"
        "若刚删过「未使用」的名字，请恢复模块末尾的 _install_adapter_annotation() 调用。"
    )


def test_get_type_hints_resolves_registry_methods():
    """registry 的公开方法注解必须能被 ``get_type_hints()`` 求值。

    回归的是 ``NameError: name 'PlatformAdapter' is not defined``。
    """
    for name in ("register", "detect", "all", "get", "get_by_name"):
        method = getattr(PlatformRegistry, name)
        hints = typing.get_type_hints(method)  # 求值失败会抛 NameError
        assert hints, f"{name} 解析出的注解为空"


def test_registry_still_functional_after_binding():
    """绑定注解不能破坏注册表本身——导入平台包后适配器应正常自注册。"""
    import doubi.platforms  # noqa: F401  —— 触发自注册

    names = {a.name for a in PlatformRegistry.all()}
    for expected in ("douyin", "bilibili", "youtube"):
        assert expected in names, f"{expected} 未注册：{sorted(names)}"


def test_module_level_getattr_cannot_satisfy_get_type_hints():
    """记录一个反直觉事实：模块级 ``__getattr__`` 救不了 ``get_type_hints``。

    这条不是在测产品代码，而是把「为什么必须做运行期绑定、而不能用
    PEP 562 的 ``__getattr__``」这一判断固化成可执行的证据——否则下一个人
    很可能用 ``__getattr__`` 重写一遍，看着优雅却完全不生效。
    """
    import types

    probe = types.ModuleType("probe")
    exec(  # noqa: S102 - 测试内部的受控构造
        "def __getattr__(name):\n"
        "    if name == 'Missing':\n"
        "        return int\n"
        "    raise AttributeError(name)\n",
        probe.__dict__,
    )
    # getattr 能拿到（走 __getattr__）
    assert getattr(probe, "Missing") is int
    # 但 globals 字典里没有 —— 而 get_type_hints 查的是这个
    assert "Missing" not in vars(probe)
