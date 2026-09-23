package dev.returnzero.directlocklab

import android.content.Context
import android.content.Intent
import android.os.SystemClock
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class DirectLockDeviceTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private fun events(run: String) = File(context.filesDir, "events.jsonl").readLines()
        .map { JSONObject(it) }.filter { it.optString("run_id") == run }
    private fun launch(mode: String): Pair<String, ActivityScenario<MainActivity>> {
        val run = "device-$mode-${SystemClock.elapsedRealtimeNanos()}"
        return run to ActivityScenario.launch(Intent(context, MainActivity::class.java)
            .putExtra("command", "start").putExtra("scenario", mode).putExtra("run_id", run))
    }
    @Test fun backgroundRetentionThenDestroyCleansUp() {
        val (run, screen) = launch("direct-untimed")
        screen.use {
            screen.moveToState(Lifecycle.State.CREATED)
            assertTrue(events(run).any { it.optString("event") == "activity_stopped" && it.optBoolean("experiment_retained") })
            assertFalse(events(run).any { it.optString("event") == "wake_lock_release" })
        }
        assertTrue(events(run).any { it.optString("event") == "wake_lock_release" && it.optString("reason") == "lifecycle_destroy" })
    }
    @Test fun explicitDebugStopWorksWhileActivityStopped() {
        val (run, screen) = launch("direct-untimed")
        screen.use {
            screen.moveToState(Lifecycle.State.CREATED)
            context.sendBroadcast(Intent("dev.returnzero.directlocklab.STOP")
                .setClassName(context.packageName, "dev.returnzero.directlocklab.StopReceiver"))
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
            assertTrue(events(run).any { it.optString("event") == "run_stop" && it.optString("reason") == "explicit_stop" })
        }
    }
    @Test fun nativeTimedAcquisitionExpires() {
        val (run, screen) = launch("direct-timed")
        screen.use {
            val deadline = SystemClock.uptimeMillis() + 65_000
            while (SystemClock.uptimeMillis() < deadline && events(run).none { it.optString("event") == "wake_lock_timeout_observed" }) SystemClock.sleep(100)
            val observation = events(run).single { it.optString("event") == "wake_lock_timeout_observed" }
            assertFalse(observation.getBoolean("is_held"))
            assertTrue(events(run).any { it.optString("event") == "run_stop" && it.optString("reason") == "timeout_observed" })
        }
    }
    @Test fun switchingRunsKeepsOldCleanupAttribution() {
        val (oldRun, screen) = launch("direct-untimed")
        val nextRun = "switch-${SystemClock.elapsedRealtimeNanos()}"
        screen.use {
            screen.onActivity {
                InstrumentationRegistry.getInstrumentation().callActivityOnNewIntent(it,
                    Intent(it.intent).putExtra("scenario", "direct-timed").putExtra("run_id", nextRun))
            }
            assertTrue(events(oldRun).any { it.optString("reason") == "scenario_switch" })
            assertFalse(events(nextRun).any { it.optString("event") == "wake_lock_release" })
            assertTrue(events(nextRun).all { it.optString("scenario") == "direct-timed" })
        }
    }
}
