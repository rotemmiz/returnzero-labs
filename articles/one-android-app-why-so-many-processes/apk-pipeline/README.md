# APK architecture pipeline

ARM64-only policy: before decoding, the pipeline requires at least one real ELF64/AArch64 native library and checks every arm64-v8a library header. Non-ELF payloads stored under an arm64 library path are recorded and excluded from native analysis; they do not invalidate other verified AArch64 libraries. Universal originals are preserved, but only ARM64 native code is in research scope. Run `python3 audit_archives.py` for the durable ABI registry. Record the source, version, hash, and signer for every input in your private artifact manifest.

Artifacts and derived proprietary code stay in a private work directory such as `~/Downloads/apk-temps`, never public git. No APK is installed or executed.

Run with Python 3, Apktool 3.0.3, Android SDK apksigner 0.9 (path in pipeline.py):

```sh
python3 -m unittest -v
python3 pipeline.py inspect ~/Downloads/apk-temps/downloads/example.xapk
python3 index_code.py /absolute/job/path/printed/by/previous/command
```

`inspect` accepts APKs or ZIP APK bundles. It stages safe-named APK members, checks CRC and signatures, decodes all manifests/resources and disassembles DEX to smali, checks base/package/version/signing consistency, and records hashes, commands, timing and tool versions. Each run is new; failed runs remain available. Original archives remain untouched. A matching signer across splits is not independent publisher authentication.

`index_code.py` groups every component by declared process and indexes all disassembled classes/methods. Inspect raw attributes and resources for unresolved values. Process labels are not runtime counts. Smali is bytecode disassembly, not reconstructed Java. JADX is not installed; native machine-code tracing is not yet automated.

Human research then traces service inheritance and binding, IPC, native handoff, teardown, and documented or hypothesized motives. Write the per-app report under `reports/`, distinguishing configuration, code paths, vendor rationale and runtime observations. Do not automatically generate motives from process names.

Current limits: unique-run retries rather than resumable caching; no complete split dependency validator; cross-split aliases can remain unresolved; effective enabled/resource state needs manual review; no native call graph, publisher certificate allowlist, or same-build runtime validation. A successful manifest stage does not mean architecture research is complete. Pilot Chrome before any batch analysis.
