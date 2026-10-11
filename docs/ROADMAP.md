# DouBi 路线图（待完善功能清单）

> 基准：**0.3.9（2026-10-05）**。本文件只记**真实且尚未解决**的事，已完成项不入表（去 [CHANGELOG.md](CHANGELOG.md)）。每条都标了**根因 / 验收标准 / 依赖关系**，方便直接当任务描述用。

## 优先级定义

**P0**：真实用户可见的正确性 / 数据安全问题，不修会出事
**P1**：功能缺口或体验明显不足，下一个版本应收口
**P2**：增强型，做了更好不做也能跑
**P3**：议题 / 观察项，等信号而不是等排期

---

## P0 — 正确性与安全

### P0-2 uifid 是 UUID4 占位

- **现状**：`webapi.py` 的 `self._uifid = uuid.uuid4().hex[:16]`。
- **风险**：平台目前未校验，一旦开始校验 uifid 来源会直接 403。
- **状态（2026-10-04 复核）**：**原假设被实测证伪**。

  0.3.6 排查「抖音搜索返回 0 行」时，最自然的猜想就是「换成 cookie 里的真实 uifid 即可过风控门」。用五个来源实测（`verify_check` 芯片判据）：

  | uifid 来源 | 结果 |
  | --- | --- |
  | UUID4 占位（现状） | `rows=0 verify_check` |
  | cookie `UIFID`（320 字符） | `rows=0 verify_check` |
  | cookie `UIFID_TEMP` | `rows=0 verify_check` |
  | cookie `x-web-secsdk-uid` | `rows=0 verify_check` |
  | cookie `odin_tt` | `rows=0 verify_check` |

  同一次会话里 `/aweme/v1/web/hot/search/list/` 与 `/aweme/v1/web/aweme/detail/` 都正常返回，`user/profile/self` 返回真实昵称——**所以不是「uifid 被校验了」，而是搜索端点这一类特有的风控**（`search_nil_type=verify_check`，需设备 / 短信验证）。

  **结论**：uifid 占位目前**仍然不是**短板，保持现状（原「一旦校验就 403」的担忧没有出现；实际出现的是另一条路径的拦截）。

- **新验收标准**：若哪天非搜索端点也开始拒不认这个 uifid，再回来处理；在此之前不动，避免提前逆向。

- **关联**：0.3.6 已让搜索被拦时在 `error_sink` 里带出 `verify_check` 证据（见 [CHANGELOG.md](CHANGELOG.md) 0.3.6 第三节），所以这个门下次复发时能立刻认出来，不会再走一遍「是不是 uifid」的排查。

---

## P1 — 下一个版本应收口

> 0.3.3 已把原有的 P1-1 / P1-3 / P1-4 三条全部收口（见 [CHANGELOG.md](CHANGELOG.md) 0.3.3）；P1-2 降级为手动实测项后已移出 ROADMAP；**0.3.7 加了两条 UX P1**（见下），下一轮 P1 候选应优先从 P2 里挑，或等新信号进来。

### P1-3 设置页「即时生效」体验（0.3.7 加）

- **现状**：设置页有「保存」按钮，用户改完一项要点保存才生效。改完立即看到效果（「主题 A」）要重启或者手动切一下触发 —— 实际上中间过程断了，用户以为「改了没生效」。
- **根因**：`_on_save` 是个一次性 save 入口，UI 控件只是把 `self._cfg` 改了一下，从来没写回 `~/.doubi/config.yml`。保存按下时一次写完。
- **修法**：debounce 500ms 自动写回 config.yml（参考 settings 的 `promptBeforeDownloadChanged` 信号——0.3.7 解析页已经实时接收了，但设置页自己不写）。主题切换已经在 `set_theme(theme_name)` 后实时刷新，但写盘要等一下。
- **验收**：改任意非破坏性项（主题 / 语言 / 并发数 / 默认画质），500ms 内写盘成功，「保存」按钮可隐藏或改为「立即保存」。
- **依赖**：无外部依赖；要复用 `DEFAULT_CONFIG_PATH` / `_to_dict()` / `_load_from_cfg()` 已有函数。

### P1-4 下载页进度信息加密（0.3.7 加）

- **现状**：下载页进度条只显示百分比 + 状态胶囊。用户看不到「当前下载速度」「还剩多久」「这一段多少 MB」。批量下 10 个文件时，整队进度没汇总。
- **根因**：`TaskRow` 只画了 `progress_percent`（百分比），没有速度 / ETA / 当前片段大小。下行整队 card 是 `DownloadPage` 上的统计条 + 状态胶囊，没整合到 TaskRow。
- **修法**：`TaskRow` 加 `speed_label`（MB/s）和 `eta_label`（剩余时间），从 `info.fraction` 增量推算（`d_bytes / d_time`）。`DownloadPage` 顶上加一条「N 个下载中，总速度 X MB/s」统计。
- **验收**：下载 100MB+ 文件时能看到「5.2 MB/s / 剩 19 秒」；批量 5 个文件时能看到「5.2 MB/s · 共 10 GB 已下」。
- **依赖**：需要 task_manager 在 progress signal 里带 speed/bps 字段（`TaskInfo` 加 optional `bytes_per_sec` / `eta_seconds`）。

---

## P2 — 增强

### P2-1 抖音其他容器类型

类似合集（M6.45 / M6.56）与话题（M6.57）的模式，可继续扩：音乐原声、合拍、同城、关注流。**前提是得先确认 yt-dlp 拿不到**（否则属于重造轮子）。

### P2-2 其他平台

- **小红书 / 微博 / 快手**：[docs/ARCHITECTURE.md](ARCHITECTURE.md) 的分层已预留位置，按 `PlatformAdapter` 实现。
- 每个平台都要能回答「下载走谁、采集走谁」两个问题，否则会重演 yt-dlp 静默降级到 generic 的坑（见 [docs/DEVELOPMENT.md](DEVELOPMENT.md) §14.6.7）。

### P2-3 新平台归类器的统一约束

当前 8 个采集容器各自写了一遍分页调用。下一步可考虑把 `_cursor_paginate` / `_search_paginate` 合并为一个可拓展的分页器接口。**不要为了抽象而抽象**——得先有第三个异常分页形态出现。

---

## P3 — 观察项（等信号，不等排期）

1. **`_MSSDK_STRDATA` blob 会过期**——随官方 `runtime_bundler_*.js` 升级而失效。典型症状：mssdk 200 但 Set-Cookie 缺 msToken → fallback 伪 token → 403 回升。**等到真的出现再处理**，提前重逆向没意义。
2. **`ruff` 历史遗留 139 处**——不阻断开发，但新代码必须保持 0 新增。若某天决定清账，建议单独一个 commit，不要混进功能提交。**2026-10-02 复核**：其中 F401 / F811 / F841 / F821 共 62 处已确认零真实缺陷（F821 的 3 处运行时缺陷已在 0.3.2 修掉，`login_dialog.py` 剩 1 处为设计使然），其余是 UP035 / UP037 / I001 风格项。清账时优先看 F401，它们只是噪音。
3. **注解可求值性**（2026-10-02 新增观察项）——`from __future__ import annotations` 让注解惰性化，但**任何显式求值**（`typing.get_type_hints()`，进而 FastAPI / Pydantic / 内省驱动框架）都会去模块 `__globals__` 里找名字，找不到就 `NameError`。项目已踩过两次（`server/deps.py` 的 `Request`、0.3.2 的 `PlatformAdapter` / `Any` / `PIL`）。**新增公共 API 时**：若注解里的名字不能在模块顶层 import（循环依赖 / 可选依赖 / 刻意延迟导入），就必须显式处理，别指望 `__getattr__`——它不参与 globals 查找。守卫见 `tests/test_registry_annotations.py`。

---

## 已评估：不做（含理由）

| 项 | 结论 | 理由 |
|---|---|---|
| **TikTok 下载 / 采集** | 不做 | 需 `curl_cffi` TLS 指纹伪装 + 签名与 UA 强耦合 + 海外出口硬门槛（上游硬编码 `127.0.0.1:10808`），移植量约 740 行；2026-10-03 用户拍板 |
| **xGnarly 签名器** | 不移植 | 上游即为**死代码**（仅类定义 + `__main__` 演示，不在 `encrypt/__init__.py` 导出名单），抖音侧无触发点（M6.59） |
| **`device_id` 生成器** | 不移植 | 上游 `get_device_id()` **无任何调用者**；DouBi 侧 `device_id` 是用户手填可选配置，缺失仅降级空串（M6.59） |
| **Slides / 图集新接口** | 不实装 | 上游 `slides.py` 是空壳；DouBi **已有两条图集路径**，再引入移动端老接口（第二套域名 + 版本号 + 响应结构）是负收益（M6.58） |

---

## 维护规则

1. **本文件只收「真实且未解决」**。修完一条，从这里**删除**，改写进 [CHANGELOG.md](CHANGELOG.md)。
2. **不要把探索期的猜想写进来**——`P3` 只放已有具体信号的观察项。
3. **每条 P0 / P1 必须能回答「怎么验收」**；答不出来的说明还没想清楚，不要列。