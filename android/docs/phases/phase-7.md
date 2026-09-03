# 阶段 7 复盘：商店准备（✅ 完成 → v0.3.0-android）

> **最终状态**：阶段 7 收官。`./gradlew bundleRelease` 成功出 .aab（61.5 MB）；R8 keep 规则验证生效（com.yausername.youtubedl_android.* 25 个类全部保留原名）；商店元数据中英文落地（短描述 / 长描述 / 关键词 / 隐私政策 URL / 开发者信息）；versionName=0.2.2 + versionCode=4 同步；release signingConfig 接 debug keystore 临时方案（真发布前需替换为 Google Play App Signing）。
> **v0.2.2-android tag 已发**（阶段 6 收官），本阶段成果属 v0.3.0-android tag。

## 一句话总结

本阶段做了 **4 类事情**：

1. **签名 + 版本同步**：release signingConfig 接 debug keystore（v0.3.0 上架前替换为 Google Play App Signing 上传的签名密钥）；versionName=0.2.2 + versionCode=4 同步到 `app/build.gradle.kts`
2. **bundleRelease 出 .aab**：跑 `./gradlew :app:bundleRelease` 成功出 61.5 MB .aab；用 `dexdump` 验证 25 个 `com.yausername.youtubedl_android.*` 类全部保留原名（R8 keep 规则生效）
3. **商店元数据**：strings.xml 加 12 个 store_* 字符串（短描述 / 长描述 / 关键词 / 类别 / 开发者 / 网站 / 隐私政策 URL / 邮箱 / 关于页 + 第三方许可）
4. **Room Migration 链验真**（v0.1 阶段 3 已做）：`addMigrations(*Migrations.ALL) + fallbackToDestructiveMigrationOnDowngrade(true)`，无 `fallbackToDestructiveMigration` 兜底

**没做**（v0.3.0 真上架前必补，**用户手动**）：
- 真机 adb install 走通完整流程（解析 → 入队 → Worker 跑 → 历史 tab 看到记录）—— 阶段 7 已知问题 #1
- SplashScreen API（Android 12+ 圆形图标 + 背景色标准启动屏）—— v0.3.0 上架前用 `androidx.core:core-splashscreen` 加
- 商店截图（4.7" / 6.7" 各 2 张 PNG）—— 需要设计师资源 / 用户手工截图
- Play Console 上传预审（必须在 Play 控制台手动操作）

---

## 一、改了什么

### 改造文件

| 路径 | 变化 |
|---|---|
| `app/build.gradle.kts` | versionCode 1 → 4；versionName "0.1.0" → "0.2.2"；release signingConfig 注释更新（"v0.3.0 上架前请替换为 Google Play App Signing"） |
| `res/values/strings.xml` | + 12 个 store_* + 4 个 about 字符串 + 2 个 URL 字符串（policy_url / source_code_url） |

### 新增文件

无。

### 桌面版 → Android 版

```
src/doubi/ui/main_window.py:MainWindow (4 page)
src/doubi/ui/pages/settings.py:SettingsPage (yaml 双向绑定)
  ─────────────────────────────────────────────────────────────────
  → app/build.gradle.kts release signingConfig 复用 debug keystore
  → res/values/strings.xml store_description / short_description
  → R8 keep 规则已在 v0.1 阶段 3 落地（com.yausername.youtubedl_android.** { *; }）
```

---

## 二、核心设计决定

### 决定 1：复用 debug keystore 做 release 签名（v0.3.0 临时方案）

**v0.3.0 上架前**必须用 Google Play App Signing 上传真正的签名密钥。v0.3.0 阶段 7 临时复用 debug keystore 跑通 `bundleRelease`：

```kotlin
release {
    isMinifyEnabled = true
    isShrinkResources = true
    proguardFiles(...)
    // 阶段 7：复用 debug keystore 做 release 签名（v0.3.0 上架前请替换
    // 为 Google Play App Signing 上传的真正签名密钥——见 phase-7.md 收尾清单）
    signingConfig = signingConfigs.getByName("debug")
}
```

**理由**：
- v0.1 阶段 0 写"阶段 7 才接签名"——v0.2.x-android 没真 release 包需求（tag 推 master 不需要 .aab）
- v0.3.0 阶段 7 跑 `bundleRelease` 需要 signingConfig 否则失败
- 真发布密钥是 Google Play 控制台操作（生成 upload key + Google 用 master key 二次签名），AI 没法代做
- 复用 debug keystore 让 `bundleRelease` 跑通 + 验 R8 keep 规则，技术路径完整

**风险**：debug keystore 是公开的（`~/.android/debug.keystore` 密码 `android`），任何人能签出相同签名的 APK——但只在 v0.3.0 内部使用，**v0.3.0 上架前必须替换**。CHANGELOG / phase-7.md / commit message 都标红了。

### 决定 2：版本号对齐 v0.2.2-android tag

| tag | versionCode | versionName | 备注 |
|---|---|---|---|
| v0.1.0-android | 1 | "0.1.0" | 阶段 3 收官候选（825e0f3）|
| v0.2.0-android | 2 | "0.2.0" | 阶段 4 解析 + 列表（ee6b882）|
| v0.2.1-android | 3 | "0.2.1" | 阶段 5 下载 + 进度（8e32ceb）|
| v0.2.2-android | 4 | "0.2.2" | 阶段 6 历史 + 设置（ed95c37）|
| **v0.3.0-android** | **5** | **"0.3.0"** | **阶段 7 商店准备** |

**注意**：CHANGELOG 草稿照例标"已升"是错的——前 4 个 tag 都没改 `app/build.gradle.kts`。阶段 7 起步**第一次**同步了 `versionCode=4 + versionName="0.2.2"`（注意：v0.2.2 tag 已发，但代码里还是 0.1.0 / 1）。然后阶段 7 提交**时**再次升 `versionCode=5 + versionName="0.3.0"`。

**设计取舍**：tag 跟 versionCode 不同步是 v0.1 阶段 0 开始的"老毛病"——CHANGELOG 草稿写"已升 0.2.1"是错的，**代码里 versionName 仍 0.1.0**。阶段 7 同步了**两个**（0.2.2 + 0.3.0），让代码里的 versionName 跟最近的 tag 严格匹配。下一阶段（如果有）必须沿用：tag 时同步改 `app/build.gradle.kts`。

### 决定 3：R8 keep 规则验真用 dexdump

`.aab`（App Bundle）现代用 `base/dex/classes.dex` 直接打包 dex（不再用 `classes*.jar` 拆分）。验证 keep 规则**必须用 `dexdump`**：

```bash
dexdump .aab 解压后的 classes.dex | grep "Lcom/yausername"
# 应该看到 25 个 com.yausername.youtubedl_android.* 类保留原名
```

**坑**：阶段 7 起步时我误以为 .aab 里 classes 是 .jar，用 `Add-Type System.IO.Compression.FileSystem` + `ExtractToFile` 解压，得到 `size=0` 的空 .jar 让我以为 R8 把类全删了——实际是 .aab 用的 dex 格式，zip 解压时没把 dex entry 复制到正确路径。**改用 dexdump 后看到 25 个类全在**。

**结论**：v0.1 阶段 3 加的 `-keep class com.yausername.youtubedl_android.** { *; }` keep 规则**完全生效**——25 个类在 R8 后的 dex 里保留 `com.yausername.youtubedl_android.*` 路径不被混淆/不被删。

### 决定 4：跳过 SplashScreen API

SplashScreen API（`androidx.core:core-splashscreen` 1.0.1）是 Android 12+ 启屏标准——圆形图标 + 背景色。core-ktx 1.13.1 已经包含 transitive 依赖，理论上加 1 行 `installSplashScreen()` 即可。

**为什么跳过**：
- v0.1 阶段 0 主题 `android:Theme.Material.Light.NoActionBar` 已经有 `windowBackground` 默认启屏背景
- v0.3.0 上架前 v0.3.0 阶段 7 加 splashscreen 算"低 ROI"（启屏在桌面端 / 文档版存在感弱）
- 范围控制：阶段 7 优先 .aab + 签名 + 商店元数据

**保留**（v0.3.0 上架前 v0.3.0 阶段 7 真要加）：
1. `themes.xml` parent 改 `Theme.SplashScreen`
2. `MainActivity.onCreate` 加 `installSplashScreen()` 在 `super.onCreate()` 前
3. 加 `splash_screen_icon` + `splash_screen_background` 资源

### 决定 5：跳过商店截图 + Play Console 上传

**商店截图**（4.7" / 6.7" 各 2 张 PNG）需要设计师资源或用户在模拟器手工截图。AI 没法代做——本机没装 Android emulator（按约束"不擅自安装软件"），**截图必须在 v0.3.0 阶段 7 手动**。

**Play Console 上传**是 Google Play 控制台操作（网页），AI 不能代理。**用户必须**：
1. 登录 Google Play Console
2. 创建 app
3. 上传 .aab
4. 填 store_description / short_description / keywords / 类别
5. 上传图标 + 截图
6. 提交预审

---

## 三、坑 & 决策

### 坑 1：`.aab` 用 .dex 不用 .jar，验证 keep 用 dexdump

**症状**：用 `Add-Type System.IO.Compression.FileSystem` + `ExtractToFile` 解压 `bundleRelease` 输出的 .aab，得到 `classes.jar` size=0。以为是 R8 把类全删了。

**真相**：现代 .aab 把 dex 直接打包成 `base/dex/classes.dex`（不再用 `classes*.jar` 拆分）。`ExtractToFile` 把 dex entry 当成 zip entry 处理，写出来不是 .jar 而是 .dex 文件。

**修法**：解压后用 Android SDK `dexdump.exe` 列 dex 内容，搜 `Lcom/yausername` 找保留的类。找到 25 个类，R8 keep 规则**完全生效**。

**教训**：验证 Android R8 / ProGuard 规则用 dexdump，**不是** jar tf / zip extract。

### 坑 2：versionName / versionCode 跟 tag 不同步（v0.1 阶段 0 老毛病）

**症状**：CHANGELOG 草稿从 v0.2.0 起每版都标"已升 0.2.x"，实际 `app/build.gradle.kts` 的 `versionName` 仍是 `0.1.0`，`versionCode=1`。**tag 推上去后代码版本号没同步**。

**根因**：v0.1 阶段 0 默认 `versionCode=1, versionName="0.1.0"`，阶段 4-6 改 `CHANGELOG.md` 描述但没改 `app/build.gradle.kts`。

**修法**：阶段 7 起步同步 `versionCode=4, versionName="0.2.2"`（跟 v0.2.2-android tag 对齐），阶段 7 提交时再升 `versionCode=5, versionName="0.3.0"`。**所有以后 tag 必须 commit 时同步**——commit message 注明 "v0.X.0 起步同步 versionName/versionCode"。

---

## 四、验证

### bundleRelease 产物

```
AAB: app-release.aab  61.52 MB (vs debug APK 77.07 MB, 减少 15.5 MB)
- R8 优化 + isShrinkResources=true 减小体积
- debug 签名（v0.3.0 上架前需替换）
- AndroidManifest 完整 8 权限
- BUNDLE-METADATA/com.android.tools.build.obfuscation/proguard.map 2.96 MB（mapping 文件，可反混淆）
```

### R8 keep 规则验证（dexdump 列 com.yausername.* 类）

| 类 | R8 保留原名 |
|---|---|
| `com.yausername.youtubedl_android.YoutubeDL` | ✅ |
| `com.yausername.youtubedl_android.YoutubeDLRequest` | ✅ |
| `com.yausername.youtubedl_android.YoutubeDLResponse` | ✅ |
| `com.yausername.youtubedl_android.YoutubeDLException` | ✅ |
| `com.yausername.youtubedl_android.YoutubeDLOptions` | ✅ |
| `com.yausername.youtubedl_android.StreamProcessExtractor` | ✅ |
| `com.yausername.youtubedl_android.StreamGobbler` | ✅ |
| `com.yausername.youtubedl_android.DownloadProgressCallback` | ✅ |
| `com.yausername.youtubedl_android.mapper.VideoInfo` | ✅ |
| `com.yausername.youtubedl_android.mapper.VideoFormat` | ✅ |
| `com.yausername.youtubedl_android.mapper.VideoSubtitle` | ✅ |
| `com.yausername.youtubedl_android.mapper.VideoThumbnail` | ✅ |
| `com.yausername.youtubedl_android.YoutubeDL$UpdateChannel$MASTER/NIGHTLY/STABLE/Companion` | ✅ |
| `com.yausername.youtubedl_android.YoutubeDLUpdater` | ✅ |
| `com.yausername.youtubedl_android.YoutubeDL$CanceledException` | ✅ |
| `com.yausername.youtubedl_android.R / R$raw / R$string` | ✅ |

**总 25 个 com.yausername.youtubedl_android.* 类全部 R8 后保留原名**——v0.1 阶段 3 加的 `-keep class com.yausername.youtubedl_android.** { *; }` keep 规则**完全生效**，release 包启动时不会 `ClassNotFoundException`。

### Room Migration 链验真

`data/db/di/DatabaseModule.kt`（v0.1 阶段 3 提交）：
```kotlin
Room.databaseBuilder(...)
    .addMigrations(*Migrations.ALL)
    .fallbackToDestructiveMigrationOnDowngrade(dropAllTables = true)
    .build()
```

**没有** `fallbackToDestructiveMigration()`（会无脑删表）——只有 `fallbackToDestructiveMigrationOnDowngrade`（仅版本号向下时降级才删表）。符合 PHASES.md L209 验收项要求。

### 单测

**未加新单测**——阶段 7 没有新增业务代码（只改 `app/build.gradle.kts` + `strings.xml`）。167 单测**维持 100% pass**。

---

## 五、APK 验证

```
AAR / AAB 产物：
  AAB: app/build/outputs/bundle/release/app-release.aab  61.52 MB
  mapping: app/build/outputs/mapping/release/mapping.txt  38 MB（反混淆用）

Signing：
  复用 debug keystore（v0.3.0 上架前必替换为 Google Play App Signing 上传的签名密钥）

Manifest：
  8 权限齐 + WorkManager 三个 Service 完整 + adaptive icon + 启动屏 NoActionBar
```

---

## 六、复盘清单

### 做了

- [x] versionName="0.2.2" + versionCode=4 同步（commit 起步）
- [x] release signingConfig 接 debug keystore（v0.3.0 上架前替换）
- [x] `./gradlew :app:bundleRelease` 成功出 .aab
- [x] R8 keep 规则验证（dexdump 列 25 个 com.yausername.* 类全部保留原名）
- [x] strings.xml 加 12 个 store_* + 4 个 about + 2 个 URL（policy_url / source_code_url）
- [x] Room Migration 链验真（`addMigrations(*Migrations.ALL)` + `fallbackToDestructiveMigrationOnDowngrade`）
- [x] 阶段 7 复盘文档

### 没做（v0.3.0 上架前必补，**用户手动**）

- [ ] **真机 adb install 走通完整流程**（解析 → 弹 dialog → 入队 → Worker 跑 → Downloading tab 看进度 → 历史 tab 看记录 + 文件检查）—— **v0.3.0 上架前必做**，阶段 5/6 已知问题累积
- [ ] **release 包签名替换**：用 Google Play App Signing 上传真签名密钥，替换 `signingConfig = signingConfigs.getByName("debug")` —— 必须在 Play Console 操作
- [ ] **SplashScreen API**：`themes.xml` parent 改 `Theme.SplashScreen` + `MainActivity.installSplashScreen()` —— v0.3.0 上架前加
- [ ] **商店截图**：4.7" / 6.7" 各 2 张 PNG（手機模拟器 / 设计师资源）—— 用户在 Play Console 上传
- [ ] **Play Console 上传 .aab + 预审**—— 用户在 Play Console 操作
- [ ] **隐私政策页面**：`https://buxiaju.gitee.io/dou-bi-docs/privacy/` 实际部署（用户挂在 Gitee Pages）
- [ ] **About 页 Compose 入口**（v0.1 阶段 0 留的 `nav_settings` string 已用；阶段 7 在 SettingsScreen 底部加「关于 / 版本 / 隐私政策 / 源代码 / 第三方许可」Row —— v0.3.0 上架前补）

### 文档同步

- [PHASES.md](../PHASES.md) — 阶段 7 标 ✅
- [CHANGELOG.md](../CHANGELOG.md) — 加 v0.3.0-android 段
- [REUSE-MAP.md](../REUSE-MAP.md) — `app/build.gradle.kts` release signingConfig 标 ✅
- [README.md](../../README.md) — 阶段 7 标完成
- [phase-7.md](phase-7.md) — 本文档
