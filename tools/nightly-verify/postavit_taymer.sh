#!/usr/bin/env bash
# Установка таймера ночной сверки памяти проекта в systemd --user этой машины (sudo не нужен).
#   tools/nightly-verify/postavit_taymer.sh --proba   # проверки и юниты, которые были бы поставлены; ничего не пишет
#   tools/nightly-verify/postavit_taymer.sh           # после зелёной пробы: юниты → ~/.config/systemd/user, enable --now
# Юниты — nightly-verify-<проект>.{service,timer}; время — NIGHTLY_VREMYA (ЧЧ:ММ по Лондону, по умолчанию 03:30;
# разводить с другими ночными задачами машины). Ставить из основной копии проекта: юниты получают её путь.
# Код: 0 — всё в порядке (или проба зелёная), 1 — проверка не прошла (ничего не поставлено), 2 — аргументы.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PROBA=0
case "${1:-}" in
    --proba) PROBA=1 ;;
    "") ;;
    *) echo "использование: postavit_taymer.sh [--proba]" >&2; exit 2 ;;
esac
VREMYA="${NIGHTLY_VREMYA:-03:30}"
[[ "$VREMYA" =~ ^[0-2][0-9]:[0-5][0-9]$ ]] || { echo "NIGHTLY_VREMYA — ЧЧ:ММ, а не «$VREMYA»" >&2; exit 2; }
COMMON="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || { echo "$REPO — не git" >&2; exit 1; }
KANON="$(dirname "$COMMON")"            # основная копия: её .git — общий git-dir всех worktree
PROEKT="${NIGHTLY_PROEKT:-$(basename "$KANON")}"
IMYA="nightly-verify-$PROEKT"
ISTOCHNIK="$REPO/tools/nightly-verify/systemd"
CEL="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
NODE="$(command -v node || true)"
# PATH для юнита: текущий без повторов и без путей сессии VS Code (`.vscode-server/…` меняется с каждой версией)
PUT="$(printf '%s' "$PATH" | tr ':' '\n' | grep -v '/\.vscode-server/' | awk 'NF && !seen[$0]++' | paste -sd: -)"
oshibok=0
ok() { echo "  ок: $*"; }
ploho() { echo "  НЕТ: $*"; oshibok=$((oshibok + 1)); }
podstavit() {
    sed -e "s|@REPO@|$KANON|g" -e "s|@PROEKT@|$PROEKT|g" -e "s|@VREMYA@|$VREMYA|g" -e "s|@NODE@|$NODE|g" -e "s|@PATH@|$PUT|g" "$1"
}

echo "машина $(hostname), пользователь $(id -un), проект $PROEKT, основная копия $KANON, таймер $IMYA.timer"
echo "проверки:"
if [ "$REPO" = "$KANON" ]; then
    ok "дерево $REPO (юниты получат этот путь)"
elif [ "$PROBA" = 1 ]; then
    echo "  внимание: копия $REPO — юниты получат путь $KANON; ставить оттуда после вливания"
else
    ploho "ставить только из $KANON, а не из $REPO: юниты запускали бы скрипт основной копии, а проверен этот"
fi
if [ -n "$NODE" ] && "$NODE" -e 'process.exit(Number(process.versions.node.split(".")[0]) < 20 ? 1 : 0)'; then
    ok "node $("$NODE" --version) ($NODE)"
else
    ploho "node ≥ 20 не найден"
fi
command -v claude >/dev/null 2>&1 && ok "claude $(claude --version 2>/dev/null | head -1) ($(command -v claude))" || ploho "claude не найден в PATH"
command -v flock >/dev/null 2>&1 && ok "flock" || ploho "нет flock (util-linux) — два прогона могли бы пересечься"
for f in tools/nightly-verify/nightly-verify.mjs tools/memory-impact.mjs tools/memory-audit.mjs tools/memory-health.mjs .claude/agents/verify.md; do
    [ -f "$KANON/$f" ] && ok "$f" || ploho "нет $KANON/$f (кит ≥ 1.11 и модуль nightly-verify в основной копии)"
done
[ -f "$KANON/.memory_bank/_kit/nightly-verify.conf" ] && ok "конфиг .memory_bank/_kit/nightly-verify.conf" \
    || echo "  внимание: нет .memory_bank/_kit/nightly-verify.conf — значения по умолчанию (2 дока, 60 утверждений)"
# как в nightly-verify.mjs:readConfig — «#» после пробела = комментарий до конца строки
remote="$(sed -n -e 's/\(^\|[[:space:]]\)#.*$//' -e 's/[[:space:]]*$//' -e 's/^remote *= *//p' "$KANON/.memory_bank/_kit/nightly-verify.conf" 2>/dev/null | tail -1)"
git -C "$KANON" remote get-url "${remote:-origin}" >/dev/null 2>&1 && ok "remote ${remote:-origin}" || ploho "нет remote ${remote:-origin}"
for u in service timer; do
    [ -f "$ISTOCHNIK/nightly-verify.$u" ] || ploho "нет $ISTOCHNIK/nightly-verify.$u"
done
systemctl --user show-environment >/dev/null 2>&1 && ok "systemd --user доступен" || ploho "systemd --user недоступен"
[ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" = yes ] && ok "linger=yes" \
    || ploho "linger не включён — таймер не сработает без входа пользователя"
kalendar="$(podstavit "$ISTOCHNIK/nightly-verify.timer" 2>/dev/null | sed -n 's/^OnCalendar=//p')"
if sled="$(systemd-analyze calendar "$kalendar" 2>/dev/null | sed -n 's/^ *Next elapse: *//p')" && [ -n "$sled" ]; then
    ok "расписание «$kalendar», следующий запуск: $sled"
else
    ploho "systemd не разобрал расписание «$kalendar»"
fi

if [ "$PROBA" = 1 ]; then
    for u in service timer; do
        echo "--- $CEL/$IMYA.$u (было бы записано):"
        podstavit "$ISTOCHNIK/nightly-verify.$u"
        if [ -f "$CEL/$IMYA.$u" ]; then
            diff -q <(podstavit "$ISTOCHNIK/nightly-verify.$u") "$CEL/$IMYA.$u" >/dev/null && echo "  (совпадает с поставленным)" || echo "  (отличается от поставленного)"
        fi
    done
    [ "$oshibok" = 0 ] && echo "проба: всё в порядке; поставить — без --proba из $KANON" || echo "проба: проблем $oshibok"
    [ "$oshibok" = 0 ]
    exit $?
fi
[ "$oshibok" = 0 ] || { echo "не ставлю: проблем $oshibok"; exit 1; }
mkdir -p "$CEL"
for u in service timer; do podstavit "$ISTOCHNIK/nightly-verify.$u" > "$CEL/$IMYA.$u"; done
systemctl --user daemon-reload
systemctl --user enable --now "$IMYA.timer"
systemctl --user list-timers "$IMYA.timer" --no-pager
echo "поставлено: $IMYA.timer; прогон руками — systemctl --user start $IMYA.service; журнал — journalctl --user -u $IMYA.service"
