Вывод: рефери права по визуальным симптомам №1/3, №14–16, №27/31 и №41/57; слишком категорична по №13, №28 и особенно №35. Ваши выводы в основном верны, но в нескольких местах предложен неверный слой исправления.

### №1 / №3 — вход и маршрут

Симптом верный, но правило «90 см от bbox блока до проёма» неверно сформулировано.

- В коде дверь находится на стене `west`, не `east`: [canon_gallery.py](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:60). Если картинка читается наоборот — дополнительно проверить ориентацию рендера.
- `block_scene()` центрирует блок и проверяет только вхождение и дугу двери; маршрут не измеряется: [canon_gallery.py](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:123).
- Норма 36″ ≈ 91 см обоснована именно для главного прохода, а не как круговой отступ от проёма. [Homes & Gardens рекомендует ≥36″ для основных маршрутов](https://www.homesandgardens.com/interior-design/the-library-how-to-design-the-perfect-living-room-layout).

Минимальная правка: перебирать сдвиги и выбирать по фактической ширине маршрута от двери в ядро комнаты: цель 91 см, затем продуктовый минимум 75 см. Не по расстоянию `door ↔ bbox`. В production полный ключ уже учитывает маршрут раньше богатства: [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1475), [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1551), но локальный gallery placer этого не делает.

### №6 / №18 / №52 — зеркала и дверь

Вы правы, что текущей гарантии нет. Но критерий должен быть не «посадка всегда от двери», а:

> зеркало выбирается так, чтобы открытая сторона группы принимала входной маршрут, а спинки/торцы не сужали его.

Сейчас:

- `tandem_r/l` и `L_right/square_r` — независимые формы: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:803), [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:642).
- Greedy идёт по паспортному порядку и способен вернуть первое валидное зеркало: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1668).
- Отдельный полноценный mirror-resolution реализован только для handedness углового дивана: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1503).

Минимум для production: зеркальная пара должна иметь квоту «обе стороны дошли до сравнения», а выбор — по полному `main_route_tier`, затем остальному ключу. Не вводить `if door_right → tandem_left`: при другой стене двери это будет ошибкой.

В галерее лучше объединить зеркала в одну карточку с двумя подрисунками либо подобрать для каждого зеркала соответствующую дверную ситуацию и подписать «сторона определяется маршрутом».

### №13 — два кресла визави

Рефери категорически не права: кресла лицом друг к другу — признанная разговорная схема. Исследовательская модель Stanford использует дистанцию разговорной группы около 4–8 ft и ориентацию посадок друг к другу; [AD показывает два кресла визави как решение для cocktails/conversation](https://www.architecturaldigest.com/story/david-lucido-460-square-foot-manhattan-studio).

Но ваша диагностика верна: показан не тот столик.

- Паспорт `armchair_pair` требует `приставной`: [zones.json](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:10).
- Галерея передаёт общий `столик` 110×60: [canon_gallery.py](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:348).
- В production `build_block` тоже предпочитает `столик` перед `приставной`, поэтому это не только дефект витрины: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:577).

Минимум: для `armchair_pair` выбирать `приставной` первым; большой журнальный стол считать другой формой. Геометрия визави сохраняется.

### №14 / №15 / №16 — одинаковые карточки

Да, это прежде всего баг сборки витрины: один `seat_kit` подаётся всем группам, минуя фильтр ролей `place_template()`.

Но есть более глубокий production-дефект:

- Фактический признак Г-дивана — `Item.corner=True`, а не произвольное поле `sofa_subtype`: [models.py](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:81).
- `compact_sectional` сейчас может собраться на прямом диване, потому что `build_block` не проверяет subtype, а каскад иногда понижает прямой диван именно до `compact_sectional`: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1622), [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:846).

Минимум:

- Галерея: required-роли каждой группы; optional — только если показывается отдельная вариация.
- `compact_sectional`: отдельный `Item(corner=True, corner_section_cm=...)`.
- Production: запретить `compact_sectional` для `corner=False`; прямой диван без кресел понижать в `sofa_solo`, не в sectional.

Последнее требует полного экзамена: это уже изменение лестницы.

### №27 / №31 — торшер и wall_vignette

Рефери права по №27. Надёжная светотехническая рекомендация — источник слегка сзади и сбоку, чтобы свет шёл через плечо на страницу, а не строго за головой. Это прямо рекомендует [Lighting Research Center при RPI](https://www.lrc.rpi.edu/programs/lightHealth/AARP/pdf/AARPbook2.pdf).

Ваши «50–60 см» разумны как preferred, но не как жёсткая норма. В проекте уже честнее записано 46–90 см, с неопределённостью: [occupancy.json](/home/pakar/igor/remlab/services/planner-solver/rules/occupancy.json:880).

Точный дефект: обычная ветка уже ставит свет сбоку-сзади, а `corner=True` намеренно ставит его строго за центром кресла: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2146). Исправлять надо `build_reading(corner=True)`: торшер за левым/правым плечом, приставной с противоположной стороны; оба зеркала.

№31 действительно повторяет №27, потому что `place_reading` всегда пробует угол раньше стены: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2254), [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2286). Честнее не давать ручной hint, а сделать мини-сцену, где углы реально заняты проёмами/недоступны — тогда боевой placer естественно дойдёт до wall fallback.

### №28 — эркер и торшер

Рефери выражает хорошее предпочтение, но не обязательный инвариант: паспорт разрешает одиночное кресло в эркере, архитектурный якорь делает его самодостаточным: [templates.json](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:863).

Ваш желаемый результат нормален — кресло внутри эркера, торшер у устья ниши со стороны комнаты. Но расширять `_bay_candidates` неправильно: он задаёт позицию кресла-якоря, а не отдельных спутников: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2835).

Минимум: добавить bay-вариант внутренней раскладки `build_reading`, где торшер стоит сбоку и чуть в сторону комнаты. Каскад остаётся: полный комплект → кресло+поверхность → singleton. Просто увеличить эркер галереи — косметика, production-дыру не закроет.

### №35 — ТВ и камин

Рефери не права. ТВ и камин side-by-side на одной стене — известная допустимая схема, но требующая баланса размеров. [Houzz прямо показывает side-by-side как один из рабочих вариантов](https://www.houzz.com/magazine/7-ways-to-rock-a-tv-and-fireplace-combo-stsetivw-vs~5176882); [Homes & Gardens показывает ТВ справа от камина](https://www.homesandgardens.com/interior-design/living-rooms/layout-tricks-that-make-a-tv-less-dominant).

Ваш канон сохранять. Но не называть его универсально рекомендуемым: нужны достаточная ширина стены, видимость обоих фокусов, тепловые нормы конкретного камина и визуальный баланс.

Что вы упустили: production-комментарий сейчас утверждает, что при наличии обоих предметов они «должны» делить стену: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2681). Это слишком сильно. Side-by-side должен быть одним семейством кандидатов; смежные стены — другим. Противоположные не безусловно запрещены, хотя риск конкурирующих фокусов и отражения выше.

### №41 / №57 — центрирование носителя и кашпо

Вы правы в симптоме, но не в объёме правки.

`build_media()` уже ставит кашпо сбоку от оси носителя: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2757). Смещение появляется потому, что `block_scene()` центрирует весь bbox и вычитает его offset: [canon_gallery.py](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:134). Поэтому:

- №41: центрировать в простенке якорь-носитель, не composite bbox.
- №57: ставить якорь через боевой `_corner_candidates`; выбрать зеркало, у которого кашпо остаётся на открытой стороне комнаты.

Общий запрет спутникам «не на оси» в `build_media` не нужен — он уже соблюдён.

Более серьёзная пропущенная дыра: паспорт утверждает, что `media_between_windows` реализован через `_window_candidates`, но эта функция ставит тумбу по центру самого окна, а не простенка: [templates.json](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:455), [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2925). Нужен настоящий `_between_windows_candidates`; это production-фикс, не витринный.

### №46 — консоль за диваном

Схема законна; проблема в экземпляре. Причём реальная практика допускает и консольный стол, и узкий комод/дрессер. [Homes & Gardens](https://www.homesandgardens.com/interior-design/styling-the-back-of-the-sofa) рекомендует высоту не выше спинки и ширину примерно от 2/3 дивана; там же прямо упомянут narrow dresser.

Текущий комод 120 см при диване 220 см — 55%, то есть проходит ваш слабый минимум 50%, но для эталона действительно выглядит куцым: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2040), [validate.py](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:1704).

Не следует вводить выдуманный gallery-only SKU. Лучше:

- найти реальный товар 140–180×30–40 см;
- ввести capability `sofa_console_capable`, а не обязательно новую каталоговую роль;
- preferred длину поднять до ≥2/3, сохранив 1/2 только как явно деградированный fallback.

Ковёр в текущем коде №46 уже добавлен и не заходит под консоль: [canon_gallery.py](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:535). Если его нет на странице — вероятен старый артефакт/кэш.

### Разделение фиксов

Чисто витринные:

- role-aware kit для №13–16;
- корректные ситуационные комнаты зеркал и `wall_vignette`;
- центрирование по якорю вместо bbox в №41/57.

Обязательные production:

- обе зеркальные формы должны доходить до сравнения;
- `armchair_pair` предпочитает паспортный приставной;
- `compact_sectional` требует `Item.corner`;
- боковой торшер в `corner_vignette`;
- bay-вариант со спутниками у устья;
- настоящий `_between_windows_candidates`;
- side-by-side камин/ТВ как альтернатива, не безусловное правило;
- console capability и предпочтительная пропорция.

Главная архитектурная рекомендация: не чинить координаты карточек вручную. Галерея должна задавать ситуацию и конкретную схему, а позицию получать через тот же production-кандидат/валидатор. Сейчас `block_scene()` нарушает этот контракт: builder боевой, placer — витринный.