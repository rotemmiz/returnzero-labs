# android17-memory-lab

Reproducible experiments that validate the claims in
[**Android 17's memory ceiling**](https://returnzero.dev/articles/android-17-memory-ceiling)
on returnzero.dev.

Android 17 introduces a per-process memory limiter backed by Linux cgroup v2
(`memory.high` + `memory.swap.max`). The article makes two claims that need
empirical backing:

1. **The limiter caps each process independently.** There is no aggregate
   per-UID budget on top of the per-process cgroups, so a multi-process app
   gets `N × cap` before the limiter bites.
2. **R8 shrinking cuts resident code memory by 80-87%.** APK size, code PSS,
   and DEX class/method counts all fall in lockstep on a realistic app.

This repo contains the apps, scripts, and raw audit artifacts to reproduce
both.

---

## Experiments

### 1. Multi-process limiter verification

**Question:** Does the Android 17 memory limiter cap per-process or per-UID?

**Verdict:** Per-process. Capping one process and over-allocating a sibling
under the same UID does not affect the sibling.

**How:** A 2-process Kotlin app (main activity + `:heavy` service, same UID)
is capped on one process at 30 MB while 600 MB is allocated into either
process via native `mmap`. Four scenarios isolate whether the cap crosses
process boundaries.

| | |
|---|---|
| App | [`limiter-app/`](limiter-app/) — minimal 2-process Kotlin app |
| Scripts | [`limiter-experiment/`](limiter-experiment/) — `run.sh`, `parse-results.ts`, config XML |
| Results | [`limiter-experiment/results/`](limiter-experiment/results/) — JSON + raw adb/dumpsys/logcat output |
| README | [`limiter-experiment/README.md`](limiter-experiment/README.md) |

### 2. R8 shrinking benchmark

**Question:** How much does R8 actually reduce APK size, resident code memory,
and cold-start time on a realistic app?

**Verdict:** APK -87%, code PSS -82%, DEX classes -80%, methods -86%. Cold
start is a wash on the emulator (-2%, inside stddev); the `madvise()` page-in
win needs a physical device with eMMC to show.

**How:** A realistic app (Compose + Retrofit + Coil + Room +
kotlinx.serialization, all exercised at startup) is built as two release
variants — `minifyEnabled false` vs `minifyEnabled true` with
`proguard-android-optimize.txt`. The runner measures APK size, `dumpsys
meminfo` Code PSS/RSS, `showmap` app-code RSS, `dexdump` class/method counts,
Perfetto traces, and 12-iteration cold-start timing (2 warmup dropped, 10
measured, mean/median/stddev).

| Metric | R8 off | R8 on | Delta |
|---|---|---|---|
| APK size | 22.17 MB | 2.82 MB | -87% |
| Code PSS (dumpsys) | 17.0 MB | 3.1 MB | -82% |
| Code RSS (showmap, app code) | 27.5 MB | 13.8 MB | -50% |
| DEX classes | 15,467 | 3,071 | -80% |
| DEX methods | 115,906 | 16,480 | -86% |
| Cold start (mean) | 378 ms (±109) | 369 ms (±122) | -2% |

| | |
|---|---|
| App | [`r8-benchmark-app/`](r8-benchmark-app/) — Compose + Retrofit + Coil + Room app, plus `:benchmark` macrobenchmark module |
| Scripts | [`r8-benchmark/`](r8-benchmark/) — `build.sh`, `run.ts`, `parse-results.ts` |
| Results | [`r8-benchmark/results/`](r8-benchmark/results/) — JSON + raw meminfo/showmap/dexdump/perfetto output |
| README | [`r8-benchmark/README.md`](r8-benchmark/README.md) |

---

## Repository structure

```
android17-memory-lab/
├── limiter-app/              # 2-process Kotlin app (main + :heavy service)
├── limiter-experiment/       # run.sh, parse-results.ts, config XML, results/
├── r8-benchmark-app/         # Compose app + :benchmark macrobenchmark module
├── r8-benchmark/             # build.sh, run.ts, parse-results.ts, results/
└── README.md                 # this file
```

## Prerequisites

- Android 17 (API 37) emulator or device. The emulator ships with the limiter
  **disabled**; see [`limiter-experiment/README.md`](limiter-experiment/README.md)
  for the one-time setup to enable it via a vendor overlay config.
- `adb` on PATH; `adb root` must work (a userdebug build, which the emulator
  image is).
- Android SDK build-tools (for `dexdump`) under
  `~/Library/Android/sdk/build-tools/`.
- `node` + `pnpm` (for the TypeScript runners and parsers).
- JDK 17 (for Gradle builds).

## Quick start

```bash
# Experiment 1: multi-process limiter
# (one-time) enable the limiter on the emulator:
emulator -avd rz-api37 -writable-system
limiter-experiment/setup-emulator.sh

cd limiter-app && ./gradlew :app:assembleDebug && adb install -r app/build/outputs/apk/debug/app-debug.apk
cd ../limiter-experiment && ./run.sh

# Experiment 2: R8 benchmark
cd ../r8-benchmark-app && ./gradlew :app:assembleReleaseNor8 :app:assembleRelease :benchmark:assembleDebug
cd ../r8-benchmark && pnpm tsx run.ts --iterations 10
```

Each experiment writes a timestamped results directory with JSON + raw audit
artifacts. Runs are idempotent — every invocation produces a new directory.

## License

MIT. The apps and scripts are throwaway experimental tooling; use them freely.

## Companion article

[**Android 17's memory ceiling**](https://returnzero.dev/articles/android-17-memory-ceiling)
on [returnzero.dev](https://returnzero.dev).