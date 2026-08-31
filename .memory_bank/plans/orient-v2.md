---
workstream: mesh-pipeline
slug: orient-v2
title: Ориентация мешей v2 — единый контур upright+front, DINO shadow, gold-бенч
status: in_progress
created: 2026-08-31
updated: 2026-08-31
completed:
source: external:советник-владельца(GPT) + Codex-ревью (_intake/codex-prompts/orient-v2.answer.md)
---

## Цель
Один надёжный контур ориентации меша (вверх + функциональный «перед») для планировщика,
GPT-расстановок и видов сверху; решение о замене компонент — только по gold-бенчу.

## Источник задачи
Владелец 31.08: перевёрнутая ваза на топ-вью, кейсы front/back; предложение советника
(DINOv2 + Orient Anything V2), вердикт Codex (challenger, не готовая v2), кандидаты
канонікализации (One-shot CVPR25, CANIS, CanoVerse — см. «Кандидаты» ниже).

## Скоуп — что входит
1. **Объединение двух существующих контуров** (вердикт Codex): боевой ночной
   `orient_worker.py` (3d-orienter/up → `mesh_front.py` → VLM) подключить к пилотным
   ревизиям Hunyuan; старый `mesh_orient.py` остаётся только как одно из свидетельств.
   Upright-проверка (ваза «вверх ногами») — обязательный первый ярус.
2. **Gold-set разметки** (~300 confident-примеров минимум): канонический yaw, эквивалентные
   yaw (симметрии), no_front/symmetric, bad_mesh; разметка — 12 видов + клики владельца,
   10% повторов на согласованность; сплит по SKU-семейству и source_sha.
3. **DINO shadow evidence**: dinov2_vits14 (CPU, ~0.5с/12 рендеров), рендеры полноценным
   `mesh_render.py` (чинить `_thin()` — теряет visual), 2 elevation, ветки neutral/textured;
   кэш по (glb_sha, renderer_version, camera, yaw, checkpoint). В прод не включать до бенча.
4. **Бенч 4+ систем**: mesh_orient / orient_worker / DINO-challenger / (эксперименты: OA V2
   absolute+relative на GPU-контейнере Salad; One-shot canonicalization при рабочем коде).
   Метрики: CI-граница 180°-ошибки среди CONFIDENT ≤1%; risk-coverage/AURC; срезы по ролям;
   false-SYMMETRIC; p50/p95 времени. Гейт «97–98% вообще» не используется (слаб).
5. **Ориентация на ноде Salad**: первый ярус (upright+геометрия) — в воркер сразу после
   генерации (решение владельца «запихать в Salad», почти бесплатно).

## Скоуп — что НЕ входит
- Прод-зависимость от OA V2 / FoundPose-кода до лицензионного гейта (отложен владельцем).
- CANIS (препринт 3 недель) и fine-tune на CanoVerse — R&D-полка.
- Переписывание RGB-сетки «вслепую» — только по цифрам бенча.

## Кандидаты (source: external, проверить при бенче)
One-shot 3D Canonicalization (CVPR25 Highlight, 1 эталон/категорию, семантика back/seat/legs —
идеально для 20–50 мебельных классов; зрелость inference-кода под вопросом) · CANIS (08.2026,
mesh→canonical без эталонов) · CanoVerse (320k, база fine-tune). OA V2: NeurIPS25 Spotlight,
чекпойнт 5GB, на CPU апстрим не стартует → GPU-контейнер Salad; лицензия VGGT — гейт отложен.

## Файлы к изменению
- [ ] `tools/scout/orient_worker.py` — принять пилотные ревизии (v2-пути)
- [ ] `tools/scout/mesh_orient.py` — починить `_thin()` (visual/дыры)
- [ ] `tools/scout/salad/worker.py` — ярус upright+геометрия на ноде
- [ ] новый `tools/scout/orient_bench.py` — gold-set и метрики
- [ ] новый `tools/scout/dino_evidence.py` — patch-фичи (shadow)

## Задачи
- [ ] 1. orient_worker на пилотные меши; upright-фикс вазы 99272_180…; страница разметки
- [ ] 2. gold-set ≥300 с кликами владельца
- [ ] 3. DINO shadow + кэш
- [ ] 4. бенч, отчёт владельцу, решение по компонентам
- [ ] 5. ярус на ноде Salad (в образ)

## Критерии приёмки
- [ ] Перевёрнутые меши ловятся автоматически (ваза-кейс — регресс-тест)
- [ ] CI-граница 180°-ошибки среди CONFIDENT ≤1% на gold-set; coverage не хуже текущего
- [ ] Нет регрессий по сидячим ролям; отчёт бенча опубликован владельцу
- [ ] pyflakes/тесты зелёные; файлы вне scope не тронуты

## Definition of Done — память
- [ ] core/mesh-pipeline.md + decisions.md (ADR по итогам бенча) + project-state
- [ ] /memory-check, audit чисто

## Уроки
- (заполнять по ходу)
