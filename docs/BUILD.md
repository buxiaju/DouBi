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
    "--collect-all", "qframelesswindow",          # 第三方 Qt 库的隐藏资源
    "--collect-all", "qfluentwidgets",
    "--paths", str(ROOT / "src"),
    "--collect-submodules", "doubi",              # 把整个 doubi 包都收进来
    str(launcher),                                # ★ 关键：自动生成的启动壳，见下文
]
```

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
└── doubi-gui.exe                      # 234,943,742 bytes (235 MB)
```

体积说明：
- Python 3.13 runtime 约 25 MB
- PySide6 约 100 MB（包含 Qt 6 全部模块）
- qfluentwidgets + qframelesswindow 约 20 MB
- 其它依赖（yt-dlp / playwright / httpx / aiohttp / ...）约 70 MB
- 业务代码 < 5 MB

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

产物：`dist/DouBi-Setup-<version>.exe`（当前 0.1.0 约 **213 MB**）。

链路是 `build_installer.py` → `build_exe.py --onedir` → `makensis`：

```
pyproject.toml:version
    ↓ 正则读出来，作为唯一版本真源
scripts/build_exe.py --onedir  →  dist/doubi-gui/（14.7 MB exe + _internal/ 3308 文件，787 MB）
    ↓ /DSRC_DIR=<绝对路径>
tools/nsis/nsis-3.11/makensis.exe  installer/doubi.nsi
    ↓ LZMA solid 压缩，825 MB → 213 MB（27.0%），单线程约 10 分钟
dist/DouBi-Setup-0.1.0.exe
```

**版本号只有一个源**。`build_installer.py` 从 `pyproject.toml` 读出
version，用 `/DPRODUCT_VERSION=` 注进 NSIS，绝不在 `.nsi` 里手抄——
手抄必然漂移。界面上显示的版本号在
`src/doubi/ui/resources/__init__.py:APP_VERSION`，改版本时两处要一起动。

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

单位是 KB。实测写入 806347，对应 787 MB，与安装目录实际占用一致。

### 6.4 静默验证配方

手工点安装向导没法反复跑，用静默模式装到隔离目录：

```powershell
# 装（/D= 必须是最后一个参数，且不能加引号）
.\dist\DouBi-Setup-0.1.0.exe /S /D=$env:LOCALAPPDATA\DouBi_VerifyTest

# 查注册表
Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DouBi"

# 卸（故意让程序开着，以此检验 EnsureAppClosed）
& "$env:LOCALAPPDATA\DouBi_VerifyTest\uninstall.exe" /S
```

实测结论：安装/卸载均退出码 0；`_internal/` 3308 个文件一个不少；
卸载后安装目录、两个 HKCU 键、开始菜单、桌面快捷方式全部清空，
残留进程 0 个，而 `~/.doubi` 完好保留。

### 6.5 编译像卡住了？先确认再等

LZMA solid 压缩 825 MB 是单线程的，中途**几分钟没有任何输出**是正常的。
别急着 Ctrl-C，先看它是真在干活还是真死了：

```powershell
Get-Process makensis | Select-Object CPU, WorkingSet   # CPU 时间应持续增长
Get-ChildItem "$env:TEMP\ns*.tmp"                      # 暂存 datablock 会涨到 ~800 MB
```

CPU 在涨、临时文件在涨，就是在压缩。

## 7. 验证清单

发版前手动检查（不在单元测试里）：

- [ ] `dist/doubi-gui.exe` 文件存在且大小 ~235 MB
- [ ] 双击启动 → 闪屏 → 主窗口出现
- [ ] **任务栏左下角应用图标是豆比**（不是 Python 双蛇）
- [ ] 标题栏左上是豆比（28px，与 M5+ 期望一致）
- [ ] 切换主题 → 标题栏图标换色
- [ ] 打开「关于」对话框 → 标题栏 + 任务栏分组图标都是豆比
- [ ] 打开「扫码登录」对话框 → 标题栏 + 任务栏分组图标都是豆比
- [ ] 关闭窗口 → 进程正常退出，无残留
- [ ] 在资源管理器中右键 .exe → 「属性」看到「豆比」图标
- [ ] 标题栏版本号与 `pyproject.toml` 一致（曾出现过 UI 显示 0.6.0 而
      安装包写 0.1.0 的不一致）

安装包额外检查：

- [ ] `dist/DouBi-Setup-<version>.exe` 存在，约 213 MB
- [ ] 安装过程无 UAC 弹窗（当前用户安装）
- [ ] 安装界面中文无乱码
- [ ] 控制面板「应用和功能」里能看到「豆比下载 <version>」，大小正确
- [ ] 开始菜单 + 桌面快捷方式可用
- [ ] 程序开着时卸载 → 提示并自动结束进程，卸载成功
- [ ] 卸载后目录 / 注册表 / 快捷方式零残留，`~/.doubi` 仍在

## 8. CI / 自动发布

CI 已就位——见 `.github/workflows/build.yml`（`build-installer`）。
工作流在 `windows-latest` runner 上跑，分两段：

**测试段**——`pip install .` + `pytest --maxfail=5`，`QT_QPA_PLATFORM=offscreen`
让无头环境也能跑 GUI 类测试（PySide6 缺失时自动 skip）。超 5 个失败
直接终止，避免花 25 分钟跑完一整轮注定红的测试。

**打包段**——`python scripts/build_installer.py`，链路就是 §6.1 的
`build_installer.py → build_exe.py --onedir → makensis`，与本地完全一致。
产物定位用 `Get-ChildItem` 而不是硬编码文件名（版本号单一真源在
`pyproject.toml`，workflow 里不抄版本号）。

**SHA256**——`Get-FileHash -Algorithm SHA256` 生成
`DouBi-Setup-<version>.exe.sha256`，与安装包一起作为 artifact 上传
（保留 90 天）。下载者用 `certutil -hashfile ... SHA256` 或
`Get-FileHash` 自行核验。

**触发**：

| 触发方式 | 行为 |
| --- | --- |
| 推送 `v*` 形式的 tag（如 `v0.1.0`） | 测试 + 打包 + 上传 artifact + **创建 GitHub Release**（draft，发版动作由人触发） |
| `workflow_dispatch` 手动 dispatch | 测试 + 打包 + 上传 artifact，**不**创建 release——用来验证「现在的 main 分支能不能成功打包」 |

**Release notes**用 `generate_release_notes: true`，让 GitHub 根据
commit 历史自动生成；仓库里有手写的 `docs/CHANGELOG.md`，PR description
也够用，不再硬编码进 workflow。

**为什么不换 linux runner**：NSIS 用 `tools/nsis/makensis.exe`（Windows
二进制），PySide6 wheel 也是 Windows 风格。换 runner 会让打包工具链
不通用，触发非 Windows 特有的 flakiness，得不偿失。

**dev / nightly 渠道**（`--onedir` 裸目录打 zip）尚未接入 workflow——
本地可手动 `python scripts/build_exe.py --onedir` 跑一份，跳过 10 分钟
的 LZMA 压缩。

## 9. 跨平台

当前 `scripts/build_exe.py` 是 Windows only：
- `sep = ";"`（Windows `--add-data` 分隔符）
- `.ico` 是 Windows 专属

macOS 用 `.icns`、Linux 用 `.png`，PyInstaller 这两个平台都支持
但需要不同的脚本。当前不做，因为项目主线是 Windows + 服务器 CLI。
