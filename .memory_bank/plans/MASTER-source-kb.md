---
workstream: layout-knowledge
slug: MASTER-source-kb
title: "MASTER: Source Knowledge Base — Mitton/Nystuen 2016 → REMLAB_INTERIOR_SOURCE_KB (KB0–KB9)"
status: draft
created: 2026-08-10
updated: 2026-08-10
completed:
---

## Цель

Построить воспроизводимую, audit-friendly **source knowledge base** из извлечённых JSON-пакетов
книги «Residential Interior Design: A Guide to Planning Spaces» (Mitton & Nystuen, 3rd ed., 2016):
lossless merge → атомарные claims со стабильными ID → реестры (словарь/авторитеты/scope) →
канонические семьи/конфликты/зависимости → retrieval-слои (полнота + релевантность) → eval →
committed snapshot. **Production-правила солвера НЕ трогаем** — на выходе только
`11_next_stage_plan.md` (план будущего редизайна правил, отдельный цикл план→«деплой»).

## Источник задачи

Промпт владельца 2026-08-10: скачать архив (13 JSON-пакетов, `CHAPTER_KNOWLEDGE_PACKAGE` v3.2),
распаковать в проект, построить KB по детальной спеке (фазы 0–11, инварианты A–G, контракты
run/state/ID). Спека сохранена: `remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md` — **она
нормативный контракт этого плана** (здесь только волны/гейты/решения).
⚠️ Спека обрезана лимитом чата внутри фазы 9 — см. «Открытые вопросы» №1.

## Контекст: что уже есть (профилирование 2026-08-10)

Корпус: `remlab_knowledge_db_v1/sources/RID_MITTON_NYSTUEN_2016_3E/` — 13 пакетов, ~11 МБ,
главы 1–10 **встык по master-страницам 15–259, без дыр и перекрытий** (гл. 4 — 3 сегмента,
гл. 6 — 2). Итого: **1729 records · 2559 measurements · 3146 evidence · 4455 entities ·
1954 contexts · 137 excluded · 287 review-items**. Скрипты профилирования —
`remlab_knowledge_db_v1/scratch_profile/`.

Здоровье корпуса (важно для гейтов):
- ссылочная целостность measurement→evidence/context — **0 нарушений**; счётчики
  chapter_summary сходятся 116/117 (единственное расхождение объяснено: ch2 R049 —
  флаг на уровне measurement);
- нормализация значений: 95.4% точных, ~60 в пределах печатного округления, **20 расхождений
  >3% — почти все опечатки самой книги, зафиксированы в conversion_note** (инвариант A1:
  сохраняем как есть + классификация CONFLICTING в фазе 2B); 1 подозрительная 10×-ошибка
  экстракции (ch8 R037, 72000 sq ft → 668.9 м²) — кандидат в EXTRACTION_REVISION_CONFLICT;
- **аномалии, которые Phase 0 фиксирует как derived metadata (raw не трогаем):**
  битые `segment_index/segment_total` у сегментов гл. 4/6 (None; «1/1» у ch6_seg2), опечатка
  имени файла `ch4_seg3ofU3`, `coverage_complete=false` у гл. 3 (не было визуального прохода),
  `source_collection_id=null` во всех пакетах (identity задаётся predeclared-маппингом спеки);
- словарь мал для корпуса: `relation_type='other'` у 54% records (у 606 есть
  `source_relation_label` — сырьё), `dimension_type` OTHER+UNKNOWN 47%, **636 уникальных
  proposed_entity_type** (хвост: доступность/ADA, лестницы, инженерка), qualifier-поля
  (`mobility_context` и др.) и ~880 уникальных condition-строк — free-text;
- авторитеты не нормализованы: **IRC в 8+ написаниях (~95 records), 101 уникальная пара
  имя|издание**; топ: IRC 2015/2003, NKBA, ANSI/UFAS/ADA, CA Title 24, Hall, Panero/Zelnik;
- дубли/конфликты размечены **только внутри файлов**: 38 dup-записей + 48 conflict-записей
  (56 ссылок-рёбер), все резолвятся; меж-сегментных связей нет — их обязан находить candidate
  graph (фаза 3E);
- `context_fingerprint` не уникален (ch4_seg3: коллизии ×14) — только группировка, не ключ;
- полезное сырьё: 65 top_findings, 143 relationship_expression, 171 HARD_CANDIDATE /
  810 SOFT / 332 SEMANTIC / 416 REFERENCE_ONLY.

## Отношение к ADR-0082 («инжест Panero/Time-Saver целиком» отклонён)

Это НЕ тот отклонённый подход, и план обязан удержать разницу:
1. Отклонён был **инжест чисел напрямую в production-правила** без доказанной необходимости.
   Здесь production-слой (`services/planner-solver/rules/*.json`) **не меняется вообще** —
   `production_policy_status="UNDECIDED_IN_THIS_PIPELINE"` у каждого canonical claim.
2. Строится **source-слой с провенансом** — то, чего не хватало в вопросе №2 рефери
   (referee-v5-brief: «камин — какой канон, есть ли источник?»): каждое число с
   evidence-локусом (страница/фигура/таблица), силой claim'а, конфликтами и авторитетом
   (IRC ≠ мнение авторов).
3. Прямое продолжение выигравшей методологии `domain/occupancy-rules.md` (ресёрч → свод с
   пруфами → верификация → конфликты владельцу → числа в JSON), но механизированное и
   масштабируемое на N книг (правило владельца «только масштабируемые решения»).
4. Явный заказ владельца 2026-08-10 — новое решение, а спека сама запрещает переписывать
   правила сейчас (шаг 9: «только план redesign»).
5. **Урок 54 остаётся в силе**: числа из источников питают ПРОВЕРКИ/пороги, но не заменяют
   процедуру выбора схемы — это ограничение обязана нести и `11_next_stage_plan.md` (KB9).

## Критическая оценка спеки (обязательный раздел; ADR-0077 — расхождения только с пруфом)

Спека (вероятно, внешняя GPT-заготовка) в целом **высокого качества и внутренне согласована**;
принимается как контракт. Корректировки — все с обоснованием:
1. **Обрезка**: текст оборвался в фазе 9 («Required coverage matrix:»). Фазы 9–11
   реконструированы по output-контракту (см. спеку, помечено). Запросить хвост у владельца;
   до получения волна KB8 исполняется по реконструкции.
2. **`candidate_pair_recall=100%` против verified positive pairs** — на bootstrap'е таких пар
   не существует, а мерить recall набором, вшитым в каналы генерации, циркулярно. Интерпретация:
   в KB5a создаём и замораживаем seed-набор ПАР (рёбер): 38 dup + 56 conflict из local hints
   (аудированные) **+ ≥50 вручную верифицированных кросс-сегментных пар** (гл. 4 seg1↔seg3,
   гл. 6 seg1↔seg2 — найдены независимо от каналов). Гейт двойной: 100% полным UNION'ом И
   **абляция: с выключенным hint-каналом остальные каналы находят ≥95%** (per-channel ablation
   recall — в отчёт). Набор наследуется следующими прогонами.
3. **`expected_input_manifest` не поставлен** ⇒ `collection_input_completeness="UNKNOWN"`
   (по спеке). Фактически главы 1–10 покрыты встык; приложения книги (в review-queue есть
   отсылки «deferred to Appendix G») не поставлены. Предложить владельцу подтвердить манифест
   «10 глав = основной корпус, приложения — опционально позже» (вопрос №2).
4. **Multi-document контракт при одном документе**: реестры/ID проектируем по спеке
   (multi-doc), но НЕ строим спекулятивную функциональность corroboration-агрегации по многим
   документам сверх требуемого — у нас 1 документ, 1 origin-группа. YAGNI без нарушения схем.
   **Legacy-миграции спеки** (CITED_AUTHORITY_PROVISION→CITED_EXTERNAL_ASSERTION;
   canonical_source_collection_id→KB): для BOOTSTRAP_FULL без prior state — **N/A**, но проверка
   на оба legacy-значения реализуется в коде загрузки prior state (KB0), чтобы контракт был
   исполним при будущем REBUILD.
5. **Embeddings/хранилище**: спека требует конфиг/чексуммы, не конкретную БД. Решение:
   файловая KB (JSONL + npz), **без pgvector на этом этапе** — pgvector в проде есть лишь как
   задел (нет vector-колонок), офлайн-пайплайну БД не нужна, детерминизм и rollback проще на
   файлах. Модель фиксируется РАНО (KB0, пин зависимостей) — vector-канал нужен уже в KB5a;
   `08_retrieval_config.json` (KB7) записывает использованный пин, не выбирает заново.
6. **LLM в семантических фазах** (проекция RECORD_SEMANTIC, вердикты пар, зависимости):
   спека требует «код, не LLM» только для механики — семантическая классификация без LLM
   невозможна. Правила: test-before-spend (пилоты, счётчики отказов, молчаливый except
   запрещён), adversarial-верификация конфликтов/дублей вторым проходом. **Канонический
   носитель LLM-выводов — дистиллированные вердикты-JSONL в committed snapshot (в git, в
   artifact_hash_manifest); rerun реплеит их по промпт-хэшу.** Сырой кэш ответов — локальная
   оптимизация, НЕ state.
7. **Стабильность DERIVED_ID при LLM-зависимых подписях (критично, инвариант G43):**
   family/scoped_variant-подписи собираются **только из персистентных registry-записей**
   (vocabulary_map с origin_anchor, замороженные normalization-mapping'и в git) — никогда
   напрямую из LLM-ответов. LLM пишет в registry один раз → review → freeze; далее подпись —
   чистая функция от registry. Смена модели/промпта = новая extraction-версия вердиктов и
   explicit supersedes-миграция registry, не remint ID. Гейт в KB5b: пересборка подписей с
   ХОЛОДНЫМ LLM-кэшем из замороженных registry даёт бит-в-бит те же ID.
8. **Юр./copyright статус** извлечённых знаний — по CLAUDE.md не реализуем юр. логику:
   TODO владельцу (вопрос №4). KB хранит короткие anchor-цитаты как evidence — практика
   уже принятая в `guides/layout-mined-rules.md` (с лицензионной легендой).

## Архитектура решения

- **Код**: `services/knowledge-db/` — Python 3.14 (факт VM), pydantic v2 + jsonschema ≥4.19
  (Draft 2020-12) + `rfc8785` (JCS), pytest; зеркало конвенции `services/planner-solver/`
  (README, requirements с пинами, tests/). Venv: `~/venvs/kdb` (pip только в venv).
  CLI-раннер: `python -m kdb run --mode BOOTSTRAP_FULL --through <phase>` — фазы идемпотентны,
  каждая пишет артефакт + валидирует + гейт; провал гейта = stop (exit code), стиль
  `tools/memory-audit.mjs` (--check/--json, exit code как гейт).
- **Данные**: `remlab_knowledge_db_v1/` — `sources/` (raw, immutable), `spec/`,
  `runs/<run_id>.staging/` → commit → `runs/<run_id>/` + `CURRENT`-указатель.
  **Git-политика** (уточнить у владельца, вопрос №3; рекомендация): в git — sources, spec, код,
  схемы + из snapshot'а: `00/01/02/02a/03*/05/06/06b/09/10/11`, `pipeline_state.json`,
  хэш-манифесты и **дистиллированные LLM-вердикты**; вне git (.gitignore) — `*.staging/`,
  `04a` (крупный, регенерируем из вердиктов), `07/07b/07c` (регенерируемы детерминированно),
  embeddings `*.npz`, сырой LLM-кэш; prior snapshots старше N−1 — диск/бэкап, не git.
- **LLM**: Gemini (`GEMINI_API_KEY`, REST — паттерн `lib/providers/gemini.ts`, py-клиент в
  `kdb/llm.py`): flash для батч-классификации, structured output по JSON Schema, retries,
  счётчики отказов, дисковый кэш `(model, prompt_sha256) → response`. Никаких массовых
  прогонов без пилота с замером объёма и стоимости.
- **Embeddings**: fastembed (паттерн `tools/scout/style_score.py`); модель-дефолт
  `paraphrase-multilingual-MiniLM-L12-v2` (~470 МБ) — **e5-large запрещён: RAM VM 5 ГБ**;
  кэш моделей на диск, НЕ /tmp (tmpfs); пины `fastembed==0.8.0`/`onnxruntime==1.28.0`
  (проверены на Python 3.14.4 этой VM).
- **Детерминизм**: механика — чистые функции над файлами; сортировки стабильные; identity без
  таймстампов; LLM-недетерминизм изолирован в замороженных registry/вердиктах (см. крит. №7).
- **Выкатка**: офлайн-подсистема — прод-образ не меняется, `./deploy.sh` НЕ запускается
  (на DEV-VM он и запрещён — OOM); но стандарт «прод не позади main» соблюдаем: **волна =
  зелёные гейты + commit + `git push origin main`** (CI-гейт).

## Волны (каждая = commit+push, зелёные гейты; строго по порядку)

### KB0 — каркас + PHASE 0 preflight
Скелет `services/knowledge-db/` (canonical.py: JCS+SHA256+DERIVED_ID; io.py: duplicate-key-aware
парсер, JSONL-писатель с parse-back; state.py: вкл. проверку legacy-значений prior state;
schemas/ + schema_registry; пин embeddings-модели в requirements). Phase 0:
`source_document_registry` (predeclared-маппинг RID_MITTON_NYSTUEN_2016_3E; НЕ из имён файлов),
segment-reconciliation по master-страницам (derived; фиксирует битые поля сегментов и ofU3),
валидация 13 пакетов, `00_input_manifest.json` (run_mode=BOOTSTRAP_FULL, completeness=UNKNOWN,
все аномалии). **Гейт:** 13/13 пакетов валидны и active_for_semantic_projection=true; повторный
прогон бит-в-бит идентичен.

### KB1 — PHASE 1 lossless merge
`01_raw_merged.json`: logical_package_key / artifact_uid / package_content_uid, observation UIDs
с record-scope; проверка на exact-дубликаты (не ожидаются). **Гейт:** счётчики до/после равны
(1729/2559/3146/1954/137/287 + 4455 entities); уникальность UID; raw-мутаций ноль (байтовое
сравнение вложенных объектов).

### KB2 — PHASE 2/2A атомы + стабильные ID (предварительная эмиссия)
In-memory проекция: MEASUREMENT_BOUND (2559), RECORD_SEMANTIC (записи без измеримых пропозиций,
~700–800; LLM-assist только для выбора supporting contexts/evidence), COMPOUND_EXPLICIT (часть
из 143 relationship_expression). Затем 2A: SELOC-локусы (master page + section + figure/table +
anchor-fingerprint), assertion slots, mint `source_assertion_uid`/`atomic_claim_id`; ch8 R037
(10×) → `EXTRACTION_REVISION_CONFLICT`-кандидат. Ожидание: ~3200–3600 атомов.
**Пилот гл. 1 ДО корпуса** с заранее заданными порогами провала: отчёт отказов LLM;
**collision-rate slot-подписей RECORD_SEMANTIC-атомов** (коллизии ≠ осознанные compound —
провал пилота, чинить подпись). `02_atomic_claims.jsonl` пишется как ПРЕДВАРИТЕЛЬНЫЙ
(финализация полей — KB3). **Гейт:** каждый measurement ровно в одном атоме (или явный
compound); все атомы резолвят observation UIDs; повторный прогон — те же ID; счётчики
observation/locus/assertion раздельны.

### KB3 — PHASE 2B/2C/2D/2E: обогащение и финализация 02_atomic_claims.jsonl
Артефакт волны — **пере-эмиссия `02_atomic_claims.jsonl` с сохранением стабильных ID**
(поля numeric/symbolic views, activation/target/quantification, utility — обязательные поля
финальных атомов по спеке). Numeric comparison view (Decimal, пиновая таблица конверсий с
версией; ожидаем ~95% CONSISTENT, ~20 CONFLICTING с подтипами); symbolic AST для 143 выражений
(allow-list, без eval); activation/target/quantification + роли entity-mentions
(детерминированно из measurement subject/reference где можно, LLM-assist на остатке — через
записываемые в registry нормализации, см. крит. №7); utility-классы; **нормализация free-text
condition-строк (~880 уникальных) в поддержанные предикаты** — метрика `predicate_coverage`.
**Гейт:** 100% измерений имеют comparison view или явный AMBIGUOUS; 0 eval-ов; классификация
консистентности сходится с профилем ±1%; predicate_coverage ≥60% непустых condition
(иначе PLANE A выродится в possible_unknowns — см. риски).

### KB4 — PHASE 3/3B/3B2/3C/3D реестры
`03_vocabulary_map.json` (62 CORE + reconciliation 636 proposed → концепты со статусами,
unresolved допустим; **registry замораживается — подписи семей строятся только из него**);
`03b` authority registry (IRC→одна identity, издания 2015/2003/unknown РАЗДЕЛЬНО; vague
«local codes» — unresolved, не именовать); `03b2` origins (CITED_CODE/STANDARD →
CITED_EXTERNAL_ASSERTION; BOOK_DESIGN_GUIDANCE/AUTHOR_EXAMPLE → ANALYZED_SOURCE_AUTHORSHIP;
composite — раздельно); `03c` scope registry + runtime evaluability (что RemLab сейчас умеет
оценивать: комнаты/зоны/клиренсы — да, лестницы/ADA-подъёмники — нет); `03d` overlays
(кандидаты: whole-book «US residential», unit-конвенции; только при source evidence).
**Гейт:** каждый атом — резолвленный origin; 0 атомов с authority-строкой без authority-ID
(или explicit unresolved); реестры идемпотентны.

### KB5a — PHASE 3E: candidate graph + вердикты пар + аудит hints
UNION каналов (signature-блоки, entity/dimension-блоки, numeric-совместимость, BM25, векторный,
local hints как seeds, authority-блоки; сегменты гл. 4/6 обязаны связаться). **Бюджет пар —
явный конфиг per-channel top-k капов, суммарно ≤150k**; детерминированная предклассификация
закрывает без LLM numeric-идентичные EXACT_DUPLICATE-кандидаты и DISJOINT-scope пары (ожидаемо
30–50% объёма); остаток — LLM-вердикты батчами (flash, кэш). **Пилот-партия: замер фактического
UNION-размера и экстраполяция стоимости ДО полного прогона; эскалация владельцу при >200k пар
или >$60.** Adversarial второй проход по TRUE_CONFLICT/DUPLICATE. Аудит всех 38 dup + 56
conflict hints (CONFIRMED/…). Seed-набор пар (крит. №2) — заморозить в `eval/`.
**Гейт:** candidate_pair_recall=100% полным UNION'ом + абляционный recall ≥95% без
hint-канала; 100% hints аудированы.

### KB5b — PHASE 4/5/6/6B: семьи, конфликты, canonical, зависимости
Семьи по signature из замороженных registry (не по связности), scope-comparability per-pair ДО
классификации, конфликт-группы (без победителей), canonical variants (scope-однородные),
dependency graph (verified only при source evidence, cycle-safe closure).
**Гейт:** каждый атом ∈ ровно одной family (или explicit review); 0 canonical с гетерогенным
scope; **ID-стабильность: пересборка подписей с холодным LLM-кэшем из замороженных registry —
бит-в-бит те же family/conflict/canonical ID**.

### KB6 — PHASE 7/7B/7C retrieval-слои
`07_retrieval_records.jsonl` (RU-алиасы переводом только метаданных — цитаты/числа не трогаем);
`07b_applicability_index.jsonl` + **completeness oracle** (полноскановый reference evaluator;
гейт: 0 false negatives на поддержанных предикатах, UNKNOWN ≠ negative); `07c` closure
(fixed-point, конфликт всегда обеими сторонами). **Гейт:** oracle зелёный; closure без потерь
mandatory-рёбер на выборке ручных кейсов; отчёт unsupported/opaque-размерностей.

### KB7 — PHASE 8 гибридный retrieval
`08_retrieval_config.json`: PLANE A (enumeration, buckets по спеке), PLANE B (BM25+vector+fusion,
open-world фильтры), PLANE C (контракт Judge-бандла; **вход только layout_fact_snapshot/
validator_snapshot — геометрию из прозы не выводим**). Конфиг записывает уже использованный
embeddings-пин (KB0). Минимальный CLI: `kdb query --plane A|B --context <json>`.
**Гейт:** PLANE A на 3 ручных runtime-контекстах (гостиная/спальня/кухня) возвращает полные
bucket'ы, сверенные с oracle, И **доля definite_matches содержательна** (не пустые definite при
толстом possible_unknowns — иначе predicate coverage чинить, не гейт ослаблять).

### KB8 — PHASE 9/10 eval и отчёт качества
`09_eval_queries.jsonl`: synthetic (помечены) + real из 65 top_findings и review-кейсов; RU+EN;
edge-кейсы scope/unknown/closure; negative controls. Прогон → метрики → `10_quality_report.md`
(гейты, покрытие, unresolved-инвентарь, ограничения, отклонения, ablation-таблица каналов).
**Гейт:** eval заморожен (fingerprint в state); отчёт полон.

### KB9 — commit + план следующего этапа
Commit-протокол по спеке (payload-хэши → snapshot_content_root → COMMITTED → внешний
pipeline_state_sha256 → CURRENT); `11_next_stage_plan.md` — план редизайна правил RemLab
(маппинг canonical→кандидаты `rules/occupancy.json`/`zones.json` с пруфами и силами, конфликты
на решение владельца, прогон constraint-contract CI, место Judge-слоя; **с учётом урока 54:
KB питает проверки и пороги, не процедуру выбора схемы; только план**).
**Гейт:** snapshot валиден как prior state для будущего `REBUILD/INCREMENTAL`; субагент `verify`
(план >5 файлов) прогнан ДО `/memory-check`.

## Скоуп — что входит
- Пайплайн фаз 0–11 по спеке для одного документа (RID_MITTON_NYSTUEN_2016_3E), BOOTSTRAP_FULL.
- Все 24 обязательных артефакта + схемы + гейты + тесты (pytest) + README.
- LLM-фазы с пилотами и дистиллированными вердиктами; embeddings + BM25 + CLI-запросы.
- Memory Bank: новая область `core/knowledge-db.md`, ADR о подсистеме, фиксация в decision tree.

## Скоуп — что НЕ входит
- Изменение production-правил/кода солвера (`services/planner-solver/**` не трогаем).
- Интеграция Judge в прод-пайплайн; веб-верификация стандартов/библиографии (запрещено спекой).
- Инжест других книг/изданий (контракт готов, но corpus — одна книга).
- Юр./copyright оценка (TODO владельцу); pgvector/БД-хранилище.
- Приложения книги (Appendix A–G) — нет во входе; только фиксация ссылок на них.
- Деплой на сервер (`./deploy.sh`) — офлайн-подсистема, прод-образ не меняется.

## Файлы к изменению
- [ ] `services/knowledge-db/**` — новая подсистема (kdb/, schemas/, tests/, README, requirements)
- [ ] `remlab_knowledge_db_v1/runs/**` — артефакты прогонов (staging→committed)
- [ ] `remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md` — создан (контракт)
- [ ] `.gitignore` — `*.staging/`, `04a`/`07*`-крупняк, npz, сырой LLM-кэш
- [ ] `.dockerignore` — исключить `remlab_knowledge_db_v1/` и `services/knowledge-db/` из
      build context прод-образа
- [ ] `.memory_bank/core/knowledge-db.md` — новая Tier-1 сводка (обязательна: новая область)
- [ ] `.memory_bank/decisions.md` — ADR: source-KB подсистема, отношение к ADR-0082
- [ ] `.memory_bank/plans/MASTER-source-kb.md` — этот план
- [ ] (KB9) `.memory_bank/project-state.md`, `core/layout.md` — ссылки на KB

## Задачи
- [ ] KB0 каркас + preflight (гейт: 13/13, детерминизм)
- [ ] KB1 merge (гейт: счётчики/UID/иммутабельность)
- [ ] KB2 атомы + стабильные ID (пилот гл. 1 с порогами → корпус)
- [ ] KB3 обогащение/финализация атомов + predicate coverage ≥60%
- [ ] KB4 реестры + заморозка (подписи только из registry)
- [ ] KB5a candidate graph + вердикты (бюджет ≤150k пар, эскалация >200k/> $60) + recall-гейт с абляцией
- [ ] KB5b семьи/конфликты/canonical/зависимости + ID-стабильность-гейт
- [ ] KB6 retrieval + applicability oracle + closure
- [ ] KB7 planes A/B/C + CLI (+definite_matches-гейт)
- [ ] KB8 eval + quality report
- [ ] KB9 commit snapshot + 11_next_stage_plan.md + verify-субагент

## Критерии приёмки
- [ ] pytest `services/knowledge-db` зелёный; `pnpm typecheck/lint/test/build` не задеты (TS не трогаем)
- [ ] Все обязательные артефакты сгенерированы, схемы 2020-12 валидны, parse-back чист
- [ ] Гейты всех волн зелёные, включая: Phase-1 счётчики равны профилю; recall=100% (+абляция
      ≥95%); oracle 0 FN; ID-стабильность KB5b; snapshot COMMITTED и валиден как prior state
- [ ] LLM: пилоты до массовых прогонов, счётчики отказов в отчёте, 0 молчаливых except;
      дистиллированные вердикты в snapshot/git
- [ ] Raw sources байтово нетронуты (хэши в манифесте)
- [ ] Не задеты файлы вне scope (в т.ч. `services/planner-solver/**`)

## Риски
- **Объём LLM-вердиктов**: реалистичная оценка UNION до капов — 100–200k пар; с капами ≤150k и
  детерминированной предклассификацией — LLM-остаток ~50–100k; стоимость на flash **~$10–40**
  (не «единицы $»); точная цифра — из пилота KB5a; триггер эскалации владельцу: >200k пар или >$60.
- **Недетерминизм LLM / нестабильность ID** — закрыт крит. №7 (замороженные registry +
  ID-стабильность-гейт KB5b); смена модели = supersedes-миграция, не remint.
- **Free-text условия** (~880 уникальных): без нормализации PLANE A вернёт пустые
  definite_matches при формально зелёном oracle (UNKNOWN ≠ negative) — закрыто гейтами
  predicate_coverage (KB3) и definite_matches (KB7).
- **Пере-инжиниринг** (спека огромна): волны строго по порядку, каждая с работающим артефактом;
  ничего «на вырост» сверх схем спеки (крит. №4).
- **Обрезанная фаза 9** — KB8 по реконструкции; при получении хвоста — diff и допилка.
- **RAM VM 5 ГБ** — только компактные ONNX-модели (MiniLM), кэш на диск; тяжёлые прогоны
  ACC-стиля не требуются.
- Правки сервера/прода не требуются вовсе — VPN-нода не затрагивается.

## Открытые вопросы владельцу (не блокируют KB0–KB3)
1. Прислать хвост спеки (после «Required coverage matrix:» в фазе 9 + фазы 10–11), если он есть.
2. Подтвердить `expected_input_manifest`: 10 глав = полный основной корпус; приложения A–G —
   будут ли извлекаться позже?
3. Git-политика больших артефактов — рекомендация в «Архитектуре» (в git: реестры/canonical/
   state/вердикты; вне git: 04a/07*, регенерируемые): ок?
4. Copyright-статус KB с цитатами-якорями из книги (юр. логику не реализуем — только решение
   о допустимости хранения в приватном репо; прецедент — layout-mined-rules).
5. Бюджет LLM: ориентир $10–40 на полный прогон вердиктов (после пилота — точная цифра;
   эскалация при >$60). Ок?

## Definition of Done — память (без этого `completed` запрещён)
- [ ] Memory Bank обновлён: `core/knowledge-db.md` (новая область в decision tree), `decisions.md`
      (ADR), `project-state.md`, `core/layout.md` (ссылка)
- [ ] «Уроки» заполнены; отброшенные подходы → `core/lessons.md`
- [ ] Субагент `verify` прогнан (план >5 файлов) ДО `/memory-check`
- [ ] `/memory-check` выполнен, audit «чисто»

## Лог выполнения
- 2026-08-10 — архив скачан и распакован в `remlab_knowledge_db_v1/sources/`; корпус
  спрофилирован (6 параллельных отчётов); спека сохранена; план создан (draft)
- 2026-08-10 — адверсариальное ревью 3 критиками (spec-compliance / project-fit / feasibility):
  блокер по ID-стабильности и 3 major-находки внесены в план (крит. №2/№7, KB5a/KB5b,
  predicate coverage, бюджеты/эскалация, пины моделей, .dockerignore, push-политика)

## Completion summary
[при завершении]

### Уроки (ОБЯЗАТЕЛЬНО)
[при завершении]

## Follow-up work
- [ ] Инжест следующих источников (Panero/Time-Saver?) — только после KB9 и решения владельца
- [ ] Интеграция PLANE C с солвером/Judge — отдельный план по `11_next_stage_plan.md`
