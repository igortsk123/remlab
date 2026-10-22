Итог: п.1 и п.3 по существу верны; п.2 в предложенном виде небезопасен. До реализации селектора нужно поправить модель состояний шага 2.

### 1. Cutout и готовность банка

Да, для текущих покупательских путей вырезка мягкого не является условием показа:

- 3D-вариант экспортирует только роли из расстановки; мягких ролей в `PLACEABLE`/`SHOW_ROLES` нет: [tools/scout/flat215_demo.py:38](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:38), [tools/scout/flat215_demo.py:78](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:78).
- `/flat` берёт объёмные предметы только с `w,d,h,msid`, отдельно ковры и настольный декор; подушки, шторы и пледы туда не попадают: [lib/configurator/fromDemo.ts:191](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:191), [lib/configurator/fromDemo.ts:255](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:255).
- Ремонтный рендер явно не вклеивает мягкое: [tools/scout/draft_render.py:60](/home/pakar/igor/remlab/tools/scout/draft_render.py:60), [tools/scout/draft_render.py:3181](/home/pakar/igor/remlab/tools/scout/draft_render.py:3181).
- Смета/список покупок строятся из реально экспортированных `items` и `decor`, поэтому soft-роли из банка туда сейчас также не доезжают: [tools/scout/flat215-demo/index.html:2497](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2497).

Где cutout всё же нужен: внутренняя `/test/sets-preview/` показывает именно кэшированные вырезки всех товаров и пишет заглушку при их отсутствии: [tools/scout/sets_preview_page.py:2](/home/pakar/igor/remlab/tools/scout/sets_preview_page.py:2), [tools/scout/sets_preview_page.py:83](/home/pakar/igor/remlab/tools/scout/sets_preview_page.py:83). Старые `viz_paste/viz_final` также режут фото для диагностических коллажей, но это не покупательский `/demo` или `/flat`: [tools/scout/viz_paste.py:552](/home/pakar/igor/remlab/tools/scout/viz_paste.py:552).

Поэтому отдельный `bank_display_ready` правилен:

- `cutout` → товар доступен, актуальное живое исходное фото, текущая партнёрская ссылка; габариты и маска не требуются;
- глобальный `render_strategy.asset_ready` не менять.

Риска показать покупателю подушку/штору пустой карточкой сейчас нет — они вообще не экспортируются. Есть другой продуктовый долг: банк считает их частью комплекта, но покупатель не видит их ни в сцене, ни в списке покупки.

Нужна именно строгая проверка фото через `alive_now`, а не просто `image_url != null`: [tools/scout/img_alive.py:123](/home/pakar/igor/remlab/tools/scout/img_alive.py:123). Витрина при неудаче скачивания превращает фото в `null`: [tools/scout/flat215_demo.py:1206](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1206).

### 2. «Сиротский» rejected

Предложенный критерий «нет generations/revisions/jobs → меша никогда не было» ненадёжен. Он действительно вернёт часть решений владельца.

Tubo — прямой контрпример: отказ владельца зафиксирован в репозитории, хотя, по приведённому замеру, записей DEV нет: [tools/scout/rules/mesh-pinned.json:42](/home/pakar/igor/remlab/tools/scout/rules/mesh-pinned.json:42).

Кроме того, `rejected` объединяет разные смыслы:

- `redo` — меш отвергнут, но должен быть переделан;
- `replace_needed` — товар надо заменить;
- quarantine `reject` — настоящий ручной брак.

Это различие уже есть в коде: [lib/mesh-audit/rules.ts:45](/home/pakar/igor/remlab/lib/mesh-audit/rules.ts:45), [tools/scout/mesh_audit_sync.py:95](/home/pakar/igor/remlab/tools/scout/mesh_audit_sync.py:95). Решение адресовано конкретному поколению и хранится в `mesh_generations.owner_verdict`: [tools/scout/008-mesh-owner-audit.sql:11](/home/pakar/igor/remlab/tools/scout/008-mesh-owner-audit.sql:11).

Предлагаю:

- ввести единый append-only ledger/tombstone `mesh_asset_decisions`;
- для новых решений хранить `sku`, `generation_key`, `decision=redo|replace_needed|reject`, источник и дату;
- старые `rejected` без доказуемого происхождения классифицировать как `legacy_unknown`, не как `missing`;
- один раз вручную/по истории мигрировать 33 legacy-записи; Tubo занести как явный `replace_needed/reject`;
- `redo` → `wait_rework` и спрос специальной переделки;
- `replace_needed/reject` → блок SKU и пересборка ячейки;
- `legacy_unknown` → не продвигать, не тратить деньги, вынести в короткую разовую триаж-очередь.

Следовательно, Tubo сейчас не следует автоматически заказывать заново за ~1 ₽. Сначала надо перенести известное решение владельца в канонический ledger.

### 3. Минимальный гейт габаритов

Гейт нужен. Более того, отсутствие `h` влияет не только на генерацию меша: `/flat` просто отбрасывает такой предмет: [lib/configurator/fromDemo.ts:191](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:191).

Минимальный масштабируемый контракт без SKU-списков:

- для mesh-роли: `h > 0`, горизонталь `w` или `dia`, плюс `d` для некруглых/неквадратных ролей;
- для напольной роли: истинный footprint `(w,d)` либо `dia`: [tools/scout/footprint.py:42](/home/pakar/igor/remlab/tools/scout/footprint.py:42);
- это фактически уже контракт постановки `mesh_required`: [tools/scout/mesh_bind.py:91](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:91), [tools/scout/mesh_bind.py:101](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:101).

Для трансформируемой мебели по текущему фиду надёжно отличить собранный размер нельзя. У Ormatek `Ширина=80`, `Длина=200`, `Раскладная конструкция=Да`; отдельного размера собранного вида нет. Резолвер закономерно кладёт `Длина` в `d`: [tools/scout/dim_resolver.py:82](/home/pakar/igor/remlab/tools/scout/dim_resolver.py:82).

Поэтому правило должно быть таким:

- если роль `диван|кресло` и имя/params указывают на трансформер (`-кровать`, `Раскладная конструкция=Да`, механизм трансформации), размеры считаются `ambiguous_configuration`;
- продвижение разрешается только при отдельном доказанном `assembled_w/d/h` из карточки/скрейпа или нормализованного параметра;
- до этого — `wait_catalog` либо пересборка ячейки.

Это динамическое правило, не SKU-blacklist.

Поправка: проблема света 99272 с осью `Длина` в текущем `main` уже исправлена — для света она отдельно направляется в `d`: [tools/scout/dim_resolver.py:69](/home/pakar/igor/remlab/tools/scout/dim_resolver.py:69), [tools/scout/dim_resolver.py:73](/home/pakar/igor/remlab/tools/scout/dim_resolver.py:73).

### 4. Остальные блокеры

Самые существенные:

- `blacklist` вечный: старые записи копируются, но никогда не удаляются после исправления данных или успешного перегона: [tools/scout/bank_pending.py:119](/home/pakar/igor/remlab/tools/scout/bank_pending.py:119), [tools/scout/bank_pending.py:171](/home/pakar/igor/remlab/tools/scout/bank_pending.py:171).
- Ячейка с одним `invalid` полностью исключается из mesh-demand, даже если остальные её товары можно и нужно доделать: [tools/scout/bank_pending.py:139](/home/pakar/igor/remlab/tools/scout/bank_pending.py:139), [tools/scout/bank_pending.py:149](/home/pakar/igor/remlab/tools/scout/bank_pending.py:149).
- `mesh_required=false` считается окончательным браком, хотя это часто временная каталожная дыра — нет высоты, глубины или enrichment: [tools/scout/bank_pending.py:102](/home/pakar/igor/remlab/tools/scout/bank_pending.py:102).
- `asset_ready(sku, role)` фактически игнорирует переданную роль и берёт `cat_role` из БД: [tools/scout/render_strategy.py:95](/home/pakar/igor/remlab/tools/scout/render_strategy.py:95), [tools/scout/render_strategy.py:113](/home/pakar/igor/remlab/tools/scout/render_strategy.py:113).
- Flat-гейт сейчас требует только `w_cm`; для ковра этого недостаточно — нужны обе стороны и живое фото: [tools/scout/render_strategy.py:90](/home/pakar/igor/remlab/tools/scout/render_strategy.py:90).
- `candidate_hash` включает только пары `(роль, SKU)`, но не alternates, URL, размеры, цену, capsule/group: [tools/scout/bank_pending.py:67](/home/pakar/igor/remlab/tools/scout/bank_pending.py:67).
- `reserve=0` может навсегда оставить банк без места, если `demo_band` постоянно выбирает все 150: [tools/scout/rules/bank-candidate.json:5](/home/pakar/igor/remlab/tools/scout/rules/bank-candidate.json:5).
- Ночная пересборка кандидата ещё не подключена; сам policy это признаёт: [tools/scout/rules/bank-candidate.json:9](/home/pakar/igor/remlab/tools/scout/rules/bank-candidate.json:9).
- Строгая проверка всего hybrid на `gone=0` заблокирует любую частичную подмену: живой банк имеет 103 повреждённые ячейки, а лимит — 25% за ночь. Для нетронутых ячеек нужен режим «не ухудшилось + degraded/hidden», для продвигаемых — абсолютная чистота.

### 5. Что поменять в плане

- Перед шагом 3 добавить «шаг 2.1»: `bank_display_ready`, типы `wait_asset | wait_catalog | redo | blocked_policy | legacy_unknown`, очищаемый blacklist и полный `candidate_hash`.
- Добавить миграцию legacy `rejected` в явный ledger решений; Tubo не регенерировать до миграции.
- Cutout в готовности банка заменить на «живое актуальное фото + available + текущая партнёрская ссылка».
- Добавить candidate-only гейт геометрии: footprint + `h`; трансформеры без доказанных assembled-размеров — `wait_catalog`.
- Подключить реальный ночной `bank_prepare`: пересборка `sets3.next.json` должна происходить до pending; сейчас план шага 3 предполагает то, чего в `refresh_daily.sh` нет.
- Назначить ненулевой резерв `bank_candidate` либо fair-share, иначе очередь может голодать.
- В шаге 3 проверять продвигаемые ячейки строго, а нетронутые — относительно baseline с обязательным `degraded/hidden`; глобально строго оставить identity, порядок, повторы и связи.
- Сам шаг 3 пусть строит и экзаменует временный hybrid и manifest продвижения; запись `sets3.json` оставить только атомарному writer шага 4.
- Расширить тесты: soft без cutout; original photo dead; `redo` против `replace_needed`; legacy unknown; снятие blacklist после исправления; трансформер со sleeping-size; starvation при `reserve=0`; hybrid с прежними degraded-ячейками.