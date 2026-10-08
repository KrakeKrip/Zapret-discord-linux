#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "$0")/.." && pwd)"
if ! command -v python3 >/dev/null; then
    if [[ " $* " == *' --dry-run '* ]]; then
        echo 'План: установить Python 3, затем запустить мастер. Изменений не выполнено.'
        exit 0
    fi
    if (( EUID != 0 )); then
        echo 'Для установки Python запусти: sudo bash scripts/setup.sh' >&2
        exit 1
    fi
    command -v apt-get >/dev/null || { echo 'Для мастера нужен Python 3 и Ubuntu/Debian' >&2; exit 1; }
    apt-get update
    apt-get install -y python3
fi
export PYTHONPATH="$source_dir/src"
exec python3 -m zapret_console.setup "$@"
