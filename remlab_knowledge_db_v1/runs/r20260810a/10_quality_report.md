# 10_quality_report — REMLAB_INTERIOR_SOURCE_KB

- run: `r20260810a`, mode `BOOTSTRAP_FULL`, parent state: нет (bootstrap)
- corpus: 13 пакетов, completeness COMPLETE (манифест владельца; приложения A-G — EXPECTED_LATER)
- unresolved packages: 0
- документы/works/lineage: 1 / 1 / 1 (`RID_MITTON_NYSTUEN_2016_3E`); unresolved lineage: 0

## Счётчики слоёв
- raw: {'records': 1729, 'measurements': 2559, 'evidence': 3146, 'applicability_contexts': 1954, 'entities': 4455, 'excluded_source_items': 137, 'chapter_review_queue': 287, 'top_findings': 65}
- атомы: 3349 (assertion-реестр 3349, инфляция поддержки: 0)
- семьи 1723 (мульти: 483) · canonical 2755 (мульти: 269) · конфликт-группы 286 · dependency-рёбра 1635 (verified: 190)
- retrieval 2755 (RU-алиасов 2755) · applicability 2755 (evaluable 2063) · closure непустой у 353
- origins: external 526 / analyzed 2823 / unresolved 35

## Candidate graph / recall
- пар: 58313; каналы: FP=11493, SUBJ_DIM=19630, SUBJ_REF=268, AUTH=2949, SIBLING=415, HINT=165, NUMNEIGH=5381, BM25=10323, VEC=7689
- verified-positive recall: 1.0; ablation без HINT: 1.0; hint-аудит: {'CONFIRMED': 23, 'PARTIAL': 43, 'REJECTED': 0, 'UNRESOLVED': 8}
- adversarial (terra): {'pairs': 0, 'confirmed': 0, 'downgraded': 0}
- не судились (low-signal, помечены UNRESOLVED_NOT_JUDGED): 11520

## Оракул applicability
- {'room_type': 'living_room', 'zone_types': ['conversation', 'tv_media']}: index 94 / reference 94 / FN 0
- {'room_type': 'bedroom', 'zone_types': ['sleeping', 'storage']}: index 223 / reference 223 / FN 0
- {'room_type': 'kitchen', 'zone_types': ['cooking', 'food_preparation']}: index 296 / reference 296 / FN 0
- {'room_type': 'bathroom', 'zone_types': ['bathing_shower', 'toilet']}: index 216 / reference 216 / FN 0
- {'room_type': 'hallway', 'zone_types': ['circulation'], 'jurisdiction': 'us_north_america'}: index 241 / reference 241 / FN 0

## Eval (матрица 20/20)
- 20/20 пунктов зелёные; synthetic помечены в 09_eval_queries.jsonl

## Независимый аудит (PHASE 10, код)
- A_input_raw_schema: чисто
- B_state_id_stability: чисто
- C_subgraph_precedence: чисто
- D_provenance_authority: чисто
- E_consolidation: чисто
- F_retrieval_applicability: чисто
- G_production_boundary: чисто

## Production boundary: изменений прод-правил = 0

## LLM-расход пайплайна
- судья пар: $0.0013 ({'gpt-5.6-luna': 0.001268}); отказов: 0

## Blockers / human-review
- kb5b review-items: 598 (см. kb5b_report.json)
- слот-коллизии (REVIEW_SLOT_COLLISION): 32 группы — таблично-повторные значения гл.4; на consolidation не влияют
- presence-атомы PRESENCE_PATTERN_AUTO: 2 (需 human-присмотр при использовании)

_Ничего сверх доказанного файлами/тестами не утверждается._
