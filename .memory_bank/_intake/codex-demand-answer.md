Вывод: расширить `mesh_demand` до 12 092 — правильно. Но класть туда `glb_path/glb_url/mesh_status` неправильно: спрос, задания, исторические ревизии и выбранный рабочий меш — разные сущности. И сейчас есть два P0-дефекта: `revision_key` схлопывает разные seed, а новые приоритеты не читаются scheduler’ом.

## 1. Где хранить ссылку на меш

Рекомендую отдельную жёсткую привязку:

```sql
product_mesh_binding (
  sku text primary key,
  revision_key text not null,
  bound_at timestamptz not null,
  bound_by text not null,
  foreign key (sku, revision_key)
    references asset_revisions(sku, revision_key)
)
```

В `asset_revisions` добавить нормальные поля:

```sql
source_sha
pipeline_version
generation_variant   -- seed/config hash
asset_uri             -- стабильный object key, не signed URL
glb_sha
```

Почему не `mesh_demand`:

- demand может стать `not_required`, но готовый ассет и история должны сохраниться;
- фото сменилось — demand получает новый `source_sha`, старая ревизия остаётся;
- возможны одновременно rejected, accepted и generating ревизии;
- локальный `glb_path` зависит от машины, signed `glb_url` протухает. Нужен стабильный `object_key/asset_uri`.

Для чтения сделать view `current_mesh_state`, объединяющее demand, job, binding, revision и orientation. Именно view отдаёт `ready/generating/rejected/stale`.

### P0: текущая идентичность уже неоднозначна

[ingest_registry.py:41](/home/pakar/igor/remlab/tools/scout/salad/ingest_registry.py:41) строит:

```python
revision_key = sku|source_sha|v1
```

Seed/job id туда не входит, а upsert перезаписывает строку — [ingest_registry.py:43](/home/pakar/igor/remlab/tools/scout/salad/ingest_registry.py:43). При трёх seed в БД остаётся «последняя записанная ревизия», а не три ревизии. До введения binding ключ надо сделать неизменяемым и уникальным, например:

`sku|source_sha|pipeline|generation_variant|glb_sha`

Иначе «жёсткая ссылка» лишь жёстко закрепит случайный последний seed.

## 2. Как расширять, не ломая текущий прогон

Не перезаписывать активный [mesh-pilot-sample.json](/home/pakar/igor/remlab/tools/scout/mesh-pilot-sample.json). `batch_show` фиксирует `total`, но каждый новый `ssh_run` заново читает файл; изменение порядка сделает текущий `--skip=245` ссылкой на другие товары.

Безопасный порядок:

1. Текущий файл заморозить до окончания прогона: сохранить SHA и `batch_id=pilot-20260901`.
2. Вставить 12 092 строк только в `mesh_demand`; это не влияет на файловый прогон.
3. Не создавать 12 092 `mesh_jobs`: demand — потребность, job — только выбранная дневная партия. Этот контракт уже заявлен в [mesh_scheduler.py:19](/home/pakar/igor/remlab/tools/scout/mesh_scheduler.py:19).
4. Следующий экспорт писать в новый immutable-файл `mesh-batch-<batch_id>.json`.
5. В дальнейшем `batch_show/ssh_run` должны принимать `--batch-id` или точный путь, а не глобальный `SAMPLE`.
6. Первые 78 flat215 закрепить как `batch_item.ordinal`, а не надеяться на приоритет.

Нужна таблица вроде:

```sql
mesh_batch_items (
  batch_id text,
  ordinal int,
  job_key text,
  primary key (batch_id, ordinal)
)
```

### Приоритет 4 сейчас не сработает как задумано

- Весь `demand_from_cut_pool()` сейчас получает priority 2 — [mesh_queue.py:238](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:238).
- Он добавляется раньше candidates/reserve через `setdefault` — [mesh_queue.py:351](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:351). Поэтому нижние источники уже не могут уточнить класс.
- Scheduler вообще не читает `mesh_demand.priority`: `_queue()` возвращает только SKU и роль — [mesh_scheduler.py:44](/home/pakar/igor/remlab/tools/scout/mesh_scheduler.py:44), а хвост сортируется по SKU — [mesh_scheduler.py:104](/home/pakar/igor/remlab/tools/scout/mesh_scheduler.py:104).

Нужно собрать все источники в staging и взять `min(priority)` по текущему снимку:

1. стоит в сете;
2. top-K/дефицит замен;
3. управляемый резерв;
4. остальной eligible-каталог.

Затем scheduler обязан учитывать этот класс. Иначе priority 4 будет декоративной колонкой.

## 3. Статусы

Один ряд `wanted/queued/generating/ready/rejected` недостаточен. У SKU одновременно могут быть demand, running job, rejected revision и старая accepted revision.

Разделить:

- `mesh_demand.status`: `wanted | paused | not_required | superseded`;
- `mesh_jobs.status`: `queued | running | retry_wait | completed | failed_terminal | cancelled`;
- `asset_revisions.status`: `generated | acceptance_pending | accepted | rejected | superseded`;
- binding: либо строка есть, либо нет;
- readiness — производное view:
  `awaiting_photo | wanted | queued | generating | acceptance_pending | rejected_only | ready | stale`.

«Меш существует, но брак» — это `asset_revisions.status='rejected'` плюс `rejection_code/reason/rejected_at`. Demand при этом остаётся `wanted`: товар всё ещё нуждается в хорошем меше.

Binding создавать одной транзакцией только после:

- revision accepted;
- `source_sha` совпадает с текущим фото;
- ориентация решена, если это условие рабочего ассета.

Текущий `mesh_ready` уже правильно сверяет accepted revision и orientation одной ревизии — [mesh_ready.py:37](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:37), но парсит `source_sha` через `split_part(revision_key, ...)`. Лучше хранить его отдельной колонкой.

## 4. Политика ролей

`MESH_EXCLUDE` надо удалить как второй канон. Quality ≥0.65 оставляется отдельно: это гейт качества каталога, а не стратегия ассета.

Сейчас три истины противоречат друг другу:

- [asset-strategies.json](/home/pakar/igor/remlab/tools/scout/rules/asset-strategies.json) по default считает люстры, бра и вазы `hunyuan3d`;
- [render_strategy.py:27](/home/pakar/igor/remlab/tools/scout/render_strategy.py:27) считает их `cutout`;
- [mesh_queue.py:40](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:40) имеет собственный `MESH_EXCLUDE`;
- scheduler требует `render_strategy.strategy(role) == 'mesh'` — [mesh_scheduler.py:39](/home/pakar/igor/remlab/tools/scout/mesh_scheduler.py:39). Поэтому свет и вазы он сейчас никогда не выберет.

Единственный канон — `asset_strategy.strategy(role)`. `render_strategy` должен лишь отображать:

- `hunyuan3d → mesh`;
- `procedural_plane → flat`;
- `cutout/parametric_soft → cutout`.

Решение владельца лучше записать явно в JSON (`люстра`, `бра`, `ваза`: `hunyuan3d`), поднять `policy_version` и добавить CI-тест всех известных ролей. Полагаться на `_default=hunyuan3d` для платного прогона опасно: опечатка роли автоматически становится GPU-заданием.

## 5. Миграция

Схема мешей сейчас встроена строкой в [mesh_queue.py:55](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:55), а в `db/init` её нет. Нужен идемпотентный `008-mesh-assets.sql`.

Порядок:

1. Снимок четырёх таблиц и SHA активного batch-файла.
2. Добавить nullable-колонки, `product_mesh_binding`, индексы и view.
3. Разобрать коллизии старых revision keys по манифестам; ничего не связывать автоматически при неоднозначности.
4. Backfill `asset_uri/source_sha/pipeline/generation_variant`.
5. Binding заполнить только для единственной текущей accepted+oriented ревизии. Неоднозначные оставить без binding и вывести отчётом.
6. Полный eligible-пул загрузить через staging + `COPY`, затем одним `INSERT … ON CONFLICT`.
7. Старые 2500 строк не удалять: приоритет пересчитать по текущему снимку; выпавшие пометить `not_required`; `first_seen` сохранить.
8. Создать jobs только scheduler’ом по лимиту.

Не делать 12 092 отдельных вызова `db()`: текущий цикл upsert вызывает новый `docker exec psql` для каждой строки — [mesh_queue.py:370](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:370). Это медленно и допускает наполовину применённое состояние. Нужны staging, одна транзакция и гейт ожидаемого размера, например отказ применения при неожиданном падении полного пула более чем на 10–15%.

Главный риск ночи: любое изменение активного `mesh-pilot-sample.json`, его порядка или политики, зашитой в уже работающие контейнеры. Схему БД и новые demand-строки можно накатывать сейчас; переключение экспортера и batch source — только с новой волны.