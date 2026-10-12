"""diagnostics 模块的纯函数测试——ci 口径能跑（不依赖 PySide6）。

覆盖：
    - redact_cookies：B 站 / 抖音敏感字段脱敏、其他字段保留
    - redact_config_yaml：proxy / secret / token 脱敏、注释行不动
    - collect_system_info：结构完整性
    - build_diagnostic_bundle：zip 写出 + 内容正确 + 脱敏落地
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

# 让 ``from doubi.core import diagnostics`` 能 import——和仓库里其他测试
# 一致。
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.diagnostics import (  # noqa: E402
    build_diagnostic_bundle,
    collect_system_info,
    redact_config_yaml,
    redact_cookies,
)


# ---------------------------------------------------------------------------
# redact_cookies
# ---------------------------------------------------------------------------


class TestRedactCookies:
    def test_bilibili_sensitive_redacted(self) -> None:
        text = (
            "# Netscape HTTP Cookie File\n"
            ".bilibili.com\tTRUE\t/\tFALSE\t1234567890\tSESSDATA\tabc123def\n"
            ".bilibili.com\tTRUE\t/\tFALSE\t1234567890\tbili_jct\tcs_token_xyz\n"
            ".bilibili.com\tTRUE\t/\tFALSE\t1234567890\tDedeUserID\t12345\n"
        )
        out = redact_cookies("bilibili", text)
        # 敏感字段被替换
        assert "abc123def" not in out
        assert "cs_token_xyz" not in out
        assert "<REDACTED-BILIBILI-SESSDATA>" in out
        assert "<REDACTED-BILIBILI-CS>" in out
        # 非敏感字段保留
        assert "12345" in out
        assert "DedeUserID" in out

    def test_douyin_sensitive_redacted(self) -> None:
        text = (
            "# Netscape HTTP Cookie File\n"
            ".douyin.com\tTRUE\t/\tFALSE\t1234567890\tsessionid\tsess_abc\n"
            ".douyin.com\tTRUE\t/\tFALSE\t1234567890\tsid_tt\tsid_xyz\n"
            ".douyin.com\tTRUE\t/\tFALSE\t1234567890\tuid_tt\t99999\n"
            ".douyin.com\tTRUE\t/\tFALSE\t1234567890\tttwid\ttwid_qq\n"
        )
        out = redact_cookies("douyin", text)
        # 敏感字段被替换
        assert "sess_abc" not in out
        assert "sid_xyz" not in out
        assert "<REDACTED-DOUYIN-SESSION>" in out
        assert "<REDACTED-DOUYIN-SID>" in out
        # uid_tt / ttwid 保留（对签名/排查有用）
        assert "99999" in out
        assert "twid_qq" in out

    def test_unknown_platform_passthrough(self) -> None:
        text = (
            ".example.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tabc\n"
        )
        out = redact_cookies("unknown_platform", text)
        # 未识别的平台：原样返回
        assert out == text

    def test_empty_input(self) -> None:
        assert redact_cookies("bilibili", "") == ""

    def test_malformed_lines_kept(self) -> None:
        # 列数不对的行：正则不会匹配，原样保留——避免误改
        text = "garbage line\n.bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tabc\n"
        out = redact_cookies("bilibili", text)
        assert "garbage line" in out
        assert "abc" not in out  # SESSDATA 仍然被脱敏


# ---------------------------------------------------------------------------
# redact_config_yaml
# ---------------------------------------------------------------------------


class TestRedactConfigYaml:
    def test_proxy_redacted(self) -> None:
        text = "proxy: http://user:pass@127.0.0.1:7890\n"
        out = redact_config_yaml(text)
        assert "127.0.0.1" not in out
        assert "user" not in out
        assert "<REDACTED>" in out
        # 字段名保留
        assert "proxy:" in out

    def test_aria2_secret_redacted(self) -> None:
        text = "aria2_secret: mysecret123\n"
        out = redact_config_yaml(text)
        assert "mysecret123" not in out
        assert "<REDACTED>" in out

    def test_safe_fields_kept(self) -> None:
        text = (
            "output_dir: /tmp/downloads\n"
            "concurrent: 4\n"
            "language: zh_CN\n"
        )
        out = redact_config_yaml(text)
        assert "/tmp/downloads" in out
        assert "4" in out
        assert "zh_CN" in out

    def test_comment_lines_kept(self) -> None:
        # 注释里的 proxy 字眼**不该**被改
        text = (
            "# proxy: http://127.0.0.1:7890\n"
            "proxy: http://127.0.0.1:7890\n"
        )
        out = redact_config_yaml(text)
        # 注释里的原值保留
        assert "# proxy: http://127.0.0.1:7890" in out
        # 实际字段被脱敏
        lines = [ln for ln in out.splitlines() if ln.startswith("proxy:")]
        assert "<REDACTED>" in lines[0]
        assert "127.0.0.1" not in lines[0]

    def test_indented_field_redacted(self) -> None:
        # YAML 嵌套格式
        text = (
            "network:\n"
            "  proxy: http://1.2.3.4:7890\n"
            "  timeout: 30\n"
        )
        out = redact_config_yaml(text)
        assert "1.2.3.4" not in out
        assert "30" in out  # timeout 不脱敏


# ---------------------------------------------------------------------------
# collect_system_info
# ---------------------------------------------------------------------------


class TestCollectSystemInfo:
    def test_contains_required_keys(self) -> None:
        info = collect_system_info()
        assert "doubi_version" in info
        assert "python" in info
        assert "platform" in info
        assert "captured_at" in info

    def test_python_keys(self) -> None:
        info = collect_system_info()
        assert "version" in info["python"]
        assert "implementation" in info["python"]

    def test_platform_keys(self) -> None:
        info = collect_system_info()
        for key in ("system", "release", "version", "machine"):
            assert key in info["platform"]

    def test_captured_at_is_iso(self) -> None:
        info = collect_system_info()
        # ISO 8601 格式可以含 +00:00 或 Z
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", info["captured_at"])


# ---------------------------------------------------------------------------
# build_diagnostic_bundle
# ---------------------------------------------------------------------------


class TestBuildDiagnosticBundle:
    def test_writes_zip_to_output(self, tmp_path: Path) -> None:
        home = tmp_path / ".doubi"
        home.mkdir()
        out = tmp_path / "diag.zip"
        result = build_diagnostic_bundle(out, home_dir=home)
        assert result == out
        assert out.is_file()
        assert zipfile.is_zipfile(out)

    def test_includes_bundle_json(self, tmp_path: Path) -> None:
        home = tmp_path / ".doubi"
        home.mkdir()
        out = tmp_path / "diag.zip"
        build_diagnostic_bundle(out, home_dir=home)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert "bundle.json" in names
            bundle = json.loads(zf.read("bundle.json"))
            assert "system" in bundle
            assert "doubi_version" in bundle["system"]
            assert "files" in bundle

    def test_redacts_config(self, tmp_path: Path) -> None:
        home = tmp_path / ".doubi"
        home.mkdir()
        (home / "config.yml").write_text(
            "output_dir: /tmp\nproxy: http://user@1.2.3.4:7890\n",
            encoding="utf-8",
        )
        out = tmp_path / "diag.zip"
        build_diagnostic_bundle(out, home_dir=home)
        with zipfile.ZipFile(out) as zf:
            config_text = zf.read("config.yml.redacted").decode("utf-8")
            assert "/tmp" in config_text  # 安全字段保留
            assert "1.2.3.4" not in config_text
            assert "<REDACTED>" in config_text

    def test_redacts_cookies(self, tmp_path: Path) -> None:
        home = tmp_path / ".doubi"
        home.mkdir()
        (home / "cookies").mkdir()
        (home / "cookies" / "bilibili.txt").write_text(
            ".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tabc123\n",
            encoding="utf-8",
        )
        out = tmp_path / "diag.zip"
        build_diagnostic_bundle(out, home_dir=home)
        with zipfile.ZipFile(out) as zf:
            cookie_text = zf.read("cookies/bilibili.txt.redacted").decode("utf-8")
            assert "abc123" not in cookie_text
            assert "<REDACTED-BILIBILI-SESSDATA>" in cookie_text

    def test_includes_recent_logs(self, tmp_path: Path) -> None:
        home = tmp_path / ".doubi"
        home.mkdir()
        (home / "logs").mkdir()
        for i in range(3):
            (home / "logs" / f"doubi-{i}.log").write_text(
                f"log {i}", encoding="utf-8"
            )
        out = tmp_path / "diag.zip"
        build_diagnostic_bundle(out, home_dir=home, max_log_files=2)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            # 只收 2 个最近的
            log_names = [n for n in names if n.startswith("logs/")]
            assert len(log_names) == 2

    def test_db_meta_only(self, tmp_path: Path) -> None:
        """doubi.db 不含内容——只记路径 + 大小。"""
        home = tmp_path / ".doubi"
        home.mkdir()
        (home / "doubi.db").write_bytes(b"fake db content with URL https://x")
        out = tmp_path / "diag.zip"
        build_diagnostic_bundle(out, home_dir=home)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            # 不应该有 doubi.db 这个文件
            assert "doubi.db" not in names
            # 但 bundle.json 里应该有 meta
            bundle = json.loads(zf.read("bundle.json"))
            assert "doubi.db.meta" in bundle["files"]
            assert bundle["files"]["doubi.db.meta"]["size_bytes"] > 0
            assert "https://x" not in json.dumps(bundle)  # 内容不进 meta

    def test_empty_home(self, tmp_path: Path) -> None:
        """~/.doubi/ 啥都没有——也能写出一个 zip（只有 bundle.json）。"""
        home = tmp_path / ".doubi"
        home.mkdir()
        out = tmp_path / "diag.zip"
        build_diagnostic_bundle(out, home_dir=home)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert "bundle.json" in names
            assert len(names) == 1  # 只有 bundle.json

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "deep" / "nested" / "diag.zip"
        home = tmp_path / ".doubi"
        home.mkdir()
        build_diagnostic_bundle(out, home_dir=home)
        assert out.is_file()
