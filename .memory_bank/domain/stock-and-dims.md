---
tier: 2
topic: stock-and-dims-details
scope: Контроль наличия и честность размеров — модель, состояния, парсер, правило footprint
tier1: ../core/stock-and-dims.md
updated: 2026-10-18
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
`stock_evidence_at`; пишет только `stock_truth.reconcile()`; демо помечает «наличие не проверено». Парсер v2
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

