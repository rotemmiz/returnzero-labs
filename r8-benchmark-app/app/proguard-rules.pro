# Keep Retrofit
-keepattributes Signature, Exceptions, RuntimeVisibleAnnotations, RuntimeVisibleParameterAnnotations
-keepclassmembers,allowshrinking,allowobfuscation interface * {
    @retrofit2.http.* <methods>;
}
-keep,allowobfuscation,allowshrinking interface retrofit2.Call
-keep,allowobfuscation,allowshrinking class retrofit2.Response
-keep,allowobfuscation,allowshrinking class kotlin.coroutines.Continuation

# Keep kotlinx.serialization
-keepattributes *Annotation*, InnerClasses
-keepclassmembers class com.returnzero.benchmark.** {
    *** Companion;
}
-keepclasseswithmembers class com.returnzero.benchmark.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keepclassmembers class com.returnzero.benchmark.data.** {
    *** INSTANCE;
}
-keepclassmembers @kotlinx.serialization.Serializable class com.returnzero.benchmark.data.** {
    *** Companion;
}

# Keep Room generated implementations
-keep class * extends androidx.room.RoomDatabase { *; }
-keep @androidx.room.Entity class * { *; }
-keep class androidx.room.* { *; }

# Keep Coil
-keep class coil.compose.** { *; }