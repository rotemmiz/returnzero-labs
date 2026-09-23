package dev.returnzero.playbacklab

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView

class MainActivity : Activity() {
    companion object {
        internal var current = java.lang.ref.WeakReference<MainActivity>(null)
    }
    private val handler = Handler(Looper.getMainLooper())
    private val gate = OwnershipGate()
    private lateinit var playerView: PlayerView
    private lateinit var status: TextView
    private var player: ExoPlayer? = null
    private var pool: PlayerPool<ExoPlayer>? = null
    private var scenario = "foreground"
    private var item = 0
    private var running = false
    private val deadline = Runnable { Events.emit("experiment_deadline"); stopAll() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        current = java.lang.ref.WeakReference(this)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 48)
            setBackgroundColor(Color.rgb(243, 246, 245))
        }
        fun text(value: String, size: Float) = TextView(this).apply {
            text = value; textSize = size; setTextColor(Color.rgb(22, 40, 37)); setPadding(0, 12, 0, 12)
            layout.addView(this)
        }
        text("Playback ownership lab", 26f)
        text("One local clip. Four ownership policies. Measure the result on this device.", 16f)
        playerView = PlayerView(this).apply { useController = false; keepScreenOn = false }
        layout.addView(playerView, LinearLayout.LayoutParams(-1, (200 * resources.displayMetrics.density).toInt()))
        status = text("Ready. Choose a scenario; Home or Hide feed triggers the transition.", 16f)
        fun button(label: String, action: () -> Unit) {
            layout.addView(Button(this).apply { text = label; isAllCaps = false; setOnClickListener { action() } })
        }
        button("A · Foreground-only cleanup") { startRun("foreground") }
        button("B · Deliberately retain playback") { startRun("retained") }
        button("C · Intentional background audio") { startRun("background") }
        button("D · Pause and retain player") { startRun("paused") }
        button("Pool · Start / switch item (2 slots)") { if (pool == null) startRun("foreground", pooled = true) else playNext() }
        button("Hide feed / leave item") { leavePlayback("hidden") }
        button("Queue late autoplay, then hide") { scheduleLate(); leavePlayback("late_callback_test") }
        button("Trigger terminal playback error") { player?.setMediaItem(MediaItem.fromUri("file:///missing-playback-lab-media.mp4")); player?.prepare() }
        button("Stop all") { stopAll() }
        text("B is deliberate misuse, not a reproduction of X. Runs stop after five minutes of handler time; suspend can delay that deadline. No direct wake lock is acquired. The clip has a quiet tone.", 13f)
        setContentView(ScrollView(this).apply {
            addView(layout)
            setOnApplyWindowInsetsListener { _, insets ->
                layout.setPadding(32, insets.systemWindowInsetTop + 32, 32, insets.systemWindowInsetBottom + 32)
                insets
            }
        })
        handle(intent)
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); handle(intent) }

    private fun handle(intent: Intent) {
        when (intent.getStringExtra("command")) {
            "start" -> startRun(intent.getStringExtra("scenario") ?: "foreground", intent.getStringExtra("run_id"), intent.getBooleanExtra("pool", false))
            "stop" -> stopAll()
            "leave" -> leavePlayback("command")
            "next" -> playNext()
            "late" -> scheduleLate()
            "error" -> { player?.setMediaItem(MediaItem.fromUri("file:///missing-playback-lab-media.mp4")); player?.prepare() }
        }
    }

    private fun startRun(mode: String, id: String? = null, pooled: Boolean = false) {
        stopAll()
        scenario = mode.takeIf { it in setOf("foreground", "retained", "background", "paused") } ?: "foreground"
        Events.begin(this, id ?: "manual-${SystemClock.elapsedRealtime()}", scenario)
        running = true
        gate.enter()
        playerView.visibility = View.VISIBLE
        handler.postDelayed(deadline, 300_000)
        if (scenario == "background") {
            startService(Intent(this, PlaybackService::class.java).setAction("dev.returnzero.playbacklab.START").putExtra("run_id", Events.runId).putExtra("scenario", scenario))
            status.text = getString(R.string.status_service)
            return
        }
        if (pooled) {
            pool = PlayerPool(2,
                factory = { key -> Players.create(this, "pool:$key") { failed -> handler.post { if (player === failed) stopAll() } } },
                deactivate = { p -> Events.emit("pool_inactive", "player_id" to Players.id(p)); p.pause(); p.stop() },
                dispose = { p -> Events.emit("pool_evicted", "player_id" to Players.id(p)); Players.release(p) })
        }
        playNext()
        status.text = getString(R.string.status_playing, scenario)
    }

    private fun playNext() {
        if (!running || !gate.active || scenario == "background") return
        val token = gate.generation
        val key = "item-${item++ % 3}"
        if (pool == null) player?.let(Players::release)
        val next = pool?.checkout(key) ?: Players.create(this, "screen") { failed -> handler.post { if (player === failed) stopAll() } }
        player = next
        playerView.player = next
        Events.emit("attach", "player_id" to Players.id(next), "item_id" to key, "generation" to token)
        next.setMediaItem(Players.media(this))
        Events.emit("prepare", "player_id" to Players.id(next))
        next.prepare()
        next.play()
    }

    private fun scheduleLate() {
        val token = gate.generation
        Events.emit("callback_scheduled", "generation" to token)
        handler.postDelayed({
            if (gate.accepts(token)) { Events.emit("callback_accepted", "generation" to token); playNext() }
            else Events.emit("callback_rejected", "generation" to token)
        }, 1_000)
    }

    private fun leavePlayback(reason: String) {
        gate.leave()
        if (!running) return
        Events.emit("leave", "reason" to reason, "generation" to gate.generation)
        playerView.player = null
        playerView.visibility = View.GONE
        Events.emit("detach")
        when (scenario) {
            "foreground" -> releaseLocal()
            "paused" -> { player?.pause(); Events.emit("paused_retained", "player_id" to player?.let(Players::id)) }
            "retained" -> Events.emit("deliberately_retained", "player_id" to player?.let(Players::id))
            "background" -> Events.emit("service_owns_playback")
        }
        status.text = getString(R.string.status_left, scenario, reason)
    }

    private fun releaseLocal() {
        playerView.player = null
        if (pool != null) pool?.close() else player?.let(Players::release)
        pool = null
        player = null
    }

    internal fun stopAll() {
        gate.leave()
        handler.removeCallbacksAndMessages(null)
        if (::playerView.isInitialized) releaseLocal()
        stopService(Intent(this, PlaybackService::class.java))
        if (running) Events.emit("run_stop")
        running = false
        if (::status.isInitialized) status.text = getString(R.string.status_stopped)
    }

    override fun onStop() { leavePlayback("onStop"); super.onStop() }
    override fun onDestroy() {
        if (current.get() === this) current.clear()
        gate.leave()
        handler.removeCallbacksAndMessages(null)
        releaseLocal()
        Events.emit("activity_destroyed")
        super.onDestroy()
    }
}
