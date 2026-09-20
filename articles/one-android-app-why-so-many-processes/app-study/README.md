# Major-app process study

This directory publishes reusable runtime recording and audit tools. The article explains the study protocol and interpretation boundaries.

## Current gate

`record.py` is a bounded **passive capability recorder**, not the finished
scenario runner. It performs no gestures, app launches, force-stops, or settings
changes. Its results are explicitly excluded from article trial statistics.

Run parser tests with `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_record test_audit test_summary`.
Run a probe with `python3 record.py --serial DEVICE --output results/UNIQUE-RUN --seconds 30`.
An existing output directory is never overwritten. Target defaults to Chrome.

Raw ADB outputs include command durations and timestamps. Per-process status,
identity, OOM adjustment, and cgroup readings are stored in processes.jsonl;
samples.csv is only a convenient RSS/swap projection. Cgroup bytes and proc KiB
must not be combined without conversion. `max` remains a literal unlimited
control value, not a missing counter. Missing observations remain null.

Heavy before/after snapshots retain service/process associations, exit histories,
full per-PID meminfo, thermal and battery diagnostics. They occur outside the
lightweight sampling window and can affect memory state. Measured sweep latency
is not a complete observer-effect assessment. PSS must be parsed/validated before
use; no summed physical RAM claim is produced here.

Candidate coverage currently uses package UID and package-name prefixes,
including named isolated processes and app zygotes. Service records are retained
for manual audit; additional service-linked PIDs and unresolved associations
still need integration before the full study. Process identity brackets each
PID read with start-time checks. It does not make a multi-process sweep atomic.

Next: audit service attribution; validate meminfo PSS/USS parsing, marker/state
capture and lifecycle intervals; lock the Chrome test pages; measure observer
effects with matched workflows; then run foreground/background scenario pilots.
Do not call these passive probes controlled app trials.

`chrome_pilot.py` now runs bounded visible warm-session pilots for Chrome or
Maps (`--app maps`). These are supervised pilots: visually verify the intended
view before gestures, and clean up the study view after recording. It preserves
existing sessions and does not force-stop. It is not a repeated-trial runner.
`audit_snapshots.py` marks header-only meminfo as missing and retains service
hosting evidence. `summarize_pilot.py` creates exploratory candidate RSS/swap
timelines with snapshot gaps and explicit incomplete-coverage labels.

Results are private and gitignored. Do not upload raw records: package/service
output can contain personal identifiers. Each finished probe has a SHA-256
manifest. New runs also retain recorder source. The first development probe
predated source archiving; its source hash and raw output remain available.
Arrange private backup before the long campaign.
