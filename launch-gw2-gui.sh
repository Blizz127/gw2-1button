#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
exec /usr/bin/python3 ./gw2_1button_gui.py "$@"
