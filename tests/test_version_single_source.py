"""版本号单一真源的守门测试。

真源是 ``src/doubi/__init__.py`` 的 ``__version__``。历史上这个字面量
被抄了三份（包 / GUI APP_VERSION / pyproject.toml），发版时必然对不上：
安装包叫 0.1.0、关于对话框写 0.0.9、``doubi -V`` 又是第三个数。

这些测试不检查「版本号是多少」——那会让每次发版都要改测试。它们只
检查「有几个地方**能**决定版本号」，答案必须是 1。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "doubi"
VERSION_FILE = SRC / "__init__.py"

#: 形如 ``__version__ = "1.2.3"`` / ``APP_VERSION = '1.2'`` 的赋值。
#: 只认字面量赋值——``APP_VERSION = __version__`` 这类派生不该被抓到。
_VERSION_LITERAL_RE = re.compile(
    r"""^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*version[A-Za-z0-9_]*)\s*=\s*["'](?P<val>\d+(?:\.\d+)+[^"']*)["']""",
    re.MULTILINE | re.IGNORECASE,
)


def test_package_version_is_a_plain_semver_string():
    import doubi

    assert isinstance(doubi.__version__, str)
    # 至少两段数字，且不是空壳/占位
    assert re.fullmatch(r"\d+(?:\.\d+)+[\w.\-+]*", doubi.__version__), doubi.__version__


def test_only_one_version_literal_in_src():
    """整个 src/ 里只允许 __init__.py 出现一处版本号字面量。

    任何 ``APP_VERSION = "0.2.0"`` 式的新拷贝都会让这条炸掉，
    修法是改成从 ``doubi.__version__`` 派生。
    """
    offenders: list[str] = []
    for py in SRC.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        for m in _VERSION_LITERAL_RE.finditer(text):
            rel = py.relative_to(ROOT).as_posix()
            if py == VERSION_FILE and m.group("name") == "__version__":
                continue  # 这就是真源本身
            line = text[: m.start()].count("\n") + 1
            offenders.append(f"{rel}:{line} {m.group('name')} = {m.group('val')!r}")

    assert not offenders, (
        "发现重复的版本号字面量，请改为从 doubi.__version__ 派生：\n  "
        + "\n  ".join(offenders)
    )


def test_gui_app_version_is_derived_not_copied():
    import doubi
    from doubi.ui.resources import APP_VERSION

    assert APP_VERSION == doubi.__version__


def test_pyproject_declares_version_dynamic():
    """pyproject.toml 不得内联 version，必须 dynamic + attr 派生。"""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert re.search(r'^\s*dynamic\s*=\s*\[[^\]]*"version"', text, re.MULTILINE), (
        "[project] 缺少 dynamic = [\"version\"]"
    )
    assert re.search(
        r'^\s*version\s*=\s*\{\s*attr\s*=\s*"doubi\.__version__"\s*\}',
        text,
        re.MULTILINE,
    ), "[tool.setuptools.dynamic] 缺少 version = { attr = \"doubi.__version__\" }"
    # 行首的 `version = "..."` 字面量必须已被移除
    assert not re.search(r'^version\s*=\s*"', text, re.MULTILINE), (
        "pyproject.toml 仍有内联 version 字面量"
    )


def test_setuptools_resolves_the_same_version():
    """构建后端解析出的版本必须与包属性一致。

    这条守的是 ``attr:`` 路径写错（比如 packages.find 的 where 变了）
    时的静默降级——setuptools 会报错或给出别的值，而不是恰好相同。
    """
    pytest.importorskip("setuptools")
    from setuptools.config.pyprojecttoml import read_configuration

    import doubi

    cfg = read_configuration(str(ROOT / "pyproject.toml"))
    assert cfg["project"]["version"] == doubi.__version__


def test_installer_script_reads_the_same_version():
    """NSIS 打包脚本读到的版本必须与包属性一致。

    ``build_installer.read_version()`` 刻意用正则而不是 import，
    所以它可能与真源脱节——这条就是那道保险。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_installer
    finally:
        sys.path.pop(0)

    import doubi

    assert build_installer.read_version() == doubi.__version__


def test_nsi_fallback_version_is_an_obvious_placeholder():
    """.nsi 的 !define 兜底值必须是 0.0.0（且四段数字合法）。

    兜底值若写成某个真实版本号，漏传 /DPRODUCT_VERSION 时会打出一个
    版本号张冠李戴的安装包，且无从察觉。
    """
    text = (ROOT / "installer" / "doubi.nsi").read_text(encoding="utf-8")
    m = re.search(r'^\s*!define\s+PRODUCT_VERSION\s+"([^"]+)"', text, re.MULTILINE)
    assert m, "doubi.nsi 里找不到 PRODUCT_VERSION 兜底定义"
    fallback = m.group(1)
    assert fallback == "0.0.0", f"兜底版本号应为占位值 0.0.0，实际 {fallback!r}"
    # VIProductVersion "${PRODUCT_VERSION}.0" 要求四段纯数字
    assert re.fullmatch(r"\d+\.\d+\.\d+", fallback)
