// 根 project 配置：只声明插件版本，不写依赖。
// 各 module 在自己的 build.gradle.kts 里 apply 需要的插件。

// 欠账 #6 已还：jacoco plugin 不在 Gradle Plugin Portal（plugin marker 没发布），
// 用传统 buildscript classpath 方式加载。AGP 8.7 起 jacoco report 走独立 task，
// 见 app/build.gradle.kts 的 jacocoTestReport。
buildscript {
    dependencies {
        classpath("org.jacoco:org.jacoco.core:0.8.12")
    }
}

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.ksp) apply false
    alias(libs.plugins.hilt) apply false
}
