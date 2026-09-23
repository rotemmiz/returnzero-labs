package dev.returnzero.directlocklab

/** A single run owns its lock and immutable event sink. All calls use the main thread. */
class LockSession(
    private val lock: Lock,
    private val schedule: (Long, () -> Unit) -> Unit,
    private val cancel: () -> Unit,
    private val event: (String, Map<String, Any?>) -> Unit,
) {
    interface Lock {
        val held: Boolean
        fun acquire(timeoutMs: Long?)
        fun release()
    }
    var active = false
        private set

    fun start(scenario: String) {
        require(scenario in setOf("direct-untimed", "direct-timed"))
        check(!active)
        active = true
        val timeout = if (scenario == "direct-timed") 60_000L else null
        lock.acquire(timeout)
        event("wake_lock_acquired", mapOf("timeout_ms" to timeout, "is_held" to lock.held,
            "tag" to "DirectLockLab:$scenario", "intentional_misuse" to (timeout == null)))
        schedule(300_000) {
            if (active) {
                event("experiment_deadline", mapOf("clock" to "uptime"))
                stop("deadline_cleanup")
            }
        }
        if (timeout != null) schedule(timeout + 250) {
            if (active) {
                // This observes framework bookkeeping; it does not prove effective suspend blocking.
                event("wake_lock_timeout_observed", mapOf("is_held" to lock.held))
                if (!lock.held) stop("timeout_observed")
            }
        }
    }

    fun stop(reason: String) {
        if (!active) return
        active = false
        cancel()
        val heldBefore = lock.held
        if (heldBefore) lock.release()
        event("wake_lock_release", mapOf("reason" to reason, "was_held" to heldBefore, "is_held" to lock.held))
        event("run_stop", mapOf("reason" to reason))
    }
}
