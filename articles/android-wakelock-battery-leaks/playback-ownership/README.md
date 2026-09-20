# Playback ownership lab

A runnable Android / Media3 prevention example for the returnzero article “The insomniac Android: diagnosing wakelock battery leaks.”

This app compares **ownership policies**, not commercial app implementations. Deliberately continuing playback after detaching a view is a synthetic mistake. A paused player may release audio wakefulness while remaining allocated. Measure each case; neither case is a claimed reproduction of X.

## Build

Requirements: JDK 17, Android SDK platform 36 and its build tools, adb, Python 3 for capture tools. All Media3 modules are pinned to 1.11.1; AGP is 8.11.1, Kotlin 2.2.10, Gradle 8.13. Minimum Android API is 26; target is 36.

Set `ANDROID_HOME` to your SDK or put `sdk.dir=/absolute/sdk/path` in local.properties. Then:

```sh
./gradlew :app:assembleDebug :app:testDebugUnitTest
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Open **Playback ownership lab** on the phone. The clip contains a quiet tone; the app does not change system volume. There is no network-media dependency and no application wake lock permission or explicit wake lock acquisition.

## Scenarios

| Button | Owner and transition |
|---|---|
| A: foreground-only | Screen owns player. Home, screen stop, or Hide feed releases it. |
| B: deliberately retain playback | Screen view detaches but player intentionally continues, subject to Android policy. Stop all releases it. |
| C: intentional background audio | MediaSessionService owns player/session. Home leaves audio running; Stop all stops service. |
| D: paused retention | Leaving pauses and retains the player object. Stop all releases it. |
| Pool | Start the foreground scenario with two retained slots; repeated presses select one of three items and exercise eviction. Leaving closes the pool. |

All calls run on the player's application thread. Every run has a five-minute Handler deadline plus Stop all; suspend can defer that callback. Local owners also release on Activity destruction. The service releases on its own destruction and does not restart automatically after process death.

**Late callback test:** queue autoplay then hide the feed. The old generation must be rejected rather than recreating the player. **Terminal error test:** attempts a missing local media file and cleans up its owner. These are labelled controls in this sample, not hooks in the website or another app.

## Tests

```sh
./gradlew :app:testDebugUnitTest
python3 -m unittest discover -s analysis -p 'test_*.py'
./gradlew :app:connectedDebugAndroidTest
```

The connected tests require an unlocked device and change the sample's playback state. They cover foreground release, pause versus release, stale callback rejection, pool eviction, terminal error cleanup, and run-context isolation during scenario switching. Unit tests exercise generations, pool reuse/capacity, creation/disposal failures and idempotent cleanup. Python tests check event accounting and conservative attribution parsing.

A passed ownership test is not proof of a released kernel blocker. Device results are recorded separately in `results/README.md`.

## Capture one trial

Use the actual serial from `adb devices -l`. Unlock the phone, disconnect charging, and close other intentional audio playback yourself if a quiet comparison is needed. The harness does not alter other apps or reset battery statistics.

```sh
python3 capture/capture.py \
  --serial SERIAL \
  --scenario foreground \
  --output /tmp/playback-lab-captures
```

Defaults: 15 seconds screen-on baseline, 30 seconds playback, 180 seconds quiet screen-off observation, 15 seconds after explicit cleanup. The sample APK must already be installed. Gradle may uninstall it after connected tests; reinstall with `adb install -r app/build/outputs/apk/debug/app-debug.apk` before capture. Repeat for `retained`, `background`, and `paused`.

For a short harness pilot, use `--baseline-seconds 3 --play-seconds 5 --observe-seconds 15 --cleanup-seconds 5`. A pilot validates the collection path; it is not a battery-life experiment.

The capture saves sequential, timestamp-bracketed audio, power, process and BatteryStats snapshots; an on-device Perfetto trace when supported; and app JSONL events. It takes no full bugreport by default. Finally it force-stops only the sample as a safety cleanup, with that boundary recorded separately. A force-stop must never be reported as successful app cleanup.

A secure screen lock may prevent a clean UI-driven Stop at the end. Inspect whether `run_stop` and release events exist before the harness force-stop. Treat missing natural cleanup evidence as inconclusive. Unlock again before the next trial.

The initial baseline is screen-on and **cannot be used as a matched suspend baseline**. Use a separately controlled screen-off idle run before claiming any suspend difference. Likewise, do not infer power savings from a short trial.

Read [capture/README.md](capture/README.md) for privacy, capability probing, and interpretation limits. Raw captures stay outside this repository. The generated report filters to the sample UID but still requires review before publication.

## Events and clocks

`files/events.jsonl` contains per-run events with elapsed realtime nanoseconds, uptime milliseconds, wall-clock milliseconds, process/UID, player ID and sequence number. Trace markers use `PL:<sequence>:<event>`. Player and service callbacks retain an immutable run context so a late callback cannot be billed to the next run.

Record names include `player_created`, `prepare`, `is_playing`, `audio_session`, `audio_decoder_initialized`, `audio_decoder_released`, `leave`, `release_start`, `release_end`, `callback_rejected`, and service lifecycle events. Decoder callbacks indicate library state, not proof of platform track teardown. Verify clock alignment and lost-event statistics in Perfetto before drawing a timeline.

The read-only analyzer checks create/release balance and extracts cumulative sample-UID AudioMix entries. It intentionally leaves device cleanup inconclusive until audio, attribution, and suspend evidence are correlated. It does not turn an absent row or a release callback into a causal conclusion.

## Media provenance

`app/src/main/res/raw/sample.mp4` is an original 12-second synthetic FFmpeg test pattern and 440 Hz sine tone, dedicated to CC0 (see MEDIA-LICENSE.txt). It loops during playback. Generation command:

```sh
ffmpeg -f lavfi -i testsrc2=size=320x180:rate=24 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 -t 12 \
  -c:v libx264 -pix_fmt yuv420p -preset fast -crf 28 \
  -c:a aac -af volume=0.1 -b:a 64k -movflags +faststart sample.mp4
```

See `docs/build-info.json` for the bundled file's SHA-256. Re-encoding with another FFmpeg version may produce different bytes; retain the hash with each run.

## Scope

This directory is a standalone Gradle project. It does not add Android dependencies to the website build. Source is MIT licensed; generated test media is CC0. This project is maintained in the public `returnzero-labs` repository.
