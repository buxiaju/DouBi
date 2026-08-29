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
    # GUI 行为偏好：下载前是否弹出选项对话框让用户覆盖画质/容器等。
    # 默认 False 是有意为之——绝大多数下载用户就是「点一下就走」。
    "prompt_before_download": False,
    # 重复下载策略：skip（跳过）/ redownload（重新下载）/ ask（询问）
    "duplicate_policy": "skip",
    # UI 语言。空串/未知值回退到 zh_CN。GUI 切换后需重启生效。
    "language": "zh_CN",
    # 下载引擎：yt-dlp（默认）/ aria2。aria2 需要 aria2 守护进程运行。
    "engine": "yt-dlp",
    # aria2 RPC 地址。aria2 守护进程的 JSON-RPC 端点。
    "aria2_rpc_url": "http://127.0.0.1:6800/jsonrpc",
    # aria2 RPC secret token（可选）。
    "aria2_secret": None,
    # ---- 通用嗅探（generic adapter） ----
    # 详见 docs/superpowers/specs/2026-08-25-generic-sniffer-design.md
    "sniff_enabled": True,              # 关掉后 generic 兜底直接返回提示，不起浏览器
    "sniff_duration_sec": 15,            # 嗅探时长 5–60 秒
    "sniff_headless": True,             # 后台跑无头浏览器
    "sniff_user_agent": "",             # 空串用 Playwright 默认 UA
    "sniff_auto_play": True,            # 自动调 video.play() 触发 m3u8 加载
    "sniff_capture_types": (            # network response 拦截的 MIME 白名单
        "video/mp4", "video/webm", "video/mp2t",
        "application/vnd.apple.mpegurl",
        "application/dash+xml",
    ),
    # ---- 系统通知（Windows toast via QSystemTrayIcon） ----
    # 下载完成后是否弹通知。三个值：
    #   "success"  — 只在「成功」时弹（推荐：失败有 GUI 弹窗，不重）
    #   "all"      — 成功 + 失败都弹（多任务并发走完一眼看结果）
    #   "summary"  — 单个任务静默；队列全部跑完时弹一次汇总（N 项完成 / M 项失败）
    "notify_on_completion": "success",
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
    prompt_before_download: bool = DEFAULTS["prompt_before_download"]
    duplicate_policy: str = DEFAULTS["duplicate_policy"]
    language: str = DEFAULTS["language"]
    engine: str = DEFAULTS["engine"]
    aria2_rpc_url: str = DEFAULTS["aria2_rpc_url"]
    aria2_secret: Optional[str] = DEFAULTS["aria2_secret"]
    # ---- 通用嗅探（generic adapter） ----
    sniff_enabled: bool = DEFAULTS["sniff_enabled"]
    sniff_duration_sec: int = DEFAULTS["sniff_duration_sec"]
    sniff_headless: bool = DEFAULTS["sniff_headless"]
    sniff_user_agent: str = DEFAULTS["sniff_user_agent"]
    sniff_auto_play: bool = DEFAULTS["sniff_auto_play"]
    sniff_capture_types: tuple[str, ...] = DEFAULTS["sniff_capture_types"]
    # 系统通知范围。允许值见 ``DEFAULTS["notify_on_completion"]`` 注释。
    notify_on_completion: str = DEFAULTS["notify_on_completion"]
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["output_root"] = str(self.output_root)
        d["database_path"] = str(self.database_path)
        d["manifest_path"] = str(self.manifest_path)
        return d


def _validate_notify_mode(value: Any) -> str:
    """Whitelist the ``notify_on_completion`` setting.

    Anything outside ``{"success", "all", "summary"}`` falls back to
    the default (``"success"``). A bad value in ``config.yml`` should
    never break the app boot path — the worst case is "user doesn't
    get notifications", which is recoverable on the settings page.
    """
    if isinstance(value, str) and value in {"success", "all", "summary"}:
        return value
    return DEFAULTS["notify_on_completion"]


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
        prompt_before_download=_coerce(
            data.get("prompt_before_download", DEFAULTS["prompt_before_download"]),
            DEFAULTS["prompt_before_download"],
        ),
        duplicate_policy=str(data.get("duplicate_policy", DEFAULTS["duplicate_policy"])),
        language=str(data.get("language", DEFAULTS["language"])),
        engine=str(data.get("engine", DEFAULTS["engine"])),
        aria2_rpc_url=str(data.get("aria2_rpc_url", DEFAULTS["aria2_rpc_url"])),
        aria2_secret=data.get("aria2_secret", DEFAULTS["aria2_secret"]),
        sniff_enabled=_coerce(
            data.get("sniff_enabled", DEFAULTS["sniff_enabled"]),
            DEFAULTS["sniff_enabled"],
        ),
        sniff_duration_sec=_coerce(
            data.get("sniff_duration_sec", DEFAULTS["sniff_duration_sec"]),
            DEFAULTS["sniff_duration_sec"],
        ),
        sniff_headless=_coerce(
            data.get("sniff_headless", DEFAULTS["sniff_headless"]),
            DEFAULTS["sniff_headless"],
        ),
        sniff_user_agent=str(data.get("sniff_user_agent", DEFAULTS["sniff_user_agent"])),
        sniff_auto_play=_coerce(
            data.get("sniff_auto_play", DEFAULTS["sniff_auto_play"]),
            DEFAULTS["sniff_auto_play"],
        ),
        sniff_capture_types=tuple(data.get("sniff_capture_types", DEFAULTS["sniff_capture_types"])),
        notify_on_completion=_validate_notify_mode(
            data.get("notify_on_completion", DEFAULTS["notify_on_completion"]),
        ),
    )
    return cfg
