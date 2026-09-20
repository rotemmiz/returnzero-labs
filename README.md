# returnzero labs

Runnable Android apps, capture tools, parsers, and reproducible experiments
for technical articles on [returnzero.dev](https://returnzero.dev).

Each article has one directory. Demo apps and scripts live beside the README
that defines what they measure, how to run them, and what their results do not
prove.

## Article labs

| Article | Apps and tooling |
|---|---|
| [Android 17 is prioritizing memory efficiency](https://returnzero.dev/articles/android-17-prioritizing-memory-efficiency) | [Memory limiter, page-type, and R8 experiments](articles/android-17-prioritizing-memory-efficiency/) |
| [The insomniac Android: diagnosing wakelock battery leaks](https://returnzero.dev/articles/android-wakelock-battery-leaks) | [Media3 playback ownership app and Battery Historian compatibility patch](articles/android-wakelock-battery-leaks/) |
| [One Android app. Why so many processes?](https://returnzero.dev/articles/one-android-app-why-so-many-processes) | [APK inspection pipeline and device process recorder](articles/one-android-app-why-so-many-processes/) |

## Repository rules

- Commit source, small generated fixtures, and documentation needed to repeat
  an experiment.
- Keep APKs, decompiled proprietary code, bugreports, device captures, and
  outputs containing personal identifiers outside git.
- Treat a script's output as evidence only within the limits documented beside
  that script.
- Use an article slug for every new top-level lab under `articles/`.

## Requirements

Requirements vary by lab. Common tools are Python 3, JDK 17, the Android SDK,
and `adb`. Read the article directory before running a project.

## License

MIT. Individual media files may declare a separate license beside the file.
