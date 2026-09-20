# Multi-process Android app labs

Companion tooling for
[One Android app. Why so many processes?](https://returnzero.dev/articles/one-android-app-why-so-many-processes).

| Directory | Purpose |
|---|---|
| [`apk-pipeline/`](apk-pipeline/) | Validates APK archives, decodes manifests and resources, disassembles DEX, and indexes components by declared process |
| [`app-study/`](app-study/) | Records and audits process, cgroup, service, memory, and lifecycle observations from an attached device |

These tools separate static package evidence from runtime observations. Process
names and manifest declarations do not establish why a vendor chose an
architecture.

APKs, decompiled proprietary code, and raw device results stay outside git.
Only the reusable inspection and recording tools are published here.
