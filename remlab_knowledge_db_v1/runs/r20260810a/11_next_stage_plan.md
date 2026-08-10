# 11_next_stage_plan — редизайн правил RemLab на базе SOURCE KB (ПЛАН, без выполнения)

Прод-правила НЕ изменены в этом пайплайне. Ниже — план отдельного этапа (свой цикл план→«деплой» по agent-workflow).

## 1. Инжест следующих источников
- Panero/Time-Saver и приложения A-G текущей книги — тем же SOURCE-пайплайном (INCREMENTAL_UPDATE); кросс-source reconciliation через существующие origin/family-слои (двойной счёт цитат IRC исключён claim-origin идентичностью).

## 2. Расслоение знания перед маппингом
- source consensus / source disagreement (конфликт-группы: 286) / jurisdiction-specific (IRC/ANSI/ADA) / anthropometric-scenario (wheelchair/standing) / examples / semantic guidance — уже размечено (utility, origins, scoped-варианты).

## 3. Классификация КАЖДОГО текущего прод-правила
- Вход: services/planner-solver/rules/*.json (occupancy, zones, severity, weights) + canonical KB (кандидатов с backbone-членами: 1364).
- Классы: supported | unsupported | contradicted | too_strict | too_weak | missing | semantic_only; каждый вердикт — со ссылками на canonical_claim_id + evidence-локусы (страница/фигура).
- Верификация текущих стандартов/кодов — ОТДЕЛЬНЫЙ процесс (в KB web-верификация запрещена).

## 4. Policy-классы (предложение, БЕЗ утверждения)
- HARD | SOFT | semantic/LLM guidance | source/reference-only | reject; предложение готовит агент, УТВЕРЖДАЕТ владелец/рефери (ADR-0077). Урок 54: числа KB питают проверки и пороги, но НЕ процедуру выбора схемы (зона строится атомарным блоком).

## 5. APPROVED PRODUCTION RULE REGISTRY (новый артефакт)
- immutable production_rule_id; supporting/contradicting canonical IDs; approved severity (классы H0/H1/S1/S2 из severity.json); applicability/runtime requirements; version/effective date; approval-провенанс (владелец/рефери). Canonical source DB остаётся immutable.

## 6. Регрессии и Judge
- Прогон layout-регрессий (252 фикс-сцены, acceptance_run) на каждое изменение правила; constraint-contract CI (совместная выполнимость пар) — обязательный гейт (урок 204/ADR-0080).
- Будущий LLM Judge получает ровно layout_fact_snapshot + validator_snapshot + PLANE C бандл (kdb query --plane C); Judge рассуждает о семантике/композиции/недостающих объектах, НИКОГДА не заменяет геометрию; солвер переводит намерения в кандидатную геометрию, точные валидаторы перепрогоняются после каждой итерации.

## 7. Миграции/rollback/гейты
- Версионирование rule-pack + возможность отката (git); человеческое утверждение до прод-деплоя; A/B на приёмке 252 сцены до дефолта.
