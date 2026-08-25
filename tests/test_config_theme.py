"""主题持久化与配置地基的回归测试。

这些测试全部不依赖 PySide6：``doubi.ui.theme`` 的解析逻辑与 token 表是
纯数据，Qt 调用只在 :func:`set_theme` 内部按需 import。

覆盖三类此前真实存在的缺陷：
  * 设置页保存用 ``asdict()`` 导致 ``yaml.safe_dump`` 抛 RepresenterError
  * ``load_config(None)`` 从不读配置文件，GUI 写进去的值永远读不回来
  * 主题名没有持久化字段
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core import config as config_mod  # noqa: E402
from doubi.core.config import AppConfig, load_config  # noqa: E402
from doubi.ui import theme as theme_mod  # noqa: E402


pytestmark = pytest.mark.gui


# ---------------------------------------------------------------------------
# 保存路径：to_dict() 必须是 yaml.safe_dump 可表示的
# ---------------------------------------------------------------------------


def test_to_dict_is_yaml_safe_dumpable():
    """曾经的 bug：asdict() 保留 Path 对象，safe_dump 直接抛异常。"""
    cfg = load_config(None)
    text = yaml.safe_dump(cfg.to_dict(), allow_unicode=True, sort_keys=False)
    assert isinstance(text, str)
    assert "theme" in text


def test_to_dict_stringifies_paths():
    cfg = AppConfig()
    data = cfg.to_dict()
    for key in ("output_root", "database_path", "manifest_path"):
        assert isinstance(data[key], str), f"{key} 应该已被转成字符串"


# ---------------------------------------------------------------------------
# 读取路径：load_config(None) 要回退到默认配置文件
# ---------------------------------------------------------------------------


def test_load_config_none_reads_default_path(tmp_path, monkeypatch):
    """曾经的 bug：path is None 时完全跳过文件读取。"""
    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text(
        yaml.safe_dump({"theme": "deep_sea", "max_quality": "720p"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", cfg_file)
    monkeypatch.delenv("DOUBI_THEME", raising=False)
    monkeypatch.delenv("DOUBI_MAX_QUALITY", raising=False)

    cfg = load_config(None)
    assert cfg.theme == "deep_sea"
    assert cfg.max_quality == "720p"


def test_load_config_none_tolerates_missing_default_path(tmp_path, monkeypatch):
    """默认配置文件不存在时用 DEFAULTS，不能抛异常。"""
    monkeypatch.setattr(
        config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "nope" / "config.yml"
    )
    monkeypatch.delenv("DOUBI_THEME", raising=False)
    assert load_config(None).theme == theme_mod.DEFAULT_THEME


def test_env_overrides_config_file(tmp_path, monkeypatch):
    """分层顺序：环境变量 > 配置文件 > 默认值。"""
    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text(yaml.safe_dump({"theme": "deep_sea"}), encoding="utf-8")
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", cfg_file)
    monkeypatch.setenv("DOUBI_THEME", "morandi")
    assert load_config(None).theme == "morandi"


def test_theme_survives_yaml_round_trip(tmp_path, monkeypatch):
    """保存 → 读回，主题名不丢。"""
    cfg_file = tmp_path / "config.yml"
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", cfg_file)
    monkeypatch.delenv("DOUBI_THEME", raising=False)

    data = load_config(None).to_dict()
    data["theme"] = "eye_care"
    cfg_file.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    assert load_config(None).theme == "eye_care"


# ---------------------------------------------------------------------------
# 主题解析
# ---------------------------------------------------------------------------


def test_default_theme_is_registered():
    assert theme_mod.DEFAULT_THEME in theme_mod.THEMES


def test_theme_names_and_labels_are_aligned():
    names, labels = theme_mod.theme_names(), theme_mod.theme_labels()
    assert len(names) == len(labels) == len(theme_mod.THEMES)
    assert len(set(names)) == len(names), "主题 key 不能重复"
    assert len(set(labels)) == len(labels), "主题显示名不能重复"


@pytest.mark.parametrize("value", ["deep_sea", "深海"])
def test_resolve_theme_accepts_key_and_label(value):
    assert theme_mod.resolve_theme(value) == "deep_sea"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("light", "default_light"),
        ("亮色", "default_light"),
        ("dark", "default_dark"),
        ("暗色", "default_dark"),
        ("auto", theme_mod.DEFAULT_THEME),
        ("自动", theme_mod.DEFAULT_THEME),
    ],
)
def test_resolve_theme_migrates_legacy_values(value, expected):
    """旧配置里存的是 light/dark/auto，升级后不能报错。"""
    assert theme_mod.resolve_theme(value) == expected


@pytest.mark.parametrize("value", ["", None, "  ", "不存在的主题"])
def test_resolve_theme_falls_back_on_bad_input(value):
    """坏配置值不许让 GUI 起不来。"""
    assert theme_mod.resolve_theme(value) == theme_mod.DEFAULT_THEME


def test_every_theme_declares_the_same_token_keys():
    """任一主题缺 token 都会让某个控件取到 None，必须对齐。"""
    baseline = set(theme_mod.THEMES[theme_mod.DEFAULT_THEME].tokens)
    assert baseline, "默认主题必须有 token"
    for name, pack in theme_mod.THEMES.items():
        assert set(pack.tokens) == baseline, f"{name} 的 token 键与默认主题不一致"


def test_theme_pack_name_matches_registry_key():
    for key, pack in theme_mod.THEMES.items():
        assert pack.name == key


def test_set_theme_updates_current_without_qt():
    """无 Qt 环境下 set_theme 只更新状态，不抛异常。"""
    original = theme_mod.current_theme_name()
    try:
        pack = theme_mod.set_theme("morandi")
        assert pack.name == "morandi"
        assert theme_mod.current_theme_name() == "morandi"
        assert theme_mod.token("text_primary") == pack.tokens["text_primary"]
    finally:
        theme_mod.set_theme(original)


def test_set_theme_with_unknown_name_keeps_working():
    original = theme_mod.current_theme_name()
    try:
        assert theme_mod.set_theme("不存在").name == theme_mod.DEFAULT_THEME
    finally:
        theme_mod.set_theme(original)


def test_subscribe_theme_notifies_and_isolates_failures():
    calls: list[str] = []

    def boom() -> None:
        raise RuntimeError("这个回调故意炸")

    theme_mod.subscribe_theme(None, boom)
    theme_mod.subscribe_theme(None, lambda: calls.append("ok"))
    original = theme_mod.current_theme_name()
    try:
        theme_mod._notify()
        assert calls == ["ok"], "一个回调抛异常不能影响其余回调"
    finally:
        theme_mod._callbacks.clear()
        theme_mod.set_theme(original)


def test_muted_qss_tracks_current_theme_token() -> None:
    """muted_qss 必须随当前主题的 text_muted 变化，否则暗色主题下文字仍发灰。

    早期各页面散落 ``setStyleSheet("color: gray;")``：gray 在暗底上对比度不足，
    而且换主题不刷新。统一走本函数后四处行为一致。
    """
    light = theme_mod.current_theme().tokens["text_muted"]
    qss_light = theme_mod.muted_qss()
    assert f"color: {light};" in qss_light
    try:
        theme_mod.set_theme("deep_sea")
        dark = theme_mod.current_theme().tokens["text_muted"]
        qss_dark = theme_mod.muted_qss()
        assert f"color: {dark};" in qss_dark
        assert qss_dark != qss_light, "切主题后 muted_qss 应发生变化"
    finally:
        theme_mod.set_theme("default_light")
