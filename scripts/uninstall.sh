#!/usr/bin/env bash
set -euo pipefail
stage="${DESTDIR:-}"
if [[ -z "$stage" ]] && (( EUID != 0 )); then
    echo 'Удаление: sudo bash scripts/uninstall.sh' >&2
    exit 1
fi
lib="$stage/usr/local/lib/zapret-console"
[[ ! -L "$lib" ]] || { echo 'Каталог приложения является ссылкой; остановлено' >&2; exit 1; }
if [[ -d "$lib" ]]; then
    rm -r -- "$lib"
fi
rm -f -- "$stage/usr/local/bin/zapret-console"
echo 'Меню удалено. Адаптер, сервис, конфигурация и сохранённые профили оставлены на месте.'
