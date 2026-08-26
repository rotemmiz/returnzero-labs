/**
 * Parse R8 benchmark results JSON and emit a markdown table for the article,
 * plus a human-readable summary on stdout.
 *
 * Usage:
 *   pnpm tsx scripts/r8-benchmark/parse-results.ts [results.json]
 *
 * Without an argument, picks the most recent results file.
 */

import { readdir, readFile, stat } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

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

interface Results {
  timestamp: string;
  iterations: number;
  device: {
    serial: string;
    api_level: number;
    release: string;
    build_id: string;
    model: string;
    device: string;
    mem_total_kb: number;
  };
  variants: VariantResult[];
}

async function latestResults(): Promise<string> {
  const here = dirname(fileURLToPath(import.meta.url));
  const root = resolve(here, "results");
  let entries: string[];
  try {
    entries = await readdir(root);
  } catch (e) {
    throw new Error("no results dir at " + root);
  }
  let best = "";
  let bestMtime = 0;
  for (const entry of entries) {
    const file = resolve(root, entry, "results.json");
    try {
      const s = await stat(file);
      if (s.isFile() && s.mtimeMs > bestMtime) {
        bestMtime = s.mtimeMs;
        best = file;
      }
    } catch (e) { /* skip */ }
  }
  if (!best) throw new Error("no results.json found");
  return best;
}

function mb(bytes: number): string {
  return (bytes / 1024 / 1024).toFixed(2);
}
function kb(n: number): string {
  return (n / 1024).toFixed(1);
}
function pct(old: number, neu: number): string {
  if (old <= 0) return "-";
  const r = ((old - neu) / old) * 100;
  return r > 0 ? `-${r.toFixed(0)}%` : `+${Math.abs(r).toFixed(0)}%`;
}

function buildTable(r: Results): string {
  const off = r.variants.find((v) => v.label === "r8-off")!;
  const on = r.variants.find((v) => v.label === "r8-on")!;
  const header =
    "| Metric | R8 off | R8 on | Delta |";
  const sep = "|---|---|---|---|";
  const rows = [
    `| APK size | ${mb(off.apk_bytes)} MB | ${mb(on.apk_bytes)} MB | ${pct(off.apk_bytes, on.apk_bytes)} |`,
    `| Code PSS (dumpsys) | ${kb(off.code_pss_kb)} MB | ${kb(on.code_pss_kb)} MB | ${pct(off.code_pss_kb, on.code_pss_kb)} |`,
    `| Code RSS (dumpsys) | ${kb(off.code_rss_kb)} MB | ${kb(on.code_rss_kb)} MB | ${pct(off.code_rss_kb, on.code_rss_kb)} |`,
    `| Code RSS (showmap) | ${kb(off.showmap_code_rss_kb)} MB | ${kb(on.showmap_code_rss_kb)} MB | ${pct(off.showmap_code_rss_kb, on.showmap_code_rss_kb)} |`,
    `| DEX classes | ${off.dex_classes} | ${on.dex_classes} | ${pct(off.dex_classes, on.dex_classes)} |`,
    `| DEX methods | ${off.dex_methods} | ${on.dex_methods} | ${pct(off.dex_methods, on.dex_methods)} |`,
    `| Cold start (mean) | ${off.cold_start_ms.mean} ms (±${off.cold_start_ms.stddev}) | ${on.cold_start_ms.mean} ms (±${on.cold_start_ms.stddev}) | ${pct(off.cold_start_ms.mean, on.cold_start_ms.mean)} |`,
    `| Cold start (median) | ${off.cold_start_ms.median} ms | ${on.cold_start_ms.median} ms | ${pct(off.cold_start_ms.median, on.cold_start_ms.median)} |`,
    `| Cold start (min) | ${off.cold_start_ms.min} ms | ${on.cold_start_ms.min} ms | ${pct(off.cold_start_ms.min, on.cold_start_ms.min)} |`,
  ];
  return [header, sep, ...rows].join("\n");
}

async function main() {
  const file = process.argv[2] ? resolve(process.cwd(), process.argv[2]) : await latestResults();
  const raw = await readFile(file, "utf8");
  const r = JSON.parse(raw) as Results;

  const lines: string[] = [];
  lines.push("# R8 shrinking benchmark: real-world impact on size, memory, and cold start");
  lines.push("");
  lines.push(`Run: ${r.timestamp}`);
  lines.push(
    `Device: Android ${r.device.release} (API ${r.device.api_level}), ${r.device.model}, ${(r.device.mem_total_kb / 1024 / 1024).toFixed(1)} GB RAM, ${r.iterations} cold-start iterations (first dropped).`
  );
  lines.push("");
  lines.push(
    `App: Compose + Navigation + Retrofit 2 + OkHttp + Coil + Room + kotlinx.serialization, all exercised at runtime (synthetic feed parsed on startup, Room seeded, Coil image requests issued, Retrofit client built). R8 build uses proguard-android-optimize.txt with keep rules for kotlinx.serialization, Retrofit, and Room.`
  );
  lines.push("");
  lines.push(buildTable(r));
  lines.push("");
  const off = r.variants.find((v) => v.label === "r8-off")!;
  const on = r.variants.find((v) => v.label === "r8-on")!;
  lines.push(
    `R8 stripped ${off.dex_classes - on.dex_classes} of ${off.dex_classes} classes (${pct(off.dex_classes, on.dex_classes)}) and ${off.dex_methods - on.dex_methods} of ${off.dex_methods} methods (${pct(off.dex_methods, on.dex_methods)}). APK shrank from ${mb(off.apk_bytes)} MB to ${mb(on.apk_bytes)} MB (${pct(off.apk_bytes, on.apk_bytes)}). Resident code PSS fell from ${kb(off.code_pss_kb)} MB to ${kb(on.code_pss_kb)} MB (${pct(off.code_pss_kb, on.code_pss_kb)}). Cold-start mean moved from ${off.cold_start_ms.mean} ms (±${off.cold_start_ms.stddev}) to ${on.cold_start_ms.mean} ms (±${on.cold_start_ms.stddev}); median from ${off.cold_start_ms.median} ms to ${on.cold_start_ms.median} ms.`
  );
  lines.push("");
  lines.push(`Source: ${file}`);
  process.stdout.write(lines.join("\n") + "\n");
}

main().catch((e) => { console.error(e); process.exit(1); });