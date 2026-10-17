---
workstream: demo
slug: demo-13-style-prompts
title: Куски промпта по стилям (render_guide v2) — по исследованию стилей: стены, пол, потолок, свет, шторы, картины, декор, запреты; показать владельцу страницей с пробным фото на стиль
status: draft
created: 2026-10-17
updated: 2026-10-17
completed:
plan_kind: sub
parent_plan: MASTER-cost-first
assignee: opus-5.5
review_after: 2026-11-28
---

## Цель
Для каждого из шести стилей в промпт «Сделать реалистичнее» подставляется подробный, проверенный по источникам кусок, который задаёт
ВСЁ окружение вокруг подобранной мебели: цвет и фактуру стен, пол (если не выбран застройщиком), потолок и плинтус, дверь и радиатор,
характер света, шторы, картины (которые мы не продаём), мелкий декор и запреты стиля. Картинка получается «в стиле», а не нейтральной.

## Источник задачи
Владелец 17.10: «пересмотреть все промпты под стили… поищи в интернете каждый стиль… цвет стен, картины, шторы — чтобы это всё создавало
антураж стиля; максимально продумай кусок промпта за каждый стиль; отдай Опусу на реализацию; проверять стили буду сам».

## Что есть
- `tools/scout/styles.json` → `styles.<стиль>.render_guide` (короткие тексты 17.10 после бенча, demo-11), `_decor_policy.deny_always`
  (мебель, светильники, электроника, перекрытия, выдуманные подушки/подлокотники). Подстановка — `tools/scout/improve_mode.py:style_block/prompt_for`
  (блок «STYLE GUIDE — VARIABLE AND ADVISORY»). Модель — `openai/gpt-image-2.5-sunburst` medium (ADR-0302), промпт improve-v2.
- Ограничения промпта, которые гайд НЕ может нарушать: не добавлять мебель, ковры, светильники; не менять геометрию; пол/стены
  застройщика — как на кадре (строки `FLOOR`/`WALLS` при выборе покупателя — тогда абзацы гайда про пол/стены игнорируются).

## Исследование (d8 17.10, источники — ниже; `source: external`)
- **Сканди:** тёплый белый/грейж, не холодный; светлое дерево (дуб, ясень, берёза), никогда тёмного; максимум дневного света; тепло через
  фактуру и материалы, а не декор; акценты — приглушённые синий/шалфей/пыльно-розовый; предметы «заслуживают место».
- **Современный:** база серый/белый/чёрный + один смелый акцент (navy, оливковый, жжёный оранжевый); чистые линии; одно крупное
  произведение как фокус; шторы — простые или жалюзи; свет как элемент дизайна, слоями.
- **Минимализм:** тёплые нейтральные, не стерильно-белые; фактура (штукатурка, микроцемент) вместо декора; окна без слоёв — одна
  прозрачная ткань или рулонная штора; ОДНО крупное произведение вместо галереи; тёплый свет 2700–3000 K (в нашем кадре — дневной, мягкий).
- **Лофт:** кирпич, бетон, металл, дерево; высокие потолки и большие окна (у нас окно и потолок заданы — только отделка); палитра тёплый
  серый, терракота кирпича, графит, кожаный коричневый; рискует быть холодным — греют дерево, растения, тёплый свет.
- **Джапанди:** стены тёплый off-white, грибной, глина, мягкий графит; два тона дерева (светлое + тёмное), без красного дуба/сосны; акценты
  матовый чёрный, тёмно-зелёный, ржавый; лён и шторы-«сёдзи»; ваби-саби — несовершенство, асимметрия, нечётное число предметов, ручная керамика.
- **Неоклассика (современная классика, рынок РФ):** светлый приглушённый фон (белый, бежевый, серый, песочный), симметрия, молдинги и
  лепнина сдержанно, паркет средних тонов, шторы в пол со складками из плотных тканей, богатый, но приглушённый декор, латунь простых форм.

## Решение — тексты `render_guide` v2.1 (после критики Codex; английский, вставлять как есть; ⚑ владелец проверяет по странице)
Структура у всех одна и короткая (6 блоков): WALLS → FLOOR → TRIM & DOOR → LIGHT → WINDOW DRESSING → ART & DECOR → STYLE NO. Без чисел
(см, кельвины), без абсолютов «никогда/ровно», без светильников, экранов и решёток, без смены окна/двери/батареи, если они уже на кадре.
**Общий префикс в коде (один раз, перед гайдом):** «STYLE GUIDE — OPTIONAL PRIORITIES. Apply only 3–4 compatible cues to eligible surfaces,
choose one option per category, and omit every cue that conflicts with IMAGE 1, the HARD RULES, SERVICE PLACEHOLDERS or FORBIDDEN. If a window,
door, radiator, sill, frame, trim, handle or curtain hardware is already rendered as a real object in IMAGE 1, preserve its exact shape, colour,
material, position and visibility; only schematic BLUE/BROWN rectangles may be resolved under SERVICE PLACEHOLDERS. Do not add visible or
concealed lighting, ceiling coves, radiator covers or screens. Any added vase or planter must contain a live plant; otherwise omit it.
Preserve the visible light direction.» Строки WALLS/FLOOR гайда **не включаются программно**, когда пол/стены выбраны застройщиком.

### сканди
```
SCANDINAVIAN STYLE — warm Nordic home.
WALLS: smooth matte paint in warm white with a faint cream or pale-greige undertone; one wall may be a slightly deeper warm greige; no wallpaper, no stripes.
FLOOR: pale natural oak or ash planks, matte, honey-light tone with calm grain.
TRIM & DOOR: simple flat white skirting and plain white trim; if the door is a schematic placeholder, make it a plain white painted door with a flat frame.
LIGHT: bright, soft, slightly warm window daylight with a gentle golden cast, soft long shadows, airy and never dim.
WINDOW DRESSING: floor-length light linen curtains in cream or oatmeal on a thin black or natural-wood rod, hung high and wide, slightly open.
ART & DECOR: one or two black-framed prints with a white mat (botanical line drawing, muted abstract or black-and-white photo) hung at eye level; one green plant in a plain white or terracotta pot; nothing more.
STYLE NO: gloss, gold, ornament, bold patterns, cold grey walls, clutter.
```

### современный
```
CONTEMPORARY STYLE — clean, warm, confident.
WALLS: perfectly smooth matte paint in warm greige or soft taupe; optionally the wall behind the sofa or the TV in a deeper muted tone (graphite, olive, clay or navy-grey), flat colour without panels.
FLOOR: wide engineered-oak planks in a warm mid tone, matte, or large-format matte warm-grey stone-look tiles.
TRIM & DOOR: slim flat skirting painted white or in the wall colour, crisp straight lines; a schematic door becomes a flat slab door in the wall colour with a slim black handle.
LIGHT: clean, even daylight with soft defined shadows; neutral-to-warm.
WINDOW DRESSING: floor-to-ceiling plain linen-look curtains in sand or graphite on a slim ceiling track, or a plain roller blind; no patterns.
ART & DECOR: one large abstract canvas or a diptych in a slim black or oak frame carrying the room's single accent colour (burnt orange, navy or olive), centred over the sofa or on the free wall; one sculptural plant in a matte ceramic pot.
STYLE NO: classical mouldings, rustic textures, chrome glitz, pastel colours, patterned wallpaper, clutter.
```

### минимализм
```
SOFT MINIMALIST STYLE — warm, quiet, uncluttered.
WALLS: one continuous light warm tone (warm off-white or pale greige) in a perfectly smooth matte or fine lime-plaster finish; no accent wall.
FLOOR: seamless pale wide-plank wood with a matte finish, or light warm microcement; no pattern.
TRIM & DOOR: skirting flush with the wall or a thin shadow gap, practically invisible; a schematic door becomes a flush door painted the wall colour with a minimal handle.
LIGHT: soft, diffused, even daylight with low contrast and barely visible shadows; no harsh sun patches.
WINDOW DRESSING: wall-to-wall sheer off-white linen from ceiling to floor on a hidden track, or a plain roller blind.
ART & DECOR: at most one oversized muted artwork (abstract canvas or monochrome photograph) in a hair-thin frame, or none; at most one architectural plant in a plain pot; large empty surfaces are intended.
STYLE NO: patterns, colour accents, gloss, ornament, groups of small objects, visible clutter.
```

### лофт
```
INDUSTRIAL LOFT STYLE — warm brick, concrete and dark steel.
WALLS: the wall behind the sofa or the TV as exposed red-brown brick with natural sandy mortar; the other walls smooth warm-grey concrete-look matte plaster or deep graphite paint.
FLOOR: wide dark-stained wood planks with visible grain, matte, or warm grey polished concrete.
TRIM & DOOR: flat dark or black skirting with hard straight edges; a schematic door becomes a dark-painted door with a dark frame.
LIGHT: warm afternoon daylight raking across the brick, a little moodier contrast than usual, but every piece of furniture clearly lit.
WINDOW DRESSING: heavy charcoal or rust linen curtains on a black pipe rod, hung loosely, or no curtains.
ART & DECOR: one large monochrome photographic poster or a vintage industrial print in a thin black frame; one tall green plant in a concrete or black metal pot.
STYLE NO: gloss, gold, classical mouldings, pastel colours, floral patterns, glossy white doors.
```

### неоклассика
```
NEOCLASSICAL STYLE (modern classic) — light, proportioned, refined.
WALLS: smooth matte paint in soft cream, warm greige or dusty grey-blue; slim white rectangular panel mouldings laid out in a calm symmetrical rhythm on the main walls; never heavy stucco.
FLOOR: natural oak herringbone parquet in a light-to-mid honey tone, matte.
TRIM & DOOR: white ceiling with a simple plain cornice, taller profiled white skirting and white architraves; a schematic door becomes a white panelled door with classic profiles and a brass handle.
LIGHT: warm golden daylight, soft and elegant, gentle highlights on the mouldings.
WINDOW DRESSING: full-length heavy curtains in cream, champagne or dusty blue with soft folds on a simple rod or ceiling track, with a sheer white inner layer; no swags or tassels.
ART & DECOR: one classical framed painting (landscape or still life) or a symmetrical pair of framed prints in dark-wood or antique-gold frames, or one framed mirror; a white orchid in a ceramic cachepot. Symmetry guides mouldings, art and curtains only — never the furniture.
STYLE NO: columns, baroque ornament, gold overload, glossy stretch ceilings, dark heavy wallpaper, palace or hotel look.
```

### джапанди
```
JAPANDI STYLE — warm, serene, wabi-sabi.
WALLS: limewash-look or fine textured plaster in warm sand, clay or mushroom, soft and even with subtle hand-finished variation; no accent colours, no wallpaper.
FLOOR: light natural ash or oak planks with a matte finish; any darker wood in trim or door reads as walnut or smoked oak.
TRIM & DOOR: minimal low trim in the wall colour or thin natural-wood skirting; a schematic door becomes a flat natural-oak or walnut veneer door with a small black handle.
LIGHT: soft, warm, filtered daylight as if through paper screens, low contrast, calm shadows.
WINDOW DRESSING: raw natural linen curtains in oatmeal on a thin wooden rod, or a bamboo or paper-look roller blind.
ART & DECOR: one ink-wash or botanical piece in a thin natural-wood frame, slightly off-centre, or none; one live plant with a simple branch-like silhouette in a handmade ceramic pot, or a wooden bowl; few objects, asymmetric, with visible craft.
STYLE NO: gloss, gold, bright colours, forced symmetry, plastic, clutter, red-toned wood.
```

## Что делать исполнителю
1. `styles.json`: заменить шесть `render_guide` текстами выше (как есть); в `prompt_for` перед гайдом — общий префикс из «Решения» (один раз);
   строки `WALLS:`/`FLOOR:` гайда вырезать программно, когда стены/пол выбраны застройщиком. `PROMPT_VERSION` → `improve-v3` (кэш по версии есть, demo-11).
2. Юнит-тест — на КОНФЛИКТЫ, а не на число заголовков: в гайдах нет слов lamp/lighting/cove/chandelier/cover/screen/rug/sofa/armchair как добавления,
   нет чисел с cm/K, нет «never»/«exactly» внутри блоков (кроме STYLE NO); префикс присутствует; при developer floor/walls строки вырезаны.
3. Страница `/test/share/style-guides/` v2: для каждого стиля — русское резюме (5–7 строк простым языком: стены, пол, свет, шторы, картины,
   декор, запреты), английский текст, и ОДНО пробное фото (оба вида) этим гайдом: сканди/современный/минимализм/лофт/джапанди — на своих
   демо-вариантах, неоклассика — на расстановке «Сканди» со стилем «неоклассика» (у неё нет демо-варианта). 6 × ~5.5 ¢. Старые фото
   вариантов не трогать до ⚑ приёмки владельцем; после «ок» — пересъёмка `--force all`.
4. Память: `core/styles.md` (гайды v2 — где и зачем), `domain/interior-styles.md` (исследование: источники), книга «Сегодня» (глава стилей), ADR.

## Критерии приёмки
- [ ] Шесть гайдов v2 в `styles.json`, промпт improve-v3, юнит-тест зелёный
- [ ] Страница с резюме, текстами и пробным фото каждого стиля показана владельцу (⚑); фото по стилям различимы (кирпич в лофте, молдинги в неоклассике, лён и глина в джапанди, один акцент в современном, пустота в минимализме, тёплый белый в сканди)
- [ ] Ни на одном пробном фото нет выдуманной мебели/светильников/ковров и подушек/подлокотников; пол застройщика, если выбран, не перекрашен
- [ ] После «ок» владельца — пересъёмка 5 вариантов

## Где обязательно советоваться с Codex
- Критика текстов (стилистическая точность + конфликты с hard rules) — `_intake/codex/2026-10-17-style-prompts-critique.md`.

## Источники (external)
Сканди: andacademy.com, styldod.com, genroom.io/scandinavian; Современный: styldod.com/contemporary-living-room-design, coasterfurniture.com,
rovelab.com; Минимализм: livingetc.com (palettes), colemanfurniture.com, wayfair.ca, salvatoriofficial.com; Лофт: dezeen.com (industrial
living rooms), redfin.com, wayfair.ca/what-is-a-loft, metallbude.com; Джапанди: genroom.io/japandi (один источник — проверить вторым);
Неоклассика: realty.yandex.ru/journal (неоклассика), t-j.ru/neoclassica, houzz.ru (современная классика), dzen.ru.

## Лог выполнения
- 2026-10-17 — d8: исследование по 6 стилям, тексты v2; критика Codex (`_intake/codex/2026-10-17-style-prompts-critique.md`: клише и абсолюты, конфликты с hard rules — LED cove, чёрная рама окна, решётки радиатора, сухая ветка, перекраска двери; ложная точность см/K; 10 императивных секций; защита окна/двери/батареи) → тексты v2.1 (6 блоков, без чисел, общий префикс, вырезание WALLS/FLOOR); передан исполнителю.
