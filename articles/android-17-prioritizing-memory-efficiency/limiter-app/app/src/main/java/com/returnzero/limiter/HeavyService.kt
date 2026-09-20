package com.returnzero.limiter

import android.app.Service
import android.content.Intent
import android.os.IBinder
import android.os.Process
import kotlin.concurrent.thread

class HeavyService : Service() {

    private val allocator = Allocator()

    override fun onBind(intent: Intent?): IBinder = android.os.Binder()

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.getBooleanExtra("prepare", false) == true) {
            thread {
                val file = java.io.File(filesDir, "limiter-pages.bin")
                java.io.RandomAccessFile(file, "rw").use { out ->
                    out.setLength(0)
                    val block = ByteArray(1024 * 1024)
                    java.util.Random(17037).nextBytes(block)
                    repeat(256) { out.write(block) }
                    out.fd.sync()
                }
                android.util.Log.i("LimiterExp", "prepared bytes=${file.length()}")
            }
            return START_NOT_STICKY
        }
        if (intent?.hasExtra("mode") == true) {
            val mode = intent.getIntExtra("mode", 0)
            val total = intent.getIntExtra("total_mb", 256).coerceIn(4, 512)
            thread {
                for (offset in 0 until total step 4) {
                    val ok = allocator.nativeStep(mode, java.io.File(filesDir, "limiter-pages.bin").absolutePath, offset.toLong() * 1024 * 1024)
                    android.util.Log.i("LimiterExp", "sample pid=${Process.myPid()} allocated_mb=${offset + 4} ok=$ok")
                    if (!ok) break
                    Thread.sleep(250)
                }
            }
            return START_NOT_STICKY
        }
        val mb = intent?.getIntExtra("alloc_mb", 0) ?: 0
        if (mb > 0) {
            thread {
                android.util.Log.i("LimiterExp", "heavy allocating ${mb}MB pid=${Process.myPid()}")
                allocator.allocate(mb)
                val rssKb = readRssKb()
                android.util.Log.i("LimiterExp", "heavy rss_kb=$rssKb")
            }
        }
        return START_NOT_STICKY
    }
}
