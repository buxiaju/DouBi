"""诊断包生成器 —— 用户报 bug 时一键导出脱敏后的关键数据。

**目标**：用户在「设置 → 诊断」点「导出诊断包」，
    选个位置保存成 zip，附给作者 / 贴到 GitHub Issue。
    zip 内容是脱敏后的 ``~/.doubi/`` 关键文件 + 系统信息 + 最近 N 个日志。

**脱敏**：

- **Cookie**：按平台清单替换敏感字段值（B 站 ``SESSDATA`` / ``bili_jct``、
  抖音 ``sessionid`` / ``sessionid_ss`` / ``sid_tt`` / ``sid_guard``），
  其他字段保留（``DedeUserID``、``uid_tt``、``ttwid`` 等不脱敏）——
  它们是平台签名必带的字段，**对排查"搜索 0 行"等真问题有用**。
- **config.yml**：代理地址、aria2 secret、rest token 等字段值替换为 ``<REDACTED>``。

**不收集**：``doubi.db``、``download_manifest.jsonl`` 的**内容**——
它们含历史 URL / 视频元数据，**只记录文件大小和路径**，
让作者按需索取。

**测试**：`tests/test_diagnostics.py`，纯函数测试，ci 口径能跑（不需要 PySide6）。

**设计原则**：本模块**不依赖** GUI / 网络。所有 Qt / 文件对话框逻辑在
``ui/pages/settings.py`` 里——本模块只负责"给个 zip 路径，吐出 zip"。
"""

from __future__ import annotations

import json
import logging
import platform
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 敏感字段配置
# ---------------------------------------------------------------------------

# 平台 → 字段名 → 脱敏占位符。
# 字段名 = Netscape cookies 文件第 6 列；占位符 = 替换成什么。
_SENSITIVE_COOKIE_FIELDS: dict[str, dict[str, str]] = {
    "bilibili": {
        "SESSDATA": "<REDACTED-BILIBILI-SESSDATA>",
        "bili_jct": "<REDACTED-BILIBILI-CS>",
    },
    "douyin": {
        "sessionid": "<REDACTED-DOUYIN-SESSION>",
        "sessionid_ss": "<REDACTED-DOUYIN-SESSION>",
        "sid_tt": "<REDACTED-DOUYIN-SID>",
        "sid_guard": "<REDACTED-DOUYIN-SID>",
    },
}

# config.yml 敏感字段（替换值为 <REDACTED>）。
# 命名匹配 ``field: value`` 或 ``field=value``，只换值。
_SENSITIVE_CONFIG_FIELDS: frozenset[str] = frozenset(
    {
        "proxy",
        "aria2_secret",
        "rest_token",
    }
)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _read_text_safely(path: Path) -> str | None:
    """读文本；失败（含 OSError / 编码错误）只 log，不抛。"""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("diagnostics: failed to read %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# 脱敏
# ---------------------------------------------------------------------------


def redact_cookies(platform_name: str, cookies_text: str) -> str:
    """对一份 Netscape cookies 文本脱敏——把指定平台的敏感字段值替换成占位符。

    Netscape 格式::

        domain<TAB>flag<TAB>path<TAB>secure<TAB>expiry<TAB>name<TAB>value

    匹配规则：以 ``name`` 开头的一行（行首可有空格 / TAB），把第 7 列
    （value）替换为占位符。其他字段（uid、ttwid 等）保留。

    未识别的平台不脱敏。
    """
    fields = _SENSITIVE_COOKIE_FIELDS.get(platform_name, {})
    out = cookies_text
    for name, placeholder in fields.items():
        # Netscape 7 列：domain TAB flag TAB path TAB secure TAB expiry TAB name TAB value
        # 用 (?:\S+\t){5} 跳过前 5 列（domain→expiry），字面量匹配 name 列，
        # 然后抓第 7 列 value 替换为占位符。
        # **不**碰 name 列的字符——name 本身不敏感，但保留能让 diff 可读。
        pattern = re.compile(
            rf"^((?:\S+\t){{5}}){re.escape(name)}\t\S+",
            re.MULTILINE,
        )
        out = pattern.sub(lambda m: m.group(1) + f"{name}\t{placeholder}", out)
    return out


def redact_config_yaml(yaml_text: str) -> str:
    """对一份 config.yml 文本脱敏——把代理 / secret / token 类字段值替换为占位符。

    匹配 ``name: value`` 或 ``name=value``（前面可有缩进 / TAB），**只换值**。
    注释行（``#`` 开头）不动。
    """
    out = yaml_text
    for name in _SENSITIVE_CONFIG_FIELDS:
        # 匹配 `field:` 或 `field =` 形式（前面可有缩进），但**不**碰注释行
        # —— 注释行以 # 开头，所以正向匹配 `\n` 之后到行尾不算注释。
        pattern = re.compile(
            rf"(^[\t ]*{re.escape(name)}[\t ]*[:=][\t ]*)([^\n#]+)",
            re.MULTILINE,
        )
        out = pattern.sub(lambda m: m.group(1) + "<REDACTED>", out)
    return out


# ---------------------------------------------------------------------------
# 系统信息
# ---------------------------------------------------------------------------


def collect_system_info() -> dict[str, Any]:
    """收集系统 / Python / DouBi 自身的元信息。"""
    # 延后 import：避免 core 顶层 import 整个 doubi 包（__init__ 在 tools 里
    # 可能会做副作用）。绝对路径从 doubi 直接拿 __version__，不在 core/__init__
    # 里放。
    from doubi import __version__

    return {
        "captured_at": datetime.now(tz=timezone.utc).isoformat(),
        "doubi_version": __version__,
        "python": {
            "version": sys.version.split()[0],  # "3.10.11" 短版本
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
    }


# ---------------------------------------------------------------------------
# 打包
# ---------------------------------------------------------------------------


def build_diagnostic_bundle(
    output_path: Path,
    *,
    home_dir: Path | None = None,
    max_log_files: int = 5,
) -> Path:
    """把 ``~/.doubi/`` 关键文件 + 系统信息 + 脱敏后 打包成 zip。

    Parameters
    ----------
    output_path:
        输出的 zip 路径（含文件名）。父目录不存在会被创建。
    home_dir:
        DouBi 配置根目录；默认 ``~/.doubi``。**测试时**用 tmp_path 传假 home。
    max_log_files:
        收多少个最近 log 文件（按 mtime 倒序）。默认 5 个。

    Returns
    -------
    Path
        写出的 zip 文件路径（即 ``output_path`` 的 resolve 后版本）。
    """
    home = (home_dir or Path.home() / ".doubi").resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bundle: dict[str, Any] = {
        "system": collect_system_info(),
        "files": {},  # name -> str（文件原内容）或 dict（仅元信息）
    }

    # ---- config.yml（脱敏）----
    cfg = home / "config.yml"
    if cfg.is_file():
        text = _read_text_safely(cfg)
        if text is not None:
            bundle["files"]["config.yml.redacted"] = redact_config_yaml(text)

    # ---- cookies/<platform>.txt（脱敏）----
    for platform_name in _SENSITIVE_COOKIE_FIELDS:
        cookie_path = home / "cookies" / f"{platform_name}.txt"
        if cookie_path.is_file():
            text = _read_text_safely(cookie_path)
            if text is not None:
                bundle["files"][f"cookies/{platform_name}.txt.redacted"] = redact_cookies(
                    platform_name, text
                )

    # ---- doubi.db（只记路径 + 大小，不含内容）----
    db = home / "doubi.db"
    if db.is_file():
        bundle["files"]["doubi.db.meta"] = {
            "path": str(db),
            "size_bytes": db.stat().st_size,
        }

    # ---- download_manifest.jsonl（同上）----
    manifest = home / "download_manifest.jsonl"
    if manifest.is_file():
        bundle["files"]["download_manifest.jsonl.meta"] = {
            "path": str(manifest),
            "size_bytes": manifest.stat().st_size,
        }

    # ---- logs/（最近 N 个文件，原样收）----
    logs_dir = home / "logs"
    if logs_dir.is_dir():
        log_files = sorted(
            logs_dir.glob("*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:max_log_files]
        for log_file in log_files:
            text = _read_text_safely(log_file)
            if text is not None:
                bundle["files"][f"logs/{log_file.name}"] = text

    # ---- 写出 zip ----
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # bundle.json —— 整体结构（系统信息 + 文件清单的索引）
        zf.writestr(
            "bundle.json",
            json.dumps(bundle, indent=2, ensure_ascii=False),
        )
        # 单独的文件按原文件名存
        for name, content in bundle["files"].items():
            if isinstance(content, str):
                zf.writestr(name, content)
            # dict（meta）已经在 bundle.json 里——不重复写出

    logger.info("diagnostics: bundle written to %s", output_path)
    return output_path
