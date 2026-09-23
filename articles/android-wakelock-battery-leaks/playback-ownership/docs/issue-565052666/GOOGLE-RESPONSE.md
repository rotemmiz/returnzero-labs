# Draft response to Google issue 565052666

**Not ready to submit: the corrected measurement matrix and demonstration evidence are pending.** Replace this status and add the reviewed results before sending. This file has not been posted to Google.

Thank you. I prepared a standalone reproduction project with two separate APKs:

- The Media3 playback app compares foreground release, deliberately continued playback, intentional background playback, and paused retention. Its final merged manifest excludes WAKE_LOCK; it makes no direct wake-lock acquisition.
- The direct-lock app has WAKE_LOCK permission and compares untimed partial-lock acquisition with a 60-second acquisition timeout. It has no media playback or foreground service.

The [project instructions](README.md) provide the build commands, manual scenario descriptions, capture commands and interpretation limits. Both apps include explicit cleanup and a five-minute safety deadline. The direct untimed mode is deliberately incorrect application behavior, clearly labeled in the UI.

Validation completed on a Pixel 9 Pro XL running Android 17, build CP2A.260805.005: eight playback instrumentation tests and four direct-lock instrumentation tests passed. The final playback test asserts the absence of WAKE_LOCK permission. A keyguard-interrupted test attempt was preserved and followed by a successful unlocked rerun.

The measurement protocol uses a matched idle control plus the six app scenarios, three repetitions per condition, and a 180-second quiet screen-off observation. It now requires an unlocked start and an observed Awake power state before the controlled screen-off transition. Earlier locked-start control captures are excluded from comparisons.

## To complete after collection

- Link the published project at its tested source revision and include both APK hashes.
- State the observed outcome for each scenario, including negative or inconclusive results.
- Add the separate screen-recording and post-reproduction bugreport references after reviewing those private artifacts.
- If sharing is later authorized, use a restricted Drive folder for android-bugreport@google.com and insert its link. No Drive sharing is part of the current task.

A finite observation does not establish indefinite persistence. Direct isHeld state, attributed BatteryStats time, current AudioMix ownership, and effective suspend behavior are reported separately. Deliberately continuing playback is not by itself a reproduction of the originally reported paused/non-playing commercial-app behavior.
