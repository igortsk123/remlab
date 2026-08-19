Главная поправка: не заводить `corner`, `window` и `bay` как равноправные функциональные зоны. Это архитектурные якоря. Иначе одно кресло получит три конкурирующих имени.

Правильная модель:

`функция (reading / quiet / storage / decor) × якорь (corner / window / bay / fireplace) × форма`

Исключение — `window_seat`: это самостоятельная атомарная композиция с особым товаром и геометрией.

### Минимальная библиотека канонов

| Канон | Состав | Инвариант / контракт | Реализация |
|---|---|---|---|
| `reading.corner_vignette` | кресло + торшер/лампа + приставной столик; пуф optional | кресло в угловом регионе; свет рядом с плечом; поверхность в пределах досягаемости; лицо в комнату/к фокусу, не в стену; свободный подход | Новый вариант существующего `place_reading`; текущий `build_reading` слишком слаб — допускает одного любого компаньона |
| `reading.window_anchor` | кресло; столик/лампа optional | кресло действительно примыкает к окну; явный `facing_target`; не закрывает радиатор/маршрут | Уже есть; нужен отдельный validator канона |
| `reading.bay_anchor` | кресло; столик/лампа optional | предмет внутри реального bay-региона; доступен; ориентирован внутрь комнаты | Объединить существующие `reading.bay` и `bay_armchair`, а не держать две зоны |
| `quiet.quiet_chat` | 2 кресла + общая поверхность | связная группа; кресла ориентированы друг к другу/столику; поверхность обязательна | Уже есть |
| `quiet.fireplace_flank` | 2 кресла + камин; столик optional | оба кресла относятся к достижимому камину; лимит угла и дистанции; проход к камину | Уже есть |
| `window_seat.bench_under_window` | банкетка/скамья `window_seat_capable`; подушки optional | спинка к оконной стене; высота не выше допустимой относительно подоконника; передний доступ; ordinary radiator — clearance, неизвестный over-radiator — fail-closed | Новая зона и placer |
| `window_seat.bay_bench` | та же банкетка в эркере | containment в bay; передний доступ; не мешает створкам/радиатору | Новый вариант того же placer |
| `decor.corner_plant` | крупное растение | действительно угловой регион; вне двери/маршрута; свет — preference, не hard | Код почти уже есть, добавить паспорт схемы |
| `decor.bay_plant` | растение | находится в bay/window opportunity; не блокирует окно и маршрут | Код почти уже есть |
| `fireplace.storage_flanks` / `plant_flanks` / `solo` | камин + симметричная пара или камин один | симметрия и выравнивание для flanks; тепловой зазор; видимость из посадки; `solo` допустим как архитектурный фокус | Геометрия уже есть, нужны паспорта и variant tags |
| `media.fireplace_side_by_side` | ТВ-носитель + камин на одной стене | общий wall anchor; оси/зазоры; оба видимы из посадки | Уже есть как `build_media_fireplace`, оформить схемой внутри `media` |
| `storage.corner_tower` | узкий стеллаж/витрина | вплотную к одной из стен угла, не по диагонали; доступ к фасаду; вне окна/двери | Вариант `place_storage` с corner filter/rank |

Композиция `кресло + столик + свет` прямо подтверждается как базовая формула читального угла у [Homes & Gardens](https://www.homesandgardens.com/interior-design/chair-table-lamp-layout-hack); для больших помещений также встречается отдельная пара кресел со столиком и светом, но это уже `quiet`, а не `reading` ([H&G о зонировании гостиной](https://www.homesandgardens.com/interior-design/the-library-how-to-design-the-perfect-living-room-layout)). Оконные сиденья, включая встроенное хранение и интеграцию со стеллажами, — устойчивый тип, подтверждаемый [Architectural Digest](https://www.architecturaldigest.com/gallery/window-seat-ideas) и [Livingetc](https://www.livingetc.com/ideas/window-seat-ideas).

### Граница между зонами

- `reading` — одно основное место для индивидуального занятия. В обычном углу требует и света, и поверхности. У окна/bay допустим singleton благодаря сильному архитектурному якорю.
- `quiet` — вторичная социальная группа: два кресла и общая поверхность либо пара у достижимого камина.
- `window_seat` — банкетка/скамья, конструктивно связанная с окном. Свободное кресло сюда не относится.
- `corner` — только координатный opportunity/anchor, не зона.
- `bay` — архитектурная форма, не отдельная функция. Нынешний `bay_armchair` лучше сделать alias/deprecated в пользу `reading.bay_anchor`.
- `fireplace` — оформление и доступность самого фокуса. Посадка возле него принадлежит `reading` при одном кресле или `quiet` при паре.
- `decor` и `storage` могут иметь corner/window-варианты, но не становятся reading только из-за местоположения.

Сейчас дублирование действительно заложено в коде: `place_reading` уже генерирует bay-кандидаты, но существует ещё отдельный `place_bay_armchair` — [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2011) и [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2146).

### Что не добавлять сейчас

- `reading.pair_facing` — дубль `quiet_chat`.
- `reading.by_fireplace` с парой кресел — дубль `quiet.fireplace_flank`, контракт которого уже реализован в [validate.py](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:1458).
- Общую зону `corner`.
- `bench_with_storage` как отдельную геометрическую схему: это capability `integrated_storage/counts_as_storage` у `bench_under_window`.
- `media_wall.tv_in_cabinetry`: это уже существующий `media_installation`; новый namespace только разделит одну функцию.
- `corner_lamp` как активную зону. Одиночный statement-торшер встречается в практике ([Livingetc](https://www.livingetc.com/ideas/living-room-corner-ideas)), поэтому это не ошибка дизайна, но он конфликтует с вашим продуктовым правилом «одиночный предмет не образует зону». Можно оставить sleeping-каноном.
- `corner_desk` сейчас. Практика реальна ([H&G](https://www.homesandgardens.com/ideas/living-room-corner-ideas)), но это новая функция `work`, требующая `work_need`, стола, рабочего кресла и света. Пустой угол сам по себе не даёт права поставить кабинет.
- `tv_over_fireplace`. Для него нет вертикальной модели высот экрана, топки и тепловых зазоров; к тому же это спорный, а не универсальный канон — современные источники уже относят его к устаревающим решениям ([H&G](https://www.homesandgardens.com/interior-design/living-rooms/dated-living-room-trends-2026)). Пока только sleeping.
- `art_gallery_wall` внутри `media`: это будущая зона `focus_wall` для сценариев `media_need=preferred/off`, но не альтернатива обязательному ТВ.

### Что уже есть в коде, но не описано данными

Нужно сначала синхронизировать паспорта с фактической геометрией:

- `fireplace` уже строит storage/plant/chair flanks и solo-fallback — [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2210).
- `media_fireplace` уже реализует камин и ТВ рядом — [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2249).
- `decor` уже ставит растения в углы и bay — [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:3000).
- `media_installation` уже покрывает ТВ, интегрированный в корпусную композицию. Это распространённая практика: [H&G о встроенной media cabinetry](https://www.homesandgardens.com/interior-design/living-rooms/built-in-cabinet-ideas-for-family-rooms).

### Порядок внедрения

1. Завести схемы для уже существующей геометрии: `decor.corner_plant/bay_plant`, fireplace-варианты, `media.fireplace_side_by_side`.
2. Устранить дублирование `reading.bay` / `bay_armchair`; формализовать `reading.window_anchor`.
3. Добавить строгий `reading.corner_vignette`: кресло + свет + поверхность.
4. Реализовать `window_seat` с двумя схемами — обычное окно и bay; радиатор без достаточных данных обрабатывать fail-closed.
5. Позже — `storage.corner_tower`.
6. `work`, одиночный statement-light, art focus и TV-over-fireplace оставить sleeping до появления сценария и данных.

Журнальные источники подтверждают сами композиции, но не ваши точные углы, сантиметры и проценты. Пределы вроде `≤45°`, `≤250 см`, `подоконник+10` и clearance должны оставаться отдельными правилами с собственной provenance в JSON, а не ссылаться на эти статьи.