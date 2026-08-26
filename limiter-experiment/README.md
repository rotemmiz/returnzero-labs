# Multi-process memory limiter experiment

Verifies whether the Android 17 memory limiter caps each process independently
(per-process cgroup `memory.high` + `memory.swap.high`) or aggregates across all
processes sharing a UID. The companion article
([Android 17's memory ceiling](https://returnzero.dev/articles/android-17-memory-ceiling),
section "Splitting the budget: multi-process architecture") makes the per-process
claim; this experiment confirms or refutes it on a real device.

## Verdict

**Confirmed: the limiter caps each process independently. There is no aggregate
per-UID cap.** Capping one process and allocating in a sibling process under the
same UID does not affect the sibling.

## Result (latest run)

Run: `20260825T235154Z` - Android 17 (API 37), build `CE2A.260420.019`, 3.8 GB
RAM emulator, limiter config visible 2048 MB / not-visible 1024 MB, manual cap
30 MB, allocation 600 MB per scenario.

| Scenario | Cap target | Cap (MB) | Alloc target | Alloc (MB) | Killed? | Main alive | Heavy alive |
|---|---|---|---|---|---|---|---|
| s1-cap-heavy-alloc-heavy | heavy | 30 | heavy | 600 | yes | yes | no |
| s2-cap-main-alloc-main | main | 30 | main | 600 | yes | no | yes |
| s3-cap-heavy-alloc-main | heavy | 30 | main | 600 | no | yes | yes |
| s4-cap-main-alloc-heavy | main | 30 | heavy | 600 | no | yes | yes |

- s1/s2: capping a process and over-allocating it kills it; the sibling survives.
- s3/s4: capping one process does not affect the sibling under the same UID,
  so the cap is per-process, not an aggregate per-UID budget.

## Prerequisites

- Android 17 (API 37) emulator or device. The emulator ships with the limiter
  **disabled** because the vendor partition has no config XML; see the setup
  steps below to enable it.
- `adb` on PATH; `adb root` must work (a userdebug build, which the emulator
  image is).
- `python3` on PATH (used for JSON escaping and the summary print).
- The experiment app `com.returnzero.limiter` installed. The app source is not
  in this repo; see the app setup below.

## Enable the limiter on an emulator

The emulator's `/vendor` partition ships without
`/vendor/etc/memory-limiter-config.xml`, so `am memory-limiter status` reports
`disabled` on a fresh image. The setup script automates the whole process:

```bash
# Boot the emulator with a writable system overlay first:
emulator -avd rz-api37 -writable-system

# Then run the setup script:
limiter-experiment/setup-emulator.sh
```

The script:
1. Verifies the device is API 37 and `adb root` works.
2. Disables verity and reboots (the overlay mounts on the next boot).
3. Pushes `memory-limiter-config.xml` to the vendor overlay upper dir.
4. Reboots so `system_server` reads the config at boot.
5. Verifies the limiter is enabled (`am memory-limiter status`).

Pass a device serial if multiple are attached:
`limiter-experiment/setup-emulator.sh emulator-5554`.

The config file (`memory-limiter-config.xml` in this directory) sets a single
limit set with `memVisible=2048 MB`, `memNotVisible=1024 MB`, `swapVisible=1024
MB`, `swapNotVisible=1024 MB`, applicable to any RAM size (`minimumRequiredMemTotal
= 0`). It is a test config; do not ship it.

## App setup

The experiment app is a minimal 2-process Kotlin app, in `../limiter-app/`.
Build and install it:

```bash
cd ../limiter-app
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The app declares:

- `MainActivity` (main process, `launchMode="singleTop"`) - accepts an
  `alloc_mb` intent extra to allocate native (mmap) memory in the main process.
- `HeavyService` (`android:process=":heavy"`, exported) - accepts an `alloc_mb`
  intent extra to allocate native memory in the `:heavy` process.

Native allocation is used (not Java `ByteArray`) because the ART heap growth
limit OOMs at ~192 MB before the cgroup `memory.high` / `memory.swap.high` cap
is reached. Native `mmap(MAP_ANONYMOUS)` with page-touching grows resident anon
memory past the ART heap and triggers the limiter's `anon+swap` kill path.

## Run the experiment

```bash
limiter-experiment/run.sh
```

This runs all four scenarios, writes a timestamped JSON result plus a `raw/`
directory of adb/dumpsys/logcat output for audit, under
`limiter-experiment/results/<timestamp>/`. Idempotent: each run
produces a new timestamped directory.

Tunables (env vars):

- `LIMIT_MB` (default 30) - manual cap in MB.
- `ALLOC_MB` (default 600) - native allocation in MB per scenario.
- `KILL_TIMEOUT_S` (default 90) - seconds to wait for a kill. The limiter
  kills 30 s after the `anon+swap` event fires, so 90 s is a safe ceiling.

## Regenerate the article table

```bash
pnpm tsx limiter-experiment/parse-results.ts
```

Picks the most recent `results/*/results.json`, prints a markdown table and
verdict to stdout. Pass a path to parse a specific run:

```bash
pnpm tsx limiter-experiment/parse-results.ts limiter-experiment/results/20260825T235154Z/results.json
```

## How the kill path works

The limiter assigns each process to a cgroup
(`/sys/fs/cgroup/apps/uid_<uid>/pid_<pid>/`) and sets `memory.high` and
`memory.swap.high`. Exceeding `memory.high` raises a `memory.high` event
(throttling, reclaim). Exceeding the swap budget raises an `anon+swap` event,
which schedules a SIGKILL after a 30 s delay (`KILL_DELAY_MS` in
`MemoryLimiter.java`). The kill reason is labeled `MemoryLimiter:AnonSwap` and
is visible in `ApplicationExitInfo` and `adb logcat` as
`Killing <pid>:<pkg> ... : MemoryLimiter:AnonSwap`.

`am memory-limiter manual <pid> <mb>` overrides the per-process cap. The manual
limit applies to both `memory.high` and `memory.swap.high`. The cap is per-PID:
a sibling process under the same UID keeps its own (uncapped or
config-derived) cgroup limits.