"""Platform registry — global lookup table for platform adapters.

Adapters self-register on import (see ``doubi.platforms.douyin.__init__``
etc.). The registry is intentionally a class with class-level state so
that ``doubi.core`` stays importable without triggering platform
package imports (avoiding the chicken-and-egg of ``platforms/__init__``
importing ``core``).
"""

from __future__ import annotations

import logging
import threading
from typing import Iterable, Optional

from .models import Platform

logger = logging.getLogger("doubi.core.registry")


def _install_adapter_annotation() -> None:
    """Bind ``PlatformAdapter`` into this module's globals, resolving the cycle.

    Why this is needed — same trap already documented in ``server/deps.py``:

    * ``from __future__ import annotations`` turns every annotation here into a
      plain string, so the name is never needed at import time;
    * once the string form is lazily evaluated later, it is resolved against
      this module's ``__globals__``. ``typing.get_type_hints()`` reads that
      dict directly, so a module-level ``__getattr__`` does **not** help.

    Without the binding, ``get_type_hints(PlatformRegistry.detect)`` raises
    ``NameError: name 'PlatformAdapter' is not defined``.

    A module-level ``from ..platforms.base import PlatformAdapter`` cannot be
    used: ``platforms/base.py`` imports this module so adapters can self-register,
    which makes that direction circular. Calling this at the *bottom* of the
    module runs after ``PlatformRegistry`` exists, at which point the import is
    safe — and if we are being imported *from* ``base.py``, ``sys.modules``
    already holds a partially-initialised entry whose ``PlatformAdapter`` is
    defined before it reaches its own import of us.
    """
    global PlatformAdapter
    from ..platforms.base import PlatformAdapter as _adapter

    PlatformAdapter = _adapter


class PlatformRegistry:
    """Thread-safe registry of platform adapters."""

    _lock = threading.RLock()
    _by_platform: dict[Platform, "PlatformAdapter"] = {}
    _by_name: dict[str, "PlatformAdapter"] = {}

    # ------------------------------------------------------------------ API

    @classmethod
    def register(cls, adapter: "PlatformAdapter") -> "PlatformAdapter":
        with cls._lock:
            existing = cls._by_platform.get(adapter.platform)
            if existing is not None and existing is not adapter:
                logger.debug(
                    "Replacing platform adapter for %s: %r -> %r",
                    adapter.platform, existing, adapter,
                )
            cls._by_platform[adapter.platform] = adapter
            cls._by_name[adapter.name] = adapter
            logger.info(
                "Registered platform adapter: %s (%s) -> %s",
                adapter.name, adapter.display_name, adapter.platform.value,
            )
            return adapter

    @classmethod
    def get(cls, platform: Platform) -> "PlatformAdapter":
        with cls._lock:
            adapter = cls._by_platform.get(platform)
        if adapter is None:
            raise KeyError(f"No adapter registered for platform: {platform!r}")
        return adapter

    @classmethod
    def get_by_name(cls, name: str) -> "PlatformAdapter":
        with cls._lock:
            adapter = cls._by_name.get(name)
        if adapter is None:
            raise KeyError(f"No adapter registered with name: {name!r}")
        return adapter

    @classmethod
    def all(cls) -> list["PlatformAdapter"]:
        with cls._lock:
            return list(cls._by_platform.values())

    @classmethod
    def detect(cls, url: str) -> Optional["PlatformAdapter"]:
        """Return the first adapter whose URL patterns match ``url``.

        Adapters are tried in descending :attr:`priority` order — generic
        兜底适配器（priority=-1, match_url 永真）排最后，确保 douyin /
        bilibili / youtube 等具体平台先匹配。
        """
        with cls._lock:
            adapters: Iterable = list(cls._by_platform.values())
        # 高 priority 先匹配；同 priority 保持注册顺序（stable sort）。
        adapters = sorted(adapters, key=lambda a: -a.priority)
        for adapter in adapters:
            try:
                if adapter.match_url(url):
                    return adapter
            except Exception:  # pragma: no cover - defensive
                logger.exception("match_url raised on %s", adapter)
        return None

    @classmethod
    def clear(cls) -> None:
        """Test helper — wipe all registered adapters."""
        with cls._lock:
            cls._by_platform.clear()
            cls._by_name.clear()

    @classmethod
    def __len__(cls) -> int:
        with cls._lock:
            return len(cls._by_platform)


# 在模块末尾绑定 ``PlatformAdapter``（见上方 ``_install_adapter_annotation``）。
#
# 必须放在这里而不是文件顶部：``platforms/base.py`` 会反向 import 本模块，
# 顶部绑定会构成循环导入。模块执行到这里时类已定义完毕，绑定是安全的。
#
# 失败不致命——真正的功能不依赖这个名字（注解本身是惰性的），受影响的只有
# 「显式内省注解」的调用方，而且仅限那些经 ``doubi.core`` 路径导入的场景。
# 因此这里吞掉 ImportError，不让一个纯类型层面的问题把核心模块拖崩。
try:
    _install_adapter_annotation()
except ImportError:  # pragma: no cover - 仅在平台包不可用时触发
    logger.debug("PlatformAdapter annotation binding skipped", exc_info=True)
