## Вывод

Путь `allow_now + CEILING LIGHT` рабочий как временное решение, но сам по себе недостаточен. Нужен отдельный жёсткий блок для потолочного светильника и снятие нескольких противоречащих запретов.

Для продукта правильнее люстра как SKU с мешем: она попадёт в смету, будет геометрически одна и та же в обоих видах и не станет зависеть от генеративной согласованности. В отличие от штор, люстра уже является полноценной каталожной ролью — [styles.json:17](/home/pakar/igor/remlab/tools/scout/styles.json:17), хотя её 2422 позиции намеренно стоят в хвосте меш-очереди — [mesh-priority.json:34](/home/pakar/igor/remlab/tools/scout/rules/mesh-priority.json:34).

Практический компромисс:

- сейчас выполнить волю владельца через генерацию;
- в UI явно пометить «светильник показан для визуализации, в смету не входит»;
- позже заменить на SKU+меш и автоматически не генерировать второй светильник.

## Где сейчас есть запреты и конфликты

Активный improve-путь:

- прямой запрет любого света в `STYLE_PREFIX` — [improve_mode.py:85](/home/pakar/igor/remlab/tools/scout/improve_mode.py:85);
- `deny_always` запрещает лампы и люстры — [styles.json:323](/home/pakar/igor/remlab/tools/scout/styles.json:323);
- `TASK` разрешает менять только отделку, материалы товаров и заглушки — [improve_mode.py:182](/home/pakar/igor/remlab/tools/scout/improve_mode.py:182);
- при наличии IMAGE 3 действует «Nothing else may be added» — [improve_mode.py:225](/home/pakar/igor/remlab/tools/scout/improve_mode.py:225);
- комментарии и паспорт политики всё ещё утверждают, что светильники запрещены — [improve_mode.py:134](/home/pakar/igor/remlab/tools/scout/improve_mode.py:134), [styles.json:335](/home/pakar/igor/remlab/tools/scout/styles.json:335);
- тест специально отклоняет `lamp`, `lighting`, `chandelier` в гайдах — [test_improve_prompt.py:26](/home/pakar/igor/remlab/tools/scout/tests/test_improve_prompt.py:26).

Старый путь `draft_render.py`, не основной для `/demo`, тоже запрещает добавление:

- стиль «never adds or removes objects» — [draft_render.py:2189](/home/pakar/igor/remlab/tools/scout/draft_render.py:2189);
- любой объект вне списка объявлен невалидным — [draft_render.py:2198](/home/pakar/igor/remlab/tools/scout/draft_render.py:2198).

Проверки ответа модели сейчас семантики не контролируют. Код проверяет только наличие маджента-полосы — [draft_render.py:3378](/home/pakar/igor/remlab/tools/scout/draft_render.py:3378). Он не проверяет:

- наличие и число люстр;
- одинаковость между видами;
- положение, высоту и перекрытие ТВ;
- сохранение камеры;
- отсутствие дополнительных спотов/треков;
- выключенное состояние.

Кэш обязательно инвалидировать. Версия уже стала `.1` из-за радиатора — [improve_mode.py:47](/home/pakar/igor/remlab/tools/scout/improve_mode.py:47); для люстры логично `.2` у обеих веток. Версия входит в ключ — [improve_mode.py:404](/home/pakar/igor/remlab/tools/scout/improve_mode.py:404) — и проверяется при выдаче результата — [draft_render.py:3336](/home/pakar/igor/remlab/tools/scout/draft_render.py:3336). Обновить также unit- и e2e-ожидания.

## Масштаб и высота

Для свободной зоны отраслевые руководства рекомендуют не менее 7 футов, то есть примерно 2,13 м, от пола до низа светильника; для обычной комнаты — центр помещения. [Kohler Lighting Guide](https://resources.kohler.com/webassets/kpna/brochures/KohlerLighting_QuickTipsGuide.pdf). Это совпадает с внутренним минимумом проекта 210 см — [occupancy.json:309](/home/pakar/igor/remlab/services/planner-solver/rules/occupancy.json:309).

При потолке 2,7 м остаётся примерно полметра на корпус и подвес. Поэтому безопасный общий язык: `shallow`, `short drop`, `close to the ceiling`, а не длинная подвесная люстра. Для низких потолков журналы также советуют избегать крупных низко висящих моделей; широкая, но неглубокая накладная форма обычно выглядит лучше. [Homes & Gardens](https://www.homesandgardens.com/ideas/living-room-ceiling-light-ideas), [Architectural Digest](https://www.architecturaldigest.com/story/the-best-lighting-for-small-spaces-according-to-designers).

## Готовые строки по стилям

```text
SCANDINAVIAN
CEILING LIGHT: one broad, shallow Nordic pendant in matte off-white metal with a small pale-oak detail and an opal diffuser; medium in scale, close to the ceiling at the room's central ceiling point, switched off.

CONTEMPORARY
CEILING LIGHT: one low-profile sculptural hoop ceiling fixture with a slim matte-black frame and an opal diffuser; medium-wide, crisp and visually light, close to the ceiling at the room's central ceiling point, switched off.

SOFT MINIMALIST
CEILING LIGHT: one broad ultra-shallow flush-mount disc in matte warm white with a seamless opal diffuser; quiet and nearly flush with the ceiling, centred in the room, switched off.

INDUSTRIAL LOFT
CEILING LIGHT: one broad shallow factory pendant in matte blackened steel with a dark canopy and a simple open underside; medium-large but visually spare, on a very short drop at the room's central ceiling point, switched off.

NEOCLASSICAL
CEILING LIGHT: one compact shallow symmetrical chandelier with slender aged-brass arms and small clear-glass shades, beneath a discreet plain ceiling rose; refined rather than ornate, on a short drop at the room's central ceiling point, switched off.

JAPANDI
CEILING LIGHT: one broad flattened washi-paper lantern with a fine pale-wood or bamboo frame, warm off-white, handcrafted and visually light; close to the ceiling at the room's central ceiling point, switched off.
```

Основания выбора:

- сканди — лаконичный плафон, дерево, плетение или ткань; [IVD](https://www.ivd.ru/dizajn-i-dekor/spalna/oformlyaem-spalnyu-v-skandinavskom-stile-samyj-polnyj-gid-76-foto-87112);
- современный — чистая скульптурная геометрия, в том числе кольцо; [Homes & Gardens](https://www.homesandgardens.com/ideas/living-room-ceiling-light-ideas);
- минимализм — простая форма и низкопрофильный широкий плафон; [Architectural Digest](https://www.architecturaldigest.com/story/the-best-lighting-for-small-spaces-according-to-designers);
- лофт — фабричная форма, чёрный матовый металл, практичный открытый светильник; [Livingetc](https://www.livingetc.com/ideas/industrial-living-room-ideas);
- неоклассика — симметрия, стекло/хрусталь и сдержанная латунь, без дворцовой перегрузки; [IVD](https://www.ivd.ru/stroitelstvo-i-remont/osvesenie/sovremennye-lyustry-kak-najti-idealnuyu-i-chto-v-mode-v-2022-godu-97282);
- джапанди — бумага, бамбук, ремесленная фактура и визуальная лёгкость; [House & Garden](https://www.houseandgarden.co.uk/article/paper-lights).

## Жёсткое исключение

В `STYLE_PREFIX` лучше заменить общий запрет на:

```text
Do not add any visible or concealed lighting except the single ceiling fixture governed by CEILING FIXTURE below and described by CEILING LIGHT in the active STYLE GUIDE. Do not add recessed or track lights, spotlights, sconces, floor or table lamps, LED strips, luminous ceilings or ceiling coves.
```

Перед `RENOVATION` добавить отдельный общий блок:

```text
CEILING FIXTURE — THE ONLY NEW LIGHTING

If IMAGE 1 already contains a ceiling fixture, preserve that catalogue product exactly and do not add another one. Otherwise add one physical ceiling fixture as specified by CEILING LIGHT in the active STYLE GUIDE.

It is the same physical fixture in both views: the same design, materials, colour, scale, ceiling attachment point and switched-off state, shown only where naturally visible from each existing camera.

Use the room's central ceiling point. Keep the fixture shallow and close to the ceiling, with normal head clearance. It must remain high in the frame and must not overlap or obscure any furniture, television, door, window or curtain.

If the ceiling point falls outside the existing crop, do not move, tilt, widen or raise the camera and do not lower the fixture merely to make it visible. The fixture emits no glow and must not change the original daylight direction, exposure, white balance or shadows.
```

Также:

- `Nothing else may be added` заменить на `Nothing else may be added except the ceiling fixture governed below`;
- уточнить `TASK`, что единственный новый объект — разрешённый потолочный светильник;
- в `deny_always` запретить именно все остальные виды света и второй потолочный светильник;
- `allow_now` оставить как запись решения владельца, но не полагаться на неё как на основное правило.

Главные дизайнерские дефекты, которые это предотвращает: слишком низкий подвес, экранный вместо комнатного центр, другая люстра во втором виде, светящаяся люстра при дневном кадре, треки/споты «в придачу», изменение кропа ради показа светильника и перекрытие телевизора.

## Минимальные платные проверки

Первый шлюз — 3 генерации на одном и том же помещении:

1. неоклассика — максимальный риск избыточного размера, золота и низкого подвеса;
2. лофт — риск дополнительных треков, спотов и светящихся Edison-ламп;
3. джапанди — риск огромного низкого бумажного плафона и расхождения формы между видами.

Если все три проходят, ещё по одному прогону для сканди, современного и минимализма: итого 6 платных запросов для выпуска, по одному на каждый реально различающийся гайд. Старые кадры можно использовать как бесплатный baseline.

Приёмка каждого результата:

- одна физическая люстра, а не по одной на ракурс;
- одна форма, материал, цвет и потолочная точка в обоих видах;
- короткий подвес, свободный проход, ТВ и мебель не перекрыты;
- камера, кроп, перспектива и видимая доля потолка не изменены;
- нет спотов, треков, бра, LED-линий и второго светильника;
- существующий торшер не изменён и не исчез;
- люстра выключена, направление дневного света и экспозиция прежние;
- стилистика различима без карикатуры.

Текущий текстовый тест до изменений проходит полностью; файлов я не менял.