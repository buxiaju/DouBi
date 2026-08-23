# GUI 主题系统设计（命名主题包 + 持久化）

- 日期：2026-08-22
- 状态：已确认，待实现
- 影响面：`core/config.py`、`ui/`（新增 `theme.py`，改 5 个文件）、`tests/`

---

## 1. 背景与问题

用户诉求是「优化界面 UI，提供多种主题设置」。调研 `src/doubi/ui/`（13 文件约 4112 行）后发现，
在加任何主题功能之前，有两个已实证的地基缺陷会让「持久化」根本无法生效。

### 缺陷 1 — 设置页存不下去，且会毁掉用户配置

`ui/pages/settings.py::_on_save` 使用 `asdict(self._cfg)` 而非 dataclass 上已存在的
`to_dict()`。`asdict()` 保留 `Path` 对象，`yaml.safe_dump` 无法表示：

```
database_path type -> WindowsPath
safe_dump FAILED: RepresenterError
('cannot represent an object', WindowsPath('doubi.db'))
```

`output_root` 侥幸未触发，因为它随后被输入框字符串覆盖；`database_path` / `manifest_path`
未被覆盖，直接抛异常。

执行顺序放大了危害：`open(..., "w")` 先把文件**截断为空**，之后 `safe_dump` 才抛异常，
而 `try` 块只包了 `import yaml`，`safe_dump` 在保护范围之外。净效果是——
点保存 → 旧配置被清空 → 异常未捕获 → 无任何失败提示。

当前 `_on_save` 零测试覆盖（`tests/test_ui_workers.py:81-86` 只断言无 PySide6 时抛异常）。

### 缺陷 2 — GUI 从不读回自己写的文件

`core/config.py::load_config` 第 106 行是 `if path is not None:`，只有显式传路径才读 YAML。
而所有 GUI 页面都传 `None`：

| 调用点 | 传入 |
| --- | --- |
| `ui/pages/settings.py:89`、`parse.py:52`、`history.py:32`、`download.py:819` | `None` |
| `server/app.py:95`、`mcp/server.py:118` | `None` |
| `cli/main.py:190` | `args.config`（默认亦为 `None`） |

即 `settings.py` 写入 `~/.doubi/config.yml`，但没有任何调用点会读它——包括 CLI，
除非用户手动 `-c` 指定。settings.py 文件头注释「the same file the CLI reads」不成立。

### 结论

主题持久化链路是「选主题 → 写 YAML → 重启读回 → 应用」。缺陷 1 断在「写」，
缺陷 2 断在「读回」。两头都断时主题功能无论怎么实现都不可能跨重启生效——这解释了
为什么现有 `_apply_theme` 只做运行时切换。**故地基修复是本设计的前置条件，不可拆分推迟。**

---

## 2. 方案选型

呈现过三个方向，用户选定 **B**：

| 方案 | 内容 | 结论 |
| --- | --- | --- |
| A | 亮/暗/自动 + 强调色选择器 | 未选。仅换主色，无法解决硬编码语义色问题 |
| **B** | **命名主题包**：每个主题是一张完整 token 表，用户选主题而非拼装参数 | **选定** |
| C | B + 用户自定义/导出主题 | 未选。可作为后续增量 |

### 已确认的两个决策

1. **CLI 优先**：`--theme` 默认值从 `"auto"` 改为 `None`，仅显式传入时才覆盖配置文件，
   与项目既有「env > file > defaults」约定一致。
2. **主题包自带明度**：选「深海」即固定为暗色，独立的「亮/暗/自动」选择器取消。

### 取舍：取消「自动」意味着丢失跟随系统明暗

这是决策 2 的直接后果。判断是值得：换来「选了什么就是什么」的确定性，且
`SystemThemeListener` 与固定主题包在语义上冲突。若后续需要，正确做法是新增独立布尔项
`follow_system_theme`，在两个「默认」包之间切换，而**不是**把「自动」塞回主题列表。

---

## 3. 地基修复设计

### 3.1 `_on_save`（三处改动）

1. `asdict(self._cfg)` → `self._cfg.to_dict()`，复用既有 Path→str 转换
2. 先 `yaml.safe_dump(data)` 到内存字符串，成功后再 `write_text`，杜绝「截断后失败」
3. 整段包 `try/except`，失败弹 `InfoBar.error`

### 3.2 `load_config` 默认路径回退

`core/config.py` 新增模块级常量：

```python
DEFAULT_CONFIG_PATH = Path.home() / ".doubi" / "config.yml"
```

`load_config(None)` 回退到该路径（存在则读）。收益：

- 6 个传 `None` 的调用点**一行不改**，自动获得读取能力
- CLI `-c` 显式路径仍然优先
- 优先级链变为 **env > 显式路径 > 默认路径 > DEFAULTS**

顺带把 settings.py 中 3 处硬编码的 `Path.home() / ".doubi" / "config.yml"` 收敛到该常量。

**行为变更已确认接受**：此改动同时影响 REST 与 MCP（它们也传 `None`）。
配置文件本应对所有入口一致生效，现状的「永不读配置」是缺陷而非特性。

---

## 4. 主题包数据结构

新增 `src/doubi/ui/theme.py`：

```python
@dataclass(frozen=True)
class ThemePack:
    name: str            # 持久化用的稳定 key，如 "deep_sea"
    label: str           # 界面显示名，如 "深海"
    dark: bool           # 自带明度，决定 setTheme(Theme.DARK/LIGHT)
    accent: str          # 主色，喂给 setThemeColor()
    tokens: dict[str, str]
```

`name` 与 `label` 分离是刻意的：写进 YAML 的是 `deep_sea` 而非「深海」，
否则改文案或做 i18n 会让所有人配置失效——这正是现有 `_apply_theme(text)`
拿中文字符串做判断的隐患。

### token 键位（覆盖已盘点的全部硬编码色）

| 分类 | 键 | 替换现状 |
| --- | --- | --- |
| 背景层 | `bg_base` `bg_layer` `bg_hover` | `setCustomBackgroundColor("#e6e6e6", "#3a3a3a")` |
| 表格行 | `row_odd` `row_even` | `_row_colors()` 的 4 个 rgba |
| 文字层 | `text_primary` `text_muted` | `_muted_color()` + 7 处字面量 `"gray"` |
| 语义色 | `status_{running,paused,completed,failed,cancelled}` 各带 `_fg` `_bg` | `TaskRow.STATUS_STYLE` |
| 进度条 | `progress_{normal,success,error,paused}` | `#2ea121` `#e64545` `#999` `#e0a030` |
| 形状 | `radius` `row_height` | `ROW_HEIGHT = 44` |

### 6 套内置主题

| key | label | 明度 | 主色 | 定位 |
| --- | --- | --- | --- | --- |
| `default_light` | 默认亮 | 亮 | `#0078d4` | 现状基线，零感知升级 |
| `default_dark` | 默认暗 | 暗 | `#4cc2ff` | 现状暗色基线 |
| `deep_sea` | 深海 | 暗 | `#2dd4bf` | 蓝绿冷调，长时间下载场景 |
| `morandi` | 莫兰迪 | 亮 | `#8c7b6b` | 低饱和暖灰 |
| `eye_care` | 护眼 | 亮 | `#3f7d58` | 米黄底 `#f5f1e8`，降蓝光 |
| `high_contrast` | 高对比 | 暗 | `#ffd60a` | 纯黑底 + 高亮字，无障碍 |

**语义色随明度调整而非直接复用**：`status_failed` 亮色下为 `#c02b2b`，暗色下必须提亮至
`#ff6b6b`，否则深背景上的暗红几乎不可读。这是现有 `_apply_status_color()` 的实际缺陷
——它用固定值，且 `_on_theme_changed` 完全不刷新它。

---

## 5. 接线设计

### 5.1 唯一入口

```python
def set_theme(name: str) -> None      # 切换 + 广播
def current_theme() -> ThemePack      # 任何位置取当前 token
def subscribe_theme(widget, callback) # 统一订阅，随 widget 销毁自动解绑
```

`set_theme` 内部三步：`setTheme(Theme.DARK if pack.dark else Theme.LIGHT)`
→ `setThemeColor(pack.accent)` → 发信号。

现状仅 `download.py` 订阅了 `qconfig.themeChanged`，其余 3 个带色文件切主题后残留旧色；
统一 helper 后 4 个文件行为一致。

### 5.2 启动优先级（决策 1）

```
CLI --theme（显式给出） > DOUBI_THEME 环境变量 > ~/.doubi/config.yml > default_light
```

`app.py` 的 `--theme` 改为 `default=None`，`choices` 从 `light/dark/auto`
改为 6 个主题 key。

### 5.3 `main_window._cycle_theme` 解耦

现状伸手进 `self.settings_interface.theme` 下拉框、并调用私有方法
`settings_interface._apply_theme(next_text)`。改为遍历主题包列表调用 `set_theme()`，
设置页下拉框反向监听主题信号同步显示。

### 5.4 解耦纪律

`theme.py` 放在 `ui/` 而**非** `core/`。`core/` 必须保持无 Qt 依赖（架构三条解耦轴之一），
主题是纯呈现层概念。`core/config.py` 只存一个字符串 `theme`，不认识 token 表——
「配置只经 `DownloadOptions` 流动」的原则同样适用：core 不该知道颜色。

### 5.5 触及面（DEVELOPMENT.md §17「加配置项要动 5 处」）

`DEFAULTS` → `AppConfig` 字段 → `load_config` env 映射 → GUI 设置页 → 各 surface。

主题项特殊：CLI / REST / MCP 无界面，**不需要**接入它们的 `_build_options()`，
仅 GUI 消费。

---

## 6. 测试

新增测试均不依赖 Qt，可在无 PySide6 环境运行：

| 测试 | 锁定的缺陷 |
| --- | --- |
| `yaml.safe_dump(cfg.to_dict())` 不抛异常 | 缺陷 1 |
| 写临时 `config.yml`，monkeypatch `DEFAULT_CONFIG_PATH`，`load_config(None)` 读到其中值 | 缺陷 2 |
| `theme` 字段经 YAML 往返后保持不变 | 持久化链路 |
| 未知主题 key 回退到 `default_light` 而不崩溃 | 容错 |

---

## 7. 实现顺序

1. 修 `_on_save`（含测试）
2. 加 `DEFAULT_CONFIG_PATH` 回退（含测试）
3. 新建 `ui/theme.py`：`ThemePack` + 6 套 token 表 + 三个入口
4. 配置接入：`DEFAULTS` / `AppConfig` / `load_config` env 映射加 `theme`
5. `app.py` 启动读取 + CLI 优先
6. `settings.py` 下拉改主题包并持久化 `name`
7. 硬编码色换 token（`download.py` / `parse.py` / `login_dialog.py` / `settings.py`）
8. `main_window` 主题循环解耦
9. 跑全量测试（基线 335：331 通过 / 4 跳过）

前 6 步交付「主题可选可持久化」，第 7-8 步交付「主题真正改变观感」。
