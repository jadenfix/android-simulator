#!/usr/bin/env bash
set -euo pipefail

NAME="${1:-android-sim-play}"
SSID="${ANDROID_SIM_SMOKE_SSID:-AndroidSimSmoke}"
PASSWORD="${ANDROID_SIM_SMOKE_PASSWORD:-smoke-test-password}"
SERIAL=""

cleanup() {
  if [[ -n "$SERIAL" ]]; then
    android-sim stop --serial "$SERIAL" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

android-sim doctor
START_OUTPUT="$(android-sim start "$NAME" --cold --headless --no-audio --wifi-ssid "$SSID" --wifi-password "$PASSWORD")"
printf '%s\n' "$START_OUTPUT"
SERIAL="$(printf '%s\n' "$START_OUTPUT" | awk '/^Started / {print $4}')"
if [[ -z "$SERIAL" ]]; then
  echo "Could not parse emulator serial from start output." >&2
  exit 2
fi

android-sim identity --serial "$SERIAL" --json
android-sim network --serial "$SERIAL" status
android-sim shell --serial "$SERIAL" -- cmd package list packages android
android-sim stop --serial "$SERIAL"
SERIAL=""

echo "macOS emulator smoke test passed for $NAME"
