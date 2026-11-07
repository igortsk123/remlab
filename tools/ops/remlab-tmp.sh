# ВРЕМЕННЫЕ ФАЙЛЫ КОНВЕЙЕРА — НА ДИСК, НЕ В /tmp (T-20261107-02). /tmp на DEV — tmpfs с квотой на пользователя (~788 МБ), его
# забивают чужие проекты и временные папки сессий; ночью 07.11 шаг лёгких копий /rt/ упал на EDQUOT, и демо не опубликовалось.
# Подключать через `.`: задаёт REMLAB_TMP (по умолчанию ~/remlab-scratch/tmp), создаёт папку, экспортирует. TMPDIR не меняет —
# это делает тот, кому нужно, чтобы python/node внутри тоже не писали в /tmp (`refresh_daily.sh`).
# В CI (T-20261107-13) без REMLAB_TMP — системная временная папка раннера (RUNNER_TEMP), как у python-помощника
# `tools/scout/remlab_tmp.py` (то же правило: REMLAB_TMP → ~/remlab-scratch/tmp → в CI системная).
# Свои файлы каждый скрипт убирает сам (trap); для папки — `remlab_tmp_dir` + `remlab_tmp_trap` ниже.
# Чистка забытого — `tools/ops/tmp-sweep.sh` (те же шаблоны, что в /tmp, и папки rt-* python-помощника).
if [ -z "${REMLAB_TMP:-}" ] && [ -n "${CI:-}${GITHUB_ACTIONS:-}" ] && [ -n "${RUNNER_TEMP:-}" ]; then
  REMLAB_TMP=$RUNNER_TEMP
fi
REMLAB_TMP=${REMLAB_TMP:-$HOME/remlab-scratch/tmp}
mkdir -p "$REMLAB_TMP"
export REMLAB_TMP
# свободно, МБ (для строки в лог): remlab_tmp_free <папка>
remlab_tmp_free() { df -Pm "$1" 2>/dev/null | awk 'NR==2{print $4}'; }
# своя папка: T=$(remlab_tmp_dir <имя>) → $REMLAB_TMP/<имя>.XXXXXX
remlab_tmp_dir() { mktemp -d "$REMLAB_TMP/$1.XXXXXX"; }
# уборка папки при выходе скрипта (вызывать в самом скрипте, не в подоболочке): код 0 — удалить; иначе или REMLAB_KEEP_TMP=1 —
# оставить и напечатать путь (разбор провала). Свой trap EXIT у скрипта этим заменяется — общий trap на выход один.
remlab_tmp_trap() {
  REMLAB_TMP_OWNED=$1
  case "$1" in "$REMLAB_TMP"/?*) ;; *) echo "remlab_tmp_trap: $1 — не внутри $REMLAB_TMP, уборку не ставлю" >&2; return 1 ;; esac
  trap '_rc=$?; if [ "$_rc" = 0 ] && [ "${REMLAB_KEEP_TMP:-0}" = 0 ]; then rm -rf -- "$REMLAB_TMP_OWNED"; else echo "временная папка оставлена: $REMLAB_TMP_OWNED" >&2; fi' EXIT
}
