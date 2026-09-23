package dev.returnzero.playbacklab

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class StopReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != "dev.returnzero.playbacklab.STOP") return
        Events.emit("stop_command_received")
        MainActivity.current.get()?.stopAll()
        context.stopService(Intent(context, PlaybackService::class.java))
    }
}
