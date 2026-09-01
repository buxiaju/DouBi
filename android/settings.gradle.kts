pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        // yausername/yt-dlp-android 与 arthenica/ffmpeg-kit 在 JitPack 也有备份
        maven { setUrl("https://jitpack.io") }
    }
}

rootProject.name = "DouBi"
include(":app")
