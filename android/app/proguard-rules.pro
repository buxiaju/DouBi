# Add project specific ProGuard rules here.
# Stage 7 will add proper R8 rules; for stages 0-6 the debug build is enough.

# Hilt（必加，否则反射失败）
-keep class dagger.hilt.** { *; }
-keep class * extends dagger.hilt.android.HiltAndroidApp
-keep,allowobfuscation,allowshrinking class * extends androidx.hilt.work.HiltWorker

# Room
-keep class androidx.room.** { *; }
-keep @androidx.room.Entity class * { *; }
-keep @androidx.room.Dao class * { *; }

# 下载引擎（欠账 #3 part 2，v0.1.0 已还）
# junkfood02/youtubedl-android 内部通过 Java 反射加载 Python 解释器与 native lib，
# R8 把内部类名混淆掉会让 release 包启动时 ClassNotFoundException。
# 整个 com.yausername.youtubedl_android.* 包名（注意 _android 后缀）原样保留。
-keep class com.yausername.youtubedl_android.** { *; }
-keep class com.yausername.ytdl.** { *; }
-keep class com.yausername.ffmpeg.** { *; }   # 阶段 5+ 接 ffmpeg-kit 时也用得上
-dontwarn com.yausername.youtubedl_android.**
-dontwarn com.yausername.ytdl.**
-dontwarn com.yausername.ffmpeg.**

# kotlinx.serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt
-keep,includedescriptorclasses class com.doubi.android.**$$serializer { *; }
-keepclassmembers class com.doubi.android.** {
    *** Companion;
}
-keepclasseswithmembers class com.doubi.android.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# Compose
-keep class androidx.compose.runtime.** { *; }
