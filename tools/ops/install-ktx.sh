#!/usr/bin/env bash
# УСТАНОВКА УТИЛИТЫ `ktx` (KTX-Software) БЕЗ SUDO (T-20261121-171/2). Нужна этапу 10 нового пути покраски (tools/scout/paint_web.py):
# раскодирует KTX2 из web.glb в PNG, чтобы сравнивать «полную» и «лёгкую» по НАСТОЯЩЕЙ текстуре. Нет утилиты — этап отказывает с причиной словами.
# Версия, адрес и контрольные суммы — только в tools/ops/ktx-release.json (не здесь). Ставит в install_dir из того же файла (по умолчанию ~/.local/opt/ktx-software),
# не в ~/remlab-logs (логи старше 7 суток уезжают на HDD). Путь к бинарю этап берёт из rules/paint-web.json (ktx_bin) или переменной KTX / PATH.
#   install-ktx.sh            установить (уже стоит та же версия — ничего не делает)
#   install-ktx.sh --check    только показать, стоит ли и какая версия (код 0 — стоит нужная)
#   install-ktx.sh --selftest проверка данных и логики без сети и без установки
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${KTX_RELEASE_JSON:-$HERE/ktx-release.json}"

field() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$DATA" "$1"; }

VERSION="$(field version)"; URL="$(field url)"; SHA1="$(field sha1)"; SHA256="$(field sha256)"; BIN="$(field binary)"
DIR="$(field install_dir)"; DIR="${DIR/#\~/$HOME}"
ARCHIVE="$(field archive)"

installed_version() {
  [ -x "$DIR/$BIN" ] || return 1
  [ -f "$DIR/.version" ] && cat "$DIR/.version" || return 1
}

case "${1:-}" in
  --selftest)
    [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "FAIL версия: $VERSION"; exit 1; }
    [[ "$SHA1" =~ ^[0-9a-f]{40}$ ]] || { echo "FAIL sha1"; exit 1; }
    [[ "$SHA256" =~ ^[0-9a-f]{64}$ ]] || { echo "FAIL sha256"; exit 1; }
    [[ "$URL" == https://github.com/KhronosGroup/KTX-Software/releases/download/v"$VERSION"/"$ARCHIVE" ]] || { echo "FAIL адрес не совпал с версией/архивом"; exit 1; }
    [[ "$DIR" != *remlab-logs* && "$DIR" == "$HOME"/* ]] || { echo "FAIL install_dir должен быть в домашней папке и не в remlab-logs: $DIR"; exit 1; }
    echo "install-ktx selftest ok"; exit 0 ;;
  --check)
    v="$(installed_version || true)"
    if [ "$v" = "$VERSION" ]; then echo "ktx $v стоит: $DIR/$BIN"; exit 0; fi
    echo "ktx ${v:-не стоит} (нужна $VERSION): запустить tools/ops/install-ktx.sh"; exit 1 ;;
  "") ;;
  *) echo "аргументы: (нет) | --check | --selftest"; exit 2 ;;
esac

if [ "$(installed_version || true)" = "$VERSION" ]; then echo "ktx $VERSION уже стоит: $DIR/$BIN"; exit 0; fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/install-ktx.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
echo "качаю $URL"
curl -fsSL -o "$TMP/$ARCHIVE" "$URL"
[ "$(sha1sum "$TMP/$ARCHIVE" | awk '{print $1}')" = "$SHA1" ] || { echo "sha1 архива не совпал — не ставлю"; exit 3; }
[ "$(sha256sum "$TMP/$ARCHIVE" | awk '{print $1}')" = "$SHA256" ] || { echo "sha256 архива не совпал — не ставлю"; exit 3; }
mkdir -p "$TMP/x"
tar -xjf "$TMP/$ARCHIVE" -C "$TMP/x" --strip-components=1
[ -x "$TMP/x/$BIN" ] || { echo "в архиве нет $BIN"; exit 4; }
"$TMP/x/$BIN" --version >/dev/null 2>&1 || { echo "ktx из архива не запускается"; exit 4; }
mkdir -p "$(dirname "$DIR")"
rm -rf "$DIR.new"
mv "$TMP/x" "$DIR.new"
echo "$VERSION" > "$DIR.new/.version"
rm -rf "$DIR.old"
[ -e "$DIR" ] && mv "$DIR" "$DIR.old"
mv "$DIR.new" "$DIR"
rm -rf "$DIR.old"
echo "ktx $VERSION поставлен: $DIR/$BIN"
