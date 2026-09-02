# 环境与构建

> **状态（2026-09-02 实测）**：命令行构建**默认是坏的** —— 本机 PATH 上的 JDK 是 26，AGP 8.7.3 的
> `androidJdkImage` 这步会在它上面挂掉。**把 `JAVA_HOME` 指向 Android Studio 自带的 JBR 就绿**，
> 46 个单测全过。下面第一节给一行可复制的命令。
>
> 本文件早期版本写过「本机没有 JDK / SDK」（阶段 0 的情况）和「JDK 26 实测通过」（错误结论，已被
> 实跑推翻），两者都已作废。

## 先做这一步，否则构建失败

在 `android/` 目录下，每个新开的 PowerShell 会话先设一次：

```powershell
$env:JAVA_HOME = 'C:\A\01SoftWares\03IDE\Android Studio\jbr'
.\gradlew.bat testDebugUnitTest --rerun
```

实测结果：`BUILD SUCCESSFUL`，`testDebugUnitTest` 真执行，46/46 通过，configuration cache 正常存盘。

要一劳永逸见下文 [永久修法](#永久修法三选一)。

## 本机 JDK 全景

| JDK | 版本 | 路径 | 能否构建本项目 |
|---|---|---|---|
| 系统 PATH（Oracle javapath） | **26.0.2.1** | `C:\A\01SoftWares\04Environment\JAVA` | ❌ **失败**，见下文 |
| Android Studio JBR | **25.0.2** | `C:\A\01SoftWares\03IDE\Android Studio\jbr` | ✅ **实测通过** |
| JDK 17 / 21（AGP 官方支持区间） | — | 本机**没装** | 未验证（理论最稳） |

- `JAVA_HOME` **未设置**，所以 `gradlew.bat` 默认回退到 PATH 上的 `java`，也就是那个 26。
- Android Studio 装在 `C:\A\01SoftWares\03IDE\Android Studio`（**不在** `C:\Program Files` 下，
  容易找不到）。版本 `AI-261.26222.65.2613.15948027`。

## ⚠️ 构建失败：JDK 26 上 jlink 挂掉

### 症状

```
> Task :app:compileDebugJavaWithJavac FAILED

Execution failed for task ':app:compileDebugJavaWithJavac'.
> Could not resolve all files for configuration ':app:androidJdkImage'.
   > Failed to transform core-for-system-modules.jar to match attributes
     {artifactType=_internal_android_jdk_image, ...}.
      > Execution failed for JdkImageTransform:
        C:\Users\29192\AppData\Local\Android\Sdk\platforms\android-35\core-for-system-modules.jar.
         > Error while executing process C:\A\01SoftWares\04Environment\JAVA\bin\jlink.exe
           with arguments {--module-path ...\transforms\<hash>\workspace\transformed\output\temp\jmod
           --add-modules java.base
           --output ...\transforms\<hash>\workspace\transformed\output\jdkImage
           --disable-plugin system-modules}
```

开着 configuration cache（项目默认）时会**先**撞一条看起来完全无关的报错，其实同一个根因：

```
Configuration cache state could not be cached: field 'generatedModuleFile' of
'com.android.build.gradle.tasks.JdkImageInput' ... error writing value of type 'TransformBackedProvider'
```

→ **别去查 configuration cache**，那是被 transform 失败带崩的表象。

### 根因

AGP 要给 `compileDebugJavaWithJavac` 造一个「Android 版 system modules 镜像」，做法是调**运行 Gradle
那个 JDK** 的 `jlink`，把 SDK 里的 `core-for-system-modules.jar` 转成 jdkImage。JDK 26 的 `jlink`
在这一步失败，JBR 25 的 `jlink` 成功。

排除过的两个猜测：

- **不是** `--disable-plugin` 参数被移除：JDK 26 和 JBR 25 的 `jlink --help` 都还有这个选项。
- **不是** `system-modules` 插件被删：两边 `jlink --list-plugins` 都列出 `--system-modules`。

jlink 自己的 stderr 被 Gradle 的 `ProcessException` 吞掉了，没取到更细的原因，所以「JDK 26 具体哪
一条约束不满足」**没查到底**。不过对干活来说够了：AGP 8.7.3 官方支持的是 JDK 17（上限 21），26 和 25
都在支持区间外，**25 能用是实测碰对了，不是官方保证**。

### A/B 实测证据（2026-09-02）

| 运行 | JAVA_HOME | 命令 | 结果 | 日志 |
|---|---|---|---|---|
| A | 不设（→ JDK 26） | `testDebugUnitTest --rerun --no-configuration-cache` | ❌ `BUILD FAILED in 14s`，挂在 `androidJdkImage` | `.scratch/gradle_jdk26_recheck.log` |
| B | AS JBR 25 | `testDebugUnitTest --rerun --no-configuration-cache` | ✅ `BUILD SUCCESSFUL in 4s`，46/46 | `.scratch/gradle_jbr25_rerun.log` |
| C | AS JBR 25 | `testDebugUnitTest --rerun`（**开** CC） | ✅ `BUILD SUCCESSFUL in 5s`，`Configuration cache entry stored.` | `.scratch/gradle_jbr25_cc.log` |

A 和 B/C 共用同一个 transform 缓存目录还能一个失败一个成功 → 说明这个 transform 的缓存键**带 JDK 身份**，
换 JDK 就必须重跑 jlink。

> `.scratch/` 已在 `.gitignore` 里，上面那些日志**只在本机**，换机器看不到，重跑一遍即可复现。

### 为什么阶段 1、2 当时是绿的

`.scratch/gradle_test_v02f.log` 里那次构建，`:app:compileDebugJavaWithJavac` 是 **UP-TO-DATE** ——
jdkImage 是更早留下的缓存产物，jlink 根本没被调。后来 wrapper 升到 Gradle 9.3.0，transform 缓存路径
变成 `caches/9.3.0/transforms/`，旧产物不再命中，这一步**第一次真正执行**，才暴露出来。

所以：**这不是代码或依赖问题，也不是文档改动引起的**，是一直存在、被缓存盖住的环境问题。

### 永久修法（三选一）

**1）用户级 `gradle.properties`（推荐，不进仓库）**

`C:\Users\29192\.gradle\gradle.properties`（当前是空的 / 不存在），加一行：

```properties
org.gradle.java.home=C:/A/01SoftWares/03IDE/Android Studio/jbr
```

路径用正斜杠，别用反斜杠。影响本机所有 Gradle 项目 —— 本机目前只有这一个 Gradle 项目，所以没副作用。

**2）装 JDK 17 或 21，再指过去（最稳，但要装东西）**

AGP 8.7.3 官方支持区间内的版本，然后同样用 `org.gradle.java.home` 指过去。
本机没装，也**没验证过**。

**3）每次会话设 `$env:JAVA_HOME`（零配置，但要记得）**

就是本文开头那一行。适合不想改任何配置文件的场景。

> **为什么不写进项目里的 `gradle.properties`**：那个文件进 git，路径是本机专属的，写进去等于把
> 别人的构建搞坏。机器专属配置一律放用户级或环境变量。
>
> **别改 `jvmTarget` / `sourceCompatibility`**：`build.gradle.kts` 里的 `VERSION_17` 是**编译产出的
> 字节码目标**，跟「用哪个 JDK 跑 Gradle」是两件事，改它治不了这个病。

## 实测环境

| 项 | 实测值 | 备注 |
|---|---|---|
| Gradle | **9.3.0**（wrapper 锁定） | `gradle/wrapper/gradle-wrapper.properties`。与 AGP 8.7.3 可用，但会报「incompatible with Gradle 10」弃用警告 |
| JDK（跑 Gradle） | **JBR 25.0.2**（AS 自带） | ✅ 唯一实测能用的。系统 JDK 26 ❌ |
| JDK（字节码目标） | 17 | `app/build.gradle.kts` 的 `sourceCompatibility` / `jvmTarget` |
| AGP | 8.7.3 | `gradle/libs.versions.toml` |
| Kotlin | 2.0.21（K2） | KSP 2.0.21-1.0.27 与之对齐 |
| Android SDK | compileSdk 35 / minSdk 24 / targetSdk 35 | `sdk.dir=C:\Users\29192\AppData\Local\Android\Sdk` |
| configuration cache | 开（`gradle.properties`） | JBR 25 下正常存盘 |
| 耗时 | 全 UP-TO-DATE 约 **20s**（含起 daemon）；单测强制重跑约 **4–5s** | |

## 命令行构建（PowerShell）

**不要用 `&&`**，PowerShell 用 `;`。所有命令在 `android/` 目录下执行，且**先设 `JAVA_HOME`**（除非已用永久修法）：

```powershell
$env:JAVA_HOME = 'C:\A\01SoftWares\03IDE\Android Studio\jbr'

# 跑全部单元测试（JVM，最常用；当前 46 个用例）
.\gradlew.bat testDebugUnitTest

# ⚠️ 上一条可能报 UP-TO-DATE 直接返回成功而一个测试都没跑。
#    想确认测试真的绿，必须加 --rerun：
.\gradlew.bat testDebugUnitTest --rerun

# 只编译，不测
.\gradlew.bat assembleDebug

# 编译 + 单测 + lint（提交前跑一遍）
.\gradlew.bat build

# 仪器测试（需真机或模拟器；当前 7 个用例从未跑过，见 PHASES.md 欠账 #4）
.\gradlew.bat connectedDebugAndroidTest

# 出 release 包：APK 用 assembleRelease，上架用的 .aab 用 bundleRelease
.\gradlew.bat bundleRelease

# 构建卡住 / 结果诡异时，先停 daemon 再清
.\gradlew.bat --stop
.\gradlew.bat clean
```

> **`UP-TO-DATE` 假绿是真踩过的坑**：本文件之前写「46 个单测实测全绿」，其实那次
> `testDebugUnitTest` 是 UP-TO-DATE，测试根本没执行。要报数就带 `--rerun`，或者直接看下面的报告文件时间戳。

### 当前测试构成（46 个单测）

| 测试类 | 用例数 | 位置 |
|---|---|---|
| `AppConfigTest` | 13 | `app/src/test/java/com/doubi/android/core/config/` |
| `AppConfigDataStoreTest` | 11 | `app/src/test/java/com/doubi/android/data/config/` |
| `YtDlpEngineTest` | 11 | `app/src/test/java/com/doubi/android/engine/ytdlp/` |
| `ModelTest` | 10 | `app/src/test/java/com/doubi/android/core/model/` |
| `ExampleUnitTest` | 1 | 模板残留 |

报告落在：

- HTML：`app/build/reports/tests/testDebugUnitTest/index.html`
- XML（CI 用）：`app/build/test-results/testDebugUnitTest/*.xml`

仪器测试另有 7 个（`MediaItemDaoTest` 6 + 模板 1），**从未执行过**。

### 三条可以忽略的警告

构建成功时也会打，**都不是错误**：

1. `Deprecated Gradle features were used in this build, making it incompatible with Gradle 10.`
   —— AGP 8.7.3 用了 Gradle 9 里已弃用的 API。升 Gradle 10 前要先升 AGP，阶段 7 再处理。
2. `WARNING: sun.misc.Unsafe::arrayBaseOffset has been called by androidx.datastore.preferences.protobuf...`
   —— DataStore 内置 protobuf 在新 JDK 上访问 `Unsafe`。上游问题，与本项目代码无关。
3. `app/build.gradle.kts:55: 'kotlinOptions' is deprecated. ... migrate to the compilerOptions types`
   —— Kotlin 2.0 的迁移提示，改法见 [kotl.in/u1r8ln](https://kotl.in/u1r8ln)，不急。

## 在 Android Studio 里打开

1. Android Studio → **File → Open**
2. 选 `C:\A\03Projects\DeepSeekHarness\DouBi\android\` 目录（**不是仓库根，是这个子目录**）
3. 等 Sync 完毕，看到 `BUILD SUCCESSFUL` 说明工具链通了
4. 顶部工具栏 Run（绿色三角）→ 选手机 / 模拟器

> **AS 里大概率一次就通**，因为它默认用自带的 JBR 25 —— 正是命令行需要手动指的那个。
> 确认位置：**Settings → Build, Execution, Deployment → Build Tools → Gradle → Gradle JDK**，
> 应该是 `jbr-25`（或写着 `Android Studio default JDK`）。**别在这里选系统的 JDK 26**。
>
> 「AS 能构建、命令行不能」就是这个原因造成的。

## 首次装环境（如果换机器）

| 工具 | 版本 | 用途 |
|---|---|---|
| **JDK** | **17 或 21**（AGP 8.7.3 官方支持）；26 ❌ 不行 | 运行 Gradle |
| **Android Studio** | Koala (2024.1) 或更新 | IDE，自带可用的 JBR |
| **Android SDK** | Platform 35 / Build-Tools 35.0.0 | `compileSdk = 35` |
| **Kotlin** | 2.0.21 | 由 AS 插件托管，无需独立装 |
| **物理手机 / 模拟器** | Android 7.0+（API 24） | 跑应用 |

1. **JDK** —— [Microsoft OpenJDK](https://learn.microsoft.com/java/openjdk/download) 或
   [Eclipse Temurin](https://adoptium.net/)，选 **17** 或 **21**，装完 `java -version` 验证。
   **别只装最新版**，太新的 JDK 会撞上文那个 jlink 问题。
2. **Android Studio** —— 默认会引导装 SDK。若跳过：More Actions → SDK Manager → SDK Platforms 勾
   **Android 15 (API 35)**；SDK Tools 勾 **Build-Tools 35** / **Platform-Tools** / **Emulator**
3. **环境变量**：`ANDROID_HOME` = `C:\Users\<你>\AppData\Local\Android\Sdk`，
   `PATH` 加 `%ANDROID_HOME%\platform-tools`
4. **`local.properties`** —— **不进 git**（已在 `.gitignore`）。换机器自己建，一行：
   `sdk.dir=C\:\\Users\\<你>\\AppData\\Local\\Android\\Sdk`

## 构建失败排查

| 报错 | 修法 |
|---|---|
| `Failed to transform core-for-system-modules.jar` / `Error while executing process ...jlink.exe` | **本机头号问题**。Gradle 跑在 JDK 26 上了。把 `JAVA_HOME` 或 `org.gradle.java.home` 指向 AS 的 JBR，见上文 |
| `Configuration cache state could not be cached: field 'generatedModuleFile' of 'JdkImageInput'` | 同一个根因的表象，**别去查 configuration cache**，先修 JDK |
| `BUILD SUCCESSFUL` 但没有任何测试执行 | `testDebugUnitTest` 是 UP-TO-DATE。加 `--rerun` |
| `SDK location not found` | `local.properties` 缺失或 `sdk.dir` 不对，见上文第 4 步 |
| `[ksp] java.lang.IllegalArgumentException` | **别动 `gradle.properties` 里的 `ksp.useKSP2=false`**。Hilt 2.52 + KSP 1.0.27 在 KSP2 模式下会抛这个（[Dagger #4680](https://github.com/google/dagger/issues/4680)）。详见 [phase-1.md](phases/phase-1.md) 坑 1 |
| `Unresolved reference 'truth'` / `'runTest'` | 测试库只加在 `testImplementation`，`androidTest` 看不到。两个作用域都要加，见 [phase-1.md](phases/phase-1.md) 坑 2 / 坑 3 |
| `Unresolved reference 'ytdlp'` | 引擎包名是 `com.yausername.youtubedl_android.*`，**不是** `com.yausername.ytdlp.*`。见 [phase-2.md](phases/phase-2.md) 坑 3 |
| `Received status code 401` from jitpack | 引擎依赖已换到 Maven Central 的 `io.github.junkfood02.youtubedl-android:library`，不该再走 JitPack。见 [phase-2.md](phases/phase-2.md) 坑 1 |
| 网络下载依赖慢 | 见下文镜像配置 |

### 国内网络加速（可选）

在 `~/.gradle/init.gradle.kts` 加（只改仓库镜像，不动 build 脚本）：

```kotlin
allprojects {
    repositories {
        maven { setUrl("https://maven.aliyun.com/repository/google") }
        maven { setUrl("https://maven.aliyun.com/repository/central") }
        maven { setUrl("https://maven.aliyun.com/repository/gradle-plugin") }
        google()
        mavenCentral()
    }
}
```

> ⚠️ 引擎依赖 `io.github.junkfood02.youtubedl-android` 在 Maven Central 上，阿里云 central 镜像通常有；
> 若镜像同步滞后导致解析失败，把 `mavenCentral()` 放前面或临时去掉镜像。

## 跑起来能看到什么

当前（阶段 2 收官）Run 起来只有一个占位页面：中央显示「DouBi Android」+ 版本号，
**没有导航、没有 4 个页面** —— 那是阶段 3 的工作。

下载功能的代码链路是通的（`DownloadRepository.enqueue` → WorkManager → `YtDlpEngine` → 落盘
`filesDir/downloads/`），但**没有任何 UI 入口触发它**，而且这条链路**从未在真机上验证过**。
见 [PHASES.md 的跨阶段欠账 #5](PHASES.md)。

下一步工作见 [PHASES.md 阶段 3](PHASES.md)。
