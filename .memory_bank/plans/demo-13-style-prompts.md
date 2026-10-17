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

## Решение — тексты `render_guide` v2 (английский, вставлять как есть; ⚑ владелец проверяет по странице)
Структура у всех одна: WALLS → FLOOR → CEILING & TRIM → DOOR & RADIATOR → LIGHT → WINDOW DRESSING → WALL ART → SMALL DECOR → MOOD → NEVER.
Общая оговорка в коде перед гайдом (один раз, не в каждом тексте): «If the buyer has chosen a developer floor or walls, the FLOOR/WALLS
lines of this guide are void — keep the rendered finish.»

### сканди
```
SCANDINAVIAN STYLE — WARM NORDIC HOME.
WALLS: smooth matte paint in warm white with a faint cream or pale greige undertone (never cold, bluish or grey-white); one wall may be a slightly deeper warm greige, no stripes or wallpaper.
FLOOR: pale natural oak or ash planks, matte, honey-light tone, visible but calm grain; never dark wood, never glossy.
CEILING & TRIM: flat white ceiling; simple flat white skirting 6–8 cm; no cornices, no mouldings.
DOOR & RADIATOR: plain white painted door with a flat frame and a matte black or steel handle; flat white panel radiator under the window.
LIGHT: bright, soft, warm daylight (about 3500 K) flooding in from the window, gentle golden cast on the walls, soft long shadows; the room looks airy and bright, never dim.
WINDOW DRESSING: floor-length light linen curtains in cream or oatmeal on a thin black or natural-wood rod, hung high and wide, slightly open; a sheer white inner layer is fine.
WALL ART: one or two black-framed prints with a wide white mat — botanical line drawings, a muted abstract or a black-and-white photograph; hung at eye level in one calm group; nothing gilded.
SMALL DECOR: one green plant (monstera, fiddle-leaf fig or olive) in a plain white or terracotta pot; a wooden bowl or a single candle holder on an existing surface — at most two small objects.
MOOD: light, calm, hygge-warm, tidy; accents only in muted blue, sage or dusty pink and only inside the art.
NEVER: gloss, gold, ornament, dark wood, bold patterns, cold grey walls, clutter.
```

### современный
```
CONTEMPORARY STYLE — CLEAN, WARM, CONFIDENT.
WALLS: perfectly smooth matte paint in warm greige or soft taupe; one accent wall allowed only behind the sofa or the TV in a deeper muted tone (graphite, olive, clay or navy-grey), flat colour, no panels.
FLOOR: wide engineered-oak planks in a warm mid tone with a matte finish, or large-format matte stone-look tiles in warm grey.
CEILING & TRIM: flat white ceiling; slim flat skirting painted white or in the wall colour; crisp straight lines everywhere.
DOOR & RADIATOR: flat slab door in the wall colour or warm grey with a slim black handle; flat white or black panel radiator under the window.
LIGHT: clean daylight slightly warm (about 4000 K), even on the walls with soft defined shadows; a subtle warm glow near the ceiling line as if from hidden LED cove lighting (no visible fixture).
WINDOW DRESSING: floor-to-ceiling plain linen-look curtains in sand or graphite on a slim ceiling track, or a plain roller blind; no valances, no patterns.
WALL ART: one large bold abstract canvas or a two-piece diptych in a slim black or oak frame, carrying the single colour accent of the room (burnt orange, navy or olive); hung centred over the sofa or on the free wall.
SMALL DECOR: one sculptural plant in a matte ceramic pot or one tall ceramic vase on an existing surface; nothing else.
MOOD: urban, uncluttered, warm neutrals with one deliberate accent colour.
NEVER: classical mouldings, rustic textures, chrome glitz, pastel colours, patterned wallpaper, visible clutter.
```

### минимализм
```
SOFT MINIMALIST STYLE — WARM, QUIET, ALMOST EMPTY.
WALLS: one continuous light warm tone (warm off-white or pale greige) in a perfectly smooth matte or fine lime-plaster finish; no accent wall, no colour blocks.
FLOOR: seamless pale wide-plank wood with a matte finish, or light warm microcement; minimal joints, no pattern.
CEILING & TRIM: flat white ceiling without cornice; skirting flush with the wall or a thin shadow gap — practically invisible.
DOOR & RADIATOR: flush door painted the wall colour with no visible frame and a minimal handle; radiator flat white and discreet, or hidden behind a plain white grille.
LIGHT: soft, diffused, even warm daylight (about 4000 K) with low contrast and barely visible shadows; no harsh sun patches.
WINDOW DRESSING: wall-to-wall sheer off-white linen from ceiling to floor on a hidden track, or no curtains at all with a plain roller blind.
WALL ART: at most ONE oversized piece — a muted abstract canvas or a monochrome photograph, unframed or in a hair-thin frame; or no art at all.
SMALL DECOR: at most ONE object — an architectural plant in a plain pot or a single ceramic vase; large empty surfaces are the point.
MOOD: silence, order, air; the furniture is the only pattern in the room.
NEVER: patterns, colour accents, gloss, ornament, multiple small objects, visible cables or clutter.
```

### лофт
```
INDUSTRIAL LOFT STYLE — WARM BRICK, CONCRETE AND BLACK STEEL.
WALLS: one feature wall of exposed red-brown brick with natural sandy mortar (behind the sofa or the TV); the other walls smooth warm-grey concrete-look matte plaster or deep graphite paint.
FLOOR: wide dark-stained wood planks with visible grain and matte finish, or warm grey polished concrete.
CEILING & TRIM: smooth concrete-look grey ceiling; flat black steel skirting and black window reveal; straight hard edges.
DOOR & RADIATOR: black-painted door with a dark steel frame, or a dark reclaimed-wood door; black cast-iron or black flat panel radiator under the window.
LIGHT: warm late-afternoon daylight (about 3500 K) raking across the brick, moody contrast with deeper shadows than usual, but the furniture stays clearly lit.
WINDOW DRESSING: heavy charcoal or rust linen curtains on a black pipe rod, hung loosely, or no curtains — black window frame only.
WALL ART: one large monochrome photographic poster or a vintage industrial print in a thin black frame, leaning or hung slightly off-centre.
SMALL DECOR: one tall green plant in a concrete or black metal pot; a stack of books or a black candle on an existing surface; at most two objects.
MOOD: converted warehouse made cosy — warm grey, brick terracotta, charcoal, leather brown.
NEVER: gloss, gold, classical mouldings, pastel colours, white glossy doors, delicate floral patterns.
```

### неоклассика
```
NEOCLASSICAL STYLE (MODERN CLASSIC) — LIGHT, SYMMETRIC, REFINED.
WALLS: smooth matte paint in soft cream, warm greige or dusty grey-blue; white rectangular panel mouldings laid out symmetrically on the main walls (two or three tall panels per wall), slim and restrained, never heavy stucco.
FLOOR: natural oak herringbone parquet in a light-to-mid honey tone with a matte finish.
CEILING & TRIM: white ceiling with a simple plain cornice; tall profiled white skirting 10–12 cm; white door architraves.
DOOR & RADIATOR: white panelled door with classic profiles and a brass handle; white column or classic panel radiator under the window, optionally behind a white fretwork cover.
LIGHT: warm golden daylight (about 3300 K), soft and elegant, gentle highlights on the mouldings.
WINDOW DRESSING: full-length heavy curtains in cream, champagne or dusty blue linen-velvet with soft folds, on a simple rod or ceiling track, with a sheer white inner layer; no swags, no tassels.
WALL ART: one classical framed painting (landscape or still life) or a symmetrical pair of framed prints in dark-wood or antique-gold frames; optionally one framed mirror on the free wall; hung centred.
SMALL DECOR: a white orchid or hydrangea in a ceramic cachepot, a candle in a brass holder — at most two objects on existing surfaces.
MOOD: quiet elegance of a renovated city flat; symmetry only in mouldings, art and curtains — never move furniture for it.
NEVER: columns, baroque ornament, gold overload, glossy stretch ceilings, dark heavy wallpaper, palace or hotel look.
```

### джапанди
```
JAPANDI STYLE — WARM, SERENE, WABI-SABI.
WALLS: limewash-look or fine textured plaster in warm sand, clay or mushroom, soft and even with subtle hand-finished variation; no accent colours, no wallpaper.
FLOOR: light natural ash or oak planks with a matte finish; where a second wood appears (door, trim) it is darker — walnut or smoked oak — never red oak or pine.
CEILING & TRIM: warm white flat ceiling; minimal low trim in the wall colour or a thin natural-wood skirting.
DOOR & RADIATOR: flat door in natural oak veneer or dark walnut with a tiny black handle; discreet white radiator or one hidden behind a slatted wood screen.
LIGHT: soft, warm, filtered daylight (about 3500 K) as if through paper screens, low contrast, calm shadows.
WINDOW DRESSING: raw natural linen curtains in oatmeal hung simply on a thin wooden rod, or a bamboo or paper roller blind.
WALL ART: one ink-wash or botanical sumi-e piece in a thin natural-wood frame, hung slightly off-centre, or no art at all.
SMALL DECOR: one bare branch or dried grass in a handmade ceramic vessel, one smooth stone or a wooden bowl — an odd number of objects, at most three, asymmetric, with visible craft.
MOOD: stillness and imperfection; warm neutrals with accents only in matte black, forest green or rust, inside the objects.
NEVER: gloss, gold, bright colours, symmetry for its own sake, plastic, clutter, pine or red-toned wood.
```

## Что делать исполнителю
1. `styles.json`: заменить шесть `render_guide` текстами выше (как есть), добавить общую оговорку про пол/стены застройщика один раз в
   `prompt_for` перед STYLE GUIDE (не в каждый текст). `PROMPT_VERSION` → `improve-v3` (кэш по версии уже есть, demo-11).
2. Юнит-тест: у каждого стиля в гайде есть все 10 разделов (WALLS…NEVER), нет слов из `deny_always` в разрешающем смысле (lamp/chandelier/
   rug/sofa как добавление), длина 900–1600 символов.
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
- 2026-10-17 — d8: исследование по 6 стилям, тексты v2, критика Codex — ниже; передача исполнителю после demo-10 или раньше (мелко).
