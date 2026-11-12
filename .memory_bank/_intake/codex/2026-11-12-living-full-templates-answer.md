# Вывод

Гостиную нельзя довести требуемым владельцем способом, просто расширив `templates.json`. Сейчас существуют четыре несвязанных механизма:

1. зонные шаблоны расставляют в основном напольную мебель;
2. `compose2` комплектует значительно более богатый набор товаров;
3. декор и картины расставляются отдельными постпроцессами;
4. подушки, плед и шторы вообще исключены из 3D.

Правильная целевая модель — цельный паспорт комнаты с зависимыми слотами:

```text
комната
├─ посадка
│  ├─ диван
│  │  ├─ подушки
│  │  └─ плед
│  ├─ журнальный столик
│  │  └─ ваза
│  └─ ковёр
├─ медиа
│  └─ ТВ-тумба/стенка
├─ локальный свет
│  └─ торшер ИЛИ приставной столик/комод → лампа
├─ стена
│  └─ диван/комод → картины
├─ потолок
│  └─ центр зоны → люстра
├─ окно
│  └─ шторы
└─ свободный угол
   └─ кашпо
```

«На то же место шаблона» должно означать тот же семантический слот и якорь, а не замороженный мировой `x/y`. После замены дивана или столика координаты зависимых предметов необходимо пересчитать от фактической поверхности нового носителя.

---

## 1. Полный состав гостиной

Каноническое ядро уже определено корректно: диван, столик, ТВ-зона, ковёр, люстра, шторы, плед, подушки и локальный свет; от 16 м² — кресло, ваза и кашпо; хранение и столовая — по условиям [`.memory_bank/core/lr-checklist.md:17`](/home/pakar/igor/remlab/.memory_bank/core/lr-checklist.md:17). Композитор проверяет почти тот же набор [`tools/scout/compose2.py:1097`](/home/pakar/igor/remlab/tools/scout/compose2.py:1097).

Обозначения количества: `уникальные SKU / наборы из 21` в каждом стиле. Порядок: `Дж / Ло / Ми / Не / Ск / Со` — джапанди, лофт, минимализм, неоклассика, сканди, современный. Это срез банка из 126 наборов [`tools/scout/sets3.json:1`](/home/pakar/igor/remlab/tools/scout/sets3.json:1), а не весь живой каталог.

| Предмет | Обязательность | Покрытие банка по стилям | Целевая 3D-стратегия | Место |
|---|---|---|---|---|
| Диван | Всегда | 16/21 · 8/21 · 16/21 · 9/21 · 21/21 · 12/21 | Реальный меш | Главная посадочная стена, лицом к ТВ |
| Журнальный столик | Всегда | 11/18 · 11/18 · 12/20 · 13/19 · 13/20 · 10/19 | Реальный меш | 36 или 42,5 см от фронта дивана |
| ТВ-тумба | Всегда, если нет стенки | 8/21 · 4/21 · 13/21 · 13/21 · 10/21 · 10/21 | Реальный меш | На медиастене по оси основного сиденья |
| Стенка | Альтернатива тумбе | 0 во всех стилях | Реальный меш | Та же медиастена |
| Ковёр | Всегда | 4/21 · 4/21 · 4/21 · 3/21 · 7/21 · 5/21 | Плоскость с текстурой товара | Под столиком, передние ножки посадки на ковре |
| Люстра | Всегда | 20/21 · 20/21 · 19/21 · 21/21 · 20/21 · 21/21 | Реальный меш | Центр функциональной зоны, не обязательно центр комнаты |
| Шторы | При наличии окна | 2/21 · 2/21 · 2/21 · 1/21 · 1/21 · 2/21 | Параметрические полотна с фактурой SKU | От архитектурного проёма |
| Подушки | Всегда на диване | 4/21 · 5/21 · 4/21 · 4/21 · 4/21 · 3/21 | Объёмный меш | На сиденье у спинки |
| Плед | Всегда | 1/12 · 1/12 · 1/12 · 2/12 · 1/12 · 2/12 | Драпируемый меш | Подлокотник либо спинка дивана |
| Торшер | Один из вариантов локального света | 3/3 во всех стилях | Реальный меш | Снаружи от подлокотника, вне маршрута |
| Настольная лампа | Альтернатива торшеру | 3/19 · 4/21 · 4/21 · 4/19 · 3/21 · 2/21 | Реальный меш | На приставном столике или комоде |
| Приставной столик | Нужен для варианта с лампой | 0 во всех стилях | Реальный меш | У подлокотника дивана/кресла |
| Кресло | От 16 м² | 9/19 · 17/19 · 14/19 · 9/18 · 12/19 · 17/19 | Реальный меш | Фланг дивана, поворот к ТВ/столику |
| Ваза | От 16 м²; ниже — опция | 4/21 · 3/21 · 5/21 · 6/21 · 5/21 · 5/21 | Реальный меш | На столике или комоде |
| Кашпо | От 16 м² | 3/21 · 3/21 · 5/21 · 6/21 · 3/21 · 4/21 | Меш кашпо + нейтральное растение | Свободный угол или сбоку от окна |
| Картины | Условно обязательны при подходящей глухой стене | В `sets3` — 0; подбор идёт отдельным каталогом | Плоскость толщиной 2–3 см | Над диваном или комодом |
| Комод | Если нет иного хранения | 12/15 · 5/16 · 10/16 · 4/15 · 13/17 · 16/17 | Реальный меш | На оставшейся глухой стене |
| Стеллаж | По желанию/хранение | 4/7 · 3/6 · 4/6 · 6/7 · 4/6 · 3/4 | Реальный меш | У стены, не между диваном и ТВ |
| Обеденный стол | По площади и типу комнаты | 11/21 · 9/21 · 9/20 · 12/21 · 12/19 · 8/19 | Реальный меш | Отдельная dining-зона |
| Стулья | Вместе со столом | 10/21 · 8/21 · 7/20 · 6/21 · 9/19 · 10/19 | Реальные меши | Вокруг стола с рабочими зонами |
| Пуф | По желанию, только внутри посадочной схемы | 3/6 · 4/4 · 3/5 · 3/8 · 4/12 · 3/7 | Реальный меш | У кресла или свободного фланга столика |
| Книги, журналы, зелень | Не товары | Нет каталожной роли для продажи | Лёгкие процедурные ассеты | На носителях, но не в корзине |

Роли действительно распознаются каталогом, включая картины, плед, подушки, свет, кашпо, вазу и шторы [`tools/scout/category_map.py:66`](/home/pakar/igor/remlab/tools/scout/category_map.py:66). Но формальное покрытие шаблонов проверяет лишь крупные зоны и считает ковёр необязательным [`tools/scout/template_coverage.py:29`](/home/pakar/igor/remlab/tools/scout/template_coverage.py:29), [`tools/scout/template_coverage.py:60`](/home/pakar/igor/remlab/tools/scout/template_coverage.py:60). Поэтому текущий зелёный `ok` не доказывает готовность полной комнаты: в отчёте, например, у первого шаблона ковров `0`, но результат всё равно `ok:true` [`tools/scout/template-coverage.json:16`](/home/pakar/igor/remlab/tools/scout/template-coverage.json:16).

### Что делать мешем, плоскостью и процедурно

| Роль | Решение | Почему |
|---|---|---|
| Диван, кресло, столы, тумбы, лампы, ваза, кашпо, люстра | Меш конкретного SKU | Важны силуэт, объём, тени и параллакс |
| Подушка | Меш конкретного SKU, привязанный к поверхности сиденья | Пробная генерация признана естественной; спрайт сбоку сразу выдаёт плоскость |
| Плед | Меш с унифицированным drape-rig и проверкой цвета | Проба дала приемлемую форму, но искажённый цвет; простой Hunyuan без контроля материала недостаточен |
| Шторы | Один параметрический комплект полотен + текстура SKU | Карточки показывают интерьер целиком, генератор вырезал мебель вместо штор; геометрия должна строиться от окна |
| Ковёр | Процедурная горизонтальная плоскость | Точная геометрия — прямоугольник/контур, ценность товара в рисунке |
| Картина | Тонкая настенная плоскость | Товар фактически является изображением; текущая схема правильна |
| Книги/нейтральная зелень | Процедурный kit, не SKU | Они не должны попадать в цену и корзину |

Текущий канон всё ещё помечает подушки, плед и шторы как `cutout` [`tools/scout/rules/asset-strategies.json:15`](/home/pakar/igor/remlab/tools/scout/rules/asset-strategies.json:15), а экспорт прямо трактует их как «без места в 3D» [`tools/scout/salad/asset_strategy.py:56`](/home/pakar/igor/remlab/tools/scout/salad/asset_strategy.py:56). Это уже противоречит более позднему решению владельца: подушка и плед — мешами [`.memory_bank/plans/mesh-19-demo-full-3d.md:66`](/home/pakar/igor/remlab/.memory_bank/plans/mesh-19-demo-full-3d.md:66).

---

## 2. Каталог цельных шаблонов гостиной

Нужны не десятки отдельных зон, а семь цельных паспортов и один архитектурный модификатор. Во всех ниже `BASE` означает полный набор: диван, столик, ТВ-зона, ковёр, люстра, шторы при окне, подушки, плед, один локальный свет; при площади от 16 м² добавляются кресло, ваза и кашпо.

```text
Легенда:
D диван    A кресло    T столик    V ТВ-зона
R ковёр    L свет      P кашпо     d дверь
W окно     C обеденный стол        → главный маршрут
```

### LR-C1 — компактная, диван и ТВ напротив

Для 12–17 м², пропорции до примерно 1:1,4; две противоположные пригодные стены.

```text
┌──────────── W ────────────┐
│       art                 │
│     [ D D D ]   L         │
│       [ R ]               │
│        [T]                │
│                           │
│       [ V V ]       → d   │
└───────────────────────────┘
```

Состав: `BASE`; при 16–17 м² — одно кресло на свободном фланге, ваза и кашпо. Основной проход идёт сбоку от композиции, а не между диваном и столиком.

Частые ошибки: диван напротив окна вместо ТВ; дверь открывается в торец дивана; столик убран ради прохода; лампа зависает без носителя.

### LR-C2 — вытянутая, посадка вдоль длинной стены

Для 14–22 м², отношение сторон примерно от 1:1,4. Медиастена — противоположная длинная стена или её глухой участок.

```text
┌──────────────────────────────┐
│ art  [ D D D ] L             │
│      [ R R R ]               │
│        [ T ]                 │
│                      → → d   │
│       [ V V ]          P     │
└──────────── W ───────────────┘
```

Состав: `BASE`, кресло только если после него остаётся непрерывный маршрут. Столик предпочтительно овальный/круглый, но это должно быть свойством реального SKU.

Ошибка: пытаться центрировать всю композицию по комнате — в вытянутой комнате ось определяется пригодными стенами и маршрутом.

### LR-C3 — угловой диван

Для 18–28 м² либо комнаты с несколькими проёмами, где прямому дивану не хватает полноценной стены.

```text
┌──────────── W ──────────────┐
│ [ D D D D ]                 │
│ [ D ] [ R R ]       P       │
│       [ T ]                 │
│                             │
│        [ V V V ]      → d   │
└─────────────────────────────┘
```

Короткая секция не должна пересекать маршрут и не может быть зеркально «нарисована», если товар имеет фиксированную левую/правую конфигурацию. Текущий код уже различает реальный угловой диван от прямого [`services/planner-solver/planner/template.py:588`](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:588).

### LR-M1 — диван + кресло

Базовый дизайнерский вариант от 16 до 26 м².

```text
┌──────────── W ──────────────┐
│       art                   │
│     [ D D D ] L             │
│ A  ↗  [ R ]                 │
│       [ T ]                 │
│                             │
│      [ V V V ]        P  d  │
└─────────────────────────────┘
```

Кресло повёрнуто одновременно к столику и ТВ, но не далее 240 см от разговорной группы; 305 см — уже проектный жёсткий предел [`services/planner-solver/rules/templates.json:50`](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:50).

### LR-O1 — кухня-гостиная, диван-разделитель

Для открытого пространства примерно от 20–22 м² при существующей кухонной части.

```text
┌────────────── W ───────────────┐
│ КУХНЯ       [ C C C C ]        │
│             dining pendant     │
│ → → →                         d │
│          спинка дивана          │
│          [ D D D ] A            │
│            [R T]                │
│            [ V V ]       P      │
└─────────────────────────────────┘
```

Здесь нужны два потолочных слота:

- ambient над центром посадки;
- pendant над обеденным столом.

Диван не должен разрывать маршрут кухня→стол→дверь. Для обеденного светильника центр определяется столом, не центром комнаты; рекомендуемая высота низа — 76–91 см над столешницей. Это дизайнерская рекомендация, не строительная норма: [Ballard Designs](https://www.ballarddesigns.com/trends-features/features/guide/chandelier-buying-guide/). Проект уже держит 71–89 см [`services/planner-solver/rules/occupancy.json:315`](/home/pakar/igor/remlab/services/planner-solver/rules/occupancy.json:315).

### LR-O2 — кухня-гостиная, всё у стен

Запасной вариант для 18–26 м², если плавающий диван перекрывает маршрут.

```text
┌──────────── W ────────────┐
│ [ D D D ]      [ C C ]    │
│   [R T]         chairs    │
│                          d │
│ [ V V ]       → → →       │
└───────────────────────────┘
```

Полный состав сохраняется, но столовая уменьшается `4→2`, а не исчезает, если назначение помещения требует dining.

### LR-L1 — большая П-/Г-композиция

Для 28–40 м².

```text
┌──────────────────────────────┐
│ A       [ D D D ]        A   │
│  ↘      [ R R ]       ↙      │
│          [ T ]                │
│                              │
│        [ V V V ]        P    │
│ → → →                    d   │
└──────────────────────────────┘
```

Состав: `BASE`, два кресла, хранение, ваза, кашпо; возможно два журнальных столика только как отдельный вариант с двумя реальными SKU.

### LR-L2 — два дивана с ТВ, только Г-/П-форма

Для 32+ м².

```text
┌──────────────────────────────┐
│       [ D D D ]              │
│ [D2]    [ R ]       A        │
│         [ T ]                │
│                              │
│        [ V V V ]       P     │
└──────────────────────────────┘
```

Два дивана строго визави — плохой шаблон для обязательной ТВ-гостиной: один из них будет смотреть поперёк ТВ. Такой вариант допустим только для назначения `conversation/fireplace`, но не как универсальный `living+media`.

### LR-X1 — окно/эркер как модификатор

Это не отдельная комната, а разрешённая надстройка к любому шаблону: кресло чтения или кашпо в эркере, если оно не забрано основной посадкой. Текущий код уже имеет `window_plant`, `bay_plant` и проверку радиатора [`services/planner-solver/rules/templates.json:974`](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:974).

### Проходы и размеры

Следует разделять три класса чисел:

- проектный канон remlab: главный маршрут 91–107 см, вторичный комфортный 76–90 см, локальный подход 60–75 см [`services/planner-solver/rules/occupancy.json:345`](/home/pakar/igor/remlab/services/planner-solver/rules/occupancy.json:345);
- доступная среда: 915 мм для доступного маршрута по ADA; это официальный американский стандарт доступности, а не универсальная норма квартиры [US Access Board](https://www.access-board.gov/ada/);
- дизайнерские рекомендации: столик в 14–18″, то есть 35,5–45,7 см от дивана, около 1/2–2/3 его длины [Ethan Allen](https://www.ethanallen.com/en_US/shop-living-occasional-table-buying-guide).

Принятые в проекте 36 и 42,5 см хорошо укладываются в внешний диапазон [`services/planner-solver/rules/templates.json:1220`](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:1220). Для ковра правильный канон — столик целиком и передние ножки всей посадки на ковре; это также подтверждает [IKEA для углового дивана](https://www.ikea.com/gb/en/rooms/living-room/how-to/how-to-arrange-an-l-shaped-sofa-in-the-living-room-pub7947efe0/).

Approved Document M — официальный британский документ доступности, но его M4(2)/M4(3) применяется только к соответствующим категориям жилья, а не автоматически к любой сцене remlab [GOV.UK](https://www.gov.uk/government/publications/access-to-and-use-of-buildings-approved-document-m). Поэтому 1500-мм разворот следует вводить как отдельный профиль `accessible`, а не как hard для всех комнат.

### Деградация

Правильные уровни:

| Уровень | Разрешённое изменение | Что нельзя удалять |
|---|---|---|
| A | Полный состав и все условные слои | Всё |
| B | Столовая `6→4→2`, более узкое реальное хранение | Ядро, проходы, декор на ядре |
| C | Для комнаты <16 м² выбрать паспорт без кресла/вазы/кашпо; для ≥16 это не «тихий дроп», а отказ | Диван, столик, ТВ, ковёр, свет, шторы, подушки, плед |
| D | Переключить вариант `лампа+столик → торшер`; поменять место вазы `комод → столик` | Сам локальный свет и сама требуемая роль |
| FAIL | Ни один полный разрешённый состав не проходит | Ничего не выбрасывать постфактум |

Текущий уровень C называет столик опциональным, а D разрешает убрать кашпо [`services/planner-solver/rules/templates.json:1391`](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:1391). Это противоречит как ядру комплектов, так и требованию владельца о полном шаблоне.

---

## 3. Локальная геометрия мелкого

Текущая локальная система подходит: `+x` вправо, `+y` вперёд в комнату [`services/planner-solver/planner/template.py:198`](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:198). Но одного `w×d×h` носителя недостаточно. Каждому мешу-носителю нужен паспорт поверхностей:

```json
{
  "support_surfaces": {
    "seat": {"polygon": [[-82,-28],[82,-28],[82,22],[-82,22]], "z": 44},
    "top": {"polygon": [[-45,-25],[45,-25],[45,25],[-45,25]], "z": 42}
  },
  "edges": {
    "seat_back": {"y": -28, "z": 44},
    "arm_left_top": {"x": -94, "z": 63},
    "arm_right_top": {"x": 94, "z": 63}
  }
}
```

Без этих данных подушку нельзя честно ставить по внешнему bbox дивана: у разных диванов отличаются толщина подлокотников, глубина сиденья, высота подушки и угловая секция.

### Подушки

Количество нужно считать по полезной ширине сиденья `U`, а не только по внешней ширине товара:

- `U < 180`: 2;
- `180 ≤ U < 240`: 3;
- `U ≥ 240`: 4;
- у углового дивана считать отдельно по основной секции; одну дополнительную подушку допустимо поставить у внутреннего угла.

Если паспорт сиденья отсутствует, временный fallback по внешней ширине: 2 до 189 см, 3 при 190–253 см, 4 от 254 см. Нынешний композитор даёт две и только третью от 254 см [`tools/scout/compose2.py:984`](/home/pakar/igor/remlab/tools/scout/compose2.py:984), что слишком редко для трёхместных диванов.

Геометрия:

```text
спинка
┌───────────────────────────┐
│  ◇       ◇       ◇        │  y = seat_back + 6…10
│                           │  наклон 8…12° к спинке
└────── полезное сиденье ───┘
   8–12 см           8–12 см
```

- опорная точка меша — нижний центр подушки;
- крайняя подушка отстоит от внутренней грани подлокотника на 8–12 см;
- промежуточные распределяются симметрично;
- между bbox подушек 4–10 см;
- если фактическая группа не помещается, отклоняется SKU подушки или берётся другой разрешённый `count`, но подушки не уменьшаются масштабированием.

IKEA рекомендует большие подушки ставить сзади, меньшие впереди; плед — на подлокотник или спинку [IKEA](https://www.ikea.com/se/en/rooms/living-room/how-to/how-to-mix-and-match-cushions-on-your-sofa-pxm6ec8061054ad11eb9ff341939922b793/).

### Плед

Два валидных слота:

1. `throw.arm_left/right`: верхняя полоса лежит на подлокотнике, 35–60 см свисает наружу;
2. `throw.back`: занимает около 25–35% ширины основной секции и свисает на сиденье.

Пледу нужен drape-anchor, а не обычная трансформация rigid mesh. Если у дивана нет паспорта края, результат должен быть `CARRIER_SURFACE_UNKNOWN`, а не плед на полу или только в списке.

### Лампа и ваза

Для любой столешницы используется `top.polygon`, сжатый внутрь минимум на:

```text
max(8 см, половина диаметра основания + 3 см)
```

- лампа: задняя четверть приставного столика или комода, ближе к стороне чтения;
- ваза на журнальном столике: задняя левая/правая четверть, не геометрический центр;
- суммарный декор не должен занимать более примерно 20% полезной площади столешницы;
- между bbox предметов минимум 6–8 см;
- `elev = support_surface.z`, а не придуманная высота.

Текущий код использует только журнальный или обеденный стол, отступ 4 см и укладывает весь декор одним центральным рядом [`tools/scout/draft_render.py:430`](/home/pakar/igor/remlab/tools/scout/draft_render.py:430). Это технически детерминированно, но визуально не является местом шаблона.

Если лампе нет носителя:

1. попробовать цельный вариант с приставным столиком;
2. затем цельный вариант с комодом;
3. затем заменить всю группу на `floor_lamp`;
4. если ни один вариант не проходит — отказ `LOCAL_LIGHT_NO_HOST`.

Ставить настольную лампу на ТВ-тумбу как общий fallback не следует: она конфликтует с экраном и меняет смысл медиазоны.

### Картины

Текущий механизм полезно сохранить, но место должна выбирать композиция, а исполнитель — пересчитывать от фактического носителя:

- общая ширина группы около 2/3 носителя;
- низ на 10–20 см выше спинки дивана;
- 5–8 см между рамами;
- проверка окна, двери, штор и высокой мебели.

Проектный `occupancy.json` уже содержит 10–20 см [`services/planner-solver/rules/occupancy.json:319`](/home/pakar/igor/remlab/services/planner-solver/rules/occupancy.json:319). Отдельный `wall-art.json` использует 22–25 см [`data/flat3d/wall-art.json:12`](/home/pakar/igor/remlab/data/flat3d/wall-art.json:12), то есть источники расходятся. Внешняя рекомендация — 4–6″, примерно 10–15 см, и ширина около 2/3 мебели [Pottery Barn](https://www.potterybarn.com/pages/features/how-to-hang-artwork/). Я бы оставил hard 10–20 см и default 15 см.

### Кашпо и люстра

Кашпо — самостоятельный напольный слот. Предпочтительно 60 см от мебели, но оно обязано пройти маршруты и радиатор. Сейчас паспорт говорит 30 см [`services/planner-solver/rules/templates.json:969`](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:969), а исполнитель жёстко требует 60 см [`services/planner-solver/planner/template.py:3822`](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:3822); это надо унифицировать.

Люстра:

- в обычной гостиной — центр посадочного ковра/разговорной зоны;
- в dining — центр фактического стола;
- в свободном проходе низ не ниже 210–213 см;
- над столом — 71–89 см от столешницы.

---

## 4. Универсальный формат

Формат спальни уже задаёт правильные сущности: `purpose`, `anchors`, `predicates`, `groups`, `relations`, целые `levels`, `invariants` и диагностику [`.memory_bank/_intake/codex/2026-11-12-bedroom-templates-answer.md:90`](/home/pakar/igor/remlab/.memory_bank/_intake/codex/2026-11-12-bedroom-templates-answer.md:90).

Ниже два полных паспорта композиции. Это проект контракта, не готовый исполняемый файл.

### Компактная гостиная

```json
{
  "schema_version": "room-composition/1",
  "unit": "cm",
  "room_type": "living",
  "templates": [
    {
      "id": "lr.compact_opposed",
      "purpose": ["living", "media"],
      "priority": 10,
      "area_m2": {"min": 12, "max": 17},
      "anchors": {
        "seating_wall": {
          "type": "wall_segment",
          "qualifiers": ["solid_or_door_clear"]
        },
        "media_wall": {
          "type": "wall_segment",
          "relation": "opposite_seating_wall"
        },
        "window": {
          "type": "opening",
          "required_when": "room_has_window"
        },
        "ceiling_living": {
          "type": "zone_centroid",
          "of": "seating"
        }
      },
      "transforms": {
        "wall_assignments": "all",
        "rotations_deg": [0, 90, 180, 270],
        "mirror": true
      },
      "predicates": [
        {"kind": "door_swing_clear"},
        {"kind": "radiator_clear"},
        {
          "kind": "route",
          "from": "entry_door",
          "to": ["seating", "window"],
          "rule_ref": "distances_cm.passage_main"
        },
        {
          "kind": "tv_visibility",
          "from": "sofa",
          "to": "media",
          "rule_ref": "tv_sofa_pair"
        }
      ],
      "groups": [
        {
          "id": "seating",
          "required": true,
          "variants": ["sofa_table_rug"],
          "slots": [
            {
              "id": "sofa",
              "role": "диван",
              "fit": "template_envelope",
              "rule_ref": "template_slot_envelopes.slots.диван"
            },
            {
              "id": "coffee",
              "role": "столик",
              "fit": "template_envelope",
              "relation": {
                "kind": "front_gap",
                "carrier": "sofa",
                "rule_ref": "geometry.coffee_gap_cm"
              }
            },
            {
              "id": "rug",
              "role": "ковёр",
              "fit": "template_envelope",
              "relation": {
                "kind": "front_legs_on_surface",
                "carriers": ["sofa"],
                "tuck_cm": 25
              }
            }
          ]
        },
        {
          "id": "sofa_soft",
          "required": true,
          "depends_on": "sofa",
          "variants": ["pillows_by_seat_width_throw_arm", "pillows_by_seat_width_throw_back"],
          "slots": [
            {
              "id": "pillows",
              "role": "подушка",
              "quantity_rule": "living.pillows_by_usable_seat_width",
              "fit": "carrier_surface",
              "surface": "sofa.seat"
            },
            {
              "id": "throw",
              "role": "плед",
              "quantity": 1,
              "fit": "carrier_edge",
              "surface": "sofa.arm_or_back"
            }
          ]
        },
        {
          "id": "media",
          "required": true,
          "variants": ["tv_stand"],
          "slots": [
            {
              "id": "tv_stand",
              "role": "тв-тумба",
              "fit": "template_envelope",
              "rule_ref": "template_slot_envelopes.slots.тв-тумба"
            }
          ]
        },
        {
          "id": "local_light",
          "required": true,
          "variants": ["floor_lamp", "side_table_table_lamp", "dresser_table_lamp"]
        },
        {
          "id": "ceiling_light",
          "required": true,
          "variants": ["living_chandelier"],
          "slots": [
            {
              "id": "chandelier",
              "role": "люстра",
              "anchor": "ceiling_living",
              "fit": "diameter_and_drop",
              "rule_ref": "chandelier_size"
            }
          ]
        },
        {
          "id": "window_textile",
          "required_when": "room_has_window",
          "variants": ["curtains_to_opening"]
        },
        {
          "id": "surface_decor",
          "required_when": "area_m2>=16",
          "variants": ["vase_on_coffee", "vase_on_dresser"]
        },
        {
          "id": "floor_decor",
          "required_when": "area_m2>=16",
          "variants": ["corner_planter", "window_side_planter"]
        },
        {
          "id": "wall_art",
          "required_when": "eligible_carrier_wall",
          "variants": ["art_over_sofa", "art_over_dresser"]
        }
      ],
      "relations": [
        {"kind": "media_opposite_primary_seat"},
        {"kind": "no_route_between_sofa_and_coffee"},
        {"kind": "children_follow_actual_carrier"},
        {"kind": "curtains_follow_opening"}
      ],
      "levels": [
        {
          "id": "A",
          "use": {
            "seating": "sofa_table_rug",
            "sofa_soft": "pillows_by_seat_width_throw_arm",
            "media": "tv_stand",
            "local_light": "side_table_table_lamp",
            "ceiling_light": "living_chandelier",
            "window_textile": "curtains_to_opening",
            "surface_decor": "vase_on_coffee",
            "floor_decor": "corner_planter",
            "wall_art": "art_over_sofa"
          }
        },
        {
          "id": "B",
          "use": {
            "seating": "sofa_table_rug",
            "sofa_soft": "pillows_by_seat_width_throw_back",
            "media": "tv_stand",
            "local_light": "floor_lamp",
            "ceiling_light": "living_chandelier",
            "window_textile": "curtains_to_opening",
            "surface_decor": "vase_on_coffee",
            "floor_decor": "window_side_planter",
            "wall_art": "art_over_sofa"
          }
        }
      ],
      "invariants": [
        "required_groups_complete",
        "sku_dimensions_intact",
        "dependent_slots_have_carrier",
        "door_clear",
        "required_routes",
        "tv_visible",
        "no_silent_unplaced"
      ],
      "selection_tags": ["opposed_media", "compact", "wall_role_based"]
    }
  ]
}
```

### Кухня-гостиная с диваном-разделителем

```json
{
  "schema_version": "room-composition/1",
  "unit": "cm",
  "room_type": "kitchen_living",
  "templates": [
    {
      "id": "lr.openplan_sofa_divider",
      "purpose": ["living", "media", "dining"],
      "priority": 20,
      "area_m2": {"min": 20},
      "anchors": {
        "kitchen_boundary": {"type": "zone_edge", "of": "kitchen"},
        "media_wall": {
          "type": "wall_segment",
          "qualifiers": ["solid", "outside_kitchen"]
        },
        "seating_axis": {
          "type": "axis",
          "relation": "parallel_kitchen_boundary"
        },
        "dining": {
          "type": "free_zone",
          "relation": "between_kitchen_and_seating_or_side"
        },
        "window": {
          "type": "opening",
          "required_when": "room_has_window"
        },
        "ceiling_living": {"type": "zone_centroid", "of": "seating"},
        "ceiling_dining": {"type": "item_centroid", "of": "dining_table"}
      },
      "transforms": {
        "wall_assignments": "all",
        "rotations_deg": [0, 90, 180, 270],
        "mirror": true
      },
      "predicates": [
        {"kind": "kitchen_zone_reserved"},
        {"kind": "door_swing_clear"},
        {
          "kind": "route",
          "from": "entry_door",
          "to": ["kitchen", "dining", "seating", "window"],
          "rule_ref": "distances_cm.passage_main"
        },
        {"kind": "tv_visibility", "from": "sofa", "to": "media"},
        {"kind": "dining_operational_envelope", "rule_ref": "zones.dining.rules"}
      ],
      "groups": [
        {
          "id": "seating",
          "required": true,
          "variants": ["floating_sofa_armchair_table_rug", "floating_sectional_table_rug"]
        },
        {
          "id": "sofa_soft",
          "required": true,
          "depends_on": "seating.primary_sofa",
          "variants": ["pillows_by_seat_width_throw_arm", "pillows_by_seat_width_throw_back"]
        },
        {
          "id": "media",
          "required": true,
          "variants": ["tv_stand", "media_wall_unit"]
        },
        {
          "id": "dining",
          "required": true,
          "variants": ["table_4_chairs", "table_2_chairs"],
          "slots": [
            {
              "id": "dining_table",
              "role": "стол обеденный",
              "fit": "template_envelope",
              "rule_ref": "template_slot_envelopes.slots.стол обеденный"
            },
            {
              "id": "dining_chairs",
              "role": "стул",
              "fit": "template_envelope",
              "relation": {"kind": "around_carrier", "carrier": "dining_table"}
            }
          ]
        },
        {
          "id": "local_light",
          "required": true,
          "variants": ["floor_lamp", "side_table_table_lamp"]
        },
        {
          "id": "ceiling_living",
          "required": true,
          "variants": ["living_chandelier"]
        },
        {
          "id": "ceiling_dining",
          "required": true,
          "variants": ["dining_pendant"]
        },
        {
          "id": "window_textile",
          "required_when": "room_has_window",
          "variants": ["curtains_to_opening"]
        },
        {
          "id": "surface_decor",
          "required": true,
          "variants": ["vase_on_coffee", "vase_on_dresser"]
        },
        {
          "id": "floor_decor",
          "required": true,
          "variants": ["corner_planter", "window_side_planter"]
        },
        {
          "id": "wall_art",
          "required_when": "eligible_carrier_wall",
          "variants": ["art_over_sofa", "art_over_dresser"]
        }
      ],
      "relations": [
        {"kind": "sofa_back_faces_kitchen_or_dining"},
        {"kind": "media_opposite_primary_seat"},
        {"kind": "dining_pendant_follows_table"},
        {"kind": "living_chandelier_follows_seating_zone"},
        {"kind": "children_follow_actual_carrier"},
        {"kind": "kitchen_route_not_cut_by_seating"}
      ],
      "levels": [
        {
          "id": "A",
          "use": {
            "seating": "floating_sofa_armchair_table_rug",
            "sofa_soft": "pillows_by_seat_width_throw_arm",
            "media": "tv_stand",
            "dining": "table_4_chairs",
            "local_light": "side_table_table_lamp",
            "ceiling_living": "living_chandelier",
            "ceiling_dining": "dining_pendant",
            "window_textile": "curtains_to_opening",
            "surface_decor": "vase_on_coffee",
            "floor_decor": "corner_planter",
            "wall_art": "art_over_sofa"
          }
        },
        {
          "id": "B",
          "use": {
            "seating": "floating_sofa_armchair_table_rug",
            "sofa_soft": "pillows_by_seat_width_throw_back",
            "media": "tv_stand",
            "dining": "table_2_chairs",
            "local_light": "floor_lamp",
            "ceiling_living": "living_chandelier",
            "ceiling_dining": "dining_pendant",
            "window_textile": "curtains_to_opening",
            "surface_decor": "vase_on_coffee",
            "floor_decor": "window_side_planter",
            "wall_art": "art_over_sofa"
          }
        }
      ],
      "invariants": [
        "required_groups_complete",
        "sku_dimensions_intact",
        "dependent_slots_have_carrier",
        "door_clear",
        "required_routes",
        "kitchen_clear",
        "dining_operational",
        "tv_visible",
        "no_silent_unplaced"
      ],
      "selection_tags": ["open_plan", "sofa_divider", "two_ceiling_zones"]
    }
  ]
}
```

### Жёсткий −20/+10 и другие виды подбора

Жёсткий конверт оставить для независимых жёстких предметов:

- диван, кресло;
- журнальный и обеденный стол;
- ТВ-тумба/стенка;
- комод, стеллаж, витрина;
- ковёр по длинной стороне;
- стул, пуф, кашпо, торшер;
- приставной столик после появления роли.

Конверт уже централизован в [`services/planner-solver/rules/zones.json:690`](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:690), а роли без правила сейчас вообще не фильтруются [`tools/scout/slot_rules.py:69`](/home/pakar/igor/remlab/tools/scout/slot_rules.py:69).

Для зависимых предметов нужен другой hard-fit:

| Роль | Проверка |
|---|---|
| Подушки | Помещается ли группа на `seat_surface` |
| Плед | Есть ли подходящий arm/back edge и допустимая ширина драпировки |
| Лампа/ваза | Влезает ли основание в `top_surface` после отступов и коллизий |
| Картины | Доля ширины носителя, высота до потолка и свободный участок стены |
| Шторы | Ширина/высота проёма, радиатор и сторона открывания |
| Люстра | Диаметр зоны и фактическая высота подвеса |

Применять слепой −20/+10 к подушке или вазе неверно: у них не один идеальный размер, а допустимая поверхность носителя.

### Что менять в солвере и экспорте

1. Над существующими зонными `Block` добавить компилятор цельного `RoomTemplate`.
2. Перебирать все назначения ролей стен, повороты и отражения; стороны света использовать только как геометрию, не как семантику.
3. Сначала связывать реальные SKU с независимыми слотами, затем строить блок по их фактическим размерам.
4. После установки носителя вычислять зависимые слоты по его `support_surfaces`.
5. Проверять весь уровень атомарно; запретить автоматическое понижение группы из-за отсутствующей роли. Сейчас такое понижение выполняется прямо в [`services/planner-solver/planner/template.py:1688`](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1688).
6. `Block.rel` расширить полями `parent_slot`, `support_surface`, `elev_cm` и `dependency`; сейчас он хранит только плоские локальные `x/y/rot` [`services/planner-solver/planner/template.py:205`](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:205).
7. Экспортировать все предметы одним списком placements. `decor`, `soft_items` и `wall_art` не должны быть параллельными моделями истинности.
8. Существующий `placeWallArt` оставить исполнителем коллизий стены, но опору и вариант должен задавать комнатный шаблон. Сейчас он сам перебирает опоры после расстановки [`lib/configurator/wall-art.ts:74`](/home/pakar/igor/remlab/lib/configurator/wall-art.ts:74).
9. Ввести раздельные диагностики:

```text
CATALOG_NO_STYLE_MATCH
CATALOG_NO_SIZE_MATCH
TEMPLATE_GEOMETRY_FAIL
CARRIER_MISSING
CARRIER_SURFACE_UNKNOWN
ASSET_MISSING
HANDEDNESS_MISMATCH
WALL_ROLE_NO_MATCH
```

---

## 5. Хватит ли товаров

### Что уже достаточно

Для одного набора на стиль достаточно диванов, столиков, ТВ-тумб, кресел, люстр, ваз и кашпо. Люстр в банке 32 уникальных SKU, а аудит 27.10 уже нашёл 63 готовых меша — отсутствие люстры в демо является главным образом проблемой экспорта, не генерации [`.memory_bank/plans/mesh-19-demo-full-3d.md:111`](/home/pakar/igor/remlab/.memory_bank/plans/mesh-19-demo-full-3d.md:111).

### Реальные дыры

1. Приставной столик: ноль во всех стилях. Из-за этого полноценный вариант «лампа на столике у дивана» не существует.
2. Стенка: ноль; допустимо жить на ТВ-тумбе, но соответствующие шаблоны нельзя объявлять.
3. Плед: всего 2 уникальных SKU на весь банк, в наборах только 12/21 на стиль.
4. Шторы: всего 5 уникальных SKU, по 1–2 на стиль.
5. Подушки: 11 уникальных SKU; сцену заполнить можно, но разнообразие быстро повторяется.
6. Торшеры: всего три уникальных товара и только три набора каждого стиля.
7. Картины не входят в `sets3`; отдельный downstream-подбор нельзя считать покрытием цельного паспорта.
8. Витрины отсутствуют в лофте, минимализме и современном стиле.
9. Ковры формально присутствуют, но старый coverage показывает ноль в строгих конвертах отдельных шаблонов. Нужен новый отчёт по реальным цельным паспортам.

### Рекомендуемое пополнение каталога

Минимальная цель — хотя бы два пригодных SKU каждой дефицитной роли на стиль:

| Роль | Сейчас уникальных в банке | Цель | Добрать ориентировочно |
|---|---:|---:|---:|
| Приставной столик | 0 | 12 | +12 |
| Плед | 2 | 12 | +10 |
| Шторы | 5 | 12 | +7 |
| Торшер | 3 | 12 | +9 |
| Подушки | 11 | 18 | +7 |
| Картины в сете | 0 | 12 | +12 связок из существующего каталога |
| Ковры нужных размеров | Неизвестно после hard-band | 2 размера × 6 стилей | До +12 после повторного аудита |

### Генерация мешей

Точную очередь без живой БД и mesh-registry назвать нельзя. Для приёмочного демо на шесть стилей разумная верхняя оценка:

- 6 кресел;
- 6 локальных светильников;
- 6 ваз;
- 6 кашпо;
- до 11 подушек;
- 2 пледа.

Итого: до 37 проверок/генераций меша. Из этого надо вычесть уже готовые привязки. Люстры сначала следует связать с готовыми 63 мешами, а не генерировать заново. Шторы — один параметрический kit и текстуры, ковры/картины — без генерации мешей.

---

## 6. Проверка до кода

| Комната | Предварительный шаблон | Почему | Что ещё требуется |
|---|---|---|---|
| Демо 439×325, 14,4 м² | `LR-C1 compact_opposed` | Две длинные глухие стены могут нести диван и ТВ; запад занят окном и радиатором, восток — дверью | Проверить оба назначения north/south, дугу восточной двери и путь вдоль восточного борта |
| Малая 350×400, 14 м² | `LR-C1` | Почти квадратная, состав без кресла по канону | Синтетический экзамен с дверью в углу и по центру |
| Малая 300×500, 15 м² | `LR-C2 elongated` | Сильная вытянутость, нужен боковой маршрут | Проверить круглый/овальный реальный столик |
| UK lounge 377×420, 15,8 м² | `LR-C1`, запасной `LR-C2` | Размер известен и подходит компактной гостиной | В репозитории есть только строка размера, нет достоверных проёмов; решение условное [`e2e/trial.spec.ts:44`](/home/pakar/igor/remlab/e2e/trial.spec.ts:44) |
| «Этажи» kitchen-living 20,8 м² | `LR-O1`, fallback `LR-O2` | Совмещённое назначение и достаточная площадь для дивана-разделителя | Доступна только подпись площади 20,8 и приблизительный контур 20,26; без проёмов окончательно выбирать нельзя [`tests/floorplan/test_area_labels.py:17`](/home/pakar/igor/remlab/tests/floorplan/test_area_labels.py:17) |
| Синтетическая Г-образная кухня-гостиная 620×780 | `LR-O1` | Специальный L-контур уже используется как тест кухни-гостиной | Добавить кухонную запрещённую зону и реальные мелкие роли [`services/planner-solver/tests/test_beam.py:141`](/home/pakar/igor/remlab/services/planner-solver/tests/test_beam.py:141) |
| Большая L-комната 30,25 м² | `LR-L1`, annex как dining/reading | Основной прямоугольник 600×400 и отдельный хвост 250×250 позволяют разделить функции | Проверить портал и дверь хвоста; геометрия подтверждена тестом [`tools/scout/tests/test_trial_bundle.py:319`](/home/pakar/igor/remlab/tools/scout/tests/test_trial_bundle.py:319) |
| Прямоугольная 30–35 м² | `LR-L1` | П-композиция диван + два кресла, полноценное хранение | Два варианта двери и окна напротив ТВ |
| 40+ м² | `LR-L2` или `LR-O1+L1` | Два дивана или отдельные living/dining-зоны | Не использовать чистое визави при обязательном ТВ |

Демо-комната действительно 439×325, с западным окном/радиатором и восточной дверью [`tools/scout/flat215.json:5`](/home/pakar/igor/remlab/tools/scout/flat215.json:5).

### Что рисовать на масштабных схемах

Повторить сильные стороны `bedroom_schemes.py`:

- единый масштаб внутри листа и сетка 50 см;
- реальные SKU и их реальные габариты;
- проёмы, дуги двери, радиаторы;
- цветные зоны главного и вторичного маршрутов;
- конус/ось взгляда на ТВ и фактическая дистанция;
- ковёр с отметкой передних ножек;
- центр living-люстры и dining-подвеса;
- подушки, плед, лампа и ваза хотя бы условными знаками на плане плюс увеличенный inset носителя;
- красная штриховка каждого нарушения;
- рядом «первый отвергнутый A» и выбранный B/C;
- таблица причин отказа с измеренным и требуемым числом.

Образец уже масштабирует схему по комнате, рисует сетку 50 см и явно показывает отказ/успех [`tools/scout/bedroom_schemes.py:1254`](/home/pakar/igor/remlab/tools/scout/bedroom_schemes.py:1254). Для гостиной лист должен называться не просто «вариант стиля», а:

```text
комната → назначение ролей стен → шаблон → уровень → реальные SKU → результат
```

---

## Что сохранить, добавить и убрать

| Сохранить | Добавить | Исправить/убрать |
|---|---|---|
| Фактические размеры SKU и запрет масштабирования [`template.py:1657`](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1657) | Цельный паспорт комнаты над зонными блоками | Автоматическое понижение группы при отсутствии роли |
| Локальные координаты `Block` | Дерево `carrier → child` и support surfaces | Подушки/плед как `list_only` |
| Проверки двери, маршрутов, окна, радиатора | Перебор всех ролей стен, поворотов и зеркал | Отдельную несогласованную расстановку декора |
| TV scoring и целевые 1,6 диагонали [`templates.json:1325`](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:1325) | Handedness углового дивана | Визави-диваны как универсальную ТВ-схему |
| `placeWallArt` как исполнитель стены | Выбор опоры картины внутри шаблона | Разные 10–20 и 22–25 см для картин |
| Процедурные плоскости ковра/картины | Параметрические шторы и drape-плед | Cutout-шторы в 3D |
| Атомарность шаблона [`template.py:20`](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:20) | Атомарность уже на уровне всей комнаты | «Не поставился один предмет, остальные оставили» |

Главный критерий готовности гостиной: в результате не должно быть ни одного товара со статусом «есть в комплекте и цене, но места в 3D нет». Если носитель, поверхность, нужный размер или актив отсутствуют, это должен быть объяснимый отказ всего уровня шаблона, а не скрытая деградация.

Файлы не изменялись.