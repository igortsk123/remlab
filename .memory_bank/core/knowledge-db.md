---
tier: 1
topic: knowledge-db
scope: Source-KB из книг — спека, план KB0–KB9
tier2: "../../remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md"
updated: 2026-08-10
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-10
---

# Knowledge DB — source-база знаний из книг (для правил расстановки)

**Что это.** Audit-friendly SOURCE KB (`knowledge_base_id="REMLAB_INTERIOR_SOURCE_KB"`) из
извлечённых JSON-пакетов книг: атомарные claims с провенансом (страница/фигура, сила,
авторитет, конфликты) → retrieval-слои. **Production-правила солвера НЕ меняет** —
только кандидаты с пруфами для будущего редизайна. Отличие от отклонённого ADR-0082 «инжеста
справочников»: source-слой с провенансом, не числа напрямую в прод.

**Статус (2026-08-10):** план **`plans/MASTER-source-kb.md` — draft, ждёт «деплой»**; код не
писался. Решения владельца: LLM — `gpt-5.6-luna`/`terra` (НЕ Gemini), бюджет ≤$60 (prereq:
биллинг OpenAI); git смешанно; цитаты храним; приложения книги — позже (INCREMENTAL).

**На диске** (`remlab_knowledge_db_v1/`):
- `remlab_knowledge_db_v1/sources/` — 13 пакетов `CHAPTER_KNOWLEDGE_PACKAGE` v3.2 (~11 МБ):
  Mitton & Nystuen «Residential Interior Design», 3rd ed. 2016; главы 1–10 встык (гл. 4 — 3
  сегмента, гл. 6 — 2). Raw immutable. 1729 records · 2559 measurements · 3146 evidence.
  `source_collection_id=null` — identity predeclared: `RID_MITTON_NYSTUEN_2016_3E`.
- `remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md` — контракт пайплайна, **v1.1 ПОЛНАЯ**
  (фазы 0–12, инварианты A–G, real-data регрессии, completion gate 21 п.).
- `remlab_knowledge_db_v1/scratch_profile/` — скрипты профилирования корпуса.

**Ключевое о корпусе:** целостность ссылок 0 нарушений; нормализация верна на 95.4%
(расхождения = опечатки книги, см. conversion_note; 1 подозрение на 10×-ошибку — ch8 R037);
IRC в 8+ написаниях; 54% relation_type='other', 636 proposed entity types; дубли/конфликты
только внутрифайловые. Детали — профили и план.

**Посадка кода (план):** подсистема services/knowledge-db (Python, pydantic + jsonschema +
rfc8785, venv ~/venvs/kdb); артефакты — runs/<run_id> в KB-каталоге.

Tier 2: спека (`tier2:`) · план `plans/MASTER-source-kb.md` · методология-родственник —
[[occupancy-rules]], `guides/layout-mined-rules.md`.
