# Reading an Android 17 capture with Battery Historian

Companion to “The insomniac Android: diagnosing wakelock battery leaks.”

These notes describe the local repair and a subsequently reconstructed parser workaround. They are not a complete modern build recipe or a claim that all Android 17 fields are supported.

## Capture and source

- Device: Pixel 9 Pro XL, Android 17, build CP2A.260805.005.
- Capture: September 19, 2026.
- Historian source: https://github.com/google/battery-historian/tree/d2356ba4fd5f
- Parser patch: [battery-historian-controller-compat.patch](./battery-historian-controller-compat.patch)
- Reconstructed parser validation used Go 1.26.4.

Google archived the repository on December 29, 2022. The original local frontend revival used Closure Library pinned to v20170409 and changed Python invocations to python3. The reconstruction described below validates the checkin parser, not the frontend build.

## Why the tables were empty

The second day's report produced “Could not parse aggregated battery stats.” Its controller data included this record:

```text
9,0,l,gmcd,175294,5335007,223.96022555555555,0.0,450,1032,2614,2843,6378
```

The old controller parser expects integer fields. Fractional strings cause its integer parsing to fail, aborting the aggregate result. The decimal 223.96022555555555 occupies the old format's power field; describing every fractional value as a timing would be misleading.

The patch retains integer strings and converts finite, in-range fractional values to rounded integers. That gets data into the legacy representation. It does not validate modern field order, units, or modem-energy calculations.

## Apply the reconstructed workaround

The original local patch was not preserved. This patch reconstructs the numeric-format workaround against the source revision above. Save the patch locally and run these commands from that checkout:

```bash
git apply --check /path/to/battery-historian-controller-compat.patch
git apply /path/to/battery-historian-controller-compat.patch
```

The patch changes only `checkinparse/checkin_parse.go`; the file already imports `math` and `strconv`. It uses `math.Round` and was tested with the Go version named above. Rebuild the parser or Historian binary using your checkout's dependency setup. The patch does not supply that setup.

## What was verified

Against the same saved day-two checkin input:

| Result | Original parser | Patched parser |
|---|---:|---:|
| Aggregate result populated | No | Yes |
| Parser errors | 1 | 0 |
| Warnings | 1 | 1,724 |
| Apps | Unavailable | 257 |
| Wake lock entries | Unavailable | 593 |

Six focused checks covered legacy integers, fractional conversion, invalid text, NaN, infinity, and overflow. The checks also verified that normalization did not mutate the caller's input slice.

Zero parser errors is not zero compatibility problems. Treat the 1,724 warnings as a limit on interpretation. The article uses the wake lock table, cross-checked against text battery statistics; it does not use this workaround to establish accurate modern controller-energy estimates.

## Recording a future capture

Enable detailed wake lock history before a reproduction if that detail is needed:

```bash
adb shell dumpsys batterystats --enable full-wake-history
adb bugreport wake-lock-report.zip
adb shell dumpsys batterystats --disable full-wake-history
```

The history flag affects future recording; it cannot restore attribution absent from an old report. In the saved capture, some summary timeline spans were labelled `unknown-wakelock-holder`, while the aggregate table retained per-app attribution. A timeline spanning charging and discharging also has a different measurement window from on-battery counters.

Capture synchronized player events, audio state, power state, and suspend events when investigating causality. A long BatteryStats duration alone does not establish that a lock prevented suspend for that duration.

Raw bugreports can contain account, device, and application information. This companion publishes selected measurements and the parser patch, not the raw report.
