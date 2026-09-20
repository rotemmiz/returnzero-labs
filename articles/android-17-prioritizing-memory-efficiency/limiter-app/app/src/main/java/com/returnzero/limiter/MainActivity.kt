package com.returnzero.limiter

import android.content.Intent
import android.os.Bundle
import android.os.Process
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlin.concurrent.thread

class MainActivity : ComponentActivity() {

    private val allocator = Allocator()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        bindService(Intent(this, HeavyService::class.java), object : android.content.ServiceConnection {
            override fun onServiceConnected(name: android.content.ComponentName?, service: android.os.IBinder?) {}
            override fun onServiceDisconnected(name: android.content.ComponentName?) {}
        }, BIND_AUTO_CREATE)
        handleAllocIntent(intent)
        setContent {
            MaterialTheme {
                Surface {
                    Column(
                        modifier = Modifier.fillMaxSize().padding(24.dp),
                        verticalArrangement = Arrangement.Center,
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text("Main PID: ${Process.myPid()}")
                        Spacer(Modifier.height(16.dp))
                        Button(onClick = { allocateMain(200) }) {
                            Text("Alloc 200 MB in main")
                        }
                        Spacer(Modifier.height(8.dp))
                        Button(onClick = { allocateMain(600) }) {
                            Text("Alloc 600 MB in main (suicide)")
                        }
                        Spacer(Modifier.height(8.dp))
                        Button(onClick = { sendAllocToHeavy(600) }) {
                            Text("Alloc 600 MB in :heavy via Intent")
                        }
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleAllocIntent(intent)
    }

    private fun handleAllocIntent(intent: Intent?) {
        val mb = intent?.getIntExtra("alloc_mb", 0) ?: 0
        android.util.Log.i("LimiterExp", "main handleAllocIntent mb=$mb pid=${Process.myPid()}")
        if (mb > 0) {
            allocateMain(mb)
        }
    }

    private fun allocateMain(mb: Int) {
        thread {
            android.util.Log.i("LimiterExp", "main allocating ${mb}MB pid=${Process.myPid()}")
            allocator.allocate(mb)
            val rssKb = readRssKb()
            android.util.Log.i("LimiterExp", "main rss_kb=$rssKb")
        }
    }

    private fun sendAllocToHeavy(mb: Int) {
        val intent = Intent(this, HeavyService::class.java)
        intent.putExtra("alloc_mb", mb)
        startService(intent)
    }
}

fun readRssKb(): Long {
    return try {
        val lines = java.io.File("/proc/self/status").readLines()
        val rssLine = lines.first { it.startsWith("VmRSS:") }
        rssLine.split(Regex("\\s+"))[1].toLong()
    } catch (e: Exception) { -1L
    }
}
