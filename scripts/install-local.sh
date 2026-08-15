#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_ROOT="${ANDROID_SIM_INSTALL_ROOT:-$HOME/.local/share/android-simulator}"
VENV="$STATE_ROOT/venv"
LOCAL_BIN="$HOME/.local/bin"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"

if ! "$PYTHON_BIN" - <<'PYVERSION' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PYVERSION
then
  echo "Python 3.10 or newer is required." >&2
  exit 2
fi

mkdir -p "$STATE_ROOT" "$LOCAL_BIN"
"$PYTHON_BIN" -m venv "$VENV"
SITE_PACKAGES="$("$VENV/bin/python" - <<'PY'
import site
paths = site.getsitepackages()
print(paths[0])
PY
)"
printf '%s\n' "$REPO_ROOT" > "$SITE_PACKAGES/android_simulator_repo.pth"

cat > "$VENV/bin/android-sim" <<EOF
#!$VENV/bin/python
from android_simulator.cli import main
raise SystemExit(main())
EOF
chmod +x "$VENV/bin/android-sim"
ln -sfn "$VENV/bin/android-sim" "$LOCAL_BIN/android-sim"

echo "Installed android-sim at $LOCAL_BIN/android-sim"
