# knowledge-db — пайплайн REMLAB_INTERIOR_SOURCE_KB

Строит audit-friendly source knowledge base из извлечённых JSON-пакетов книг
(сейчас: Mitton & Nystuen, Residential Interior Design, 3rd ed. 2016).
**Production-правила солвера не меняет** — только source-слой с провенансом.

- Контракт: `remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md` (v1.1)
- План/волны: `.memory_bank/plans/MASTER-source-kb.md` (KB0–KB9)
- Данные: `remlab_knowledge_db_v1/` (sources — raw immutable; runs/<id>.staging → commit)

## Запуск

```bash
~/venvs/kdb/bin/python -m kdb run --phase 0          # preflight
~/venvs/kdb/bin/python -m kdb run --phase 0-1        # диапазон фаз
~/venvs/kdb/bin/python -m pytest                     # гейты (из этой папки)
```

venv: `~/venvs/kdb` (`pip install -r requirements.txt`; pip только в venv — правило DEV-VM).

## Структура

- `kdb/canonical.py` — JCS (RFC 8785) + SHA-256 + `DERIVED_ID`
- `kdb/io.py` — duplicate-key-aware парс, запись с parse-back, JSONL
- `kdb/identity.py` — predeclared identity документа (спека)
- `kdb/phase0.py` — preflight: валидация 13 пакетов, сегменты по master-страницам,
  манифест входа + реестр документов
- `kdb/schemacheck.py` — валидация артефактов (JSON Schema 2020-12), `schemas/`
- `tests/` — гейты волн на реальном корпусе (детерминизм, счётчики, схемы)

Каждая фаза идемпотентна; провал гейта = ненулевой exit code.
LLM-фазы (KB2+): OpenAI `gpt-5.6-luna` → эскалация `gpt-5.6-terra`, кэш вердиктов
на диске, пилот до массового прогона (test-before-spend).
