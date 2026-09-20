# Bounded page-type study

Build `limiter-app` and install its debug APK on an Android 17 device with an
active limiter. Keep the lab activity visible. Run:

```sh
python3 limiter-experiment/compare-pages.py --device SERIAL --iterations 5 --duration 30
MPLCONFIGDIR=/tmp/limiter-matplotlib python3 limiter-experiment/plot-pages.py limiter-experiment/results/RUN
```

The runner writes metadata, raw command transcripts, samples.csv per trial, and
result.json per trial. Plotting creates SVG and PNG charts plus summary.json.
Only the lab worker gets a manual override. The runner removes that override
and force-stops the lab after each trial. Global ignore settings are untouched.

Three modes touch 256 MiB in 4 MiB steps, 250 ms apart: anonymous mappings,
read-only file mappings, and private file mappings dirtied once per page.
Anonymous and dirty pages are allocated natively to avoid an ART heap failure.
The file is generated in the app's private storage and fsynced before trials.
This is a warm-cache experiment. File-cache charge ownership may differ from
the process's mapped RSS; the cgroup and process charts deliberately report
different counters. Do not present them as interchangeable memory measures.

Each mode has five runs in seeded shuffled order. There is no discarded warmup
or reboot in this protocol. The device's ambient memory state is recorded, not
reset. Native anonymous pages are highly compressible: only one byte per page
is written. Results cannot be generalized to random/incompressible buffers.

The Pixel's command help reports percentage units, but readback on build
CP2A.260805.005 confirms integer MiB. A manual value of 128 initially sets both
memory.high and memory.swap.max to 134217728. memory.swap.high stays max.
memory.high can change during execution; plot its actual sampled values.

Thirty-second survival is an observation, not proof that a workload cannot be
killed. Exit history and exact PID survival are recorded before cleanup.
If a worker exits before allocation completes, inspect its exit reason before
classifying the run. This protocol does not yet implement the complete article
plan's sibling-allocation experiment, visibility experiment, or a cold file
cache comparison.

The runner caps each trial at 256 MiB and 30 seconds by default, and refuses
new trials if battery temperature reaches 38 C. Disconnects can prevent cleanup;
manual overrides last only as long as the worker PID. Force-stop the lab after
reconnecting if a run was interrupted.
