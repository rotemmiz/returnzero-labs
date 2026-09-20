package dev.returnzero.playbacklab

import android.content.Context
import android.net.Uri
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.analytics.AnalyticsListener
import java.util.IdentityHashMap

object Players {
    private var nextId = 0
    private val ids = IdentityHashMap<ExoPlayer, String>()
    private val runs = IdentityHashMap<ExoPlayer, Events.RunContext>()
    fun id(player: ExoPlayer): String = ids[player] ?: "released"

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    fun create(context: Context, owner: String, run: Events.RunContext = Events.capture(), terminalError: (ExoPlayer) -> Unit): ExoPlayer {
        val player = ExoPlayer.Builder(context.applicationContext).build()
        val id = "p${++nextId}"
        runs[player] = run
        ids[player] = id
        Events.emitFor(run, "player_created", "player_id" to id, "owner_id" to owner)
        player.setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MOVIE).build(), true)
        player.repeatMode = Player.REPEAT_MODE_ONE
        player.volume = 0.3f
        player.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) { Events.emitFor(run, "is_playing", "player_id" to id, "is_playing" to isPlaying) }
            override fun onPlaybackStateChanged(state: Int) { Events.emitFor(run, "playback_state", "player_id" to id, "state" to state) }
            override fun onPlayWhenReadyChanged(ready: Boolean, reason: Int) { Events.emitFor(run, "play_when_ready", "player_id" to id, "ready" to ready, "reason" to reason) }
            override fun onPlaybackSuppressionReasonChanged(reason: Int) { Events.emitFor(run, "suppression", "player_id" to id, "reason" to reason) }
            override fun onAudioSessionIdChanged(audioSessionId: Int) { Events.emitFor(run, "audio_session", "player_id" to id, "audio_session_id" to audioSessionId) }
            override fun onPlayerError(error: PlaybackException) { Events.emitFor(run, "player_error", "player_id" to id, "error_code" to error.errorCode); terminalError(player) }
        })
        player.addAnalyticsListener(object : AnalyticsListener {
            override fun onAudioDecoderInitialized(time: AnalyticsListener.EventTime, decoderName: String, initializedTimestampMs: Long, initializationDurationMs: Long) {
                Events.emitFor(run, "audio_decoder_initialized", "player_id" to id, "decoder" to decoderName)
            }
            override fun onAudioDecoderReleased(time: AnalyticsListener.EventTime, decoderName: String) {
                Events.emitFor(run, "audio_decoder_released", "player_id" to id, "decoder" to decoderName)
            }
        })
        return player
    }

    fun media(context: Context): MediaItem = MediaItem.Builder()
        .setUri(Uri.parse("android.resource://${context.packageName}/${R.raw.sample}"))
        .setMediaMetadata(MediaMetadata.Builder().setTitle("Playback ownership test").setArtist("Local generated test clip").build()).build()

    fun release(player: ExoPlayer) {
        val id = ids.remove(player) ?: return
        val run = runs.remove(player) ?: Events.capture()
        Events.emitFor(run, "release_start", "player_id" to id)
        player.release()
        Events.emitFor(run, "release_end", "player_id" to id)
    }
}
