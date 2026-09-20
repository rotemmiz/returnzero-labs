#!/usr/bin/env bash
#
# Build both APK variants for the R8 benchmark:
#   - R8 disabled  (releaseNor8 build type, minifyEnabled false)
#   - R8 enabled   (release build type, minifyEnabled true, proguard-android-optimize.txt)
#
# Copies the APKs to a known path alongside this script (build/) so run.ts
# can find them without poking into the app's build/outputs tree.
#
# Usage:
#   r8-benchmark/build.sh [app_dir]
#
# app_dir defaults to ../r8-benchmark-app (sibling of this directory in the
# repo). Override by passing a path as the first argument.
#
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${1:-}"

if [[ -z "$APP_DIR" ]]; then
  APP_DIR="$HERE/../r8-benchmark-app"
fi

if [[ -z "$APP_DIR" ]] || [[ ! -d "$APP_DIR" ]]; then
  echo "ERROR: app dir not found. Pass the path to the r8-benchmark-app root."
  echo "       Example: r8-benchmark/build.sh /path/to/r8-benchmark-app"
  exit 1
fi

OUT_DIR="$HERE/build"
mkdir -p "$OUT_DIR"

cd "$APP_DIR" || { echo "ERROR: cannot cd to $APP_DIR"; exit 1; }

if [[ -n "${JAVA_HOME:-}" ]]; then
  : # already set
elif [[ -d /Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home ]]; then
  export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home
fi

echo "[build] building releaseNor8 (R8 disabled), release (R8 enabled), and macrobenchmark module in $APP_DIR"
./gradlew :app:assembleReleaseNor8 :app:assembleRelease :benchmark:assembleDebug --no-daemon 2>&1 | tail -20

R8_OFF="$APP_DIR/app/build/outputs/apk/releaseNor8/app-releaseNor8.apk"
R8_ON="$APP_DIR/app/build/outputs/apk/release/app-release.apk"
BENCH="$APP_DIR/benchmark/build/outputs/apk/debug/benchmark-debug.apk"

if [[ ! -f "$R8_OFF" ]] || [[ ! -f "$R8_ON" ]] || [[ ! -f "$BENCH" ]]; then
  echo "ERROR: expected APKs not found:"
  echo "  R8 off: $R8_OFF"
  echo "  R8 on:  $R8_ON"
  echo "  bench:  $BENCH"
  exit 1
fi

cp "$R8_OFF" "$OUT_DIR/app-r8-off.apk"
cp "$R8_ON"  "$OUT_DIR/app-r8-on.apk"
cp "$BENCH"  "$OUT_DIR/benchmark.apk"

echo "[build] done"
echo "  R8 off: $OUT_DIR/app-r8-off.apk  ($(stat -f%z "$OUT_DIR/app-r8-off.apk") bytes)"
echo "  R8 on:  $OUT_DIR/app-r8-on.apk   ($(stat -f%z "$OUT_DIR/app-r8-on.apk") bytes)"
echo "  bench:  $OUT_DIR/benchmark.apk   ($(stat -f%z "$OUT_DIR/benchmark.apk") bytes)"