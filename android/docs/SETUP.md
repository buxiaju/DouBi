# 第一次打开这个项目

本机**目前没有 JDK / Android SDK / Gradle**（截至创建本文件时）。本节讲清楚装什么、怎么打开这个目录。

## 前置依赖

| 工具 | 最低版本 | 用途 |
|---|---|---|
| **JDK 17** | 17.0.10+ | AGP 8.7 强制要求 |
| **Android Studio** | Hedgehog (2023.1) 或更新 | IDE；推荐 Koala (2024.1) 之后 |
| **Android SDK** | Platform 35 / Build-Tools 35.0.0 | compileSdk = 35 |
| **Kotlin** | 2.0.21 | 由 Android Studio 插件托管，无需独立装 |
| **物理手机 / 模拟器** | Android 7.0+（API 24） | 跑应用 |

### 安装步骤（Windows）

1. **JDK 17**（如果系统没装）—— 推荐用 [Microsoft OpenJDK 17](https://learn.microsoft.com/java/openjdk/download) 或 [Eclipse Temurin 17](https://adoptium.net/)。装完后在 PowerShell 验证：

   ```powershell
   java -version
   # openjdk version "17.0.10" 2024-01-16
   ```

2. **Android Studio**（你刚装过）—— 默认会引导你装 Android SDK。如果跳过：
   - 打开 Android Studio → More Actions → SDK Manager
   - SDK Platforms 勾 **Android 15 (API 35)**
   - SDK Tools 勾 **Android SDK Build-Tools 35** / **Android SDK Platform-Tools** / **Android Emulator**（如要模拟器）

3. **环境变量**（装完 Android SDK 后）：
   - `ANDROID_HOME` = `C:\Users\<你>\AppData\Local\Android\Sdk`
   - `PATH` 加 `%ANDROID_HOME%\platform-tools` 和 `%ANDROID_HOME%\emulator`

## 在 Android Studio 里打开

1. Android Studio → **File → Open**
2. 选 `C:\A\03Projects\DeepSeekHarness\DouBi\android\` 目录（**不是仓库根，是这个子目录**）
3. 第一次打开会提示：
   - "Gradle Wrapper not found, would you like to create one?" → **Yes**
   - 自动选默认 Gradle 8.10.2 / AGP 8.7.0 / Kotlin 2.0.21 → **OK**
4. 等 Sync 完毕（左下角进度条），看到 `BUILD SUCCESSFUL` 就说明工具链通了
5. 顶部工具栏 Run 按钮（绿色三角）→ 选你的手机 / 模拟器 → 第一次跑会下载 Compose 等依赖，约 5-10 分钟

### Sync 失败常见原因

| 报错 | 修法 |
|---|---|
| `Could not find tools.jar` | JDK 没装对版本；确认 `java -version` 是 17 |
| `SDK location not found` | File → Project Structure → SDK Location → 选 SDK 路径 |
| `Minimum supported Gradle version is X` | 用 Android Studio 自带的「Update Gradle wrapper」功能 |
| 网络下载依赖失败 | Gradle 用 Google 仓 + Maven Central，中国大陆可能慢；配 Gradle 代理见下 |

### 国内网络加速（可选）

在 `~/.gradle/init.gradle.kts` 加：

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

不影响 build 脚本本身，只改仓库镜像。

## 跑起来能看到什么

第一次跑通后应该看到：

- 启动屏 `DouBi` Logo → 主页面（v0 阶段是个占位 `HomeScreen`，中央显示「DouBi Android」+ 版本号）
- 没有崩溃、没有 ANR

这就算工具链通了，可以进 [PHASES.md](PHASES.md) 阶段 1 的工作。
