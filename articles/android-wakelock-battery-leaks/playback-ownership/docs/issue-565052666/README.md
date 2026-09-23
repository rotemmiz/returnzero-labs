# Google issue 565052666 reproduction package

This package investigates [issue 565052666](https://issuetracker.google.com/issues/565052666) with two independent apps. A Media3 app examines AudioMix attribution and playback ownership. A separate app deliberately acquires a partial wake lock, with either no acquisition timeout or a 60-second timeout. These experiments do not reproduce proprietary application internals.

## Build and install

From the playback-ownership directory, use JDK 17 and the existing pinned Android toolchain:

```sh
./gradlew :app:assembleDebug :direct-lock:assembleDebug \
  :app:testDebugUnitTest :direct-lock:testDebugUnitTest \
  :app:lintDebug :direct-lock:lintDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb install -r direct-lock/build/outputs/apk/debug/direct-lock-debug.apk
python3 -m unittest discover -s capture -p 'test_*.py'
python3 -m unittest discover -s analysis -p 'test_*.py'
./gradlew :app:connectedDebugAndroidTest :direct-lock:connectedDebugAndroidTest
```

Connected tests operate the demo apps. Reinstall both APKs afterward if Gradle removes them. Debug APKs alone expose explicit Stop receivers for use behind keyguard, restricted to callers with the system DUMP permission (including adb shell) or the app itself. Release builds do not expose those receivers and are not supported by the capture harness.

## Reproduction matrix

| Scenario | Mechanism and transition |
| --- | --- |
| idle | Both sample apps stopped; matched 180-second screen-off observation. |
| foreground | Play local video; Home releases the screen-owned player. |
| retained | Play local video; Home detaches its view but deliberately retains playback. |
| background | Play local video through the intentional MediaSessionService owner. |
| paused | Play local video; Home pauses and retains the player object. |
| direct-untimed | Acquire a direct partial wake lock without an acquisition timeout; Home retains it. |
| direct-timed | Acquire a direct partial wake lock with a 60-second timeout; Home retains the owner. |

The direct app has no media playback or foreground service. The playback app has no WAKE_LOCK permission or direct wake-lock acquisition. Each run has a five-minute uptime-based Handler safety deadline; device suspend or freezing can defer it. Explicit Stop, owner destruction, and harness force-stop provide separate cleanup paths. Force-stop is never counted as natural release.

## Capture protocol

Choose the serial from `adb devices -l`. Unlock the Pixel before every trial, including idle, disconnect charging, and keep audio route and volume fixed. Do not change battery optimization, Doze, app-ops, or system logging between trials. Close other intentional media yourself before starting a quiet comparison.

```sh
python3 capture/capture.py --serial SERIAL --scenario paused \
  --apk app/build/outputs/apk/debug/app-debug.apk \
  --source-commit COMMIT --output /PRIVATE/PATH/measurements \
  --play-seconds 30 --observe-seconds 180
```

The direct scenarios select `dev.returnzero.directlocklab` automatically and use the direct APK. An optional `--package` must match the scenario. `--apk` checks its SHA-256 against the installed package. `--source-commit` is a recorded build-provenance assertion, not independent proof; retain the build record and use a clean committed source revision.

For the complete matrix, the runner rotates the scenario order, waits for manual unlock between trials, and checkpoints each attempt. Rerun the identical command to resume after an interruption; failed attempts remain recorded.

```sh
python3 capture/matrix.py --serial SERIAL --source-commit COMMIT \
  --output /PRIVATE/PATH/matrix
```

First run a short pilot with `--baseline-seconds 3 --play-seconds 5 --observe-seconds 15 --cleanup-seconds 5`. Then run three repetitions of all seven scenarios, rotating the starting scenario each repetition. Keep all failed trials and their failure reasons. Only the separate idle scenario is a matched screen-off control; the per-trial screen-on baseline is not.

Each measurement has 30 seconds of active setup/playback and 180 seconds without ADB commands during screen-off observation. Boundary dumps are sequential, timestamp-bracketed, and perturb the device. Wi-Fi ADB and tracing are also experimental limitations. Capture records battery state, process state, power locks, audio route/track state, attribution, device build, APK hashes and app events. Check actual recorded timing, deadline events, trace capabilities, clock alignment and data loss before interpreting a run.

## Google evidence

Run demonstrations separately with `--screenrecord --bugreport` and a short observation window. The recording is capped at 180 seconds and is not a quiet measurement. Bugreport collection happens after observation and before explicit cleanup; it perturbs the device and may overlap the safety deadline. Inspect the recorded boundaries and events rather than assuming the original state survived collection.

Raw videos, bugreports, event logs, dumps and Perfetto traces stay outside git. Private `artifact-index.json` files identify artifacts by size and SHA-256. Review videos for notifications and other personal content before sharing. The repository contains source, reproduction instructions and reviewed sample-specific findings only. The Google response is a draft; nothing is submitted or shared through Drive by this workflow.

## Interpretation

- An allocated or paused player is not evidence of an active AudioMix lock.
- Deliberately continued playback is an explicit synthetic condition, not proof of the reported post-playback leak.
- Cumulative BatteryStats attribution is not the observed duration or proof of prevented suspend.
- Direct `isHeld()` reports app-side ownership; inspect system enabled/disabled state separately. Android can suppress wake locks under system power policy. See [Doze documentation](https://developer.android.com/training/monitoring-device-state/doze-standby).
- A three-minute observation cannot establish indefinite persistence or battery-life impact.
- Missing rows, unavailable trace events, failed starts, interrupted captures or unresolved attribution produce inconclusive results, not proof of absence.

After collection, run `python3 analysis/trace_report.py /PRIVATE/PATH/RUN --trace-processor /path/to/trace_processor` for clock, app-marker and loss checks. A trace report still requires manual interpretation.
