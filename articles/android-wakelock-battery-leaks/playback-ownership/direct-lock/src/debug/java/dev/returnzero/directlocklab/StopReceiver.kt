package dev.returnzero.directlocklab

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Debug-only harness control; manifest component supports explicit delivery behind keyguard. */
class StopReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == "dev.returnzero.directlocklab.STOP") ActiveRun.stop("explicit_stop")
    }
}
