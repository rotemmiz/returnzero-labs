package com.returnzero.limiter

class Allocator {
    fun allocate(mb: Int) {
        nativeAllocate(mb)
    }

    fun free() {
        nativeFree()
    }

    fun rssKb(): Long = nativeRssKb()

    private external fun nativeAllocate(mb: Int)
    private external fun nativeFree()
    private external fun nativeRssKb(): Long

    companion object {
        init {
            System.loadLibrary("allocator")
        }
    }
}