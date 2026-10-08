#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "$0")/.." && pwd)"
stage="${DESTDIR:-}"
backend_root='/opt/zapret-discord-youtube-linux'
unit='zapret_discord_youtube.service'
configure=false
while (( $# )); do
    case "$1" in
        --backend-root) backend_root="${2:?Укажи каталог адаптера}"; configure=true; shift 2 ;;
        --service) unit="${2:?Укажи имя сервиса с .service}"; configure=true; shift 2 ;;
        *) echo "Неизвестный параметр: $1" >&2; exit 1 ;;
    esac
done
if [[ -z "$stage" ]] && (( EUID != 0 )); then
    echo 'Установка: sudo bash scripts/install.sh' >&2
    exit 1
fi
if [[ -z "$stage" ]]; then
    for tool in python3 whiptail curl ip systemctl sudo; do
        command -v "$tool" >/dev/null || { echo "Не найдена зависимость: $tool. См. README.md" >&2; exit 1; }
    done
    [[ -f "$backend_root/conf.env" && -x "$backend_root/nfqws" ]] || {
        echo "Сначала установи и настрой zapret-discord-youtube-linux: $backend_root" >&2
        exit 1
    }
fi
lib="$stage/usr/local/lib/zapret-console"
[[ ! -L "$lib" ]] || { echo 'Каталог приложения не должен быть символической ссылкой' >&2; exit 1; }
install -d -m 0755 "$lib/zapret_console" "$stage/usr/local/bin" "$stage/etc/zapret-console" "$stage/var/lib/zapret-console"
for file in "$source_dir"/src/zapret_console/*.py; do
    install -m 0644 "$file" "$lib/zapret_console/"
done
cat > "$stage/usr/local/bin/zapret-console" <<'LAUNCHER'
#!/usr/bin/python3 -I
import sys
sys.path.insert(0, '/usr/local/lib/zapret-console')
from zapret_console.app import entrypoint
entrypoint()
LAUNCHER
chmod 0755 "$stage/usr/local/bin/zapret-console"
settings="$stage/etc/zapret-console/settings.json"
if [[ ! -f "$settings" ]] || [[ "$configure" == true ]]; then
    python3 - "$settings" "$backend_root" "$unit" <<'PY'
import json, re, sys
from pathlib import Path
dest, root, unit = sys.argv[1:]
if not Path(root).is_absolute() or not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', unit):
    raise SystemExit('Некорректный путь адаптера или имя сервиса')
Path(dest).write_text(json.dumps({'backend_root': root, 'service': unit}, indent=2) + '\n')
Path(dest).chmod(0o644)
PY
fi
if [[ -z "$stage" ]]; then
    /usr/local/bin/zapret-console --doctor
    /usr/local/bin/zapret-console --status
    if [[ ! -f /var/lib/zapret-console/known-good.json ]]; then
        /usr/local/bin/zapret-console --admin save-good
    fi
    echo 'Установлено. Запуск: zapret-console'
else
    echo "Файлы установлены в staging-каталог: $stage"
fi
