#!/usr/bin/env bash
# Еженедельная сверка книги о продукте с кодом советником (book-memory-sync п.4, правило codex-adviser: дёшево — vercel-sol).
# Отчёт — `.memory_bank/_intake/codex/book-check-<дата>.md`; расхождения правит агент при своде памяти (/memory-check).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
OUT=".memory_bank/_intake/codex/book-check-$(date +%F).md"
P=$(mktemp)
cat > "$P" <<'TXT'
Сверь книгу `.memory_bank/guides/product-book.md` с кодом репозитория. Книга — идеал «после правок» плюс абзацы «Сегодня»
(как сейчас). Проверяй ТОЛЬКО абзацы «Сегодня» и имена файлов/функций в скобках: существует ли, верно ли описано текущее
поведение. Верни таблицу «абзац (глава) → что сказано → что в коде (файл:строка) → верно/неверно», в конце число
расхождений. Кратко, по-русски. Ничего не правь.
TXT
export PATH="$HOME/.local/bin:$PATH"   # крон не видит ~/.local/bin, где лежит codex
set -a; . tools/scout/.env 2>/dev/null; set +a
if codex exec --profile vercel-sol --ephemeral --sandbox read-only -C "$PWD" -o "$OUT" - < "$P" > /dev/null 2>&1; then
  echo "сверка книги: отчёт $OUT"
else
  echo "WARN:book_check: советник не ответил — сверка книги пропущена"
fi
rm -f "$P"
