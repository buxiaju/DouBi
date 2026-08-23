"""Configuration loading.

DouBi uses a layered config (env > file > defaults) with YAML as the
on-disk format. This is intentionally minimal in M1 — we only need
enough to drive the CLI. The douyin-downloader's rich ``config.yml``
schema will be folded in during M2; Bili23's QSettings will be folded
in during M5.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import yaml  # type: ignore
    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False


#: 无显式路径时读取的默认配置文件。GUI 设置页写入的就是这个文件，
#: ``load_config(None)`` 会回退到它——否则写入的配置永远不会被读回。
DEFAULT_CONFIG_PATH: Path = Path.home() / ".doubi" / "config.yml"


DEFAULTS: dict[str, Any] = {
    "output_root": "./Downloaded",
    "output_dir_template": "{platform}/{author}/{media_type}",
    "concurrent_jobs": 3,
    "container": "mp4",
    "max_quality": "best",
    "write_thumbnail": False,
    "write_metadata_json": False,
    "write_nfo": False,
    "write_danmaku": False,
    "write_subtitles": False,
    "resume": True,
    "filename_template": "{title}_{item_id}",
    "rate_limit": None,
    "proxy": None,
    "database": True,
    "database_path": "doubi.db",
    "manifest_path": "download_manifest.jsonl",
    "theme": "default_light",
}


@dataclass
class AppConfig:
    """Resolved application configuration."""

    output_root: Path = Path(DEFAULTS["output_root"])
    output_dir_template: str = DEFAULTS["output_dir_template"]
    concurrent_jobs: int = DEFAULTS["concurrent_jobs"]
    container: str = DEFAULTS["container"]
    max_quality: str = DEFAULTS["max_quality"]
    write_thumbnail: bool = DEFAULTS["write_thumbnail"]
    write_metadata_json: bool = DEFAULTS["write_metadata_json"]
    write_nfo: bool = DEFAULTS["write_nfo"]
    write_danmaku: bool = DEFAULTS["write_danmaku"]
    write_subtitles: bool = DEFAULTS["write_subtitles"]
    resume: bool = DEFAULTS["resume"]
    filename_template: str = DEFAULTS["filename_template"]
    rate_limit: Optional[str] = DEFAULTS["rate_limit"]
    proxy: Optional[str] = DEFAULTS["proxy"]
    database: bool = DEFAULTS["database"]
    database_path: Path = Path(DEFAULTS["database_path"])
    manifest_path: Path = Path(DEFAULTS["manifest_path"])
    theme: str = DEFAULTS["theme"]
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["output_root"] = str(self.output_root)
        d["database_path"] = str(self.database_path)
        d["manifest_path"] = str(self.manifest_path)
        return d


def _coerce(value: Any, default: Any) -> Any:
    """Light coercion so the same defaults dict can drive a typed config."""
    if value is None:
        return default
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, Path):
        return Path(str(value))
    return value


def load_config(path: Optional[Path] = None, *, env_prefix: str = "DOUBI_") -> AppConfig:
    """Load config from YAML file and environment overrides.

    Resolution order (highest priority first):
        1. environment variables (``DOUBI_OUTPUT_DIR`` etc.)
        2. YAML file at ``path`` if given, else :data:`DEFAULT_CONFIG_PATH`
        3. built-in defaults
    """
    data: dict[str, Any] = dict(DEFAULTS)

    explicit = path is not None
    path = Path(path) if explicit else DEFAULT_CONFIG_PATH
    if path.exists() and _HAS_YAML:
        with path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if isinstance(loaded, dict):
            data.update({k: v for k, v in loaded.items() if v is not None})
    elif explicit and path.exists() and not _HAS_YAML:  # pragma: no cover
        raise RuntimeError(
            f"Config file {path} given but PyYAML is not installed. "
            "`pip install pyyaml`."
        )

    # Env overrides — only known keys
    env_keys = {
        "OUTPUT_ROOT": "output_root",
        "OUTPUT_DIR_TEMPLATE": "output_dir_template",
        "CONCURRENT_JOBS": "concurrent_jobs",
        "CONTAINER": "container",
        "MAX_QUALITY": "max_quality",
        "PROXY": "proxy",
        "RATE_LIMIT": "rate_limit",
        "DATABASE_PATH": "database_path",
        "MANIFEST_PATH": "manifest_path",
        "THEME": "theme",
    }
    for env_k, cfg_k in env_keys.items():
        v = os.environ.get(env_prefix + env_k)
        if v is not None and v != "":
            data[cfg_k] = _coerce(v, DEFAULTS[cfg_k])

    # Build typed config
    cfg = AppConfig(
        output_root=_coerce(data["output_root"], DEFAULTS["output_root"]),
        output_dir_template=str(data["output_dir_template"]),
        concurrent_jobs=_coerce(data["concurrent_jobs"], DEFAULTS["concurrent_jobs"]),
        container=str(data["container"]),
        max_quality=str(data["max_quality"]),
        write_thumbnail=_coerce(data["write_thumbnail"], DEFAULTS["write_thumbnail"]),
        write_metadata_json=_coerce(data["write_metadata_json"], DEFAULTS["write_metadata_json"]),
        write_nfo=_coerce(data["write_nfo"], DEFAULTS["write_nfo"]),
        write_danmaku=_coerce(data["write_danmaku"], DEFAULTS["write_danmaku"]),
        write_subtitles=_coerce(data["write_subtitles"], DEFAULTS["write_subtitles"]),
        resume=_coerce(data["resume"], DEFAULTS["resume"]),
        filename_template=str(data["filename_template"]),
        rate_limit=data["rate_limit"],
        proxy=data["proxy"],
        database=_coerce(data["database"], DEFAULTS["database"]),
        database_path=_coerce(data["database_path"], DEFAULTS["database_path"]),
        manifest_path=_coerce(data["manifest_path"], DEFAULTS["manifest_path"]),
        theme=str(data["theme"]),
    )
    return cfg
