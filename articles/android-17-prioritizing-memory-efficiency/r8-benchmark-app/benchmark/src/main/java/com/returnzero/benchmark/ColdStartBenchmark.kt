package com.returnzero.benchmark

import androidx.benchmark.macro.MacrobenchmarkScope
import androidx.benchmark.macro.StartupMode
import androidx.benchmark.macro.StartupTimingMetric
import androidx.benchmark.macro.junit4.MacrobenchmarkRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Cold-start benchmark using androidx.benchmark:macro-junit4.
 *
 * The framework handles: force-stop + killProcess, startup timing (measured
 * from the moment the process is forked, not from `am start` dispatch), warmup
 * iterations, statistical analysis (median + min/max), Perfetto trace capture,
 * and emits a structured report JSON to the device.
 *
 * 12 iterations with the framework's own warmup handling. The runner script
 * (run.ts) toggles the installed app APK between R8-on and R8-off variants
 * before invoking this instrumentation, and parses the report JSON.
 */
@RunWith(AndroidJUnit4::class)
class ColdStartBenchmark {

    @get:Rule
    val benchmarkRule = MacrobenchmarkRule()

    @Test
    fun coldStartup() = benchmarkRule.measureRepeated(
        packageName = "com.returnzero.benchmark",
        metrics = listOf(StartupTimingMetric()),
        iterations = 12,
        startupMode = StartupMode.COLD,
    ) {
        pressHome()
        startActivityAndWait()
    }
}