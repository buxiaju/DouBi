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
