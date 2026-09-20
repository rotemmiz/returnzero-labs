#!/usr/bin/env bash
#
# Enable the Android 17 memory limiter on an emulator.
#
# The emulator's /vendor partition ships without
# /vendor/etc/memory-limiter-config.xml, so `am memory-limiter status` reports
# `disabled` on a fresh image. This script:
#   1. Checks the emulator is running and is an API 37 userdebug build.
#   2. Disables verity and reboots (the overlay mounts on the next boot).
#   3. Pushes the config XML to the vendor overlay upper dir.
#   4. Reboots so system_server reads the config at boot.
#   5. Verifies the limiter is enabled.
#
# Prerequisites:
#   - Emulator booted with -writable-system (or -writable-system overlay).
#     If you haven't booted with -writable-system, the script will detect it
#     and tell you to relaunch.
#   - adb root must work (userdebug build, which the emulator image is).
#
# Usage:
#   limiter-experiment/setup-emulator.sh [serial]
#
# If no serial is given, uses the first device. If multiple devices are
# attached, pass the serial (e.g. emulator-5554).
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$HERE/memory-limiter-config.xml"

SERIAL="${1:-}"
ADB="adb"
if [[ -n "$SERIAL" ]]; then
  ADB="adb -s $SERIAL"
fi

# --- check config exists ---
if [[ ! -f "$CONFIG" ]]; then
  echo "ERROR: config not found: $CONFIG"
  exit 1
fi

# --- check device is connected ---
if ! $ADB get-state &>/dev/null; then
  echo "ERROR: no device found."
  echo "       Boot the emulator with: emulator -avd rz-api37 -writable-system"
  exit 1
fi

# --- check it's API 37 ---
API_LEVEL="$($ADB shell getprop ro.build.version.sdk 2>/dev/null | tr -d '[:space:]')"
if [[ "$API_LEVEL" != "37" ]]; then
  echo "ERROR: expected API 37 (Android 17), got API $API_LEVEL"
  exit 1
fi

echo "[setup] device: $($ADB shell getprop ro.product.model 2>/dev/null), API $API_LEVEL"

# --- check writable-system ---
if ! $ADB root &>/dev/null; then
  echo "ERROR: adb root failed. Boot with -writable-system:"
  echo "       emulator -avd rz-api37 -writable-system"
  exit 1
fi

# --- step 1: disable verity ---
VERITY="$($ADB shell dmverity --status 2>/dev/null || echo unknown)"
if echo "$VERITY" | grep -qi "enabled\|true"; then
  echo "[setup] disabling verity..."
  $ADB disable-verity
  echo "[setup] rebooting for overlay to mount..."
  $ADB reboot
  $ADB wait-for-device
  echo "[setup] waiting for boot to settle..."
  for i in $(seq 1 30); do
    if $ADB shell getprop sys.boot_completed 2>/dev/null | grep -q 1; then break; fi
    sleep 2
  done
  sleep 5
else
  echo "[setup] verity already disabled"
fi

# --- re-root after reboot ---
$ADB root >/dev/null 2>&1
sleep 2

# --- step 2: push config to vendor overlay ---
echo "[setup] pushing memory-limiter-config.xml..."
$ADB push "$CONFIG" /data/local/tmp/mlc.xml >/dev/null

echo "[setup] copying to vendor overlay upper dir..."
$ADB shell "su 0 mkdir -p /mnt/scratch/overlay/vendor/upper/etc" 2>/dev/null
$ADB shell "su 0 cp /data/local/tmp/mlc.xml /mnt/scratch/overlay/vendor/upper/etc/memory-limiter-config.xml" 2>/dev/null

# verify the file landed
if ! $ADB shell "ls /vendor/etc/memory-limiter-config.xml" &>/dev/null; then
  echo "ERROR: config not visible at /vendor/etc/memory-limiter-config.xml"
  echo "       The overlay may not have mounted. Try:"
  echo "         $ADB disable-verity && $ADB reboot"
  echo "       then re-run this script."
  exit 1
fi
echo "[setup] config is visible at /vendor/etc/memory-limiter-config.xml"

# --- step 3: reboot so system_server reads config ---
echo "[setup] rebooting for system_server to read config..."
$ADB reboot
$ADB wait-for-device
echo "[setup] waiting for boot to settle..."
for i in $(seq 1 30); do
  if $ADB shell getprop sys.boot_completed 2>/dev/null | grep -q 1; then break; fi
  sleep 2
done
sleep 5

# --- step 4: verify limiter is enabled ---
$ADB root >/dev/null 2>&1
sleep 1
STATUS="$($ADB shell am memory-limiter status 2>&1)"
if echo "$STATUS" | grep -q "enabled"; then
  echo "[setup] limiter is ENABLED:"
  echo "$STATUS" | head -5
  echo ""
  echo "[setup] done. You can now run: limiter-experiment/run.sh"
else
  echo "ERROR: limiter is not enabled. Status:"
  echo "$STATUS"
  exit 1
fi