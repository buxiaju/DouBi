"""体积精简的守门测试。

精简做了三件互相咬合的事，每一件单独看都「不影响本地开发」，
所以单靠跑代码是发现不了的——问题只在**发布版**里暴露：

1. 不打包 ``chrome-headless-shell.exe``（-270.7 MB），代价是
   每个 ``chromium.launch()`` 都必须显式带 ``channel="chromium"``。
   漏一处，本地照样跑（本地 ms-playwright 有 headless_shell），
   发布版一点就抛 ``Executable doesn't exist at ...``。
2. ``--exclude-module`` 掉 QtWebEngine / QtMultimedia / PIL 等
   （-330 MB 量级），代价是 src 里从此不许出现这些 import。
3. 用 ``tools/nm3u8dl/ffmpeg.exe``（10.91 MB）替掉 imageio_ffmpeg
   轮子（83.6 MB），代价是「排除轮子」和「打包替代品」必须同时在。
   只做前者，发布版就没有 ffmpeg 了。

这些测试全部检查「约束还在不在」，不检查具体数字，所以不会因为
下次升级 Playwright 或换 ffmpeg 版本就变红。
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "doubi"
BUILD_SCRIPT = ROOT / "scripts" / "build_exe.py"


def _load_build_module():
    """把 scripts/build_exe.py 当模块加载，读出它的常量。

    build_exe.py 的模块级只有常量和函数定义，真正干活的是 main()，
    所以 import 它没有副作用。
    """
    spec = importlib.util.spec_from_file_location("_build_exe_probe", BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _iter_src_py() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


# ---------------------------------------------------------------------------
# 1. channel="chromium"：headless_shell 被裁掉后的运行时前置条件
# ---------------------------------------------------------------------------

def _find_chromium_launch_calls() -> list[tuple[Path, int, ast.Call]]:
    """AST 扫出所有 ``*.chromium.launch(...)`` 调用。

    用 AST 而不是 grep，是为了能真正读到关键字参数——grep 只能看见
    「这行有没有 channel 这个词」，分不清它是参数还是注释里提到的。
    """
    found: list[tuple[Path, int, ast.Call]] = []
    for path in _iter_src_py():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute) or fn.attr != "launch":
                continue
            owner = fn.value
            # 兼容 ``p.chromium.launch`` 与 ``await p.chromium.launch``
            if isinstance(owner, ast.Attribute) and owner.attr == "chromium":
                found.append((path, node.lineno, node))
    return found


def test_there_are_exactly_two_chromium_launch_sites():
    """launch 点位数量本身就是要盯的东西。

    新增第三处 launch 时这条会红，提醒作者「你也得带 channel」——
    这比等发布版炸掉便宜得多。
    """
    calls = _find_chromium_launch_calls()
    where = sorted(f"{p.relative_to(ROOT)}:{ln}" for p, ln, _ in calls)
    assert len(calls) == 2, f"chromium.launch 点位变了：{where}"


def test_every_chromium_launch_pins_channel_to_chromium():
    """每处 launch 都必须显式 channel="chromium"。

    这是不打包 chrome-headless-shell.exe（270.7 MB）的直接代价。
    """
    offenders: list[str] = []
    for path, lineno, call in _find_chromium_launch_calls():
        kw = {k.arg: k.value for k in call.keywords if k.arg}
        chan = kw.get("channel")
        ok = isinstance(chan, ast.Constant) and chan.value == "chromium"
        if not ok:
            offenders.append(f"{path.relative_to(ROOT)}:{lineno}")

    assert not offenders, (
        "这些 chromium.launch() 缺少 channel=\"chromium\"：\n  "
        + "\n  ".join(offenders)
        + "\n发布版不带 chrome-headless-shell.exe，缺了它会抛 "
        "\"Executable doesn't exist\"。"
    )


def test_build_script_skips_headless_shell():
    """打包脚本确实在跳过 headless_shell——上一条的另一半。"""
    mod = _load_build_module()
    prefixes = mod._BROWSER_SKIP_PREFIXES
    assert any(p.startswith("chromium_headless_shell") for p in prefixes), prefixes


# ---------------------------------------------------------------------------
# 2. --exclude-module 与 src 的 import 必须自洽
# ---------------------------------------------------------------------------

def _collect_imported_names() -> dict[str, str]:
    """收集 src 下所有被 import 的模块全名 -> 出处。

    ``import a.b`` 和 ``from a.b import c`` 都记为 ``a.b``；
    相对导入（level>0）跳过——它们指向 doubi 自己。
    """
    seen: dict[str, str] = {}
    for path in _iter_src_py():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    seen.setdefault(alias.name, f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                if node.module:
                    seen.setdefault(node.module, f"{path.relative_to(ROOT)}:{node.lineno}")
    return seen


def test_no_source_file_imports_an_excluded_module():
    """被 --exclude-module 的东西，src 里一行都不许 import。

    判据是「import 链上有没有」而不是「文件在不在包里」：只要没有
    任何代码路径会执行到那条 import，排除就是安全的。这条测试就是
    把这个前提钉死——以后谁加了 ``from PIL import Image``，这里会红。

    注意匹配规则：``PySide6.QtWebEngineCore`` 这种带点的只精确匹配
    自己（否则会误伤大量合法的 ``PySide6.QtWidgets``），不带点的
    则连同其所有子模块一起禁掉。
    """
    mod = _load_build_module()
    excluded: list[str] = list(mod.EXCLUDE_MODULES)
    imported = _collect_imported_names()

    offenders: list[str] = []
    for ex in excluded:
        for name, where in imported.items():
            if "." in ex:
                hit = name == ex
            else:
                hit = name == ex or name.startswith(ex + ".")
            if hit:
                offenders.append(f"{name}（{where}）被 --exclude-module {ex} 排除了")

    assert not offenders, "打包排除项与源码 import 冲突：\n  " + "\n  ".join(offenders)


@pytest.mark.parametrize(
    "must_exclude",
    [
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia",
        "PIL",
        "imageio_ffmpeg",
    ],
)
def test_the_heavy_hitters_stay_excluded(must_exclude: str):
    """点名保护几个体积大户，防止排除清单被「顺手清理」掉。

    QtWebEngineCore 一进依赖图就会拖来 Qt6WebEngineCore.dll(194MB)
    + devtools .pak(72MB) + qtwebengine_locales(44MB)，约 321 MB。
    """
    mod = _load_build_module()
    assert must_exclude in mod.EXCLUDE_MODULES


# ---------------------------------------------------------------------------
# 3. 排除 imageio_ffmpeg ⇔ 打包 tools/nm3u8dl/ffmpeg.exe
# ---------------------------------------------------------------------------

def test_excluding_imageio_ffmpeg_requires_bundling_a_replacement():
    """两件事必须同时成立，否则发布版没有 ffmpeg。

    installer/doubi.nsi 只做 ``File /r dist/doubi-gui\\*.*``，
    tools/ 不进安装包——所以替代品必须靠 --add-data 进去。
    """
    mod = _load_build_module()
    if "imageio_ffmpeg" not in mod.EXCLUDE_MODULES:
        pytest.skip("没有排除 imageio_ffmpeg，这条约束不适用")

    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "FFMPEG_EXE" in source
    assert "--add-data" in source
    assert 'f"{FFMPEG_EXE}{sep}tools/nm3u8dl"' in source, (
        "排除了 imageio_ffmpeg 却没把 tools/nm3u8dl/ffmpeg.exe 打进去"
    )


def test_bundled_ffmpeg_is_present_in_the_repo():
    """ffmpeg.exe 是构建输入，必须是 git 跟踪的真实文件。

    它不是「本地碰巧有」——fresh clone 和 CI 都得能拿到，
    否则 build_exe.py 的预检会直接失败。
    """
    mod = _load_build_module()
    assert mod.FFMPEG_EXE.is_file(), f"缺少构建输入 {mod.FFMPEG_EXE}"


def test_all_engines_resolve_ffmpeg_through_the_shared_helper():
    """三个引擎都必须走 find_bundled_ffmpeg，而不是各自造轮子。

    以前它们各自 fallback 到 imageio_ffmpeg；轮子被排除后，任何
    漏改的引擎都会在发布版里静默拿不到 ffmpeg（m3u8 会降级成
    aiohttp 分片下载，yt-dlp 会没法合流）。
    """
    from doubi.engines import m3u8, nm3u8dl, yt_dlp

    for module in (m3u8, nm3u8dl, yt_dlp):
        assert hasattr(module, "find_bundled_ffmpeg"), (
            f"{module.__name__} 没有导入 find_bundled_ffmpeg"
        )
        src = Path(module.__file__).read_text(encoding="utf-8")
        assert "imageio_ffmpeg" not in src, (
            f"{module.__name__} 仍然引用 imageio_ffmpeg，但它已被打包排除"
        )


def test_bundled_ffmpeg_probes_meipass_first(monkeypatch, tmp_path):
    """冻结环境下必须先看 sys._MEIPASS，再看 cwd。

    发布版从快捷方式启动时 cwd 可能是 C:\\Windows\\System32，
    cwd 优先的写法会直接找不到自带的 ffmpeg。ui/i18n.py 定位
    locales 用的就是同一套 _MEIPASS 优先模式。
    """
    import sys

    from doubi.engines._subproc import find_bundled_ffmpeg

    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    fake_meipass = tmp_path / "meipass"
    target = fake_meipass / "tools" / "nm3u8dl"
    target.mkdir(parents=True)
    (target / name).write_bytes(b"not really ffmpeg")

    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    resolved = find_bundled_ffmpeg()

    assert resolved == str(target / name), (
        f"_MEIPASS 没被优先采用，实际返回 {resolved}"
    )
