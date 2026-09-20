# Validation record — 2026-09-20

## Completed

- Debug app and device-test APK build with JDK 17.
- Nine Kotlin ownership/pool unit tests pass.
- Seven Python analyzer tests pass.
- Android lint passes: zero errors; four dependency-update notices remain for deliberately pinned build/test versions.
- Debug app installed over Wi-Fi ADB on a Pixel 9 Pro XL running Android 17, build CP2A.260805.005.
- Review corrected stale-run event attribution and stale-player error handling.

## Device tests: six passed

The complete corrected connected suite passed on the Pixel: six tests, zero failures, errors or skipped tests (182.888 seconds). It verifies foreground release, pool eviction/closure, stale callback rejection, paused retention/destruction, terminal media-error cleanup, and run-context isolation. See `device-tests.json` for test names, timing and the tested APK hash.

The earlier test-intent mismatch was fixed without changing app behavior or assertions. These are app ownership checks, not a reproduced X bug, proof of released kernel blockers, or a battery measurement.

## Foreground pilot: cleanup observed

The final trace-enabled pilot completed on the same Pixel. One player was created and released; release finished **73.9 ms after onStop**. AudioFlinger showed its track active before leaving, then recorded track removal and marked the sample idle after leaving. The quiet screen-off observation lasted 15.006 seconds. See `foreground-pilot.json` for the reviewed numeric summary and tested APK hash.

Perfetto v58.2 parsed the 5,530,426-byte trace. All 16 app events match trace markers on clock ID 6 (BOOTTIME); markers follow their event timestamps by approximately 0.03–1.63 ms. No nonzero parser-error or data-loss statistics were reported. There are two ftrace setup notices; wakeup-source event support is not established. Suspend/resume events exist, but their presence is not a measurement of successful suspend residency.

The sample's cumulative partial AudioMix counter read 17 ms at baseline/play-end and 27 ms at observation-end/cleanup-end. This accounting counter is neither playback duration nor proof of prevented suspend. No causal battery conclusion follows from this single trial.

Earlier capture attempts exposed unstable Wi-Fi ADB, Gradle uninstalling the test app, and a Perfetto output-path permission error. The APK was reinstalled and the harness now writes traces under `/data/misc/perfetto-traces`; the final run used that correction. Failed attempts are not included as successful measurements.

## Measurement gates still open

Run repeated four-scenario trials and a matched screen-off idle control before comparing suspend behavior. Resolve the two ftrace setup notices and verify wakeup-source coverage. No X reproduction or battery-life recovery has been established. No battery, lock-screen, or other apps' settings were changed.

Raw snapshots and traces remain private, outside the repository. Only reviewed sample-specific summaries are included here.
