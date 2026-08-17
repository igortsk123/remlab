# Session scratch — блокнот захвата на ходу (append-only)

> **Зачем.** Захватывать durable-факт/решение в МОМЕНТ, когда он принят (там он ярче всего),
> а не раскапывать весь диалог на выдохе в конце сессии. `/memory-check` (Этап 1) консолидирует
> эти строки в `.memory_bank/` и очищает блокнот. Это амортизирует дорогой захват и лечит
> «согласованное замерзание» (частый провал: работал → не записал).

> **Как писать.** Принял ADR-значимое/durable (решение, миграция, контракт/API, интеграция,
> смена этапа, неочевидная грабля) → СРАЗУ допиши 1–2 строки СЮДА, не прерывая работу.
> Формат: `- ГГГГ-ММ-ДД — <что> — <почему/куда в память>`. Это НЕ канон, а сырьё для консолидации.

> **Что НЕ писать.** То, что и так в коде/git (структура, разовые правки), и то, что важно
> только для этого диалога. Значения секретов — НИКОГДА (только в `_secrets/`, вне git).

<!-- SCRATCH START — /memory-check переносит обработанное в банк и усекает до этой метки -->
- 17.08 подписи рендера (владелец №2/№15/№18/№19): писать ТОЛЬКО куда повёрнут («→ к ТВ» ≤15°, «под N° к X» при развороте — градусы нужны для 3D/LLM), диван — только к фокусу (ТВ/камин), симметричные предметы (стол обеденный/стул/столик/хранение) без подписи; вырез контура: «пилон/колонна» (внутрь) vs «снаружи» (у эркера/скоса), подпись поверх предметов. Экзамен перезапущен для перерисовки (05:20).
- 17.08 Q6a внедрён: `tools/scout/capabilities.py` (+`rules/capabilities.json` caps-v1) → таблица product_capabilities (tri-state evidence, seat_* vs overall_*, wall_seat_capable/dining_seat_capable/guaranteed_seats/shallow_storage_capable/placement_modes/extension_mechanism_present sleeping; PK, rules_hash/input_hash, дельта); пересчёт в refresh_daily после load3 и в enrich_wait после забора; `--export` → capabilities-index.json; compose2: планировочный слот «банкетка» из индекса (SKU с source_role/planning_role/caps_used/cap_rules_version). Дев-БД: 10516 строк, банкетка 27 (nonton 14/divan 13), dining_seat 13 (только divan.ru с params), shallow 883, ext_mech 124. Codex-критика учтена (`codex-prompts/q6a-capabilities.answer.md`): capability ≠ конверт слота, fail-closed по подтипу, unknown≠false. Ждёт (после экзамена): Item.caps в солвере (модель), Q6b edge_nook.
- 17.08 владелец №31 (столик не по центру): не шаблон, а выбор beam — гипотеза с допуском (+axis_shifted, без декора) выиграла у канона по терму circulation (15.7 vs 16.8); «столик по центру» в ключе не представлен. Codex (`codex-prompts/q5-axis-shift-tier.answer.md`): ярус template_degradation (max_level,count: 0 канон / 1 зазор 36 / 2 сдвиг|32|48) + main_path_violations — ВЫШЕ мягких термов в v1 и v2; optional-зоны НЕ считать (negative space легален, ADR-0091); перечисление: канон всех форм, ≤1 деградированный на форму; axis_shifted → table_axis_shifted (+gapNN пометки). Внедрено (патч `codex-prompts/q5_degradation_patch.py`), set16-base — по центру; до патча 12 сцен с axis_shifted.
- 17.08 подписи v2 (владелец №55): «под N° к X» только при диагональной позе (rot не кратен 90); галерея перерисована и опубликована.
