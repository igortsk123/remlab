#!/usr/bin/env bash
# Установка таймера учёта токенов (tokeny-mashiny/1) проекта в systemd --user этой машины (sudo не нужен).
#   tools/tokeny/postavit_taymer.sh vygruzka [--proba]   # на каждой машине: common, algor, pakardev
#   tools/tokeny/postavit_taymer.sh svodka   [--proba]   # одна машина (TOKENY_SVODKA_NA, по умолчанию common) — для отправки
# Юниты — tokeny-<вид>-<проект>.{service,timer}: у каждого проекта свои, проекты на машине не мешают друг другу.
# Время — TOKENY_VREMYA (ЧЧ:ММ по Лондону; по умолчанию выгрузка 07:30, сводка 07:50). Проекты — разводить по времени
# (выгрузка читает все журналы проекта): remlab 07:10, sup2-repo 07:20, tamara 07:30.
# Прежнее имя без проекта (tokeny-<вид>, так стояла tamara до кита) с тем же скриптом — считается установкой: второй
# таймер не ставится, сказано явно.
# --proba — проверки и разница с уже стоящими юнитами, без записи и без systemctl, меняющих состояние.
# Без --proba (после зелёной пробы): юниты из tools/tokeny/systemd/ с подставленными @REPO@, @PROEKT@, @VREMYA@ →
# ~/.config/systemd/user/, daemon-reload, enable --now <таймер>. Повторный запуск даёт тот же результат.
# Код: 0 — всё в порядке (или проба зелёная), 1 — проверка не прошла (ничего не поставлено), 2 — аргументы.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
KORNI="${TOKENY_PROEKTY:-/home/pakar/igor}"
PROEKT="${TOKENY_PROEKT:-$(basename "${REPO%%/.claude/worktrees/*}")}"  # подмена — для пробы из копии задачи
KANON="$KORNI/$PROEKT"
VID="${1:-}"
PROBA=0
[ "${2:-}" = "--proba" ] && PROBA=1
case "$VID" in
    vygruzka) VREMYA="${TOKENY_VREMYA:-07:30}" ;;
    svodka) VREMYA="${TOKENY_VREMYA:-07:50}" ;;
    *) echo "использование: postavit_taymer.sh vygruzka|svodka [--proba]" >&2; exit 2 ;;
esac
[ $# -le 2 ] && { [ $# -lt 2 ] || [ "$PROBA" = 1 ]; } || { echo "лишние аргументы: $*" >&2; exit 2; }
[[ "$VREMYA" =~ ^[0-2][0-9]:[0-5][0-9]$ ]] || { echo "TOKENY_VREMYA — ЧЧ:ММ, а не «$VREMYA»" >&2; exit 2; }
SHABLON="tokeny-$VID"
IMYA="tokeny-$VID-$PROEKT"
ISTOCHNIK="$REPO/tools/tokeny/systemd"
CEL="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
NA_SVODKU="${TOKENY_SVODKA_NA:-common}"
oshibok=0
ok() { echo "  ок: $*"; }
ploho() { echo "  НЕТ: $*"; oshibok=$((oshibok + 1)); }
podstavit() { sed -e "s|@REPO@|$KANON|g" -e "s|@PROEKT@|$PROEKT|g" -e "s|@VREMYA@|$VREMYA|g" "$1"; }

echo "машина $(hostname), пользователь $(id -un), проект $PROEKT, дерево $KANON, таймер $IMYA.timer"
echo "проверки:"
if [ "$REPO" = "$KANON" ]; then
    ok "дерево $REPO (юниты получат этот путь)"
elif [ "$PROBA" = 1 ]; then
    echo "  внимание: копия $REPO — юниты получат путь $KANON; ставить из него после вливания"
else
    ploho "ставить только из $KANON, а не из $REPO: юниты запускали бы скрипт каноничного дерева, а проверен этот"
fi
if python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    ok "python3 $(python3 -c 'import platform; print(platform.python_version())')"
else
    ploho "python3 ≥ 3.12 не найден"
fi
skript="tools/tokeny/$([ "$VID" = vygruzka ] && echo vygruzit.sh || echo svodka.sh)"
[ -x "$KANON/$skript" ] && ok "скрипт $KANON/$skript" || ploho "нет исполняемого $KANON/$skript"
for u in service timer; do
    [ -f "$ISTOCHNIK/$SHABLON.$u" ] || ploho "нет $ISTOCHNIK/$SHABLON.$u"
done
if [ "$VID" = vygruzka ]; then
    zh="$HOME/.claude/projects/$(printf '%s' "$KANON" | sed 's/[^A-Za-z0-9]/-/g')"
    [ -d "$zh" ] && ok "журналы $zh ($(find "$zh" -maxdepth 1 -name '*.jsonl' | wc -l) сессий)" \
        || ploho "нет журналов $zh"
    papka="$KANON/data/logs/tokeny"
    [ -f "$HOME/.claude/usage-log.jsonl" ] && ok "журнал недели ~/.claude/usage-log.jsonl" \
        || echo "  внимание: нет ~/.claude/usage-log.jsonl — % недели этой учётки в сводке будет «нет замера»"
else
    [ "$(hostname)" = "$NA_SVODKU" ] && ok "машина $NA_SVODKU" || ploho "сводку ставим только на $NA_SVODKU, а это $(hostname)"
    papka="$KANON/data/otchety/tokeny"
fi
p="$papka"
while [ ! -e "$p" ] && [ "$p" != / ]; do p="$(dirname "$p")"; done
[ -d "$p" ] && [ -w "$p" ] && ok "запись в $papka (проверено на $p)" || ploho "нет записи в $papka"
systemctl --user show-environment >/dev/null 2>&1 && ok "systemd --user доступен" || ploho "systemd --user недоступен"
[ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" = yes ] && ok "linger=yes" \
    || ploho "linger не включён — таймер не сработает без входа пользователя"
kalendar="$(podstavit "$ISTOCHNIK/$SHABLON.timer" 2>/dev/null | sed -n 's/^OnCalendar=//p')"
if sled="$(systemd-analyze calendar "$kalendar" 2>/dev/null | sed -n 's/^ *Next elapse: *//p')" && [ -n "$sled" ]; then
    ok "расписание «$kalendar», следующий запуск: $sled"
else
    ploho "systemd не разобрал расписание «$kalendar»"
fi

staryy="$(systemctl --user cat "$SHABLON.service" 2>/dev/null | sed -n 's/^ExecStart=//p')"
if [ "$staryy" = "$KANON/$skript" ] && [ "$(systemctl --user is-enabled "$SHABLON.timer" 2>/dev/null)" = enabled ]; then
    echo "юниты: уже стоит $SHABLON.timer (прежнее имя, без проекта) с тем же скриптом — второй таймер не ставлю"
    systemctl --user list-timers "$SHABLON.timer" --no-pager
    [ "$oshibok" -gt 0 ] && { echo "проверка не прошла ($oshibok)"; exit 1; }
    exit 0
fi

echo "юниты в $CEL:"
for u in service timer; do
    novyy="$(podstavit "$ISTOCHNIK/$SHABLON.$u" 2>/dev/null)"
    if [ ! -f "$CEL/$IMYA.$u" ]; then
        echo "  $IMYA.$u — новый:"
        printf '%s\n' "$novyy" | sed 's/^/    /'
    elif [ "$novyy" = "$(cat "$CEL/$IMYA.$u")" ]; then
        echo "  $IMYA.$u — без изменений"
    else
        echo "  $IMYA.$u — изменится:"
        diff -u "$CEL/$IMYA.$u" <(printf '%s\n' "$novyy") | sed 's/^/    /'
    fi
done
sostoyanie="$(systemctl --user is-enabled "$IMYA.timer" 2>/dev/null)"
echo "  $IMYA.timer сейчас: ${sostoyanie:-не установлен}"

if [ "$oshibok" -gt 0 ]; then
    echo "проверка не прошла ($oshibok) — ничего не ставлю"
    exit 1
fi
if [ "$PROBA" = 1 ]; then
    echo "проба: всё в порядке; ничего не записано"
    exit 0
fi
mkdir -p "$CEL" || exit 1
for u in service timer; do
    podstavit "$ISTOCHNIK/$SHABLON.$u" > "$CEL/$IMYA.$u.tmp" && mv -f -- "$CEL/$IMYA.$u.tmp" "$CEL/$IMYA.$u" \
        || { echo "не записан $CEL/$IMYA.$u" >&2; exit 1; }
done
systemctl --user daemon-reload || exit 1
systemctl --user enable --now "$IMYA.timer" || exit 1
systemctl --user list-timers "$IMYA.timer" --no-pager
