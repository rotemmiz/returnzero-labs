package dev.returnzero.playbacklab

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OwnershipGateTest {
    @Test fun leavingRejectsLateCallbacksEvenAfterReentry() {
        val gate = OwnershipGate()
        val oldToken = gate.enter()
        assertTrue(gate.accepts(oldToken))
        gate.leave()
        assertFalse(gate.active)
        assertFalse(gate.accepts(oldToken))
        val newToken = gate.enter()
        assertFalse(gate.accepts(oldToken))
        assertTrue(gate.accepts(newToken))
    }

    @Test fun everyEnterSupersedesEarlierWorkAndRepeatedLeaveStaysInactive() {
        val gate = OwnershipGate()
        assertFalse(gate.accepts(gate.generation))
        val first = gate.enter()
        val second = gate.enter()
        assertFalse(gate.accepts(first))
        assertTrue(gate.accepts(second))
        gate.leave()
        gate.leave()
        assertFalse(gate.accepts(gate.generation))
        assertFalse(gate.accepts(second))
    }
}
