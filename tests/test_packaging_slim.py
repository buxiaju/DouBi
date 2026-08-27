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


# ---------------------------------------------------------------------------
# 4. 非 .py 资源：--collect-submodules 收不到它们
# ---------------------------------------------------------------------------
# 0.3.0 踩过：catch_lite.js 没有 --add-data，构建成功、测试全绿、发布版
# 一嗅探就报「catch_lite.js 加载失败；安装包可能损坏」。
#
# 为什么本地永远发现不了：开发时 importlib.resources 落到真实 src 目录，
# 文件就在那儿；只有冻结后才走 _MEIPASS，那里才是空的。
#
# 下面两条不硬编码文件名，而是从**代码本身**推出「有哪些资源要进包」，
# 这样以后新增任何 resources.files(...) 读的文件都会被自动纳入检查。


def _iter_resource_reads() -> list[tuple[Path, int, str, str]]:
    """AST 扫出 ``resources.files("pkg").joinpath("name")`` 形态的资源读。

    返回 ``(源文件, 行号, 包名, 资源名)``。用 AST 而不是 grep：要拿到
    的是两个字符串字面量的**值**，grep 只能确认「这行提到了 joinpath」。
    """
    found: list[tuple[Path, int, str, str]] = []
    for path in _iter_src_py():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute) or fn.attr != "joinpath":
                continue
            inner = fn.value
            # 只认 files(...) 的直接返回值，形如 files("pkg").joinpath("x")
            if not isinstance(inner, ast.Call):
                continue
            inner_fn = inner.func
            name = inner_fn.attr if isinstance(inner_fn, ast.Attribute) else (
                inner_fn.id if isinstance(inner_fn, ast.Name) else None
            )
            if name != "files":
                continue
            if not (inner.args and isinstance(inner.args[0], ast.Constant)):
                continue
            if not (node.args and isinstance(node.args[0], ast.Constant)):
                continue
            pkg, res = inner.args[0].value, node.args[0].value
            if isinstance(pkg, str) and isinstance(res, str):
                found.append((path, node.lineno, pkg, res))
    return found


def test_every_importlib_resource_exists_in_the_repo():
    """代码里点名要读的资源，仓库里必须真有它。

    先钉住这一半：路径写错（改名、挪目录）会在这里红，而不是等到
    运行时被 except FileNotFoundError 吞掉变成一句模糊的错误提示。

    资源可以是文件（catch_lite.js）也可以是目录（ui/locales），
    所以判据是 exists() 而不是 is_file()。
    """
    reads = _iter_resource_reads()
    assert reads, "一个 resources.files(...).joinpath(...) 都没扫到，扫描逻辑可能失效了"

    for path, lineno, pkg, res in reads:
        assert pkg.startswith("doubi"), (
            f"{path.name}:{lineno} 读的是第三方包 {pkg} 的资源，本测试的假设不成立"
        )
        target = ROOT / "src" / Path(pkg.replace(".", "/")) / res
        assert target.exists(), (
            f"{path.name}:{lineno} 要读 {pkg}/{res}，但 {target} 不存在"
        )


def _add_data_targets() -> set[str]:
    """解析出 build_exe.py 里所有 ``--add-data`` 的包内目标目录。

    按「列表里紧跟在 ``--add-data`` 后面的那个元素」配对，而不是把源码
    里所有 f-string 都当候选——后者会把预检的中文报错消息也算进来
    （第一版就踩了这个，assert 失败消息里出现了「它是发布版唯一的
    ffmpeg 来源」这种字符串）。
    """
    tree = ast.parse(BUILD_SCRIPT.read_text(encoding="utf-8"), filename=str(BUILD_SCRIPT))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        for prev, cur in zip(node.elts, node.elts[1:]):
            if not (isinstance(prev, ast.Constant) and prev.value == "--add-data"):
                continue
            # 值形如 f"{CONST}{sep}dst/dir"，取末段常量即包内目标
            if isinstance(cur, ast.JoinedStr) and cur.values:
                tail = cur.values[-1]
                if isinstance(tail, ast.Constant) and isinstance(tail.value, str):
                    targets.add(tail.value.lstrip("/"))
            elif isinstance(cur, ast.Constant) and isinstance(cur.value, str):
                _, _, dst = cur.value.rpartition(";")
                targets.add((dst or cur.value).lstrip("/"))
    return targets


def test_every_non_py_resource_read_at_runtime_has_an_add_data_entry():
    """每个运行时要读的非 .py 资源，都必须在 build_exe.py 里有 --add-data。

    ``--collect-submodules doubi`` 只把 Python 模块收进 PYZ，
    .js / .json / .svg 这类数据文件一个都不带。漏一个的后果不是构建
    失败，而是发布版里静默少一个文件——这正是 0.3.0 的事故形态。
    """
    targets = _add_data_targets()
    assert targets, "没解析到任何 --add-data 目标，解析逻辑可能失效了"

    for path, lineno, pkg, res in _iter_resource_reads():
        if res.endswith(".py"):
            continue
        pkg_dir = pkg.replace(".", "/")
        # 单文件资源 → 目标是所在包目录；整目录资源 → 目标是该目录本身
        covered = pkg_dir in targets or f"{pkg_dir}/{res}" in targets
        assert covered, (
            f"{path.name}:{lineno} 运行时要读 {pkg}/{res}，但 build_exe.py 里"
            f"没有对应的 --add-data 目标（期望 {pkg_dir!r} 或 {pkg_dir + '/' + res!r}）。"
            f"现有目标：{sorted(targets)}。"
            "缺了它构建照样成功，但发布版会少这个文件。"
        )


def test_build_script_preflights_every_add_data_source_file():
    """单文件类型的构建输入必须有 is_file() 预检。

    这是 FFMPEG_EXE 那段注释立下的规矩：「早失败而不是让 --add-data
    静默丢一个不存在的路径」。PyInstaller 对不存在的 --add-data 源
    只是警告，不报错，所以预检是唯一的拦截点。
    """
    mod = _load_build_module()
    source = BUILD_SCRIPT.read_text(encoding="utf-8")

    single_file_inputs = [
        name
        for name in ("SVG_TEMPLATE", "CATCH_LITE_JS", "FFMPEG_EXE")
        if isinstance(getattr(mod, name, None), Path)
    ]
    assert single_file_inputs, "一个单文件构建输入都没找到，常量可能被改名了"

    for name in single_file_inputs:
        assert f"if not {name}.is_file():" in source, (
            f"{name} 没有预检，缺文件时构建会静默成功并产出坏包"
        )
        assert getattr(mod, name).is_file(), f"缺少构建输入 {getattr(mod, name)}"


def test_catch_lite_js_is_the_only_source_of_the_injected_script():
    """catch_lite.js 没有兜底路径，所以它是硬依赖。

    对比 icon.png：那个只是 QtSvg 不可用时的兜底，且读之前有
    is_file() 保护，不打包只是安全降级。catch_lite.js 缺了则整个
    通用嗅探直接返回错误——两者不能用同一套标准对待。
    """
    sniffer_src = (SRC / "core" / "sniffer.py").read_text(encoding="utf-8")

    assert "安装包可能损坏" in sniffer_src, (
        "加载失败时的用户可见提示没了？那这条测试要重写"
    )
    # 加载失败只有「返回空串 → 报错」这一条路，没有第二个 JS 来源
    assert sniffer_src.count("catch_lite.js") >= 2
    assert "MediaRecorder" not in sniffer_src, (
        "JS 逻辑不该内联进 Python，那样就有两个真源了"
    )


# ---------------------------------------------------------------------------
# 6. aiohttp 是 HLS 下载的唯一可行路径，必须显式收集（M6.20）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("package", ["aiohttp", "multidict", "yarl"])
def test_aiohttp_stack_is_explicitly_collected(package: str):
    """aiohttp 全家必须 --collect-all，不能靠静态分析推导。

    背景：捆绑的 tools/nm3u8dl/ffmpeg.exe 是 N_m3u8DL-CLI 的定制构建，
    编译时没启用任何 TLS 后端，``-protocols`` 里根本没有 https。喂它
    https 播放列表会立刻 "Protocol not found" 退出。现实中的 m3u8
    几乎全是 https，所以 aiohttp 分片下载器不是降级备选，而是 HLS
    的**主路径**——漏了它，HLS 下载 100% 不可用。

    为什么静态分析不够：m3u8.py / direct_http.py 用的是函数内延迟
    ``import aiohttp``；而 multidict / yarl / propcache 带 .pyd
    C 扩展。这两点叠加，漏包的表现是运行时 ModuleNotFoundError，
    构建期毫无征兆。
    """
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert f'"--collect-all", "{package}"' in source, (
        f"{package} 没有被显式收集；HLS 下载会在用户机上 ImportError"
    )


def test_aiohttp_is_a_declared_dependency():
    """既然是主路径，pyproject 必须声明它——不能只靠碰巧装上了。"""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "aiohttp" in pyproject, "aiohttp 未在 pyproject.toml 声明"


def test_aiohttp_stack_is_not_excluded():
    """反向守护：别让体积精简顺手把 aiohttp 全家排除掉。"""
    mod = _load_build_module()
    for package in ("aiohttp", "multidict", "yarl", "propcache", "frozenlist"):
        assert package not in mod.EXCLUDE_MODULES, (
            f"{package} 被排除了，HLS 下载会完全失效"
        )
