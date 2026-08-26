package com.returnzero.limiter

import android.app.Service
import android.content.Intent
import android.os.IBinder
import android.os.Process
import kotlin.concurrent.thread

class HeavyService : Service() {

    private val allocator = Allocator()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val mb = intent?.getIntExtra("alloc_mb", 0) ?: 0
        if (mb > 0) {
            thread {
                android.util.Log.i("LimiterExp", "heavy allocating ${mb}MB pid=${Process.myPid()}")
                allocator.allocate(mb)
                val rssKb = readRssKb()
                android.util.Log.i("LimiterExp", "heavy rss_kb=$rssKb")
            }
        }
        return START_STICKY
    }
}