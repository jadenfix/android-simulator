#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Bootstrap an official Android Emulator environment on an Apple Silicon Mac.

Usage:
  ./scripts/bootstrap-macos.sh [options]

Options:
  --with-studio          Also install the Android Studio GUI.
  --install-homebrew     Install Homebrew using its official installer when absent.
  --no-create            Install tools but do not create the default AVD.
  --name NAME            Default AVD name (default: android-sim-play).
  --profile PROFILE      play, google, or aosp (default: play).
  --api LEVEL            Pin an Android API level; otherwise select the newest supported candidate.
  --ram-mb MB            Override automatically selected emulator RAM.
  --data-gb GB           AVD data partition size (default: 16).
  -h, --help             Show this help.

This script installs only first-party Android SDK packages plus Homebrew-managed
Python and Temurin Java. It does not download APKs from unofficial stores.
EOF
}

WITH_STUDIO=0
INSTALL_HOMEBREW=0
CREATE_AVD=1
AVD_NAME="android-sim-play"
PROFILE="play"
API_LEVEL=""
RAM_MB=""
DATA_GB="16"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-studio) WITH_STUDIO=1; shift ;;
    --install-homebrew) INSTALL_HOMEBREW=1; shift ;;
    --no-create) CREATE_AVD=0; shift ;;
    --name) AVD_NAME="${2:?--name requires a value}"; shift 2 ;;
    --profile) PROFILE="${2:?--profile requires a value}"; shift 2 ;;
    --api) API_LEVEL="${2:?--api requires a value}"; shift 2 ;;
    --ram-mb) RAM_MB="${2:?--ram-mb requires a value}"; shift 2 ;;
    --data-gb) DATA_GB="${2:?--data-gb requires a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This bootstrap script requires macOS." >&2
  exit 2
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This bootstrap is intentionally pinned to Apple Silicon (arm64)." >&2
  exit 2
fi
case "$PROFILE" in
  play|google|aosp) ;;
  *) echo "--profile must be play, google, or aosp" >&2; exit 2 ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}"
LOCAL_BIN="$HOME/.local/bin"
ZSHRC="$HOME/.zshrc"

if ! command -v brew >/dev/null 2>&1; then
  if [[ "$INSTALL_HOMEBREW" -ne 1 ]]; then
    cat >&2 <<'EOF'
Homebrew is required but was not found.
Install it from https://brew.sh, or re-run this script with --install-homebrew.
EOF
    exit 2
  fi
  echo "Installing Homebrew from the official installer..."
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi
fi

BREW_PREFIX="$(brew --prefix)"
eval "$(brew shellenv)"

PYTHON_OK=0
if command -v python3 >/dev/null 2>&1; then
  if python3 - <<'PYVERSION' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PYVERSION
  then
    PYTHON_OK=1
  fi
fi
if [[ "$PYTHON_OK" -ne 1 ]]; then
  brew install python
  hash -r
fi
PYTHON_BIN="$(command -v python3)"

if ! /usr/libexec/java_home -v 21 >/dev/null 2>&1; then
  brew install --cask temurin@21
fi
JAVA_HOME="$(/usr/libexec/java_home -v 21)"
export JAVA_HOME

if ! brew list --cask android-commandlinetools >/dev/null 2>&1; then
  brew install --cask android-commandlinetools
fi
if [[ "$WITH_STUDIO" -eq 1 ]] && ! brew list --cask android-studio >/dev/null 2>&1; then
  brew install --cask android-studio
fi

SDKMANAGER="$(command -v sdkmanager || true)"
if [[ -z "$SDKMANAGER" ]]; then
  SDKMANAGER="$BREW_PREFIX/bin/sdkmanager"
fi
if [[ ! -x "$SDKMANAGER" ]]; then
  echo "sdkmanager was not found after installing android-commandlinetools." >&2
  exit 2
fi

mkdir -p "$SDK_ROOT" "$LOCAL_BIN"
export ANDROID_SDK_ROOT="$SDK_ROOT"
export ANDROID_HOME="$SDK_ROOT"

# sdkmanager prompts on stdin. A terminated `yes` process is expected, so do not
# let pipefail turn its SIGPIPE into a bootstrap failure.
set +o pipefail
yes | "$SDKMANAGER" --sdk_root="$SDK_ROOT" --licenses >/dev/null
set -o pipefail

"$SDKMANAGER" --sdk_root="$SDK_ROOT" \
  "cmdline-tools;latest" \
  "platform-tools" \
  "emulator"

PYTHON_BIN="$PYTHON_BIN" "$REPO_ROOT/scripts/install-local.sh"

BEGIN_MARKER="# >>> android-simulator >>>"
END_MARKER="# <<< android-simulator <<<"
TMP_ZSHRC="$(mktemp)"
if [[ -f "$ZSHRC" ]]; then
  awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin {skip=1; next}
    $0 == end {skip=0; next}
    !skip {print}
  ' "$ZSHRC" > "$TMP_ZSHRC"
fi
cat >> "$TMP_ZSHRC" <<EOF
$BEGIN_MARKER
export ANDROID_SDK_ROOT="\${ANDROID_SDK_ROOT:-\$HOME/Library/Android/sdk}"
export ANDROID_HOME="\$ANDROID_SDK_ROOT"
export JAVA_HOME="\${JAVA_HOME:-\$(/usr/libexec/java_home -v 21 2>/dev/null)}"
export PATH="\$HOME/.local/bin:\$ANDROID_SDK_ROOT/emulator:\$ANDROID_SDK_ROOT/platform-tools:\$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:\$PATH"
$END_MARKER
EOF
mv "$TMP_ZSHRC" "$ZSHRC"

export PATH="$LOCAL_BIN:$SDK_ROOT/emulator:$SDK_ROOT/platform-tools:$SDK_ROOT/cmdline-tools/latest/bin:$PATH"

if [[ "$CREATE_AVD" -eq 1 ]]; then
  CREATE_ARGS=(create --name "$AVD_NAME" --profile "$PROFILE" --data-gb "$DATA_GB")
  if [[ -n "$API_LEVEL" ]]; then CREATE_ARGS+=(--api "$API_LEVEL"); fi
  if [[ -n "$RAM_MB" ]]; then CREATE_ARGS+=(--ram-mb "$RAM_MB"); fi
  android-sim "${CREATE_ARGS[@]}"
fi

cat <<EOF

Android simulator setup complete.

Open a new terminal, then run:
  android-sim doctor
  android-sim start "$AVD_NAME" --wifi-ssid "JadenAndroid" --wifi-password "change-this-password"

Install an APK:
  android-sim install ~/Downloads/app.apk

Open an official Play Store listing:
  android-sim play com.spotify.music
EOF
