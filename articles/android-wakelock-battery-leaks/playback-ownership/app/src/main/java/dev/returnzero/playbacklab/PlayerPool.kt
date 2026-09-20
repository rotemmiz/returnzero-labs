package dev.returnzero.playbacklab

/** Confined to the player's application thread. Each factory call must return a new player. */
class PlayerPool<T : Any>(
    private val capacity: Int = 2,
    private val factory: (String) -> T,
    private val deactivate: (T) -> Unit,
    private val dispose: (T) -> Unit,
) : AutoCloseable {
    init {
        require(capacity > 0) { "Player pool capacity must be positive" }
    }

    private val players = LinkedHashMap<String, T>()
    private var activeId: String? = null
    private var closed = false

    val size: Int get() = players.size

    fun checkout(itemId: String): T {
        check(!closed) { "Player pool is closed" }
        if (activeId == itemId) return players.getValue(itemId)

        deactivateActive()
        val player = players[itemId] ?: factory(itemId)
        players.remove(itemId)
        players[itemId] = player
        activeId = itemId

        if (players.size > capacity) {
            val oldestId = players.keys.first()
            val oldest = players.remove(oldestId)!!
            dispose(oldest)
        }
        return player
    }

    fun deactivateActive() {
        val id = activeId ?: return
        deactivate(players.getValue(id))
        activeId = null
    }

    override fun close() {
        if (closed) return
        closed = true
        var failure: Throwable? = null
        try {
            deactivateActive()
        } catch (error: Throwable) {
            failure = error
        }
        val owned = players.values.toList()
        players.clear()
        activeId = null
        for (player in owned) {
            try {
                dispose(player)
            } catch (error: Throwable) {
                val previous = failure
                if (previous == null) failure = error
                else if (previous !== error) previous.addSuppressed(error)
            }
        }
        failure?.let { throw it }
    }
}
