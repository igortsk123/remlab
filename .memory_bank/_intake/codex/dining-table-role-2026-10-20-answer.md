Вердикт: А+Б — верное направление, но в текущем виде применять не стоит. Нужны исключения для цвета/трансформеров, верхняя граница для барных столов и протяжка фильтра в банк/демо.

1. Регэкспы и данные

- На локальном снимке фидов read-only разбор через [load3.py:250](/home/pakar/igor/remlab/tools/scout/load3.py:250) дал 226 товаров с ролью `стол обеденный`:

  - Б отсекает Glasar 81×81×40 и рабочий City Furniture 100×50×76;
  - В дополнительно отсекает Shengfang 100×35×75 и `Нолан` 35×35×75;
  - Caterina Provence «кофейный» не задевается: между `стол` и `кофейный` есть другие слова;
  - `Стол барный Парсон 60×60×103` предложение пропускает;
  - настоящий `Стол-трансформер … 133×133×75`, у которого `Тип товара=Стол обеденный`, уже сейчас теряется: `^стол\s` не принимает дефис в `Стол-трансформер` — [category_map.py:76](/home/pakar/igor/remlab/tools/scout/category_map.py:76).

- Ложных отсечений настоящего обеденного стола текущими А/Б на этом снимке не нашёл. Но конструкция опасна:

  - `стол\w*` совпадает со `столешница`, а без левой границы — и с окончанием другого слова;
  - `кофейн\w*` совпадает с `кофейня`;
  - короткое название `Обеденный стол кофейный` А ошибочно превратит в столик, потому что правило столика идёт раньше обеденного, а первое совпадение побеждает — [category_map.py:72](/home/pakar/igor/remlab/tools/scout/category_map.py:72), [category_map.py:183](/home/pakar/igor/remlab/tools/scout/category_map.py:183);
  - `журнальн` ошибочно заберёт `стол-трансформер журнальный-обеденный`;
  - голые `рабоч|консол` могут зацепить описание свойства/коллекции, а не назначение.

- Рекомендация: явное `обеденн` и dual-use трансформеры разбирать до кофейного/журнального; отрицательные типы искать как соседние слова вокруг `стол`, с `\b` и разделителем `[\s-]+`. Добавить `барн`. Детские уже закрыты категорией, именем и `role_by_name` — [category_map.py:33](/home/pakar/igor/remlab/tools/scout/category_map.py:33), [category_map.py:112](/home/pakar/igor/remlab/tools/scout/category_map.py:112), [category_map.py:163](/home/pakar/igor/remlab/tools/scout/category_map.py:163).

2. Размеры

- ГОСТ 13025.3-85 задаёт для бытового обеденного стола высоту 720–780 мм и посадочное место 600×325 мм; для кухонного допускает 500×300 мм. Поэтому `h < 65` — не нормативная граница, а хороший консервативный анти-мусорный порог: он оставляет запас 7 см до нормы и ловит Glasar. Источник: [ГОСТ 13025.3-85](https://files.stroyinf.ru/Data2/1/4294838/4294838127.pdf), [карточка изменения Росстандарта](https://protect.gost.ru/gost/changesdetails/9b23e138-6e74-4bd7-b19f-a9536b8b6bf1).

- Нужен и верхний предохранитель: для вашей онтологии барный стол 100+ см — не `стол обеденный`, тем более барные стулья уже запрещены — [unfit.py:17](/home/pakar/igor/remlab/tools/scout/unfit.py:17). Я бы поставил `h > 90 → unfit` либо как минимум обязательное `\bбарн\w*\b`.

- `d < 50` стандартом прямо не обосновано: 300/325 мм — глубина одного посадочного места, не минимальная полная глубина столешницы. Как консервативный фильтр консоли — нормально; `<50`, не `≤50`, плюс `d_eff = d or dia`. Узкие пристенные столы и складные модели иначе будут ложноположительными.

- Трансформер с высотой сложенного журнального состояния нельзя автоматически принимать или отвергать. Нужны габариты именно обеденной конфигурации; если их нет — quarantine/manual или отсутствие из автоматического 3D-подбора. Иначе солвер расставит одну геометрию, а меш покажет другую.

- «Высоты нет → только понизить» сейчас технически не реализуется: `unfit()` возвращает только bool — [unfit.py:19](/home/pakar/igor/remlab/tools/scout/unfit.py:19). В демо-пул товары без `h` вообще не входят — [demo_swap_pool.py:75](/home/pakar/igor/remlab/tools/scout/demo_swap_pool.py:75).

3. Цепочка и возможные поломки

- Новый `d` безопаснее добавить последним или keyword-only: текущий пятый позиционный аргумент — `dia` — [compose2.py:276](/home/pakar/igor/remlab/tools/scout/compose2.py:276). Все вызовы демо сейчас передают только `h`; им нужно передать `d=` явно — [flat215_demo.py:501](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:501), [flat215_demo.py:640](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:640), [flat215_demo.py:662](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:662).

- А сама по себе не очистит `sets3`: лечение считает товар умершим только при `cat_role is null`, но не при смене `стол обеденный → столик` — [sets_incremental.py:567](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:567). Б надо включить в `_slot_ok`, тогда `--enforce-contracts` заменит уже накопленный мусор — [sets_incremental.py:168](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:168), [sets_incremental.py:871](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:871).

- Экзамен читает замороженный снимок `sets3`, а не свежие роли БД — [acceptance_run.py:48](/home/pakar/igor/remlab/tools/scout/acceptance_run.py:48), [solver_run.py:13](/home/pakar/igor/remlab/tools/scout/solver_run.py:13). Солвер доверяет ключу роли: строит столовую и приставляет стулья независимо от названия/высоты — [template.py:1012](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1012), [validate.py:748](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:748). Текущий дефект уже виден в артефакте как dining SKU — [v3set1-layout.json:1287](/home/pakar/igor/remlab/tools/scout/v3set1-layout.json:1287).

- Сторож `role_canon` фактически тавтологичен: `lr_roles.role` — это alias того же `p.cat_role`, после чего они сравниваются — [bootstrap.sql:59](/home/pakar/igor/remlab/tools/scout/bootstrap.sql:59), [tests_chain.py:126](/home/pakar/igor/remlab/tools/scout/tests_chain.py:126). Нужны отдельные live-инварианты: запрещённые dining-названия/размеры = 0; роль SKU банка совпадает с текущей `cat_role`; опубликованные варианты проходят `unfit`.

- Отдельный артефакт уже называет Shengfang обеденным столом и не исправится автоматически от `category_map` — [furniture.json:555](/home/pakar/igor/remlab/data/flat3d/furniture.json:555).

Итого: принимать после добавления приоритета явного `обеденный`, политики dual-use, `барн`/верхней высоты, `d` во все вызовы и очистки существующего банка через `_slot_ok`. Файлы не изменял.