---
tier: 1
topic: knowledge-db
scope: Source-KB из книг — спека, KB0–KB9
tier2: "../../remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md"
updated: 2026-10-29
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-29
review_after: 2026-12-05
---

# Knowledge DB — source-база знаний из книг (для правил расстановки)

**Что это.** SOURCE KB (`knowledge_base_id="REMLAB_INTERIOR_SOURCE_KB"`) из JSON-пакетов книг: атомарные
claims с провенансом (страница, сила, конфликты) → retrieval-слои. Сама база прод-правила не меняет —
кандидаты с пруфами (не «инжест справочников» отклонённого ADR-0082).

**Статус (2026-08-10): ПОСТРОЕНА (ADR-0084)** — снапшот `runs/r20260810a` COMMITTED: 3349
атомов, 1723 семьи, 2755 canonical, 286 конфликтов, 1635 deps; eval 20/20, аудит A–G чисто,
оракул FN=0; LLM ~$4.7 (`gpt-5.6-luna`+terra). Запросы `python -m kdb query --plane A|B|C`
(`services/knowledge-db/kdb/__main__.py`) читают папку `runs/r20260810a.staging`, которой после фиксации нет
(`services/knowledge-db/kdb/phase9.py:518`) — сломано; рабочие читатели снимка — `services/knowledge-db/kdb/scene_rules.py`, `services/knowledge-db/kdb/export_rules.py`.
Дальше: приложения A–G (INCREMENTAL). План — `completed_plans/MASTER-source-kb.md`.
**Использование:** слияние правил выполнено (ADR-0086, `completed_plans/kb-rules-merge.md`, W0–W4): числа книги — в
`services/planner-solver/rules/occupancy.json`, судья берёт правила базы (`tools/scout/judge_layout.py` → `services/knowledge-db/kdb/scene_rules.py`).

**На диске** (`remlab_knowledge_db_v1/`):
- `remlab_knowledge_db_v1/sources/` — 13 пакетов `CHAPTER_KNOWLEDGE_PACKAGE` v3.2 (~11 МБ):
  Mitton & Nystuen «Residential Interior Design», 3rd ed. 2016; главы 1–10 встык (гл. 4 — 3
  сегмента, гл. 6 — 2). Raw immutable. 1729 records · 2559 measurements · 3146 evidence.
  `source_collection_id="SOURCE_ID_MISSING"` — identity predeclared: `RID_MITTON_NYSTUEN_2016_3E`.
- `remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md` — контракт пайплайна, **v1.1 ПОЛНАЯ**
  (фазы 0–12, инварианты A–G, real-data регрессии, completion gate 21 п.).

**Корпус:** целостность 0 нарушений; ~20 CONFLICTING = опечатки книги.

**Код:** `services/knowledge-db/` (Python, pytest 56 гейтов, venv ~/venvs/kdb); артефакты —
runs/<run_id>; вердикты пар в git (`registries/pair_verdicts.jsonl`), кэш LLM и слои 07/04a — вне git. W0: `services/knowledge-db/kdb/export_rules.py`
→ `docs/kb-rules-classification.md` (вердикты прод-параметрам; прод не трогает).

Tier 2: спека (`tier2:`) · [[occupancy-rules]] · `guides/layout-mined-rules.md`.
