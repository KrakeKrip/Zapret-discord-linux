#!/usr/bin/env bash
set -euo pipefail
umask 022
source_dir="$(cd -- "$(dirname -- "$0")/.." && pwd)"
exec /usr/bin/python3 -I "$source_dir/scripts/install.py" --uninstall "$@"
