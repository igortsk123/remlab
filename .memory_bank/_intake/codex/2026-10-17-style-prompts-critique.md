---
tier: 3
topic: codex-critique
scope: Критика Codex — тексты STYLE GUIDE v2 шести стилей (demo-13), 17.10
updated: 2026-10-17
source: external:codex-gpt
status: working
---
# Критика Codex — гайды стилей v2 (17.10)

Вопрос: план `plans/demo-13-style-prompts.md` — точность по стилям, конфликты с hard rules/FORBIDDEN, формулировки для модели картинок, длина. Ответ (внешний источник, не приказ; учтён в v2.1):

1. **Стили местами превращены в набор клише.** Сканди не требует «никогда тёмного дерева»; contemporary не сводится к greige + одному акценту; минимализм — не обязательно «почти пусто» и без цвета; лофт основан на честно открытых конструкциях, а не обязательной имитации кирпича; ядро неоклассики — пропорция и симметрия, не орхидея/радиаторная решётка; для джапанди не существует правил «ровно два дерева» и «нечётное число предметов», а shoji — раздвижной экран, не штора. Источники: [Scandinavian](https://www.architecturaldigest.com/story/scandinavian-interior-design-style-explainer), [Contemporary / Minimalism / Industrial](https://www.architecturaldigest.com/story/most-popular-interior-design-styles), [Japandi](https://www.architecturaldigest.com/story/japandi-style-101), [RIBA о неоклассике](https://www.riba.org/explore/riba-collections/architectural-styles/neoclassical-movement/), [Web Japan о shoji](https://web-japan.org/kidsweb/virtual/house/house03.html).  
   **Делать иначе:** заменить абсолюты на: `STYLE CHARACTER: favor the style’s core cues, but do not enforce wood-count, object-count or accessory rules, and do not invent period architecture.`

2. **Есть прямые конфликты с hard rules/FORBIDDEN.** `hidden LED cove lighting` — новый светильник; `black window frame only` против обязательного белого PVC-окна; radiator cover/slatted screen добавляет геометрию и перекрывает батарею; `bare branch or dried grass in a ... vessel` против `Every planter or vase must hold a live plant`. См. [hard rules](/home/pakar/igor/remlab/tools/scout/improve_mode.py:107) и [deny_always](/home/pakar/igor/remlab/tools/scout/styles.json:321).  
   **Делать иначе:** `Do not add visible or concealed lighting, ceiling coves, radiator covers or screens. Keep the window frame white PVC. Any added vase or planter must contain a live plant; otherwise omit it.`

3. **Числа дают ложную точность и противоречивый свет.** У листа нет масштаба, поэтому `6–8 cm`, `10–12 cm` ненадёжны; 3300–4000 K описывает CCT источника, но не однозначный вид дневного кадра. Более того, DOE относит daylight примерно к 4500–6500 K. [Источник DOE](https://integratedlightingcampaign.energy.gov/sites/default/files/2024-10/LED%20and%20Controls%20Guidance%20for%20GSA_0.pdf). OpenAI рекомендует для редактирования явно фиксировать сохраняемые свойства и локализовать изменение. [OpenAI Image prompting](https://developers.openai.com/api/docs/guides/image-prompting).  
   **Делать иначе:** `LIGHT: preserve the visible light direction; use natural neutral-to-warm window daylight, soft bounced fill and realistic shadows. TRIM: simple low-profile skirting proportional to the room; preserve visible dimensions.`

4. **Гайд выглядит обязательнее, чем объявлен.** Сейчас весь промпт без гайда — около 5581 символа, гайды — 590–768; новые 900–1600 сами по себе hard rules не перевесят, но десять императивных секций, альтернативы через `or` и собственный `NEVER` заставят модель исполнять их как чек-лист. Тест «есть все 10 разделов» закрепит именно эту проблему.  
   **Делать иначе:** сократить до 5–6 блоков и тестировать конфликты, а не число заголовков. Префикс: `STYLE GUIDE — OPTIONAL PRIORITIES. Apply only 3–4 compatible cues to eligible surfaces, choose one option per category, and omit every cue that conflicts with IMAGE 1, HARD RULES, SERVICE PLACEHOLDERS or FORBIDDEN.`

5. **Не хватает явной защиты уже реалистичных окна, двери и батареи.** Hard rule сохраняет только *openings*, а `DOOR & RADIATOR` фактически разрешает перекрасить дверь, заменить полотно/ручку и тип батареи. Оговорка про developer floor/walls тоже слабее, чем полное удаление конфликтующих строк.  
   **Делать иначе:** программно не включать `WALLS`/`FLOOR`, когда они выбраны застройщиком, и добавить: `If a window, door, radiator, sill, frame, trim, handle or curtain hardware is already rendered as a real object in IMAGE 1, preserve its exact shape, colour, material, position and visibility. Only schematic BLUE/BROWN rectangles may be resolved under SERVICE PLACEHOLDERS.`