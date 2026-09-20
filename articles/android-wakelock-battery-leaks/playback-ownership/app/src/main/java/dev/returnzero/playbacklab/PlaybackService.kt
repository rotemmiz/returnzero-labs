package dev.returnzero.playbacklab

import android.content.Intent
import android.os.Handler
import android.os.Looper
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService

class PlaybackService : MediaSessionService() {
    private var player: ExoPlayer? = null
    private var session: MediaSession? = null
    private var run = Events.capture()
    private val handler = Handler(Looper.getMainLooper())
    private val deadline = Runnable { Events.emitFor(run, "service_deadline"); stopSelf() }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        if (intent?.action == "dev.returnzero.playbacklab.START") {
            val requested = Events.RunContext(intent.getStringExtra("run_id") ?: "missing", intent.getStringExtra("scenario") ?: "background")
            if (requested != Events.capture()) {
                Events.emitFor(requested, "service_start_rejected")
                stopSelf(startId)
                return START_NOT_STICKY
            }
            closePlayback()
            run = requested
            Events.emitFor(run, "service_created")
            val created = Players.create(this, "service", run) { failed -> handler.post { if (player === failed) stopSelf() } }
            player = created
            session = MediaSession.Builder(this, created).build()
            created.setMediaItem(Players.media(this))
            created.prepare()
            Events.emitFor(run, "service_play")
            created.play()
            handler.postDelayed(deadline, 300_000)
        }
        return START_NOT_STICKY
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    private fun closePlayback() {
        handler.removeCallbacksAndMessages(null)
        player?.let(Players::release)
        player = null
        session?.release()
        session = null
    }

    override fun onDestroy() {
        closePlayback()
        Events.emitFor(run, "service_destroyed")
        super.onDestroy()
    }
}
