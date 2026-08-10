# SPEC: REMLAB_INTERIOR_SOURCE_KB — контракт пайплайна (v1)

> **Provenance:** промпт владельца, чат 2026-08-10 (metadata origin: `PROMPT_SUPPLIED`).
> **⚠️ ОБРЕЗАН**: исходное сообщение превысило лимит чата (50 000 символов) и оборвалось
> внутри PHASE 9 на строке «Required coverage matrix:». Фазы 9 (продолжение), 10, 11
> реконструируются по output-контракту (`09_eval_queries.jsonl`, `10_quality_report.md`,
> `11_next_stage_plan.md`). Хвост запрошен у владельца — при получении дописать сюда и
> поднять версию спеки.
> Ниже — конспект-контракт, близкий к тексту оригинала (структура и все нормативные
> положения сохранены; формулировки местами сжаты без потери смысла).

## Роль и задача

Главный knowledge-engineering agent RemLab. RemLab автоматически расставляет реальные
предметы мебели в жилых помещениях. Вход — source chapter/segment JSON из строгого SOURCE
EXTRACTION pipeline (source claims, measurements, applicability, entities, relations,
evidence, provenance).

Задача — НЕ выбирать «правильные» интерьерные правила и НЕ переписывать production rules
RemLab. Построить воспроизводимую, audit-friendly SOURCE knowledge base:
1. lossless объединить source packages;
2. проверить целостность;
3. выделить устойчивые atomic claims;
4. построить persistent vocabulary/authority/source identities;
5. canonicalize semantic families, scoped variants, conflicts и dependencies без потери source facts;
6. построить exhaustive applicability + relevance retrieval layers;
7. подготовить hybrid retrieval, eval и quality audit;
8. сохранять persistent identity между runs;
9. только в конце написать план будущего redesign RemLab rules, не выполняя redesign сейчас.

## Fixed project identity

- `knowledge_base_id="REMLAB_INTERIOR_SOURCE_KB"` — identity всей multi-document source KB, НЕ книги.
- Predeclared current source document:
  - `source_document_id="RID_MITTON_NYSTUEN_2016_3E"`
  - `source_work_id="RID_MITTON_NYSTUEN_WORK"`
  - `source_independence_group_id="RID_MITTON_NYSTUEN_WORK"`
  - «Residential Interior Design: A Guide to Planning Spaces», Maureen Mitton, Courtney Nystuen, Third Edition, 2016
  - metadata origin: `PROMPT_SUPPLIED`
- Пакеты с `SOURCE_ID_MISSING`: raw НЕ менять; derived mapping к predeclared ID разрешён
  только потому, что identity задан здесь. Другие книги/издания → отдельные persistent
  `source_document_id`; издания не схлопывать; при подтверждённой lineage — общий
  `source_work_id` и обычно общий `source_independence_group_id`.
- Четыре уровня provenance identity не смешивать:
  1. `knowledge_base_id` — corpus;
  2. `source_document_id` — конкретное анализируемое издание/документ;
  3. `source_work_id` + `source_independence_group_id` — conceptual work / document-lineage;
  4. `claim_corroboration_origin_group_id` — claim-level independent corroboration root.
- Document count / lineage count ≠ independent claim corroboration. Две книги, цитирующие
  один внешний provision, = два analyzed documents, но один claim-origin.
- Cited authority внутри книги — `cited_authority_id` lineage metadata; становится
  `source_document_id` только если оригинал отдельно загружен/проанализирован.
- Web/general knowledge для bibliographic repair или modern-standard verification — ЗАПРЕЩЕНО.

## Run contract

Ровно один `run_mode`:
- `BOOTSTRAP_FULL` — нет trusted prior state; текущие packages формируют corpus.
- `REBUILD_WITH_PRIOR_STATE` — corpus передан заново, persistent identities/migrations из validated prior snapshot.
- `INCREMENTAL_UPDATE` — только new/changed packages поверх prior committed corpus.

Для rebuild/incremental обязателен `prior_state_snapshot` (read-only, полный, `COMMITTED`).
Нет/невалиден → `ERROR_INVALID_PRIOR_STATE`; incremental без state → `ERROR_INCREMENTAL_STATE_REQUIRED`.
Не mint'ить параллельную ID-систему поверх partial corpus.

Перед использованием prior state: (1) parse/validate `pipeline_state.json`, require
`state_status="COMMITTED"`; (2) совместимость pipeline/schema versions; (3) verify все payload
hashes из `artifact_hash_manifest` + пересчёт `snapshot_content_root_sha256`; (4) если записан
внешний `pipeline_state_sha256` — verify bytes; (5) verify `knowledge_base_id`; (6) persistent
registries — только из validated snapshot; (7) referential-integrity checks; (8) записать parent
snapshot identity/hash в новый input manifest/state.

Active corpus semantics: incremental = prior committed + explicit delta; отсутствие старого
пакета во входе ≠ deletion; `input_delta_manifest` ops `ADD|REPLACE|REMOVE` адресуют стабильный
`logical_package_key`; без delta-манифеста: новый ключ ⇒ ADD, изменённый контент ⇒ candidate
REPLACE/re-extraction (reconciliation), отсутствие ⇒ не REMOVE.

Completeness: только `expected_input_manifest` авторитетен для COMPLETE/INCOMPLETE; без него
`collection_input_completeness="UNKNOWN"`; не выводить недостающие главы из имён файлов,
нумерации или памяти модели.

Механика (merge, хэши, схемы, счётчики, referential validation) — код, не LLM. Не держать
всю KB в памяти модели.

## Нормативные инварианты (глобальные, override phase-local convenience)

### A. SOURCE FIDELITY
1. Raw source JSON immutable — не переписывать числа/юниты/evidence/exclusions/notes/anchors/wording.
2. Ни один source record/measurement/evidence/context/excluded/review item не исчезает.
3. Mechanical merge — детерминированный код, не LLM-пересказ.
4. Не усреднять конфликтующие значения, не выбирать «победителя» при консолидации.
5. Не повышать силу: `EXAMPLE ≠ TYPICAL ≠ PREFERRED ≠ RECOMMENDED_MINIMUM ≠ REQUIRED_MINIMUM`.
6. Source claim ≠ production rule. `source_claim_strength`, `remlab_candidate_use`, authority,
   Judge-оценки — не HARD/SOFT policy RemLab.
7. Embeddings — retrieval-индексы, не истина; числа/операторы/юниты/scope/authority — только structured.

### B. SOURCE GRAPH / ATOMICITY
8. Package — provenance-граф, не независимые массивы; не флаттенить, не декартить contexts/entities/measurements/evidence.
9. Для measurement-bound claims авторитетны рёбра `measurement.context_ids[]`/`evidence_ids[]` — не приклеивать все record-contexts/evidence.
10. Measurement-локальные поля (subject/reference/measured_from/to, condition/state/population/value/strength) сильнее record-сводок для этой атомарной пропозиции.
11. Record-level qualifiers/authority/entities — parent metadata, если не evidence-backed для ребёнка.
12. `record.entities[]` — mentions, не автоматические runtime-prerequisites/фильтры.
13. Сохранять existence/cardinality/prohibition/alternative/presence claims и без скалярного измерения.
14. Несколько contexts у одного measurement — OR-ветки (если source явно не требует co-occurrence); предикаты внутри ветки — AND.

### C. UNKNOWN / SCOPE
15. `unknown` field-sensitive: selector/identity ⇒ `UNRESOLVED_SELECTOR` (не wildcard, не MATCH);
    optional qualifier (population, sex, age_group, percentile, posture, mobility_context,
    clothing_or_equipment, person/object state) ⇒ `UNSPECIFIED_BY_SOURCE` — не создаёт runtime-предикат
    и сам по себе не понижает applicability до UNKNOWN. `other` — explicit fallback bucket, не wildcard.
16. `assignment_basis` — provenance, не confidence. `EXPLICIT_SOURCE` и валидный `CHAPTER_CONTEXT`
    могут давать definite source context; `INFERRED` ⇒ verification/UNKNOWN semantics.
17. `zone_types[]` одного контекста — один associated set; zone-retrieval — membership/overlap,
    не Cartesian room×zone, если source не требует co-existence всех зон.
18. `universal_residential` — domain/scope-маркер, не литеральный room type и не автоматически whole-dwelling scope.
19. Broader/narrower словаря ≠ наследование applicability; только явные APPROVED `applicability_subsumption_edges`.
20. Semantic applicability и runtime evaluability — раздельны.

### D. ACTIVATION VS CONSTRAINT
21. Activation/focus selection отдельно от constraint/effect evaluation.
22. Presence/cardinality claim применим и при отсутствии target'а — отсутствие может БЫТЬ нарушением.
23. Source entities ≠ автоматические `ENTITY_PRESENT` триггеры.

### E. PROVENANCE / CORROBORATION
24. Провенанс-размерности (document/work/independence/origin/authority/evidence/member IDs)
    не расщепляют семантически идентичный вопрос.
25. Разные издания — разные documents; издания одной work обычно делят lineage-группу и не
    добавляют independent corroboration.
26. Каждый corroboration-eligible atomic claim резолвит origin:
    `ANALYZED_SOURCE_AUTHORSHIP | CITED_EXTERNAL_ASSERTION | COMPOSITE | UNKNOWN`.
27. Identity внешней ассерции = authority/source entity + edition/version (если известны) +
    locator/provision (если известен) + source-faithful semantic slot. Отсутствие locator ≠ authorship.
28. Если цитируемый оригинал позже ingested — quotations/restatements мапятся на тот же claim-origin (при verified identity).
29. Unresolved lineage/origin никогда не увеличивает independent corroboration count.

### F. SEMANTIC GROUPING
30. Semantic pair discovery — на этапе консолидации, explicit, high-recall; query-time RAG не чинит пропущенные рёбра.
31. Candidate generation — OR/UNION независимых каналов; ни один канал не completeness-гейт.
32. Unknown/provisional metadata расширяет кандидатов, не hard-исключает пары.
33. Pair candidate ≠ relation verdict.
34. Три отдельных слоя: semantic-question identity / relationship classification / provenance-corroboration.
35. Family ≠ blind connected components/transitive closure: каждый member индивидуально
    удовлетворяет resolved `family_semantic_signature`; inconsistent triangles/bridges ⇒ split/review/migration.
36. Разные значения/операторы/силы могут быть в одной semantic-question family.
37. Duplicate/agreement/conflict требуют scope comparability: `EQUIVALENT | OVERLAPPING | DISJOINT | UNKNOWN`.
38. Одно значение в disjoint scopes ≠ consensus; разные значения в disjoint scopes ≠ conflict.
39. Canonical variant scope-однороден: не union'ить неэквивалентные `effective_source_scope`.
40. Dependencies (`QUALIFIES`, `EXCEPTION_TO`, `LIMITS_APPLICABILITY_OF`, `OVERRIDES_IN_SCOPE`,
    `TRADEOFF_WITH`, `VALUE_REFERENCE_TO`, …) — first-class рёбра, не классы duplicate/conflict.
41. Active verified modifiers/dependencies включаются в Judge-контекст fixed-point, cycle-safe closure; top-K их не прячет.

### G. STABLE STATE
42. Package hashes / observation IDs — extraction-version identity, не stable semantic identity.
43. Stable assertion/atomic ID переживают несвязанные правки пакета, реордеринг, добавление
    supporting evidence, alias-правки словаря.
44. Re-extraction того же logical assertion — observation, не новая corroboration; material
    disagreement без authoritative precedence ⇒ `EXTRACTION_REVISION_CONFLICT/UNRESOLVED`.
45. Persistent IDs — только из validated prior state или mint в текущем run; не читать
    одноимённые файлы из staging/output опортюнистически.
46. Prior committed snapshot immutable; новый run пишет в новый staging и становится reusable
    только после всех гейтов.
47. `pipeline_state.json` не содержит хэш собственных финальных байтов; payload-хэши исключают
    `pipeline_state.json` и mutable pointers; финальный state хэшируется внешне после сериализации.

## Output & state contract

Все артефакты — в новый staging: `remlab_knowledge_db_v1/runs/<run_id>.staging/`. Prior snapshot read-only.

Обязательные артефакты:
`00_input_manifest.json` · `01_raw_merged.json` · `02_atomic_claims.jsonl` ·
`02a_source_assertion_revision_registry.jsonl` · `03_vocabulary_map.json` ·
`03b_cited_authority_registry.json` · `03b2_claim_corroboration_origins.jsonl` ·
`03c_scope_semantics_registry.json` · `03d_source_scope_overlays.jsonl` ·
`04a_semantic_comparison_candidates.jsonl` · `04_claim_groups.jsonl` ·
`05_conflict_groups.jsonl` · `06_canonical_knowledge.jsonl` ·
`06b_claim_dependency_graph.jsonl` · `07_retrieval_records.jsonl` ·
`07b_applicability_index.jsonl` · `07c_context_closure_index.jsonl` ·
`08_retrieval_config.json` · `09_eval_queries.jsonl` · `10_quality_report.md` ·
`11_next_stage_plan.md` · `pipeline_state.json` · `schema_registry.json` · `schemas/`.

Все machine-readable — JSON Schema Draft 2020-12. Для каждого JSON/JSONL: reject duplicate keys;
parse-back validate; JSONL = один UTF-8 объект на непустую строку; required/types/enums/null;
затем referential-integrity + semantic assertions. Schema failure ⇒ артефакт incomplete; чинить
derived/код, не raw.

`pipeline_state.json` минимум: `state_snapshot_id`, `state_status`, `run_id`, `run_mode`,
`pipeline_version`, `derived_schema_version`, `knowledge_base_id`; active source identities;
registry fingerprints; `parent_state_snapshot_id`, `parent_pipeline_state_sha256`;
input/delta/active-corpus fingerprints; `snapshot_content_root_sha256`; `artifact_hash_manifest`
(только immutable payloads, sorted by normalized relative path);
`pipeline_state_self_hash_policy="EXTERNAL_AFTER_FINALIZATION"`; registry artifacts,
referential/completion statuses, commit protocol, timestamps.

Commit protocol: (1) validate всё; (2) hash payload-артефактов (исключая pipeline_state.json и
mutable pointers); (3) `snapshot_content_root_sha256 = SHA256(JCS(sorted {path:payload_sha256}))`;
(4) `state_status="COMMITTED"` только после гейтов; (5) сериализовать state один раз, внешний
`pipeline_state_sha256`, не вписывать обратно; (6) publish/atomic-rename, `CURRENT`-указатель
последним; (7) prior snapshot сохранять для rollback/audit. Провал ⇒ `STAGING|FAILED|INCOMPLETE`
— не валидный prior state.

Миграции: legacy `CITED_AUTHORITY_PROVISION` → `CITED_EXTERNAL_ASSERTION` (сохранить equivalent
origin identity); legacy `canonical_source_collection_id="RID_MITTON_NYSTUEN_2016_3E"` → одна
явная миграция в multi-document KB (сохранить document ID, проставить work/independence,
`knowledge_base_id`, записать migration, не толковать book ID как KB ID).

## Derived ID policy

RFC 8785/JCS + full SHA-256: `DERIVED_ID(prefix, payload) = prefix + "_" + SHA256(JCS(payload))`.
Identity payload — только identity-defining semantics/upstream stable IDs; без timestamp, prose,
confidence, retrieval text, processing order. Stable semantic IDs не зависят от
observation/package-version IDs (кроме самих observation/version объектов).

- `atomic_claim_id = DERIVED_ID("ATOM", {source_assertion_uid})`.
- `claim_family_id = DERIVED_ID(... resolved family_semantic_signature ...)` — без member IDs/counts/provenance/numeric answer/strength.
- `conflict_group_id` = family + conflict scope signature (не current members).
- `canonical_claim_id` = family + `scoped_variant_semantic_signature` (scope semantics вкл., raw provenance IDs искл.).
- `retrieval_id` = canonical claim + retrieval variant/language key.

`family_semantic_signature` = ЧТО за вопрос: canonical entity roles, activation/focus, constraint
target, quantifier family, relation, dimension/metric family, endpoints, activity/state, минимальная
локальная applicability для идентификации вопроса. Исключает document/work/origin, evidence,
authority lineage, численный ответ, силу.

`scoped_variant_semantic_signature` добавляет normalized applicability branch semantics +
`effective_source_scope_signature` + scope-defining population/state/mobility/temporal +
authority/jurisdiction scope (только если материально меняет applicability).

Membership — state, не identity: `member_ids[]`, `member_count`,
`membership_fingerprint_sha256=SHA256(JCS(sorted member IDs))` отдельно. Смена semantic/scope
signature ⇒ новый ID + explicit supersedes migration.

## PHASE 0 — preflight

0A. run mode, prior state validation, active corpus после delta.
0B. Persistent `source_document_registry` ДО semantic projection; precedence резолюции:
(1) authoritative package→document mapping/manifest; (2) predeclared current-book mapping;
(3) validated prior registry; (4) raw ISBN/DOI; (5) сильная bibliographic metadata с edition
discrimination; (6) `UNRESOLVED`. Не резолвить из `SOURCE_ID_MISSING`/filename similarity/пунктуации
заголовка. Unresolved/conflicting ⇒ raw/auditable, но `active_for_semantic_projection=false`.
Registry: document/work/independence IDs, lineage relation (`ORIGINAL|REVISION_OF|TRANSLATION_OF|
ABRIDGEMENT_OF|DERIVED_FROM|RELATED_WORK|UNKNOWN`), parents, resolution status, kind, normalized
bibliographic metadata, metadata origin, raw variants, identity confidence/status, package provenance, migrations.
0C. Валидация каждого входного JSON: duplicate-key-aware parse + standard parse; filename, bytes,
`file_sha256`, JCS `canonical_json_sha256`; schema/vocab/source/chapter/segment/page/count metadata;
uniqueness record IDs и per-record measurement/evidence/context IDs; локальная резолюция всех
refs; truncation/exact duplicates/overlapping segments/incompatible schemas/unresolved identity/
coverage flags; missing packages — только против `expected_input_manifest`.
`00_input_manifest.json`: run/prior/delta/completeness semantics, все logical package keys,
duplicates/collisions/removals, KB identity, registries/assignments, unresolved packages.
Invalid/truncated raw input блокируется, не чинится.

## PHASE 1 — lossless mechanical merge

`01_raw_merged.json` детерминированным кодом. Bootstrap: merge active packages. Rebuild: supplied
corpus = truth, prior даёт identities/migrations. Incremental: prior full raw + ADD/REPLACE/REMOVE.
Каждый raw package object — byte/semantic unchanged внутри raw-слоя; derived metadata снаружи.

Идентичности пакета: (1) byte artifact: `logical_package_key=<source_document_id>::<chapter_or_
section_identity>::<segment_identity>`; `artifact_uid=<logical_package_key>::RAW_SHA256_<file_sha256>`;
(2) parsed content: `package_content_uid=<logical_package_key>::JCS_SHA256_<canonical_json_sha256>`
(fallback `RAW_FALLBACK_SHA256_...`, `content_identity_quality="RAW_FALLBACK"`). Не фабриковать
logical key для unresolved documents.

Observation IDs включают record scope (measurement/evidence/context IDs record-локальны):
`<package_content_uid>::<record_id>[::<measurement_id|evidence_id|context_id>]`. Artifact UID
никогда не входит в stable semantic IDs.

Exact duplicates: все файлы в audit inventory; byte/JCS-дубликат участвует семантически один раз;
representative = lexicographically smallest artifact UID; дубликаты `active_for_semantic_projection=false`;
overlapping non-identical segments не auto-drop.

Gate: before/after счётчики packages/records/measurements/evidence/excluded/review равны; UIDs
уникальны; raw semantic mutation = none. Провал стопит пайплайн.

## PHASE 2 / 2A — atomic projection + stable assertion identity

Порядок обязателен: (1) IN-MEMORY atomic candidates без stable IDs; (2) PHASE 2A reconciliation;
(3) только затем `02_atomic_claims.jsonl`.

Один atomic claim = одна независимо проверяемая пропозиция. Split гетерогенных measurements/
conditions, но не отрывать numeric child от родительского condition. Presence/cardinality/
prohibition/alternative/property — отдельные атомы при семантической независимости.

Режимы: `MEASUREMENT_BOUND` (точные referenced contexts/evidence; measurement-поля правят);
`RECORD_SEMANTIC` (только supporting contexts/evidence/entities; неуверенные подмножества —
contextual/UNKNOWN); `COMPOUND_EXPLICIT` (только для неделимых явных формул с совместимым scope/roles).

Каждое source-derived поле атома: field-origin binding (`MEASUREMENT|CONTEXT|RECORD|EVIDENCE_DERIVED|
RECONCILED`) + source path/value + status. Measurement-локальные поля не перетираются parent `MIXED`/
record qualifiers. Record qualifier входит в предикат атома только при явном source-скоупинге ребёнка.

Applicability — safe Boolean AST: `AND|OR|NOT|PREDICATE|TRUE|UNKNOWN`. Пустое условие ⇒ TRUE;
optional `UNSPECIFIED_BY_SOURCE` ⇒ нет предиката; opaque непустое ⇒ UNKNOWN. Без runtime eval.

Финальные атомы: stable/revision identity; document/work/independence provenance; observation/
evidence loci; strength/value type/candidate use; entity-role/context/evidence/qualifier bindings;
original + source-normalized measurement поля; numeric/symbolic views; authority candidate
provenance; downstream utility; conditions/scope; verification flags; source trace.

PHASE 2A — `02a_source_assertion_revision_registry.jsonl`. Слои identity:
(1) extraction observation/version UIDs; (2) `source_evidence_locus_uid=DERIVED_ID("SELOC",
source_evidence_locus_signature)` из source document + stable position (master page, при
отсутствии — printed-page fallback ниже качеством; section; figure/table/cell/dimension;
консервативный anchor fingerprint; locus kind), `locus_identity_quality=HIGH|MEDIUM|LOW|UNRESOLVED`;
(3) persistent `source_assertion_uid` из `source_document_id + assertion_anchor_locus_uid +
assertion_semantic_slot_signature`. Supporting evidence set — membership, НЕ identity.

Anchor priority: unique direct proposition-bearing evidence → table cell/figure dimension/source
anchor → direct locus → stable locator + semantic slot. Bootstrap-ties — детерминированный tuple,
anchor персистится. Ошибочный anchor — explicit migration, не silent remint.

`assertion_semantic_slot_signature` — source-faithful, pre-vocabulary: subject/reference roles,
relation/dimension family, endpoints, quantifier/constraint kind, differentiating local condition,
property/table/figure slot. Исключает numeric answer, normalized value, package IDs, confidence/
notes/routing/canonical vocabulary/support membership.

Резолюция против persistent registry: exact document+anchor+compatible slot → equivalent locus+slot →
overlapping high-confidence locus+equivalent slot → review. Prior registry wins.
`atomic_claim_id=DERIVED_ID("ATOM",{source_assertion_uid})`; `atomic_claim_version_uid` = stable
atomic ID + extracted values/conditions/strength + observation provenance.
Revision status: `SINGLE|EQUIVALENT_REEXTRACTIONS|EXPLICITLY_SUPERSEDED|EXTRACTION_REVISION_CONFLICT|UNRESOLVED`.
Material disagreement без precedence — unresolved, блок от definite downstream use; не выбирать
по timestamp/имени файла. Раздельные счётчики observation/locus/assertion/document.

## PHASE 2B — dual numeric comparison

Source numeric — exactly preserved. `numeric_comparison_view` — только из `value_original/
range_original + unit_original`; source `normalized_value` не единственная истина. Decimal +
pinned conversion table (factors/version/reference). Preserve operator, approx/range/inclusive,
strength. Ambiguous ⇒ `AMBIGUOUS/UNAVAILABLE`, no guess. Классификация derived vs source-normalized:
`CONSISTENT|ROUNDING_COMPATIBLE|CONFLICTING|NOT_COMPARABLE|UNKNOWN`. Source mismatch retained.
Подтипы: `SAME_PRIMARY_QUANTITY_WITH_EQUIVALENCY_DISCREPANCY`, `INTERNAL_UNIT_EQUIVALENCY_CONFLICT`.

## PHASE 2C — symbolic/relational constraints

Для каждого `relationship_expression`: preserve source string + allow-listed AST если надёжно;
parse status `PARSED|PARTIALLY_PARSED|OPAQUE`; kinds `INEQUALITY|EQUALITY|FORMULA|PROPORTION|
ORDERING|COMPOUND|EXAMPLE|QUALITATIVE_RELATION|OTHER`; atoms/operators/variables/units/roles/linkage.
Никогда не eval. OPAQUE остаётся знанием. Формула ≠ worked example (пример не универсализируется).
Grouping сравнивает operator/role структуру, не только строки.

## PHASE 2D — activation, target, quantification

Отдельно: `activation_view` (focus scope/selector + триггеры/runtime capabilities);
`constraint_target_view` (constrained/expected/prohibited/reference targets);
`quantification_view` (`EXISTS_MIN|EXISTS_MAX|EXACT_COUNT|FOR_EACH|NONE|AT_LEAST_ONE_OF|ALL_OF|
CONDITIONAL_EXISTENCE|RECOMMENDED_PRESENCE|OTHER` + alternatives/min/max/exact/scope/condition/phrase).
Роли mentions: `ACTIVATION_TRIGGER|FOCUS|CONSTRAINT_TARGET|ALTERNATIVE_TARGET|REFERENCE_CONTEXT|
PROHIBITED_TARGET|EXAMPLE_ONLY|UNKNOWN`. Отсутствие target ≠ applicability mismatch для presence/
cardinality. Evaluation states (`SATISFIED|UNSATISFIED|NOT_APPLICABLE_TO_INSTANCE|NOT_EVALUABLE|
UNKNOWN|NOT_EVALUATED`) отдельно от production PASS/FAIL.

## PHASE 2E — downstream utility (не policy)

Классы: `SOURCE_CONSTRAINT_GUIDANCE | SEMANTIC_DESIGN_GUIDANCE | MODELING_REFERENCE |
EXAMPLE_REFERENCE | HISTORICAL_CONTEXT | SOURCE_META_KNOWLEDGE | UNRESOLVED_UTILITY` (+ Judge
backbone eligibility/reason/confidence/review basis). Только in-scope `SOURCE_CONSTRAINT_GUIDANCE`
может быть mandatory Judge backbone. `REFERENCE_ONLY` — routing hint, не deletion. Canonical union
utility-классов — discovery metadata; backbone membership — member-level (пример не наследует
операционный авторитет от canonical-соседа).

## PHASE 3 — vocabulary/alias registry (`03_vocabulary_map.json`)

Concept identity ≠ label. CORE — фиксированные RemLab IDs. Новые концепты — persistent registry
identity; reuse prior до mint. Labels/translations/definitions/members не remint'ят identity.
Kinds: entity/relation/room/zone/dimension/activity/state + geography/jurisdiction/market/culture/
population/temporal/source-scope/other. Statuses: `EXACT|SYNONYM|NARROWER|BROADER|RELATED|
NOT_EQUIVALENT|UNRESOLVED`. Initial mint не-CORE: persisted stable `origin_anchor` (lexicographically
smallest member исходной группы) + full SHA-256. Merge/split — explicit survivor/deprecated/
replaced-by migration; retired ID не переиспользуется. Unresolved — provisional identity, не hard-фильтры.

## PHASE 3B — cited authority registry (`03b_cited_authority_registry.json`)

Один authority при string-вариациях + отдельная привязка к атомам. Raw поля immutable.
Registry: kind (`CODE|STANDARD|BOOK|GUIDELINE|ORGANIZATION|OTHER|UNKNOWN`), title/org/edition/
jurisdiction только source-supported, raw variants, represented analyzed doc/work только при
независимом ingest+verify, attribute provenance, status/confidence/review.
Binding: exact claim/version, authority ID/status/role/basis/evidence/paths, edition/locator basis.
Roles: `GOVERNS_CLAIM|PRIMARY_SOURCE_OF_CLAIM|DEFINES_TERM|SUPPORTS_CLAIM|SUPPORTS_EXAMPLE|
COMPARED_AUTHORITY|EXCEPTION_AUTHORITY|LOCAL_VARIANT_AUTHORITY|UNKNOWN`.
Composite record authority — парсить кандидатов, биндить per atomic child; не union на всех
siblings. Vague «local codes» — unresolved local authority, не выдумывать имя. Record-level
authority — candidate context. Разные издания — разные authority IDs; unknown edition не сливать
с known. Не web-обновлять стандарты.

## PHASE 3B2 — claim corroboration origins (`03b2_claim_corroboration_origins.jsonl`)

На каждый corroboration-eligible атом — один claim-level origin: source-authored ⇒ authorship
origin (analyzed document/work semantics); externally attributed ⇒ `CITED_EXTERNAL_ASSERTION`
(verified authority + edition/version + locator + slot); mixed ⇒ `COMPOSITE`; insufficient ⇒
`UNKNOWN/UNRESOLVED`. Unresolved/composite не считать independent support. Две книги с одной
внешней ассерцией — один origin. Restatement ≠ source-authored interpretation; при возможности split.

## PHASE 3C — scope semantics registry (`03c_scope_semantics_registry.json`)

Source applicability отдельно от runtime evaluability и production policy. Preserve точные
context branches/roles/conditions/assignment basis. Только явные canonical scope concepts и
APPROVED subsumption edges. Для каждого атома/canonical: normalized branches + Boolean AST;
source context support class (`SOURCE_EXPLICIT`, `SOURCE_CONTEXT_DEFINITE`, `INFERRED/UNKNOWN`);
`residential_domain_scope`; primary/possible scope target levels; required runtime capabilities +
`runtime_evaluability`; qualifiers с field-sensitive unknown semantics.
`CHAPTER_CONTEXT` не автоматически uncertain (definite при валидном контракте), но не relabel
в explicit wording. `INFERRED` non-definite до верификации.

## PHASE 3D — source-wide scope overlays (`03d_source_scope_overlays.jsonl`)

Source-statement, явно квалифицирующий другие claims (whole-book geography/market/population/
time scope, unit convention) — first-class overlay только при source evidence (qualifier + target
class + extent). Notes/interpretation/aliases — seed discovery, не verification.
Overlay: source anchor/evidence, document boundary, kind, effect (`APPLICABILITY_QUALIFIER|
INTERPRETATION_CONVENTION|PARSING_CONVENTION|RETRIEVAL_CONTEXT_ONLY`), extent, safe target-selector
AST, inherited qualifiers, status, stable identity независимо от matched members.
`effective_source_scope = local_source_scope AND все matching VERIFIED APPLICABILITY_QUALIFIER overlays`.
Overlay narrow/qualify/annotate, никогда silently broaden/erase. Конфликты explicit.
Runtime compatibility: `UNRESTRICTED|MATCH|MISMATCH|UNKNOWN|CONFLICTING`; MISMATCH/UNKNOWN не
удаляет знание, но блокирует definite Judge backbone для этого runtime-контекста. Overlays
bounded by `source_document_id`, не создают corroboration per inherited child.

## PHASE 3E — high-recall candidate graph (`04a_semantic_comparison_candidates.jsonl`)

ДО grouping/conflict/dependency решений. Малые корпуса — exhaustive all-pairs предпочтителен;
большие — high-recall blocking + measured recall + blocked-out audits. Incremental: новые атомы
против ВСЕГО active corpus. Pair ID детерминирован из sorted atomic IDs + purpose.
UNION независимых каналов: exact family-signature blocks; entity-role/relation/dimension/endpoint/
quantifier overlap; numeric compatibility; symbolic similarity; lexical/BM25; vector; local
duplicate/conflict hints (seeds only); authority/locator cues; scope/entity/condition blocks;
dependency-specific signals. Ни один канал не hard-исключает. Unknown расширяет кандидатов.
Candidate generation ≠ evidence. Recall против verified positive regression pairs;
`candidate_pair_recall=100%` перед commit. Для proposed families — дополнить missing within-family pairs.

## PHASE 4 — claim families (`04_claim_groups.jsonl`)

Три слоя: A. `same_semantic_question_status=SAME|DIFFERENT|UNRESOLVED`; B. relationship:
`EXACT_DUPLICATE|SEMANTIC_DUPLICATE|COMPATIBLE_VARIANT|COMPLEMENTARY|SCOPED_VARIANT|
POTENTIAL_CONFLICT|TRUE_CONFLICT|RELATED_NOT_SAME|SAME_PRIMARY_QUANTITY_WITH_EQUIVALENCY_
DISCREPANCY|UNRESOLVED`; C. provenance/corroboration.
Алгоритм: candidate signature → reconcile → mint `claim_family_id` из resolved signature →
каждый member индивидуально удовлетворяет (или reviewed equivalence mapping) → не из
connectivity/transitivity → inconsistent triangles/bridges: max consistent families + review →
incremental bridging не сливает silently две stable families (explicit migration).
Перед классификацией — scope relation (local + inherited effective): EQUIVALENT ⇒ full comparison;
OVERLAPPING ⇒ scoped variants, statements только про intersection; DISJOINT ⇒ ни duplicate/
consensus/conflict из разницы значений; UNKNOWN ⇒ unresolved. Numeric — по comparison view.
OPAQUE symbolic не классифицируется лексикой. Min vs preferred, разные states, code vs example,
text+figure restatement, same authority/origin/work — не автоматические duplicate/conflict/
independence. Каждый raw hint (`local_duplicate_of/local_conflicts_with`) аудитится:
`CONFIRMED|PARTIAL|REJECTED|UNRESOLVED`; hint ≠ canonical edge.

## PHASE 5 — conflicts (`05_conflict_groups.jsonl`)

Conflict group только при comparable question + known non-empty scope intersection. DISJOINT ⇒
нет; UNKNOWN ⇒ не TRUE_CONFLICT; OVERLAPPING ⇒ только про intersection. Хранить comparable/
differing dimensions, member scopes, numeric/symbolic views, strengths, authority/context,
subtype, unresolved status. Не выбирать победителя/среднее/большинство/web-verify.
До TRUE_CONFLICT — проверить verified qualifier/exception/override/tradeoff dependencies
(general+exception ≠ конфликт). Не изобретать dependency, чтобы спрятать реальный конфликт.

## PHASE 6 — canonical knowledge (`06_canonical_knowledge.jsonl`)

Canonical — semantic hub, не замена вариантов. Один `canonical_claim_id` = один scope-однородный
вариант; OVERLAPPING/DISJOINT/UNKNOWN ⇒ sibling variants одной family. Retain: family/concepts/
entities+roles/relation; activation/target/quantification; canonical branches/context lineage/
zone semantics; dimension/activity/conditions/domain/scope target/runtime capability; overlays +
effective scope signature + member scope bindings; `production_policy_status=
"UNDECIDED_IN_THIS_PIPELINE"`; document/work/lineage/origin/authority/member/assertion/evidence
provenance; membership fingerprint/counts; relationship state; раздельные метрики (document count,
work count, lineage group count, claim-origin count, unresolved); все numeric/symbolic/strength/
authority/utility варианты; Judge-backbone vs supplemental member IDs; source trace, aliases,
review reasons, dependency edges. `AGREEING` = scope-local agreement, не независимое подтверждение.
Не синтезировать одно значение из нескольких, если не truly equivalent representations.

## PHASE 6B — dependency graph (`06b_claim_dependency_graph.jsonl`)

Рёбра: `QUALIFIES|EXCEPTION_TO|LIMITS_APPLICABILITY_OF|OVERRIDES_IN_SCOPE|TRADEOFF_WITH|
VALUE_REFERENCE_TO|PREREQUISITE_FOR|EXPLAINS|ILLUSTRATES`. Verify только при source evidence
(type, direction, target). Similarity/shared entities/proximity/notes — seeds only. Uncertain
target ⇒ provisional, без mandatory closure. Closure defaults: QUALIFIES/EXCEPTION_TO/active
OVERRIDES_IN_SCOPE/TRADEOFF_WITH — bidirectional mandatory; LIMITS_APPLICABILITY_OF — target→modifier;
VALUE_REFERENCE_TO/PREREQUISITE_FOR — по направлению; EXPLAINS/ILLUSTRATES — supplemental.
Scope/condition-aware activation; MISMATCH modifier не mandatory; UNKNOWN included/labeled для
safe interpretation. Fixed-point, cycle-safe; циклы аудируются, не рвутся произвольно.
Граф выражает source semantics, не production precedence.

## PHASE 7 — retrieval records (`07_retrieval_records.jsonl`)

Retrieval units из scope-однородных canonical variants (не family-level unions). Preserve trace/
scope/utility/strength/authority/origin/conflict/dependency metadata + structured filter fields.
`retrieval_text`/`embedding_input_text` из canonical claim + source-faithful aliases + inherited
scope/convention context. Translation/aliases — derived metadata; не переводить/перетирать
quoted evidence/anchors/числа/юниты. EN source + RU queries через multilingual aliases;
structured fields авторитетны.

## PHASE 7B — exhaustive applicability index (`07b_applicability_index.jsonl`)

Completeness-first inventory, не top-K. Индексировать каждый scope-однородный unit: activation,
constraint-target, quantifier, entity roles, relation/endpoints, branches, effective scope,
runtime capabilities, assignment-basis support, utility routing.
Matching: OR между branch'ами, AND внутри; unknown selector ⇒ UNKNOWN (не wildcard); optional
`UNSPECIFIED_BY_SOURCE` ⇒ нет предиката; zone-set — overlap/membership, не ALL; vocabulary
inheritance только через APPROVED edges; role-aware; missing constrained target не деактивирует
presence/cardinality; overlay compatibility explicit; three-valued MATCH/MISMATCH/UNKNOWN (+
conflict state); OPAQUE ⇒ не definite MATCH; runtime evaluability отдельно.
Completeness oracle: сравнение с full-scan reference evaluator по всем active units; для
поддержанных предикатов explicit MATCH set — ноль false negatives. UNKNOWN не считается negative.
Unsupported/opaque dimensions — отдельным отчётом. Все классы source остаются в inventory;
utility решает Judge routing, не retention.

## PHASE 7C — context closure (`07c_context_closure_index.jsonl`)

Closure только из verified canonical family/conflict/dependency relations (не raw hints):
члены/варианты canonical/family для интерпретации; все члены active conflict group (Judge не
видит одну сторону); active verified dependencies по closure policy. Fixed point, cycle detection,
scope/condition activation, stable IDs. Modifier не прячется top-K после выбора seed.

## PHASE 8 — hybrid retrieval config (`08_retrieval_config.json`)

Три плана:
- PLANE A `CONSTRAINT_ENUMERATION/COMPLETENESS_FIRST`: перечислить ВСЕ применимые source
  constraints для структурного runtime-контекста; без top-K как гейта; buckets:
  `definite_matches`, `evaluable_definite_matches`, `contextual_matches`,
  `cross_scope_source_references`, `applicable_but_not_evaluable`, `possible_unknowns` + routing
  views (`source_constraint_guidance_matches`, `source_semantic_guidance_candidates`,
  `source_supplemental_references`); гидрировать canonical + mandatory closure. Relevance
  сортирует, не удаляет.
- PLANE B `DISCOVERY_QA/RELEVANCE_FIRST`: BM25 + vector + exact aliases + structured boosts,
  fusion/reranking; фильтры open-world (absent/unknown ≠ negative, если query явно не требует
  known mismatch).
- PLANE C `LAYOUT_JUDGE_CONTEXT`: bounded Judge context из authoritative backbone + selected
  guidance + closure. Входы: `layout_fact_snapshot` (детерминированная геометрия),
  `validator_snapshot`, `project_context`, design/user goals. Раздельные buckets (mandatory
  in-scope/evaluable, applicable-but-not-evaluable, contextual-unverified, cross-scope,
  unknown-scope, semantic/modeling guidance, supplemental). Порядок: (1) production validators
  отдельны и авторитетны для PASS/FAIL; (2) PLANE A enumeration; (3) PLANE B под token budget;
  (4) closure до fixed point; (5) preserve strength/scope/uncertainty/provenance; (6) example/
  history не становится P1 из-за operational-соседа. Judge bundle: traceable IDs, scope,
  conditions, authority/origin, conflict/dependency context.
Geometry boundary: runtime-геометрия — только из RemLab geometry/validator state, не из
retrieval-прозы. Embeddings: model/provider/version, template, language handling, dimensions,
normalization, batching, checksum/config; top-K/fusion/rerank — tunable config.

## PHASE 9 — eval (`09_eval_queries.jsonl`) — ⚠️ ОБРЕЗАНО ЗДЕСЬ

Frozen auditable eval set: synthetic + verified real-source; synthetic помечен; production-метрики
требуют verified frozen holdout. Далее в оригинале следовала «Required coverage matrix:» — текст
не получен. Реконструкция требований (по контракту артефактов и логике фаз): покрытие обоих
retrieval-планов (enumeration completeness + discovery relevance), RU/EN запросы, scope edge
cases (unknown/mismatch/overlay), closure-кейсы (конфликт/зависимость обязаны подтянуться),
negative controls; метрики recall/precision@K, MATCH-полнота против oracle; результаты — в
`10_quality_report.md`.

## PHASE 10 — quality report (`10_quality_report.md`) — реконструкция

Сводный аудит качества: счётчики фаз и гейтов, целостность, покрытие, unresolved/review
инвентарь, метрики eval, известные ограничения, санкционированные отклонения от спеки.

## PHASE 11 — next stage plan (`11_next_stage_plan.md`) — реконструкция

План будущего redesign RemLab rules НА ОСНОВЕ KB, без выполнения redesign: как canonical/
conflict/dependency слои мапятся на кандидатов в `services/planner-solver/rules/*.json`, процесс
верификации и решения владельца, интеграция с constraint-contract CI, Judge-слой. Только план.
