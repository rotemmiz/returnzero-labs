package dev.returnzero.directlocklab

import org.junit.Assert.*
import org.junit.Test

class LockSessionTest {
    private class FakeLock : LockSession.Lock {
        override var held = false
        var timeout: Long? = -1
        var releases = 0
        override fun acquire(timeoutMs: Long?) { timeout = timeoutMs; held = true }
        override fun release() { releases++; held = false }
    }
    private class Fixture {
        val lock = FakeLock()
        val tasks = mutableMapOf<Long, () -> Unit>()
        val events = mutableListOf<Pair<String, Map<String, Any?>>>()
        val session = LockSession(lock, { delay, task -> tasks[delay] = task }, { tasks.clear() }, { name, fields -> events.add(name to fields) })
    }
    @Test fun untimedUsesNoTimeoutAndDeadlineReleases() {
        val f = Fixture()
        f.session.start("direct-untimed")
        assertNull(f.lock.timeout)
        f.tasks.getValue(300_000).invoke()
        assertFalse(f.lock.held)
        assertEquals("deadline_cleanup", f.events.last().second["reason"])
        assertTrue(f.tasks.isEmpty())
    }
    @Test fun timedUsesFrameworkTimeoutAndOnlyObservesExpiry() {
        val f = Fixture()
        f.session.start("direct-timed")
        assertEquals(60_000L, f.lock.timeout)
        f.lock.held = false // Simulate framework timeout, independently of the Handler observation.
        f.tasks.getValue(60_250).invoke()
        assertEquals(0, f.lock.releases)
        assertEquals("timeout_observed", f.events.last().second["reason"])
    }
    @Test fun heldAtObservationDoesNotInventTimeoutRelease() {
        val f = Fixture()
        f.session.start("direct-timed")
        f.tasks.getValue(60_250).invoke()
        assertTrue(f.session.active)
        assertEquals("wake_lock_timeout_observed", f.events.last().first)
        assertEquals(true, f.events.last().second["is_held"])
        f.session.stop("explicit_stop")
        assertEquals(1, f.lock.releases)
    }
    @Test fun cleanupIsIdempotentAndOldCallbackCannotRestart() {
        val f = Fixture()
        f.session.start("direct-timed")
        val stale = f.tasks.getValue(60_250)
        f.session.stop("lifecycle_destroy")
        val count = f.events.size
        stale()
        f.session.stop("explicit_stop")
        assertEquals(count, f.events.size)
        assertEquals(1, f.lock.releases)
    }
    @Test(expected = IllegalArgumentException::class)
    fun rejectsPlaybackScenarios() { Fixture().session.start("retained") }
}
