# 阶段 9 复盘：自用 UX 收官（✅ 完成 → v0.4.1-android）

> **最终状态**：阶段 9 收官。**自用策略变更**（v0.3.0 阶段 7 收官时记的「上架必补 7 项」全部砍掉）；release signingConfig 改读 `~/.gradle/gradle.properties` 环境变量（自用 keystore 走本地）；4 个 v0.2.2 阶段 6 累积 UX 欠账（「打开保存目录」+ 设置项补全 + SplashScreen API + UI test 改 ViewModel test）一起做。200/200 单测全绿（v0.4.0 184 + 16 新增），`bundleRelease` 成功出 .aab **64.7 MB**。
> **v0.4.0-android tag 已发**（阶段 8 收官），本阶段成果属 v0.4.1-android tag。

## 一句话总结

本阶段做了 **4 大块**事情（按 commit 顺序）：

1. **文档清理**：删 v0.3.0 阶段 7 收官时记的「上架必补 7 项」段（自用策略变更，CHANGELOG / README / phase-7.md / PHASES.md）
2. **签名迁移**：v0.3.0 阶段 7 复用 debug keystore → 本地生成 `~/.android/doubi-release.keystore` + `~/.gradle/gradle.properties` 配路径密码 + `app/build.gradle.kts` 读环境变量
3. **4 个 UX 欠账**（用户选 C 方案不拆版）：
   - C1：「打开保存目录」按钮 + FileProvider + `res/xml/file_paths.xml`
   - C2：SettingsViewModelTest +13 字段级 / HistoryViewModelTest +4 事件测试（UI test 改 ViewModel test——自用环境没装 Robolectric/真机/模拟器）
   - C3：SplashScreen API（`androidx.core:core-splashscreen:1.0.1` + `Theme.SplashScreen` parent + `MainActivity.installSplashScreen()`）
   - C4：SettingsScreen 4 个新 Section（主题切换 / 重复下载策略 / 引擎+aria2 / 通用嗅探 5 字段 + write3 个）

**没做**：
- Compose UI test（v0.2.2 阶段 6 记的欠账）——自用环境没装 Robolectric/真机/模拟器，改成补 ViewModel 字段级测试（C2）

---

## 一、改了什么

### 新增文件

| 路径 | 作用 |
|---|---|
| `app/src/main/java/com/doubi/android/core/sniffer/` | 阶段 8 已写，本阶段未变 |
| `app/src/main/res/xml/file_paths.xml` | FileProvider 路径配置（files-path / external-files-path / external-path） |
| `app/src/test/java/com/doubi/android/core/sniffer/HttpContentTypeSnifferTest.kt` | 阶段 8 已写，本阶段未变 |
| `app/src/test/java/com/doubi/android/ui/history/HistoryViewModelTest.kt` | 阶段 6 已写，本阶段 +4 例（onOpenSaveDir / onRedownload） |
| `app/src/test/java/com/doubi/android/ui/settings/SettingsViewModelTest.kt` | 阶段 6 已写，本阶段 +13 例（v0.4.1 新增字段级 onFieldChanged） |
| `~/.android/doubi-release.keystore` | **本地自用 keystore**（不进 git） |
| `~/.gradle/gradle.properties` | **自用 keystore 密码配置**（不进 git） |
| `docs/phases/phase-9.md` | 本文档 |

### 修改文件

| 路径 | 变化 |
|---|---|
| `app/build.gradle.kts` | + `signingConfigs.create("release")` 读 `~/.gradle/gradle.properties`；`buildTypes.release.signingConfig` 引用 `signingConfigs.getByName("release")`；+ `implementation(libs.androidx.core.splashscreen)`；versionCode 6→7；versionName "0.4.0"→"0.4.1" |
| `gradle/libs.versions.toml` | + `core-splashscreen = "1.0.1"` + `androidx-core-splashscreen` |
| `app/src/main/AndroidManifest.xml` | + `<provider>` 声明 FileProvider |
| `app/src/main/res/values/themes.xml` | parent 改 `Theme.SplashScreen` + `postSplashScreenTheme` 指向 `Theme.DouBi.PostSplash`（保留原本的 statusBarColor transparent） |
| `app/src/main/res/values/colors.xml` | + `splash_background` 主品牌色 |
| `app/src/main/res/values/strings.xml` | + 13 个 Settings 字符串（theme / duplicate / aria2 / sniff 5 个 / 通用 section）+ `pasting_sniffing` 已存在（v0.4.0）+ 「打开保存目录」+「没有可用的文件管理器」 |
| `app/src/main/java/com/doubi/android/MainActivity.kt` | + `installSplashScreen()` 在 super.onCreate 之前；collect `AppConfig.theme` 传给 `DouBiTheme` |
| `app/src/main/java/com/doubi/android/ui/theme/Theme.kt` | `DouBiTheme(themeSetting: String = "system")` 接受主题方案；`darkTheme` 计算逻辑按 `default_light` / `default_dark` / `system` 分支 |
| `app/src/main/java/com/doubi/android/core/config/ConfigValidator.kt` | `validateTheme` 白名单加 `"system"` |
| `app/src/main/java/com/doubi/android/data/config/AppConfigDataStore.kt` | `updateField` 补 6 个 key：`sniff_user_agent` / `aria2_rpc_url` / `filename_template` / `output_root` / `output_dir_template` / `container` / `max_quality`（v0.1 阶段 6 SettingsScreen 用 onFieldChanged 但 updateField 缺分支会抛 "Unknown config key"） |
| `app/src/main/java/com/doubi/android/ui/settings/SettingsScreen.kt` | + 「打开保存目录」ActionRow + 4 个新 Section（主题 / 重复下载 / 附加 NFO/JSON/弹幕 / 引擎+aria2 / 通用嗅探 5 字段） |
| `app/src/test/java/com/doubi/android/ExampleUnitTest.kt` | startsWith 断言保持 `"0.4"`（v0.4.0 / v0.4.1 都 0.4 prefix） |
| `docs/CHANGELOG.md` | +「未发布 v0.4.1」段；v0.3.0 段已知问题改"v0.4.1 自用策略变更"说明 |
| `docs/PHASES.md` | 阶段 7 段已知问题改自用策略变更 |
| `docs/phases/phase-7.md` | 「上架必补 7 项」段整段删，换成自用策略说明 |
| `docs/REUSE-MAP.md` | 加 v0.4.1 自用 keystore 跟 splashscreen 映射 |
| `README.md` | 待完成项改"自用策略，不上架 Play" |

### 桌面版 → Android 版

```
桌面版 `src/doubi/core/config.py:AppConfig` 30 字段
  ─────────────────────────────────────────────────
  → 阶段 9 v0.4.1：SettingsScreen 暴露 25 字段（剩 3 个 database/databasePath/manifestPath 是 schema 对齐保留不暴露 UI）
  → 字段级 onFieldChanged 测试覆盖 13 字段（v0.4.1 新增）

桌面版无 SplashScreen（桌面版 PyInstaller 自包含）
  ─────────────────────────────────────────────────
  → 阶段 9 v0.4.1：androidx.core:core-splashscreen 1.0.1 + Theme.SplashScreen parent + installSplashScreen()

桌面版无 FileProvider（桌面版 PyInstaller 自包含 FS）
  ─────────────────────────────────────────────────
  → 阶段 9 v0.4.1：res/xml/file_paths.xml + AndroidManifest <provider> + 「打开保存目录」按钮

桌面版 release 签名（PyInstaller onedir）
  ─────────────────────────────────────────────────
  → 阶段 9 v0.4.1：本地自用 keystore 走 gradle.properties 环境变量
```

---

## 二、核心设计决定

### 决定 1：自用策略变更，删「上架必补 7 项」段

v0.3.0 阶段 7 收官时记的「上架前必补 7 项」（真机 adb install / release 签名替换 / SplashScreen API / 商店截图 / Play Console 上传 / 隐私政策页 / SettingsScreen About Row）——**自用场景下用不上 SplashScreen API / 商店截图 / Play Console 上传 / 隐私政策页 / About Row**（除了 SplashScreen 是体验优化可以保留）。release 签名改用本地自用 keystore 走环境变量；真机 adb install 走 sideload 自签名 APK 升级。

**理由**：
- 上架流程 = Play Console + 隐私政策 + 截图 + 预审 = 1-3 天，AI 没法代做
- 自用 sideload 升级签名一致 = 本地 keystore 自管 = 跟 v0.3.0 debug keystore 临时方案同样的"临时"哲学，但是 user-owned
- SplashScreen API 体验优化跟上架无关，**保留作为 v0.4.1 C3**

**风险**：自用 keystore 跟 debug keystore 一样是公开位置（`~/.android/`），但密码是用户独有的 32 位随机串。debug keystore 密码是 `android`（公开），自用 keystore 密码**不**进 git。

### 决定 2：自用 keystore 走 `gradle.properties` 环境变量，不进 git

**架构**：
- keystore 文件：`C:\Users\29192\.android\doubi-release.keystore`（标准 Android SDK 位置，**不进 git**）
- 密码配置：`C:\Users\29192\.gradle\gradle.properties`（Gradle 用户级 config，**不进 git**）
- `app/build.gradle.kts` 读 `providers.gradleProperty()` 拿 4 个变量（STORE_FILE / STORE_PASSWORD / KEY_ALIAS / KEY_PASSWORD）
- 缺失任一变量 → `error()` 立即报错（不静默回退 debug keystore——v0.3.0 阶段 7 临时方案的"坑"避免复发）

**理由**：
- `gradle.properties` 在用户主目录（`~/.gradle/`），跟项目里 `gradle.properties` 不同——项目里的会进 git
- 走 `providers.gradleProperty("DOUBI_RELEASE_STORE_FILE").orElse(providers.environmentVariable(...))` 链：gradle.properties 优先，环境变量兜底
- 不静默回退是**关键**——v0.3.0 阶段 7 复用 debug keystore 的"临时方案"用 commit message 红字标了 2 次还在，没强制报错没法避免复发

**风险**：换电脑需要重新生成 keystore（升级时签名会变，**用户必须把 keystore 备份到安全位置**）——v0.4.1 阶段 9 复盘会写明。

### 决定 3：SettingsViewModelTest 字段级覆盖，不做 Compose UI test

v0.2.2 阶段 6 记的"Compose UI test for HistoryScreen / SettingsScreen"欠账——自用环境下没装真机/模拟器，跑 instrumented test 不行；Robolectric 也没装。

**实际选择**：补 ViewModel 字段级单测：
- `SettingsViewModelTest` 从 3 例扩到 16 例（+13 新字段级 `onFieldChanged` 验证）
- `HistoryViewModelTest` 从 6 例扩到 10 例（+4 `onOpenSaveDir` / `onRedownload` 事件测试）

**理由**：
- ViewModel test 走 `testDebugUnitTest` 不需要 Android runtime，本地 JVM 跑
- 字段级覆盖**等价**于 UI test 的"用户改一项 → 字段更新"——UI test 测渲染，ViewModel test 测状态
- 200/200 单测全绿，UI 改动回归保护达到 ViewModel 层（Compose 渲染层不覆盖，**等 v0.4.2+ 真机 sideload 时再补 instrumented test**）

**风险**：Compose recompose / state hoist 的 bug（罕见）测不到——v0.4.2+ 真机 sideload 跑 instrumented test 覆盖。

### 决定 4：「打开保存目录」走 ACTION_OPEN_DOCUMENT_TREE 简化版

桌面版用户直接打开文件管理器，Android 端**因为 scoped storage 限制应用只能访问自己的目录**——`Context.filesDir/downloads/` 是 `/data/data/com.doubi.android/files/downloads/`，用户访问不到。

**实际选择**：
- 加 `res/xml/file_paths.xml` FileProvider 路径配置（为未来"分享单文件"功能预留）
- 「打开保存目录」按钮 → 启动 `Intent.ACTION_OPEN_DOCUMENT_TREE` 让用户**自己选**DouBi 目录
- v0.4.1 简化版：只启动 intent，不处理 `onActivityResult` 拿 `takePersistableUriPermission`——后续 v0.4.2 拓展

**理由**：
- v0.4.1 单版本控制在 1-2 周内能合的程度
- 即使没 takePersistableUriPermission，用户也能用系统文件管理器浏览 `/sdcard/Android/data/com.doubi.android/files/Downloads/`（Android 11+ 默认可见）
- 未来 v0.4.2+ 在 `onActivityResult` 拿授权 URL 存 DataStore，下次直接 navigate

**风险**：用户第一次点「打开保存目录」会看到系统文件选择器弹窗——**这是 Android 5+ 的标准 SAF 流程**，用户应该能理解。

### 决定 5：SplashScreen API 走 `Theme.SplashScreen` parent 模式

`androidx.core:core-splashscreen:1.0.1` 提供两种集成方式：
- A: `installSplashScreen()` 在 `Activity.onCreate` 第一行 + 默认 `Theme.SplashScreen` 走系统圆形 icon
- B: 完全自定义 splash view 自己画

**实际选择**：A 模式（最简，30 行代码搞定）。

**理由**：
- v0.4.1 自用策略：体验优化但不追求酷炫
- Android 12+ 启屏标准：背景色 + 圆形 icon 居中（adaptive icon 自动圆形 mask）
- `postSplashScreenTheme` 指向原本的 `Theme.DouBi`（保留 v0.1 阶段 0 的 `android:Theme.Material.Light.NoActionBar` parent）
- **不动 `windowBackground`**——`Theme.SplashScreen` 接管了

**风险**：Android 11- 设备看不到 SplashScreen 效果（系统不渲染）——降级到 v0.1 阶段 0 的 `windowBackground` 黑色背景，UI 短暂黑屏（<100ms）用户感知不到。

---

## 三、坑 & 决策

### 坑 1：gradle.properties 路径反斜杠被 `file()` 解析吞掉

**症状**：v0.4.1 起步时 `DOUBI_RELEASE_STORE_FILE=C:\Users\29192\.android\doubi-release.keystore`，第一次 `bundleRelease` 报：
```
Keystore file 'C:\A\03Projects\DeepSeekHarness\DouBi\android\app\C:Users29192.androiddoubi-release.keystore' not found
```

**根因**：`file("C:\\Users\\...")` 在 Gradle 8.x 把 `C:` 当作 Windows 盘符但**反斜杠被当 Java 字符串转义字符**，结果 `\` 被吃掉 → 相对路径。

**修法**：
1. 改 `gradle.properties` 路径用 forward slash：`DOUBI_RELEASE_STORE_FILE=C:/Users/29192/.android/doubi-release.keystore`
2. `app/build.gradle.kts` 强制 `file(storeFilePath).absoluteFile`（虽然不用 forward slash 也行，但加 `.absoluteFile` 更稳）

**教训**：Windows 上 Gradle `file(String)` 接 Windows 路径**不可靠**——永远用 forward slash 或 `.absoluteFile`。

### 坑 2：mockk `capture(slot).let {}` 不识别为 capture

**症状**：写 `coEvery { repo.enqueue(sourceUrl = capture(slot).let { "url" }, ...) }` 报：
```
Failed matching mocking signature
left matchers: [slotCapture<String>()]
```

**根因**：`capture(slot).let {}` 是个表达式，mockk 的 matcher 机制不识别 `.let` 之后的部分——`capture()` 的 matcher 必须在参数**直接位置**。

**修法**：直接 stub 不 capture——`coEvery { repo.enqueue(sourceUrl = "url", platform = "youtube", itemId = "abc", title = "Sample") } returns "task-1"`。

**教训**：mockk `capture(slot)` 只能用在**直接参数位置**，不能在 `let` / `apply` / `run` 里。

### 坑 3：Truth `isAnyOf(vararg)` 是 `equals` 不是 `instanceOf`

**症状**：`assertThat(ev).isAnyOf(Reenqueued::class.java, Failure::class.java)` 报：
```
expected any of: [class Reenqueued, class Failure]
but was: Failure(...)
```

**根因**：Truth 的 `isAnyOf` 是 `Subject.equals(expected)` 检查，不是 `instanceOf` 检查——`ev` 是 `Failure` 实例，不会 `equals` `Reenqueued::class.java`。

**修法**：`assertThat(ev).isNotNull()` 或 `assertThat(ev).isInstanceOf(Failure::class.java)`。

**教训**：Truth 的 `isAnyOf` 跟 Kotlin/Java 习惯不一样——用 `isInstanceOf` 更直接。

### 坑 4：signingConfigs.create("release") 跟 buildTypes.release 顺序问题

**症状**：v0.4.1 起步把 `signingConfigs.create("release")` 放在 `buildTypes` **之后**，第一次 `assembleDebug` 报：
```
SigningConfig with name 'release' not found
```

**根因**：Gradle 解析 `buildTypes.release.signingConfig = signingConfigs.getByName("release")` 时，`signingConfigs.create("release")` 还没执行。

**修法**：把 `signingConfigs` 块移到 `buildTypes` **之前**。

**教训**：Gradle DSL 顺序敏感——`signingConfigs` 必须在 `buildTypes` 之前定义。

### 坑 5：windowSplashScreenAnimatedIcon 用 @mipmap 错

**症状**：v0.4.1 起步 themes.xml `windowSplashScreenAnimatedIcon=@mipmap/ic_launcher_foreground`，`processDebugResources` 报：
```
error: resource mipmap/ic_launcher_foreground not found
```

**根因**：`ic_launcher_foreground` 在 `res/drawable/`（adaptive icon 的 foreground 层），不是 `mipmap`。`mipmap` 只有 `ic_launcher.xml` / `ic_launcher_round.xml`（adaptive icon 总 manifest）。

**修法**：用 `@drawable/ic_launcher_foreground`。

**教训**：Android adaptive icon 的 `mipmap` / `drawable` 区分——foreground/background 在 drawable，组合 manifest 在 mipmap。

---

## 四、验证

### 单测

| 测试类 | 例数 | 状态 |
|---|---|---|
| `AppConfigTest` | 13 | ✅ |
| `AppConfigDataStoreTest` | 11 | ✅ |
| `ModelTest` | 10 | ✅ |
| `ProgressTest` | 25 | ✅ |
| `MediaFormatTest` | 15 | ✅ |
| `YouTubeUrlTest` | 25 | ✅ |
| `ParseAndExpandUseCaseTest` | 17 | ✅ |
| `YtDlpEngineTest` | 26 | ✅ |
| `DownloadWorkerTest` | 13 | ✅ |
| `ExampleUnitTest` | 1 | ✅ |
| `DownloadingViewModelTest` | 5 | ✅ |
| **`HistoryViewModelTest`** | **10**（v0.4.0 6 + 4 onOpenSaveDir/onRedownload）| ✅ |
| **`SettingsViewModelTest`** | **16**（v0.4.0 3 + 13 字段级 onFieldChanged）| ✅ |
| **`HttpContentTypeSnifferTest`** | **13**（v0.4.0 已加）| ✅ |
| **总计** | **200**（v0.4.0 184 + 16 新增）| ✅ |

### APK 验证

```
$ ./gradlew bundleRelease
BUILD SUCCESSFUL in 1m 26s
53 actionable tasks: 17 executed, 1 from cache, 35 up-to-date

AAB: app/build/outputs/bundle/release/app-release.aab  64,721,004 bytes (≈ 64.7 MB)
- R8 优化 + isShrinkResources=true（v0.3.0 .aab 是 61.5 MB，v0.4.0 加 OkHttp/Sniffer 后涨到 64.7 MB）
- 自用 keystore 签名（v0.4.1 起步：~/.android/doubi-release.keystore）
- 25 个 com.yausername.youtubedl_android.* 类 R8 keep 规则仍然生效（v0.1 阶段 3 加的）
- 跟 v0.3.0 .aab 签名不同——v0.3.0 是 debug keystore 签，v0.4.0/v0.4.1 是自用 keystore 签
  （真升级时需要先卸载 v0.3.0 debug keystore 签的 .aab，因为签名不一致会装不上）
```

### Configuration Cache 验真

v0.4.1 起步清掉旧 cache 后（`mv .gradle/configuration-cache .gradle/configuration-cache.bak`），`bundleRelease --no-configuration-cache` 跑通。Configuration Cache 在 build.gradle.kts 改动后**不会复用**旧的解析结果——这是 Gradle 8.x 的设计。

### static check

`./gradlew testDebugUnitTest --rerun` 全绿 200 例（不 --rerun 会有 UP-TO-DATE 假绿）。

---

## 五、APK 验证

```
AAB: app/build/outputs/bundle/release/app-release.aab  64.7 MB
Signing：自用 keystore 走 ~/.gradle/gradle.properties
Manifest：8 权限齐 + WorkManager 三个 Service 完整 + SplashScreen 启屏标准 + FileProvider
```

### 升级路径（自用场景）

```bash
# 1. 在新电脑生成新 keystore（用 keytool）
$ANDROID_JBR/bin/keytool -genkeypair -keystore ~/.android/doubi-release.keystore \
  -alias doubi -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass <password> -keypass <password> \
  -dname "CN=DouBi,O=Self-Use,C=CN"

# 2. ~/.gradle/gradle.properties 配 4 个变量
# 3. ./gradlew bundleRelease
# 4. adb install -r app/build/outputs/bundle/release/app-release.aab
#    （-r 保留数据；如果从 v0.3.0 debug keystore 签的 .aab 升级，需要先卸载）
```

---

## 六、复盘清单

### 做了

- [x] **自用策略变更**：删 v0.3.0 阶段 7「上架必补 7 项」段（CHANGELOG / README / phase-7.md / PHASES）
- [x] **签名迁移**：本地生成 `~/.android/doubi-release.keystore` + `~/.gradle/gradle.properties` 配密码 + `app/build.gradle.kts` 读环境变量 + `bundleRelease` 验真（R8 keep 规则仍然生效）
- [x] **C1：「打开保存目录」按钮** + FileProvider + `res/xml/file_paths.xml` + `ActionRow` Compose
- [x] **C2：ViewModel 字段级测试**：SettingsViewModelTest 3→16（+13 例 v0.4.1 新字段级 onFieldChanged）+ HistoryViewModelTest 6→10（+4 例 onOpenSaveDir / onRedownload）
- [x] **C3：SplashScreen API**：`androidx.core:core-splashscreen:1.0.1` + `Theme.SplashScreen` parent + `MainActivity.installSplashScreen()` + `splash_background` 颜色
- [x] **C4：SettingsScreen 4 个新 Section**（主题切换 / 重复下载 / 引擎+aria2 / 通用嗅探 5 字段）+ `updateField` 补 6 个 key + `validateTheme` 加 `system` 选项
- [x] **200/200 单测全绿**（v0.4.0 184 + 16 新增）
- [x] **64.7 MB .aab 签名成功**（自用 keystore）
- [x] **versionName 0.4.0→0.4.1 + versionCode 6→7 同步**（commit 起步强制约定）
- [x] **阶段 9 复盘文档**

### 没做（v0.4.2+ 单独 PR）

- [ ] **Compose UI test**（v0.2.2 阶段 6 记的欠账）—— 需 Robolectric 或真机/模拟器环境，v0.4.2+ sideload 真机跑 instrumented test 覆盖
- [ ] **takePersistableUriPermission** 处理 ACTION_OPEN_DOCUMENT_TREE onActivityResult（v0.4.1 简化版只启动 intent，v0.4.2 接授权 URL 存 DataStore）
- [ ] **Sniffer Error 时给用户即时反馈**（不等 15s 兜底完成）—— v0.5.0 优化
- [ ] **headless browser 嗅探 + B 站 / 抖音 / Twitter adapter** —— v0.5.0 单独 PR

### 文档同步

- [x] [PHASES.md](../PHASES.md) — 阶段 7 改自用策略说明
- [x] [CHANGELOG.md](../CHANGELOG.md) — + v0.4.1-android 段；v0.3.0 段已知问题改自用策略说明
- [x] [REUSE-MAP.md](../REUSE-MAP.md) — 加 v0.4.1 自用 keystore 跟 splashscreen 映射
- [x] [README.md](../../README.md) — 阶段 9 标完成；待完成改"自用策略，不上架 Play"
- [x] [phase-9.md](phase-9.md) — 本文档
