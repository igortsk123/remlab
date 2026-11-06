#!/usr/bin/env python3
"""СТОРОЖА КАНДИДАТА БАНКА КОМНАТЫ (room-bank-01 этап Г, T-20261106-93; Codex `_intake/codex/room-bank-2026-11-06-answer.md`
§ 3 п.3–7 и «Обязательные тесты»). Спальня и прихожая.

ЗАЧЕМ. Чтобы ночью банк комнаты можно было обновлять без человека, кандидат (`sets-<комната>.next.json`) должен пройти те же
ворота, что гостиная (`bank_promote`): ячейка подменяется ЦЕЛИКОМ и только чистая, смешанный банк проверяется целиком, за ночь —
не больше четверти ячеек. Здесь — сами сторожа и сухой вердикт; ничего не пишут (писатель — `bank_refresh`, по флагам ведущего).

СТОРОЖА ЯЧЕЙКИ-ПРЕТЕНДЕНТА (по ТЕКУЩЕМУ каталогу `catalog_items.items(комната)`):
  strict — товар есть в показе комнаты (цена, фото, свежий фид — `<модуль каталога>.shown_where`), не «нет в наличии»;
           ссылка и фото — те же, что в каталоге сейчас, фото не мёртвое (`img_alive.dead_room_photos`); роль товара в каталоге
           = роль слота; крупное — с известными Ш×Г×В по каталогу и в полосе слота (`<сборщик>.gate`: `dims_sane` прихожей —
           `footprint_ok`, неизвестный размер не выдумываем); полоса записи — из типоразмеров слота (прихожая, T-90 —
           `compose_hall.check_bank`); штук — как в слоте; итог = сумме позиций;
  ready  — роли, которым по стратегии профиля (`rules/asset-strategies.json` → `hunyuan3d`) нужна модель в 3D, — привязка
           `offer_asset_binding` годна по правилу витрины (`room_bindings.usable`, режим `rooms.<комната>.mesh_gate`: модель
           привязки = модель сцены, выложена, в индексе прода). Ковёр, зеркало (`procedural_plane`), шторы и плед (`cutout`),
           лампа спальни (в витрине только строкой списка) модели не требуют — у них фото и ссылка из strict;
  exam   — экзамен на ФАКТИЧЕСКОЙ ячейке: готовая расстановка записи с размерами ТЕКУЩЕГО каталога → `planner.validate`
           HARD = 0; каждый предмет солвера записи стоит в расстановке; против живой ячейки — не меньше расставленных.
СМЕШАННЫЙ БАНК (живой + подменённые ячейки, порядок — матрица профиля):
  `<сборщик>.check_bank` (ядро, тумбы пары, полосы, разнообразие внутри (room_id, purpose), раскладка HARD) и порядок ступеней цены
  в (room_id, purpose, band, style) — НОВОЕ нарушение с участием подменяемой ячейки → она не идёт;
  demo (только спальня; у прихожей показа нет — пропуск строкой): варианты витрины (`demo_bedroom.pick_records` → `build_variant`
  со сторожем модели) по живому и по смешанному банку: вариант не пропал, нет нового `incomplete`, ядро на месте, нет
  `dims_unknown`, у каждого 3D-предмета модель годна;
  доля — не больше `max_promote_share` (25 %) ячеек живого банка за ночь, целыми ячейками; порядок — живая ячейка сломана
  (strict) → ячейка витрины → порядок матрицы (журнала ожидания, как `bank_pending` у гостиной, у комнат пока нет);
  остальные — «отложено» (снятая демо-сторожем ячейка место отложенной этой ночью не отдаёт — следующей ночью).
Живого банка нет (прихожая) — режим «поколение 0»: кандидат целиком (`room_bootstrap.verdict`) + strict + exam; ждущие модели —
предупреждением (первый банк кладёт ведущий словом, `room_bootstrap run`).

  ~/venvs/scout/bin/python room_guards.py --room bedroom [--candidate Ф] [--live Ф] [--json Ф]   # сухой вердикт, код 0
  python3 room_guards.py --selftest                                                     # тесты — tests/test_room_guards.py
"""
from __future__ import annotations

import importlib
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SOLVER = os.path.join(HERE, '..', '..', 'services', 'planner-solver')

COMPOSERS = {'bedroom': 'compose_bedroom', 'hall': 'compose_hall'}
LIST_ONLY = {'bedroom': ('лампа',)}        # в витрине только строкой (`demo_bedroom.LIST_ROLES`, T-77/2) — модели не требуют
SHARE_DEFAULT = 0.25


def base_role(role: str) -> str:
    return re.sub(r'\s+\d+$', '', role or '')


def composer(room: str):
    if room not in COMPOSERS:
        raise ValueError(f'сторожей для {room!r} нет (есть: {", ".join(COMPOSERS)})')
    return importlib.import_module(COMPOSERS[room])


def sku_of(it: dict | None) -> str | None:
    if not isinstance(it, dict):
        return None
    if it.get('mid') and it.get('eid'):
        return f"{it['mid']}:{it['eid']}"
    return it.get('sid')


def cell_key(s: dict) -> str:
    return s.get('cell') or '|'.join(str(s.get(k)) for k in ('room_id', 'purpose', 'band', 'style', 'tier'))


def mesh_roles(room: str, roles=None) -> set:
    """Роли, которым по стратегии ПРОФИЛЯ комнаты (`asset_strategies`, `_default`) нужна 3D-модель (`hunyuan3d`), кроме
    «только в списке»."""
    import room_profile as RP
    P = RP.load(room)
    st = P.get('asset_strategies') or {}
    roles = roles if roles is not None else list(P['roles'])
    return {r for r in roles if st.get(base_role(r), st.get('_default', 'hunyuan3d')) == 'hunyuan3d'
            and r not in LIST_ONLY.get(room, ())}


# ---------------------------------------------------------------- каталог
def load_catalog(room: str, fetch=None) -> dict:
    """{offer_id: CatalogItem} текущего показа комнаты (мебель room_catalog и декор products) — одним проходом адаптера."""
    import catalog_items as CI
    return {c.offer_id: c for c in CI.items(room, _fetch=fetch)}


def _photo(c) -> str:
    return (c.photo.get('best') if c.origin == 'room_catalog' else c.photo.get('url')) or ''


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def strict_cell(room: str, s: dict, cat: dict, R: dict, dead=frozenset()) -> list[str]:
    """Строгая чистота ячейки по текущему каталогу → причины (пусто — чиста)."""
    M = composer(room)
    out = []
    slots = s.get('slots') or {}
    cfg = {sl['role']: sl for sl in R['purposes'][s['purpose']]['slots']} if s.get('purpose') in R.get('purposes', {}) else {}
    for role, it in (s.get('items') or {}).items():
        k = sku_of(it)
        if not k:
            out.append(f'{role}: нет артикула')
            continue
        c = cat.get(k)
        if c is None:
            out.append(f'{role} {k}: нет в показе каталога (ушёл, нет цены/фото или не в свежем фиде)')
            continue
        if c.in_stock is False:
            out.append(f'{role} {k}: нет в наличии')
        if base_role(role) not in c.roles:
            out.append(f'{role} {k}: роль в каталоге теперь {"/".join(c.roles)}')
        if c.price is not None and it.get('price') is not None and int(it['price']) != int(c.price):
            out.append(f'{role} {k}: цена {it["price"]} ≠ {int(c.price)} в каталоге')
        if (it.get('url') or '') != (c.url or ''):
            out.append(f'{role} {k}: ссылка не текущая')
        img = _photo(c)
        if (it.get('img') or '') != img:
            out.append(f'{role} {k}: фото не текущее')
        elif img and img in dead:
            out.append(f'{role} {k}: фото мёртвое')
        sl = slots.get(role) or {}
        if sl.get('qty') is not None and int(it.get('qty') or 1) != int(sl['qty']):
            out.append(f'{role} {k}: штук {it.get("qty") or 1} ≠ {sl["qty"]} слота')
        if base_role(role) in cfg and isinstance(sl.get('band'), dict):   # тот же ворот, что при сборке (`gate` сборщика)
            d = c.dims
            cur = dict(it, role=base_role(role), w=_num(d.get('w')), d=_num(d.get('d')), h=_num(d.get('h')),
                       sleep_w=_num(d.get('sleep_w')), footprint_ok=d.get('footprint_ok') is True)   # как `to_dicts` сборщика
            g = M.gate(cur, dict(cfg[base_role(role)], ideal=sl.get('ideal') or {}), sl['band'])
            if g:
                out.append(f'{role} {k}: по каталогу сейчас {g}')
    total = sum((it.get('price') or 0) * int(it.get('qty') or 1) for it in (s.get('items') or {}).values())
    if s.get('total') is not None and abs(total - float(s['total'])) > 1:
        out.append(f"итог {s['total']} ≠ сумме позиций {total}")
    return out


# ---------------------------------------------------------------- готовность
def ready_cell(room: str, s: dict, F, roles: set) -> list[dict]:
    """Ждущие модели предметы ячейки → [{role, sku, why}] (пусто — готова к показу). F — `room_ready.Facts`."""
    import room_bindings as RB
    out = []
    for role, it in (s.get('items') or {}).items():
        if base_role(role) not in roles:
            continue
        k = sku_of(it)
        why = RB.usable(F.asset(k), F.msid(k), F.idx, F.mode)[0] if k else 'нет артикула'
        if why:
            out.append({'role': role, 'sku': k, 'why': why})
    return out


# ---------------------------------------------------------------- экзамен
def _solver_roles(room: str) -> set:
    if room == 'bedroom':
        import demo_bedroom as DB
        return set(DB.SOLVER_ROLES)
    return set(composer(room).MAJOR) | {sl['role'] for sl in composer(room).rules()['purposes'][room]['slots']}


def _placements(room: str, s: dict, cat: dict, roles: set) -> tuple[list, list]:
    """(расстановка записи с размерами текущего каталога, роли без известного размера)."""
    sys.path.insert(0, SOLVER)
    from planner.models import Item, Placement
    pls, unknown = [], []
    items = s.get('items') or {}
    for r, p in (s.get('layout') or {}).items():
        if r.startswith('_') or not isinstance(p, dict) or 'x' not in p or base_role(r) not in roles:
            continue
        it = items.get(r) or items.get(base_role(r)) or {}
        c = cat.get(p.get('sid') or sku_of(it) or '')
        w, d, h = (_num(c.dims.get(x)) for x in ('w', 'd', 'h')) if c else (p.get('w'), p.get('d'), p.get('h'))
        if not (w and d):
            unknown.append(r)
            continue
        pls.append(Placement(role=r, x=p['x'], y=p['z'], rot=int(p.get('rot') or 0), elev_cm=p.get('elev') or 0,
                             item=Item(role=r, w_cm=w, d_cm=d, h_cm=h or p.get('h') or 60)))
    return pls, unknown


def _hard(room: str, s: dict, pls: list) -> list[str]:
    from planner.models import Severity
    from planner.validate import validate
    M = composer(room)
    rm = (s.get('layout') or {}).get('_room') or {}
    model = M._room_model(rm, s['purpose']) if room == 'bedroom' else M._room_model(rm)
    return sorted({v.code for v in validate(model, pls).violations if v.severity is Severity.HARD})


def exam_cell(room: str, s: dict, cat: dict, old: dict | None = None) -> list[str]:
    """Экзамен фактической ячейки → причины (пусто — сдала). old — живая ячейка той же клетки (сравнение «не хуже»)."""
    roles = _solver_roles(room)
    rm = (s.get('layout') or {}).get('_room')
    if not isinstance(rm, dict) or not rm.get('w'):
        return ['нет комнаты расстановки (layout._room)']
    out = []
    need = [r for r in (s.get('items') or {}) if base_role(r) in roles]
    lay = s.get('layout') or {}
    miss = [r for r in need if not any(base_role(k) == base_role(r) and isinstance(v, dict) and 'x' in v
                                       for k, v in lay.items() if not k.startswith('_'))]
    if miss:
        out.append(f'не в расстановке: {", ".join(miss)}')
    pls, unknown = _placements(room, s, cat, roles)
    if unknown:
        out.append(f'размер по каталогу неизвестен: {", ".join(unknown)}')
    hard = _hard(room, s, pls)
    if hard:
        out.append(f'жёсткие нарушения с размерами каталога: {hard}')
    if old is not None:
        before, _ = _placements(room, old, cat, roles)
        if len(pls) < len(before):
            out.append(f'расставлено меньше живой ячейки: {len(pls)} < {len(before)}')
    return out


# ---------------------------------------------------------------- смешанный банк
def _tier_order(R: dict) -> list:
    return sorted(R['tiers'], key=lambda t: sum(R['tiers'][t]) / 2)


def tier_problems(bank: list, R: dict) -> list[str]:
    """Порядок ступеней цены в группе (room_id, purpose, band, style): итог младшей > старшей — нарушение (оба set_id)."""
    order = _tier_order(R)
    out = []
    groups: dict = {}
    for s in bank:
        if s.get('tier') in order:
            groups.setdefault((s.get('room_id'), s.get('purpose'), s.get('band'), s.get('style')), []).append(s)
    for g, sets in groups.items():
        sets = sorted(sets, key=lambda x: order.index(x['tier']))
        for i, lo in enumerate(sets):
            for hi in sets[i + 1:]:
                if float(lo.get('total') or 0) > float(hi.get('total') or 0):
                    out.append(f"{lo['set_id']}↔{hi['set_id']}: ступень {lo['tier']} ({lo.get('total')}) дороже "
                               f"{hi['tier']} ({hi.get('total')}) в {'|'.join(map(str, g))}")
    return out


def bank_problems(room: str, bank: list, R: dict, tol: tuple, spare: str = 'hard') -> list[str]:
    """Нарушения банка целиком: сборщик (`check_bank`) + порядок ступеней; «~» — предупреждения, отброшены."""
    M = composer(room)
    got = M.check_bank(bank, R, tol, spare=spare) if room == 'bedroom' else M.check_bank(bank, R, tol)
    return [p for p in got if not p.startswith('~')] + tier_problems(bank, R)


# ---------------------------------------------------------------- витрина спальни
def mesh_gate(F):
    """Сторож модели варианта (как `flat215_demo.bedroom_mesh_gate`): товар витрины → '' или причина."""
    import room_bindings as RB

    def ok(x: dict) -> str:
        k = str(x.get('sid') or '').replace('_', ':', 1)
        return RB.usable(F.asset(k), x.get('msid'), F.idx, F.mode)[0] if k else 'нет артикула'
    ok.note = lambda x: RB.orient_note(F.asset(str(x.get('sid') or '').replace('_', ':', 1)), F.mode)
    return ok


def demo_variants(bank: list, cat: dict, F, styles: list) -> dict:
    """{(room_id, стиль): {'rec', 'variant' | 'incomplete'}} — витрина спальни по банку тем же кодом, что сборка демо."""
    import demo_bedroom as DB
    import footprint as FP

    def sku(items: dict, role: str):
        it = items.get(role) or items.get(base_role(role))
        k = sku_of(it)
        if not k:
            return None
        c = cat.get(k)
        dims = {x: (_num(c.dims.get(x)) if c else it.get(x)) for x in ('w', 'd', 'h')}
        return {'name': it.get('name'), 'sid': k.replace(':', '_', 1), 'msid': F.msid(k), 'url': it.get('url'),
                'img': it.get('img'), **dims}

    def dims_of(v, s, role=''):
        s = s or {}
        known = FP.footprint_known({'w': s.get('w'), 'd': s.get('d')})
        return {'w': s.get('w'), 'd': s.get('d'), 'h': s.get('h'), 'dims_src': 'каталог' if known else 'неизвестно',
                'dims_unknown': not known}
    rooms = list(dict.fromkeys(r['room_id'] for r in bank))
    recs = DB.pick_records(bank, rooms, styles)
    lays: dict = {}
    if DB.one_rule().get('enabled'):
        for rid in rooms:
            rs = [r for r in recs if r['room_id'] == rid and isinstance((r.get('layout') or {}).get('_room'), dict)]
            arts, _ = DB.one_layout({r['style']: r['layout'] for r in rs}, styles, {r['style']: r.get('purpose') for r in rs})
            lays.update({(rid, st): a for st, a in arts.items()})
    gate, lead, out = mesh_gate(F), DB.lead_roles(), {}
    for rec in recs:
        geo = DB.room_geo(rec['room_id'], layout_room=DB.bank_room(bank, rec['room_id']))
        v, why = DB.build_variant(rec, geo, sku, dims_of, lambda st: st or None, mesh_ok=gate, lead=lead,
                                  layout=lays.get((rec['room_id'], rec.get('style'))),
                                  spares=DB.lead_spares(bank, rec, lead))
        out[(rec['room_id'], rec.get('style'))] = {'rec': rec, 'variant': v, 'incomplete': why}
    return out


CORE = ('кровать', 'шкаф', 'комод')


def core_of(v: dict | None) -> set:
    """Ядро спальни, стоящее в 3D варианта: кровать и шкаф/комод (`compose_bedroom.check_bank` «ядро неполное»)."""
    return {base_role(x['role']) for x in (v or {}).get('items') or []} & set(CORE)


def demo_problems(old: dict, new: dict, promoted: set, F, roles: set) -> dict:
    """Демо-сторож old ↔ hybrid → {ячейка: [причины]} только у подменённых ячеек (`promoted` — ключи ячеек)."""
    gate = mesh_gate(F)
    out: dict = {}
    for key, n in new.items():
        c = cell_key(n['rec'])
        if c not in promoted:
            continue
        o = old.get(key) or {}
        bad = []
        if n['incomplete']:
            if o.get('variant'):
                bad.append(f"вариант {key[0]} «{key[1]}» пропал: нет {', '.join(map(str, n['incomplete'].get('missing') or []))}")
            elif not o.get('incomplete'):
                bad.append(f"новый incomplete {key[0]} «{key[1]}»: {', '.join(map(str, n['incomplete'].get('missing') or []))}")
        v = n['variant'] or {}
        if v:
            gone = core_of(o.get('variant')) - core_of(v)      # было в 3D живого варианта, нет в смешанном
            if gone:
                bad.append(f"ядро в витрине: пропало {', '.join(sorted(gone))} (есть {', '.join(sorted(core_of(v))) or '—'})")
        if v.get('dims_unknown'):
            bad.append('размер неизвестен у размещаемого: ' + ', '.join(x['role'] for x in v['dims_unknown']))
        for x in v.get('items') or []:
            if base_role(x['role']) in roles and gate(x['sku']):
                bad.append(f"{x['role']}: модель не годна ({gate(x['sku'])})")
        if bad:
            out[c] = bad
    for key, o in old.items():          # стиль комнаты был в витрине, а в смешанном банке его нет совсем
        if o.get('variant') and key not in new:
            out.setdefault('*', []).append(f'вариант {key[0]} «{key[1]}» пропал из выбора')
    return out


# ---------------------------------------------------------------- план
def sig(s: dict) -> str:
    """Содержимое ячейки для «изменилась ли»: состав (артикул, штук, цена), запас замен, расстановка."""
    lay = {r: [p.get('x'), p.get('z'), p.get('rot'), p.get('sid')] for r, p in (s.get('layout') or {}).items()
           if not r.startswith('_') and isinstance(p, dict)}
    return json.dumps({'items': {r: [sku_of(it), it.get('qty'), it.get('price')] for r, it in (s.get('items') or {}).items()},
                       'alts': {r: [sku_of(a) for a in xs] for r, xs in (s.get('alternates') or {}).items()},
                       'layout': lay, 'total': s.get('total')}, ensure_ascii=False, sort_keys=True)


def hybrid_of(live: list, cand: list, take: set, order: list | None = None) -> list:
    """Смешанный банк: ячейки `take` — запись кандидата ЦЕЛИКОМ, остальные — живая ЦЕЛИКОМ; порядок — `order` (матрица
    профиля), затем живые ячейки вне матрицы на своих местах."""
    L = {cell_key(s): s for s in live}
    C = {cell_key(s): s for s in cand}
    order = order or [cell_key(s) for s in cand]
    out, seen = [], set()
    for c in order:
        rec = C.get(c) if c in take else L.get(c)
        if rec is not None:
            out.append(rec)
            seen.add(c)
    out += [s for s in live if cell_key(s) not in seen]
    return out


def plan(live: list, cand: list, *, strict_fn, ready_fn, exam_fn, bank_fn, demo_fn=None, share: float = SHARE_DEFAULT,
         order: list | None = None, demo_cells: set = frozenset()) -> dict:
    """Решение по ячейкам кандидата против живого банка → {'rows': [...], 'take': [ячейки], 'hybrid': [...], 'cap': N}.
    Решения: same (не изменилась), rejected (strict/exam/связи/демо — причины), waiting (ждёт модели), promote, deferred (предел)."""
    L = {cell_key(s): s for s in live}
    rows, cand_by = [], {}
    for i, s in enumerate(cand):
        c = cell_key(s)
        cand_by[c] = s
        old = L.get(c)
        row = {'cell': c, 'set_id': s.get('set_id'), 'index': i, 'new': old is None}
        if old is not None and sig(old) == sig(s):
            rows.append(dict(row, decision='same'))
            continue
        st, ex = strict_fn(s), exam_fn(s, old)
        wait = ready_fn(s)
        if st or ex:
            rows.append(dict(row, decision='rejected', kind='strict' if st else 'exam', reasons=(st + ex)[:8]))
        elif wait:
            rows.append(dict(row, decision='waiting', kind='ready',
                             reasons=[f"{w['role']} {w['sku']}: {w['why']}" for w in wait][:8]))
        else:
            rows.append(dict(row, decision='eligible', live_broken=bool(old is not None and strict_fn(old)),
                             demo=c in demo_cells))
    cap = math.floor(share * len(live)) if live else len(cand)
    base = set(bank_fn(live)) if live else set()
    elig = sorted((r for r in rows if r['decision'] == 'eligible'),
                  key=lambda r: (not r['live_broken'], not r['demo'], r['index']))
    take: list = []
    for r in elig:
        if len(take) >= cap:
            r.update(decision='deferred', reasons=[f'предел {cap} ячеек за ночь ({share:.0%} живого) — следующей ночью'])
            continue
        hyb = hybrid_of(live, cand, set(take) | {r['cell']}, order)
        new = [p for p in bank_fn(hyb) if p not in base and (r['set_id'] or '\0') in p]
        if new:
            r.update(decision='rejected', kind='bank', reasons=new[:8])
            continue
        take.append(r['cell'])
        r['decision'] = 'promote'
    for _ in range(len(take) + 1):     # демо и перепроверка связей после снятых: пока не устоится
        if not take:
            break
        hyb = hybrid_of(live, cand, set(take), order)
        drop: dict = {}
        if demo_fn is not None:
            got = demo_fn(live, hyb, set(take)) or {}
            for c, why in got.items():
                if c in take:
                    drop[c] = ('demo', why)
            if '*' in got:              # стиль пропал из выбора — виновника не указать: все подмены ночи снимаются
                drop.update({c: ('demo', got['*']) for c in take if c not in drop})
        probs = [p for p in bank_fn(hyb) if p not in base]
        for c in take:
            sid = cand_by[c].get('set_id') or '\0'
            hit = [p for p in probs if sid in p]
            if hit and c not in drop:
                drop[c] = ('bank', hit)
        if not drop:
            break
        for r in rows:
            if r['cell'] in drop:
                kind, why = drop[r['cell']]
                r.update(decision='rejected', kind=kind, reasons=why[:8])
        take = [c for c in take if c not in drop]
    return {'rows': rows, 'take': take, 'cap': cap, 'hybrid': hybrid_of(live, cand, set(take), order), 'share': share}


def summary(rep: dict) -> dict:
    out: dict = {}
    for r in rep['rows']:
        k = r['decision'] + (f":{r['kind']}" if r.get('kind') and r['decision'] == 'rejected' else '')
        out[k] = out.get(k, 0) + 1
    return out


# ---------------------------------------------------------------- ночь
ROOM_RU = {'bedroom': 'спальня', 'hall': 'прихожая'}


def _wait_lines(rows: list) -> list[str]:
    return [f"{w['role']} {w['sku']}: {w['why']}" for w in rows][:8]


def night(room: str, cand: list, live: list | None, *, cat: dict, F, R: dict, tol: tuple, dead=frozenset(),
          share: float = SHARE_DEFAULT, identity_fn=None, gen0_verdict=None, F_strict=None,
          assume_ready: bool = False) -> tuple[dict, list[str]]:
    """Сухой вердикт ночи → (отчёт, строки вывода; последняя — DIGEST одной строкой на комнату).
    identity_fn(комната, кандидат) — отказы идентичности (`room_bootstrap.identity`): есть — кандидат не годен целиком.
    gen0_verdict — суд поколения 0 (`room_bootstrap.verdict`), когда живого банка нет. F_strict — те же факты в режиме
    strict (привязка `ready` + `published_3d`): сколько ячеек ждали бы ещё при строгом правиле — строкой, вердикт не меняет.
    assume_ready — ДИАГНОСТИКА (как `--force-ready` гостиной): ожидание моделей снято, чтобы увидеть остальных сторожей на
    живых данных; в ночи не используется, в строке дайджеста помечено."""
    roles = mesh_roles(room)
    strict_fn = lambda s: strict_cell(room, s, cat, R, dead)   # noqa: E731
    ready_fn = (lambda s: []) if assume_ready else (lambda s: ready_cell(room, s, F, roles))   # noqa: E731
    exam_fn = lambda s, old: exam_cell(room, s, cat, old)       # noqa: E731
    L, ru = [], ROOM_RU.get(room, room)
    nodemo = 'у прихожей показа нет — демо-сторож пропущен'
    if not live:
        fatal = gen0_verdict(room, cand) if gen0_verdict else (identity_fn(room, cand) if identity_fn else [])
        rows = []
        for i, s in enumerate(cand):
            st, ex, wt = strict_fn(s), exam_fn(s, None), ready_fn(s)
            d = 'rejected' if st or ex else ('waiting' if wt else 'ok')
            rows.append({'cell': cell_key(s), 'set_id': s.get('set_id'), 'index': i, 'decision': d,
                         'kind': 'strict' if st else ('exam' if ex else ('ready' if wt else None)),
                         'reasons': (st + ex)[:8] if d == 'rejected' else _wait_lines(wt)})
        rep = {'room': room, 'mode': 'generation0', 'fatal': fatal, 'rows': rows, 'take': [], 'cap': None}
        sm = summary(rep)
        good = not fatal and not sm.get('rejected:strict') and not sm.get('rejected:exam')
        L.append(f'room_guards {room}: живого банка нет — режим «поколение 0»; ячеек кандидата {len(cand)}')
        L += [f'  ✗ {x}' for x in fatal[:10]]
        L += [f"  {r['decision']}:{r['kind']} {r['cell']}: " + '; '.join(r['reasons'])[:300]
              for r in rows if r['decision'] == 'rejected']
        L.append('  ' + (nodemo if room == 'hall' else 'демо-сторож: живого банка нет — сравнивать не с чем'))
        L.append(f"DIGEST:банк {ru} (сторожа, сухо): поколение 0 — {'годен' if good else 'не годен'}; ячеек {len(cand)}, "
                 f"strict ✗{sm.get('rejected:strict', 0)}, экзамен ✗{sm.get('rejected:exam', 0)}, ждут модели "
                 f"{sm.get('waiting', 0)}, без замечаний {sm.get('ok', 0)}" + (f'; отказов кандидата {len(fatal)}' if fatal else '')
                 + ('; демо — нет показа' if room == 'hall' else '') + '; живой не тронут')
        return rep, L
    fatal = identity_fn(room, cand) if identity_fn else []
    if fatal:
        rep = {'room': room, 'mode': 'replace', 'fatal': fatal, 'rows': [], 'take': [], 'cap': None}
        L.append(f'room_guards {room}: кандидат не годен целиком ({len(fatal)})' + ''.join(f'\n  ✗ {x}' for x in fatal[:10]))
        L.append(f'DIGEST:банк {ru} (сторожа, сухо): кандидат не годен целиком — {fatal[0][:120]}; живой не тронут')
        return rep, L
    demo_fn = None          # у прихожей показа нет — демо-сторож не зовётся (строка ниже)
    demo_cells: set = set()
    if room == 'bedroom':
        import demo_bedroom as DB
        styles = [s for s in R['styles'] if any(x.get('style') == s for x in live + cand)]
        demo_cells = {cell_key(r) for r in DB.pick_records(live, list(dict.fromkeys(x['room_id'] for x in live)), styles)}
        memo: dict = {}

        def bedroom_demo(lv, hyb, take):
            if 'old' not in memo:
                memo['old'] = demo_variants(lv, cat, F, styles)
            return demo_problems(memo['old'], demo_variants(hyb, cat, F, styles), take, F, roles)
        demo_fn = bedroom_demo
    bank_fn = lambda b: bank_problems(room, b, R, tol)          # noqa: E731
    rep = plan(live, cand, strict_fn=strict_fn, ready_fn=ready_fn, exam_fn=exam_fn, bank_fn=bank_fn, demo_fn=demo_fn,
               share=share, order=[cell_key(s) for s in cand], demo_cells=demo_cells)
    rep.update(room=room, mode='replace', fatal=[])
    rep.pop('hybrid', None)
    sm = summary(rep)
    L.append(f"room_guards {room}: живой {len(live)} ячеек, кандидат {len(cand)}; предел {rep['cap']} ({share:.0%})")
    for r in rep['rows']:
        if r['decision'] not in ('same', 'promote'):
            L.append(f"  {r['decision']}{':' + r['kind'] if r.get('kind') else ''} {r['cell']}: " + '; '.join(r.get('reasons') or [])[:300])
    if room == 'hall':
        L.append('  ' + nodemo)
    if F_strict is not None and F.mode != 'strict':
        more = sum(1 for r, s in zip(rep['rows'], cand) if r['decision'] != 'same'
                   and ready_cell(room, s, F_strict, roles) and not ready_cell(room, s, F, roles))
        L.append(f'  правило модели {F.mode}; при strict (ready + published_3d) ждали бы ещё ячеек: {more}; в живом банке '
                 f'ждут модели {sum(1 for s in live if ready_cell(room, s, F, roles))} из {len(live)}')
    rej = {k.split(':')[1]: v for k, v in sm.items() if k.startswith('rejected:')}
    L.append(f"DIGEST:банк {ru} (сторожа, сухо): подменить {sm.get('promote', 0)} из {len(cand)} (предел {rep['cap']}), "
             f"без изменений {sm.get('same', 0)}, ждут модели {sm.get('waiting', 0)}, отложено {sm.get('deferred', 0)}, отказ "
             f"{sum(rej.values())}" + (' (' + ', '.join(f'{k} {v}' for k, v in rej.items()) + ')' if rej else '')
             + ('' if room == 'bedroom' else '; демо — нет показа') + '; живой не тронут'
             + ('; ДИАГНОСТИКА: ожидание моделей снято' if assume_ready else ''))
    return rep, L


def run_night(room: str, cand_path: str | None = None, json_out: str | None = None, live_path: str | None = None,
              assume_ready: bool = False) -> int:
    """Сухой вердикт по файлам комнаты (кандидат, живой банк), каталогу и привязке — печать; JSON — только по `--json`.
    live_path — другой живой банк (только чтение; сухой прогон из worktree против основной копии)."""
    import room_bank_spec as RBS
    import room_bootstrap as RBo
    import room_ready as RR
    spec = RBS.for_room(room)
    M = composer(room)
    cand_path = cand_path or spec.candidate
    live_path = live_path or spec.live
    try:
        cand = json.load(open(cand_path, encoding='utf-8'))
    except (FileNotFoundError, ValueError) as e:
        print(f'WARN:room_guards:{room}: кандидат {cand_path} не читается ({type(e).__name__}) — сторожа не судили', flush=True)
        print(f'DIGEST:банк {ROOM_RU.get(room, room)} (сторожа, сухо): кандидата нет — не судили; живой не тронут', flush=True)
        return 0
    live = json.load(open(live_path, encoding='utf-8')) if os.path.exists(live_path) else None
    try:
        from img_alive import dead_room_photos
        dead = dead_room_photos()
    except Exception as e:  # noqa: BLE001 — нет базы: фото судим по ссылке, мёртвых не знаем (строкой)
        print(f'WARN:room_guards: мёртвые фото не читаются ({type(e).__name__}) — проверка «фото мёртвое» пропущена', flush=True)
        dead = set()
    cat = load_catalog(room)
    F = RR.load_facts(mode=spec.rules().get('mesh_gate') or 'orient', demo_data=spec.demo_data)
    F_strict = RR.Facts(F.rows, F.why, F.idx, F.rep_map, 'strict')
    R = M.rules()
    share = float(os.environ.get('BANK_MAX_PROMOTE_SHARE')
                  or json.load(open(spec.rules_path, encoding='utf-8')).get('max_promote_share', SHARE_DEFAULT))
    skipped = RBo.skipped_of(cand_path)
    rep, lines = night(room, cand, live, cat=cat, F=F, R=R, tol=M.tolerance(), dead=dead, share=share, F_strict=F_strict,
                       identity_fn=lambda rm, c: RBo.identity(rm, c, skipped),
                       gen0_verdict=lambda rm, c: RBo.verdict(rm, c, skipped=skipped), assume_ready=assume_ready)
    for x in lines:
        print(x, flush=True)
    if json_out:
        json.dump(rep, open(json_out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    return 0


def _opt(argv: list, name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None


def main(argv: list) -> int:
    if '--selftest' in argv:
        import subprocess
        return subprocess.call([sys.executable, os.path.join(HERE, 'tests', 'test_room_guards.py')])
    import room_bank_spec as RBS
    room, argv = RBS.room_arg(argv)
    if room not in COMPOSERS:
        print(__doc__)
        return 2
    return run_night(room, _opt(argv, '--candidate'), _opt(argv, '--json'), _opt(argv, '--live'), '--assume-ready' in argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
