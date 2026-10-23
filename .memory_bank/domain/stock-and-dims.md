---
tier: 2
topic: stock-and-dims-details
scope: Контроль наличия и честность размеров — модель, состояния, парсер, правило footprint
tier1: ../core/stock-and-dims.md
updated: 2026-10-23
last_verified: 2026-10-18
importance: high
source: manual
---

# Наличие и размеры честно — детали (план `stock-and-dims-honesty`, 03.09.2026)

Сводка — [[catalog]]. Аудит и план — `completed_plans/stock-and-dims-honesty.md`, критика Codex —
`_intake/codex/codex-stock-honesty-answer.md`.

## Контроль наличия (`tools/scout/stock_check.py`, `page_alive.py`, `stock_truth.py`)
`stock_check.py` ходит на карточки с якорем домена
(главная + 3 живых карточки), карантин магазина окончателен (`disposition=quarantined`), негатив действует только
по текущей ссылке (`products.direct_url_hash`), гейт по решающим ответам; антибот только у mdm
(`probe_domain_status.policy=disabled`, проба раз в неделю). Модель в `products`: `availability_state`
(in_stock|out_of_stock|unknown), `page_state` (alive|gone|unknown), `availability_basis` (page|feed|none),
`stock_evidence_at`; пишет только `stock_truth.reconcile()`; демо помечает «наличие не проверено» (замер 11.10: основание `page` — 20 002, `feed` — 1 389). Парсер v2
(snake_case, `href=`, JSON-LD Product, inline-остаток tvoydom) включён по умолчанию с 03.09 после gold-замера в тени
(`page_alive.py:PARSER_V2`, откат — `STOCK_PARSER_V2=0`); тень — `stock_check.py --shadow`, отчёт — `stock_shadow_report.py`. Со страницы берём цену/имя/canonical только как наблюдения (`product_page_facts`).

## Размеры (`tools/scout/footprint.py`, `dim_resolver.py`)
 `footprint.py` — одно правило «Ш×Г или диаметр известны» для compose2, лечения, солвера,
сцены, экспорта и демо; выдуманных дефолтов нет (диван 100, типовые, «квадратное основание», меш без калибровки — убраны).
Недостающую глубину с 11.10 выводит `tools/scout/dim_prior.py` по роли и форме (`dims_evidence.d.source='role_prior'`,
только где `d_cm` пуста); из меша (`mesh_dims.py`) — только при пройденной калибровке; load3 выведенную глубину не
затирает, пока фид не даст свою (`footprint_known` источник не различает).
Оси по магазинам — `dim_resolver.py:SHOP_DIM_KEYS`: tvoydom (99272), мебель — «Длина» = фасад, «Ширина» = глубина
(замер 1 100 карточек); свет tvoydom — глубина из «Глубина», иначе из «Длина»; Орматек (93965) — наоборот, «Длина» =
глубина. Тройка «Ш×Г×В» в названии — авторитет.
Банк №3 (03.09): 126 сетов, 2 479 позиций, 0 напольных без размера. **Отрицательно:** глубина из меша по одному
фото (Риббл w:d 1,87:1,99 vs фид 1,62) — не включать; `available` API — precision 0 % (замер 03.09, история).

## Дыры каталога — выведенные размеры и гейты (план `catalog-holes-bank`, 23.10; ADR-0309…0311)
Слово владельца 23.10: «партнёр ничего сам не добавит; если указан только размер спального места и это характерный паттерн
производителя — достраивай размеры сам примерно; главное — чтобы влезло» (допуск расстановки +10/−20 %). Правило — по паттерну
магазина или формы, без списков SKU; ошибка — в сторону «больше». Каждый вывод — свой `source` в `dims_evidence.<ось>`.
- **Карантин категорий без размеров** (`tools/scout/dimless.py:decide`, `exclude_sql`): n ≥ `MIN_N` (5) и 0 товаров с измеренными Ш и В
  (вывод `role_prior|mesh_ratio|shape_rule` не считается измерением); малые — по ближайшему предку пути с n ≥ 5, иначе по доле
  магазина ≥ `SHOP_SHARE` (0,9). Роль НЕ снимается (роль = допуск в загрузку, `load3.assign`) — иначе ушли бы «Модульные гостиные»
  divan.ru; вне — приор (`dim_prior.py`), спрос мешей (`mesh_bind.py`), пул (`compose2.py`). Замер 23.10: 42 категории / 850 товаров.
- **Провенанс приора** (`dim_prior.py`, `load3.py` upsert): `role_prior` хранит `role, shape, p10, median, p75, p90, n`; повторная загрузка
  выведенную глубину с провенансом не стирает; «d есть, evidence.d нет» — потерянный вывод, `dim_prior --apply` его снимает;
  калибровка учится только на измеренном.
- **Свет по «Тип»** (`tools/scout/category_map.py:light_role`): принадлежность (`LIGHT_ACCESSORY`) и точечный/трековый/подсветка
  (`LIGHT_NOT_LIVING`) — без роли; «Светильник настенный» в «люстрах» → бра. Нижний порог высоты 1 см у люстры и бра
  (`dim_resolver.py:ROLE_MIN_H_CM`; лампа и торшер ниже 5 см — мусор); 0,1 см — мусор и у света.
- **Шар** (`dim_resolver.py:sphere_height`, `SPHERE_RX`): ваза/кашпо «шар»/«сферическ» без высоты — высота = диаметр или Ш при Ш≈Г
  (±10 %); источник `shape_rule:sphere`.
- **Трансформеры Орматека** (`dim_resolver.py:transformer_dims`, `SLEEP_IN_FEED`, `TRANSFORMER_COEF`): у дивана/кресла с механизмом,
  «Раскладной конструкцией» или «кровать» в названии хвост «A×B» — спальное место (короче 170 — габарит, правило молчит). Тип:
  кресло / угловой / прямой; место «вперёд» (аккордеон, выкатной, каскад, отелло, седафлекс…) или «вдоль» (остальные; неизвестный —
  «вдоль», фронт больше). Ш = место + прибавка, Г и В — таблица (квантиль 0,75 по 956 трансформерам divan.ru, пересчёт и сверка —
  `transformer_calib.py`); «Ширина» фида больше места — это собранный фронт, берём её; измеренная высота остаётся.
  Недооценка > 10 % на divan.ru: прямой 0–7 %, кресло до 13 %, угловой — сторона 22 % (форма «Г»/«П» по названию не видна).
  `bank_ready.py:PROVEN_SQL` считает `shape_rule:transformer` доказанным; «Не раскладывается» — не трансформер (`TRANSFORMER_SQL`).
  Замер 23.10: доказано 0 → 84 из 86 (2 кресла с хвостом-габаритом ждут). Квантиль 0,9 для стороны угловых — отвергнут (ведущий):
  угловые почти перестали бы влезать.
- **Вылет люстры** (`dim_resolver.py:pendant_drop`, `DROP_RANGE`): «Высота» диапазоном «36/136» — min/max, регулируемый; «Длина цепи» —
  max = высота + цепь, min = высота (входит ли цепь в «Высоту», фид не говорит — сторона «длиннее»); «Регулируемая высота» → `drop_adj`.
  Поля — в `dims_evidence.h` (jsonb, без миграции; колонки понадобятся только для индекса/фильтра на сайте); в `dims_source` не пишутся.
  Гейт `compose_gates.py:pendant_out(…, drop_min, ceiling_cm)` / `drop_limit`: минимальная подвеска ≤ потолок − `CLEARANCE_CM` (210,
  СП 59.13330.2020); потолок — `apartmentRef.ceilingCm` (`contracts/partner.ts`, 220…450, не заполнен) → `flat215_demo.py:demo_ceiling` →
  `room.height_cm` и `demo_swap_pool.py:fits`; нет — 270 (`contracts/apartment.ts:DEFAULT_CEILING_CM`, зеркало `compose_gates.CEILING_CM`).
  Сборка (`compose2.py`) и лечение (`sets_incremental.py:_slot_ok`, только замена — стоящие не выселяются) — на базовом потолке.
  tvoydom 23.10: «Высота» диапазоном у 341 люстры, «Длина цепи» — 597, флаг регулировки — 371. Вне слота в пуле 4 253 люстр:
  при 270 — 1 131 (+31 подвес, +37 регулируемых без высоты), 250 — 1 586, 300 — 790, 320 — 530.
- **Подъём `load3.py:HASH_VERSION`** при каждой смене правил (5 — пороги света и шар, 6 — трансформеры, 7 — вылет): ночь-baseline без
  платного переобогащения; сторож — `dim_resolver.py --selftest` (`RULES_FINGERPRINT`).
- **Отвергнуто:** снять роль у категорий без размеров (теряли настоящую мебель); словари слов для фурнитуры (теряют шкафы
  Орматека); семейный приор высоты ламп (владелец 23.10); рендер подвеса на min(max, норма) (ведущий 23.10, не делаем).

## Схема (`004-stock-honesty.sql`, `005-stock-model.sql`)
- `product_page_observation`: `disposition` (accepted|quarantined|anchor|shadow), `response_kind`, `failure_kind`
  (timeout|dns|tls|rate_limit|server_error|challenge|no_signal|redirected|http_error), `evidence_kind`
  (schema|inline_stock|http_gone|none), `price_seen/name_seen/canonical_url`; view `product_page_facts`.
- `probe_domain_status(host, probe_version, policy, state, blocked_until, reason, checked_at, last_probe_at)`.
- `products.direct_url_hash` (пишет load3 через `page_alive.url_key`), поля честной модели (см. выше).

## Замеры 03.09
- Д1: tvoydom `content="in_stock"` (snake_case) не читался v1 → 3 332 «неизвестно»; Д2: gipfel `href=` не читался
  (не антибот); реальный антибот только mdm (SmartCaptcha). 1 193 `gone` — реальные 404 и по прямой, и по партнёрской
  ссылке. Цены страниц расходятся с фидом (tvoydom 9 699 vs 5 999, divanboss 21 999 vs 19 499).
- Оси tvoydom: «Длина» = фасад (1-е число названия) у стула 178:34, дивана 49:5, комода 29:1, статуэтки 72:2.
- Банк №3 vs старый: позиций 2 279 → 2 479, напольных без footprint 112 → 0, диванов без глубины 77 → 0,
  обеденных столов 71 → 121; честные потери: стеллаж 120 → 38, стенка 24 → 0, камин 62 → 22, пуф 103 → 42, витрина 32 → 5.
- Стоимость проверок: экзамен солвера на 126 сетах — 68 мин; `compose2 --style --bands all` — 2,5 мин; сборка
  демо `flat215_demo.py` — 1,5 мин; тень 760 карточек tvoydom — ~55 мин (gzip, пауза 2–5 с). Экзамен 126/126 OK.

