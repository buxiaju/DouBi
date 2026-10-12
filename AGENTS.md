# AGENTS.md

> 协作给本仓的 AI agent / 协作者的工程约束。**这是本项目的真源**——
> 任何与下文冲突的对话/记忆/工具建议以此文件为准。`docs/DEVELOPMENT.md`
> 是更详细的设计与流程文档，本文是它的「快查表」。

## 项目速览

- **DouBi（豆比）**：桌面端多平台视频下载助手（Electron-free，纯 Python + Qt6）
- **作者**：buxiaju 个人维护，Windows 10/11 x64 单平台
- **版本真源**：`src/doubi/__init__.py:__version__`（`pyproject.toml` 用
  `dynamic = ["version"]` 读取）
- **当前版本**：见 `__version__` 字段；CHANGELOG 速查表同步更新

## 关键路径

| 用途 | 路径 |
| --- | --- |
| 入口（CLI） | `src/doubi/cli/main.py` |
| 入口（GUI） | `src/doubi/ui/main_window.py` |
| 服务端 | `src/doubi/server/app.py` |
| 平台适配器 | `src/doubi/platforms/{douyin,bilibili}/` |
| 抖音签名 | `src/doubi/platforms/douyin/sign/{abogus,xbogus}.py`（外部移植：JohnserfSeed/f2 + Evil0ctal） |
| 文档 | `docs/{QUICKSTART,ARCHITECTURE,BUILD,DEVELOPMENT,CHANGELOG,ICONS,UI_DESIGN,ROADMAP}.md` |
| 全量测试 | `scripts/run_full_tests.py`（`--mode local/ci/gui-slow`） |
| 构建产物 | `scripts/build_installer.py` + `installer/doubi.nsi`（PyInstaller + NSIS） |
| 临时探针 | `.scratch/`（gitignore，不入版本） |

## 工具链

- **Python ≥ 3.10**（pyproject requires-python）
- **测试**：pytest + PySide6 offscreen（用 `QT_QPA_PLATFORM=offscreen`）
- **GUI**：PySide6 + qfluentwidgets（可选依赖，CI 不装）
- **打包**：PyInstaller onedir + NSIS 3.x
- **lint**：ruff（`pyproject.toml` 配置；`--fix` 优先 + `--unsafe-fixes` 谨慎）

## 测试基线

**发版前必跑两个口径**（基线数字进 CHANGELOG / Release 正文）：

```powershell
# local：装齐 extras，排除会挂的 test_theme_apply_gui.py
python scripts/run_full_tests.py --mode local

# ci：sys.meta_path 屏蔽 9 个可选依赖，复刻 CI 的 `pip install .` 环境
python scripts/run_full_tests.py --mode ci
```

**已知全量跑会挂的边界**：

- `tests/test_theme_apply_gui.py`（28 例，`gui` + `slow`）→ local 模式默认排除
- 6 个 PySide6 offscreen 跨文件 UI 测试（`test_ui_{feedback,shortcuts,loading_and_empty,shortcuts_and_loading_e2e,shell_regression_037,shell_regression_039}.py`）合集跑会在 87%-88% 位置挂起，单跑都过。发版前先 `git stash` 跑一遍，或用 `pytest --ignore` 跑非 UI shell 文件，UI shell 单独跑。

**断网口径探针**（防「测试静默真联网」）：`.scratch/nonet_hits.log`，
判据是 `^HIT` 行数（不是总行数——nonet.py v3 写 4 行/命中，v6 写 1 行/命中）。

## 发版固定动作

按顺序，不跳步：

1. **基线**：local + ci 两口径测试，记录 passed/skipped 数字
2. **CHANGELOG 补段落**：用「症状 / 根因 / 修法 / 判据」四段式写；速查表加行；删速查表里的「暂未收录」提示
3. **打 tag**：`annotated`，单行 `X.Y.Z — <卖点>`，**不要**长 commit message 格式
4. **推远端**：`git push origin vX.Y.Z`（Gitee）+ `git push Github vX.Y.Z`（GitHub），两个都要显式推
5. **打包**：`python scripts/build_installer.py`（7-8 分钟）
6. **SHA256 侧签** + **隔离静默验收**（NSIS /S，0.3.5 起不再卡在确认框，但仍要验）
7. **手工建 Release**：Gitee + GitHub 两个平台都要建

**`origin` = Gitee（主仓，含历史附件）**，`Github` = GitHub（镜像 + Release 分发）。

## Commit 格式

```
<类型>(<范围>): <主题> — <卖点/根因>

* 改动 1
* 改动 2
* 测试 N 例通过

<文件 / 数字 / 链接>
```

- **类型**：`feat` / `fix` / `chore` / `docs` / `perf` / `refactor` / `test`
- **范围**：项目内的子模块名（`ui` / `core` / `server` / `cli` / `platforms` / `installer` / `tests` / `docs` / `changelog` / `release`）
- **不要栈式推送**：单版本走完整流程，不要发版中分批 commit + 中间 push
- **commit message 文件**：用 `.scratch/msg_*.txt` + `git commit -F`（PowerShell 5.1 对长 message 的 `→` 转义不稳）

## PowerShell 严格（必读）

**环境**：Windows 10/11 + PowerShell 5.1，`&&` / `||` 不可用，UTF-8 默认会带 BOM。

| 禁用 | 替代 |
| --- | --- |
| `&&` / `||` | `;` + `$LASTEXITCODE` 检查 |
| `tail` / `head` / `grep` / `wc` | `Select-Object -First/-Last` / `Select-String` / `Measure-Object` |
| `ls -la` | `Get-ChildItem \| Format-Table` |
| `python` 裸 | OK（PATH 里就是 python.exe），但 `npm` 用 `npm.cmd`，`npx` 用 `npx.cmd` |
| `python -m pip` 短选项 | 用长选项：`--find-links` 不写成 `-f` |
| `Remove-Item` 删除文件 | **硬拦截**——临时文件进工作树，`.gitignore` 排除，不删 |
| `mavis-trash` | 不可用（launcher 不可访问）——同上，进 `.scratch/` |
| `sed -i` | 用 Edit 工具（`edit`） |
| 写 UTF-8 文件 | `Set-Content -Encoding UTF8` 会写 BOM，改用 Write 工具 |
| bash 反斜杠转义 | 用 `$env:VAR='val'` + 单引号 |

**调试命令统一前缀**：`$env:PYTHONUNBUFFERED="1"; python -u ...` 避免管道缓冲假象。

## 编码与中文输出

- **日志乱码**：PowerShell 5.1 cp936 默认 + GBK 管道重编码
  → `PYTHONIOENCODING=utf-8` 或 `chcp 65001`
  → 关键脚本（`run_full_tests.py`）提示语已用英文
- **文件编码**：源码、文档统一 UTF-8 无 BOM（用 Write/Edit 工具，不走 PowerShell `Set-Content`）

## 一致性约定

- **bullet**：统一 `-`，不用 `*` / `+` / `1.`
- **每文件 1 个 H1**；H2/H3 不跳级
- **代码块加语言标签**（` ```python ` 而非 ` ``` `）
- **`from __future__ import annotations`**：annotation 永不求值，类型注解可以是字符串
- **typing.Dict/List/Tuple**：本仓 ≥ 3.10，**用内建** `dict` / `list` / `tuple`
- **`Optional[X]` / `Union[X, Y]`**：仍用 typing 导入（PEP 604 `X | None` 迁移待 P2 评估）

## 已知「静默失败」陷阱

工程实战中多次栽过的坑——给协作者提个醒：

- **qfluentwidgets `SegmentedWidget.currentItem()`** 返回 `SegmentedItem` 对象，**不是** routeKey 字符串
  → 取路由用 `currentRouteKey()`
- **qfluentwidgets `InfoBar.*(message=...)`** 第 2 个参数叫 `content`，无 `message`
  → 用 `title=` + `content=`
- **AST 守护测试** `tests/test_ui_qfluent_api_guards.py`：禁止 `currentItem()`、禁止 `InfoBar.* message=`、禁止未知 InfoBar 方法名
- **PySide6 offscreen 跨文件状态累积**：6 个 UI shell 测试合集跑会挂，单跑过
  → 发版前拆批跑
- **断网探针** `.scratch/nonetSS.py` v6：每次命中写 1 行（v3 写 4 行/host=2 host）
  → 判据是 `^HIT` 行数，**不是文件总行数**
- **NSIS /S 静默安装**：0.3.5 起 `EnsureAppClosed` 在 `MessageBox` 之前 `IfSilent doubi_kill`，不必先 `Stop-Process doubi-gui`

## 跨项目偏好（user-level，非本项目独有）

- 质量优先于速度（每版本 typecheck 0 error + 全量测试全绿才发版）
- 真实使用驱动（上线后实测反馈 + 截图 = 下一版优先级）
- 决断力强（复杂方案不反复拉锯）
- 不喜欢栈式推送（commit + push 单版本走完）

---

*本文件随项目一起维护；改动后请同步 PR 描述。*
