# R8 shrinking benchmark: real-world impact on size, memory, and cold start

Benchmarks a realistic Android app (Kotlin, Compose, Retrofit + OkHttp, Coil,
Room, kotlinx.serialization) with R8 enabled vs disabled, measuring APK size,
resident code in RAM, and cold-start time.

## Result (latest run)

Run `2026-08-26T0808Z` - Android 17 (API 37), `sdk_gphone64_arm64`, 3.8 GB RAM
emulator, 12 cold-start iterations (2 warmup dropped, 10 measured, 1 s settle).

| Metric | R8 off | R8 on | Delta |
|---|---|---|---|
| APK size | 22.17 MB | 2.82 MB | -87% |
| Code PSS (dumpsys) | 17.0 MB | 3.1 MB | -82% |
| Code RSS (dumpsys) | 111.8 MB | 97.7 MB | -13% |
| Code RSS (showmap) | 27.5 MB | 13.8 MB | -50% |
| DEX classes | 15467 | 3071 | -80% |
| DEX methods | 115906 | 16480 | -86% |
| Cold start (mean) | 378 ms (±109) | 369 ms (±122) | -2% |
| Cold start (median) | 444 ms | 443 ms | -0% |
| Cold start (min) | 223 ms | 176 ms | -21% |

R8 stripped 12,396 of 15,467 classes (-80%) and 99,426 of 115,906 methods
(-86%). The APK shrank 87%. Resident code PSS fell 82%. Cold-start mean did not
meaningfully move (-2%, inside the ±109/±122 ms stddev) - emulator cold start
is dominated by host scheduling and swiftshader GPU emulation, not storage
page-in, so the `madvise()` win the docs show does not reproduce here. Size
and code-resident-memory numbers are stable; cold-start needs a physical
device (especially eMMC) to show the page-in delta.

The two code-RSS numbers measure different things. `dumpsys meminfo` Code RSS
includes all file-backed code mappings the process touches (framework `.oat`,
`.art`, shared libraries) and only drops 13% because most of it is shared
framework code R8 cannot touch. `showmap` code RSS, summed over only the app's
own `base.apk`/`base.odex` plus boot `.oat`/`.dex`, drops 50% - that is the
app-attributable code footprint. Code PSS (proportional, so shared pages are
fractionally charged) drops 82%, the closest single number to "how much less
RAM your code costs."

## Device tiers

This run used a single Android 17 (API 37) ARM64 emulator at 3.8 GB RAM. The
task spec asks for 2 device tiers (flagship + budget); a second emulator
profile with `-memory 2048` did not report a lower `MemTotal` (the emulator
reports host-visible memory regardless of the `-memory` flag on this image),
so the two tiers were not meaningfully different and the second run was
dropped. To get a real budget tier, run on a physical low-RAM device or an
emulator image with enforced cgroup memory limits. The script accepts
`--device <serial>` so you can run it against any attached device.

## Prerequisites

- Android 17 (API 37) emulator or device, booted, with `adb root` working
  (userdebug build - `showmap` needs root).
- `adb` on PATH.
- Android SDK build-tools (for `dexdump`) under
  `~/Library/Android/sdk/build-tools/`.
- The benchmark app built via `build.sh` (see below).
- `perfetto` on the device (present on userdebug emulator images).

## Build both APK variants

```bash
r8-benchmark/build.sh
```

Builds two release APKs from the benchmark app (in `../r8-benchmark-app/`):

- **R8 off** (`releaseNor8` build type, `minifyEnabled false`) - the baseline.
- **R8 on** (`release` build type, `minifyEnabled true`, `proguardFiles
  getDefaultProguardFile('proguard-android-optimize.txt')` + app keep rules).

Copies them to `r8-benchmark/build/app-r8-off.apk` and
`app-r8-on.apk`.

Keep rules needed (in the app's `proguard-rules.pro`):

- **kotlinx.serialization** - keep the `Companion` and `serializer()` for
  `@Serializable` data classes so the generated serializers are not stripped.
- **Retrofit** - keep `@retrofit2.http.*`-annotated interface methods and the
  `retrofit2.Call`/`Response`/`Continuation` types.
- **Room** - keep `RoomDatabase` subclasses and `@Entity` classes (KSP-generated
  DAO implementations reference them by name).
- **Coil** - keep `coil.compose.**` (Compose integration uses reflection).

No keep rule blocked shrinking of a major library in this app. The Compose
compiler plugin and kotlinx.serialization compiler plugin generate code that
R8 can reach, so no broad `-keep class com.example.** { *; }` was needed.

## Run the benchmark

```bash
pnpm tsx r8-benchmark/run.ts --iterations 10
```

For a specific device:

```bash
pnpm tsx r8-benchmark/run.ts --device emulator-5554 --iterations 10
```

For each variant, the runner:

1. Uninstalls any prior copy, installs the APK.
2. Runs 12 cold starts via `am start -W -S` (atomic force-stop + start),
   drops the first 2 (warmup), records `TotalTime` for the remaining 10,
   with a 1 s settle between iterations. Reports mean, median, min, max,
   and stddev.
3. Does one more cold start, waits 5 s for settle, runs `dumpsys meminfo <pkg>`
   (parses the App Summary `Code` row PSS + RSS) and `showmap <pid>` (sums RSS
   for `.oat`/`.odex`/`.dex`/`base.apk` mappings).
4. Runs `dexdump -f` on each DEX in the APK and sums `class_defs_size` and
   `method_ids_size`.
5. Captures a Perfetto trace (ftrace + process_stats) for one cold start and
   saves the raw trace for audit.
6. Records the APK file size.

### Cold-start measurement: macrobenchmark vs manual protocol

The proper Android tool for cold-start benchmarking is `androidx.benchmark`
macro-junit4. The benchmark app includes a `:benchmark` module
(`ColdStartBenchmark.kt`) that uses `MacrobenchmarkRule.measureRepeated` with
`StartupMode.COLD` and `StartupTimingMetric`, which handles warmup,
statistical analysis, and Perfetto trace capture. Build it with `build.sh`
(it also produces `build/benchmark.apk`) and run via:

```bash
adb install -r r8-benchmark/build/benchmark.apk
adb shell am instrument -w -e class com.returnzero.benchmark.ColdStartBenchmark \
  -e androidx.benchmark.suppressErrors EMULATOR \
  com.returnzero.benchmark.macrobench/androidx.benchmark.junit4.AndroidBenchmarkRunner
```

However, on this Android 17 (API 37) emulator build, `am start -W` does not
emit the "Displayed" signal the macrobenchmark framework needs to confirm
activity launch completion (`IllegalStateException: Unable to confirm activity
launch completion`), so the instrumentation throws. The `run.ts` script
therefore falls back to the equivalent manual protocol (`am start -W -S`,
which is what the framework uses internally) with explicit warmup, settle,
and statistics. On a physical device where the macrobenchmark instrumentation
runs, prefer it over the manual protocol.

All raw output (`meminfo`, `showmap`, `dexdump`, perfetto traces, cold-start
logs) is saved under `results/<timestamp>/raw/<variant>/` for audit. The
parsed JSON is at `results/<timestamp>/results.json`.

Idempotent: every run produces a new timestamped directory.

## Regenerate the article table

```bash
pnpm tsx r8-benchmark/parse-results.ts
```

Picks the most recent `results/*/results.json` and prints a markdown table
plus a summary. Pass a path to parse a specific run.

## The benchmark app

The app lives outside the repo (per the task constraint). It is a minimal but
realistic Compose app:

- `MainActivity` with a `NavHost` + `FeedScreen`.
- `FeedViewModel` (AndroidViewModel) that loads from Room, builds a Retrofit
  client, and parses a synthetic JSON feed via kotlinx.serialization on
  startup (so serialization is genuinely exercised even without network).
- `FeedScreen` renders a `LazyColumn` of article cards with `AsyncImage`
  (Coil) image loads.
- Room database with one entity and a DAO (`insertAll`, `getAll`, `clear`).

Every library is called at runtime, so R8's reachability analysis keeps the
live code and strips the rest - the numbers reflect a real shrinking pass, not
a toy that imports but never calls.