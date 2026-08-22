"""Logging setup for DouBi.

We standardize on a single ``setup_logger()`` entrypoint so CLI, REST,
and any library consumer can produce consistent output. The default
format is a compact single-line layout; verbose mode adds module /
lineno for debugging.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Final

_DEFAULT_FORMAT: Final = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
_VERBOSE_FORMAT: Final = "%(asctime)s %(levelname)-7s [%(name)s] %(filename)s:%(lineno)d | %(message)s"

_configured = False


def setup_logger(level: str | int = "INFO", verbose: bool = False, force: bool = False) -> None:
    """Configure the root logger for DouBi.

    Idempotent unless ``force=True``. Subsequent calls only adjust the
    level / formatter.
    """
    global _configured

    root = logging.getLogger("doubi")
    if _configured and not force:
        _apply_level(root, level, verbose)
        return

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_VERBOSE_FORMAT if verbose else _DEFAULT_FORMAT))
    root.addHandler(handler)
    root.propagate = False
    _apply_level(root, level, verbose)
    _configured = True


def _apply_level(root: logging.Logger, level: str | int, verbose: bool) -> None:
    if isinstance(level, str):
        numeric = logging.getLevelName(level.upper())
        if not isinstance(numeric, int):
            numeric = logging.INFO
    else:
        numeric = level
    if verbose:
        numeric = min(numeric, logging.DEBUG)
    root.setLevel(numeric)
    for h in root.handlers:
        h.setFormatter(logging.Formatter(_VERBOSE_FORMAT if verbose else _DEFAULT_FORMAT))


def get_logger(name: str) -> logging.Logger:
    """Shortcut for ``logging.getLogger("doubi." + name)``."""
    if not name.startswith("doubi"):
        name = f"doubi.{name}"
    return logging.getLogger(name)


def quiet_external_loggers() -> None:
    """Silence chatty third-party loggers (httpx, aiohttp, urllib3)."""
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# Honor ``DOUBI_LOG_LEVEL`` so users can flip verbosity without code changes.
_env_level = os.environ.get("DOUBI_LOG_LEVEL")
if _env_level:
    setup_logger(_env_level, verbose=_env_level.upper() == "DEBUG")
