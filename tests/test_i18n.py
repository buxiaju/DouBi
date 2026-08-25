"""i18n 基础设施测试。

钉死四件事：
1. 词表文件是合法 JSON 且每个语言文件结构正确；
2. ``tr`` 能取到译文、找不到时回退到源语言再回退到 key 本身；
3. ``set_language`` 切换后后续 ``tr`` 走新语言，未知语言回退源语言；
4. 语言枚举/标签 API 稳定（设置页语言下拉依赖它）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from doubi.ui import i18n


@pytest.fixture(autouse=True)
def _reset_language():
    """每个用例跑完恢复默认语言，避免污染后续测试。"""
    i18n.set_language(i18n.DEFAULT_LANGUAGE)
    yield
    i18n.set_language(i18n.DEFAULT_LANGUAGE)


# ---------------------------------------------------------------------------
# 词表文件完整性
# ---------------------------------------------------------------------------

def _locales_dir() -> Path:
    return Path(i18n.__file__).resolve().parent / "locales"


def _load_json(lang: str) -> dict[str, str]:
    path = _locales_dir() / f"{lang}.json"
    assert path.is_file(), f"locale file missing: {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{lang}.json is not a JSON object"
    return {str(k): str(v) for k, v in data.items()}


def test_source_locale_is_valid_json():
    table = _load_json(i18n.DEFAULT_LANGUAGE)
    assert table, "zh_CN.json must not be empty"
    # 源语言里几个被 UI 实际使用的 key 必须存在。
    for key in ("nav.parse", "nav.download", "nav.settings", "language.label"):
        assert key in table, f"missing key in source locale: {key}"


def test_every_language_has_a_locale_file():
    """``available_languages`` 里列出的每个语言都要有对应词表文件。"""
    for lang in i18n.available_languages():
        _load_json(lang)  # 断言文件存在且是合法 JSON


def test_translation_keys_cover_source_in_every_language():
    """非源语言不应漏掉源语言里已有的 key（漏译会被发现）。

    源语言是 key 的来源；如果 ``en.json`` 缺了某条 key，回退会让 UI 显示中文，
    这通常是疏漏而非有意为之。这里要求非源语言覆盖源语言全部 key。
    """
    source = _load_json(i18n.DEFAULT_LANGUAGE)
    for lang in i18n.available_languages():
        if lang == i18n.DEFAULT_LANGUAGE:
            continue
        table = _load_json(lang)
        missing = sorted(set(source) - set(table))
        assert not missing, f"{lang}.json missing keys: {missing}"


# ---------------------------------------------------------------------------
# translate / 回退
# ---------------------------------------------------------------------------

def test_translate_returns_value_from_current_language():
    i18n.set_language("en")
    assert i18n.tr("nav.parse") == "Parse"
    i18n.set_language("zh_CN")
    assert i18n.tr("nav.parse") == "解析"


def test_translate_falls_back_to_source_when_key_missing_in_current():
    """当前语言缺某 key 时回退到源语言，而不是显示 key 本身。"""
    # 用一个 zh_CN 有、en 故意不收的 key 验证回退路径。
    # 这里直接造一个：所有正式 key 都被上一条测试要求覆盖，
    # 所以临时往内存词表里插一条只在源语言存在的 key。
    i18n._tables.setdefault("zh_CN", {})["__test_only_zh"] = "中文专用"
    i18n._tables.setdefault("en", {})  # 确保 en 表存在但不含该 key
    try:
        i18n.set_language("en")
        assert i18n.tr("__test_only_zh") == "中文专用"
    finally:
        i18n._tables["zh_CN"].pop("__test_only_zh", None)


def test_translate_returns_key_when_completely_unknown():
    """源语言也没有的 key 直接返回 key 本身，不抛错。"""
    assert i18n.tr("totally.made.up.key.xyz") == "totally.made.up.key.xyz"


def test_translate_supports_format_placeholders():
    i18n._tables.setdefault("zh_CN", {})["__fmt"] = "共 {n} 个"
    try:
        assert i18n.tr("__fmt", n=5) == "共 5 个"
    finally:
        i18n._tables["zh_CN"].pop("__fmt", None)


def test_translate_placeholder_mismatch_does_not_raise():
    i18n._tables.setdefault("zh_CN", {})["__fmt2"] = "共 {n} 个"
    try:
        # 传了不匹配的占位符名，退回未填充译文而非抛 KeyError。
        assert i18n.tr("__fmt2", wrong=1) == "共 {n} 个"
    finally:
        i18n._tables["zh_CN"].pop("__fmt2", None)


# ---------------------------------------------------------------------------
# set_language / 语言枚举
# ---------------------------------------------------------------------------

def test_set_language_switches_subsequent_calls():
    i18n.set_language("en")
    assert i18n.current_language() == "en"
    assert i18n.tr("nav.settings") == "Settings"


def test_set_language_unknown_falls_back_to_default():
    i18n.set_language("fr_FR")
    assert i18n.current_language() == i18n.DEFAULT_LANGUAGE


def test_set_language_none_falls_back_to_default():
    i18n.set_language(None)
    assert i18n.current_language() == i18n.DEFAULT_LANGUAGE


def test_set_language_idempotent():
    i18n.set_language("en")
    i18n.set_language("en")  # 再次设置同一个不应出错
    assert i18n.current_language() == "en"


def test_available_languages_and_labels_same_length_and_order():
    langs = i18n.available_languages()
    labels = i18n.language_labels()
    assert len(langs) == len(labels)
    assert i18n.DEFAULT_LANGUAGE in langs
    # 源语言排第一（设置页展示顺序约定）。
    assert langs[0] == i18n.DEFAULT_LANGUAGE


def test_default_language_is_zh_cn():
    assert i18n.DEFAULT_LANGUAGE == "zh_CN"
