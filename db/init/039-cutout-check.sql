-- Страница проверки вырезок /lab/cutout-check (T-20261119-104, владелец TG 2098/2102): по каждому товару /demo — фото магазина и вырезка, кнопка «не ок»
-- и комментарий «что не так». Одна кнопка «не ок»: без отметки карточка считается «ок»; «просмотрено» — карточка побыла на экране ≥ 1 с (viewed_at).
-- Отметки доходят до конвейера выгрузкой списком (`tools/scout/cutout_check_sync.py --export`).
-- Только добавления: существующие таблицы не меняются. Идемпотентно (прод применяет все init-файлы на каждом деплое): if not exists + именованные ограничения.
-- Перед первым применением на проде — pg_dump (директор, 19.11: «новые таблицы в пилоте без вопросов, pg_dump перед применением»).
-- Откат (только руками, после pg_dump):  drop table if exists cutout_check_marks; drop table if exists cutout_check_items;

-- Карточки: одна на (прогон, товар). generation_key — отпечаток ВЫРЕЗКИ (sha файла): перегнали цепочку и положили новую вырезку — ключ другой,
-- отметка и текст сбрасываются (старые нажатия остаются в журнале), чтобы «не ок» не относилось к картинке, которую владелец не видел.
create table if not exists cutout_check_items (
  id             serial      primary key,
  run            text        not null,               -- метка прогона вырезки (папка ~/remlab-logs/t104-1119/<метка>)
  sku            text        not null,
  position       integer     not null default 0,     -- порядок на странице (роль, имя) — задаёт DEV
  role           text,
  name           text,
  name_en        text,
  shop           text,
  shop_url       text,
  photo_url      text,                               -- фото магазина, как лежит на сервере (/test/cutout-check/…)
  cut_url        text,                               -- вырезка с прозрачностью (webp)
  generation_key text        not null,
  info           jsonb,                              -- вердикт цепочки, размеры, предупреждения — для подписи и разбора
  mark           text,                               -- null (= ок) | bad; 'ok' допустим — старый вид «вернуть в ок» теперь снимает отметку
  mark_at        timestamptz,
  mark_by        text,
  viewed_at      timestamptz,                        -- карточка побыла на экране ≥ 1 с (без нажатий); новая вырезка сбрасывает
  viewed_by      text,
  note           text,                               -- последняя принятая версия «что не так»
  note_seq       bigint,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint cutout_check_items_run_sku_uq unique (run, sku),
  constraint cutout_check_items_mark_chk check (mark in ('ok', 'bad'))
);
create index if not exists cutout_check_items_run_pos_idx on cutout_check_items (run, position);

-- Журнал: каждое нажатие и каждая версия текста — строка навсегда (append-only). op_id — повтор запроса (сеть, двойной тап, маяк закрытия вкладки)
-- даёт одну строку. Не применённое (карточка уже заменена, другая вкладка успела раньше, версия текста старее принятой) — тоже строка, applied=false.
create table if not exists cutout_check_marks (
  id             bigserial   primary key,
  item_id        integer     not null,
  run            text        not null,
  sku            text        not null,
  generation_key text        not null,
  kind           text        not null,               -- mark | note | view
  mark           text,                               -- для kind=mark: ok | bad | clear
  body           text,                               -- для kind=note: текст как набран (пустой — стёрт)
  client_seq     bigint,                             -- для kind=note: номер версии из браузера
  expected       text,                               -- для kind=mark: какую отметку видела вкладка (ok | bad | null)
  applied        boolean     not null default true,
  reason         text,                               -- stale | state_conflict | older
  reviewer       text        not null,
  editor_id      text,
  op_id          text        not null,
  created_at     timestamptz not null default now(),
  constraint cutout_check_marks_op_uq unique (op_id),
  constraint cutout_check_marks_kind_chk check (kind in ('mark', 'note', 'view')),
  constraint cutout_check_marks_mark_chk check (mark is null or mark in ('ok', 'bad', 'clear')),
  constraint cutout_check_marks_body_len check (body is null or char_length(body) <= 2000),
  constraint cutout_check_marks_reviewer_len check (char_length(reviewer) between 1 and 40)
);
create index if not exists cutout_check_marks_item_idx on cutout_check_marks (item_id, id);
