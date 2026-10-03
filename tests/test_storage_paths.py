"""0.3.3 P1-1: ``core.storage.paths`` + ``load_config`` default rewrite.

These tests pin the new canonical home (``~/.doubi/``), the silent
one-shot migration from the 0.3.2-era CWD-relative layout, and the
sentinel-rewrite path inside :func:`load_config` that lets tests monkey
patch ``Path.home`` without freezing the defaults at import time.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _patch_home(monkeypatch, tmp_path: Path) -> Path:
    # Route Path.home() to a per-test temp directory.
    #
    # On CPython 3.13 ``Path.home`` is a method defined on
    # ``pathlib._abc.PathBase`` and re-exported via ``Path``. Class-
    # level ``setattr(Path, "home", ...)`` does *not* override it
    # because the original lives on a parent class. Patching the
    # unbound function on ``PathBase`` works.
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    import pathlib._abc
    monkeypatch.setattr(
        pathlib._abc.PathBase, "home", classmethod(lambda cls: fake_home),
    )
    return fake_home


def test_data_home_creates_directory(tmp_path):
    from doubi.core.storage.paths import data_home

    out = data_home(tmp_path)
    assert out == tmp_path / ".doubi"
    assert out.is_dir()


def test_default_paths_resolve_into_data_home(tmp_path):
    from doubi.core.storage.paths import (
        default_db_path,
        default_manifest_path,
    )

    db = default_db_path(tmp_path)
    manifest = default_manifest_path(tmp_path)
    assert db == tmp_path / ".doubi" / "doubi.db"
    assert manifest == tmp_path / ".doubi" / "download_manifest.jsonl"
    assert db.parent.is_dir()
    assert manifest.parent.is_dir()


def test_migrate_legacy_relpath_moves_basename_files(tmp_path):
    from doubi.core.storage.paths import migrate_legacy_relpath

    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    legacy_db = cwd / "doubi.db"
    legacy_db.write_text("legacy-db", encoding="utf-8")
    legacy_manifest = cwd / "download_manifest.jsonl"
    legacy_manifest.write_text("{}\n", encoding="utf-8")

    moves = migrate_legacy_relpath(
        target_db=home / ".doubi" / "doubi.db",
        target_manifest=home / ".doubi" / "download_manifest.jsonl",
        cwd=cwd,
        home=home,
    )

    assert len(moves) == 2
    assert not legacy_db.exists()
    assert not legacy_manifest.exists()
    assert (home / ".doubi" / "doubi.db").read_text(encoding="utf-8") == "legacy-db"
    assert (home / ".doubi" / "download_manifest.jsonl").read_text(
        encoding="utf-8"
    ) == "{}\n"


def test_migrate_legacy_relpath_does_not_overwrite_existing(tmp_path):
    # Silent migration must never destroy a fresh canonical file.
    from doubi.core.storage.paths import migrate_legacy_relpath

    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    (cwd / "doubi.db").write_text("LEGACY", encoding="utf-8")
    canonical = home / ".doubi" / "doubi.db"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("CANONICAL", encoding="utf-8")

    moves = migrate_legacy_relpath(
        target_db=canonical,
        target_manifest=home / ".doubi" / "download_manifest.jsonl",
        cwd=cwd,
        home=home,
    )
    assert moves == []
    assert canonical.read_text(encoding="utf-8") == "CANONICAL"
    assert (cwd / "doubi.db").read_text(encoding="utf-8") == "LEGACY"


def test_migrate_legacy_relpath_skips_when_no_legacy(tmp_path):
    # A clean install must not move or create anything.
    from doubi.core.storage.paths import migrate_legacy_relpath

    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    moves = migrate_legacy_relpath(
        target_db=home / ".doubi" / "doubi.db",
        target_manifest=home / ".doubi" / "download_manifest.jsonl",
        cwd=cwd,
        home=home,
    )
    assert moves == []


def test_load_config_defaults_to_data_home(monkeypatch, tmp_path):
    # AppConfig() must point at ~/.doubi/; load_config also picks up
    # the canonical home when the file has no explicit override.
    from doubi.core.config import AppConfig, load_config
    from doubi.core.storage.paths import DATA_HOME_NAME

    fake_home = _patch_home(monkeypatch, tmp_path)
    cfg = AppConfig()
    expected_home = fake_home / DATA_HOME_NAME
    assert cfg.database_path == expected_home / "doubi.db"
    assert cfg.manifest_path == expected_home / "download_manifest.jsonl"
    assert cfg.database_path.is_absolute()
    assert cfg.manifest_path.is_absolute()

    # Also via load_config(cfg_path) where the YAML does NOT specify
    # database_path / manifest_path — sentinel rewrite must kick in.
    cfg_path = tmp_path / "minimal.yml"
    cfg_path.write_text("language: en\n", encoding="utf-8")
    loaded = load_config(cfg_path)
    assert loaded.database_path == expected_home / "doubi.db"
    assert loaded.manifest_path == expected_home / "download_manifest.jsonl"


def test_load_config_triggers_silent_migration(monkeypatch, tmp_path):
    # load_config should migrate the legacy CWD doubi.db once.
    from doubi.core.config import load_config
    from doubi.core.storage.paths import DATA_HOME_NAME

    fake_home = _patch_home(monkeypatch, tmp_path)
    # Use the explicit-config path so load_config does not touch the
    # real ``~/.doubi/config.yml`` (the test that precedes this one
    # creates ``fake_home/.doubi/`` via ``data_home()``; without the
    # explicit path the default config might pick up values left by
    # an earlier test in the same session).
    cfg_path = tmp_path / "isolated_config.yml"
    cfg_path.write_text("concurrent_jobs: 1\n", encoding="utf-8")

    cwd = tmp_path / "cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    legacy = cwd / "doubi.db"
    legacy.write_text("HISTORICAL", encoding="utf-8")

    # Switch into the cwd that holds the legacy file before triggering
    # load_config so migrate_legacy_relpath actually sees it.
    monkeypatch.chdir(cwd)

    cfg = load_config(cfg_path)
    canonical = fake_home / DATA_HOME_NAME / "doubi.db"
    assert not legacy.exists(), "legacy file should have been moved"
    assert canonical.read_text(encoding="utf-8") == "HISTORICAL"
    assert cfg.database_path == canonical


def test_load_config_preserves_explicit_relative_path(monkeypatch, tmp_path):
    # A user-configured "./var/doubi.db" must survive sentinel rewrite.
    from doubi.core.config import load_config

    _patch_home(monkeypatch, tmp_path)
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(
        "database_path: ./var/doubi.db\nmanifest_path: ./var/manifest.jsonl\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.database_path == Path("./var/doubi.db")
    assert cfg.manifest_path == Path("./var/manifest.jsonl")


def test_database_default_path_resolves_to_data_home(monkeypatch, tmp_path):
    # Database() with no arg should land in ~/.doubi/ too.
    from doubi.core.storage.database import Database
    from doubi.core.storage.paths import DATA_HOME_NAME

    fake_home = _patch_home(monkeypatch, tmp_path)
    db = Database()
    expected = fake_home / DATA_HOME_NAME / "doubi.db"
    assert db.db_path == expected