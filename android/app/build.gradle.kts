// 欠账 #6 已还：jacoco 覆盖率（plugin 在根 build.gradle.kts 用 buildscript classpath 引入，
// 这里 apply。jacoco plugin marker artifact 不在 Gradle Plugin Portal / Google maven，
// 只能走传统 classpath 方式）
import org.gradle.testing.jacoco.plugins.JacocoTaskExtension
import org.gradle.testing.jacoco.tasks.JacocoReport

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
    alias(libs.plugins.hilt)
}

apply(plugin = "org.gradle.jacoco")

android {
    namespace = "com.doubi.android"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.doubi.android"
        // 桌面版 0.3.1 起独立递增；Android 版独立版本号：
        // v0.1.0 = 1（阶段 3 收官候选）
        // v0.2.0 = 2（阶段 4 解析 + 列表）
        // v0.2.1 = 3（阶段 5 下载 + 进度 + 完成通知）
        // v0.2.2 = 4（阶段 6 历史 + 设置）
        // v0.5.0 = 8（阶段 10 headless browser 嗅探：WebViewHolder + WebViewHeadlessSniffer
        //   + CompositeSniffer 按 AppConfig.sniffHeadless 动态选 http/headless）
        versionCode = 8
        versionName = "0.5.0"

        minSdk = 24
        targetSdk = 35
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables {
            useSupportLibrary = true
        }
        // JunkFood02/yt-dlp-android 带的 native lib 限制 ABIs——和 README 写的一致
        ndk {
            abiFilters += listOf("x86", "x86_64", "armeabi-v7a", "arm64-v8a")
        }
    }

    // 阶段 9 v0.4.1：自用 release keystore 走 gradle.properties 环境变量。
    // keystore 跟密码**本地**生成，**不进 git**——用户在 `~/.gradle/gradle.properties`
    // 配 `DOUBI_RELEASE_STORE_FILE` / `DOUBI_RELEASE_STORE_PASSWORD` /
    // `DOUBI_RELEASE_KEY_ALIAS` / `DOUBI_RELEASE_KEY_PASSWORD` 四个变量。
    //
    // 生成 keystore（一次性）：
    //   $ANDROID_JBR/bin/keytool -genkey -v \
    //     -keystore ~/.android/doubi-release.keystore \
    //     -alias doubi -keyalg RSA -keysize 2048 -validity 10000 \
    //     -storepass <password> -keypass <password> \
    //     -dname "CN=DouBi,O=Self-Use,C=CN"
    //
    // 缺失任何一个变量 → build 立即报错（不静默回退 debug keystore）。
    signingConfigs {
        create("release") {
            val storeFilePath = providers.gradleProperty("DOUBI_RELEASE_STORE_FILE")
                .orElse(providers.environmentVariable("DOUBI_RELEASE_STORE_FILE"))
                .orNull
                ?: error("release keystore 未配置：在 ~/.gradle/gradle.properties 设 DOUBI_RELEASE_STORE_FILE（路径）")
            // Windows 反斜杠会被 file() 当转义字符吃掉，强制走 absoluteFile 转绝对路径
            storeFile = file(storeFilePath).absoluteFile
            storePassword = providers.gradleProperty("DOUBI_RELEASE_STORE_PASSWORD")
                .orElse(providers.environmentVariable("DOUBI_RELEASE_STORE_PASSWORD"))
                .orNull
                ?: error("release keystore 密码未配置：在 ~/.gradle/gradle.properties 设 DOUBI_RELEASE_STORE_PASSWORD")
            keyAlias = providers.gradleProperty("DOUBI_RELEASE_KEY_ALIAS")
                .orElse(providers.environmentVariable("DOUBI_RELEASE_KEY_ALIAS"))
                .orNull
                ?: error("release key alias 未配置：在 ~/.gradle/gradle.properties 设 DOUBI_RELEASE_KEY_ALIAS")
            keyPassword = providers.gradleProperty("DOUBI_RELEASE_KEY_PASSWORD")
                .orElse(providers.environmentVariable("DOUBI_RELEASE_KEY_PASSWORD"))
                .orNull
                ?: error("release key 密码未配置：在 ~/.gradle/gradle.properties 设 DOUBI_RELEASE_KEY_PASSWORD")
        }
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            // 欠账 #6 已还：debug build 启用 jacoco 单元测试覆盖率
            enableUnitTestCoverage = true
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            // 阶段 9 v0.4.1 自用策略：release 签名读 ~/.gradle/gradle.properties 里的
            // 自用 keystore 信息。keystore 跟密码**不进 git**——本地生成。
            //
            // 缺失时的行为：build 报「找不到 release keystore」错误，不静默回退到
            // debug keystore（v0.3.0 阶段 7 的临时方案，自用场景下不再需要）。
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
        freeCompilerArgs += listOf(
            "-opt-in=kotlin.RequiresOptIn",
            "-opt-in=androidx.compose.material3.ExperimentalMaterial3Api",
            "-opt-in=androidx.compose.foundation.ExperimentalFoundationApi"
        )
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
            excludes += "/META-INF/DEPENDENCIES"
        }
        // AGP 8.7+ 默认把 .so 按 page-aligned 方式打入（解压后用 mmap），需要关闭
        // extractNativeLibs。但本项目 AndroidManifest.xml 里 `android:extractNativeLibs="true"`
        // 仍然保留（防 miniSdk 24 上某些定制系统 load 不动 mmapped .so，且与 ndk 库的旧行为兼容），
        // 所以这里要显式声明 useLegacyPackaging = true，否则 AGP 会喷 warning。
        jniLibs {
            useLegacyPackaging = true
        }
    }

    testOptions {
        unitTests {
            isIncludeAndroidResources = true
            isReturnDefaultValues = true
        }
    }

    // 欠账 #3 已还：导出 Room schema 到 app/schemas/，并把 app/schemas/ 打进
    // androidTest 资源——MigrationTestHelper 用它来跑 v1→v2 迁移测试
    sourceSets {
        getByName("androidTest").assets.srcDirs("$projectDir/schemas")
    }
}

// 欠账 #3 已还：Room schema 导出位置（KSP 选项）
ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

// 欠账 #6 已还：jacoco 覆盖率报告（XML + HTML）。
// 运行：`.\gradlew.bat testDebugUnitTest jacocoTestReport`
// 报告落在 app/build/reports/jacoco/jacocoTestReport/{html/index.html,jacocoTestReport.xml}
tasks.withType<Test>().configureEach {
    extensions.configure(JacocoTaskExtension::class) {
        // 排除 KSP 生成的 stub（没有覆盖价值）+ 第三方 lib（不在本项目范围内）
        // JacocoTaskExtension.excludes 是 List<String>?——保险起见用 ?:
        excludes = (excludes ?: emptyList()) + listOf(
            "**/R.class",
            "**/R$*.class",
            "**/BuildConfig.class",
            "**/*\$\$serializer*.class",     // kotlinx.serialization 生成的
            "**/*_Factory*.class",            // Hilt 生成的
            "**/*_Provide*Factory*.class",
            "**/*_HiltModules*.class",
            "**/*_GeneratedInjector*.class",
            "**/Dagger*Component*.class",
            "**/Hilt_*.class",
            "**/*_Impl*.class",                // Room / Hilt impl 类
        )
    }
}

dependencies {
    // AndroidX core
    implementation(libs.androidx.core.ktx)
    // 阶段 9 v0.4.1：SplashScreen API（Android 12+ 圆形图标 + 背景色标准启屏）
    implementation(libs.androidx.core.splashscreen)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.activity.compose)

    // Lifecycle
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)

    // Compose
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.extended)
    debugImplementation(libs.androidx.compose.ui.tooling)

    // Navigation
    implementation(libs.androidx.navigation.compose)

    // Hilt
    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)
    implementation(libs.hilt.navigation.compose)
    implementation(libs.hilt.work)
    ksp(libs.hilt.work.compiler)

    // Room（阶段 1 启用）
    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)

    // DataStore（阶段 1 启用）
    implementation(libs.datastore.preferences)

    // WorkManager（阶段 2 启用）
    implementation(libs.work.runtime.ktx)

    // Network（阶段 4 启用）
    implementation(libs.retrofit)
    implementation(libs.retrofit.kotlinx.serialization)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.kotlinx.serialization.json)

    // Coroutines
    implementation(libs.kotlinx.coroutines.android)

    // Logging
    implementation(libs.timber)

    // 下载引擎（阶段 2 兑底：Maven Central 的 junkfood02 youtubedl-android）
    // Java 包名是 com.yausername.youtubedl_android.*（不是 com.yausername.ytdlp.*）。
    // 自带 yt-dlp + Python 3.8 静态打包，体积约 30MB。
    // ffmpeg-kit（HLS / 音频提取 / 视频合并）暂不开——没有它就没有 HLS 兜底方案。
    implementation(libs.ytdlp.android)
    // implementation(libs.ffmpeg.kit)

    // 单元测试
    testImplementation(libs.junit)
    testImplementation(libs.mockk)
    testImplementation(libs.turbine)
    testImplementation(libs.truth)
    testImplementation(libs.kotlinx.coroutines.test)

    // 仪器测试
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    // 阶段 1 漏的：androidTestImplementation 也得加 truth（与 testImplementation 配对）
    androidTestImplementation(libs.truth)
    // 同上：runTest / TestScope 等协程测试工具也得加
    androidTestImplementation(libs.kotlinx.coroutines.test)
    // 欠账 #3 已还：MigrationTestHelper 用于写 v1→v2 迁移测试；需要把 schemas/
    // 打进 androidTest 资源（详见 build.gradle.kts 的 sourceSets）
    androidTestImplementation(libs.room.testing)
}

// 欠账 #3 已还：Room schema 导出位置（KSP 选项）
ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

// 欠账 #6 已还：jacoco 覆盖率。
// apply(plugin = "org.jacoco") + JacocoTaskExtension 让 :app:testDebugUnitTest 产出 jacoco.exec；
// 配合下方 jacocoTestReportXml 任务把它转成 XML 给 CI（sonarqube / codecov）吃。
// AGP 自带 createDebugUnitTestCoverageReport 出 HTML 报告（app/build/reports/coverage/test/debug/）。

tasks.withType<Test>().configureEach {
    extensions.configure(JacocoTaskExtension::class) {
        // 排除 KSP 生成的 stub（没有覆盖价值）+ 第三方 lib（不在本项目范围内）
        excludes = (excludes ?: emptyList()) + listOf(
            "**/R.class",
            "**/R$*.class",
            "**/BuildConfig.class",
            "**/*\$\$serializer*.class",     // kotlinx.serialization 生成的
            "**/*_Factory*.class",            // Hilt 生成的
            "**/*_Provide*Factory*.class",
            "**/*_HiltModules*.class",
            "**/*_GeneratedInjector*.class",
            "**/Dagger*Component*.class",
            "**/Hilt_*.class",
            "**/*_Impl*.class",                // Room / Hilt impl 类
            "**/databinding/**",
        )
    }
}

tasks.register<JacocoReport>("jacocoTestReport") {
    dependsOn("testDebugUnitTest")
    group = "verification"
    description = "把 jacoco.exec 转成 XML 给 CI / sonarqube / codecov 吃"

    // AGP 8.7+ 把 jacoco.exec 落在 build/outputs/unit_test_code_coverage/<variant>UnitTest/<test>UnitTest.exec
    val execFile = layout.buildDirectory.file(
        "outputs/unit_test_code_coverage/debugUnitTest/testDebugUnitTest.exec"
    )

    classDirectories.setFrom(
        fileTree(layout.buildDirectory.dir("intermediates/javac/debug/classes")) {
            exclude(
                "**/R.class",
                "**/R$*.class",
                "**/BuildConfig.class",
                "**/*\$\$serializer*.class",
                "**/*_Factory*.class",
                "**/*_Provide*Factory*.class",
                "**/*_HiltModules*.class",
                "**/*_GeneratedInjector*.class",
                "**/Dagger*Component*.class",
                "**/Hilt_*.class",
                "**/*_Impl*.class",
                "**/databinding/**",
            )
        },
        fileTree(layout.buildDirectory.dir("tmp/kotlin-classes/debug")) {
            exclude(
                "**/*\$\$serializer*.class",
                "**/*_Factory*.class",
                "**/*_Provide*Factory*.class",
                "**/*_HiltModules*.class",
                "**/*_GeneratedInjector*.class",
                "**/Dagger*Component*.class",
                "**/Hilt_*.class",
                "**/*_Impl*.class",
            )
        },
    )
    sourceDirectories.setFrom(files("src/main/java", "src/main/kotlin"))
    executionData.setFrom(files(execFile))

    reports {
        xml.required.set(true)
        html.required.set(false)
        csv.required.set(false)
    }
}
