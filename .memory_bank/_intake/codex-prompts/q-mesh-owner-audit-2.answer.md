## Вывод

План существенно лучше, но остаются три блокера:

1. нет явного указателя на текущий физический меш;
2. ручной и автоматический reseed всё ещё могут заказать один seed;
3. DB-less selftest не проверит главные транзакционные гарантии.

## А. Идентичность, отказ и отвязка

1. **Блокер: `mesh_generations` недостаточно — нужен `current_generation_key`.**

   `asset_revisions` остаётся логической ревизией `sku|source_sha|pipeline`, а физические попытки будут отдельными. Добавьте:

   - `asset_revisions.current_generation_key → mesh_generations`;
   - `products.mesh_generation_key → mesh_generations`.

   Иначе нельзя атомарно доказать, какой именно меш сейчас привязан, и безопасно выполнить CAS-отвязку.

2. **Повторный ingest пока остаётся недетерминированным.**

   Сейчас файлы обходятся лексикографически, и все попытки одного товара пишутся в одну строку: [ingest_registry.py](/home/pakar/igor/remlab/tools/scout/salad/ingest_registry.py:28), [ingest_registry.py](/home/pakar/igor/remlab/tools/scout/salad/ingest_registry.py:41). Старый каталог, обработанный после нового, способен снова стать текущим.

   Нужное правило: `current_generation_key` меняется только по монотонному `generated_at`, с детерминированным tie-break по `generation_key`. Порядок обхода диска не должен влиять на итог.

3. **`bind_ready()` обновляет не только при смене URI.**

   Условие сейчас — изменился URI **или `mesh_at`**: [mesh_bind.py](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:115). Настоящая проблема другая: отсутствие строки в `_bind` ничего не отвязывает.

   Отказ владельца должен одной DEV-транзакцией:

   - записать ledger по `prod_decision_id`;
   - поставить `owner_verdict` конкретному generation;
   - изменить логическую ревизию только при `current_generation_key = rejected_key`;
   - очистить `products.mesh_uri/mesh_at/mesh_generation_key`;
   - поставить `mesh_status='rejected'`;
   - создать запрос переделки.

4. **Нельзя выбирать “свежайший неотвергнутый”.**

   Это воскресит старый seed, от которого система уже отказалась. Выбирать нужно только текущую generation. Если она отвергнута — товар без меша до появления и прохождения следующей generation.

5. **Разделите два вердикта.**

   В `mesh_generations` нужны как минимум:

   - `machine_verdict`;
   - `owner_verdict`;
   - `owner_decision_id`;
   - `generated_at`.

   Один общий `verdict` смешает автоматический брак с решением владельца. Сейчас автоматическая приёмка живёт в `verdict.json`: [apply_repairs.py](/home/pakar/igor/remlab/tools/scout/salad/apply_repairs.py:202).

6. **Ориентация всё ещё может принадлежать другому физическому мешу.**

   `mesh_ready` связывает ориентацию с ревизией фактически по SKU: [mesh_ready.py](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:45). Новый перегон способен унаследовать готовность старого. Уже существует более честная сверка по `glb_sha` в [mesh_dims.py](/home/pakar/igor/remlab/tools/scout/mesh_dims.py:58); её следует сделать общим контрактом готовности. Это нельзя оставлять «вне скоупа».

7. **Legacy-потребители не увидят DB-отказ.**

   `topview_render` и старая галерея смотрят только на файловый `owner_reject.json`: [topview_render.py](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:252), [gallery_build.py](/home/pakar/igor/remlab/tools/scout/salad/gallery_build.py:189). Либо перевести их на `mesh_generations`, либо атомарно писать sidecar конкретной generation.

8. **Конфликт ручного и автоматического reseed реален.**

   `apply_repairs` всегда создаёт `seed+1` для seed 0 и дедуплицирует только по `(sku, seed)`: [apply_repairs.py](/home/pakar/igor/remlab/tools/scout/salad/apply_repairs.py:172). Ручной запрос может независимо заказать тот же seed 1 и получить cached старую попытку.

   `next_seed` надо резервировать транзакционно как следующий свободный среди:

   - `mesh_generations`;
   - pending/running rework;
   - `mesh-reseed.json`;
   - активного снимка очереди.

   Лучше устранить файловый источник и включить `seed` в job identity сейчас. Отложенный долг `mesh_jobs.job_key без seed` напрямую противоречит этому плану и [регламенту](/home/pakar/igor/remlab/tools/scout/rules/mesh-priority.json:70).

## Б. Очередь

Формулировка «принято, ждёт сборки очереди» честная и безопасная. Раньше материализовать нужно только durable request в БД; менять живой JSON не надо.

Но процедура старта волны должна быть строже:

1. запросить остановку `batch_show` на границе пачки;
2. дождаться отсутствия `batch_show/ssh_run` и завершения post-processing;
3. выполнить pull решений;
4. транзакционно зарезервировать seed и `queue_build_id`;
5. собрать новый снимок во временный файл;
6. проверить уникальность полного `job_key`, лимит и policy version;
7. `fsync + atomic rename`;
8. связать прогресс с `queue_build_id`, а не с общим файлом;
9. только затем запустить новый процесс с явным `MESH_SAMPLE`.

Сейчас файл пишется непосредственно, не атомарно: [mesh_priority.py](/home/pakar/igor/remlab/tools/scout/mesh_priority.py:188). `batch_show` считает `total` один раз и хранит общий позиционный курсор: [batch_show.py](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:636). Простое «перезаписать файл и сбросить done=0» может повторно генерировать ещё не привязанные результаты.

Минимально приемлемо: immutable snapshot + отдельный progress по `queue_build_id`. Правильный итоговый вариант — завершённость по полному `job_key`, как уже требует регламент.

## В. Что ещё поправить

- Лимит «2 на товар» в плане превращён в «2 на `sku+source_sha+pipeline`». Это позволяет ещё две попытки после каждой смены фото/версии. Такое обнуление отдельно подтвердить у владельца; буквальная формулировка требует lifetime-счётчика по SKU.
- Для двойного клика одной транзакции мало: нужен `SELECT … FOR UPDATE` либо уникальность `(scope, manual_attempt_no)`. Иначе две вкладки одновременно обе увидят счётчик 1.
- `mesh_audit_page_views` лишняя при наличии `seen_at` на item, если отдельная аналитика страниц не нужна.
- Постеры следует строить для публикуемой партии, не сразу для всех 1291.
- Минутный sync и 12-минутную публикацию партии нельзя держать под одним flock: решения будут задерживаться. Нужны отдельные лёгкий sync-lock и publisher-lock.
- В плане расходятся пути: Caddy сейчас монтирует `/opt/remlab/test → /srv/test` и обслуживает `/test/*`: [docker-compose.yml](/home/pakar/igor/remlab/docker-compose.yml:15), [Caddyfile](/home/pakar/igor/remlab/caddy/Caddyfile:29). `/srv/mesh-audit` сам по себе не смонтирован. Нужен специальный `handle_path /test/mesh-audit/*` над общим `/test/*`.
- Удаление предыдущей партии сразу после switch сломает старую открытую вкладку, если GLB ещё не был лениво загружен. Нужны явный `410/reload` либо короткий grace; это не потеря данных, но UX должен быть определён.

## Минимальные тесты

Обязательные, причём первые шесть — на временной PostgreSQL, не только `--selftest`:

1. ingest старой/новой generation в обоих порядках даёт одинаковую current;
2. CAS-отказ старой вкладки не отвязывает новую generation;
3. reject очищает product binding, а повторные `ingest → bind → enforce` не воскрешают его;
4. новая generation не становится ready с ориентацией старого `glb_sha`;
5. автоматический и ручной запросы одновременно получают разные seeds;
6. два параллельных клика не превышают лимит;
7. crash до/после rename снимка восстанавливается по `queue_build_id`;
8. request становится `queued` только после успешной фиксации снимка;
9. повторный pull идемпотентен;
10. переключение партии не удаляет staging, DEV-источники или новую активную партию.

Итог: П2–П5 можно развивать, но до UI я бы закрыл `current_generation_key`, точную привязку ориентации и единый allocator seed. Именно там ещё возможна тихая порча решения владельца. Файлы не менял.