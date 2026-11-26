---
title: Хук против heredoc/herestring в Bash агентов
tier: 3
topic: Хук против heredoc/herestring в Bash агентов (python, работает и на algor)
scope: tools/hooks/guard_heredoc.py, tools/hooks/guard_heredoc_test.py, .claude/settings.json (строку добавляет директор)
status: in_progress
updated: 2026-11-26
owner_word: TG 3014 ❓2 → TG 3015–3017 «мелкие вопросы не задавать, жду результат» (26.11)
---

# Хук против heredoc в Bash

## Зачем
heredoc/herestring в Bash запрещены правилом директора 25.11 (их тело не видит ни разбор команд, ни гард конвейера,
и правки файлов уходят мимо Write). За 25–26.11 нарушений 31 у трёх рабочих — словами не держится. Хук guard-bash.mjs
на algor молчит (нет node), поэтому проверка — на python, как guard_conveyor.py.

## Правило
- Bash-команда содержит heredoc (`<<WORD`, `<<-WORD`, `<<'WORD'`, `<<"WORD"`) или herestring (`<<<`) вне кавычек → срабатывание.
- Не срабатывает: `<<` внутри строки в кавычках, арифметика `$(( a << 2 ))`, текст после `#`.
- Режим из `tools/hooks/guard-heredoc.json`: `"mode": "warn"` — выход 0 + предупреждение в stderr; `"block"` — выход 2, причина
  и подсказка: «файл — инструментом Write, в Bash только запуск; короткий текст — printf; коммит — git commit -m».
- С 26.11 — warn сутки, затем директор ставит block (одна строка в json). fail-open: своя ошибка → выход 0.
- Каждое срабатывание — строка в `~/.local/state/remlab/heredoc-guard.log` (время, сессия, первые 80 символов команды).

## Шаги
1. `guard_heredoc.py` + `guard-heredoc.json` + `guard_heredoc_test.py` (не менее 12 случаев: 5 видов heredoc, herestring,
   кавычки, арифметика, комментарий, пустой ввод, битый JSON, режимы warn/block).
2. Тест — в job CI рядом с `guard_conveyor_test.py` (`.github/workflows/ci.yml`).
3. Строку в `.claude/settings.json` (PreToolUse, matcher Bash) добавляет ДИРЕКТОР после приёмки (рабочий `.claude/` не трогает).

## Конвейер (4 строки)
- Вход: JSON PreToolUse (tool_input.command).
- Выход: код 0/2 + stderr; журнал срабатываний.
- Что чистит шаг: ничего.
- Salad или наши ядра: наши, мгновенно.
