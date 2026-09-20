package dev.returnzero.playbacklab

import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Test

class PlayerPoolTest {
    private class Player(val id: String) {
        var deactivations = 0
        var disposals = 0
    }

    private fun pool(capacity: Int = 2, factory: (String) -> Player = ::Player) =
        PlayerPool(capacity, factory, { it.deactivations++ }, { it.disposals++ })

    @Test fun cachedPlayersAreReusedAndLeastRecentlyUsedInactivePlayerIsEvicted() {
        val pool = pool()
        val first = pool.checkout("first")
        val second = pool.checkout("second")
        assertSame(first, pool.checkout("first"))
        val third = pool.checkout("third")
        assertEquals(2, pool.size)
        assertEquals(1, second.disposals)
        assertEquals(0, first.disposals)
        assertEquals(0, third.disposals)
        pool.close()
        assertEquals(1, first.disposals)
        assertEquals(1, second.disposals)
        assertEquals(1, third.disposals)
    }

    @Test fun switchingDeactivatesThePreviousPlayerButRepeatedCheckoutDoesNot() {
        val pool = pool()
        val first = pool.checkout("first")
        assertSame(first, pool.checkout("first"))
        assertEquals(0, first.deactivations)
        val second = pool.checkout("second")
        assertEquals(1, first.deactivations)
        pool.deactivateActive()
        pool.deactivateActive()
        assertEquals(1, second.deactivations)
        pool.close()
    }

    @Test fun closeDisposesEveryPlayerExactlyOnceAndRejectsFurtherCheckout() {
        val pool = pool()
        val first = pool.checkout("first")
        val second = pool.checkout("second")
        pool.close()
        pool.close()
        pool.deactivateActive()
        assertEquals(0, pool.size)
        assertEquals(1, first.disposals)
        assertEquals(1, second.disposals)
        assertEquals(1, second.deactivations)
        assertThrows(IllegalStateException::class.java) { pool.checkout("third") }
    }

    @Test fun failedCreationPreservesOwnershipForCleanupAndRetry() {
        val pool = pool(factory = { id ->
            if (id == "broken") error("Creation failed")
            Player(id)
        })
        val first = pool.checkout("first")
        val second = pool.checkout("second")
        assertThrows(IllegalStateException::class.java) { pool.checkout("broken") }
        assertEquals(2, pool.size)
        assertEquals(1, second.deactivations)
        assertSame(first, pool.checkout("first"))
        pool.close()
        assertEquals(1, first.disposals)
        assertEquals(1, second.disposals)
    }

    @Test fun capacityOneDisposesPreviousPlayerOnSwitch() {
        val pool = pool(capacity = 1)
        val first = pool.checkout("first")
        val second = pool.checkout("second")
        assertEquals(1, pool.size)
        assertEquals(1, first.deactivations)
        assertEquals(1, first.disposals)
        pool.close()
        assertEquals(1, first.disposals)
        assertEquals(1, second.disposals)
    }

    @Test fun invalidCapacityIsRejected() {
        assertThrows(IllegalArgumentException::class.java) { pool(capacity = 0) }
        assertThrows(IllegalArgumentException::class.java) { pool(capacity = -1) }
    }

    @Test fun closeStillDisposesAllPlayersIfDeactivationOrDisposalThrows() {
        val disposed = mutableListOf<String>()
        val pool = PlayerPool(
            factory = ::Player,
            deactivate = { player -> if (player.id == "second") error("Deactivate failed") },
            dispose = { player ->
                disposed.add(player.id)
                if (player.id == "first") error("Dispose failed")
            },
        )
        pool.checkout("first")
        pool.checkout("second")
        val error = assertThrows(IllegalStateException::class.java) { pool.close() }
        assertEquals("Deactivate failed", error.message)
        assertEquals(1, error.suppressed.size)
        assertEquals(listOf("first", "second"), disposed)
        pool.close()
        assertEquals(2, disposed.size)
        assertEquals(0, pool.size)
    }
}
