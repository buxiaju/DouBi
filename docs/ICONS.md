# 豆比图标管线

> 配套代码：`src/doubi/ui/resources/`（`__init__.py` / `icon.svg` / `icon_template.svg` / `icon.png` / `icon.ico`）
> 配套脚本：`scripts/build_icons.py`（生成 PNG）/ `scripts/build_ico.py`（生成 .ico）/ `scripts/build_exe.py`（打包 .exe）

## 1. 为什么是 SVG 而不是 PNG

一开始项目用的是 PNG——单文件、QIcon 一装就完事。但很快撞到三个硬限制：

| 限制 | 后果 |
| --- | --- |
| Windows 任务栏要求 **多档位**（16/32/48/64/128/256），每档矢量比位图锐利 | 一张 1024px PNG 缩到 16px 锯齿明显 |
| 主题切换要换色 | 位图无法运行时换色，要么手画 7 张，要么改回矢量 |
| 豆比紫（品牌主题）配色从图标反推 | 设计稿本身就是矢量，强行转位图会丢锐度 |

于是有了现在的设计：**矢量 SVG 模板 + 主题换色 + 缓存多档位 QPixmap**。

## 2. 三个文件，三种用途

### 2.1 `icon.svg` —— 设计源稿（不参与运行时）

用户提供 1124×1124 的设计稿，包含：

- `<filter>`：投影 + 内高光
- `<clipPath>`：腮红椭圆裁剪
- `<linearGradient>`：底板渐变
- 呆毛、闭眼、腮红、嘴、舌头等吉祥物元素

**为什么不直接渲染**：Qt 只实现 SVG Tiny 1.2，原始设计稿的 `feColorMatrix`
投影层被误画成「实心黑圆角矩形」在最上层。实测用 `QSvgRenderer` 渲染原始
SVG 时，**29% 像素变成纯黑**，整张图标糊成一块黑方块（见 `test_render_icon_pixmap_size_and_no_black_block`
的「>5% 阈值」设置来源）。

设计源稿保留为视觉参考 / 重设计参考，**不进入运行时**。

### 2.2 `icon_template.svg` —— 渲染模板（QtSvg 安全子集）

把设计稿重写为 QtSvg 能正确渲染的版本，**去 filter / 去 clipPath**：
- `<filter>` → 由 rim-light 描边近似
- `<clipPath>` 删掉（裁剪框完全包住两个腮红椭圆，本来就是 no-op）
- viewBox 收紧到 `50 30 1024 1024`——让圆角方块**出血铺满**画布
  （源稿四周 4.5% 是死边——图标在标题栏 / 任务栏里看着偏小就是这段
  留白吃掉的）

7 个品牌色 hex 既是模板里的字面量，**也是换色锚点**：

```xml
<linearGradient id="bg">
  <stop offset="0" stop-color="#FF8C42"/>   <!-- bg_from -->
  <stop offset="1" stop-color="#FF5E7C"/>   <!-- bg_to -->
</linearGradient>
<rect fill="url(#bg)" .../>                <!-- 底板 -->
<path fill="#E8552A" .../>                 <!-- tuft 呆毛 -->
<ellipse fill="#FFE4D1" .../>              <!-- face 脸 -->
<circle fill="#2A2A2A" .../>               <!-- ink 眼/嘴 -->
<ellipse fill="#FF9AA2" .../>              <!-- blush 腮红 -->
<ellipse fill="#FF6B6B" .../>              <!-- tongue 舌头 -->
```

**`BRAND_PALETTE` 必须与这些字面量逐字一致**（含大小写）——`icon_svg(accent)`
做单次正则替换，锚点错一个就漏色。`test_icon_template_exists_and_holds_all_anchors`
守这条。

### 2.3 `icon.png` —— 1024px 兜底位图

`scripts/build_icons.py` 从模板 SVG 渲染 1024×1024 输出。运行时只在 QtSvg
不可用（如极老的 PySide6 发行版）时走这条。检测到 QtSvg 失败自动退化，调用方
什么都不用改。

### 2.4 `icon.ico` —— Windows 多档位图标

`scripts/build_ico.py` 生成 6 档（16/32/48/64/128/256）的 PNG 合集，
按 ICONDIR / ICONDIRENTRY 格式封装。`scripts/build_exe.py` 用 PyInstaller
打包时通过 `--icon` 参数嵌入 .exe 资源段——这是 **Windows 任务栏读取
「应用分组图标」的唯一渠道**。`QApplication.setWindowIcon` 改不了任务栏。

> **为什么不依赖 PIL**：`Pillow 12.3.0 + Python 3.13 + Windows` 触发
> `STATUS_STACK_BUFFER_OVERRUN`（0xC0000409）。`build_ico.py` 用
> Qt + 手写 ICONDIR 绕开，最稳。

## 3. 资源模块 API（`ui/resources/__init__.py`）

```python
from doubi.ui.resources import (
    APP_NAME, APP_DISPLAY_NAME, APP_VERSION, APP_COPYRIGHT,
    BRAND_PALETTE,                          # 7 色 → 语义名
    icon_path, icon_source_path, icon_template_path,
    icon_palette, icon_svg,                 # 换色
    render_icon_pixmap, load_app_icon, load_splash_pixmap,
    clear_icon_cache,
)
```

### 3.1 `icon_palette(accent=None)` —— 配色推导

按主色推导整套图标配色：

| 元素 | 推导公式 | 含义 |
| --- | --- | --- |
| `bg_from` / `bg_to` | 主色色相 ±20°，亮度 0.63/0.68，饱和度 `0.42 + 0.55 * s` | 同色系斜向双色调 |
| `tuft` | 主色色相 -15°，亮度 0.52，饱和度 `0.35 + 0.40 * s` | 比底板更沉 |
| `face` | 主色色相 -6°，亮度 0.90，饱和度 `0.55 + 0.45 * s` | 主色极浅版（冷色主题下变薄荷） |
| `ink` / `blush` / `tongue` | 恒定 | **角色辨识度核心**——不随主题变色 |

**饱和度公式的由来**：`0.42 + 0.55 * s` 把莫兰迪这类低饱和主色（`s ≈ 0.18`）
压到 0.52 底板饱和度，避免刺眼；亮色主色（`s ≈ 0.9`）给到 0.92 也不会过于
浓艳。数值反推自品牌原图（豆比紫用品牌色 #f59e6a → s ≈ 0.87，底板 0.90 正好）。

**`accent=None` / 不可解析 / 脏色值** → **退化到 `BRAND_PALETTE`**，绝不抛异常。
这保证一个坏配置不会让 GUI 起不来。

**豆比紫的特殊性**：`doubi` 主题本身从图标反推，再用主色二次推导只会偏离
原图。`_active_accent()` 检测到 `current_theme().name == "doubi"` 时返回
`None`，让图标走品牌原色。**这是产品决定，不是技术 bug**。

### 3.2 `icon_svg(accent=None)` —— 换色

**一次正则替换**完成所有换色：

```python
_HEX_TO_KEY = {v: k for k, v in BRAND_PALETTE.items()}
_BRAND_RE = re.compile(
    "|".join(re.escape(h) for h in sorted(BRAND_PALETTE.values(), key=len, reverse=True))
)

def icon_svg(accent=None):
    tpl = _template_text()
    if tpl is None:
        return None
    palette = icon_palette(accent)
    return _BRAND_RE.sub(lambda m: palette[_HEX_TO_KEY[m.group(0)]], tpl)
```

**为什么不逐色 `str.replace`**：那样在「A 替换成 B，B 又被下一轮替换」时会
产生二次命中，产出错色（典型场景：`#FF8C42` 替换成新色 X，但 X 又恰好是
`BRAND_PALETTE` 里的另一个锚点，第二次替换会把它换掉）。正则一次性扫描
`|` 把所有锚点合并成一个大模式，避免这个问题。

**为什么按长度倒序匹配 hex**：当前 7 个品牌色互不为前缀（`#FF8C42` /
`#FF5E7C` / ...），所以这步不严格需要。但保留这个防御性写法——如果
将来加 `#FFF` 这种短前缀，长度倒序保证它不会优先匹配 `#FFF...` 的长
前缀锚点。

### 3.3 `render_icon_pixmap(size, accent=None, *, themed=True)` —— 渲染

```python
def render_icon_pixmap(size=256, accent=None, *, themed=True):
    if size <= 0:
        return None
    key = (size, _resolve_accent(accent, themed))
    cached = _pixmap_cache.get(key)
    if cached is not None:
        return cached
    pix = _render_svg(size, key[1]) or _render_png(size)
    if pix is not None:
        _pixmap_cache[key] = pix
    return pix
```

- `themed=True` 时 `_active_accent()` 自动从 `current_theme()` 取主色
- `themed=False` 固定品牌原色
- `size <= 0` → 返回 `None`（不抛——上层用 `if pix is None` 防御比 try/except
  干净）
- 按 `(size, accent)` 缓存到 `_pixmap_cache`，同一主题切来切去不会重复渲染
- `_render_svg` 失败时降级到 `_render_png`（用 `icon.png` 兜底）

### 3.4 `load_app_icon(size=None, ...)` —— 多档位 QIcon

```python
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

def load_app_icon(size=None, accent=None, *, themed=True):
    if size is not None:
        pix = render_icon_pixmap(size, accent, themed=False)
        if pix is None:
            return None
        icon = QIcon()
        icon.addPixmap(pix)
        return icon if not icon.isNull() else None

    # size=None：填全部档位
    icon = QIcon()
    added = False
    for s in ICON_SIZES:
        pix = render_icon_pixmap(s, resolved, themed=False)
        if pix is not None:
            icon.addPixmap(pix)
            added = True
    if not added:
        return None
    _icon_cache[resolved] = icon
    return icon
```

- `size=None` → 装填全部 10 档——Qt 在标题栏（16）、任务栏（32）、Alt+Tab（48）、
  资源管理器（16/32/48/64）、系统设置（128/256）各挑最合适的一档，**避免
  系统强制缩放产生锯齿与白边**
- `size=N` → 只装一档（用于对话框 / 闪屏）
- 按 `accent` 缓存到 `_icon_cache`——切主题会换 key，缓存自动失效
- `_resolve_accent` 决定 `accent` / `themed` 参数的优先级

### 3.5 `load_splash_pixmap(w, h, ...)` —— 闪屏

```python
def load_splash_pixmap(width=256, height=256, accent=None, *, themed=True):
    side = min(int(width), int(height))
    if side <= 0:
        return None
    return render_icon_pixmap(side, accent, themed=themed)
```

`min(w, h)` 边长的矢量渲染——比「渲染大图再缩放」少一次重采样，锐度更好。
`side <= 0` 返回 `None`（不抛）。

### 3.6 缓存失效

- **同进程内切主题**：`subscribe_theme(_refresh_app_icon)` 重新生成
  `accent` → 缓存 key 改变 → 自动失效。
- **测试 / 热替换**：`clear_icon_cache()` 一次性清空。
- **`_template_cache`**：模板文件内容只读，启动后**几乎不变**，
  `icon_template_path` 的修改需要重启应用。

## 4. 主窗口图标全链路

```
用户切主题
    ↓
set_theme(新主题名)
    ├── 1. setTheme(DARK/LIGHT)
    ├── 2. setThemeColor(accent)
    ├── 3-6. ... 主题生效（见 ARCHITECTURE §8）
    └── 7. _notify()
            ↓
         订阅者回调执行
            ↓
         MainWindow._refresh_app_icon()
            ↓
         load_app_icon()  ← 用当前主题主色
            ↓
         QIcon 含 8 档矢量渲染的图标
            ↓
         self.setWindowIcon(icon)  +  QApplication.setWindowIcon(icon)
            ↓
         windowIconChanged 信号
            ↓
         qfluentwidgets.FluentTitleBar.setIcon(icon)
            ↓
         iconLabel.setPixmap(QIcon(icon).pixmap(18, 18))   ← 被我们替换成 28px
```

### 4.1 标题栏图标放大（`main_window._enlarge_titlebar_icon`）

qfluentwidgets `FluentTitleBar.setIcon` 把 pixmap 尺寸**写死 18px**——48px
高的标题栏里 18px 图标明显偏小。修法：

```python
TITLEBAR_ICON_SIZE = 28

def _enlarge_titlebar_icon(self, size=TITLEBAR_ICON_SIZE):
    title_bar = getattr(self, "titleBar", None)
    label = getattr(title_bar, "iconLabel", None)
    if title_bar is None or label is None:
        return
    label.setFixedSize(size, size)

    def set_icon(icon, _label=label, _size=size):
        _label.setPixmap(QIcon(icon).pixmap(_size, _size))

    # 关键：必须断开旧 setIcon
    try:
        self.windowIconChanged.disconnect(title_bar.setIcon)
    except (TypeError, RuntimeError):
        pass
    title_bar.setIcon = set_icon
    self.windowIconChanged.connect(set_icon)
    set_icon(self.windowIcon())
```

**为什么必须断开旧信号**：qfluentwidgets 在 `FluentTitleBar.__init__` 里
`self.window().windowIconChanged.connect(self.setIcon)`。如果只改
`iconLabel` 尺寸没换槽函数，下一次 `setWindowIcon` 触发信号，旧
`setIcon` 会把 `iconLabel.pixmap` 打回 18px。`_enlarge_titlebar_icon`
一定要在 `disconnect → connect` 这一对操作之间完成，顺序反了会
丢信号。

**为什么用闭包而不是方法**：`title_bar.setIcon` 是 qfluentwidgets 的实例
方法，覆写成 `set_icon` 后保留方法签名 `(icon)`，与 `windowIconChanged`
信号 `SIGNAL(object)` 兼容。`QIcon(icon).pixmap(...)` 这一步会判断
参数类型（QIcon / QPixmap / str），三层都正确。

**为什么 `try/except` 包 disconnect**：qfluentwidgets 在某些版本里会把
`self.setIcon` 重新定义在子类中，**已绑定的连接用 `disconnect` 找不到**。
异常吞掉——「断不掉」只是回到原状态，不会更糟；下面立即 `title_bar.setIcon = set_icon`
覆写它，效果一样。

### 4.2 关于 / 登录对话框补 setWindowIcon

```python
class BilibiliQRDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("B 站扫码登录")
        icon = load_app_icon()
        if icon is not None and not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(500, 600)
        ...
```

之前 dialog 没设 `windowIcon`，Windows 任务栏 / Alt+Tab 会回退到
**python.exe 的双蛇 logo**（用户报的「Python 终端图标」就是这个）。
修法是 `self.setWindowIcon(load_app_icon())` + 工厂函数顶部
`from ..resources import load_app_icon`。

防御性写法：`if icon is not None and not icon.isNull()`——`load_app_icon`
在 QtSvg 不可用时返回 None，dialog 仍然能跑（Windows 用 python.exe 双蛇兜底）。

## 5. 模板回归守卫

Qt 只实现 SVG Tiny 1.2，**任何**新贡献的 SVG 都可能踩 filter 坑。守卫测试：

### 5.1 `test_icon_template_has_no_unsupported_svg_features`

```python
def test_icon_template_has_no_unsupported_svg_features():
    import re
    text = icon_template_path().read_text(encoding="utf-8")
    # 头部注释里会解释为什么去掉这些特性，检查前先剥掉注释只看真实标记
    markup = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    for token in ("<filter", "<clipPath", "filter=", "clip-path=", "<fe"):
        assert token not in markup, f"模板含 QtSvg 不支持的 {token}"
```

**注意剥注释**：模板头部的注释会解释「为什么去掉 filter」，不剥的话注释里
的「`<filter>`」字面量会触发假阳性。`re.DOTALL` 让 `.` 匹配换行，处理
多行注释。

### 5.2 `test_render_icon_pixmap_size_and_no_black_block`

```python
def test_render_icon_pixmap_size_and_no_black_block(qapp):
    pix = render_icon_pixmap(128, themed=False)
    img = pix.toImage()
    black = 0
    for y in range(0, 128, 2):
        for x in range(0, 128, 2):
            c = img.pixelColor(x, y)
            if c.alpha() == 255 and c.red() < 8 and c.green() < 8 and c.blue() < 8:
                black += 1
    total = (128 // 2) ** 2
    assert black / total < 0.05, f"纯黑占比 {black / total:.1%}，filter 又被渲染了"
```

`feColorMatrix` bug 的症状就是 29% 像素变纯黑。**5% 阈值**远低于此，足够
抓回归；同时**远高于正常图标的黑像素占比**（闭眼 + 嘴 + 阴影），不会
假阳性。

### 5.3 `test_icon_template_exists_and_holds_all_anchors`

```python
def test_icon_template_exists_and_holds_all_anchors():
    p = icon_template_path()
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    for key, value in BRAND_PALETTE.items():
        assert value in text, f"模板缺少 {key} 锚点 {value}"
```

`BRAND_PALETTE` 与模板字面量必须逐字一致。漏一个 → `icon_svg(accent)`
替换会漏色（视觉：图标底板少换了一档），而且**没有运行时校验**（SVG 渲染
不会报错，只是颜色对不上）。**这是该测试最重要的防线**。

## 6. 7 套主题预览图

`scripts/build_icons.py --preview` 额外导出 `screenshots/icon_themes.png`，
把 7 套主题的图标拼成一行 160px 一格，让肉眼快速核对换色结果。

```bash
python scripts/build_icons.py --preview
# ✓ src/doubi/ui/resources/icon.png  1024×1024
# ✓ screenshots/icon_themes.png  2360×160
```

预览图不进运行时，只是开发期间的肉眼核对工具。

## 7. 踩过的坑

### 7.1 `QPixmap.save(QBuffer, "PNG")` 在 offscreen 平台崩溃

```
STATUS_STACK_BUFFER_OVERRUN (0xC0000409)
```

PySide6 6.x 在 `QT_QPA_PLATFORM=offscreen` 下，**`QPixmap.save(QBuffer, "PNG")`**
会触发原生级崩溃。`QImage.save(QBuffer, "PNG")` 没事。这条经验写进了
`build_ico.py` 的注释，提醒后来人不要为了「少一次 QPixmap.fromImage 转换」
而踩坑。

### 7.2 `asyncio.run` 在 Qt 主线程炸

```python
def _kick_status_refresh():
    try:
        asyncio.ensure_future(self._refresh_account_status_async())
    except RuntimeError:
        try:
            asyncio.run(self._refresh_account_status_async())
        except Exception:
            pass
```

Qt 主线程已经在跑 QApplication event loop，**`asyncio.run` 在已有 running
event loop 的线程里调用会抛 `RuntimeError`**。这里 `except Exception: pass`
虽然吞掉了，**coroutine 也没被消费**——这就是「账号状态永远停在未登录」
的根因。修法是**改用 Qt 自带的事件循环集成**（qasync），不要在 Qt 主线程
启动新 asyncio loop。

### 7.3 不要在 `__init__` 里改 `qfluentwidgets.setIcon`

```python
# 错误：qfluentwidgets 在 setIcon 里用 pixmap(18, 18)
title_bar.setIcon = my_set_icon  # 实例属性覆盖
```

**这是「实例属性覆盖 vs 方法绑定」的微妙问题**。`self.window().windowIconChanged.connect(self.setIcon)`
里 `self.setIcon` 是属性查找，所以**实例属性覆写**会立即生效。但 PySide6
的 signal/slot 内部**可能缓存方法引用**——遇到时仍要 `disconnect + reconnect`
才能稳。**别只覆写方法**。

## 8. 配套脚本一览

| 脚本 | 用途 | 调用 |
| --- | --- | --- |
| `scripts/build_icons.py` | 从模板 SVG 生成 1024px PNG + 7 主题预览图 | `python scripts/build_icons.py [--preview]` |
| `scripts/build_ico.py` | 从模板 SVG 生成多档位 .ico | `python scripts/build_ico.py` |
| `scripts/build_exe.py` | PyInstaller 打包（默认 onefile） | `python scripts/build_exe.py [--onedir] [--console]` |
| `scripts/build_installer.py` | 出 onedir 产物并用内置 NSIS 打成安装包 | `python scripts/build_installer.py [--skip-build]` |

打包脚本的细节、踩坑与产物说明见 [docs/BUILD.md](./BUILD.md)。
