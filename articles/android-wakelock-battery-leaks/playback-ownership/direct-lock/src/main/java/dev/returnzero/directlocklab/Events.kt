package dev.returnzero.directlocklab

import android.content.Context
import android.os.Process
import android.os.SystemClock
import android.os.Trace
import android.util.Log
import org.json.JSONObject
import java.io.File

object Events {
    data class RunContext(val runId: String, val scenario: String)
    private var file: File? = null
    private var sequence = 0L
    var runId = "manual"
        private set
    var scenario = "direct-untimed"
        private set

    @Synchronized fun begin(context: Context, id: String, mode: String) {
        file = File(context.filesDir, "events.jsonl")
        if (file!!.length() > 8_000_000) file!!.renameTo(File(context.filesDir, "events.previous.jsonl"))
        runId = id
        scenario = mode
        emit("run_start")
    }

    @Synchronized fun capture(): RunContext = RunContext(runId, scenario)

    @Synchronized fun emit(event: String, vararg fields: Pair<String, Any?>) = emitFor(capture(), event, *fields)

    @Synchronized fun emitFor(run: RunContext, event: String, vararg fields: Pair<String, Any?>) {
        val record = JSONObject()
            .put("run_id", run.runId).put("scenario", run.scenario).put("seq", ++sequence)
            .put("elapsed_ns", SystemClock.elapsedRealtimeNanos())
            .put("uptime_ms", SystemClock.uptimeMillis()).put("wall_ms", System.currentTimeMillis())
            .put("pid", Process.myPid()).put("uid", Process.myUid())
            .put("thread", Thread.currentThread().name).put("event", event)
        for ((key, value) in fields) record.put(key, value ?: JSONObject.NULL)
        try {
            Trace.beginSection("DL:$sequence:$event".take(127))
            file?.appendText(record.toString() + "\n")
            Log.i("DirectLockLab", record.toString())
        } finally { Trace.endSection() }
    }
}
