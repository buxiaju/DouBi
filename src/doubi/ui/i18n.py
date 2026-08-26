"""轻量级国际化（i18n）基础设施。

设计取舍
========

没有用 Qt 自带的 ``.ts`` / ``.qm`` 工具链：

* ``.ts`` 是 XML，需要 ``lupdate`` 扫源码生成、``lrelease`` 编译成二进制
  ``.qm``，两步构建依赖 PyQt/PySide 的工具链，CI 上多一层麻烦。
* Qt 的 ``tr()`` 绑在 ``QObject`` 子类上，模块级函数和非 Qt 代码（CLI、
  REST、日志）用不了，翻译覆盖面会被「有没有继承 QObject」切一刀。

改用 **JSON 词表 + 纯函数 ``tr()``**：

* 词表是普通 JSON，人能直接读改，不需要构建步骤。
* :func:`tr` 是模块级函数，任何代码都能调——GUI、CLI、REST 一套机制。
* 语言切换是运行时的，:func:`set_language` 后续 ``tr()`` 调用立即走新语言。
  已渲染的 Qt 控件不会自动重译（Qt 的 ``.qm`` 方案也做不到，除非重 emit
  ``LanguageChange`` 事件 + 逐个 ``retranslateUi``），所以 GUI 切语言后
  需要重启——和主题里 ``database_path`` 等「重启生效」字段同一档处理。

回退顺序：当前语言 → ``zh_CN``（源语言/兜底）→ key 本身。

新增可译字符串只需往 ``locales/zh_CN.json`` 和对应语言文件加同一把 key，
不需要改本模块。
"""

from __future__ import annotations

import importlib.resources as ilr
import json
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("doubi.ui.i18n")

__all__ = [
    "DEFAULT_LANGUAGE",
    "available_languages",
    "language_labels",
    "current_language",
    "set_language",
    "translate",
    "tr",
]

#: 源语言，也是所有 key 的兜底语言。新字符串先在这里出现，再翻译出去。
DEFAULT_LANGUAGE = "zh_CN"


def _resolve_locales_dir() -> Path:
    """返回词表 ``locales`` 目录的**真实可读**绝对路径。

    三种运行形态，优先级从高到低：

    1. **PyInstaller frozen bundle** — 脚本启动时 PyInstaller 把
       ``--add-data`` 收集的所有文件解压到 ``sys._MEIPASS``。
       ``doubi/ui/i18n.py`` 被编译为字节码塞进 PYZ CArchive，模块级
       ``Path(__file__)`` 指向 PYZ 里的**假路径**，拼出的 ``locales``
       自然不存在；必须用 ``_MEIPASS`` 重拼真实解压位置。
    2. **源码 / pip -e（可编辑）安装** — ``Path(__file__).parent / locales``
       就是真实目录，直接用。
    3. **普通 pip wheel 安装** — 模块源文件仍在 site-packages/doubi/ui/，
       回退到 (2) 已经覆盖，这里显式地再 ``importlib.resources`` 兜底，
       避免打包成 ``.zipapp`` 或 ``pex`` 等极端形态时失败。
    """
    # 1) Frozen: _MEIPASS / doubi / ui / locales
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate = Path(sys._MEIPASS) / "doubi" / "ui" / "locales"
        if candidate.is_dir():
            return candidate
        logger.warning("PyInstaller frozen: _MEIPASS/locales 未找到，词表将 fallback 到 key 本身")

    # 2) Normal: alongside this module
    src_side = Path(__file__).resolve().parent / "locales"
    if src_side.is_dir():
        return src_side

    # 3) importlib.resources fallback: find package "doubi.ui" and locate locales/
    try:
        pkg_locales = ilr.files("doubi.ui").joinpath("locales")  # type: ignore[attr-defined]
        with ilr.as_file(pkg_locales) as p:  # type: ignore[attr-defined]
            resolved = Path(p)
        if resolved.is_dir():
            logger.debug("locales/ 目录通过 importlib.resources 定位到 %s", resolved)
            return resolved
    except Exception:
        # importlib.resources 失败（例如没装成 package）—— 回退返回 src_side，
        # 调用方 load 会发现路径不存在，打 debug 日志并返回空表。这已经是
        # 所有兜底都失效后的「最后一条路」：把 源文件侧目录当线索继续返回，
        # 避免抛出异常导致 import 本模块直接挂。
        pass
    return src_side


#: 词表目录。和本模块同层的 ``locales/``。
_LOCALES_DIR = _resolve_locales_dir()

# 语言 key → 显示名。显示名用各自语言书写，方便用户在母语里认出自己的语言。
# 顺序即界面展示顺序（源语言排第一）。
_LANGUAGES: dict[str, str] = {
    "zh_CN": "简体中文",
    "en": "English",
}

# 运行时词表缓存：lang → {key: text}。首次访问某语言时从磁盘加载。
_tables: dict[str, dict[str, str]] = {}

#: 当前生效语言。模块级单例——和 theme._current 一样，全局唯一。
_current: str = DEFAULT_LANGUAGE


def _load_table(lang: str) -> dict[str, str]:
    """加载某语言的词表，带缓存。

    缺失文件 / JSON 损坏时返回空表并告警：调用方会自然回退到
    :data:`DEFAULT_LANGUAGE`，不会让一次翻译失败把 UI 打挂。
    """
    cached = _tables.get(lang)
    if cached is not None:
        return cached
    path = _LOCALES_DIR / f"{lang}.json"
    if not path.is_file():
        logger.debug("词表缺失: %s", path)
        _tables[lang] = {}
        return _tables[lang]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("词表读取失败: %s", path, exc_info=True)
        _tables[lang] = {}
        return _tables[lang]
    if not isinstance(data, dict):
        logger.warning("词表不是 JSON 对象: %s", path)
        _tables[lang] = {}
        return _tables[lang]
    table = {str(k): str(v) for k, v in data.items()}
    _tables[lang] = table
    return table


def available_languages() -> list[str]:
    """全部语言 key，顺序即界面展示顺序（源语言排第一）。"""
    return list(_LANGUAGES)


def language_labels() -> list[str]:
    """全部语言显示名，与 :func:`available_languages` 同序。"""
    return list(_LANGUAGES.values())


def _label_to_key(label: str) -> str:
    """显示名 → key，找不到回退到 :data:`DEFAULT_LANGUAGE`。"""
    for k, v in _LANGUAGES.items():
        if v == label:
            return k
    return DEFAULT_LANGUAGE


def current_language() -> str:
    """当前生效的语言 key（可直接写入配置）。"""
    return _current


def set_language(lang: Optional[str]) -> None:
    """切换当前语言。

    未知 key 回退到 :data:`DEFAULT_LANGUAGE`，而不是抛错——配置文件里
    写错语言不该让应用起不来。``None`` 显式表示「用默认」。
    """
    global _current
    if not lang or lang not in _LANGUAGES:
        lang = DEFAULT_LANGUAGE
    if lang == _current:
        return
    _current = lang
    logger.debug("语言切换为 %s", lang)


def translate(key: str, **kwargs) -> str:
    """按 key 取译文，支持 ``str.format`` 占位符。

    >>> translate("nav.parse")
    '解析'
    >>> translate("msg.restored_n", n=3)
    '3 个任务已暂停待续'

    回退顺序：当前语言 → ``zh_CN`` → key 原样返回。找不到 key 不抛错——
    漏译不该让 UI 崩，最坏情况是显示 key 本身，一眼能看出缺哪条。
    """
    table = _load_table(_current)
    text = table.get(key)
    # 当前语言没有这条 key 时回退到源语言，再没有就把 key 本身当译文。
    if text is None and _current != DEFAULT_LANGUAGE:
        text = _load_table(DEFAULT_LANGUAGE).get(key)
    if text is None:
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            # 占位符对不上时退回未填充的译文，比抛错好。
            return text
    return text


#: :func:`translate` 的短别名。UI 代码里 ``from ..i18n import tr`` 后
#: 直接 ``tr("nav.parse")`` 用，和主流 i18n 库的惯例一致。
tr = translate
