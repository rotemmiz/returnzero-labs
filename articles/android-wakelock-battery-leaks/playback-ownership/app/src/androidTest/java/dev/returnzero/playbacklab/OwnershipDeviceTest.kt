package dev.returnzero.playbacklab

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
class OwnershipDeviceTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private fun events(run: String): List<JSONObject> = File(context.filesDir, "events.jsonl").let { file ->
        if (!file.exists()) emptyList() else file.readLines().mapNotNull { runCatching { JSONObject(it) }.getOrNull() }.filter { it.optString("run_id") == run }
    }
    private fun awaitEvent(run: String, name: String) {
        val end = SystemClock.uptimeMillis() + 8_000
        while (SystemClock.uptimeMillis() < end) {
            if (events(run).any { it.optString("event") == name }) return
            SystemClock.sleep(50)
        }
        fail("Missing $name in ${events(run)}")
    }
    private fun launch(mode: String, pooled: Boolean = false): Pair<String, ActivityScenario<MainActivity>> {
        val run = "test-$mode-${SystemClock.elapsedRealtimeNanos()}"
        val intent = Intent(context, MainActivity::class.java).putExtra("command", "start")
            .putExtra("scenario", mode).putExtra("run_id", run).putExtra("pool", pooled)
        return run to ActivityScenario.launch(intent)
    }
    private fun releasedIds(run: String) = events(run).filter { it.optString("event") == "release_end" }.map { it.getString("player_id") }
    private fun createdIds(run: String) = events(run).filter { it.optString("event") == "player_created" }.map { it.getString("player_id") }

    @Test fun foregroundExitReleasesEveryCreatedPlayer() {
        val (run, screen) = launch("foreground")
        screen.use {
            awaitEvent(run, "player_created")
            screen.moveToState(Lifecycle.State.CREATED)
            awaitEvent(run, "release_end")
            assertEquals(createdIds(run), releasedIds(run))
        }
        assertEquals(releasedIds(run).size, releasedIds(run).distinct().size)
    }

    @Test fun pausedRetentionKeepsPlayerUntilOwnerDestroyed() {
        val (run, screen) = launch("paused")
        screen.use {
            awaitEvent(run, "player_created")
            screen.moveToState(Lifecycle.State.CREATED)
            awaitEvent(run, "paused_retained")
            assertTrue(releasedIds(run).isEmpty())
        }
        awaitEvent(run, "release_end")
        assertEquals(createdIds(run), releasedIds(run))
    }

    @Test fun lateCallbackCannotRestartStoppedOwner() {
        val (run, screen) = launch("foreground")
        screen.use {
            screen.onActivity { InstrumentationRegistry.getInstrumentation().callActivityOnNewIntent(it, Intent(it.intent).putExtra("command", "late")) }
            screen.moveToState(Lifecycle.State.CREATED)
            awaitEvent(run, "callback_rejected")
            assertEquals(1, createdIds(run).size)
            assertEquals(createdIds(run), releasedIds(run))
        }
    }

    @Test fun poolEvictsThenClosesAllRemainingPlayers() {
        val (run, screen) = launch("foreground", true)
        screen.use {
            repeat(3) { screen.onActivity { InstrumentationRegistry.getInstrumentation().callActivityOnNewIntent(it, Intent(it.intent).putExtra("command", "next")) } }
            awaitEvent(run, "pool_evicted")
            screen.moveToState(Lifecycle.State.CREATED)
            assertEquals(createdIds(run).sorted(), releasedIds(run).sorted())
        }
        assertEquals(releasedIds(run).size, releasedIds(run).distinct().size)
    }

    @Test fun terminalMediaErrorClosesOwner() {
        val (run, screen) = launch("foreground")
        screen.use {
            screen.onActivity { InstrumentationRegistry.getInstrumentation().callActivityOnNewIntent(it, Intent(it.intent).putExtra("command", "error")) }
            awaitEvent(run, "player_error")
            awaitEvent(run, "release_end")
            assertEquals(createdIds(run), releasedIds(run))
        }
    }
    @Test fun lateEventsKeepTheirOriginalRunAfterScenarioSwitch() {
        val (oldRun, screen) = launch("background")
        val newRun = "test-switch-${SystemClock.elapsedRealtimeNanos()}"
        screen.use {
            awaitEvent(oldRun, "player_created")
            screen.onActivity {
                val previous = Events.capture()
                InstrumentationRegistry.getInstrumentation().callActivityOnNewIntent(it, Intent(it.intent).putExtra("command", "start").putExtra("scenario", "foreground").putExtra("run_id", newRun))
                Events.emitFor(previous, "old_callback_delivered")
            }
            awaitEvent(oldRun, "service_destroyed")
            assertTrue(events(oldRun).any { it.optString("event") == "old_callback_delivered" })
            assertFalse(events(newRun).any { it.optString("event") in setOf("service_destroyed", "old_callback_delivered") })
            assertTrue(releasedIds(newRun).isEmpty())
        }
        awaitEvent(newRun, "release_end")
    }

    @Test fun explicitDebugStopReleasesRetainedOwner() {
        val (run, screen) = launch("retained")
        screen.use {
            awaitEvent(run, "player_created")
            screen.moveToState(Lifecycle.State.CREATED)
            context.sendBroadcast(Intent("dev.returnzero.playbacklab.STOP").setClassName(context, "dev.returnzero.playbacklab.StopReceiver"))
            awaitEvent(run, "stop_command_received")
            awaitEvent(run, "run_stop")
            assertEquals(createdIds(run), releasedIds(run))
        }
    }

    @Test fun playbackApkDoesNotRequestDirectWakeLockPermission() {
        assertEquals(android.content.pm.PackageManager.PERMISSION_DENIED,
            context.checkSelfPermission(android.Manifest.permission.WAKE_LOCK))
    }

}
