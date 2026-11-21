# Keep Kotlinx Serialization DTOs and Room entities intact when R8 minification is enabled.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.SerializationKt

-keep,includedescriptorclasses class com.flacify.android.network.**$$serializer { *; }
-keepclassmembers class com.flacify.android.network.** {
    *** Companion;
}
-keepclasseswithmembers class com.flacify.android.network.** {
    kotlinx.serialization.KSerializer serializer(...);
}

-keep class com.flacify.android.data.db.** { *; }
