#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -m compileall -q android_simulator
python3 -m unittest discover -s tests -v
python3 -m android_simulator --help >/dev/null
