# Android 17 memory labs

Companion projects for
[Android 17 is prioritizing memory efficiency](https://returnzero.dev/articles/android-17-prioritizing-memory-efficiency).

| Directory | Purpose |
|---|---|
| [`limiter-app/`](limiter-app/) | Two-process Android app for limiter and page-backing experiments |
| [`limiter-experiment/`](limiter-experiment/) | Limiter runner, file-vs-anonymous page study, parsers, and plots |
| [`r8-benchmark-app/`](r8-benchmark-app/) | Realistic Android app with R8-on and R8-off variants |
| [`r8-benchmark/`](r8-benchmark/) | Build, measurement, and result parsing scripts |

The checked-in source includes the current physical-device page study. Raw
device outputs remain local because they can contain device and application
details.

Start with [the limiter experiment guide](limiter-experiment/README.md) or
[the R8 benchmark guide](r8-benchmark/README.md). Run commands from this
article directory unless a guide tells you to enter a child project.
