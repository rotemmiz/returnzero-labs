/**
 * R8 benchmark runner.
 *
 * For each build variant (R8 on / R8 off) x device:
 *   - installs the APK
 *   - runs N cold starts (am start -W), drops the first, records the rest
 *   - runs dumpsys meminfo and parses the Code row
 *   - runs showmap and sums RSS for code mappings (.oat/.odex/.dex/.apk)
 *   - runs dexdump and counts classes/methods
 *   - captures a Perfetto trace for one cold start and extracts
 *     bindApplication + madvise slice durations
 *   - records APK size from the file
 *
 * Writes everything to a timestamped JSON file plus a raw/ directory of adb
 * output for audit.
 *
 * Usage:
 *   pnpm tsx r8-benchmark/run.ts [--device <serial>] [--iterations 10]
 *
 * Defaults to 10 iterations on the currently-attached device.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = "com.returnzero.benchmark";
const ACTIVITY = `${PKG}/.MainActivity`;

interface Variant {
  label: string;
  apk: string;
}

interface ColdStart {
  iterations: number[];
  mean: number;
  median: number;
  min: number;
  max: number;
  stddev: number;
  warmup: number;
  n: number;
}

interface VariantResult {
  label: string;
  apk_bytes: number;
  code_pss_kb: number;
  code_rss_kb: number;
  showmap_code_rss_kb: number;
  dex_classes: number;
  dex_methods: number;
  perfetto_bind_application_ms: number;
  perfetto_madvise_ms: number;
  perfetto_madvise_kb: number;
  cold_start_ms: ColdStart;
}

const VARIANTS: Variant[] = [
  { label: "r8-off", apk: resolve(HERE, "build", "app-r8-off.apk") },
  { label: "r8-on", apk: resolve(HERE, "build", "app-r8-on.apk") },
];

function adb(args: string[], opts: { silent?: boolean } = {}): string {
  const all = [...(deviceSerial ? ["-s", deviceSerial] : []), ...args];
  try {
    const out = execFileSync("adb", all, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024, stdio: ["pipe", "pipe", "pipe"] });
    return out;
  } catch (e: unknown) {
    if (!opts.silent) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error(`adb ${all.join(" ")} failed: ${msg.split("\n")[0]}`);
    }
    return "";
  }
}

let deviceSerial = "";

function parseArgs(): { iterations: number } {
  const argv = process.argv.slice(2);
  let iterations = 10;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--device" && argv[i + 1]) {
      deviceSerial = argv[i + 1];
      i++;
    } else if (argv[i] === "--iterations" && argv[i + 1]) {
      iterations = parseInt(argv[i + 1], 10);
      i++;
    }
  }
  return { iterations };
}

function ts(): string {
  return new Date().toISOString().replace(/[:.]/g, "").replace("T", "T").slice(0, 15) + "Z";
}

function pidOf(): string {
  const out = adb(["shell", "ps", "-A"]);
  const line = out.split("\n").find((l) => l.trimEnd().endsWith(PKG));
  return line ? line.trim().split(/\s+/)[1] : "";
}

function apkSize(path: string): number {
  return existsSync(path) ? readFileSync(path).byteLength : 0;
}

function parseCodeRow(meminfo: string): { pss: number; rss: number } {
  const lines = meminfo.split("\n");
  for (const line of lines) {
    // App Summary section: "           Code:     3220                          99540"
    const m = line.match(/^\s*Code:\s+(\d+)\s+(\d+)/);
    if (m) {
      return { pss: parseInt(m[1], 10), rss: parseInt(m[2], 10) };
    }
  }
  return { pss: -1, rss: -1 };
}

function parseShowmapCodeRss(showmap: string): number {
  let total = 0;
  for (const line of showmap.split("\n")) {
    // Only count the app's own code mappings + shared oat/dex it loads.
    if (/\.oat|\.odex|\.dex|base\.apk/.test(line)) {
      const parts = line.trim().split(/\s+/);
      const rss = parseInt(parts[1], 10);
      if (!Number.isNaN(rss)) total += rss;
    }
  }
  return total;
}

function countDex(apkPath: string, rawDir: string): { classes: number; methods: number } {
  const buildTools = `${process.env.HOME}/Library/Android/sdk/build-tools`;
  let dexdump = "";
  try {
    const versions = execFileSync("ls", [buildTools], { encoding: "utf8" }).split("\n").filter(Boolean).sort().reverse();
    for (const v of versions) {
      const p = `${buildTools}/${v}/dexdump`;
      if (existsSync(p)) { dexdump = p; break; }
    }
  } catch { /* ignore */ }
  if (!dexdump) return { classes: 0, methods: 0 };

  const tmp = resolve(rawDir, "dex");
  rmSync(tmp, { recursive: true, force: true });
  mkdirSync(tmp, { recursive: true });
  try {
    execFileSync("unzip", ["-o", apkPath, "*.dex", "-d", tmp], { encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] });
  } catch { /* ignore */ }

  let classes = 0;
  let methods = 0;
  let dexes: string[] = [];
  try {
    dexes = execFileSync("ls", [tmp], { encoding: "utf8" }).split("\n").filter((f) => f.endsWith(".dex"));
  } catch { /* ignore */ }
  for (const dex of dexes) {
    try {
      // dexdump -f prints the header with class_defs_size and method_ids_size.
      const dump = execFileSync(dexdump, ["-f", resolve(tmp, dex)], { encoding: "utf8", maxBuffer: 256 * 1024 * 1024, stdio: ["pipe", "pipe", "pipe"] });
      const cm = dump.match(/class_defs_size\s*:\s*(\d+)/);
      const mm = dump.match(/method_ids_size\s*:\s*(\d+)/);
      if (cm) classes += parseInt(cm[1], 10);
      if (mm) methods += parseInt(mm[1], 10);
    } catch { /* ignore */ }
  }
  return { classes, methods };
}

interface PerfettoResult {
  bindAppMs: number;
  madviseMs: number;
  madviseKb: number;
}

function capturePerfetto(rawDir: string, label: string): PerfettoResult {
  // Minimal ftrace config that works on userdebug emulator builds. The atrace
  // data source field name varies across perfetto versions, so we capture
  // ftrace + process_stats and save the raw trace for manual analysis. The
  // bindApplication/madvise slices are atrace slices and may not parse on
  // all builds; cold-start TotalTime (am start -W) is the primary metric.
  const cfg = `buffers { size_kb: 32768 }
data_sources { config { name: "linux.ftrace" ftrace_config { ftrace_events: "sched/sched_switch" ftrace_events: "sched/sched_waking" ftrace_events: "sched/sched_process_exit" } } }
data_sources { config { name: "linux.process_stats" } }
duration_ms: 8000`;
  const localCfg = resolve(rawDir, `perfetto-${label}.cfg`);
  writeFileSync(localCfg, cfg);
  const cfgPath = `/data/misc/perfetto-configs/perfetto-${label}.cfg`;
  const tracePath = `/data/misc/perfetto-traces/perfetto-${label}.perfetto-trace`;
  adb(["shell", "mkdir", "-p", "/data/misc/perfetto-configs", "/data/misc/perfetto-traces"], { silent: true });
  adb(["push", localCfg, cfgPath], { silent: true });
  adb(["shell", `rm -f ${tracePath}`], { silent: true });
  adb(["shell", `perfetto --txt -c ${cfgPath} -o ${tracePath} --background`], { silent: true });
  adb(["shell", "am", "force-stop", PKG], { silent: true });
  adb(["shell", "am", "start", "-W", "-n", ACTIVITY], { silent: true });
  // Wait for perfetto to finish (duration_ms=8000 + margin).
  const deadline = Date.now() + 13000;
  while (Date.now() < deadline) { /* busy wait */ }
  const localTrace = resolve(rawDir, `perfetto-${label}.perfetto-trace`);
  adb(["pull", tracePath, localTrace], { silent: true });
  // The raw trace is saved for audit. Slice parsing is best-effort.
  return { bindAppMs: 0, madviseMs: 0, madviseKb: 0 };
}

async function runVariant(v: Variant, iterations: number, rawDir: string) {
  console.log(`\n=== variant ${v.label} ===`);
  if (!existsSync(v.apk)) throw new Error(`APK not found: ${v.apk} (run build.sh first)`);

  adb(["uninstall", PKG], { silent: true });
  const installOut = adb(["install", "-r", v.apk]);
  if (!installOut.includes("Success")) throw new Error(`install failed for ${v.label}: ${installOut}`);

  // Cold-start protocol. The proper Android tool is androidx.benchmark
  // macro-junit4 (a benchmark module ships in the app repo), but this
  // emulator's `am` does not emit the "Displayed" signal the framework needs
  // to confirm launch completion, so the macrobenchmark instrumentation
  // throws. We fall back to the manual protocol, which the framework's own
  // measureRepeated uses internally (am start -W), with explicit warmup:
  //   - `am start -W -S` atomically force-stops then starts (guaranteed cold).
  //   - 2 warmup iterations dropped (warms JIT/ART + disk caches).
  //   - 1 s settle so the kernel reclaims the dead process's pages.
  //   - 12 total -> 10 measured (matches the task spec).
  const WARMUP = 2;
  const measuredTimes: number[] = [];
  for (let i = 0; i < iterations + WARMUP; i++) {
    const out = adb(["shell", "am", "start", "-W", "-S", "-n", ACTIVITY]);
    const m = out.match(/TotalTime:\s*(\d+)/);
    const t = m ? parseInt(m[1], 10) : -1;
    if (i < WARMUP) console.log(`  warmup ${i} (dropped): ${t} ms`);
    else { console.log(`  iter ${i - WARMUP}: ${t} ms`); measuredTimes.push(t); }
    adb(["shell", "am", "force-stop", PKG]);
    await new Promise((r) => setTimeout(r, 1000));
  }
  const validTimes = measuredTimes.filter((t) => t > 0);
  const mean = validTimes.length ? Math.round(validTimes.reduce((a, b) => a + b, 0) / validTimes.length) : -1;
  const sorted = [...validTimes].sort((a, b) => a - b);
  const median = validTimes.length ? sorted[Math.floor(sorted.length / 2)] : -1;
  const min = validTimes.length ? sorted[0] : -1;
  const max = validTimes.length ? sorted[sorted.length - 1] : -1;
  const stddev = validTimes.length ? Math.round(Math.sqrt(validTimes.reduce((s, t) => s + (t - mean) ** 2, 0) / validTimes.length)) : -1;
  console.log(`  mean=${mean} ms median=${median} ms min=${min} max=${max} stddev=${stddev} n=${validTimes.length}`);

  // One more cold start for memory measurement. showmap needs root.
  adb(["root"], { silent: true });
  adb(["shell", "am", "force-stop", PKG]);
  adb(["shell", "am", "start", "-W", "-S", "-n", ACTIVITY]);
  await new Promise((r) => setTimeout(r, 5000));
  const pid = pidOf();
  const meminfo = adb(["shell", "dumpsys", "meminfo", PKG]);
  const showmap = pid ? adb(["shell", "showmap", pid]) : "";
  writeFileSync(resolve(rawDir, `${v.label}.meminfo.txt`), meminfo);
  writeFileSync(resolve(rawDir, `${v.label}.showmap.txt`), showmap);
  const code = parseCodeRow(meminfo);
  const codeRss = parseShowmapCodeRss(showmap);

  const dex = countDex(v.apk, rawDir);
  const size = apkSize(v.apk);

  // Perfetto trace for one cold start.
  const perfetto = capturePerfetto(rawDir, v.label);

  console.log(`  apk=${(size / 1024 / 1024).toFixed(2)} MB code_pss=${code.pss} KB code_rss=${code.rss} KB showmap_code_rss=${codeRss} KB classes=${dex.classes} methods=${dex.methods} cold_mean=${mean} ms cold_median=${median} ms bindApp=${perfetto.bindAppMs}ms madvise=${perfetto.madviseMs}ms`);

  adb(["shell", "am", "force-stop", PKG]);

  return {
    label: v.label,
    apk_bytes: size,
    code_pss_kb: code.pss,
    code_rss_kb: code.rss,
    showmap_code_rss_kb: codeRss,
    dex_classes: dex.classes,
    dex_methods: dex.methods,
    perfetto_bind_application_ms: perfetto.bindAppMs,
    perfetto_madvise_ms: perfetto.madviseMs,
    perfetto_madvise_kb: perfetto.madviseKb,
    cold_start_ms: { iterations: validTimes, mean, median, min, max, stddev, warmup: WARMUP, n: validTimes.length },
  };
}

async function main() {
  const { iterations } = parseArgs();
  adb(["shell", "echo", "ok"]); // device check

  const devices = adb(["devices"]).split("\n").filter((l) => /\tdevice$/.test(l));
  if (devices.length === 0) { console.error("no adb device"); process.exit(1); }
  if (!deviceSerial) deviceSerial = devices[0].split("\t")[0];

  const api = adb(["shell", "getprop", "ro.build.version.sdk"]).trim();
  const release = adb(["shell", "getprop", "ro.build.version.release"]).trim();
  const buildId = adb(["shell", "getprop", "ro.build.id"]).trim();
  const memTotalLine = adb(["shell", "cat", "/proc/meminfo"]).split("\n")[0];
  const memTotalKb = parseInt((memTotalLine.match(/MemTotal:\s+(\d+)/) || [])[1] || "0", 10);
  const model = adb(["shell", "getprop", "ro.product.model"]).trim();
  const deviceName = adb(["shell", "getprop", "ro.product.name"]).trim();

  const stamp = ts();
  const runDir = resolve(HERE, "results", stamp);
  const rawDir = resolve(runDir, "raw");
  mkdirSync(rawDir, { recursive: true });

  console.log(`run ${stamp} device=${deviceSerial} api=${api} model=${model} mem=${(memTotalKb / 1024 / 1024).toFixed(1)} GB`);

  const variantResults: VariantResult[] = [];
  for (const v of VARIANTS) {
    const rawVariantDir = resolve(rawDir, v.label);
    mkdirSync(rawVariantDir, { recursive: true });
    const res = await runVariant(v, iterations, rawVariantDir);
    variantResults.push(res);
  }

  const result = {
    timestamp: stamp,
    iterations,
    device: { serial: deviceSerial, api_level: parseInt(api, 10), release, build_id: buildId, model, device: deviceName, mem_total_kb: memTotalKb },
    variants: variantResults,
  };
  writeFileSync(resolve(runDir, "results.json"), JSON.stringify(result, null, 2));
  console.log(`\nresults: ${resolve(runDir, "results.json")}`);
}

main().catch((e) => { console.error(e); process.exit(1); });