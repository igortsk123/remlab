# ВРЕМЕННЫЕ ФАЙЛЫ КОНВЕЙЕРА — НА ДИСК, НЕ В /tmp (T-20261107-02). /tmp на DEV — tmpfs с квотой на пользователя (~788 МБ), его
# забивают чужие проекты и временные папки сессий; ночью 07.11 шаг лёгких копий /rt/ упал на EDQUOT, и демо не опубликовалось.
# Подключать через `.`: задаёт REMLAB_TMP (по умолчанию ~/remlab-scratch/tmp), создаёт папку, экспортирует. TMPDIR не меняет —
# это делает тот, кому нужно, чтобы python/node внутри тоже не писали в /tmp (`refresh_daily.sh`).
# Свои файлы каждый скрипт убирает сам (trap); чистка забытого — `tools/ops/tmp-sweep.sh` (те же шаблоны, что в /tmp).
REMLAB_TMP=${REMLAB_TMP:-$HOME/remlab-scratch/tmp}
mkdir -p "$REMLAB_TMP"
export REMLAB_TMP
# свободно, МБ (для строки в лог): remlab_tmp_free <папка>
remlab_tmp_free() { df -Pm "$1" 2>/dev/null | awk 'NR==2{print $4}'; }
