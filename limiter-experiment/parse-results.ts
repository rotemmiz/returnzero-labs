/**
 * Parse limiter-experiment results JSON and emit a markdown table for the
 * article, plus a human-readable summary on stdout.
 *
 * Usage:
 *   pnpm tsx scripts/limiter-experiment/parse-results.ts [results.json]
 *
 * Without an argument, defaults to the most recent results file.
 */

import { readdir, readFile, stat } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

interface Scenario {
  name: string;
  cap_target: "main" | "heavy";
  cap_mb: number;
  alloc_target: "main" | "heavy";
  alloc_mb: number;
  main_pid: number;
  heavy_pid: number;
  killed_target: string;
  killed: 0 | 1;
  main_alive_after: boolean;
  heavy_alive_after: boolean;
}

interface Results {
  timestamp: string;
  device: {
    api_level: number;
    build_id: string;
    release: string;
    mem_total_kb: number;
  };
  config: { limit_mb: number; alloc_mb: number; kill_timeout_s: number };
  limiter_status_preflight: string;
  scenarios: Scenario[];
}

async function latestResults(): Promise<string> {
  const here = dirname(fileURLToPath(import.meta.url));
  const resultsRoot = resolve(here, "results");
  let entries: string[];
  try {
    entries = await readdir(resultsRoot);
  } catch {
    throw new Error(`no results dir at ${resultsRoot}`);
  }
  let best = "";
  let bestMtime = 0;
  for (const entry of entries) {
    const file = resolve(resultsRoot, entry, "results.json");
    try {
      const s = await stat(file);
      if (s.isFile() && s.mtimeMs > bestMtime) {
        bestMtime = s.mtimeMs;
        best = file;
      }
    } catch {
      // skip
    }
  }
  if (!best) throw new Error("no results.json found under " + resultsRoot);
  return best;
}

function verdictLine(s: Scenario): string {
  const capped = s.cap_target;
  const allocated = s.alloc_target;
  const sameProcess = capped === allocated;
  if (sameProcess) {
    return s.killed === 1
      ? `Capped ${capped} at ${s.cap_mb} MB, allocated ${s.alloc_mb} MB in ${allocated}: ${allocated} killed, ${capped === "main" ? "heavy" : "main"} survived.`
      : `Capped ${capped} at ${s.cap_mb} MB, allocated ${s.alloc_mb} MB in ${allocated}: ${allocated} NOT killed (unexpected).`;
  }
  return s.killed === 0
    ? `Capped ${capped} at ${s.cap_mb} MB, allocated ${s.alloc_mb} MB in ${allocated} (the uncapped process): ${allocated} NOT killed.`
    : `Capped ${capped} at ${s.cap_mb} MB, allocated ${s.alloc_mb} MB in ${allocated}: ${allocated} killed (aggregate UID cap present).`;
}

function buildTable(r: Results): string {
  const header =
    "| Scenario | Cap target | Cap (MB) | Alloc target | Alloc (MB) | Killed? | Main alive | Heavy alive |";
  const sep = "|---|---|---|---|---|---|---|---|";
  const rows = r.scenarios.map((s) => {
    const kill = s.killed === 1 ? "yes" : "no";
    const main = s.main_alive_after ? "yes" : "no";
    const heavy = s.heavy_alive_after ? "yes" : "no";
    return `| ${s.name} | ${s.cap_target} | ${s.cap_mb} | ${s.alloc_target} | ${s.alloc_mb} | ${kill} | ${main} | ${heavy} |`;
  });
  return [header, sep, ...rows].join("\n");
}

async function main() {
  const file = process.argv[2] ? resolve(process.cwd(), process.argv[2]) : await latestResults();
  const raw = await readFile(file, "utf8");
  const r = JSON.parse(raw) as Results;

  const perProcess = r.scenarios.filter((s) => s.cap_target === s.alloc_target);
  const aggregate = r.scenarios.filter((s) => s.cap_target !== s.alloc_target);
  const perProcessConfirmed = perProcess.every((s) => s.killed === 1);
  const aggregateRefuted = aggregate.every((s) => s.killed === 0);
  const verdict =
    perProcessConfirmed && aggregateRefuted
      ? "CONFIRMED: the limiter caps each process independently. No aggregate per-UID cap."
      : "RESULT UNEXPECTED: see the table.";

  const lines: string[] = [];
  lines.push(`# Android 17 multi-process memory limiter experiment`);
  lines.push(``);
  lines.push(`Run: ${r.timestamp}`);
  lines.push(
    `Device: Android ${r.device.release} (API ${r.device.api_level}), build ${r.device.build_id}, ${(r.device.mem_total_kb / 1024 / 1024).toFixed(1)} GB RAM.`
  );
  lines.push(
    `Limiter config: visible ${/visibleMem=(\d+)MB/.exec(r.limiter_status_preflight)?.[1] ?? "?"} MB, manual cap ${r.config.limit_mb} MB, allocation ${r.config.alloc_mb} MB.`
  );
  lines.push(``);
  lines.push(buildTable(r));
  lines.push(``);
  lines.push(`**Verdict:** ${verdict}`);
  lines.push(``);
  for (const s of r.scenarios) {
    lines.push(`- ${verdictLine(s)}`);
  }
  lines.push(``);
  lines.push(`Source: \`${file}\``);

  const out = lines.join("\n");
  process.stdout.write(out + "\n");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});