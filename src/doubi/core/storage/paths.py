"""Default on-disk paths for DouBi runtime data (DB / manifest).

0.3.3 (P1-1) — move the defaults from CWD-relative (``doubi.db`` /
``download_manifest.jsonl``) into the user data home so that:

* installing/uninstalling via the NSIS installer no longer leaves a stale
  ``doubi.db`` next to ``doubi-gui.exe`` (the previous default caused
  the install-dir to grow by ~57 KB on every run, surviving uninstall);
* GUI users running from the Start Menu get a stable location that
  doesn't move whenever the installer changes.

The home is :data:`windows/.doubi` on every OS — a deliberate, cross-
platform choice rather than ``%APPDATA%`` / ``~/.local/share``, because
DouBi ships as a single-binary Windows-only product today and going
through ``Path.home() / ".doubi"`` keeps the path inspectable from both
GUI and CLI without an extra environment lookup.

Public surface:

* :func:`data_home` — the directory itself; created on demand.
* :func:`default_db_path` — ``<data_home>/doubi.db``.
* :func:`default_manifest_path` — ``<data_home>/download_manifest.jsonl``.
* :func:`migrate_legacy_relpath` — one-shot, best-effort migration of
  an existing CWD-relative ``doubi.db`` / ``download_manifest.jsonl``
  into the new home; runs silently on first start after the upgrade.

The functions accept an optional ``home`` and ``cwd`` so tests can run
in isolation without touching the real user home.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("doubi.core.storage.paths")

#: User data home directory. ``~/.doubi`` on every supported platform.
#: Not configurable on purpose: the whole point of 0.3.3's P1-1 is that
#: this is the one and only canonical location.
DATA_HOME_NAME = ".doubi"

#: Default database filename inside :data:`DATA_HOME_NAME`.
DB_FILENAME = "doubi.db"

#: Default manifest filename inside :data:`DATA_HOME_NAME`.
MANIFEST_FILENAME = "download_manifest.jsonl"


def data_home(home: Optional[Path] = None) -> Path:
    """Return (and create) the user data home directory.

    ``home`` is for tests; production callers leave it ``None`` and
    fall back to :func:`Path.home`.
    """
    base = Path(home) if home is not None else Path.home()
    target = base / DATA_HOME_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def default_db_path(home: Optional[Path] = None) -> Path:
    """Return the canonical database path (no filesystem side-effects beyond ``mkdir``)."""
    return data_home(home) / DB_FILENAME


def default_manifest_path(home: Optional[Path] = None) -> Path:
    """Return the canonical manifest path (no filesystem side-effects beyond ``mkdir``)."""
    return data_home(home) / MANIFEST_FILENAME


def _is_relative_basename(value: Path) -> bool:
    """True for the *old* default layout, where the path was a relative
    basename (``doubi.db`` / ``download_manifest.jsonl``) resolved
    against the CWD at the moment of use.

    We treat a path as "legacy" when:

    * it has no parent directory components (i.e. just a filename), or
    * the parent directory is exactly ``""`` / ``"."``.

    Anything absolute, or relative to a deeper folder (``./var/doubi.db``
    etc.), is **not** treated as the legacy default — the user picked
    that on purpose.
    """
    if value.is_absolute():
        return False
    parent = value.parent
    return parent == Path("") or parent == Path(".")


def migrate_legacy_relpath(
    *,
    target_db: Optional[Path] = None,
    target_manifest: Optional[Path] = None,
    cwd: Optional[Path] = None,
    home: Optional[Path] = None,
) -> list[str]:
    """Best-effort one-shot migration of legacy CWD-relative files.

    Walks the CWD looking for the two filenames used by 0.3.2 and
    earlier (``doubi.db``, ``download_manifest.jsonl``). When found
    *and* the canonical home does not yet have a copy, moves them
    silently into the canonical home. Existing canonical files are
    never overwritten — silent migration must not destroy data.

    Returns a list of human-readable ``"kind: source -> dest"``
    records for tests / observability. The function never raises;
    failures are logged and skipped so a broken migration cannot
    block application boot.
    """
    cwd = Path(cwd) if cwd is not None else Path(os.getcwd())
    target_db = (
        Path(target_db) if target_db is not None else default_db_path(home)
    )
    target_manifest = (
        Path(target_manifest) if target_manifest is not None
        else default_manifest_path(home)
    )

    moves: list[str] = []
    pairs = (
        (DB_FILENAME, target_db, "db"),
        (MANIFEST_FILENAME, target_manifest, "manifest"),
    )
    for filename, target, kind in pairs:
        legacy = cwd / filename
        if not legacy.exists():
            continue
        if target.exists():
            # Canonical home already has one — never overwrite.
            logger.info(
                "paths: skip %s migration, target already exists at %s",
                kind, target,
            )
            continue
        try:
            # Make sure the destination directory exists before shutil.move.
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(target))
            moves.append(f"{kind}: {legacy} -> {target}")
            logger.info("paths: migrated %s from %s to %s", kind, legacy, target)
        except OSError as exc:
            # Don't block boot on a migration hiccup.
            logger.warning(
                "paths: failed to migrate %s (%s -> %s): %s",
                kind, legacy, target, exc,
            )
    return moves


__all__ = [
    "DATA_HOME_NAME",
    "DB_FILENAME",
    "MANIFEST_FILENAME",
    "data_home",
    "default_db_path",
    "default_manifest_path",
    "migrate_legacy_relpath",
]