В целом корни Н2–Н6 верны. Н1 как автоматическое снятие роли — небезопасен и противоречит собственной приёмке.

### 1. Корни и Н1

- Корень Н1 подтверждён: после неудачи на листе классификатор повторяет поиск по полному пути, поэтому родительские «Шкафы»/«Стеллажные системы» дают роль фурнитуре — [category_map.py:229](/home/pakar/igor/igor/remlab/tools/scout/category_map.py:229). `load3` доверяет карте без товарной проверки — [load3.py:223](/home/pakar/igor/remlab/tools/scout/load3.py:223).
- Пересчёт по локальным фидам 22.10 и текущему `category-roles.json`:
  - 96431: 40 ролевых категорий, 821 товар;
  - при `n ≥ 5` отпадут 29 категорий / 798 товаров;
  - 11 малых категорий / 23 товара останутся с ложной ролью. Поэтому критерий «96431: 0 товаров» недостижим — [план:69](/home/pakar/igor/remlab/.memory_bank/plans/catalog-holes-bank.md:69), [category-roles.json:1](/home/pakar/igor/remlab/tools/scout/category-roles.json:1).
- Кроме 96431 выпадут только уже названные:
  - divan.ru `112923:3745`, «Топперы для дивана» — 13;
  - divan.ru `112923:24`, «Модульные гостиные» — 24 настоящих предмета мебели — [report.md:26](/home/pakar/remlab-logs/catalog-holes/2252/report.md:26).
  Других магазинов в нулевой группе `n ≥ 5` не нашёл.
- Потеря реальна: `accepted = bool(role)`, поэтому снятая роль исключает оффер из загрузки — [load3.py:223](/home/pakar/igor/remlab/tools/scout/load3.py:223), [load3.py:370](/home/pakar/igor/remlab/tools/scout/load3.py:370); через три пропуска старая строка архивируется — [load3.py:527](/home/pakar/igor/remlab/tools/scout/load3.py:527). Сейчас «Модульные гостиные» семантически классифицированы правильно, хотя без габаритов не проходят напольный пул — [compose2.py:287](/home/pakar/igor/remlab/tools/scout/compose2.py:287).
- Ещё одна дыра плана: `category_map --build` не запускается ночью; `refresh_daily.sh` сразу вызывает `load3` — [refresh_daily.sh:232](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:232). Кэши датированы 11.10, фиды — 22.10. Без ночного `feed_taxonomy --build` + `category_map --build` статистика и дайджест не обновятся.

Рекомендация: «0 % размеров» использовать как `category_dimless/quarantine`, а не как источник онтологии. Роль сохранить; исключить такую категорию из `dim_prior`, мешей и автоподбора. Для `dim_prior --apply` достаточно требовать измеренные `w+h`: это сразу не даст фурнитуре получить глубину. Если всё же снимать роль — нужен отдельный режим для малых категорий и явное исключение для «Модульных гостиных».

### 2. Н2 и подвесы

Н2а должен исполняться в `load3.assign`, потому что `category_map.build` параметров товара не видит — [category_map.py:242](/home/pakar/igor/remlab/tools/scout/category_map.py:242), [load3.py:203](/home/pakar/igor/remlab/tools/scout/load3.py:203). Сравнение `Светильник настенный` должно быть точным: в фиде есть `Светильник настенно-потолочный`, который нельзя превратить в бра.

Н2б: корень верен, но ролевой минимум надо применять во всех шести местах проверки `MIN_CM`, а не только в финальном clamp — [dim_resolver.py:251](/home/pakar/igor/remlab/tools/scout/dim_resolver.py:251), [dim_resolver.py:303](/home/pakar/igor/remlab/tools/scout/dim_resolver.py:303), [dim_resolver.py:323](/home/pakar/igor/remlab/tools/scout/dim_resolver.py:323). При условии `≥ 1` мусорное значение ровно `1` не отсекается. Кроме того, сначала нужен Н2а: среди низких высот есть пульты, преобразователи и аксессуары, которым узкое правило Н2а пока не снимает роль.

По высоте подвеса прямой специальной нормы для люстры в жилой комнате нет; есть нормативные и дизайнерские ориентиры:

- СП 59.13330.2020 задаёт 2,1 м свободного пространства над путём движения — [СП 59.13330.2020](https://base.garant.ru/400382837/).
- ADA §307.4 требует минимум 2030 мм на путях движения — [US Access Board](https://www.access-board.gov/ada/chapter/ch03/).
- Светотехническое руководство рекомендует 7 футов ≈ 213 см над проходом и 30–36″ ≈ 76–91 см над поверхностью стола — [Lightology](https://www.lightology.com/index.php?module=how_to&sub=pendant_lighting).

Для продукта разумный hard-policy:

- проход: `clearance_cm = 210`; при потолке 270 см допустимый подвес лишь `≤ 60 см`, не 70–100;
- обеденный стол: низ светильника на 76–91 см выше столешницы;
- журнальный столик: нормативного минимума нет; дизайнерский ориентир тот же, но применять его можно только если светильник гарантированно целиком над столиком. Иначе считать зоной прохода.

В данных лучше отдельные `suspension_min_cm` / `suspension_max_cm` + `adjustable`, а не `h + flag`. Текущий парсер диапазона берёт только первое число — [dim_resolver.py:184](/home/pakar/igor/remlab/tools/scout/dim_resolver.py:184). Термин «вылет» лучше не использовать: он двусмысленен с горизонтальной проекцией.

Гейт ставить:

1. В `compose2` при выборе люстры — [compose2.py:908](/home/pakar/igor/remlab/tools/scout/compose2.py:908).
2. Повторно в солвере как hard-validation: `Room.ceiling_cm` уже есть — [models.py:58](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:58), но потолочный свет сейчас не доезжает до планировщика.
3. Не в нынешний `compose_gates`: `admit()` получает только SKU и картинку, без потолка, позиции и размеров — [compose_gates.py:42](/home/pakar/igor/remlab/tools/scout/compose_gates.py:42).

Пока банк не знает высоту потолка и зону светильника, безопасен только общий гейт 210 см для принятой базовой высоты комнаты.

### 3. Н4

Общее правило «круглая ваза, `w=d`» хуже: равные горизонтали описывают и цилиндр, высота которого не равна диаметру.

Оставить именно сферу, но:

- regex с границами: `\bшар\b|сферическ...`, иначе сработают «Шарм», «шары», названия коллекций;
- роль `ваза|кашпо`;
- `h is null`;
- есть `dia` либо `w≈d`;
- `h = max(dia,w,d)` с `source=shape_rule:sphere`.

Фраза «завышение ≤15 %» неверна: пример 18×15 даёт +20 % относительно настоящей высоты — [report.md:32](/home/pakar/remlab-logs/catalog-holes/2252/report.md:32).

Реализовывать лучше в `dim_resolver`, не в `dim_prior`: это детерминированный вывод из того же оффера. Иначе следующий `load3` затрёт `h_cm` и evidence — [load3.py:493](/home/pakar/igor/remlab/tools/scout/load3.py:493); `dim_prior` сейчас предназначен только для глубины — [dim_prior.py:173](/home/pakar/igor/remlab/tools/scout/dim_prior.py:173).

### 4. Н6 и потребители

Баг подтверждён: `d_cm` сохраняет `role_prior`, а metadata — только `mesh_ratio` — [load3.py:487](/home/pakar/igor/remlab/tools/scout/load3.py:487), [load3.py:496](/home/pakar/igor/remlab/tools/scout/load3.py:496).

Последствия исправления:

- `dim_prior.calibrate` наконец перестанет принимать эти 1272 глубины за измеренные — [dim_prior.py:112](/home/pakar/igor/remlab/tools/scout/dim_prior.py:112).
- `bank_ready` источник не анализирует, кроме отдельного `scrape|manual` для трансформеров; изменится только стабильность числовой глубины — [bank_ready.py:63](/home/pakar/igor/remlab/tools/scout/bank_ready.py:63), [bank_ready.py:127](/home/pakar/igor/remlab/tools/scout/bank_ready.py:127).
- `mesh_bind` читает только размеры: `mesh_required` перестанет мигать вместе с `d_cm` — [mesh_bind.py:91](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:91).
- Витрина показывает `dims_source`, но готовность считает по числам; она станет стабильной — [bootstrap.sql:93](/home/pakar/igor/remlab/tools/scout/bootstrap.sql:93).
- Дополнительный дефект: `mesh_dims --calibrate` обещает глубины «из фида», но не исключает `role_prior/mesh_ratio` — [mesh_dims.py:207](/home/pakar/igor/remlab/tools/scout/mesh_dims.py:207). Добавить фильтр по evidence.

### 5. Порядок и правки плана

1. Н6 выпускать атомарно с запретом `dim_prior` для категорий без измеренных `w+h` и очисткой/повторным применением приоров. Иначе Н6 просто закрепит плохую глубину фурнитуры.
2. Н2а, затем Н2б; расширить тесты на `настенно-потолочный`, пульты, аксессуары и значение ровно 1 см.
3. Н4 перенести из `dim_prior.py` в `dim_resolver.py`, ужесточить форму и поправить оценку ошибки.
4. Н1 не выпускать как снятие роли. Переписать на карантин пригодности; исправить несовместимые `n ≥ 5` и «96431 = 0»; добавить ночную пересборку карт и `WARN:` для дайджеста — контракт дайджеста уже есть в [refresh_daily.sh:38](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:38).
5. Н2в: сначала схема данных и разбор min/max, затем гейт `compose2`, затем проверка солвера. Добавить миграцию схемы и поля в `load3`/витрину/экспорт кандидата — сейчас этого нет в перечне файлов плана.
6. Замер до/после отдельно по ролям, архивированию, `dim_prior`, `mesh_required`, wait-клеткам; различать «снята причина wait_catalog у 51» и «ячейка стала чистой — только 12» — [report.md:11](/home/pakar/remlab-logs/catalog-holes/2252/report.md:11).
7. Н5 и Н3 оставить владельцу, как в плане.