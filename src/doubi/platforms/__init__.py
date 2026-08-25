"""Platform adapters.

Each adapter knows how to recognize, parse, and post-process URLs for a
specific platform. Importing this package also triggers registration of
all built-in adapters into ``doubi.core.registry.PlatformRegistry``.
"""

from __future__ import annotations

from . import bilibili  # noqa: F401  (side-effect: register adapter)
from . import douyin    # noqa: F401  (side-effect: register adapter)
from . import generic   # noqa: F401  (side-effect: register adapter; priority=-1 兜底)
from . import youtube   # noqa: F401  (side-effect: register adapter)
from .base import PlatformAdapter

__all__ = ["PlatformAdapter"]
