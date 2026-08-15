#!/usr/bin/env bash
set -euo pipefail

VENV="$HOME/.local/share/android-simulator/venv"
CLI="$HOME/.local/bin/android-sim"
ZSHRC="$HOME/.zshrc"
BEGIN_MARKER="# >>> android-simulator >>>"
END_MARKER="# <<< android-simulator <<<"

rm -f "$CLI"
rm -rf "$VENV"

if [[ -f "$ZSHRC" ]]; then
  tmp="$(mktemp)"
  awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin {skip=1; next}
    $0 == end {skip=0; next}
    !skip {print}
  ' "$ZSHRC" > "$tmp"
  mv "$tmp" "$ZSHRC"
fi

cat <<'EOF'
Removed the android-sim CLI and its shell environment block.
Android SDK packages and AVD data were intentionally preserved.
To remove those too, delete ~/Library/Android/sdk and ~/.android/avd manually.
EOF
