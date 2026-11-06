#!/usr/bin/env bash
# НУЖНА ЛИ ВЫКЛАДКА (T-20261106-66/2). Каждый зелёный push в main пересоздавал app/draft — и коммит только памяти
# тоже: 60 перезапусков сайта за сутки 05–06.11, в каждом 5–10 с ответов 502. Решение: сравнить ДЕРЕВО выкатанной
# версии (/api/health → version) с целевым коммитом; если различаются только пути из белого списка — выкладку
# пропустить. Сравниваем с тем, что РЕАЛЬНО на проде, а не с прошлым коммитом: отменённый в очереди прогон с кодом
# не потеряется — его изменения попадут в разницу следующего.
# Любое сомнение (версия не читается, кадры на другой версии, коммита нет, diff упал) → выкладка как раньше.
#
#   deploy-need.sh <TARGET_SHA>   — решение для deploy.yml: stdout «deploy=true|false», причина — в stderr;
#                                   в CI дописывает $GITHUB_OUTPUT и $GITHUB_STEP_SUMMARY
#   deploy-need.sh --status       — прод позади main? (сверка вместо «version == HEAD main»: после пропуска
#                                   прод законно стоит на последнем КОДОВОМ коммите)
#   deploy-need.sh --selftest     — сухой прогон на списках путей и временном репозитории (CI)
set -uo pipefail
SITE=${SITE:-https://remont-lab.online}

# БЕЛЫЙ СПИСОК — только то, что не попадает ни в образ app/draft, ни на сервер (deploy.yml копирует compose,
# db/init, infra/server/*, tools/apply-db-init.sh, caddy/Caddyfile). Корневые *.md отсекает .dockerignore.
# tools/, tests/, e2e/, .github/ сюда НЕ входят: draft копирует tools/scout/*, сервер — tools/apply-db-init.sh.
SKIP_RE='^(\.memory_bank/|docs/|\.claude/|\.vscode/|[^/]+\.md$)'

# stdin — список путей; 0 = все из белого списка (пустой список — деревья равны — тоже 0)
docs_only() {
  local f
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    [[ "$f" =~ $SKIP_RE ]] || { FIRST_CODE=$f; return 1; }
  done
  return 0
}

ver_of() { sed -n 's/.*"version": *"\([0-9a-f]\{40\}\)".*/\1/p' | head -1; }

# $1 — целевой коммит. stdout: «skip <версия прода>» | «deploy <причина>»
decide() {
  local target=$1 app_h draft_h app drv files
  app_h=${HEALTH_JSON-$(curl -s --max-time 10 "$SITE/api/health" || true)}
  draft_h=${DRAFT_JSON-$(curl -s --max-time 10 "$SITE/api/draft/health" || true)}
  app=$(printf '%s' "$app_h" | ver_of); drv=$(printf '%s' "$draft_h" | ver_of)
  [ -n "$app" ] || { echo "deploy версия сайта не читается"; return; }
  printf '%s' "$app_h" | grep -q '"ok":true' || { echo "deploy сайт не здоров (ok≠true)"; return; }
  [ "$drv" = "$app" ] || { echo "deploy кадры на другой версии (${drv:0:12}) — выкладка их выровняет"; return; }
  [ "$app" != "$target" ] || { echo "deploy прод уже на целевой версии — повторный запуск, выкладываем как просили"; return; }
  git cat-file -e "$app^{commit}" 2>/dev/null || git fetch -q --depth=1 origin "$app" 2>/dev/null \
    || { echo "deploy коммит прода ${app:0:12} не нашёлся"; return; }
  git cat-file -e "$target^{commit}" 2>/dev/null || { echo "deploy целевой коммит не найден"; return; }
  # --no-renames: перенос app/x → docs/x должен показать и удаление из app/, иначе «только docs» и пропуск
  files=$(git diff --no-renames --name-only "$app" "$target" 2>/dev/null) || { echo "deploy сравнение не удалось"; return; }
  FIRST_CODE=""
  if docs_only <<<"$files"; then echo "skip $app"; else echo "deploy изменён код: $FIRST_CODE"; fi
}

selftest() {
  local fail=0 t
  ok_() { echo "  ok: $1"; }
  bad() { echo "  FAIL: $1" >&2; fail=1; }
  check_list() { # $1 ожидание 0|1, $2 подпись, stdin список
    if docs_only; then r=0; else r=1; fi
    [ "$r" = "$1" ] && ok_ "$2" || bad "$2 (получили $r, ждали $1)"
  }
  printf '.memory_bank/plans/x.md\ndocs/a.md\n.claude/rules/r.md\nCLAUDE.md\n' | check_list 0 "только память/доки/правила"
  printf '' | check_list 0 "пустой список (деревья равны)"
  printf '.memory_bank/x.md\napp/page.tsx\n' | check_list 1 "память + код"
  printf 'app/README.md\n' | check_list 1 "md не в корне — не пропуск"
  printf 'docs2/a.md\n' | check_list 1 "похожий префикс docs2/"
  printf '.memory_bank_x/a\n' | check_list 1 "похожий префикс .memory_bank_x/"
  printf 'tools/scout/draft_service.py\n' | check_list 1 "tools/ (попадает в образ кадров)"
  printf 'caddy/Caddyfile\n' | check_list 1 "Caddyfile (едет на сервер)"
  printf '.github/workflows/deploy.yml\n' | check_list 1 ".github/"

  t=$(mktemp -d); trap 'rm -rf "$t"' RETURN
  (
    cd "$t" && git init -q && git config user.email t@t && git config user.name t
    mkdir -p app docs .memory_bank && echo a > app/x.ts && echo d > docs/d.md && git add . && git commit -qm c1
    echo m > .memory_bank/m.md && git add . && git commit -qm docs
    git mv app/x.ts docs/x.ts && git commit -qm moved
    echo 2 > app/y.ts && git add . && git commit -qm code
  ) >/dev/null
  local c1 c2 c3 c4 r
  c1=$(git -C "$t" rev-parse HEAD~3); c2=$(git -C "$t" rev-parse HEAD~2); c3=$(git -C "$t" rev-parse HEAD~1); c4=$(git -C "$t" rev-parse HEAD)
  h() { printf '{"ok":true,"version":"%s"}' "$1"; }
  dj() { printf '{"ok": true, "version": "%s"}' "$1"; }
  run() { (cd "$t" && HEALTH_JSON=$1 DRAFT_JSON=$2 decide "$3"); }
  expect() { case "$1" in "$2"*) ok_ "$3 → $1";; *) bad "$3 → «$1», ждали «$2…»";; esac; }
  expect "$(run "$(h "$c1")" "$(dj "$c1")" "$c2")" "skip $c1" "прод c1, цель — коммит памяти"
  expect "$(run "$(h "$c1")" "$(dj "$c1")" "$c3")" "deploy изменён код: app/x.ts" "перенос app→docs (без детекта переименований)"
  expect "$(run "$(h "$c2")" "$(dj "$c2")" "$c4")" "deploy изменён код" "прод отстал на кодовый коммит (отменённый прогон в очереди)"
  expect "$(run "" "$(dj "$c1")" "$c2")" "deploy версия сайта не читается" "сайт не ответил"
  expect "$(run '{"ok":true,"version":"prev"}' "$(dj "$c1")" "$c2")" "deploy версия сайта не читается" "откат на :prev"
  expect "$(run '{"ok":false,"version":"'"$c1"'"}' "$(dj "$c1")" "$c2")" "deploy сайт не здоров" "ok=false"
  expect "$(run "$(h "$c1")" "$(dj "$c2")" "$c2")" "deploy кадры на другой версии" "кадры отстали"
  expect "$(run "$(h "$c2")" "$(dj "$c2")" "$c2")" "deploy прод уже на целевой" "повторный запуск"
  expect "$(run "$(h "$(printf 'a%.0s' {1..40})")" "$(dj "$(printf 'a%.0s' {1..40})")" "$c2")" "deploy коммит прода" "коммита прода нет"
  [ "$fail" = 0 ] && { echo "deploy-need selftest ok"; return 0; }
  echo "deploy-need selftest FAIL" >&2; return 1
}

case "${1:-}" in
  --selftest) selftest; exit $? ;;
  --status)
    git fetch -q origin main 2>/dev/null || true
    main=$(git rev-parse origin/main 2>/dev/null) || { echo "нет origin/main"; exit 2; }
    d=$(decide "$main")
    case "$d" in
      "skip "*) echo "прод не позади main: на ${d#skip }, до main ${main:0:12} — только документы/память"; exit 0 ;;
      "deploy прод уже на целевой"*) echo "прод не позади main: на ${main:0:12}"; exit 0 ;;
      *) echo "прод ПОЗАДИ main ${main:0:12}: ${d#deploy }"; exit 1 ;;
    esac ;;
  ""|-*) echo "usage: deploy-need.sh <TARGET_SHA> | --status | --selftest" >&2; exit 2 ;;
  *)
    d=$(decide "$1")
    case "$d" in
      "skip "*) need=false; why="на проде ${d#skip }, до ${1:0:12} изменены только документы/память — app и draft не пересоздаём" ;;
      *) need=true; why=${d#deploy } ;;
    esac
    echo "deploy=$need"; echo "выкладка: $need — $why" >&2
    [ -n "${GITHUB_OUTPUT:-}" ] && echo "deploy=$need" >> "$GITHUB_OUTPUT"
    [ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo "**Выкладка: $need** — $why" >> "$GITHUB_STEP_SUMMARY"
    [ "$need" = false ] && echo "::notice title=Выкладка пропущена::$why"
    exit 0 ;;
esac
