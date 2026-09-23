package dev.returnzero.directlocklab

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

object ActiveRun {
    var session: LockSession? = null
    fun stop(reason: String) { session?.stop(reason); session = null }
}

class MainActivity : Activity() {
    private var owned: LockSession? = null
    private var run: Events.RunContext? = null
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 80, 32, 48)
        }
        layout.addView(TextView(this).apply { text = "Direct partial wake lock lab"; textSize = 25f })
        layout.addView(TextView(this).apply {
            text = "Untimed acquisition is intentional misuse. No media or foreground service. Home/screen-off retains the experiment; Stop or activity destruction cleans up. Five-minute Handler deadline uses uptime and can be delayed by suspend or process freezing. isHeld is not proof of suspend blocking."
            textSize = 16f
        })
        status = TextView(this).apply { text = "Ready"; textSize = 18f }
        layout.addView(status)
        fun button(label: String, action: () -> Unit) {
            layout.addView(Button(this).apply { text = label; setOnClickListener { action() } })
        }
        button("Untimed acquire() — intentional misuse") { startRun("direct-untimed") }
        button("Timed acquire(60 seconds)") { startRun("direct-timed") }
        button("Stop") { ActiveRun.stop("explicit_stop"); status.text = "Stopped" }
        setContentView(ScrollView(this).apply { addView(layout) })
        handle(intent)
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); handle(intent) }

    private fun handle(intent: Intent) {
        when (intent.getStringExtra("command")) {
            "start" -> startRun(intent.getStringExtra("scenario") ?: "direct-untimed", intent.getStringExtra("run_id"))
            "stop" -> { ActiveRun.stop("explicit_stop"); status.text = "Stopped" }
        }
    }

    @SuppressLint("WakelockTimeout") // Untimed acquisition is the explicit experiment, bounded by owner cleanup and Handler deadline.
    private fun startRun(mode: String, id: String? = null) {
        if (mode !in setOf("direct-untimed", "direct-timed")) {
            status.text = "Unknown scenario: $mode"
            return
        }
        ActiveRun.stop("scenario_switch")
        Events.begin(this, id ?: "manual-${SystemClock.elapsedRealtime()}", mode)
        val context = Events.capture()
        run = context
        val handler = Handler(Looper.getMainLooper())
        val wakeLock = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "DirectLockLab:$mode")
        wakeLock.setReferenceCounted(false)
        val session = LockSession(
            object : LockSession.Lock {
                override val held get() = wakeLock.isHeld
                override fun acquire(timeoutMs: Long?) {
                    if (timeoutMs == null) wakeLock.acquire() else wakeLock.acquire(timeoutMs)
                }
                override fun release() = wakeLock.release()
            },
            schedule = { delay, task -> handler.postDelayed({ task() }, delay); Unit },
            cancel = { handler.removeCallbacksAndMessages(null) },
            event = { name, fields ->
                Events.emitFor(context, name, *fields.toList().toTypedArray())
                if (name == "run_stop" && run == context) status.text = "Stopped: ${fields["reason"]}"
            },
        )
        owned = session
        ActiveRun.session = session
        session.start(mode)
        status.text = "Running $mode\nRun ${context.runId}"
    }

    override fun onStop() {
        run?.let { Events.emitFor(it, "activity_stopped", "experiment_retained" to (owned?.active == true)) }
        super.onStop()
    }

    override fun onDestroy() {
        owned?.stop("lifecycle_destroy")
        if (ActiveRun.session === owned) ActiveRun.session = null
        run?.let { Events.emitFor(it, "activity_destroyed") }
        super.onDestroy()
    }
}
