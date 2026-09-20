package dev.returnzero.playbacklab

class OwnershipGate {
    var generation: Long = 0
        private set
    var active: Boolean = false
        private set

    fun enter(): Long {
        generation += 1
        active = true
        return generation
    }

    fun leave() {
        generation += 1
        active = false
    }

    fun accepts(token: Long): Boolean = active && token == generation
}
