#!/usr/bin/env python3
"""ПРОБА АГЕНТА: ВСЕ СПАЛЬНИ ЗАГРУЖЕННОГО ПЛАНА (план agent-trial-04-bedroom, задачи А–Д; T-20261109-22).

Вход — результат стенда (`contracts/trial.ts:floorplanResult`, см). Шаги на комнату:
  1. спальни всех панелей (`kind == 'bedroom'`, либо «Bedroom …» в составной подписи); id — `bedroom-<n>`, единые на задание;
  2. контур → ядро и проёмы теми же функциями, что у гостиной (`trial_room`): без окна комната не отказ (флаг), без входа — отказ;
  3. подбор: стиль → наборы и запас того же стиля из банка спальни (`sets-bedroom.json`, ТОЛЬКО товары; готовая расстановка чужой
     квартиры `layout` не читается, TG 1377) плюс кровати каталога в стиле; в подбор идёт только товар с годной живой моделью
     (`flat215_demo.room_mesh_gate('bedroom')`);
  4. кровать — по площади: ближайшая к идеальной ширине (120–180, узких 90 нет — решение владельца); нет модели или не встала — следующая,
     что влезает; ни одна — комната без кровати и честный текст (TG 1377);
  5. проверка солвером и по ПОЛНОМУ контуру (`planner.validate` + `trial_room.post_check`): мебель в контуре, дуги дверей обеих
     петель свободны, вход достижим;
  6. масштаб не подтверждён — отказ по всем комнатам, вопросов не задаём, мебель не подгоняем;
  7. выход `bedrooms.json` — только разрешённые поля (`ITEM_KEYS`, `SKU_KEYS`); проверка `assert_no_shop` по всему JSON: ни названий,
     ни ссылок магазинов. `bundle_parts(job)` — куски для общей версии данных задания (`trial_bundle`).

  ~/venvs/scout/bin/python trial_bedroom.py <trial_id> <floorplanResult.json> [--frames <папка>]
  ~/venvs/scout/bin/python trial_bedroom.py <trial_id> --bench model-*.json [--frames <папка>]
  ~/venvs/scout/bin/python trial_bedroom.py --coverage [--out <папка>]    # А: живые готовые кровати по ширине × стилю
Банк — `TRIAL_BEDROOM_SETS` (по умолчанию `tools/scout/sets-bedroom.json` этой копии). Код выхода: 0 — готово, 3 — частично, 2 — отказ.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import demo_room as R  # noqa: E402
import trial_demo as TD  # noqa: E402
import trial_room as TR  # noqa: E402

COMP = json.load(open(os.path.join(HERE, 'rules', 'bedroom-composition.json'), encoding='utf-8'))
STYLE_ID = {'сканди': 'scandi', 'современный': 'modern', 'минимализм': 'minimal', 'лофт': 'loft', 'неоклассика': 'neoclassic',
            'джапанди': 'japandi'}
STYLES = list(COMP.get('styles') or STYLE_ID)
BED_NAME = re.compile(r'\b(bed\s?room|bedroom|guest\s?room|box\s?room|nursery)\b', re.I)
NOT_BED = re.compile(r'en[\s-]?suite|bath|wc|shower|dressing|landing|closet|linen', re.I)
ROOM_ROLES = ('кровать', 'тумба прикроватная', 'шкаф', 'комод')
NEUTRAL = {'кровать': 'Bed', 'тумба прикроватная': 'Bedside table', 'шкаф': 'Wardrobe', 'комод': 'Chest of drawers'}
BED_WIDTHS = (120, 140, 160, 180)                  # ширины спального места пробы; узкие 90 — вне охвата (TG 1377)
NARROW_MAX_CM = 100.0                              # спальное/рама уже — «узкая», не ставим и не считаем
IDEAL_SIZES = ((18.0, 300.0, 180), (11.5, 255.0, 160), (9.0, 0.0, 140), (0.0, 0.0, 120))   # площадь ядра, короткая сторона → идеальная ширина спального, см (NDSS)
NDSS_DOUBLE = (11.5, 255.0)                        # двуспальная «для пары» — NDSS 2015 (площадь м², короткая сторона см)
NIGHTSTANDS = {'couple': 2, 'guest': 1, 'single': 1}
MAX_BEDS = 10                                      # кроватей на стиль × ядро в переборе
ROOM_BUDGET_S = 25.0                               # бюджет на комнату (чтобы плохой план не ел конвейер); вышло — лучшее, что есть
MIN_STYLES_READY = 2                               # меньше стилей — комната честно «частично» (владелец TG 1382: разные стили)
SMALLEST_BED = {'sofa': [120.0, 195.0], 'bearer': [0.0, 0.0], 'tv_min_cm': 0.0}   # «влезает ли хоть какая-то кровать» в ядро (рама 120)

# ТЕКСТЫ ДЛЯ ПОКУПАТЕЛЯ по комнате (страница на английском; TG 1377). Код → текст
TEXT_NO_PRODUCTS = 'No suitable products under the current templates.'
TEXT_NOT_READABLE = 'This room could not be read reliably from the plan, so furniture was not placed.'
OUTCOME_TEXT = {
    'scale_unverified': 'Room dimensions could not be confirmed from this plan, so furniture was not placed.',
    'no_products': TEXT_NO_PRODUCTS, 'bed_no_fit': TEXT_NO_PRODUCTS, 'room_too_small': TEXT_NO_PRODUCTS,
    'contour_distorted': TEXT_NOT_READABLE, 'opening_ambiguous': TEXT_NOT_READABLE, 'no_core': TEXT_NOT_READABLE,
    'opening_cut_by_core': TEXT_NOT_READABLE, 'no_entry': TEXT_NOT_READABLE, 'no_bedrooms': None,
    'partial': 'Some styles or items are not available for this room.'}
OUTCOME_DEFAULT = 'Furniture could not be placed in this room.'
# ЕДИНЫЙ РАЗРЕШЁННЫЙ СПИСОК ПОЛЕЙ ТОВАРА В ВЫХОДЕ (TG 1377, Codex 09.11): предмет и его `sku` — только эти поля; ни `url`, `shop`,
# `img`, ни цены магазина. Источник один — `public_item`; `assert_no_shop` проверяет ВЕСЬ JSON задания.
ITEM_KEYS = {'role', 'x', 'y', 'rot', 'w', 'd', 'h', 'dims_src', 'sku', 'corner', 'corner_left', 'section', 'elev'}
SKU_KEYS = {'name', 'msid', 'w', 'd', 'h', 'sleep_w'}
SHOP_LINKS = re.compile(r'(https?:|//[a-z0-9.-]+\.[a-z]{2,}|gdeslon|\berid=)', re.I)
BANNED_KEYS = {'url', 'url_direct', 'shop', 'img', 'img_hd', 'price', 'brand'}


class BedroomRefusal(Exception):
    def __init__(self, code: str, detail: str = ''):
        super().__init__(f'{code}: {detail}')
        self.code, self.detail = code, detail


class ShopLeak(RuntimeError):
    pass


def base_role(role: str) -> str:
    return re.sub(r'\s+\d+$', '', role or '')


# ───────────────────────── спальни плана → ядро ─────────────────────────

def _bedroom_named(name: str) -> bool:
    """Спальня по имени: хоть одна часть подписи — «Bedroom …», и она не про санузел («Bedroom 2 / En-suite»)."""
    return any(BED_NAME.search(p) and not NOT_BED.search(p) for p in re.split(r'[/,+&]', name or ''))


def bedrooms_of(result: dict) -> list:
    """→ [(панель, комната, id)]: все спальни со всех панелей, id `bedroom-<n>` — по порядку панелей, единые на задание."""
    out, n = [], 0
    for panel in result.get('panels') or []:
        for room in panel.get('rooms') or []:
            if room.get('kind') == 'bedroom' or _bedroom_named(room.get('name') or ''):
                n += 1
                out.append((panel, room, f'bedroom-{n}'))
    return out


def adapt_room(panel: dict, room: dict, cfg: dict) -> dict:
    """Спальня плана → {poly, ops, candidates, flags, room_id…} (шаги `trial_room.adapt` без правил гостиной: окно не обязательно,
    обязательная группа — самая маленькая кровать). Отказ — `BedroomRefusal`."""
    from planner.geometry import largest_free_rectangles
    ours, amb = TR._openings_of(panel, room, cfg)
    if amb:
        raise BedroomRefusal('opening_ambiguous', '; '.join(f"{o['kind']} {o['widthCm']:.0f} см в {o['_d']:.0f} см от стены" for o in amb))
    flags = [] if TR._light(ours, cfg)[0] else ['no_window']
    try:
        fr = TR.ortho_frame(room['contour'], cfg)
        ops = [TR._place_opening(fr['poly'], o, fr['T'], cfg) for o in ours]
    except TR.Refusal as e:
        raise BedroomRefusal(e.code, e.detail) from e
    rects = [g.bounds for g in largest_free_rectangles(fr['poly'], min_side_cm=cfg['core_min_side_cm'], limit=24)]
    if not rects:
        raise BedroomRefusal('no_core', 'нет прямоугольного ядра')
    cands = [TR.core_candidate(fr['poly'], r, ops, SMALLEST_BED, cfg) for r in rects[:int(cfg['core_candidates'])]]
    ok = [c for c in cands if not c['reasons']]
    ok.sort(key=lambda c: (not c['light_on_core'], -c['area_m2']))
    if not ok:
        why = [r.split(':')[0] for c in cands for r in c['reasons']]
        if 'opening_unplaced' in why and 'no_entry' not in why and 'living_core_small' not in why:
            code = 'opening_ambiguous'
        else:
            code = next((m for k, m in (('opening_cut_by_core', 'opening_cut_by_core'), ('no_entry', 'no_entry'),
                                        ('living_core_small', 'room_too_small')) if k in why), 'no_core')
        raise BedroomRefusal(code, '; '.join(f"ядро {c['w']:.0f}×{c['d']:.0f}: {', '.join(c['reasons'])}" for c in cands))
    return {'panel': panel, 'room': room, 'poly': fr['poly'], 'ops': ops, 'candidates': ok, 'flags': flags,
            'contour': fr['contour'], 'control': fr['control']}


# ───────────────────────── товары: живые модели, запас по стилю ─────────────────────────

def _sid(it: dict) -> str | None:
    return it.get('sid') or (f"{it['mid']}:{it['eid']}" if it.get('mid') and it.get('eid') else None)


def _sku(it: dict) -> dict:
    return {'sid': (_sid(it) or '').replace(':', '_', 1)}


def _defect_names() -> re.Pattern | None:
    md = (COMP.get('mesh_defect') or {}).get('names')
    return re.compile(md, re.I) if md else None


def _ready(it: dict | None, mesh_ok, defect) -> bool:
    """Годен в подбор: знаем размер, модель готова и выложена (`mesh_ok`), не брак по имени."""
    if not it or not _sid(it) or not (it.get('w') and it.get('d') and it.get('h')):
        return False
    if defect and defect.search(it.get('name') or ''):
        return False
    return not mesh_ok(_sku(it))


def _sleep_w(it: dict) -> float:
    """Ширина спального места; неизвестна — по раме (рама шире места на типичные 5–15 см, запас для узких — рамой)."""
    v = it.get('sleep_w')
    return float(v) if isinstance(v, (int, float)) and v > 0 else float(it.get('w') or 0) - 10.0


def _bed_ok(it: dict) -> bool:
    return _sleep_w(it) >= NARROW_MAX_CM and it.get('w', 0) >= NARROW_MAX_CM


def load_bank() -> list:
    path = os.environ.get('TRIAL_BEDROOM_SETS') or os.path.join(HERE, 'sets-bedroom.json')
    return R.load_bank(path)


def bank_pool(bank: list, style: str, role: str) -> list:
    """Товары роли у записей банка стиля (сначала сами наборы, потом `alternates`), без повторов; порядок банка.
    Запись банка = список товаров; её расстановка `layout` НЕ используется (чужая геометрия, TG 1377)."""
    recs = [r for r in bank if (r.get('style') or '') == style]
    seen, rows = set(), []
    for r in recs:
        for it in [v for k, v in (r.get('items') or {}).items() if base_role(k) == role] + list((r.get('alternates') or {}).get(role) or []):
            sid = _sid(it)
            if sid and sid not in seen:
                seen.add(sid)
                rows.append(dict(it, _style=style, _src='bank'))
    return rows


def catalog_beds(style: str, thr: float, catalog: list) -> list:
    """Кровати каталога в стиле (`room_profile.in_style`, порог профиля) → словари как в банке."""
    import room_profile as RP
    out = []
    for c in catalog:
        if 'кровать' not in c.roles or not RP.in_style(c.style, style, thr):
            continue
        d = c.dims
        out.append({'mid': c.mid, 'eid': c.eid, 'sid': f'{c.mid}:{c.eid}', 'name': c.name or '', 'w': d.get('w'), 'd': d.get('d'), 'h': d.get('h'),
                    'sleep_w': d.get('sleep_w'), 'style_score': (c.style or {}).get(style), '_style': style, '_src': 'catalog'})
    return out


def load_catalog() -> tuple[list, str]:
    """Кровати каталога с оценками стиля; база не читается — пустой список и причина (подбор останется на банке)."""
    try:
        import catalog_items as CI
        return CI.items('bedroom', roles=['кровать']), ''
    except Exception as e:  # noqa: BLE001 — отчёт о сбое, подбор продолжается на банке
        return [], repr(e)[:200]


def _thr() -> float:
    return float(json.load(open(os.path.join(HERE, 'rules', 'demo-swap.json'), encoding='utf-8'))['in_style_min'])


def bed_pool(style: str, bank: list, catalog: list, mesh_ok, defect, thr: float, ideal: float, used: set) -> list:
    """Готовые кровати стиля (и соседних, запасом) по близости к идеальной ширине; первыми — не занятые другими спальнями задания."""
    own = bank_pool(bank, style, 'кровать') + catalog_beds(style, thr, catalog)
    far = []
    for st in R.neighbour_styles(style):
        far += [dict(it, _borrowed=st) for it in bank_pool(bank, st, 'кровать') + catalog_beds(st, thr, catalog)]
    seen, rows = set(), []
    for it in own + far:
        sid = _sid(it)
        if sid in seen or not _bed_ok(it) or not _ready(it, mesh_ok, defect):
            continue
        seen.add(sid)
        rows.append(it)

    def key(it):
        return (abs(_sleep_w(it) - ideal), bool(it.get('_borrowed')), _sid(it) in used, it['_src'] != 'bank', -float(it.get('style_score') or 0))
    rows.sort(key=key)
    return rows


def ideal_bed(area_m2: float, short: float) -> float:
    for lo, sh, w in IDEAL_SIZES:
        if area_m2 >= lo and short >= sh:
            return float(w)
    return 120.0


def purposes_for(it: dict, area_m2: float, short: float) -> list:
    """Назначения кровати по её ширине и площади ядра: «пара» только в комнате NDSS для двоих; остальное — гостевая/одна."""
    w = _sleep_w(it)
    out = []
    if w >= 140 and area_m2 >= NDSS_DOUBLE[0] and short >= NDSS_DOUBLE[1]:
        out.append('couple')
    if 120 <= w <= 165:
        out.append('guest')
    if w <= 145:
        out.append('single')
    return out


def pick_role(role: str, bank: list, style: str, mesh_ok, defect, used: set):
    """Первый годный товар роли для стиля: свой стиль, потом соседние (`neighbour_styles`); незанятые раньше занятых."""
    for st in [style] + R.neighbour_styles(style):
        rows = [it for it in bank_pool(bank, st, role) if _ready(it, mesh_ok, defect)]
        rows = [it for it in rows if _sid(it) not in used] or rows
        if rows:
            return dict(rows[0], **({'_borrowed': st} if st != style else {}))
    return None


# ───────────────────────── солвер: кровать → проверка ─────────────────────────

def build_room(cand: dict, cfg: dict, hinge: str, purpose: str):
    from planner.models import Opening, Room
    ops = TD.TR_strip(TR.solver_openings(cand, cfg, hinge))
    return Room(width_cm=cand['w'], depth_cm=cand['d'], openings=[Opening(**o) for o in ops], radiators=[], room_type='bedroom',
                purpose=purpose), ops


def solve_kit(ad: dict, cand: dict, cfg: dict, kit: dict, purpose: str):
    """Набор на ядре, обе петли дверей → лучшая попытка {placements, hard, post, ops, room, meta} или None."""
    from planner.bedroom import solve_bedroom
    from planner.models import Item
    items = []
    for role, it in kit.items():
        for k in range(NIGHTSTANDS[purpose] if role == 'тумба прикроватная' else 1):
            items.append(Item(role=f'{role} {k + 1}' if k else role, w_cm=float(it['w']), d_cm=float(it['d']), h_cm=float(it['h'])))
    best = None
    for hinge in ('left', 'right'):
        room, ops = build_room(cand, cfg, hinge, purpose)
        lay = solve_bedroom(room, items, purpose)
        ps = lay.placements
        if not any(base_role(p.role) == 'кровать' for p in ps):
            continue
        hard = sorted(set(TD.hard_of(room, ps)) | {f"{v.code}|{','.join(sorted(v.roles))}" for v in lay.violations if v.severity.name == 'HARD'})
        post = TR.post_check(ad, cand, ps)
        rec = {'placements': ps, 'hard': hard, 'post': post, 'ops': ops, 'hinge': hinge,
               'score': (len(hard) + len(post['problems']), len(lay.skipped_optional)), 'skipped': list(lay.skipped_optional),
               'reason': list(lay.meta.get('reason') or []), 'floor_pct': lay.floor_used_pct, 'room': room}
        if best is None or rec['score'] < best['score']:
            best = rec
        if rec['score'][0] == 0:
            break
    return best


def public_item(p, it: dict, msid: str | None) -> dict:
    """Предмет варианта по РАЗРЕШЁННОМУ списку полей (нейтральное имя, ключ модели, размер)."""
    base = base_role(p.role)
    label = NEUTRAL.get(base, base)
    if base == 'кровать':
        label = f"{label} {round(_sleep_w(it))} cm"
    sku = {'name': label, 'msid': msid, 'w': it['w'], 'd': it['d'], 'h': it['h']}
    if base == 'кровать':
        sku['sleep_w'] = it.get('sleep_w')
    out = {'role': p.role, 'x': round(p.x, 1), 'y': round(p.y, 1), 'rot': int(p.rot or 0), 'w': it['w'], 'd': it['d'], 'h': it['h'],
           'dims_src': 'catalog', 'sku': sku, 'corner': False, 'corner_left': False, 'section': None}
    return {k: v for k, v in out.items() if k in ITEM_KEYS}


def furnish_style(ad: dict, cfg: dict, style: str, ctx: dict, used: set, deadline: float) -> tuple[dict | None, dict | None]:
    """Стиль в спальне → (вариант без id, None) или (None, {style, code, detail}): перебор кроватей по ширине, потом ядер."""
    tried, had_bed_on_any = 0, False
    for ci, cand in enumerate(ad['candidates']):
        area, short = cand['area_m2'], min(cand['w'], cand['d'])
        ideal = ideal_bed(area, short)
        beds = bed_pool(style, ctx['bank'], ctx['catalog'], ctx['mesh_ok'], ctx['defect'], ctx['thr'], ideal, used)
        had_bed_on_any = had_bed_on_any or bool(beds)
        others = {r: pick_role(r, ctx['bank'], style, ctx['mesh_ok'], ctx['defect'], used) for r in ROOM_ROLES[1:]}
        for bed in beds[:MAX_BEDS]:
            for purpose in purposes_for(bed, area, short):
                if time.time() > deadline:
                    return None, {'style': style, 'code': 'budget', 'detail': 'кончился бюджет комнаты'}
                tried += 1
                kit = {'кровать': bed, **{r: it for r, it in others.items() if it}}
                res = solve_kit(ad, cand, cfg, kit, purpose)
                if res and res['score'][0] == 0:
                    return variant_from(res, ad, cand, ci, style, bed, others, purpose, ctx), None
    if not had_bed_on_any:
        return None, {'style': style, 'code': 'no_products', 'detail': 'нет кровати с готовой моделью в стиле'}
    return None, {'style': style, 'code': 'bed_no_fit', 'detail': f'ни одна кровать не встала ({tried} попыток)'}


def variant_from(res: dict, ad: dict, cand: dict, ci: int, style: str, bed: dict, others: dict, purpose: str, ctx: dict) -> dict:
    x0, y0 = cand['rect'][0], cand['rect'][1]
    kit = {'кровать': bed, **{r: it for r, it in others.items() if it}}
    items, msid = [], ctx['msid']
    for p in res['placements']:
        it = kit[base_role(p.role)]
        items.append(public_item(p, it, msid(_sid(it))))
    placed = {base_role(p.role) for p in res['placements']}
    missing = [{'role': r, 'why': 'нет готовой модели' if r not in kit else 'нет места'} for r in ROOM_ROLES if r not in placed]
    return {'style': style, 'style_id': STYLE_ID.get(style, ''), 'purpose': purpose, 'core_index': ci, 'hinge': res['hinge'],
            'bed_sleep_w': round(_sleep_w(bed)), 'bed_borrowed_style': bed.get('_borrowed'),
            'items': items, 'missing_item': missing, 'fill_pct': res['floor_pct'], 'hard': [], 'post_ok': res['post']['ok'],
            'status': 'ok' if not any(m['role'] in R.lead_roles('bedroom') for m in missing) else 'partial',   # ведущие — профиль комнаты (кровать + тумба); шкаф и комод необязательны, их нехватка в `missing_item`
            'placements': TD._ps_json(res['placements'], x0, y0),
            'openings_core': res['ops'], '_sids': [_sid(k) for k in kit.values()]}


def furnish_room(trial_id: str, panel: dict, room: dict, rid: str, cfg: dict, ctx: dict) -> dict:
    t0 = time.time()
    rec = {'room_id': rid, 'src_id': room['id'], 'panel': panel['id'], 'panel_title': panel.get('title'), 'name': room.get('name'),
           'area_m2': room.get('areaM2'), 'variants': [], 'style_failures': [], 'flags': []}
    try:
        ad = adapt_room(panel, room, cfg)
    except BedroomRefusal as e:
        rec['outcome'] = refused(e.code, e.detail)
        return rec
    rec.update(contour=ad['contour'], control=ad['control'], flags=list(ad['flags']))
    deadline = time.time() + ROOM_BUDGET_S
    for st in STYLES:
        var, fail = furnish_style(ad, cfg, st, ctx, ctx['used'].setdefault(st, set()), deadline)
        if var is None:
            rec['style_failures'].append(fail)
            continue
        ctx['used'][st].update(var.pop('_sids'))
        var['id'] = R.variant_id(rid, var['style_id'])
        var['room_id'] = rid
        rec['variants'].append(var)
    if rec['variants']:
        cand = ad['candidates'][rec['variants'][0]['core_index']]
        rec['core'] = {'rect': cand['rect'], 'w': cand['w'], 'd': cand['d'], 'area_m2': cand['area_m2'], 'index': rec['variants'][0]['core_index'],
                       'residues': [{k: v for k, v in r.items() if k != 'poly'} for r in cand['residues']]}
        rec['openings_full'] = [{k: v for k, v in o.items()} for o in ad['ops']]
        rec['openings_core'] = rec['variants'][0]['openings_core']
    rec['outcome'] = outcome_of(rec)
    rec['seconds'] = round(time.time() - t0, 2)
    return rec


def refused(code: str, detail: str) -> dict:
    return {'state': 'refused', 'code': code, 'text': OUTCOME_TEXT.get(code, OUTCOME_DEFAULT), 'detail': detail, 'styles_ok': 0, 'styles_total': 0}


def outcome_of(rec: dict) -> dict:
    """Исход комнаты (ready/partial/refused) — по вариантам и причинам провала стилей; refused — только когда ни одного варианта."""
    ok = [v for v in rec['variants'] if v['status'] == 'ok']
    fails = rec['style_failures']
    total = len(rec['variants']) + len(fails)
    if not rec['variants']:
        codes = {f['code'] for f in fails}
        code = 'no_products' if codes <= {'no_products'} else ('bed_no_fit' if 'bed_no_fit' in codes else next(iter(sorted(codes)), 'solver_failed'))
        return refused(code, '; '.join(sorted({f['detail'] for f in fails})))
    base = {'styles_ok': len(ok), 'styles_total': total, 'failed_styles': sorted(f['style'] for f in fails)}
    if len(ok) == total and len(ok) >= MIN_STYLES_READY:
        return dict(base, state='ready', code=None, text=None, detail=None)
    return dict(base, state='partial', code='styles_or_items_missing', text=OUTCOME_TEXT['partial'],
                detail=f"готово стилей {len(ok)} из {total}; без товара: {sorted({m['role'] for v in rec['variants'] for m in v['missing_item']})}")


# ───────────────────────── задание целиком ─────────────────────────

def default_ctx() -> dict:
    """Живые данные (БД и индекс прода — только чтение): банк, каталог кроватей, сторож моделей."""
    import flat215_demo as FD
    gate = FD.room_mesh_gate('bedroom')
    bank = load_bank()
    catalog, why = load_catalog()
    return {'bank': bank, 'catalog': catalog, 'catalog_error': why, 'mesh_ok': gate, 'msid': gate.msid, 'defect': _defect_names(), 'thr': _thr(), 'used': {}}


def shop_tokens(ctx: dict) -> list:
    """Что нельзя выдать: имена магазинов, домены ссылок и названия товаров банка и каталога пробы."""
    bank = ctx.get('bank') or []
    toks = set()
    for r in bank:
        for it in list((r.get('items') or {}).values()) + [a for xs in (r.get('alternates') or {}).values() for a in xs or []]:
            if isinstance(it, dict):
                if it.get('shop'):
                    toks.add(str(it['shop']).lower())
                if it.get('name'):
                    toks.add(str(it['name']).lower())
    for c in ctx.get('catalog') or []:
        if getattr(c, 'shop', None):
            toks.add(str(c.shop).lower())
        if getattr(c, 'name', None):
            toks.add(str(c.name).lower())
    return sorted(t for t in toks if len(t) >= 3)


def assert_no_shop(obj, tokens: list) -> None:
    """Проверка очисткой ВЫВОДА: ни запрещённых полей, ни ссылок, ни названий магазинов/товаров во всём JSON. Найдено — `ShopLeak`."""
    def walk(v, path):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in BANNED_KEYS or (isinstance(k, str) and (k.endswith('_url') or k == 'href')):
                    raise ShopLeak(f'запрещённое поле {path}.{k}')
                walk(x, f'{path}.{k}')
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                walk(x, f'{path}[{i}]')
        elif isinstance(v, str):
            s = v.lower()
            if SHOP_LINKS.search(s) or any(re.search(r'(?<!\w)' + re.escape(t) + r'(?!\w)', s) for t in tokens):
                raise ShopLeak(f'значение в {path}: {v[:80]}')
    walk(obj, '$')


def build(trial_id: str, result: dict, ctx: dict | None = None) -> dict:
    """Все спальни задания → `bedrooms.json` (папка пробы). Исходы по комнатам, отказ задания — статус `refused`, не исключение."""
    t0 = time.time()
    OUT = TD.out_dir(trial_id)
    os.makedirs(OUT, exist_ok=True)
    cfg = TR.rules()
    job = {'trial_id': trial_id, 'version': 1, 'status': None, 'scale': (result.get('scale') or {}).get('status'), 'rooms': [], 'flags': [],
           'timings': {}}
    rooms = bedrooms_of(result)
    if not rooms:
        job.update(status='refused', refusal={'code': 'no_bedrooms'})
        _write(OUT, job)
        return job
    if job['scale'] == 'not_verified':                      # масштаб не подтверждён — никакой подгонки и вопросов агенту (Codex 09.11, TG 1377)
        for panel, room, rid in rooms:
            job['rooms'].append({'room_id': rid, 'src_id': room['id'], 'panel': panel['id'], 'panel_title': panel.get('title'), 'name': room.get('name'),
                                 'area_m2': room.get('areaM2'), 'variants': [], 'style_failures': [], 'flags': [],
                                 'outcome': refused('scale_unverified', 'масштаб плана не проверен')})
        job.update(status='refused', refusal={'code': 'scale_unverified'})
        _write(OUT, job)
        return job
    ctx = ctx or default_ctx()
    if ctx.get('catalog_error'):
        job['flags'].append('catalog_unavailable')
    for panel, room, rid in rooms:
        job['rooms'].append(furnish_room(trial_id, panel, room, rid, cfg, ctx))
    states = {r['outcome']['state'] for r in job['rooms']}
    job['status'] = 'refused' if states == {'refused'} else ('ok' if states == {'ready'} else 'partial')
    job['timings'] = {'total_s': round(time.time() - t0, 2), 'rooms_s': {r['room_id']: r.get('seconds') for r in job['rooms']}}
    assert_no_shop(job, shop_tokens(ctx))                    # проверка всего вывода; поймали — падаем, а не публикуем
    _write(OUT, job)
    return job


def _write(out: str, job: dict) -> None:
    TD._write(os.path.join(out, 'bedrooms.json'), job)


# ───────────────────────── куски для общей версии данных (trial_bundle) ─────────────────────────

def _page_openings(ops: list) -> list:
    """Проёмы ядра → формат `room.openings` страницы (служебное снято, проход без полотна — `opening`), как `trial_demo.core_room(render=True)`."""
    out = []
    for o in ops:
        o = {k: v for k, v in o.items() if not k.startswith('_')}
        if o.get('kind') == 'door' and not o.get('swing_cm'):
            o = {k: v for k, v in o.items() if k != 'swing_cm'}
            o['kind'] = 'opening'
        out.append(o)
    return out


def bundle_parts(job: dict, storey_by_panel: dict | None = None) -> dict:
    """`bedrooms.json` → куски контракта `contracts/trial-bundle.ts`: `rooms_geo`, `apartment_rooms`, `variants` (id уникальны
    на задание: комната — `bedroom-<n>`, вариант — `<комната>-<стиль>`). `storey_by_panel` — {id панели: этаж} (`trial_bundle.storeys`).
    Куски вливаются в сборку `trial_bundle.build` вместе с гостиной; в них нет ни магазинов, ни ссылок (см. `assert_no_shop`)."""
    storey_by_panel = storey_by_panel or {}
    rooms_geo, apartment, variants = {}, [], []
    for i, r in enumerate(job['rooms'], 1):
        rid = r['room_id']
        o = r['outcome']
        st = storey_by_panel.get(r['panel'])
        apartment.append({'id': rid, 'kind': 'bedroom', 'ordinal': i, 'titleEn': r.get('name') or 'Bedroom', 'areaM2': r.get('area_m2'),
                          'contentState': 'ready' if r['variants'] else 'soon', 'furniture_state': 'refused' if o['state'] == 'refused' else 'ready',
                          'furniture_code': o.get('code'), 'furniture_text': o.get('text'),
                          **({'storey': st} if st is not None else {})})
        if not r['variants']:
            continue
        core = r['core']
        geo = {'w': core['w'], 'd': core['d'], 'title': f"{r.get('name') or 'Bedroom'} {r.get('area_m2') or core['area_m2']:.1f} m²",
               'openings': _page_openings(r['openings_core']), 'radiators': [], **({'storey': st} if st is not None else {})}
        rooms_geo[rid] = geo
        for v in r['variants']:
            variants.append({'id': v['id'], 'room_id': rid, 'style': v['style'], 'style_id': v['style_id'], 'title': v['style'].capitalize(), 'purpose': v['purpose'],
                             'items': v['items'], 'decor': [], 'dims_unknown': [], 'missing_item': v['missing_item'], 'fill': [], 'fill_pct': v.get('fill_pct'),
                             'cams': [], 'pending': False, 'furniture_state': 'ready' if v['status'] == 'ok' else 'partial',
                             'room_size': {'w': core['w'], 'd': core['d']}})
    return {'rooms_geo': rooms_geo, 'apartment_rooms': apartment, 'variants': variants}


# ───────────────────────── А. замер покрытия ─────────────────────────

def bed_width_bucket(sleep_w: float) -> int | None:
    return next((b for b in BED_WIDTHS if abs(sleep_w - b) <= 5.0), None)


def coverage(ctx: dict | None = None) -> dict:
    """Живые готовые модели кроватей: ширина × стиль (и пустые ячейки для волны, без узких 90 см). Банк и каталог — отдельно."""
    ctx = ctx or default_ctx()
    mesh_ok, defect, thr, bank, catalog = ctx['mesh_ok'], ctx['defect'], ctx['thr'], ctx['bank'], ctx['catalog']
    t = {s: {b: {'bank': set(), 'catalog': set()} for b in BED_WIDTHS} for s in STYLES}
    for style in STYLES:
        rows = [('bank', it) for it in bank_pool(bank, style, 'кровать')] + [('catalog', it) for it in catalog_beds(style, thr, catalog)]
        for src, it in rows:
            b = bed_width_bucket(_sleep_w(it))
            if b is not None and _ready(it, mesh_ok, defect):
                t[style][b][src].add(_sid(it))
    table = {s: {str(b): {'bank': len(v['bank']), 'catalog': len(v['catalog'] | v['bank'])} for b, v in row.items()} for s, row in t.items()}
    empty = [{'style': s, 'sleep_w': b} for s in STYLES for b in BED_WIDTHS if not (t[s][b]['bank'] | t[s][b]['catalog'])]
    return {'table': table, 'empty_cells': empty, 'catalog_error': ctx.get('catalog_error') or ''}


# ───────────────────────── кадры сверху ─────────────────────────

ROLE_RGB = {'кровать': (205, 110, 100), 'тумба прикроватная': (150, 120, 90), 'шкаф': (120, 120, 160), 'комод': (140, 130, 100)}


def frames(job: dict, dst: str) -> list:
    os.makedirs(dst, exist_ok=False)
    for k, v in ROLE_RGB.items():
        TD.ROLE_RGB.setdefault(k, v)
    out = []
    for r in job['rooms']:
        if not r['variants']:
            continue
        scene = {'trial_id': r['room_id'], 'room': {'contour': r['contour']}, 'core': r['core'], 'openings_full': r['openings_full']}
        for v in r['variants']:
            p = os.path.join(dst, f"{r['room_id']}-{v['style_id']}.png")
            TD.frame_top(scene, {'placements': v['placements'], 'problems': [], 'hard': []}, p,
                         f"{v['style']} · {v['purpose']} · спальное {v['bed_sleep_w']}")
            out.append(p)
    return out


def _slot(label: str):
    ops = os.path.abspath(os.path.join(HERE, '..', 'ops'))
    if ops not in sys.path:
        sys.path.insert(0, ops)
    try:
        import heavy_slot as HS
    except ImportError:
        return contextlib.nullcontext()
    return HS.heavy_slot(label, min_gb=3.0, timeout=900.0, cmd=f'trial_bedroom {label}')


def _arg(args: list, name: str) -> str | None:
    if name in args:
        i = args.index(name)
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return None


def main() -> int:
    args = sys.argv[1:]
    if '--coverage' in args:
        args.remove('--coverage')
        out = _arg(args, '--out')
        with _slot('trial-bedroom-coverage'):
            c = coverage()
        print(json.dumps(c, ensure_ascii=False, indent=1))
        if out:
            os.makedirs(out, exist_ok=True)
            TD._write(os.path.join(out, 'coverage.json'), c)
        return 0
    fr = _arg(args, '--frames')
    if '--bench' in args:
        args.remove('--bench')
        trial_id, paths = args[0], args[1:]
        result = TR.from_bench_models([json.load(open(p, encoding='utf-8')) for p in paths])
    else:
        if len(args) != 2:
            print(__doc__)
            return 0
        trial_id, paths = args[0], args[1:]
        result = json.load(open(paths[0], encoding='utf-8'))
    with _slot(f'trial-bedroom-{trial_id}'):
        job = build(trial_id, result)
        if fr and job['rooms']:
            job['frames'] = frames(job, fr)
    brief = {'status': job['status'], 'refusal': job.get('refusal'), 'flags': job['flags'], 'timings': job['timings'],
             'rooms': [{'room': r['room_id'], 'src': r['src_id'], 'panel': r['panel_title'], 'name': r.get('name'), 'area_m2': r.get('area_m2'),
                        'state': r['outcome']['state'], 'code': r['outcome'].get('code'), 'text': r['outcome'].get('text'),
                        'styles': [(v['style'], v['bed_sleep_w'], v['purpose'], v['status'], bool(v.get('bed_borrowed_style'))) for v in r['variants']],
                        'style_failures': r['style_failures'], 'flags': r['flags'], 'seconds': r.get('seconds')} for r in job['rooms']]}
    print(json.dumps(brief, ensure_ascii=False, indent=1))
    return {'ok': 0, 'partial': 3}.get(job['status'], 2)


if __name__ == '__main__':
    sys.exit(main())
