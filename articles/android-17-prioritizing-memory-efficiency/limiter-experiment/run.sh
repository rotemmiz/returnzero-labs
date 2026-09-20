#!/usr/bin/env bash
#
# Multi-process Android 17 memory limiter experiment.
#
# Verifies whether the Android 17 memory limiter caps each process independently
# (per-process cgroup memory.high + memory.swap.high) or aggregates across all
# processes sharing a UID.
#
# Runs three scenarios:
#   1. Cap :heavy, allocate in :heavy  -> :heavy killed, main survives (per-process cap)
#   2. Cap main,  allocate in main     -> main killed,  :heavy survives (per-process cap)
#   3. Cap :heavy, allocate in main    -> main NOT killed (no aggregate UID cap)
#   4. Cap main,  allocate in :heavy   -> :heavy NOT killed (no aggregate UID cap)
#
# Output: a timestamped JSON file plus a directory of raw adb/logcat/dumpsys
# output for audit. Idempotent: every run produces a new result file.
#
# Prerequisites:
#   - Android 17 (API 37) emulator/device with the memory limiter enabled
#     (see README.md for the vendor config setup)
#   - The experiment app installed (com.returnzero.limiter)
#   - adb on PATH; device connected; `adb root` works (userdebug build)
#
# Usage:
#   limiter-experiment/run.sh [results_dir]
#
set -uo pipefail

PKG="com.returnzero.limiter"
MAIN_ACTIVITY="$PKG/.MainActivity"
HEAVY_SERVICE="$PKG/.HeavyService"
LIMIT_MB="${LIMIT_MB:-30}"          # manual cap in MB (low enough that 600MB alloc blows it)
ALLOC_MB="${ALLOC_MB:-600}"         # native mmap allocation in MB
KILL_TIMEOUT_S="${KILL_TIMEOUT_S:-90}"  # the limiter kills 30s after the anon+swap event
BOOT_WAIT_S="${BOOT_WAIT_S:-15}"
HERE="$(cd "$(dirname "$0")" && pwd)"

RESULTS_DIR="${1:-$HERE/results}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$RESULTS_DIR/$TS"
RAW_DIR="$RUN_DIR/raw"
mkdir -p "$RAW_DIR"

log() { printf '[run %s] %s\n' "$TS" "$*" | tee -a "$RAW_DIR/run.log"; }

fail() { log "ERROR: $*"; exit 1; }

require() { command -v "$1" >/dev/null 2>&1 || fail "missing dependency: $1"; }
require adb
command -v python3 >/dev/null 2>&1 || fail "missing dependency: python3 (needed for JSON escaping)"

# --- preflight ---------------------------------------------------------------
adb get-state >/dev/null 2>&1 || fail "no adb device"

API_LEVEL=$(adb shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r')
[[ "$API_LEVEL" == "37" ]] || fail "expected API 37 (Android 17), got '$API_LEVEL'"

LIM_STATUS=$(adb shell am memory-limiter status 2>&1)
echo "$LIM_STATUS" > "$RAW_DIR/limiter-status.preflight.txt"
echo "$LIM_STATUS" | grep -q "enabled" || fail "memory limiter not enabled (see README.md)"

# Confirm the app is installed.
adb shell pm path "$PKG" >/dev/null 2>&1 || fail "app $PKG not installed"

log "preflight ok: API=$API_LEVEL limiter enabled, app installed"

# --- helpers -----------------------------------------------------------------
pid_of_main() { adb shell ps -A 2>&1 | grep -E "${PKG}$" | awk '{print $2}' | tr -d '\r'; }
pid_of_heavy() { adb shell ps -A 2>&1 | grep ":heavy" | awk '{print $2}' | tr -d '\r'; }

clear_limiter() {
  # Remove any manual limits and ignored UIDs from prior runs.
  local m h
  m=$(pid_of_main); h=$(pid_of_heavy)
  [[ -n "$m" ]] && adb shell am memory-limiter manual "$m" none >/dev/null 2>&1 || true
  [[ -n "$h" ]] && adb shell am memory-limiter manual "$h" none >/dev/null 2>&1 || true
  adb shell am memory-limiter ignore none >/dev/null 2>&1 || true
}

start_app() {
  adb shell am force-stop "$PKG" >/dev/null 2>&1
  adb shell am start -n "$MAIN_ACTIVITY" >/dev/null 2>&1
  # Wait for both processes to spawn.
  local i
  for i in $(seq 1 15); do
    sleep 1
    [[ -n "$(pid_of_main)" ]] && [[ -n "$(pid_of_heavy)" ]] && return 0
  done
  return 1
}

allocate_in() {
  local target="$1" mb="$2"
  if [[ "$target" == "main" ]]; then
    # Bring activity to front with the alloc extra (cold intent -> onCreate reads it).
    adb shell am start -n "$MAIN_ACTIVITY" --ei alloc_mb "$mb" >/dev/null 2>&1
  else
    adb shell am startservice -n "$HEAVY_SERVICE" --ei alloc_mb "$mb" >/dev/null 2>&1
  fi
}

alive_main()  { [[ -n "$(pid_of_main)" ]]; }
alive_heavy() { [[ -n "$(pid_of_heavy)" ]]; }

# Poll for a kill. Args: process ("main"|"heavy"), timeout seconds.
# Sets global KILLED=1 if the process died, 0 if still alive at timeout.
wait_for_kill() {
  local proc="$1" timeout="$2"
  KILLED=0
  local i
  for i in $(seq 1 "$((timeout * 2))"); do
    sleep 0.5
    if [[ "$proc" == "main" ]]; then alive_main || { KILLED=1; return; }
    else alive_heavy || { KILLED=1; return; }
    fi
  done
}

capture_state() {
  local label="$1"
  {
    echo "=== $label ==="
    echo "--- ps ---";        adb shell ps -A 2>&1 | grep "$PKG"
    echo "--- limiter ---";  adb shell am memory-limiter status 2>&1
  } > "$RAW_DIR/${label}.txt" 2>&1
}

# Run one scenario. Args: name, cap_target, alloc_target.
run_scenario() {
  local name="$1" cap_target="$2" alloc_target="$3"
  log "scenario $name: cap=$cap_target alloc=$alloc_target"

  start_app || fail "could not start both processes for $name"
  sleep 2
  local main_pid heavy_pid
  main_pid=$(pid_of_main); heavy_pid=$(pid_of_heavy)
  [[ -n "$main_pid" ]] && [[ -n "$heavy_pid" ]] || fail "missing PIDs for $name (main=$main_pid heavy=$heavy_pid)"
  log "main_pid=$main_pid heavy_pid=$heavy_pid"

  clear_limiter
  sleep 1

  local cap_pid
  if [[ "$cap_target" == "main" ]]; then cap_pid="$main_pid"
  else cap_pid="$heavy_pid"; fi

  log "applying manual cap ${LIMIT_MB}MB to $cap_target (pid=$cap_pid)"
  adb shell am memory-limiter manual "$cap_pid" "$LIMIT_MB" 2>&1 | tee "$RAW_DIR/${name}.cap.txt" || true
  sleep 1
  # Record the cgroup memory.high right after applying the cap.
  adb shell "su 0 cat /sys/fs/cgroup/apps/uid_10231/pid_${cap_pid}/memory.high 2>&1" \
    > "$RAW_DIR/${name}.cgroup-memory-high.txt" 2>&1 || true

  capture_state "${name}.pre-alloc"

  log "allocating ${ALLOC_MB}MB in $alloc_target"
  allocate_in "$alloc_target" "$ALLOC_MB"

  # The killed target is the process that is allocated into.
  local killed_target="$alloc_target"
  log "waiting up to ${KILL_TIMEOUT_S}s for $killed_target to be killed"
  wait_for_kill "$killed_target" "$KILL_TIMEOUT_S"
  local killed=$KILLED

  capture_state "${name}.post-alloc"

  # Pull the relevant logcat slice (kill line + limiter events) for this scenario.
  adb logcat -d 2>&1 | grep -iE "MemoryLimiter|LimiterExp|Killing.*MemoryLimiter" \
    > "$RAW_DIR/${name}.logcat.txt" 2>&1 || true

  local main_alive heavy_alive
  alive_main && main_alive=true || main_alive=false
  alive_heavy && heavy_alive=true || heavy_alive=false

  log "scenario $name result: killed=$killed main_alive=$main_alive heavy_alive=$heavy_alive"

  # Emit a JSON object fragment for this scenario.
  cat > "$RUN_DIR/${name}.json" <<EOF
{
  "name": "$name",
  "cap_target": "$cap_target",
  "cap_mb": $LIMIT_MB,
  "alloc_target": "$alloc_target",
  "alloc_mb": $ALLOC_MB,
  "main_pid": $main_pid,
  "heavy_pid": $heavy_pid,
  "killed_target": "$killed_target",
  "killed": $killed,
  "main_alive_after": $main_alive,
  "heavy_alive_after": $heavy_alive
}
EOF

  # Clean up for the next scenario.
  clear_limiter
  adb shell am force-stop "$PKG" >/dev/null 2>&1
  sleep 2
}

# --- run scenarios -----------------------------------------------------------
log "starting experiment: limit_mb=$LIMIT_MB alloc_mb=$ALLOC_MB kill_timeout=${KILL_TIMEOUT_S}s"

run_scenario "s1-cap-heavy-alloc-heavy" "heavy" "heavy"
run_scenario "s2-cap-main-alloc-main"   "main"  "main"
run_scenario "s3-cap-heavy-alloc-main"  "heavy" "main"
run_scenario "s4-cap-main-alloc-heavy"  "main"  "heavy"

# --- assemble final JSON -----------------------------------------------------
log "assembling results.json"
{
  echo "{"
  echo "  \"timestamp\": \"$TS\","
  echo "  \"device\": {"
  echo "    \"api_level\": $API_LEVEL,"
  echo "    \"build_id\": \"$(adb shell getprop ro.build.id 2>/dev/null | tr -d '\r')\","
  echo "    \"release\": \"$(adb shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')\","
  echo "    \"mem_total_kb\": $(adb shell cat /proc/meminfo 2>/dev/null | head -1 | awk '{print $2}' | tr -d '\r')"
  echo "  },"
  echo "  \"config\": { \"limit_mb\": $LIMIT_MB, \"alloc_mb\": $ALLOC_MB, \"kill_timeout_s\": $KILL_TIMEOUT_S },"
  echo "  \"limiter_status_preflight\": $(python3 -c "import json,sys; print(json.dumps(open('$RAW_DIR/limiter-status.preflight.txt').read()))"),"
  echo "  \"scenarios\": ["
  echo "    $(cat "$RUN_DIR/s1-cap-heavy-alloc-heavy.json"),"
  echo "    $(cat "$RUN_DIR/s2-cap-main-alloc-main.json"),"
  echo "    $(cat "$RUN_DIR/s3-cap-heavy-alloc-main.json"),"
  echo "    $(cat "$RUN_DIR/s4-cap-main-alloc-heavy.json")"
  echo "  ]"
  echo "}"
} > "$RUN_DIR/results.json"

log "done. results in $RUN_DIR/results.json"
echo
echo "=== SUMMARY ==="
echo "Run dir: $RUN_DIR"
for s in s1-cap-heavy-alloc-heavy s2-cap-main-alloc-main s3-cap-heavy-alloc-main s4-cap-main-alloc-heavy; do
  python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d["name"] + ": killed=" + str(d["killed"]) + " main_alive=" + str(d["main_alive_after"]) + " heavy_alive=" + str(d["heavy_alive_after"]))
' "$RUN_DIR/$s.json"
done