---
tier: 1
topic: knowledge-db
scope: Source-KB из книг — спека, KB0–KB9
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

**Статус (2026-08-10): ПОСТРОЕНА (ADR-0084)** — снапшот `runs/r20260810a` COMMITTED: 3349
атомов, 1723 семьи, 2755 canonical, 286 конфликтов, 1635 deps; eval 20/20, аудит A–G чисто,
оракул FN=0; LLM ~$4.7 (`gpt-5.6-luna`+terra). Запросы: `kdb query --plane A|B|C` из
`services/knowledge-db`. Дальше: приложения A–G (INCREMENTAL), редизайн правил — план в
снапшоте (`11_next_stage_plan.md`). План — `completed_plans/MASTER-source-kb.md`.

**На диске** (`remlab_knowledge_db_v1/`):
- `remlab_knowledge_db_v1/sources/` — 13 пакетов `CHAPTER_KNOWLEDGE_PACKAGE` v3.2 (~11 МБ):
  Mitton & Nystuen «Residential Interior Design», 3rd ed. 2016; главы 1–10 встык (гл. 4 — 3
  сегмента, гл. 6 — 2). Raw immutable. 1729 records · 2559 measurements · 3146 evidence.
  `source_collection_id=null` — identity predeclared: `RID_MITTON_NYSTUEN_2016_3E`.
- `remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md` — контракт пайплайна, **v1.1 ПОЛНАЯ**
  (фазы 0–12, инварианты A–G, real-data регрессии, completion gate 21 п.).
- `remlab_knowledge_db_v1/scratch_profile/` — скрипты профилирования корпуса.

**Ключевое о корпусе:** целостность 0 нарушений; ~20 CONFLICTING = опечатки книги;
IRC в 8+ написаниях; дубли/конфликты размечены только внутрифайлово.

**Код:** `services/knowledge-db/` (Python, pydantic + jsonschema + rfc8785, pytest 56 гейтов,
venv ~/venvs/kdb); артефакты — runs/<run_id> в KB-каталоге; реестры LLM-вердиктов в git
(реплей без сети, ID-стабильность).

Tier 2: спека (`tier2:`) · [[occupancy-rules]] · `guides/layout-mined-rules.md`.
