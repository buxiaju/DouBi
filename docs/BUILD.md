# 打包 Windows 可执行文件与安装包

> 配套脚本：`scripts/build_ico.py`（生成 .ico）/ `scripts/build_exe.py`（PyInstaller）
> / `scripts/build_installer.py`（NSIS 安装包）
> 产物：`dist/doubi-gui.exe`（onefile，约 235 MB）、`dist/doubi-gui/`（onedir，约 787 MB）
> 、`dist/DouBi-Setup-<version>.exe`（安装包，约 213 MB）
>
> 发给最终用户请用**安装包**（§6）；onefile 适合自己临时跑一份，onedir 是安装包的原料。

## 1. 为什么需要打包

Python 进程运行时，Windows 任务栏的「应用分组」图标（钉在任务栏左侧
那个 + Alt+Tab 切换时显示的）**永远显示 `python.exe` 的图标**——
蓝色终端窗口 + 黄蓝双蛇 logo。

这是 OS 层面的硬伤：
- 任务栏的「应用图标」从**进程对应 .exe 的资源段**读取
- Python 进程对应 `python.exe`，这个 .exe 的图标资源里就是双蛇 logo
- `QApplication.setWindowIcon(icon)` 只能改：
  - ✅ 窗口标题栏
  - ✅ Alt+Tab 切换时显示的窗口图标
  - ❌ **任务栏的应用分组图标**（这个 OS 层面读 .exe 资源）

唯一的解决：**把项目打包成真正的 .exe**，打包时把 .ico 嵌入 .exe 资源段。

## 2. 流程总览

```
icon_template.svg (QtSvg 安全的矢量模板)
   ↓
scripts/build_ico.py → icon.ico (6 档位 PNG 合集)
   ↓
scripts/build_exe.py --icon icon.ico → dist/doubi-gui.exe
   ↓
Windows 任务栏读取 dist/doubi-gui.exe 资源段 → 显示豆比图标
   ↓
scripts/build_installer.py + installer/doubi.nsi → dist/DouBi-Setup-<version>.exe
```

**两个脚本必须分两步**：
- `build_ico.py` 只产出 .ico 文件，~22 KB
- `build_exe.py` 用 .ico 作 `--icon` 参数，PyInstaller 把 .ico 嵌进
  .exe 资源段

要发给最终用户时再多一步：`build_installer.py` 用 NSIS 把 onedir 产物
包成安装程序（详见 §6）。

## 3. `scripts/build_ico.py` —— 矢量 SVG → 多档位 .ico

### 3.1 6 档位为什么是 16/32/48/64/128/256

Windows 任务栏 / 资源管理器 / 系统设置各需要不同尺寸：

| 尺寸 | 用在哪 |
| --- | --- |
| 16 | 资源管理器文件名旁的「小图标」 |
| 32 | **任务栏** + Alt+Tab |
| 48 | 大图标视图（资源管理器） |
| 64 | 高 DPI 屏幕的任务栏 |
| 128 | 大图标视图（系统设置） |
| 256 | Windows 10+ 任务栏（高 DPI 缩放后的实际显示尺寸） |

> **不是越多越好**：.ico 文件大小与档位数线性相关，6 档是「覆盖所有
> 实际使用场景 + 文件不过大」的甜点。Windows 任务栏没匹配的尺寸时会
> 自己缩放（**这就是位图锯齿的来源**——所以覆盖越全越好）。

### 3.2 为什么不依赖 PIL

`Pillow 12.3.0 + Python 3.13 + Windows` 触发
`STATUS_STACK_BUFFER_OVERRUN`（0xC0000409）崩溃。在 `scripts/build_ico.py`
里走 Qt + 手写 ICONDIR 绕开：

```python
import struct
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

# 1. 矢量渲染到 size×size → QImage
# 2. QImage.save(QBuffer, "PNG") → 内存 PNG
# 3. 按 ICONDIR / ICONDIRENTRY 格式拼成 .ico
```

**关键陷阱**：`QPixmap.save(QBuffer, "PNG")` 在
`QT_QPA_PLATFORM=offscreen` 下同样崩溃——**`QImage.save` 没事**。
这条经验写进注释提醒后来人。

### 3.3 .ico 文件结构

```
┌──────────────────────────────────────┐
│ ICONDIR (6 字节)                     │
│   reserved: u16 = 0                  │
│   type:     u16 = 1 (ICO)            │
│   count:    u16 = N (档位数)         │
├──────────────────────────────────────┤
│ ICONDIRENTRY[0] (16 字节)            │
│   width:  u8 = 16 (256 → 0)          │
│   height: u8 = 16                    │
│   color_count: 0 (无调色板)          │
│   reserved: 0                        │
│   planes: 1                          │
│   bit_count: 32 (ARGB)               │
│   bytes_in_res: u32 = PNG size       │
│   image_offset: u32 = 6 + 16*N       │
│ ICONDIRENTRY[1..N-1] ...             │
├──────────────────────────────────────┤
│ PNG[0] ... PNG[N-1]                  │
└──────────────────────────────────────┘
```

每张 PNG 嵌在文件后部，`image_offset` 指向它。Windows 按需挑最接近目标
像素的尺寸解码。Python 的 `struct` 就能写——不需要任何外部库。

### 3.4 用法

```bash
python scripts/build_ico.py
# → icon.ico  sizes=(16, 32, 48, 64, 128, 256)  total=22439 bytes
```

**检查产物**：
```bash
python -c "
from PySide6.QtGui import QImageReader
r = QImageReader('src/doubi/ui/resources/icon.ico')
print('size:', r.size())
print('frames:', r.imageCount())
"
# size: PyQt6.QtCore.QSize(256, 256)
# frames: 6
```

## 4. `scripts/build_exe.py` —— PyInstaller 打包

### 4.1 命令行

```bash
python scripts/build_exe.py                 # 默认 onefile + GUI 模式
python scripts/build_exe.py --onedir       # 拆目录（启动快，调试用）
python scripts/build_exe.py --console      # 带控制台窗口（默认 GUI 模式，无 console）
```

`--onefile` 把 Python runtime + 所有依赖打包成单个 ~235 MB .exe；启动时
会先解包到 `%TEMP%/_MEIxxxxx` 再跑（启动略慢 1-2 秒）。
`--onedir` 拆成 `dist/doubi-gui/doubi-gui.exe` + 大量 .dll/.pyd，
启动快、便于排查 dll 加载问题。

### 4.2 关键 PyInstaller 参数

```python
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--clean",
    "--name", "doubi-gui",
    "--specpath", str(ROOT),
    "--icon", str(ICON),                          # ★ 关键：嵌入 .ico 进 .exe 资源
    "--add-data", f"{SVG_TEMPLATE}{sep}doubi/ui/resources",  # SVG 模板进 .exe
    # ★ 0.3.0 新增：i18n JSON 词表（zh_CN.json / en.json）。
    # 漏了这行，打包后 GUI 就直接显示 nav.parse / app.title_suffix 这类
    # i18n key 名（见 CHANGELOG G7）。目标路径必须和 i18n._resolve_locales_dir()
    # 在 frozen 形态里用的 "doubi/ui/locales" 完全一致。
    "--add-data", f"{LOCALES_DIR}{sep}doubi/ui/locales",
    # ★ 0.3.1 新增：通用嗅探注入页面的 catch_lite.js。
    # 漏了这行，发布版一嗅探非平台链接就报「catch_lite.js 加载失败；
    # 安装包可能损坏」，即通用嗅探 100% 不可用（见 CHANGELOG M6.19）。
    "--add-data", f"{CATCH_LITE_JS}{sep}doubi/platforms/generic",
    "--collect-all", "qframelesswindow",          # 第三方 Qt 库的隐藏资源
    "--collect-all", "qfluentwidgets",
    "--paths", str(ROOT / "src"),
    "--collect-submodules", "doubi",              # 只收 .py，不收数据文件！
    str(launcher),                                # ★ 关键：自动生成的启动壳，见下文
]
```

> ⚠️ **`--collect-submodules doubi` 只收 Python 模块，不收 `.js`/`.json`/`.svg`
> 这类数据文件。** 名字里的 "collect" 容易让人以为它把整个包目录都搬进去了——
> 并没有。任何非 `.py` 资源都必须有自己的 `--add-data`。0.3.0 就是栽在这上面。

**需要强制收集的三类数据文件**（漏任何一个都会触发"源码里正常、打包后异常"类 bug）：

| 数据 | 参数 | 为什么必须手动加 | 代码侧对应 |
|---|---|---|---|
| `icon_template.svg` | `--add-data SRC → doubi/ui/resources` | 不是 Python 模块，PyInstaller 静态分析抓不到；图标系统运行时按路径 open | `src/doubi/ui/resources/__init__.py` 的 `ICON_SVG_PATH` |
| `locales/{zh_CN,en}.json` | `--add-data SRC → doubi/ui/locales` | i18n 翻译表是纯 JSON；漏加就表现为 GUI 出现 `nav.parse` 等英文 key（CHANGELOG G7 实锤） | `src/doubi/ui/i18n.py::_resolve_locales_dir()` |
| `catch_lite.js` | `--add-data SRC → doubi/platforms/generic` | 注入页面的 JS；**无兜底路径**，缺失即通用嗅探直接报错，不降级（CHANGELOG M6.19 实锤） | `src/doubi/core/sniffer.py::_load_catch_lite_js()` |

> **`importlib.resources` 不是免死金牌。** 它解决的是**路径**（冻结后仍能定位到
> `sys._MEIPASS` 下的目录），不解决**打包**（文件有没有被放进去）。两件事独立。
> `sniffer.py` 用的就是 `importlib.resources.files(...)`，路径逻辑完全正确，
> 照样炸——因为文件压根没进包。

> ✅ **已实测确认**：冻结环境下 `resources.files(pkg).joinpath(name)` **能**正确
> 读到 `--add-data` 投放的文件（PyInstaller 的 `FrozenImporter` 实现了
> `get_resource_reader`，把查找重定向到 `_MEIPASS`）。用一个最小 onedir 探针
> 单独验过：`frozen = True` / `RESULT = OK`。
>
> 注意**别拿 i18n 当先例佐证**：`i18n._resolve_locales_dir()` 的 frozen 分支走的是
> `sys._MEIPASS` **手工拼路径**，`importlib` 只是第 3 层兜底、在发布版从未被执行。
> 所以 M6.19 之前，本项目其实**没有任何**已验证的 `importlib.resources` 冻结先例。

**这类 bug 本地永远测不出来**：开发态 `importlib` / `Path(__file__)` 都解析到真实
`src/` 目录，文件当然在。只有冻结产物才暴露。所以拦截点只能放在**构建脚本**：
每个 `--add-data` 源都配一条 `is_file()` 预检（PyInstaller 对不存在的源
**只告警不报错**，不预检就会静默少文件），并由
`tests/test_packaging_slim.py` 的守卫测试 AST 扫描
`resources.files(pkg).joinpath(name)` 调用点、与 `--add-data` 目标集合求差，
新增资源自动纳入覆盖。

**运行时寻址必须匹配 frozen 路径**：打包后源码文件不再存在真实文件，`Path(__file__)`
指向 PYZ CArchive 内部的一个「假路径」，用它拼子目录是找不到任何文件的。
`i18n._resolve_locales_dir()` 因此走**三层 fallback**：

1. `frozen`（有 `sys.frozen` 且设了 `sys._MEIPASS`）：
   `sys._MEIPASS / "doubi" / "ui" / "locales"` → 正好落在 PyInstaller `--add-data` 的目标目录
2. 源码形态：`Path(__file__).parent / "locales"`（开发环境）
3. 兜底：`importlib.resources.files("doubi.ui").joinpath("locales")`（pip wheel / zipapp）

> 打包后如果要快速排查"locale 到底收没收进来"：onedir 就直接
> `dir dist\doubi-gui\_internal\doubi\ui\locales\`，能看到 `zh_CN.json` 就通过；
> onefile 可以临时 `set DOU_DEBUG_I18N=1` 启动，日志里会有 WARNING 级提示
> "PyInstaller frozen: _MEIPASS/locales 未找到"。

**`--icon src/doubi/ui/resources/icon.ico`** —— 没有这个参数，任务栏
图标就是 PyInstaller 默认的（也是 Python 默认的）。**这是任务栏图标
生效的唯一渠道**。

**入口用「自动生成的启动壳」，而不是 `--module`** ——

> ⚠️ 早期版本的本文档写的是 `--module doubi.ui.app`。**PyInstaller
> 根本没有这个选项**，6.22.2 会直接报
> `error: unrecognized arguments: --module`。入口只能是脚本路径。

但直接把 `src/doubi/ui/app.py` 当入口又会触发 §5.1 的相对导入崩溃：
它被当成顶层 `__main__` 解包，`doubi` 父包不存在。

`build_exe.py` 的解法是构建期生成一层极薄的启动壳
`_doubi_gui_launcher.py`（放在项目根，跑完即删）：

```python
import sys
from doubi.ui.app import main          # 绝对导入，不是相对导入

if __name__ == "__main__":
    sys.exit(main())
```

它在包**外面**，以绝对导入进包，于是 `doubi` 包结构被完整保留，
`app.py` 内部的 `from .theme import ...` 正常工作。代价同样是必须让
`src/` 在 sys.path 里，所以保留 `--paths src`。

**`--collect-all qframelesswindow` / `qfluentwidgets`** —— 这两个
第三方 Qt 库用 QRC 编译了图标 / 样式表 / 翻译文件作为 Python 模块属性
（`qframelesswindow.titlebar.__init__` 里有 `from . import _rc`），
PyInstaller 默认钩子抓不全。`--collect-all` 显式收齐所有子模块与
数据文件。**没有这个参数，标题栏 / fluent 控件会显示异常或崩溃**。

> ⚠️ 但 `--collect-all` 是把双刃剑：它会强收**每一个**子模块，包括代码
> 从没 import 过的 `multimedia` / `webengine` / `image_utils`，一路把
> QtWebEngineCore + QtMultimedia + PIL 拖进来（321 + 12.8 MB）。0.3.0 因此
> 追加了三类参数——`--exclude-module`（50 个）、浏览器目录按子项展开的
> `--add-data`（跳过 headless_shell）、ffmpeg 的 `--add-data`。**这三者
> 互相咬合，改动前务必先读 §4.5。**

**`--add-data icon_template.svg` —— 注意源路径与目标路径的写法**：

```python
f"{SVG_TEMPLATE}{sep}doubi/ui/resources"
#   ↑ 源文件（绝对路径）  ↑ Windows 是 ';'，POSIX 是 ':'
#                          ↑ 在 .exe 内的相对路径
```

PyInstaller 把源文件打包到 .exe 内，运行时用 `_MEIPASS` 临时目录
解包。Python 端用 `importlib.resources` 或 `__file__` 解析运行时
位置。`resources/__init__.py` 里：

```python
RESOURCE_DIR = Path(__file__).resolve().parent
icon_template_path = lambda: RESOURCE_DIR / "icon_template.svg"
```

打包后 `__file__` 指向 `_MEIPASS/doubi/ui/resources/__init__.py`，
`icon_template_path()` 返回的就是解包后的实际路径。**这是 QtSvg
找 SVG 的关键**——别用 cwd-relative 路径。

### 4.3 产物

```
dist/
└── doubi-gui/                         # onedir：687.4 MB / 1002 个文件
    ├── doubi-gui.exe
    └── _internal/
```

体积说明（0.3.0 精简后实测，onedir 口径）：

| 项 | 体积 | 能不能再砍 |
|---|---|---|
| `playwright_browsers/chromium-1234` | 430.3 MB | ❌ 通用嗅探的硬地板 |
| `playwright/driver`（其中 `node.exe` 88.3 MB） | 103.5 MB | ❌ Playwright 驱动进程必需 |
| `PySide6` | 92.3 MB | ⚠️ 已从 550.6 MB 砍下来，见 §4.5 |
| `tools/nm3u8dl`（含 ffmpeg.exe 10.91 MB） | 10.9 MB | ❌ 引擎直接调用 |
| Python 3.13 runtime + 其它依赖 + 业务代码 | 约 40 MB | — |

> 精简前是 **1501.8 MB / 4005 个文件**，一半以上是「装进来但从没被 import」
> 的死重量。完整取数、判据与三条不能动的约束见 §4.5。

**压缩**：onefile 模式 PyInstaller 默认开 LZMA 压缩（`--noupx` 时
不用 UPX），压缩比约 50%。要更小可加 `--upx-dir` 跑 UPX，但会拖慢
启动 2-3 秒，且偶尔触发杀毒软件误报。

### 4.4 启动时序

```
用户双击 dist/doubi-gui.exe
    ↓
Windows 读 .exe 资源段显示任务栏图标
    ↓
PyInstaller bootloader 解包到 %TEMP%\_MEIxxxxx\ (~1-2 秒)
    ↓
sys.path 包含 _MEIPASS（包含我们 --add-data 的 SVG 模板）
    ↓
执行 doubi.ui.app:main()
    ↓
set_theme("doubi") + 创建 MainWindow
    ↓
setWindowIcon(icon) + QApplication.setWindowIcon(icon)
    ↓
主窗口出现，标题栏 + 任务栏都已是豆比图标
```

**关键点**：onefile 解包需要时间，启动后头 1-2 秒内窗口不显示。
这是 PyInstaller 的硬限制（不是 bug），可以预先用闪屏掩盖——
`splash.show_splash(app)` 在主窗口创建前显示，详见 `ui/splash.py`。

### 4.5 体积精简：1501.8 MB → 678.5 MB（0.3.0）

**结果**：onedir 产物 **1501.8 MB / 4005 文件 → 678.5 MB / 881 文件**
（−823.3 MB，−54.8%）。分项：

> 本节数字是精简这一步的净效果。此后 M6.20 为修 HLS 下载又补进 aiohttp
> 全链（+8.9 MB / +121 文件），**当前实测值是 687.4 MB / 1002 文件**（§4.3）。
> 分开记是为了让「精简省了多少」和「现在有多大」各自可查，不互相污染。

| 分项 | 精简前 | 精简后 | 手段 |
|---|---|---|---|
| `PySide6` | 550.6 MB | **92.3 MB** | `--exclude-module` 排 38 个 Qt 模块 |
| `playwright_browsers` | 701 MB | **430.3 MB** | 不打包 `chromium_headless_shell`（270.7 MB） |
| `imageio_ffmpeg` | 83.6 MB | **0** | 换成仓库自带的 `ffmpeg.exe`（10.91 MB） |
| `PIL` | 12.8 MB | **0** | `--exclude-module PIL` |

#### 为什么会胖：`--collect-all` 的过度收集

`--collect-all qfluentwidgets` 会强行收进**每一个**子模块，不管代码有没有
import 它。于是三条无人问津的路径把整个 Qt 重型栈拖了进来：

| 拖油瓶 | 拖进来什么 | 代价 |
|---|---|---|
| `qfluentwidgets/multimedia/{media_player,video_widget}.py` | QtMultimedia | 数十 MB |
| `qframelesswindow/webengine/__init__.py` | QtWebEngineWidgets → QtWebEngineCore | **321 MB** |
| `qfluentwidgets/common/image_utils.py` | PIL | 12.8 MB |

QtWebEngineCore 一旦进依赖图，PySide6 的 hook 就会连带拽入
`Qt6WebEngineCore.dll`（194 MB）、`qtwebengine_devtools_resources.debug.pak`
（72.3 MB）、`qtwebengine_resources.pak`（11.1 MB）、`qtwebengine_locales`
（43.65 MB）。

#### 排除安全的判据

**判据是「运行时 `sys.modules` 里有没有」，不是「文件在不在包里」。** 三重取证：

1. `Grep` 全量 `src/`：除 `QtCore` / `QtGui` / `QtWidgets` / `QtSvg` 外无任何
   Qt 模块被 import。
2. 起真 GUI 后探测 `sys.modules`：QtWebEngine / QtMultimedia / QtQuick /
   QtQml / PIL **一个都没加载**。
3. 重打包后逐文件核对：`_internal` 里 **零个** `*webengine*` 残留
   —— 这条最关键，它证明了 `--exclude-module` 会连 hook 贡献的**数据文件**
   （`.pak` / locales）一起丢掉，而这是静态分析唯一答不出来的问题。

PIL 还有一层构造性保证——`qfluentwidgets` 自己就把它当**可选**依赖：

```python
# qfluentwidgets/components/widgets/acrylic_label.py
try:
    from ...common.image_utils import gaussianBlur
    isAcrylicAvailable = True
except ImportError:
    isAcrylicAvailable = False
    def gaussianBlur(imagePath, ...):
        return QPixmap(imagePath)          # 优雅降级
```

而 DouBi 全仓 `Acrylic` / `gaussianBlur` / `isAcrylicAvailable` 零引用，
所以排掉 PIL 连降级路径都走不到。

#### 三条不能动的约束

这三条互相咬合，**动其中任何一条都会让发布版在用户机上炸**：

**① 两处 `chromium.launch` 必须都带 `channel="chromium"`**

Playwright 1.62 的 `headless=True` 默认要找单独的
`chrome-headless-shell.exe`（就在被我们跳过的 270.7 MB 目录里），缺了直接
launch 失败。`channel="chromium"` 改用完整 Chromium 内置的 "new headless"。
两处调用点：`core/sniffer.py`、`core/auth/browser_login.py`。

已用**打包产物本身**验证两种模式都能起：
`headless=True → HeadlessChrome/151.0.0.0`、`headless=False → Chrome/151.0.0.0`。

**② `EXCLUDE_MODULES` 只在「没人 import 它们」时才安全**

以后若要引入视频预览、内嵌浏览器、PIL 图像处理，必须先从
`scripts/build_exe.py::EXCLUDE_MODULES` 里删掉对应项，否则打包能过、
运行时 `ImportError`。

**③ ffmpeg 必须继续靠 `--add-data` 带进去**

`installer/doubi.nsi` 只有一条 payload 规则
（`File /r "${SRC_DIR}\*.*"` 覆盖 `dist/doubi-gui`），仓库里的 `tools/`
**不进安装包**。所以排掉 `imageio_ffmpeg` 之后，
`build_exe.py::FFMPEG_EXE` 的那行 `--add-data` 是发布版**唯一**的 ffmpeg
来源，还配了构建期 pre-flight 检查（文件不存在就直接失败，不生成残废产物）。

四个引擎统一走 `engines/_subproc.py::find_bundled_ffmpeg()`，寻址
**`_MEIPASS` 优先**——frozen 形态下从快捷方式启动时 `Path.cwd()` 常常是
`C:\Windows\System32`。已模拟 frozen 布局（设 `sys._MEIPASS` + `sys.frozen`
+ `os.chdir(r'C:\Windows\System32')`）验证四个解析器全部返回打包内路径。

#### 守卫测试

上述约束全部由 `tests/test_packaging_slim.py`（13 条）锁死，其中 3 条做过
变异验证（故意改坏约束，确认对应测试变红且理由正确）：

- `test_there_are_exactly_two_chromium_launch_sites` — 新增第三处 launch 会被抓住
- `test_every_chromium_launch_pins_channel_to_chromium` — AST 检查，不是 grep
- `test_no_source_file_imports_an_excluded_module` — 排除项与实际 import 冲突即报
- `test_excluding_imageio_ffmpeg_requires_bundling_a_replacement` — 约束 ③
- `test_bundled_ffmpeg_probes_meipass_first` — 寻址顺序

## 5. 踩过的坑

### 5.1 入口报错：`ImportError: attempted relative import`

```
File "app.py", line 23, in <module>
    from . import GUIUnavailableError, is_gui_available
ImportError: attempted relative import with no known parent package
```

**根因**：直接传文件路径 `src/doubi/ui/app.py` 给 PyInstaller，onefile
模式把 `app.py` 当顶层脚本解包，`doubi` 父包不存在。

**修法**：不要把包内文件当入口。`build_exe.py` 在构建期生成一层位于包
**外面**的启动壳 `_doubi_gui_launcher.py`，用绝对导入 `from doubi.ui.app
import main` 进包，包结构就被完整保留了，详见 §4.2。

> ⚠️ 本文档早期版本写的是「用 `--module doubi.ui.app`」。**PyInstaller
> 没有 `--module` 选项**，6.22.2 会直接报 `unrecognized arguments`。
> 入口只能是脚本路径，所以才需要启动壳。

### 5.2 任务栏图标不显示

`--icon` 参数没传，或传了路径错。**检查产物**：

```python
import PyInstaller.utils.win32.icon as icon
print(icon.__file__)
# 找到 PyInstaller 用的 .ico 转换逻辑在哪里
```

PyInstaller 内部把 .ico 重新封装成多档位 + 调 `UpdateResourceW` API
写入 .exe。如果 .ico 文件本身有 bug（比如 ICONDIR / ICONDIRENTRY
格式错），PyInstaller 会**静默忽略**——不报错，.exe 资源段里就没图标。

**判据**：解包后用 7-Zip 看 .exe 的「资源 > Icon」段，应该有 6 个 PNG。
或者用 NirSoft ResourcesExtract / Windows 资源管理器查看。

### 5.3 启动后弹「Unhandled exception in script」

```
Unhandled exception in script
```

PyInstaller 解包完后启动 Python 子进程，子进程炸了会显示这个窗口。
**必须从命令行启动 .exe**才能看到完整 traceback：

```bash
.\dist\doubi-gui.exe
```

会显示具体的 import error / 缺失模块 / 路径问题。`--console` 模式
打包会直接看到 console 窗口输出。

### 5.4 `--collect-all` 漏了导致 fluent 控件异常

```
AttributeError: type object 'FluentWindowBase' has no attribute 'xxx'
```

或：
- 标题栏图标位置错了
- 翻译文件 `translations/qfluentwidgets_zh_CN.qm` 缺失
- 自定义样式表 QRC 文件没被收

**修法**：对所有第三方 Qt 库都加 `--collect-all <pkg>`，不要相信
PyInstaller 默认钩子能搞定一切。

### 5.5 Windows Defender 误报

PyInstaller onefile 产物经常被 Windows Defender / 360 / 火绒标记
成「可疑程序」或「木马」。这是 PyInstaller 打包产物的固有问题——
loader 的行为模式与正常 .exe 不同，启发式引擎容易误报。

**缓解**：
- 提交到 VirusTotal 让多家引擎打分，通常 5/72 误报就上线
- 给 .exe 申请代码签名证书（EV 证书可获得即时信誉）
- 改用 `--onedir` 模式（产物文件多，反病毒引擎特征更接近「正常程序」）

## 6. NSIS 安装包

`.exe` 只解决「能跑」，安装包解决「能装」——开始菜单、桌面快捷方式、
控制面板里的卸载项，这些都得靠安装器写注册表和 `.lnk`。

### 6.1 一条命令

```bash
python scripts/build_installer.py              # onedir 构建 + 编译安装包
python scripts/build_installer.py --skip-build # 复用现有 dist/doubi-gui/
```

产物：`dist/DouBi-Setup-<version>.exe`（当前 0.3.0 实测 **219.0 MB**）。

体积精简（§4.5）之前这里是 441.3 MB；onedir 从 1501.8 MB 砍到 678.5 MB 后，
安装包同步降到 215.5 MB（**−225.8 MB / −51.2%**），已回到 0.1.0（213 MB）的量级。
其后 M6.20 补进 aiohttp 全链（`--collect-all aiohttp/multidict/yarl`），
onedir 回涨到 687.4 MB、安装包到 219.0 MB——这 +3.5 MB 是 HLS 下载的必需代价，
不是回退：打包后的 ffmpeg 无 TLS 后端，aiohttp 是唯一可用的 https 分片下载路径（见 CHANGELOG M6.20）。

链路是 `build_installer.py` → `build_exe.py --onedir` → `makensis`：

```
pyproject.toml:version（AST 解析，单一真源）
    ↓ 读出后同步写入 src/doubi/__init__.py:__version__
       （GUI APP_VERSION / REST /health / NSIS / pyproject 全部派生自它，
        杜绝手抄漂移。UI 标题栏显示的版本号就是 __init__.__version__）
scripts/build_exe.py --onedir  →  dist/doubi-gui/（1002 文件，总 687.4 MB，含精简后的 Playwright Chromium）
    ↓ /DSRC_DIR=<绝对路径>
tools/nsis/nsis-3.11/makensis.exe  installer/doubi.nsi
    ↓ LZMA solid 压缩；SetDatablockOptimize off（见 §6.4 规则）
      687.4 MB（720,833,119 B）→ 压缩数据 229,593,643 B → 最终安装包
      229,657,135 B（219.0 MB，31.8%）
      单线程 makensis 约 5-8 分钟
dist/DouBi-Setup-0.3.0.exe
```

> 压缩率从 29.3% 升到 31.7% 是预期的：被砍掉的 WebEngine `.pak`、
> headless_shell、PIL 等本来就是**高可压缩**的重复内容，剩下的
> Chromium/node.exe 二进制熵更高，压不动。所以安装包的降幅（−51.2%）
> 略小于 onedir 的降幅（−54.8%）。

**版本号只有一个源**。`build_installer.py` 从 `src/doubi/__init__.py` AST
静态解析 `__version__`（不是抄 pyproject 里的动态 `attr =`），再用
`/DPRODUCT_VERSION=` 注进 NSIS。所以 GUI APP_VERSION / REST `/health` /
NSIS 安装包 `VIProductVersion` 三处永远一致，绝不用手抄。
`VIProductVersion` 必须是四段纯数字，因此写成 `"${PRODUCT_VERSION}.0"`
（0.3.0 → 0.3.0.0）。`VIAddVersionKey /LANG=2052` —— 2052 是简体中文 LCID。

**NSIS 不在 PATH 里**（便携版），所以脚本按顺序探测
`tools/nsis/nsis-3.11/makensis.exe` 和 `.../Bin/makensis.exe`。

### 6.2 makensis 调用要点

```python
cmd = [
    str(makensis),
    "/INPUTCHARSET", "UTF8",            # ★ 不加就是满屏乱码
    f"/DPRODUCT_VERSION={version}",
    f"/DSRC_DIR={SRC_DIR}",             # ★ 必须绝对路径
    f"/DOUT_FILE={out_file}",
    str(NSI),
]
```

- `/INPUTCHARSET UTF8`：`.nsi` 里全是中文字符串，不指定 makensis 会
  按系统 ACP 猜编码，猜错整个安装界面就是乱码。
- **传绝对路径**：NSIS 解析相对路径是相对 `makensis` 的**工作目录**，
  不是 `.nsi` 文件所在目录。`.nsi` 里的默认值也因此用 `${__FILEDIR__}` 兜底。
- `VIProductVersion` 必须是**四段纯数字**，所以写成 `"${PRODUCT_VERSION}.0"`。
- `VIAddVersionKey /LANG=2052` —— 2052 是简体中文 LCID。

### 6.3 installer/doubi.nsi 的设计取舍

**装当前用户，不要管理员权限**：

```nsis
InstallDir "$LOCALAPPDATA\DouBi"
RequestExecutionLevel user
```

`RequestExecutionLevel user` 免 UAC 弹窗，代价是注册表**只能写
HKCU**——写 HKLM 会静默失败。控制面板卸载项因此落在
`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DouBi`。

**关进程用 tasklist，不用 nsProcess**：便携版 NSIS 只带了
`nsExec.dll`，没有 `nsProcess.dll`，所以拿 `tasklist` 的退出码当谓词：

```nsis
nsExec::Exec 'cmd /c tasklist /FI "IMAGENAME eq ${APP_EXE}" /NH | find /I "${APP_EXE}"'
Pop $0
${If} $0 != 0
  Return          ; 没在跑，直接过
${EndIf}
...
nsExec::Exec 'taskkill /F /IM "${APP_EXE}" /T'
Pop $0
Sleep 1500        ; taskkill 返回 ≠ 文件句柄已释放
```

`Sleep 1500` 不是玄学：`taskkill` 返回只代表信号已发，句柄回收是异步的，
不等就会在覆盖 `_internal/` 时撞上「文件被占用」。

这段逻辑安装器和卸载器都要用，NSIS 没有跨 installer/uninstaller 共享
函数的机制，于是把函数体包成宏、用 `un` 前缀参数化，插两次：

```nsis
!insertmacro EnsureAppClosed ""
!insertmacro EnsureAppClosed "un."
```

**卸载不删用户数据**。`~/.doubi` 里是 cookie、配置、下载数据库，删掉
就是数据丢失，所以放在 `Section /o`（默认不勾）里，让用户显式选择。
主卸载段收尾用的是 `RMDir "$INSTDIR"` 而**不是** `RMDir /r`——用户自己
往安装目录扔的文件不该被连带删掉。

**`EstimatedSize` 要自己算**，NSIS 不会填：

```nsis
${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
IntFmt $0 "0x%08X" $0
WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"
```

单位是 KB。0.1.0 基线写入 806347，对应 787 MB；0.3.0 引入 Playwright Chromium
后安装目录约 1.57 GB，`${GetSize}` 会自动重新计算。

### 6.4 NSIS 构建期两条硬规则（0.3.0 integrity fail 事故后新增，绝不能丢）

**规则 1：`installer/doubi.nsi` 里永远 `SetDatablockOptimize off`**（在
`SetCompressor /SOLID lzma` 之前）。

```nsis
; 0.3.0 事故修复：1.57 GB 大安装包 NSIS 3.11 datablock optimizer 偶发 launcher
; 预存 CRC 头与实际文件 CRC 不一致，用户侧双击即弹 "NSIS Error — Installer
; integrity check has failed"。关掉 optimizer 体积从 ~345 MB → 441 MB (+28%)，
; 但 makensis 日志保证显式打印 "CRC (0xXXXXXXXX): 4 / 4 bytes"（launcher CRC
; 真写进 PE 头），永不触发 integrity check。
SetDatablockOptimize off
SetCompressor /SOLID lzma
```

> 体积精简（§4.5）后源目录只剩 678.5 MB，但**这条规则依然不许动**。
> 事故的触发条件是 optimizer 的块合并逻辑本身，不是「包够大才会犯」——
> 体积变小只是降低了概率，没有修掉 bug。0.3.0 精简后重打的
> 215.5 MB 安装包同样是在 `SetDatablockOptimize off` 下编译并验证通过的。

> 为什么不用 `NCRC`？`/NCRC` 只是让 NSIS launcher 跳过自校验运行，**并没有
> 修 bug**，文件被真的篡改时也会静默放过（安全退化），企业安全软件还会
> 把「跳过自校验的 NSIS exe」当木马。正确做法是从源头保证 CRC 头正确。

**规则 2：makensis exit 0 后，必须再等「文件大小连续 10 秒不变」才允许算哈希。**

原因三层叠加：
- NSIS 关闭 `Compressed data:` 流后，还有 PE 尾 CRC/footer 要写进文件最后 4KB
- Windows 写缓存 + Defender/火绒钩子会在句柄 close 之后再异步刷字节
- 异步构建脚本（前次的后台 job）非常容易「`ls dist/` 看到文件存在」就以为完成了——实际 SHA256 对 NSIS 写一半的快照算出来的，用户拿到 exe 立刻 integrity fail

最小可落地 Python 实现（发布流程建议固定）：
```python
def wait_stable(p: Path, window_sec: float = 10.0, poll_sec: float = 1.5):
    last_size, last_change = -1, time.time()
    while True:
        cur = p.stat().st_size if p.exists() else -1
        if cur != last_size:
            last_size = cur
            last_change = time.time()
        if time.time() - last_change >= window_sec and cur > 0:
            return cur
        time.sleep(poll_sec)
```

验证 makensis 真的写了 CRC footer（日志里一定要有下面两行，缺任何一行都不要发布）：
```
CRC (0x5291D80F):                  4 / 4 bytes
Total size:                225926086 / 711750527 bytes (31.7%)
```

### 6.5 静默验证配方

手工点安装向导没法反复跑，用静默模式装到隔离目录：

```powershell
# 装（/D= 必须是最后一个参数，且不能加引号；<version> 替换为例如 0.3.0）
.\dist\DouBi-Setup-<version>.exe /S /D=$env:LOCALAPPDATA\DouBi_VerifyTest

# 查注册表
Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DouBi"

# 卸（故意让程序开着，以此检验 EnsureAppClosed）
& "$env:LOCALAPPDATA\DouBi_VerifyTest\uninstall.exe" /S
```

实测结论（0.3.0 当前 **219.0 MB** 安装包，即 M6.20 补进 aiohttp 全链后重打的那份）：
安装/卸载均退出码 0；落盘 **1003 个文件 / 687.4 MB**（1002 个源文件 + `uninstall.exe`），与 `dist/doubi-gui/`
逐项吻合；`*headless_shell*` 残留 **0 个**，`*webengine*` 按**文件**计也是 **0 个**
（`-Filter *webengine*` 会命中 `_internal\qframelesswindow\webengine\` 这个**目录名**，
里面只有一个 756 B 的 `__init__.py`；真正的重物 `Qt6WebEngineCore.dll` /
`qtwebengine_resources.pak` / `qtwebengine_devtools_resources.debug.pak` /
`QtWebEngineCore.pyd` 四项全为 0——查残留时要按文件数而非条目数判定，否则会误报）；
注册表 `EstimatedSize` 自动重算。`_internal` 下 `_ssl.pyd`(177.7 KB) / `_socket.pyd`(84.7 KB)
与 aiohttp 链的 4 个 `.pyd` 齐备（`_http_parser` 254.5 KB、`_http_writer` 42.5 KB，
multidict / yarl / propcache / frozenlist 各 1 个），这是 https 分片下载能跑的前提。
装出来的 `doubi-gui.exe` 启动后标题栏为「豆比下载 0.3.0 · 多平台视频下载器 - DouBi」、
`Responding=True`、内存 152.1 MB。卸载（**故意让程序开着**以检验 `EnsureAppClosed`）
后安装目录、HKCU 键、开始菜单、桌面快捷方式全部清空，残留进程 0 个，
而 `~/.doubi` 完好保留。

### 6.6 编译像卡住了？先确认再等

LZMA solid 压缩 1.57 GB 是单线程的，中途**几分钟没有任何输出**是正常的。
别急着 Ctrl-C，先看它是真在干活还是真死了：

```powershell
Get-Process makensis | Select-Object CPU, WorkingSet   # CPU 时间应持续增长
Get-ChildItem "$env:TEMP\ns*.tmp"                      # 暂存 datablock 会涨到 ~1.5 GB
```

CPU 在涨、临时文件在涨，就是在压缩。makensis 退出前日志最后一行通常是
`Compressed data: ...`，真正结束后还会追加「CRC / Total size / OK」三行。

## 7. 验证清单（0.3.0 修订版）

发版前手动检查（不在单元测试里）：

- [ ] **模拟 CI 依赖集跑一遍全量测试**（0.3.0 CI 红了才补的一条，见
      CHANGELOG M6.21 / DEVELOPMENT §15.1）。本地装齐 extras + 惯用
      `-m "not slow"`，比 CI 的「只有基础依赖 + 无 mark 过滤」**小一圈**，
      所以「测试里裸导入可选依赖」这类失效模式在本地必然漏过去。做法：临时脚本
      往 `sys.meta_path` 插一个 Blocker，对 `pydantic` / `fastapi` / `uvicorn` /
      `PySide6` / `qfluentwidgets` / `qasync` / `psutil` 抛 `ModuleNotFoundError`
      并清掉 `sys.modules` 里的同名模块，再 `pytest.main(["-q", "--maxfail=5"])`。
      判绿标准不是「没红」，而是 **passed+failed 与 CI 相等、skipped 也相等**
      （0.3.0 基线：`629 passed / 146 skipped`）
- [ ] `dist/doubi-gui.exe`（onefile 便携版）文件存在（精简后未重新量化，见 §4.5）
- [ ] onedir `dist/doubi-gui/doubi-gui.exe` 存在，整个目录约 **1002 文件 / 687.4 MB**
- [ ] **侧签哈希与 exe 实际匹配**：`dist/DouBi-Setup-<v>.exe.sha256` 和
      `SHA256SUMS.txt` **不会**随重打包自动更新，重打后必须重写，否则会留着上一版
      的哈希（0.3.0 就发生过：exe 已是新的，侧签还是 M6.17 的 `e833f155…`，
      照它校验必然失败）。用两种工具交叉验证：
      `(Get-FileHash dist\DouBi-Setup-0.3.0.exe -Algorithm SHA256).Hash` 与
      `certutil -hashfile dist\DouBi-Setup-0.3.0.exe SHA256`
- [ ] **打包期 i18n 收集验证（onedir）**：`dir dist\doubi-gui\_internal\doubi\ui\locales\` 能看到 `zh_CN.json`、`en.json`（CHANGELOG G7 回归检查）
- [ ] 双击启动 → 闪屏 → 主窗口出现
- [ ] **GUI 翻译正常自检（2 条）**：① 标题栏显示 `豆比下载 0.3.0 · 多平台视频下载器`（不是 `app.title_suffix`）；② 左侧导航文字是「解析 / 下载 / 历史 / 设置」（不是 `nav.parse`）
- [ ] **任务栏左下角应用图标是豆比**（不是 Python 双蛇）
- [ ] 标题栏左上是豆比（28px，与 M5+ 期望一致）
- [ ] 切换主题 → 标题栏图标换色
- [ ] 打开「关于」对话框 → 标题栏 + 任务栏分组图标都是豆比
- [ ] 打开「扫码登录」对话框 → 标题栏 + 任务栏分组图标都是豆比
- [ ] 关闭窗口 → 进程正常退出，无残留
- [ ] 在资源管理器中右键 .exe → 「属性」看到「豆比」图标
- [ ] 标题栏版本号与 `src/doubi/__init__.py:__version__` 一致（单一真源，杜绝 UI 0.6.0 / 安装包 0.1.0 那种漂移）

安装包额外检查（0.3.0 新增三条，CHANGELOG G8 integrity fail 回归检查）：

- [ ] `dist/DouBi-Setup-<version>.exe` 存在，**约 219 MB**（0.3.0 当前基线：
      精简后 215.46 MB，M6.20 补 aiohttp 全链后 **219.02 MB**；精简前是 441 MB。
      如果拿到的是 345 MB 那一档，说明 `SetDatablockOptimize` 被打开了，不要发——见 §6.4）
- [ ] **发布前 CRC/footer 证据**：makensis 构建日志里显式有 `CRC (0xXXXXXXXX): 4 / 4 bytes` 和 `Total size: ...` 两行
- [ ] **双击不弹 integrity check fail**：首次运行安装包，NSIS launcher 自校验通过（正常进入中文安装向导）
- [ ] **侧签 SHA 校验通过**：PowerShell 执行
  ```powershell
  $e=(Get-Content dist\DouBi-Setup-0.3.0.exe.sha256).Trim()
  $a=(Get-FileHash dist\DouBi-Setup-0.3.0.exe -Algorithm SHA256).Hash.ToLower()
  $e -eq $a   # 必须 $true
  ```
- [ ] 安装过程无 UAC 弹窗（当前用户安装）
- [ ] 安装界面中文无乱码
- [ ] 控制面板「应用和功能」里能看到「豆比下载 <version>」，大小正确
- [ ] 开始菜单 + 桌面快捷方式可用
- [ ] 程序开着时卸载 → 提示并自动结束进程，卸载成功
- [ ] 卸载后目录 / 注册表 / 快捷方式零残留，`~/.doubi` 仍在

发布后线上核对（0.3.0 事故后新增，见 §8.3 / §8.5）：

- [ ] **标签指向 release commit**：`git log -n 1 --oneline vX.Y.Z` 等于那条
      `release: X.Y.Z` 提交（错位会让 Release 的 Source code 压缩包装旧代码）
- [ ] **标签是 annotated**：`git cat-file -t vX.Y.Z` 返回 `tag` 而非 `commit`
- [ ] **远端分支已同步**：`git rev-list --left-right --count Github/master...HEAD`
      输出 `0	0`
- [ ] **线上资产哈希 == 本地**：Release 资产的 `digest`（`sha256:...`）与本地
      `Get-FileHash` 一致——不一致说明被 CI 重建的产物覆盖过
- [ ] **Release 正文完整**：亮点 / 安装 / **校验 SHA256** / 已知限制 四段都在
      （0.3.0 粘贴时被截断，后三段全丢）

## 8. CI / 自动发布

CI 已就位——见 `.github/workflows/build.yml`（`build-installer`）。
工作流在 `windows-latest` runner 上跑，分两段：

**测试段**——`pip install .` + `pytest --maxfail=5`，`QT_QPA_PLATFORM=offscreen`
让无头环境也能跑 GUI 类测试（PySide6 缺失时自动 skip）。超 5 个失败
直接终止，避免花 25 分钟跑完一整轮注定红的测试。

> **CI 不装任何 extras**，只有 `pip install .` 的基础依赖 + `pytest
> pytest-asyncio ruff`。也就是说 `fastapi` / `pydantic` / `uvicorn` /
> `PySide6` 在 runner 上**都不存在**，测试里凡是会走到这些包的地方必须有
> `pytest.importorskip` 守卫，否则**报错**而不是跳过。0.3.0 就因为
> `test_config_forwarding.py` 漏了这个守卫，让 `v0.3.0` 标签上留了一次红色
> CI（详见 CHANGELOG M6.21、约定见 DEVELOPMENT §15.1）。
>
> 另外 CI 的 pytest **不带 `-m "not slow"`**，测试集与本地惯用口径不等价：
> `test_theme_apply_gui.py`（`gui` + `slow`）在 CI 因缺 PySide6 被 skip，
> 在本地却会真起 Qt 事件循环并长时间挂住——所以 CI 45s 跑完，本地 10 分钟+。
> 想不动测试就闭掉这个缺口，只有两条路：给 CI 装齐 extras（变慢），或者把
> §7 那条「模拟 CI 依赖集」检查当成发版前必做项。

**打包段**——`python scripts/build_installer.py`，链路就是 §6.1 的
`build_installer.py → build_exe.py --onedir → makensis`，与本地完全一致。
产物定位用 `Get-ChildItem` 而不是硬编码文件名（版本号单一真源在
`src/doubi/__init__.py:__version__`，`pyproject.toml` 用
`dynamic = ["version"]` + `attr:` 静态读取它，workflow 里不抄版本号）。

**SHA256**——`Get-FileHash -Algorithm SHA256` 生成
`DouBi-Setup-<version>.exe.sha256`，与安装包一起作为 artifact 上传
（保留 90 天）。下载者用 `certutil -hashfile ... SHA256` 或
`Get-FileHash` 自行核验。

> **格式分歧（待统一）**：CI 写的是 `<exe>.sha256  <hash>`（`Out-File
> -Encoding ascii -NoNewline`），本地 `build_installer.py` 写的是标准
> `sha256sum` 格式 `<hash> *<filename>` + LF。两种格式混进同一个 Release
> 会让校验方困惑（`sha256sum -c` 只认后者）。§7 清单里的那段
> `$e -eq $a` 校验脚本假设的是**本地**格式，直接拿去校验 CI 产物会失败。

**触发**：

| 触发方式 | 行为 |
| --- | --- |
| 推送 `v*` 形式的 tag（如 `v0.1.0`） | 测试 + 打包 + 上传 artifact + **创建 GitHub Release**（draft，发版动作由人触发） |
| `workflow_dispatch` 手动 dispatch | 测试 + 打包 + 上传 artifact，**不**创建 release——用来验证「现在的 master 分支能不能成功打包」 |

**Release notes**用 `generate_release_notes: true`，让 GitHub 根据
commit 历史自动生成；仓库里有手写的 `docs/CHANGELOG.md`，PR description
也够用，不再硬编码进 workflow。

**为什么不换 linux runner**：NSIS 用 `tools/nsis/makensis.exe`（Windows
二进制），PySide6 wheel 也是 Windows 风格。换 runner 会让打包工具链
不通用，触发非 Windows 特有的 flakiness，得不偿失。

**dev / nightly 渠道**（`--onedir` 裸目录打 zip）尚未接入 workflow——
本地可手动 `python scripts/build_exe.py --onedir` 跑一份，跳过 10 分钟
的 LZMA 压缩。

### 8.1 仓库拓扑：两个远端，名字都不是默认的

```
Github  git@github.com:buxiaju/DouBi.git      (fetch / push)
origin  https://gitee.com/buxiaju/dou-bi.git  (fetch / push)
```

三个反直觉的点，每一个都能让你把代码推错地方：

1. **GitHub 远端叫 `Github`（首字母大写），不叫 `origin`**。`origin` 是
   Gitee。
2. **默认分支是 `master`，不是 `main`**。
3. **本地 `master` 的 upstream 是 `origin/master`（Gitee）**。所以裸跑
   `git push` 会推到 Gitee 去。推 GitHub 必须显式写远端和 refspec：

```powershell
git push Github master:master
```

同步到两个远端就分别推两次；本文档不建议给 `Github` 设 upstream，因为
「默认推 Gitee」是这个仓库的既有约定，改掉会让肌肉记忆失效。

### 8.2 SSH 推送配置

远端已是 SSH 形式（`git@github.com:...`）。若拿到的是新机器或远端还是
HTTPS，按下面走：

```powershell
# 1. 切成 SSH（fetch/push 一起改）
git remote set-url Github git@github.com:buxiaju/DouBi.git

# 2. 验鉴权（用系统 OpenSSH：C:\Windows\System32\OpenSSH\ssh.exe）
ssh -T git@github.com
# → Hi buxiaju! You've successfully authenticated, but GitHub does not provide shell access.
```

**`ssh -T` 退出码是 1，这是成功不是失败**——GitHub 永远拒绝 shell，所以
必然非零退出。判据是那句 `Hi <user>!`，不要看退出码。

同理，**PowerShell 里 git 的正常输出会被渲染成红色 `NativeCommandError`**，
因为 git 把进度信息写 stderr。判据是退出码 + refspec 那一行，例如
`c5913c5..13f3393  master -> master` 就是推成功了。别被红字骗去"修"一个
本来没坏的东西。

推送后核对远端是否真的一致（`0	0` 表示不落后不超前）：

```powershell
git fetch Github
git rev-list --left-right --count Github/master...HEAD
```

### 8.3 发布顺序：先推 commit，再打 tag（顺序错了会出事故）

**0.3.0 真实事故**：`v0.3.0` 标签指向的是 `c5913c5 fix(ci): 修复 0.2.0
发版 CI 测试集合失败`，而不是 `13f3393 release: 0.3.0 ...`。根因是**在
release commit 推上去之前就建了标签**。

后果不只是难看：GitHub Release 页面的 **Source code (zip/tar.gz) 是按
标签解析的**（`zipball_url` / `tarball_url` 同理）。标签错位 =
**任何人从 Release 下载源码都拿到旧版本代码**，而安装包资产却是新的，
两者对不上。`git describe` 做版本考古也会算错。

正确顺序：

```powershell
# 1. 先确认工作区干净、版本号已改
git status --short                       # 必须为空
Select-String -Path src\doubi\__init__.py -Pattern "__version__"

# 2. 提交并推送 commit
git commit -m "release: X.Y.Z - <摘要>"
git push Github master:master

# 3. 确认远端 master 已就位，再打标签（annotated，不要轻量标签）
git log -n 1 --oneline Github/master
git tag -a vX.Y.Z -m "DouBi X.Y.Z"
git push Github vX.Y.Z

# 4. 回验标签落点必须等于 release commit
git log -n 1 --oneline vX.Y.Z
git cat-file -t vX.Y.Z                   # 期望 tag（annotated）而非 commit
```

用 `-a`（annotated）而非轻量标签：轻量标签没有创建者、时间、说明，
`git cat-file -t` 返回 `commit`，事后无法区分"谁在什么时候发的版"。

### 8.4 标签打错了怎么补：先掐掉 CI 触发器

改标签只能 `git tag -f` + 强推，但 **`.github/workflows/build.yml` 的
触发条件是 `on: push: tags: ["v*"]`**。强推标签会重跑整条 CI，最后
`softprops/action-gh-release@v2` 会对已存在的 Release 执行 update，
**把 CI 现场构建的 exe 覆盖上去**。

NSIS 打包不是可复现构建，新 exe 的 SHA256 必然不等于你已经手工验证并
写进 release notes 的那个哈希。于是「已发布且校验过的安装包被一个未经
验证的构建替换，而正文里的哈希值对不上」——这是最坏情况。

所以安全路径是**先让触发器失效，再动标签**：

```powershell
# 1. 临时改 build.yml：注释掉 on.push.tags，或给 release 步骤加 if: false
#    提交并推送这个改动

# 2. 移动标签
git tag -f -a v0.3.0 13f3393 -m "DouBi 0.3.0"
git push Github v0.3.0 --force

# 3. 确认 CI 没被触发、Release 资产哈希未变，再把 build.yml 改回来
```

只想核对而不想动手时，可以先查线上真实状态（资产 `digest` 字段就是
`sha256:...`，直接和本地 `Get-FileHash` 比）：Release API 的
`get_release_by_tag` 能一次看到 `target_commitish`、`draft`、
`created_at`（= 标签创建时间，能反推标签是不是建早了）和每个资产的
`digest`。

### 8.5 手动发布 Release 的填写要点

| 字段 | 值 |
| --- | --- |
| Tag | `vX.Y.Z`（必须已指向 release commit，见 §8.3） |
| Target | `master` |
| Title | `DouBi X.Y.Z — <一句话卖点>` |
| Set as latest release | ✔ |
| Set as pre-release | ✘ |

正文必备四段：亮点 / 安装（含静默安装命令）/ **校验 SHA256（把哈希值
写进正文）** / 已知限制。

> **0.3.0 教训**：正文粘贴时被截断，`静默安装`、`校验（SHA256）`、
> `已知限制` 三段全丢了，等于下载者拿不到官方哈希做比对。**发布后务必
> 回到页面把正文从头到尾读一遍**，长正文尤其容易在粘贴时截断。

资产只能传文件，**目录传不了**——`dist\doubi-gui\`（onedir，1002 文件）
不是可上传对象，要发便携版得先打成 zip 或用 onefile 的
`dist\doubi-gui.exe`。0.3.0 实际只传了三个文件：

```
DouBi-Setup-0.3.0.exe          229,657,135 bytes   # 219.02 MB
DouBi-Setup-0.3.0.exe.sha256   88 bytes
SHA256SUMS.txt                 88 bytes
```

> **同名资产不能共存**：M6.20 修下载链路后安装包重打过一次
> （215.46 MB / `225,926,086` bytes → **219.02 MB / `229,657,135` bytes**），
> 换资产必须**先删线上旧文件再上传**，否则同名冲突。换完记得同步改正文里的
> 体积与 SHA256——正文哈希和资产 `digest` 不一致比体积写错严重得多。

## 9. 跨平台

当前 `scripts/build_exe.py` 是 Windows only：
- `sep = ";"`（Windows `--add-data` 分隔符）
- `.ico` 是 Windows 专属

macOS 用 `.icns`、Linux 用 `.png`，PyInstaller 这两个平台都支持
但需要不同的脚本。当前不做，因为项目主线是 Windows + 服务器 CLI。
