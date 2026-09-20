# One-device capture

Install the debug app, connect Wi-Fi ADB, and manually unlock the phone. Keep the audio route constant and disconnect physical charging for battery trials. The runner never guesses a PIN or changes volume, app-ops, battery history, Doze, or global logging.

```sh
python3 capture/capture.py --serial 'YOUR_ADB_SERIAL' --scenario foreground --output /tmp/playback-runs
python3 analysis/report.py /tmp/playback-runs/RUN_ID
python3 -m unittest discover -s analysis -p 'test_*.py'
```

Scenarios: `foreground`, `retained`, `background`, `paused`. Defaults: `--baseline-seconds 15 --play-seconds 30 --observe-seconds 180 --cleanup-seconds 15`. Shorten durations only for a harness pilot. Playback plus quiet observation must total at most 270 seconds, leaving some headroom before the app's five-minute safety deadline. Snapshot overhead adds time; inspect deadline events before interpreting a run.

The runner captures sequential timestamp-bracketed audio, audio-flinger, power, battery attribution and process snapshots at boundaries. It probes Perfetto data sources and atrace categories, requests supported categories and power ftrace events, and preserves the config and capability output. A requested event is not proof that the kernel provides it: validate markers, clock relationship, event availability and loss counters in Perfetto. Traces stop on explicit cleanup or their bounded duration.

Home ends the foreground area, then the runner sleeps the screen. There are no ADB calls during the quiet observation interval. Boundary snapshots occur afterward and perturb the device. The initial baseline is screen-on idle and **cannot serve as a matched suspend baseline**. A separate manually unlocked screen-off idle trial is required for meaningful suspend comparison. Wi-Fi ADB and instrumentation can affect results.

The runner wakes the screen before explicit Stop. Secure keyguard may delay that Activity command; inspect app release events instead of assuming it succeeded. `finally` force-stops only the sample package and finalizes the trace even after Ctrl-C or SIGTERM. The fallback force-stop is a separate manifest boundary, never natural cleanup evidence. If the phone disconnects, the app's non-waking deadline is the fallback and executes when the process next gets CPU time.

Output directories and files are private by default (0700/0600). Raw snapshots and traces can expose unrelated applications or system activity. **Do not commit or publish them.** No bugreport or system-wide logcat is collected. `report.json` and `report.md` contain selected app event counts and numeric AudioMix durations for the sample UID, with no device serial or other app names. Inspect even those reports before publishing. `events.jsonl` is the private complete app log; the analyzer selects the current run.

The report separates balanced app create/release records from device cleanup, which remains inconclusive pending trace and audio analysis. Cumulative attribution entries are not per-run durations, active-lock proof, prevented suspend, or battery-hours measurements. No automatic causality claims are made.

The private manifest records run ID, scenario, durations, app UID, actual Android build, command time brackets, capture boundaries, trace warnings and status. `private/environment-package.txt` records installed package metadata; `private/environment-battery.txt` records charge/temperature. Source commit, APK hash and build dependency versions must accompany the run from the build record. The capture never infers these from the current checkout.
