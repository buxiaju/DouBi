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


# ---------------------------------------------------------------------------
# M6.27 — login dialog 词表完整性
# ---------------------------------------------------------------------------
#
# M6.25 (B 站) + M6.26 (抖音) 改写了两套登录对话框，把硬编码中文搬进
# ``tr()``。这两条测试钉死「未来谁动 dialog 字符串都得用 tr」，否则
# 切换到 en 时 UI 会露出半中半英。


#: M6.25 + M6.26 dialog 实际用到的 key 白名单。如果 dialog 里新增了
#: 硬编码字符串，源语言会先有这个 key；测试做反向检查——这个白名单
#: 里的 key 必须在源语言都有译文（保护性的，反向防止删 key 漏 UI）。
M6_LOGIN_KEYS = frozenset(
    {
        # B 站 dialog — 窗口 / 标签
        "login.bili.window_title",
        "login.bili.tab.qr",
        "login.bili.tab.import_cookie",
        # B 站 dialog — QR tab
        "login.bili.qr.hint",
        "login.bili.qr.generating",
        "login.bili.qr.preparing",
        "login.bili.qr.waiting_scan",
        "login.bili.qr.scanned_confirm",
        "login.bili.qr.success_saving",
        "login.bili.qr.expired",
        "login.bili.qr.poll_error",
        "login.bili.qr.url_label",
        "login.bili.qr.refresh_button",
        "login.bili.qr.copy_button",
        "login.bili.qr.fail_prefix",
        "login.bili.qr.success_path",
        "login.bili.qr.render_fail",
        # B 站 dialog — 导入 Cookie tab
        "login.bili.import.title",
        "login.bili.import.hint",
        "login.bili.import.pick_button",
        "login.bili.import.placeholder",
        "login.bili.import.confirm_button",
        # 抖音 dialog
        "login.dy.window_title",
        "login.dy.hint",
        "login.dy.qr.loading",
        "login.dy.qr.screenshot_decode_fail",
        "login.dy.status.starting",
        "login.dy.status.starting_headless",
        "login.dy.status.qr_ready",
        "login.dy.checkbox.headed",
        "login.dy.checkbox.headed_tooltip",
        "login.dy.fail_with_hint",
        "login.dy.success",
        # settings 卡片上的说明文案
        "login.bili.settings_detail",
        "login.dy.settings_detail",
        # 共享
        "common.close",
    }
)


def test_m6_login_keys_all_present_in_source_locale():
    """M6.25 + M6.26 dialog 实际用到的 key 都必须在源语言存在。

    反向防漏：加白名单后，删 / 改 key 都会被这个测试拦下来。
    """
    source = _load_json(i18n.DEFAULT_LANGUAGE)
    missing = sorted(M6_LOGIN_KEYS - set(source))
    assert not missing, f"源语言缺 M6 login key: {missing}"


def test_m6_login_keys_fully_translated_in_every_language():
    """``available_languages`` 中每种语言都必须翻译这套 M6 词表。

    ``test_translation_keys_cover_source_in_every_language`` 已经检查了
    全量覆盖——这里把它收紧到 M6 子集，让失败信息更聚焦。
    """
    for lang in i18n.available_languages():
        if lang == i18n.DEFAULT_LANGUAGE:
            continue
        table = _load_json(lang)
        missing = sorted(M6_LOGIN_KEYS - set(table))
        assert not missing, f"{lang}.json 缺 M6 login key: {missing}"


@pytest.mark.parametrize(
    "key, kwargs",
    [
        ("login.bili.qr.url_label", {"url": "https://x", "length": 32}),
        ("login.bili.qr.poll_error", {"message": "boom"}),
        ("login.bili.qr.fail_prefix", {"error": "ETIMEDOUT"}),
        ("login.bili.qr.success_path", {"path": "/tmp/x.txt"}),
        ("login.bili.qr.render_fail", {"error": "OOM"}),
        ("login.dy.fail_with_hint", {"error": "nope"}),
    ],
)
def test_m6_login_keys_format_placeholders(key, kwargs):
    """所有带 ``{...}`` 占位符的 key 都能被 ``tr(**kwargs)`` 正常填充。

    反向：M6.25/26 新加的 key 里好几个用了 ``{url}`` / ``{path}`` 等
    占位符，缺一个会变成「KeyError 弹窗」——这个测试钉死每个 key 都能
    用 happy-path kwargs 走通。
    """
    i18n.set_language("en")
    out = i18n.tr(key, **kwargs)
    # 译文不应再含裸 ``{name}`` 占位符——所有占位符必须已被填实
    for k in kwargs:
        assert f"{{{k}}}" not in out, (
            f"placeholder {{{k}}} not substituted in {key}: {out!r}"
        )
    # 也应该非空
    assert out.strip(), f"{key} produced empty translation"


def test_login_dialog_strings_use_tr_not_hardcoded_zh():
    """M6.25/26 改完后，``login_dialog.py`` 不应再出现 login.* 域外
    硬编码的「扫码 / 登录 / 二维码 / 导入 / 抖音 / B 站」中文词
    （这些都该走 tr()）。

    这个测试刻意避开模块 docstring（顶层那些中文是给读者看的，可以
    留）和工具提示字符串（\"\"\"…\"\"\" 多行也会被命中——放过）。它
    只扫 setText / setPlaceholderText / setToolTip / addItem /
    setWindowTitle 这五个实打实落在 UI 上的方法调用。
    """
    import re
    from pathlib import Path
    p = Path("src/doubi/ui/dialogs/login_dialog.py")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    # 找 setText / setWindowTitle / addItem / setToolTip / setPlaceholderText
    # 后面的字符串字面量。允许 ``tr(...)``、空串 \"\"、其他变量赋值。
    pattern = re.compile(
        r"""(?P<call>\.set(?:Text|WindowTitle|PlaceholderText|ToolTip)\(|\.addItem\()
            \s*
            (?P<arg>
                tr\([^)]*\)              # 走 tr
              | \"\"                     # 空串
              | f?[\"'][^\"']*[\"']      # 普通字符串
            )
        """,
        re.VERBOSE,
    )
    hardcoded_zh: list[tuple[int, str]] = []
    for m in pattern.finditer(text):
        arg = m.group("arg")
        if not arg or arg.startswith("tr(") or arg == "\"\"":
            continue
        # 跳过纯模板字符串 / 变量
        if arg.startswith("f\"") or arg.startswith("f'"):
            continue
        # 看是否含 login.* 中文关键词
        if any(zh in arg for zh in (
            "扫码", "二维码", "导入", "抖音", "B 站", "确认", "关闭",
        )):
            line = text[: m.start()].count("\n") + 1
            hardcoded_zh.append((line, arg))
    assert not hardcoded_zh, (
        "login_dialog.py 还有硬编码中文没走 tr():\n"
        + "\n".join(f"  line {ln}: {a}" for ln, a in hardcoded_zh)
    )
