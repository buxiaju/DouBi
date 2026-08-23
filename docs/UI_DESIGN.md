# 豆比 UI 设计语言

> 配套代码：`src/doubi/ui/theme.py`（主题 / token / 排版 / 间距 / 圆角常量 / 辅助 QSS）
> `src/doubi/ui/widgets.py`（共享组件）
> 主题生效链路见 [docs/ARCHITECTURE.md §8](./ARCHITECTURE.md#8-主题的全局生效链路)
> 图标配色见 [docs/ICONS.md](./ICONS.md)

## 1. 原则

> 「用户看不到的设计原则，用户一定能感受到的设计缺陷。」

5 条决定所有视觉决策：

1. **语义色必须随明度重算，不能跨明度复用**——`#c02b2b` 在深色底上
   几乎不可读，所以暗色骨架统一提亮到 `#ff6b6b`。
2. **每处颜色都要跟着主题变**——五层失效点（见 [DEVELOPMENT §13.4.2](./DEVELOPMENT.md#1342-五层失效点每处颜色都要跟着变的真正难点)）
   缺一就发白。
3. **不取代 qfluentwidgets**——`PushButton` / `LineEdit` / `ComboBox` 等
   仍在直接用，共享组件是「需要统一表达力」时用。
4. **不依赖 PySide6 也能 import**——共享组件的 class 体在工厂函数内部，
   模块顶层只暴露 `build_*` 函数，CI 无头环境跑测试不卡 PySide6 安装。
5. **辅助 QSS 替代字面量**——`setStyleSheet("color: gray;")` 一律
   改 `muted_qss()`，让次级说明跟着主题走。

## 2. 主题包（`ThemePack`）

7 套主题，**主题名是稳定的 key**（写进 YAML），**界面显示名是 label**
（给用户看）。`THEMES` 的 key 顺序就是 GUI 下拉框 / 导航栏循环 / 启动
`--theme choices` 的顺序。

| key | label | 明度 | 底色 | 主色 |
| --- | --- | --- | --- | --- |
| `default_light` | 默认亮 | 亮 | `#f3f3f3` | `#0078d4` |
| `default_dark` | 默认暗 | 暗 | `#202020` | `#4cc2ff` |
| `doubi` | 豆比紫 | 暗 | `#1a1230` | `#f59e6a` |
| `deep_sea` | 深海 | 暗 | `#0f1c24` | `#2dd4bf` |
| `morandi` | 莫兰迪 | 亮 | `#eceae5` | `#8c7b6b` |
| `eye_care` | 护眼 | 亮 | `#f5f1e8` | `#3f7d58` |
| `high_contrast` | 高对比 | 暗 | `#000000` | `#ffd60a` |

**`doubi` 是品牌默认主题**——配色从应用图标反推，深紫底 + 琥珀橙主色
与图标本身是同一色系。**它不是通过 `accent` 二次推导回来的**——
`icon_palette("doubi")` 直接返回 `BRAND_PALETTE`，否则用主色 `#f59e6a`
反推会让图标偏色、丢原图味道。详见 [ICONS.md §3.1](./ICONS.md#31-icon_paletteaccentnone--配色推导)。

## 3. Token 体系

`ThemePack.tokens` 是一个字典，覆盖所有「可能需要取色」的地方。所有
主题必须声明同一组键——`test_every_theme_has_full_token_set` 守这条。

| 组 | 键 | 用途 |
| --- | --- | --- |
| 背景 | `bg_base` | 窗口底色 |
| | `bg_layer` | 卡片 / 输入框 |
| | `bg_hover` | 悬停态 |
| | `bg_elevated` | 浮起态（弹层 / popup） |
| 文字 | `text_primary` | 正文 |
| | `text_muted` | 次级说明 |
| 强调 | `accent` | 主色 |
| | `accent_soft` | 浅底（hover/选中态） |
| | `accent_strong` | 深色（pressed） |
| 表格 | `row_odd` / `row_even` | 交替行（`rgba`） |
| 状态 | `status_{running,paused,completed,failed,cancelled}_{fg,bg}` | 任务状态徽标 |
| 进度 | `progress_{normal,success,error,paused}` | 自绘进度条 |
| 尺寸 | `radius` / `radius_card` / `radius_pill` | 圆角三档 |
| | `row_height` | 表格行高 |
| 阴影 | `shadow_sm` / `shadow_md` / `shadow_lg` | 三级阴影 QSS |
| 装饰 | `gradient_header` | `header_qss()` 用的 hero 渐变，None 时退纯色 |

**取色用 `token(key)`**——`from .theme import token, set_theme`，
`set_theme("deep_sea")` 后 `token("bg_base")` 返回 `#0f1c24`。**不要
直接 `THEMES[current].tokens["bg_base"]`**——路径更长且少一层 fallback。

## 4. 排版 / 间距 / 圆角 常量

| 常量 | 值 | 用途 |
| --- | --- | --- |
| `TYPE_H1` | 24 | 页面级 H1 标题 |
| `TYPE_H2` | 20 | H2 |
| `TYPE_H3` | 16 | H3 / 卡片标题 |
| `TYPE_BODY` | 13 | 正文（绝大多数场景） |
| `TYPE_CAPTION` | 12 | 表格内容 / 卡片副标题 |
| `TYPE_TINY` | 10 | 角标 / 极小提示 |
| `SPACE_XS` | 4 | 紧凑行内 |
| `SPACE_SM` | 8 | 元素内 padding |
| `SPACE_MD` | 12 | 卡片内容 padding |
| `SPACE_LG` | 16 | 卡片间距 / 大段 padding |
| `SPACE_XL` | 24 | 页面级水平 padding |
| `SPACE_XXL` | 32 | 页面级垂直 padding / 大段间距 |
| `RADIUS_DEFAULT` | 4 | 控件默认圆角 |
| `RADIUS_CARD` | 8 | 卡片圆角 |
| `RADIUS_PILL` | 20 | 胶囊形（按钮 / 徽标） |

**单调性是硬约束**：`TYPE_H1 > H2 > H3 > BODY > CAPTION > TINY`、
`SPACE_XS < SM < MD < LG < XL < XXL`。`test_typography_constants_are_exposed`
守这条。**不要在某个页面里把字号 / 间距覆盖成字面量**——那会让该页面
脱钩设计系统。

## 5. 辅助 QSS 函数

每个函数返回一段 QSS 字符串，调用方 `widget.setStyleSheet(...)` 一次性
应用。**全部走 token**，切主题时跟着走。

| 函数 | 用途 |
| --- | --- |
| `heading_qss(level=1..3)` | 页面级标题，level 对应 `TYPE_H1..H3` |
| `body_qss()` | 正文字号 + 字色 |
| `muted_qss()` | 次级说明（暗色骨架上重算灰度） |
| `card_qss(elevated=False)` | CardWidget 边框 + 背景 |
| `header_qss(level=1..3)` | 标题区渐变（`gradient_header` 存在时走渐变，否则退纯色） |
| `app_qss(pack=None)` | **整套**全局 QSS——`set_theme()` 内部自动调用 |

**为什么要 `muted_qss()` 而不是 `setStyleSheet("color: gray;")`**：
- 暗色骨架上 `gray` 实际是 `#a0a0a0`，对比度不足
- 字面量 `gray` 不会随主题变——切到「深海」还是亮灰，跟墨蓝底不协调
- `muted_qss()` 在每个主题下都重新计算 `text_muted` 与 `bg_base` 的
  对比度，保证 WCAG AA（4.5:1 文本对比度）

## 6. 共享组件（`ui/widgets.py`）

5 个组件，每个都是工厂函数（**不依赖 PySide6 也能 import**）。

### 6.1 `PageHeader` —— 页面级三段式

```python
from doubi.ui.widgets import build_page_header

Header = build_page_header()
header = Header(parent)
header.set_title("设置")
header.set_subtitle("账号 / 主题 / 性能 / 路径。所有改动点「保存设置」后才会写入配置文件。")
header.add_action(my_button)   # 右侧动作槽，自动 stretch
```

四个页面（解析 / 下载 / 历史 / 设置）都用它。统一视觉：标题 + 副标题
+ 右侧动作（如「保存设置」按钮）。

### 6.2 `EmptyState` —— 居中占位态

```python
Empty = build_empty_state()
e = Empty(parent)
e.set_text("等待你粘贴链接", "支持视频 / 图集 / 直播 / ...")
e.refresh_text()  # 程序更新文本后调用
```

空表格 / 空列表 / 未开始任务时用。比「裸标签 + icon」更显眼，比「一张
图 + 大字」更克制。

### 6.3 `StatChip` —— 顶部统计小方块

```python
Chip = build_stat_chip()
c = Chip(parent)
c.set_value(7)
c.set_label("运行中")
c.set_kind("running")  # "running" | "paused" | "completed" | "failed"
```

下载页顶部 4 个 stat chip（运行中 / 已暂停 / 已完成 / 失败）就是它。
`set_kind` 决定主色：running 用 accent，paused 用 `status_paused_fg`，
等等。

### 6.4 `PlatformBadge` —— 圆形彩色平台徽标

```python
Badge = build_platform_badge()
b = Badge(parent)
b.set_platform("B 站")   # "B 站" | "抖音"
```

B 站蓝、抖音红，登录对话框与设置页的「账号与登录」卡都用它。比写
「B 站」两个字加色块更醒目。

### 6.5 `SectionDivider` —— 卡片内分组

```python
Divider = build_section_divider()
d = Divider(parent, title="账号", subtitle="管理 B 站 / 抖音的登录态")
layout.addWidget(d)
```

「细横线 + 副标题」一行。设置页 5 张分组卡的标题区都是它。

## 7. 主题系统接线

| 入口 | 接线 |
| --- | --- |
| 启动参数 | `doubi-gui --theme doubi` |
| 配置文件 | `~/.doubi/config.yml` 的 `theme` 字段 |
| 环境变量 | `DOUBI_THEME=eye_care` |
| 启动优先级 | `--theme` > `DOUBI_THEME` > 配置文件 > 内置默认（豆比紫） |
| 设置页下拉 | 选中即预览，**点「保存设置」才落盘** |
| 导航栏画笔按钮 | 循环切换，**不落盘** |

详见 [QUICKSTART.md §换主题](./QUICKSTART.md#换主题) 与
[DEVELOPMENT.md §13.4.4](./DEVELOPMENT.md#1344-接线与启动优先级)。

## 8. 设计决策记录

### 8.1 为什么不取代 fluent 控件

qfluentwidgets 已经提供了 `PushButton` / `LineEdit` / `ComboBox` 等
高质量控件，再包一层会让我们：
- 失去 fluent 控件的样式跟随能力（控件自己 `setStyleSheet` 优先级
  高于全局 QSS，包一层反而卡这层）
- 维护成本高（fluent 控件 API 一变我们要跟着改 wrapper）
- 视觉一致性变差（fluent 自己的样式细节我们看不到）

共享组件是「fluent 控件不直接做的事」时用——页面级 PageHeader、
占位态、统计条、分组线。

### 8.2 为什么不用枚举而用字符串

`StatChip.set_kind("running")` 看起来应该用 `enum.Kind.RUNNING`，但
**字符串够用**：
- 4 种 kind，全部用 `if kind == "running"`，string 比较最快
- IDE 自动补全可以靠 mypy literal 类型
- 测试代码写 `set_kind("running")` 比 `set_kind(Kind.RUNNING)` 短 6 个字符
- `Kind` 枚举只在 `theme.py` 内部用——UI 层只看到字符串

### 8.3 为什么豆比紫是 `dark=True`

`#1a1230` 底色明度 ~0.1，是暗色。`ThemePack.dark=True` 让
`setTheme(Theme.DARK)` 把 qfluentwidgets 内部所有 `*Dark` 模板
（如 `qfluentwidgets.dark.QSS_PATH`）打开。如果错填 `dark=False`，
库的暗色控件会显示「白底深色文字」，与我们的深紫底不协调。

### 8.4 为什么不用 QSS 变量 (`--variable`)

Qt 的 QSS 不支持 CSS 变量，所以「一个值用在多处」只能：
- 用 Python 字符串拼接（`qfluentwidgets` 的做法）
- 用 `setProperty` + `qproperty-*`（仅对自定义 property 有效）
- 用全局 QSS 选择器匹配（覆盖性差）

我们走「Python 字符串拼接」路线——`app_qss(pack)` 把 token 表翻译成
完整的全局 QSS 字符串，`set_theme()` 时一次性应用。**复杂度集中在
一处**，不需要在每个控件上做属性匹配。

## 9. 排版示例

「设置」页面（4 张分组卡）排版逻辑：

```
┌─ PageHeader ──────────────────────────────┐
│  设置                                     │
│  账号 / 主题 / 性能 / 路径。所有改动点...    │
│  [保存设置]  ← 右上角动作                │
└─────────────────────────────────────────┘

┌─ Card (1) ────────────────────────────────┐
│  ┌─ SectionDivider ─────────────────────┐  │
│  │  账号与登录                          │  │
│  │  管理 B 站 / 抖音的登录态            │  │
│  └──────────────────────────────────────┘  │
│                                          │
│  [PlatformBadge B 站]  [扫码登录]  ...    │
└──────────────────────────────────────────┘
```

- 卡片间距：`SPACE_LG` (16px)
- 卡片内 padding：`SPACE_MD` (12px)
- 卡片标题字号：`TYPE_H3` (16px)
- 副标题字号：`TYPE_CAPTION` (12px) + `muted_qss()`
- 卡片圆角：`RADIUS_CARD` (8px)
- 卡片底色：`token("bg_layer")`
- 卡片边框：`1px solid rgba(255,255,255,0.06)`（Mica 关闭后用 token）

## 10. 风格 checklist

新加页面 / 控件前过一遍：

- [ ] 用 `token(key)` 取色，**不用字面量 hex**
- [ ] 字号从 `TYPE_*` 选，**不写 12px 14px 16px**
- [ ] 间距从 `SPACE_*` 选，**不写 8px 12px 16px**
- [ ] 圆角从 `RADIUS_*` 选，**不写 border-radius: 4px**
- [ ] 次级说明用 `muted_qss()`，**不写 `color: gray`**
- [ ] 标题用 `heading_qss()` / `header_qss()`，**不写 `font-size: 24px`**
- [ ] 卡片用 `build_page_header()`，**不写自定义 HBox + 标签**
- [ ] 空态用 `build_empty_state()`，**不写居中标签**
- [ ] 统计条用 `build_stat_chip()`，**不写 HBox + 数字 + 标签**
- [ ] 平台标识用 `build_platform_badge()`，**不写彩色文字**
- [ ] 切主题后跑一遍 UI，**所有元素跟着变**

## 11. 已知妥协

### 11.1 qfluentwidgets 的 Mica / Acrylic 效果

Mica 是 Win11 上的毛玻璃背景色，需要 `_normalBackgroundColor()` 透传——
但 `_apply_window_background()` 必须**关掉它**才能让 `bg_base` 真正生效。
**取舍**：在 Win11 上放弃 Mica 的视觉收益，换取主题色精准生效。

未来想两全：Mica 用半透明 alpha 叠加 `bg_base`，但 PySide6 6.x 还没暴露
对应的 API（需要原生调用 DwmSetWindowAttribute + 客户端区合成）。

### 11.2 high_contrast 主题在亮色面板上还是发亮

`high_contrast` 用 `#000000` 底 + `#ffd60a` 强调色，明度对比度
21:1（远超 WCAG AAA）。但系统层有些控件仍按 OS 主题画（Win10 资源管理器
+ 部分右键菜单），用户切到 high_contrast 会看到「应用内全黑 + OS
控件还是亮」。这是 OS 行为，不是我们能修的。

### 11.3 启动速度

M6.4 之后主窗口默认 1100×760，4 个页面共享 Module-scope 单例。冷启动
约 1.5 秒（其中 PySide6 import 0.8s、QApplication 构造 0.3s、
页面构造 0.4s）。闪屏在 PySide6 import 时还没创建，是 M6.4+ 的
待办：把 splash 改到 PyInstaller bootloader 那一层。
