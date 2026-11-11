-- «Подтвердить планировку» (план trial-confirm-plan-01; T-20261111-16): правки комнат и проёмов агента — ЧЕРНОВИКОМ, без пересборки на каждую;
-- кнопка «Подтвердить планировку» (`POST /api/trial/<id>/confirm`) ставит ОДНУ пересборку `edit` на всё.
-- * `confirmed_at` — правка подтверждена (её значения в основных колонках идут в сборку: `lib/trial/repo-rebuild-worker.ts:editsOf`);
--   null — строка только черновик (агент добавил правку, ещё не подтвердил), в сборку не идёт.
-- * `draft` — НЕподтверждённое изменение уже подтверждённой строки ({name, kind, w_cm, d_cm, anchor, request_id} у комнаты;
--   {kind, c, width_cm, removed, request_id} у проёма). Основные колонки остаются подтверждёнными: сборка до кнопки берёт их.
--   Черновик есть = `confirmed_at is null or draft is not null` (`lib/trial/repo-draft.ts`).
-- * `rebuild_id` — пересборка, которая строит эту подтверждённую правку: публикация помечает `built` её строки
--   (и подтверждённые раньше её постановки — они были в claim), не все разом.
-- * `dims_ok` (только комнаты) — агент в окне подтверждения отметил «размеры верны»: сборка ставит комнате флаг `user_dims`
--   (`tools/floorplan/room_edits.py:apply`) — проверка размера снята, фото можно (`trial_bundle.photo_ok`).
-- * `trial_rebuilds.progress` — ход пересборки для страницы (`GET /api/trial/<id>/rebuild-status`): оценка времени от сервера
--   (`eta_s`, `room_eta_s`), состояния комнат и «N из M» от воркера (пульс аренды), замеры стадий (`timings`) после публикации.
-- Уже существующие строки правок сделаны старым путём (каждая сразу ставила пересборку) — они подтверждены: `confirmed_at = updated_at`.
-- Это заполнение — ОДИН раз, при добавлении колонки (файл применяется на КАЖДОМ деплое: повтор не должен подтвердить черновики).
-- Перед применением на проде — pg_dump. Откат (только руками, после pg_dump; черновики при этом становятся подтверждёнными правками —
-- сперва `delete from trial_room_edits where confirmed_at is null` и то же для проёмов, если их так не оставлять):
--   alter table trial_room_edits drop column if exists confirmed_at, drop column if exists rebuild_id, drop column if exists draft,
--     drop column if exists dims_ok;
--   alter table trial_opening_edits drop column if exists confirmed_at, drop column if exists rebuild_id, drop column if exists draft;
--   alter table trial_rebuilds drop column if exists progress;

do $$
begin
  if not exists (select 1 from information_schema.columns
                 where table_schema = current_schema() and table_name = 'trial_room_edits' and column_name = 'confirmed_at') then
    alter table trial_room_edits add column confirmed_at timestamptz;
    update trial_room_edits set confirmed_at = coalesce(updated_at, created_at);
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema = current_schema() and table_name = 'trial_opening_edits' and column_name = 'confirmed_at') then
    alter table trial_opening_edits add column confirmed_at timestamptz;
    update trial_opening_edits set confirmed_at = coalesce(updated_at, created_at);
  end if;
end
$$;

alter table trial_room_edits add column if not exists rebuild_id text;
alter table trial_room_edits add column if not exists draft jsonb;
alter table trial_room_edits add column if not exists dims_ok boolean not null default false;
alter table trial_opening_edits add column if not exists rebuild_id text;
alter table trial_opening_edits add column if not exists draft jsonb;
alter table trial_rebuilds add column if not exists progress jsonb;

-- повтор черновика по `request_id` (он у черновика подтверждённой строки — внутри `draft`)
create index if not exists trial_room_edits_request on trial_room_edits (job_id, request_id);
