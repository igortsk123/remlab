#!/usr/bin/env python3
"""УДЕРЖАНИЕ ЯЧЕЕК КАНДИДАТА БАНКА (план conv-14b задачи 3–4, разбор Codex 23.10 `_intake/codex/bank-candidate-stability-2026-10-23-answer.md`).

ЗАЧЕМ. Ночь 23.10: ночной кандидат и проба через 30 минут совпали в 1109 из 2754 позиций — кандидат переезжал каждую ночь, ожидание
ячейки (`bank_pending`: `since`, недостающие меши) сбрасывалось, и меши, заказанные под вчерашний состав, бросались до готовности.
Теперь источник удержания — ПРЕДЫДУЩИЙ КАНДИДАТ (не живой банк): валидная ячейка копируется целиком, пересобираются только
ячейки, у которых есть причина. Этот модуль — чистые правила (сборщик `compose2` подставляет факты); здесь же отпечаток выбора.

ДВА ОТПЕЧАТКА. `selection_hash` — роли, SKU и количество позиций: по нему держится ячейка и её ожидание. Полный `candidate_hash`
(`bank_pending`: ссылка, фото, цена, габариты, запасные, капсула) проверяет публикуемую версию — его меняет и цена удержанной ячейки.

ПРАВИЛА (`rules/bank-candidate.json:keep`, умолчания — `DEFAULTS`):
  • сразу пересобрать — товар ушёл (`catalog_media`), вне контракта слота (`sets_incremental._slot_ok`), блок политики
    (`compose_gates._blocked`: replace_needed/reject журнала, failed_terminal — с семейством по `mesh_family_rep`);
  • держать — новая ссылка, фото, цена того же SKU: медиа и цена обновляются, выбор — нет;
  • `wait_catalog` (дыра каталога) — отсрочка `wait_catalog_grace_nights`, затем пересборка: иначе ячейка ждала бы вечно;
    товару, которому не хватает только обогащения (его ночная порция берёт первым), — `wait_catalog_enrich_nights`;
  • `wait_asset` (ждём меш) — пересмотр через `wait_asset_review_nights` (право на переоценку, не удаление);
  • цена ушла из сегмента тира больше чем на `price_hysteresis_pct` % и держится там `price_out_nights` ночей — пересборка;
    сразу — если у удержанных ячеек одной (полоса, стиль) сломался порядок тиров по итогу;
  • плановое обновление — раз в `refresh_days` дней: претендент заменяет ячейку, только если лучше на
    Δ ≥ max(`refresh_min_delta`, 2 × шум повторной сборки) и мешевый долг не растёт;
  • новый лучший товар сам по себе ячейку не трогает (и ту, что ждёт меш, тоже).
БОНУС ГОТОВОМУ МЕШУ (задача 4) — только последний разрыв ничьей: в окне `mesh_tie_window` баллов от лучшего (`mesh_tiebreak`).

СОСТОЯНИЕ УДЕРЖАНИЯ — рядом с кандидатом (`<кандидат>.keep.json`, `meta_path`): {ячейка: selection_hash, built_at, checked_at,
sel_price {sku: цена при выборе}, price_out {sku: с какой ночи вне сегмента}}. Сборщик пишет его рядом со своим выводом,
`bank_prepare` переносит к кандидату только вместе с готовым кандидатом.

  python3 bank_keep.py --selftest
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, 'rules', 'bank-candidate.json')
TIERS = ('эконом', 'комфорт', 'премиум')
DAY = 86400
SLACK_S = 6 * 3600          # ночь сдвигается на часы (шаг идёт не в одну минуту) — «прошла ночь» с допуском
DEFAULTS = {'enabled': True, 'wait_catalog_grace_nights': 2, 'wait_catalog_enrich_nights': 5, 'wait_asset_review_nights': 21, 'price_hysteresis_pct': 12,
            'price_out_nights': 2, 'refresh_days': 30, 'refresh_min_delta': 1.0, 'refresh_noise_p95': 0.0,
            'mesh_tie_window': 0.25}


def rules(path: str = RULES_PATH) -> dict:
    try:
        r = (json.load(open(path, encoding='utf-8')) or {}).get('keep') or {}
    except (OSError, ValueError):
        r = {}
    return {**DEFAULTS, **{k: v for k, v in r.items() if not k.startswith('_')}}


def sku(it: dict | None) -> str | None:
    return f"{it.get('mid')}:{it.get('eid')}" if it and it.get('eid') else None


def key(s: dict) -> str:
    """Ключ ячейки — как `bank_pending.key` (`set_identity.cell`: band, style, tier)."""
    return '|'.join(str(s.get(f)) for f in ('band', 'style', 'tier'))


def selection_hash(s: dict) -> str:
    """Отпечаток ВЫБОРА ячейки: роль → (SKU, количество). Цена, ссылка, фото, габариты, запасные и капсула в него не входят —
    они меняются у того же товара и выбор не меняют (Codex § 3)."""
    body = sorted((r, sku(it), int((it or {}).get('qty') or 1)) for r, it in (s.get('items') or {}).items() if sku(it))
    return hashlib.sha256(json.dumps(body, ensure_ascii=False).encode()).hexdigest()[:12]


def meta_path(candidate: str) -> str:
    return (candidate[:-5] if candidate.endswith('.json') else candidate) + '.keep.json'


def load_meta(candidate: str) -> dict:
    try:
        return (json.load(open(meta_path(candidate), encoding='utf-8')) or {}).get('cells') or {}
    except (OSError, ValueError):
        return {}


def load_stats(path: str) -> dict:
    try:
        return (json.load(open(path, encoding='utf-8')) or {}).get('stats') or {}
    except (OSError, ValueError):
        return {}


def write_meta(path: str, cells: dict, now: float, stats: dict | None = None) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'updated_at': round(now), 'stats': stats or {}, 'cells': cells}, f, ensure_ascii=False,
                  indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def nights(since: float | None, now: float) -> int:
    """Сколько ночей прошло с `since` (с допуском на сдвиг шага в ночи)."""
    return int((now - since + SLACK_S) // DAY) if since else 0


def total_of(s: dict) -> int:
    """Итог как у сборщика и `bank_promote.total_of`: запасные (`alt`) в сумму не входят."""
    return round(sum((it.get('price') or 0) * int(it.get('qty') or 1) for it in (s.get('items') or {}).values()
                     if it and not it.get('alt')))


def refresh_prices(s: dict, price_now: dict) -> int:
    """Цена удержанной ячейки — текущая каталожная (того же SKU); итог и цена второго pod пересчитываются. → сколько сменилось."""
    n = 0
    for it in list((s.get('items') or {}).values()) + [a for lst in (s.get('alternates') or {}).values() for a in (lst or [])]:
        p = price_now.get(sku(it))
        if p is not None and it.get('price') != p:
            it['price'] = p
            n += 1
    s['total'] = total_of(s)
    it = s.get('items') or {}
    if it.get('кресло 3') and it.get('столик 2') and s.get('pod_delta_price'):
        s['pod_delta_price'] = 2 * (it['кресло 3'].get('price') or 0) + (it['столик 2'].get('price') or 0)
    return n


def _in_band(p: float, band: tuple, h: float) -> bool:
    lo, hi = band
    return lo * (1 - h) <= p <= hi * (1 + h)


def price_track(s: dict, meta: dict, band_of, now: float, R: dict) -> tuple[dict, list]:
    """Гистерезис цены (Codex § 3): позиция, выбранная В сегменте тира, ушла из него больше чем на `price_hysteresis_pct` % →
    отметка `price_out[sku]` с этой ночи; держится `price_out_nights` ночей подряд — пересобрать. Вернулась — отметка снимается.
    Выбранное ВНЕ сегмента (мягкий подбор декора, люстра по середине списка) — не судим: оно и при выборе было вне.
    `band_of(role)` → (lo, hi) сегмента тира ячейки или None. → (новые отметки, позиции «пора пересобрать»)."""
    h = float(R['price_hysteresis_pct']) / 100
    sel, was = meta.get('sel_price') or {}, meta.get('price_out') or {}
    out, due = {}, []
    for role, it in (s.get('items') or {}).items():
        k = sku(it)
        if not k or it.get('alt'):
            continue
        band, p0 = band_of(role), sel.get(k)
        if not band or p0 is None or not _in_band(p0, band, h) or _in_band(it.get('price') or 0, band, h):
            continue
        out[k] = was.get(k, round(now))
        if nights(out[k], now) + 1 >= int(R['price_out_nights']):
            due.append(f'{role}: цена {it.get("price")} вне сегмента {band[0]}–{band[1]} ({nights(out[k], now) + 1} ноч.)')
    return out, due


def decide(s: dict, meta: dict, pend: dict | None, hard: list, price_due: list, now: float, R: dict,
           enriching=frozenset()) -> tuple[str, str]:
    """Судьба ячейки предыдущего кандидата → ('keep' | 'rebuild' | 'refresh', причина).
    `hard` — причины немедленной пересборки (ушёл, контракт, блок политики, порядок тиров); `pend` — запись ожидания
    `bank_pending` этой ячейки (учитывается, только если посчитана по ЭТОМУ выбору). `enriching` — товары, которым не хватает
    только обогащения (`mesh_bind.awaiting_enrichment`): ночная порция берёт товары кандидата первыми — отсрочка у них своя,
    длиннее (`wait_catalog_enrich_nights`; Codex § 2: «2–3 ночи без активного обогащения»)."""
    if hard:
        return 'rebuild', hard[0]
    if price_due:
        return 'rebuild', price_due[0]
    sh = selection_hash(s)
    if pend and pend.get('selection_hash') == sh:
        for k, m in sorted((pend.get('missing') or {}).items()):
            n = nights(m.get('since'), now)
            grace = R['wait_catalog_enrich_nights'] if (k in enriching or m.get('rep') in enriching) else R['wait_catalog_grace_nights']
            if m.get('type') == 'wait_catalog' and n >= int(grace):
                return 'rebuild', f"{m.get('role')}: дыра каталога {n} ноч. ({m.get('why')}) — отсрочка кончилась"
            if m.get('type') == 'wait_asset' and n >= int(R['wait_asset_review_nights']):
                return 'rebuild', f"{m.get('role')}: ждёт меш {n} ноч. — пересмотр"
    last = max(meta.get('built_at') or now, meta.get('checked_at') or 0)
    if now - last >= float(R['refresh_days']) * DAY:
        return 'refresh', f'плановое обновление ({int((now - last) // DAY)} дн.)'
    return 'keep', ''


def _sel_total(s: dict, meta: dict) -> int:
    sel = (meta or {}).get('sel_price') or {}
    return round(sum((sel.get(sku(it), it.get('price')) or 0) * int(it.get('qty') or 1)
                     for it in (s.get('items') or {}).values() if it and not it.get('alt')))


def _tier_pairs(cells: dict, total) -> set:
    by = {}
    for k, s in cells.items():
        if s.get('tier') in TIERS:
            by.setdefault((s.get('band'), s.get('style')), []).append((TIERS.index(s['tier']), k, s))
    bad = set()
    for grp in by.values():
        grp.sort(key=lambda x: (x[0], x[1]))
        for i, (_, ka, a) in enumerate(grp):
            for _, kb, b in grp[i + 1:]:
                if total(ka, a) > total(kb, b):
                    bad.add((ka, kb))
    return bad


def tier_conflicts(cells: dict, metas: dict | None = None) -> set:
    """Ячейки одной (полоса, стиль), у которых итог младшего тира выше старшего (`bank_promote.tier_bad`). → ключи.
    С `metas` (состояние удержания) — только пары, которые сломала СМЕНА ЦЕНЫ после выбора (при ценах выбора порядок был цел):
    такую ячейку пересобираем сразу (Codex § 3). Порядок, сломанный самой сборкой (сухая ночь 24.10: 8–10 ячеек 31–50 м²
    в свежей сборке), пересборка не чинит — она гоняла бы ячейку каждую ночь; это отчёт, не причина."""
    now = _tier_pairs(cells, lambda k, s: total_of(s))
    if metas is not None:
        now -= _tier_pairs(cells, lambda k, s: _sel_total(s, metas.get(k)))
    return {k for pair in now for k in pair}


def cell_score(s: dict) -> float:
    """Качество ячейки для планового обновления: сумма баллов подбора (`pick2` → `score`) показываемых позиций."""
    return round(sum(float(it.get('score') or 0) for it in (s.get('items') or {}).values() if it and not it.get('alt')), 2)


def mesh_debt(s: dict, needs_mesh) -> int:
    return sum(1 for r, it in (s.get('items') or {}).items() if sku(it) and needs_mesh(r, sku(it)))


def challenger_wins(kept: dict, new: dict, needs_mesh, R: dict) -> tuple[bool, str]:
    """Плановое обновление: претендент лучше на Δ ≥ max(refresh_min_delta, 2 × шум) и не увеличивает мешевый долг."""
    if selection_hash(kept) == selection_hash(new):
        return False, 'претендент тот же'
    d = round(cell_score(new) - cell_score(kept), 2)
    need = max(float(R['refresh_min_delta']), 2 * float(R['refresh_noise_p95']))
    if d < need:
        return False, f'Δ {d} < {need}'
    if mesh_debt(new, needs_mesh) > mesh_debt(kept, needs_mesh):
        return False, f'Δ {d}, но мешей не хватает больше ({mesh_debt(new, needs_mesh)} > {mesh_debt(kept, needs_mesh)})'
    return True, f'Δ {d}'


def meta_for(s: dict, prev: dict | None, action: str, now: float, price_out: dict | None = None) -> dict:
    """Запись состояния удержания ячейки после решения. Удержана — прежние built_at/sel_price; собрана заново — с этой ночи."""
    now = round(now)
    if action == 'keep' and prev and prev.get('selection_hash') == selection_hash(s):
        return {**prev, 'price_out': price_out or {}}
    if action == 'checked' and prev:
        return {**prev, 'checked_at': now, 'price_out': price_out or {}}
    return {'selection_hash': selection_hash(s), 'built_at': now, 'checked_at': now, 'price_out': {},
            'sel_price': {sku(it): it.get('price') for it in (s.get('items') or {}).values() if sku(it)}}


def mesh_tiebreak(scored: list, ready, window: float) -> list:
    """БОНУС ГОТОВОМУ МЕШУ — ТОЛЬКО ПОСЛЕДНИЙ РАЗРЫВ НИЧЬЕЙ (Codex § 2б): среди кандидатов не дальше `window` баллов от лучшего
    товар с готовым мешом идёт первым (порядок внутри групп прежний); дальше окна — как было. Основной балл не трогаем —
    иначе банк законсервировал бы посредственный ассортимент с мешами. `scored` — [(балл, товар)] уже отсортирован."""
    if window <= 0 or len(scored) < 2:
        return scored
    top = scored[0][0]
    n = next((i for i, x in enumerate(scored) if x[0] < top - window), len(scored))
    head = scored[:n]
    flags = [bool(ready(x[1])) for x in head]
    if not any(flags) or all(flags):
        return scored
    return [x for x, f in zip(head, flags) if f] + [x for x, f in zip(head, flags) if not f] + scored[n:]


def base_role(role: str) -> str:
    return re.sub(r'\s+\d+$', '', role or '')


def _selftest() -> int:
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    R = dict(DEFAULTS)
    now = 1_800_000_000

    def it(e, price=1000, **k):
        return {'mid': 1, 'eid': e, 'price': price, 'qty': 1, 'url': f'u{e}', 'img': f'i{e}', **k}

    def cell(tier='эконом', **items):
        return {'band': '14-16', 'style': 'сканди', 'tier': tier, 'items': items, 'alternates': {}, 'capsule': {'style': 'x'}}
    a = cell(диван=it('A'), столик=it('B'))
    b = {**cell(диван=it('A', price=1200, url='new', img='new2'), столик=it('B')), 'alternates': {'диван': [it('C')]}}
    ok('selection_hash: цена/ссылка/фото/запасные того же SKU выбор не меняют', selection_hash(a) == selection_hash(b))
    ok('selection_hash: другой SKU или количество — другой выбор',
       selection_hash(a) != selection_hash(cell(диван=it('A'), столик=it('X')))
       and selection_hash(a) != selection_hash(cell(диван=it('A', qty=2), столик=it('B'))))
    ok('selection_hash не зависит от порядка ролей', selection_hash(cell(столик=it('B'), диван=it('A'))) == selection_hash(a))
    m0 = meta_for(a, None, 'rebuild', now)
    ok('собрана заново: built_at, sel_price с этой ночи', m0['built_at'] == now and m0['sel_price'] == {'1:A': 1000, '1:B': 1000})
    ok('удержана: прежние built_at и sel_price', meta_for(b, m0, 'keep', now + 5 * DAY)['built_at'] == now)
    act, why = decide(a, m0, None, [], [], now + DAY, R)
    ok('ни причины — держим', act == 'keep', (act, why))
    ok('ушёл/контракт/блок — пересобрать сразу', decide(a, m0, None, ['диван: ушёл'], [], now + DAY, R) == ('rebuild', 'диван: ушёл'))
    pend = {'selection_hash': selection_hash(a), 'missing': {'1:B': {'role': 'столик', 'type': 'wait_catalog', 'why': 'нет высоты',
                                                                     'since': now}}}
    ok('wait_catalog: первая ночь — отсрочка', decide(a, m0, pend, [], [], now + DAY, R)[0] == 'keep')
    ok('wait_catalog: вторая ночь — пересобрать', decide(a, m0, pend, [], [], now + 2 * DAY - 3600, R)[0] == 'rebuild')
    ok('wait_catalog, товар в очереди обогащения: 4 ночи — ждём, 5 — пересобрать',
       decide(a, m0, pend, [], [], now + 4 * DAY, R, enriching={'1:B'})[0] == 'keep'
       and decide(a, m0, pend, [], [], now + 5 * DAY, R, enriching={'1:B'})[0] == 'rebuild')
    pend_old = {**pend, 'selection_hash': 'другой'}
    ok('ожидание посчитано по другому выбору — не учитываем', decide(a, m0, pend_old, [], [], now + 5 * DAY, R)[0] == 'keep')
    pa = {'selection_hash': selection_hash(a), 'missing': {'1:A': {'role': 'диван', 'type': 'wait_asset', 'since': now}}}
    ok('wait_asset: 20 ночей — ждём меш', decide(a, m0, pa, [], [], now + 20 * DAY, R)[0] == 'keep')
    ok('wait_asset: 21 ночь — пересмотр', decide(a, m0, pa, [], [], now + 21 * DAY, R)[0] == 'rebuild')
    ok('30 дней — плановое обновление', decide(a, {**m0}, None, [], [], now + 30 * DAY, R)[0] == 'refresh')
    ok('после проверки — снова через 30 дней',
       decide(a, meta_for(a, m0, 'checked', now + 30 * DAY), None, [], [], now + 31 * DAY, R)[0] == 'keep')
    # гистерезис цены
    band = lambda role: (900, 1100)  # noqa: E731
    po, due = price_track(cell(диван=it('A', price=1180)), m0, band, now + DAY, R)
    ok('цена в пределах 12 % за сегментом — не отметка', po == {} and due == [], (po, due))
    po, due = price_track(cell(диван=it('A', price=1300)), m0, band, now + DAY, R)
    ok('цена вне сегмента > 12 % — отметка, первая ночь не пересборка', po == {'1:A': now + DAY} and due == [], (po, due))
    po2, due2 = price_track(cell(диван=it('A', price=1300)), {**m0, 'price_out': po}, band, now + 2 * DAY, R)
    ok('вторая ночь вне сегмента — пересобрать', po2 == po and len(due2) == 1, (po2, due2))
    po3, _ = price_track(cell(диван=it('A', price=1000)), {**m0, 'price_out': po}, band, now + 2 * DAY, R)
    ok('цена вернулась — отметка снята', po3 == {})
    m_soft = {**m0, 'sel_price': {'1:A': 5000}}
    ok('выбрано вне сегмента (мягкий подбор) — цену не судим',
       price_track(cell(диван=it('A', price=6000)), m_soft, band, now + 3 * DAY, R) == ({}, []))
    # цены удержанной ячейки
    c = cell(диван=it('A'), столик=it('B'), **{'кресло 2': it('K', alt=True)})
    n = refresh_prices(c, {'1:A': 1500, '1:K': 9})
    ok('цены — каталожные, итог без запасных', n == 2 and c['total'] == 2500 and c['items']['кресло 2']['price'] == 9, (n, c['total']))
    # порядок тиров
    lo, mid = cell('эконом', диван=it('A', price=5000)), cell('комфорт', диван=it('B', price=4000))
    ok('порядок тиров сломан — обе ячейки', tier_conflicts({'e': lo, 'k': mid}) == {'e', 'k'})
    ok('порядок цел — пусто', tier_conflicts({'e': cell('эконом', диван=it('A', price=3000)), 'k': mid}) == set())
    sel_ok = {'e': {'sel_price': {'1:A': 3000}}, 'k': {'sel_price': {'1:B': 4000}}}
    ok('порядок сломала цена после выбора — пересобрать обе', tier_conflicts({'e': lo, 'k': mid}, sel_ok) == {'e', 'k'})
    sel_bad = {'e': {'sel_price': {'1:A': 5000}}, 'k': {'sel_price': {'1:B': 4000}}}
    ok('порядок был сломан уже при выборе (свойство сборки) — не пересобираем', tier_conflicts({'e': lo, 'k': mid}, sel_bad) == set())
    # плановое обновление
    kept = cell(диван=it('A', score=5.0), столик=it('B', score=3.0))
    better = cell(диван=it('C', score=6.5), столик=it('B', score=3.0))
    tiny = cell(диван=it('D', score=5.4), столик=it('B', score=3.0))
    no_mesh = lambda r, k: k == '1:C'  # noqa: E731
    ok('претендент лучше на 1.5 — заменяет', challenger_wins(kept, better, lambda r, k: False, R)[0])
    ok('претендент лучше на 0.4 — нет', not challenger_wins(kept, tiny, lambda r, k: False, R)[0])
    ok('претендент лучше, но мешевый долг растёт — нет', not challenger_wins(kept, better, no_mesh, R)[0])
    ok('шум 0.8 → порог 1.6', not challenger_wins(kept, better, lambda r, k: False, {**R, 'refresh_noise_p95': 0.8})[0])
    # бонус меша
    sc = [(5.0, {'e': 'a'}), (4.9, {'e': 'b'}), (4.8, {'e': 'c'}), (4.0, {'e': 'd'})]
    rd = lambda x: x['e'] in ('c', 'd')  # noqa: E731
    ok('в окне 0.25 готовый меш — первым, порядок прочих прежний',
       [x[1]['e'] for x in mesh_tiebreak(sc, rd, 0.25)] == ['c', 'a', 'b', 'd'])
    ok('вне окна меш не поднимается', [x[1]['e'] for x in mesh_tiebreak(sc, lambda x: x['e'] == 'd', 0.25)] == ['a', 'b', 'c', 'd'])
    ok('окно 0 — выключено', mesh_tiebreak(sc, rd, 0) == sc)
    ok('rules: умолчания и ключи из файла', rules('/нет/файла') == DEFAULTS)
    print(f'bank_keep selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
