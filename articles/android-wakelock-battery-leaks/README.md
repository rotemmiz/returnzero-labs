# Wakelock and playback ownership labs

Companion projects for
[The insomniac Android: diagnosing wakelock battery leaks](https://returnzero.dev/articles/android-wakelock-battery-leaks).

| Directory | Purpose |
|---|---|
| [`playback-ownership/`](playback-ownership/) | Runnable Media3 app comparing foreground cleanup, retained playback, background audio, paused retention, and player pooling |
| [`battery-historian/`](battery-historian/) | Compatibility note and patch for parsing the Android 17 bugreport used in the article |

The app is a prevention and measurement example. It is not copied code from X,
Reddit, or another commercial app, and it does not claim to reproduce their
internal implementation.

Raw captures and bugreports stay outside git. They can contain account, device,
and application information.
