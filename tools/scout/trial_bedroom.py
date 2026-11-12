#!/usr/bin/env python3
"""ПРОБА АГЕНТА: ВСЕ СПАЛЬНИ ЗАГРУЖЕННОГО ПЛАНА (план agent-trial-04-bedroom, задачи А–Д; T-20261109-22).

Вход — результат стенда (`contracts/trial.ts:floorplanResult`, см). Шаги на комнату:
  1. спальни всех панелей (`kind == 'bedroom'`, либо «Bedroom …» в составной подписи); id — `bedroom-<n>`, единые на задание;
  2. контур → ядро и проёмы теми же функциями, что у гостиной (`trial_room`): без окна комната не отказ (флаг), без входа — отказ;
  3. подбор: стиль → наборы и запас того же стиля из банка спальни (`sets-bedroom.json`, ТОЛЬКО товары; готовая расстановка чужой
     квартиры `layout` не читается, TG 1377) плюс кровати каталога в стиле; в подбор идёт только товар с годной живой моделью
     (`flat215_demo.room_mesh_gate('bedroom')`);
  4. ШАБЛОНЫ (владелец 09.11, TG 478/480; `templates`): назначение × ширина спального места (120–180; узкая 90–100 — назначение
     `single_narrow`, включается тем же выключателем, что у ночной сборки: `narrow_enabled`) из `rules/bedroom-composition.json`, по
     порядку от идеальной для площади ширины; шаблон, которому ядро меньше нормы (спальное + проход сбоку, длина + проход у изножья —
     `bed_need`), не перебирается (`too_small`); шаблон → товары стиля под него (кровать его ширины с моделью, тумбы) → нет товаров
     или не встали — следующий шаблон; ни один — комната ПУСТАЯ, исход `no_products` (код; надпись «нет подходящих товаров согласно
     действующим шаблонам» на нужном языке ставят сборщик и страница), остальные обставляются; комната меньше любого шаблона —
     `room_too_small` (то же состояние страницы, точная причина), не «не прочитана»;
  5. проверка солвером и по ПОЛНОМУ контуру (`planner.validate` + `trial_room.post_check`): мебель в контуре, дуги дверей обеих
     петель свободны, вход достижим;
  6. масштаб не подтверждён — отказ по всем комнатам, вопросов не задаём, мебель не подгоняем;
  7. выход `bedrooms.json` — только разрешённые поля (`ITEM_KEYS`, `SKU_KEYS`); проверка `assert_no_shop` по всему JSON: ни названий,
     ни ссылок магазинов. `bundle_parts(job)` — куски для общей версии данных задания (`trial_bundle`).

  ~/venvs/scout/bin/python trial_bedroom.py <trial_id> <floorplanResult.json> [--frames <папка>] [--brief <файл.json>]
  ~/venvs/scout/bin/python trial_bedroom.py --bench <trial_id> model-*.json [--frames <папка>] [--brief <файл.json>]
Кадры: сверху (каждый вариант; пустая комната — с кодом исхода) и от двери (меши). Исход комнаты — код (`ROOM_STATES`), не текст.
  ~/venvs/scout/bin/python trial_bedroom.py --coverage [--out <папка>]    # А: живые готовые кровати по ширине × стилю
Банк — `TRIAL_BEDROOM_SETS` (по умолчанию `tools/scout/sets-bedroom.json` этой копии). Код выхода: 0 — готово, 3 — частично, 2 — отказ.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import demo_room as R  # noqa: E402
import trial_demo as TD  # noqa: E402
import trial_room as TR  # noqa: E402
import trial_bundle as BU  # noqa: E402  — сборщик данных страницы: общая чистка товара и проёмы страницы

COMP = json.load(open(os.path.join(HERE, 'rules', 'bedroom-composition.json'), encoding='utf-8'))
STYLE_ID = {'сканди': 'scandi', 'современный': 'modern', 'минимализм': 'minimal', 'лофт': 'loft', 'неоклассика': 'neoclassic',
            'джапанди': 'japandi'}
STYLES = list(COMP.get('styles') or STYLE_ID)
BED_NAME = re.compile(r'\b(bed\s?room|bedroom|guest\s?room|box\s?room|nursery)\b', re.I)
NOT_BED = re.compile(r'en[\s-]?suite|bath|wc|shower|dressing|landing|closet|linen', re.I)
ROOM_ROLES = ('кровать', 'тумба прикроватная', 'шкаф', 'комод')
BED_WIDTHS = (120, 140, 160, 180)                  # ширины спального места пробы; узкие 90 — вне охвата (TG 1377)
NARROW_MAX_CM = 100.0                              # спальное/рама уже — «узкая», не ставим и не считаем (пока узкая выключена)
NARROW_PURPOSE = 'single_narrow'                   # узкая односпальная (UK single), шаблон солвера `bed_narrow_wall` (план bedroom-uk-single-01)
NARROW_WIDTHS = (90, 100)                          # её спальное место — `bedroom-composition.json` purposes.single_narrow sleep_w [90, 100]
IDEAL_SIZES = ((18.0, 300.0, 180), (11.5, 255.0, 160), (9.0, 0.0, 140), (0.0, 0.0, 120))   # площадь ядра, короткая сторона → идеальная ширина спального, см (NDSS)
NDSS_DOUBLE = (11.5, 255.0)                        # двуспальная «для пары» — NDSS 2015 (площадь м², короткая сторона см)
NIGHTSTANDS = {p: next((int(s.get('qty') or 1) for s in v['slots'] if s['role'] == 'тумба прикроватная'), 1)
               for p, v in COMP['purposes'].items() if 'slots' in v}          # тумб в шаблоне назначения (пара — 2, Н1)
TEMPLATE_PURPOSES = ('couple', 'guest', 'single')  # назначения шаблонов спальни; детская/кабинет — свои роли, не здесь
BACK_ROLES = ('кровать', 'шкаф', 'комод')          # спинкой к стене полного контура, не к стороне ядра над нишей
BACK_GAP_CM = 12.0                                 # задняя кромка дальше от стены — «стоит в воздухе»
BACK_MIN_SHARE = 0.8                               # доля точек кромки, что обязаны быть у стены
HINGES = ('left', 'right')                         # петля двери на плане неизвестна — пробуем обе; первый вариант комнаты фиксирует свою
MAX_CORES = 3                                   # ядер на стиль: дальше — те же кровати на всё меньшей площади
ROOM_BUDGET_S = 30.0                               # бюджет на комнату (чтобы плохой план не ел конвейер); вышло — лучшее, что есть
MIN_STYLES_READY = 2                               # меньше стилей — комната честно «частично» (владелец TG 1382: разные стили)
BED_LEN_MIN_CM = 195.0                             # самая короткая кровать (спальное 190 + рама) — нижняя граница длины для проверки «влезает»


def narrow_enabled() -> bool:
    """Узкая односпальная в пробе — ТЕМ ЖЕ выключателем, что у ночной сборки банка: пока у назначения `single_narrow` в
    `rules/bedroom-composition.json` стоит `empty` (NOT_IN_BANK: моделей узких кроватей нет, «ок» владельца на шаблон не дан; владелец
    TG 1377 — «односпальные отложены»), шаблонов 90–100 нет. Снимут `empty` — проба берёт их сама, без правки кода."""
    p = COMP['purposes'].get(NARROW_PURPOSE) or {}
    return 'slots' in p and not p.get('empty')


def template_purposes() -> tuple:
    return TEMPLATE_PURPOSES + ((NARROW_PURPOSE,) if narrow_enabled() else ())


def widths_of(purpose: str) -> tuple:
    """Ширины спального места шаблонов назначения: узкие — только у узкой (у `single` полоса 90–140, но её шаблоны — прежние 120/140)."""
    return NARROW_WIDTHS if purpose == NARROW_PURPOSE else BED_WIDTHS


def all_widths() -> tuple:
    return (NARROW_WIDTHS if narrow_enabled() else ()) + BED_WIDTHS


def _norm(key: str, default: float) -> float:
    """Число нормы спальни — из `services/planner-solver/rules/occupancy.json` (тот же `num`, что у солвера; одно число — одно место)."""
    from planner.bedroom_checks import num
    return num(key, default)


def bed_need(sleep_w: float, purpose: str, length: float | None = None) -> tuple[float, float]:
    """Наименьшая площадка под кровать шаблона по нормам солвера: поперёк — спальное место (нижняя граница рамы) + проход сбоку
    `bed_side_passage` (паре — с двух сторон, Н1), вдоль — длина рамы (`length`: самая короткая реальная рама ширины шаблона —
    `frames_len`; нет — `BED_LEN_MIN_CM`) + проход у изножья `bed_foot_min`. Необходимое условие, не достаточное: двери, окна и тумбы
    решает солвер."""
    side, foot = _norm('bed_side_passage', 75), _norm('bed_foot_min', 60)
    return float(sleep_w) + side * (2 if purpose == 'couple' else 1), (length or BED_LEN_MIN_CM) + foot


def _frame_d(it: dict) -> float:
    """Длина рамы кровати (`d`), неизвестна — `BED_LEN_MIN_CM`."""
    v = it.get('d')
    return float(v) if isinstance(v, (int, float)) and v > 0 else BED_LEN_MIN_CM


def frames_len(beds: list) -> float | None:
    """Самая короткая реальная рама среди кроватей ширины шаблона (T-20261110-20: у рам 120 каталога длина 210–226, а не 195) — длина
    для `bed_need`; кроватей нет — None (запасная `BED_LEN_MIN_CM`)."""
    return min((_frame_d(b) for b in beds), default=None)


def frame_need(it: dict, purpose: str) -> tuple[float, float]:
    """Площадка под РАМУ конкретной кровати: ширина рамы + проход сбоку (паре — с двух), длина рамы + проход у изножья. Рама шире
    `bed_frame_max` ядра — заведомо не встанет (T-20261110-20: в ядре 205 Кевия 150 и Сейлор 153 занимали оба места шаблона)."""
    side, foot = _norm('bed_side_passage', 75), _norm('bed_foot_min', 60)
    return float(it.get('w') or 0) + side * (2 if purpose == 'couple' else 1), _frame_d(it) + foot


def fits_core(need: tuple, cand: dict) -> bool:
    a, b = need
    return (a <= cand['w'] and b <= cand['d']) or (a <= cand['d'] and b <= cand['w'])


def bed_frame_max(cores: list) -> float:
    """Диагностика (спрос волны мешей): самая широкая рама кровати одному, что проходит по проходу сбоку хоть на одном ядре, см."""
    side, foot = _norm('bed_side_passage', 75), _norm('bed_foot_min', 60)
    return max([a - side for c in cores for a, b in ((c['w'], c['d']), (c['d'], c['w'])) if b >= BED_LEN_MIN_CM + foot] or [0.0])


def smallest_bed() -> dict:
    """«Влезает ли хоть какая-то кровать» в ядро (`trial_room.core_candidate`): самое узкое спальное место включённых шаблонов × длина."""
    return {'sofa': [float(min(all_widths())), BED_LEN_MIN_CM], 'bearer': [0.0, 0.0], 'tv_min_cm': 0.0}

# ИСХОД ПО КОМНАТЕ — КОДОМ, без готовых строк (владелец TG 486–488: проба на RU и EN; Codex lang п.2.4): надпись по коду подставляют
# сборщик (`trial_bundle.OUTCOME_TEXT`, обе локали) и страница. `state` — для страницы, `code` — точная причина (диагностика):
#   furnished — есть варианты; no_products — не подошёл ни один шаблон («нет подходящих товаров согласно действующим шаблонам»);
#   not_readable — комнату не прочитать по плану (отдельно от «нет товаров»); scale_unverified — масштаб не подтверждён;
#   failed — перебор не закончен (бюджет). `pending` — у сборщика: стадия ещё не отдала кусок.
ROOM_STATES = ('furnished', 'no_products', 'not_readable', 'scale_unverified', 'failed')
CODE_STATE = {'no_products': 'no_products', 'bed_no_fit': 'no_products', 'room_too_small': 'no_products',
              'scale_unverified': 'scale_unverified',
              **{c: 'not_readable' for c in ('contour_distorted', 'opening_ambiguous', 'no_core', 'opening_cut_by_core', 'no_entry')}}
# ЕДИНЫЙ РАЗРЕШЁННЫЙ СПИСОК ПОЛЕЙ ТОВАРА — ОДИН НА ВСЕ КОМНАТЫ, у сборщика данных страницы (`trial_bundle`, TG 1377, Codex 09.11):
# предмет и его `sku` — только `BU.ITEM_KEYS`/`BU.SKU_KEYS` (имена по роли, цвет, модель, размеры); ни `url`, `shop`, `img`, ни цены.
# Здесь не копируется: фильтр — `BU.public_item`, проверка всего JSON — `BU.assert_public` (утечка → `ShopLeak`, а не публикация).
ITEM_KEYS, SKU_KEYS = BU.ITEM_KEYS, BU.STAGE_SKU_KEYS          # + `sid` — ключ товара для сборщика (T-20261110-25)


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
    ours, amb, oflags = TR.openings_of(panel, room, cfg)
    if amb:
        raise BedroomRefusal('opening_ambiguous', '; '.join(f"{o['kind']} {o['widthCm']:.0f} см в {o['_d']:.0f} см от стены" for o in amb))
    flags = ([] if TR._light(ours, cfg)[0] else ['no_window']) + oflags
    try:
        fr = TR.ortho_frame(room['contour'], cfg)
        ops = [TR._place_opening(fr['poly'], o, fr['T'], cfg) for o in ours]
    except TR.Refusal as e:
        raise BedroomRefusal(e.code, e.detail) from e
    # ядро спальни — не уже самой узкой кровати шаблонов с проходом сбоку (120 + 75 = 195; общий порог ядра 200 — для гостиной)
    side = _norm('bed_side_passage', 75)
    core_min = min(float(cfg['core_min_side_cm']), min(all_widths()) + side)
    rects = [g.bounds for g in largest_free_rectangles(fr['poly'], min_side_cm=core_min, limit=24)]
    if not rects:
        x0, y0, x1, y1 = fr['poly'].bounds
        if min(x1 - x0, y1 - y0) < core_min:            # уже любой кровати с проходом — комната мала, а не «не прочитана»
            raise BedroomRefusal('room_too_small', f'комната {x1 - x0:.0f}×{y1 - y0:.0f}: нужна сторона ≥ {core_min:.0f} см '
                                                   f'(спальное {min(all_widths())} + проход {side:.0f})')
        raise BedroomRefusal('no_core', 'нет прямоугольного ядра')
    cands = [TR.core_candidate(fr['poly'], r, ops, smallest_bed(), cfg) for r in rects[:int(cfg['core_candidates'])]]
    ok = [c for c in cands if not c['reasons']]
    ok.sort(key=TR.core_rank)
    if ok and 'entry_via_niche' in ok[0]['flags']:
        flags.append('entry_via_niche')                # ядра без входа через нишу стоят раньше — раз первое с нишей, то и все
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


def _taken(variant: dict) -> set:
    """Товары готового варианта в виде ключей подбора (`_sid`): у артикула `sku.sid` первое «:» заменено на «_» (`public_item`) — берём
    и как есть (банк: «mid_eid»), и с «:» обратно (каталог: «mid:eid»), иначе взятая спальня не занимала бы свои товары."""
    out = set()
    for q in variant.get('items') or []:
        s = (q.get('sku') or {}).get('sid')
        if s:
            out.update({s, s.replace('_', ':', 1)})
    return out


def _sku(it: dict, mesh_ok=None) -> dict:
    """Артикул для сторожа моделей: `sid` и модель, которую грузит сцена (`msid` — `mesh_ok.msid`, как у живого демо). Без `msid`
    сторож отвечает «модели сцены нет» даже выложенной модели — так проба 09.11 не видела ни одной кровати."""
    sid = (_sid(it) or '').replace(':', '_', 1)
    f = getattr(mesh_ok, 'msid', None)
    return {'sid': sid, 'msid': f(sid) if f else sid}


def _defect_names() -> re.Pattern | None:
    md = (COMP.get('mesh_defect') or {}).get('names')
    return re.compile(md, re.I) if md else None


def _ready(it: dict | None, mesh_ok, defect) -> bool:
    """Годен в подбор: знаем размер, модель готова и выложена (`mesh_ok`), не брак по имени."""
    if not it or not _sid(it) or not (it.get('w') and it.get('d') and it.get('h')):
        return False
    if defect and defect.search(it.get('name') or ''):
        return False
    return not mesh_ok(_sku(it, mesh_ok))


def _sleep_w(it: dict) -> float:
    """Ширина спального места; неизвестна — по раме (рама шире места на типичные 5–15 см, запас для узких — рамой)."""
    v = it.get('sleep_w')
    return float(v) if isinstance(v, (int, float)) and v > 0 else float(it.get('w') or 0) - 10.0


def _bed_ok(it: dict) -> bool:
    lo = min(all_widths()) - 5.0 if narrow_enabled() else NARROW_MAX_CM      # узкая включена — её кровати (спальное 90–100) в подборе
    return _sleep_w(it) >= lo and it.get('w', 0) >= lo


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


def bed_pool(style: str, bank: list, catalog: list, mesh_ok, defect, thr: float, ideal: float, used: set, room_used: set = frozenset()) -> list:
    """Готовые кровати стиля (и соседних, запасом): первыми — не стоящие уже в этой комнате в другом стиле (`room_used`), дальше по
    близости к ширине шаблона, свои раньше соседних, не занятые другими спальнями задания раньше занятых."""
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
        return (_sid(it) in room_used, abs(_sleep_w(it) - ideal), bool(it.get('_borrowed')), _sid(it) in used, it['_src'] != 'bank', -float(it.get('style_score') or 0))
    rows.sort(key=key)
    return rows


def ideal_bed(area_m2: float, short: float) -> float:
    for lo, sh, w in IDEAL_SIZES:
        if area_m2 >= lo and short >= sh:
            return float(w)
    return 120.0


def couple_room(area_m2: float, short: float) -> bool:
    return area_m2 >= NDSS_DOUBLE[0] and short >= NDSS_DOUBLE[1]


def templates(area_m2: float, short: float) -> list:
    """ШАБЛОНЫ РАССТАНОВКИ СПАЛЬНИ (правило владельца 09.11, TG 478/480): назначение × ширина спального места. Состав — из
    `rules/bedroom-composition.json` → `purposes.<назначение>.slots` (полоса `sleep_w` кровати, число тумб), ширины — `widths_of`
    (`BED_WIDTHS`; узкие 90–100 — только у `single_narrow`, и только когда она включена — `narrow_enabled`, TG 1377). Обязательное в
    шаблоне — кровать и тумбы (ведущие роли профиля спальни), шкаф и комод — по месту.
    Порядок — от идеальной для ядра ширины (NDSS по площади и короткой стороне), при равной — шире; «пара» — только в комнате NDSS
    для двоих. → [{id, purpose, sleep_w, nightstands}]"""
    ideal = ideal_bed(area_m2, short)
    purposes = template_purposes()
    out = []
    for purpose in purposes:
        if purpose == 'couple' and not couple_room(area_m2, short):
            continue
        lo, hi = next(s['sleep_w'] for s in COMP['purposes'][purpose]['slots'] if s['role'] == 'кровать')
        out += [{'id': f'{purpose}-{w}', 'purpose': purpose, 'sleep_w': w, 'nightstands': NIGHTSTANDS[purpose]}
                for w in widths_of(purpose) if lo <= w <= hi]
    out.sort(key=lambda t: (abs(t['sleep_w'] - ideal), -t['sleep_w'], purposes.index(t['purpose'])))
    return out


def pick_role(role: str, bank: list, style: str, mesh_ok, defect, used: set, keep=None):
    """Первый годный товар роли для стиля: свой стиль, потом соседние (`neighbour_styles`); незанятые раньше занятых. `keep` — отбор
    товара (ступень тумб `slim_stands`)."""
    for st in [style] + R.neighbour_styles(style):
        rows = [it for it in bank_pool(bank, st, role) if _ready(it, mesh_ok, defect) and (keep is None or keep(it))]
        rows = [it for it in rows if _sid(it) not in used] or rows
        if rows:
            return dict(rows[0], **({'_borrowed': st} if st != style else {}))
    return None


def _ns_step_keep(step: dict):
    """Годится ли тумба в ступень лестницы пары (`bedroom-composition.json` purposes.couple.nightstand_steps): размер в полосе ступени
    (идеал × допуск профиля спальни, как `compose_bedroom.band_of`) и слово в имени (`name_re`, подвесные)."""
    import compose_common as CC
    import room_profile as RP
    band = CC.band_of(step, tuple(RP.load('bedroom').get('tolerance') or (0.8, 1.1)))
    name_re = re.compile(step['name_re'], re.I) if step.get('name_re') else None

    def keep(it: dict) -> bool:
        for k, (lo, hi) in band.items():
            v = float(it.get(k) or 0)
            if not lo <= v <= hi:
                return False
        return name_re is None or bool(name_re.search(it.get('name') or ''))
    return keep


def slim_stands(bank: list, style: str, mesh_ok, defect, used: set) -> list:
    """ЛЕСТНИЦА ТУМБ ПАРЫ в туре (T-20261112-95, владелец TG 910/929; та же, что у сборщика банка `Composer.nightstand_steps`): по ступеням
    правил — узкие, потом подвесные — первая годная тумба банка стиля (и соседних) → [тумба с `_ns_step`]. Ступени без товара нет в
    списке. Полок и бра в каталоге нет — их ступени нет и здесь."""
    out = []
    for step in (COMP['purposes'].get('couple') or {}).get('nightstand_steps') or []:
        it = pick_role('тумба прикроватная', bank, style, mesh_ok, defect, used, keep=_ns_step_keep(step))
        if it is not None and _sid(it) not in {_sid(x) for x in out}:
            out.append(dict(it, _ns_step=step['id']))
    return out


EXTRA_ROLES = ('шкаф', 'комод')                    # «по месту» (владелец 11.11, TG 992): шкаф главнее комода (вес решателя 3 против 2)
EXTRA_SIZES = 3                                    # разных размеров на роль: от самого широкого, что влезает в стену ядра, к узкому
EXTRA_TRIES = 4                                    # проб размеров на вариант сверх обязательных (`fit_extras`): 4 размера и без потолка
#                                                    перебор съедал бюджет большой спальни (T-20261111-06/2: Jsfx20 30 → 25 предметов)
EXTRA_SLICE_S = 4.0                                # потолок времени подбора размеров на вариант (страховка; обычно раньше — EXTRA_TRIES):
#                                                    вышел — лучшее найденное
EXTRA_GIVEUP = 4                                   # роль столько проб на ядре ломала шаблон «не у стены» и ни разу не встала — дальше
#                                                    её не пробуем (кроме первой пробы варианта): «Этажи» спальня 1 — каждый шкаф и
#                                                    комод «в воздухе» (`back_off_wall`), 25 проб впустую, ×2,4 времени


def role_sizes(role: str, bank: list, style: str, mesh_ok, defect, used: set, wall_max: float) -> list:
    """ШКАФ И КОМОД ПО МЕСТУ (владелец 11.11, TG 992: «шкаф в спальню ставится шаблоном, где влезает?»), как кровати по размеру:
    кандидаты роли — по одному на размер w×d×h, от самого широкого, что не длиннее самой длинной стены ядер (`wall_max`), к узкому.
    Сперва свой стиль (от широкого к узкому), за ним — товары соседних стилей УЖЕ самого узкого своего (запас на тесную стену,
    не подмена стиля); при равном размере — незанятые другими спальнями раньше занятых. Не больше EXTRA_SIZES. Встанет ли —
    решает солвер (`fit_extras`)."""
    out, seen, own_min = [], set(), None
    for k, st in enumerate([style] + R.neighbour_styles(style)):
        rows = [it for it in bank_pool(bank, st, role) if _ready(it, mesh_ok, defect) and float(it['w']) <= wall_max]
        rows.sort(key=lambda it: (-float(it['w']), -float(it['d']), _sid(it) in used))
        for it in rows:
            if k and own_min is not None and float(it['w']) >= own_min:
                continue
            key = size_key(it)
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(it, **({'_borrowed': st} if k else {})))
        if k == 0 and out:
            own_min = min(float(it['w']) for it in out)
    return _cap_sizes(out)


def _cap_sizes(rows: list) -> list:
    """Свои размеры — до EXTRA_SIZES − 1, последнее место — самому узкому из соседних стилей (если он есть): иначе при EXTRA_SIZES своих
    широких шкафах узкий запас не пробовался бы никогда."""
    own = [it for it in rows if not it.get('_borrowed')]
    far = sorted((it for it in rows if it.get('_borrowed')), key=lambda it: -float(it['w']))     # стабильно: внутри ширины — порядок стилей
    if not own:
        return far[:EXTRA_SIZES]
    if not far:
        return own[:EXTRA_SIZES]
    own = own[:EXTRA_SIZES - 1]
    n = EXTRA_SIZES - len(own)                     # свободные места — соседним стилям: от широкого, последнее — самому узкому
    return own + (far[:n - 1] + far[-1:] if len(far) > n else far)


def cramped(dims: dict, failed: dict) -> bool:
    """Набор не меньше того, где шкаф или комод уже не встал на этом ядре: те же роли есть, каждая не уже и не мельче (w, d) —
    теснее не станет просторнее, проба не нужна (как `dominated` у кроватей)."""
    return all(r in dims and dims[r][0] >= w and dims[r][1] >= d for r, (w, d) in failed.items())


def fit_extras(ad: dict, cand: dict, cfg: dict, core_kit: dict, extras: dict, tpl: dict, deadline: float) -> tuple[dict, dict]:
    """Шкаф и комод поверх выполненного шаблона (кровать + тумбы) — ПО МЕСТУ, от широкого к узкому (`extras` — `role_sizes`).
    Лучшее — больше вставших предметов, при равном — со шкафом (вес решателя 3 против 2), затем шире; солвер сам снимает
    необязательное без места (`skipped_optional`), поэтому в набор варианта идут только вставшие роли.
      1) самые широкие шкаф и комод вместе — всегда (как полный набор прежней лестницы `kit_ladder`); встали оба — готово;
      2) шкаф не встал — самый узкий шкаф при комоде, что встал (или самом узком): не встал — шире не пробуем, встал — шире его
         от широкого (`fit_role`); так же комод при шкафе, что встал; шкаф есть, а комода нет — самый узкий шкаф с самым узким
         комодом. Не больше EXTRA_TRIES проб и EXTRA_SLICE_S секунд (и не позже `deadline` стиля): вышло — лучшее найденное;
         набор не меньше того, где на этом ядре что-то уже не встало (у прошлого стиля тоже), не пробуется (`cramped`); роль,
         что на ядре EXTRA_GIVEUP проб ломала шаблон (проверка назвала её, например `back_off_wall`) и ни разу не встала, дальше
         не пробуется (`hopeless`);
      3) не встало ни одного (шаблон ломался набором, например шкаф не у стены) — КОМОД БЕЗ ШКАФА, затем шкаф без комода, тоже
         вне потолка проб и времени (пропуск — только `cramped` и `hopeless`): со шкафом комната не теряет предметы, что прежняя лестница
         ставила (T-20261111-06/2).
    → (расстановка, набор)."""
    purpose = tpl['purpose']
    wards, dressers = extras.get('шкаф') or [], extras.get('комод') or []
    want = bool(wards) + bool(dressers)
    stop = min(deadline, time.time() + EXTRA_SLICE_S)
    best = {'rank': (0, False, 0.0, 0.0), 'res': solve_kit(ad, cand, cfg, core_kit, purpose), 'kit': dict(core_kit)}
    tried, left = set(), [EXTRA_TRIES]
    # пробы ядра, где чего-то из шкафа и комода не встало, — общие для стилей комнаты (ядро у них одно); петли у первого стиля —
    # обе, дальше — одна его (`furnish_room`): не встало при обеих — не встанет и при одной
    core_key = (tuple(cand.get('rect') or ()), purpose)
    fails = ad.setdefault('extra_fail', {}).setdefault(core_key, [])
    # по роли на ядре: [сколько проб не встала, вставала ли хоть раз]
    stat = ad.setdefault('extra_stat', {}).setdefault(core_key, {r: [0, False] for r in EXTRA_ROLES})

    def hopeless(role):
        return stat[role][0] >= EXTRA_GIVEUP and not stat[role][1]

    def run(ward, dresser, must=False) -> None:
        if must != 'always':                            # безнадёжную на этом ядре роль не берём в пробу (`EXTRA_GIVEUP`)
            ward, dresser = (None if hopeless('шкаф') else ward), (None if hopeless('комод') else dresser)
        key = (size_key(ward) if ward else None, size_key(dresser) if dresser else None)
        if key == (None, None) or key in tried:
            return
        kit = dict(core_kit, **{r: it for r, it in (('шкаф', ward), ('комод', dresser)) if it})
        dims = {r: (float(it['w']), float(it['d'])) for r, it in kit.items()}
        if must != 'always' and any(cramped(dims, f) for f in fails):
            return
        if not must:
            if left[0] <= 0 or time.time() > stop:
                return
            left[0] -= 1
        tried.add(key)
        res = solve_kit(ad, cand, cfg, kit, purpose)
        ok = template_ok(res, tpl)
        got = {base_role(p.role) for p in res['placements']} & set(EXTRA_ROLES) if ok else set()
        lost = (set(kit) & set(EXTRA_ROLES)) - got
        if lost:
            fails.append(dims)
        # шаблон сломан, и проверка по контуру назвала роль (`back_off_wall` — решатель ставит её к стороне ядра, за которой не
        # стена): это про место, а не размер — уже не поможет. Не встала по месту (снята решателем) — не считаем: уже может встать
        named = {base_role(p.get('role') or '') for p in ((res or {}).get('post') or {}).get('problems') or []} & lost
        for r in set(kit) & set(EXTRA_ROLES):
            if r in got:
                stat[r][1] = True
            elif not ok and r in named:
                stat[r][0] += 1
        if not ok:
            return
        rank = (len(got), 'шкаф' in got) + tuple(float(kit[r]['w']) if r in got else 0.0 for r in EXTRA_ROLES)
        if rank > best['rank']:
            best.update(rank=rank, res=res, kit={r: it for r, it in kit.items() if r not in EXTRA_ROLES or r in got})

    def has(role):
        return role in best['kit']

    def fit_role(role, sizes, other):
        """Роль не встала самой широкой: сперва самая узкая (не встала — шире не встанут, проба одна), встала — шире её от широкого."""
        if not sizes or has(role) or hopeless(role):
            return
        kit = (lambda it: (it, other) if role == 'шкаф' else (other, it))
        run(*kit(sizes[-1]))
        if has(role):
            for it in sizes[1:-1]:
                run(*kit(it))
                if best['kit'].get(role) is it:
                    break

    if not want:
        return best['res'], best['kit']
    run(wards[0] if wards else None, dressers[0] if dressers else None, must='always')
    fit_role('шкаф', wards, best['kit'].get('комод') or (dressers[-1] if dressers else None))
    ward = best['kit'].get('шкаф')
    fit_role('комод', dressers, ward)
    if ward and dressers and not has('комод') and not hopeless('комод') and float(wards[-1]['w']) < float(ward['w']):
        run(wards[-1], dressers[-1])                    # шкаф встал, комод ни один — самый узкий шкаф с самым узким комодом
    if best['rank'][0] == 0:
        if dressers:
            run(None, dressers[0], must=True)
        if best['rank'][0] == 0 and wards:
            run(wards[-1], None, must=True)
    return best['res'], best['kit']


# ───────────────────────── солвер: кровать → проверка ─────────────────────────

def build_room(cand: dict, cfg: dict, hinge: str, purpose: str):
    from planner.models import Opening, Room
    ops = TD.TR_strip(TR.solver_openings(cand, cfg, hinge))
    return Room(width_cm=cand['w'], depth_cm=cand['d'], openings=[Opening(**o) for o in ops], radiators=[], room_type='bedroom',
                purpose=purpose), ops


def room_edge(ad: dict, cand: dict):
    """Стены комнаты так, как их видит ядро: граница «ядро ∪ его остатки» (`TR._residue_parts`). Щель уже `TR.SLIVER_CM` между стороной
    ядра и стеной контура — дрожь стены после выпрямления или пилястра (Этажи, спальня 1: выступ перегородки 20 см у нижнего угла, ядро
    330 при стене 350) — остатком не считается: у ядра там стена, и 3D-коробка комнаты (`rooms_geo` — ядро и пристройки-остатки) рисует
    стену там же. Без этого шкаф у правой стороны ядра — «в воздухе» (`back_off_wall`), хотя в 3D он у стены. Ниша глубже — остаток,
    граница — её дальняя стена (кадр D: щель 57 см за кроватью по-прежнему «в воздухе»). Память — `ad['edge']` по ядру."""
    memo = ad.setdefault('edge', {})
    key = tuple(cand['rect'])
    if key not in memo:
        from shapely.geometry import box
        from shapely.ops import unary_union
        g = unary_union([box(*cand['rect'])] + [r['poly'] for r in cand['residues'] if r.get('poly') is not None])
        memo[key] = g.boundary
    return memo[key]


def back_off_wall(ad: dict, cand: dict, placements: list) -> list:
    """Спинка кровати, шкафа, комода — у стены комнаты (`room_edge`: полный контур без щелей уже `TR.SLIVER_CM`). Ядро — прямоугольник: его
    сторона бывает «стеной» солвера и над нишей комнаты, тогда кровать стоит изголовьем в воздух (кадр D, спальня 2: щель 57 см за
    кроватью). Доля точек задней кромки дальше `BACK_GAP_CM` от стены → роль."""
    from shapely.geometry import Point
    x0, y0 = cand['rect'][0], cand['rect'][1]
    edge = room_edge(ad, cand)
    bad = []
    for p in placements:
        if base_role(p.role) not in BACK_ROLES or p.item is None:
            continue
        rad = math.radians(p.rot or 0)
        fx, fy = math.sin(rad), math.cos(rad)                # вперёд от спинки (как `planner.validate._back_pt`)
        ax, ay = fy, -fx                                     # вдоль спинки
        bx, by = x0 + p.x - fx * p.item.d_cm / 2, y0 + p.y - fy * p.item.d_cm / 2
        pts = [Point(bx + ax * p.item.w_cm * t, by + ay * p.item.w_cm * t) for t in (-0.45, -0.3, -0.15, 0.0, 0.15, 0.3, 0.45)]
        near = sum(1 for q in pts if edge.distance(q) <= BACK_GAP_CM)
        if near / len(pts) < BACK_MIN_SHARE:
            bad.append(p.role)
    return bad


def solve_kit(ad: dict, cand: dict, cfg: dict, kit: dict, purpose: str):
    """Набор на ядре, обе петли дверей → лучшая попытка {placements, hard, post, ops, room, meta} или None. Память `ad['memo']`: одинаковые
    размеры на том же ядре считаем один раз (у стилей и кроватей они часто совпадают — комната не упирается в бюджет)."""
    key = (cand['area_m2'], tuple(cand['rect']), purpose, ad.get('hinges', HINGES),
           tuple(sorted((r, it['w'], it['d'], it['h']) for r, it in kit.items())))
    if key in ad['memo']:
        return ad['memo'][key]
    res = _solve_kit(ad, cand, cfg, kit, purpose)
    ad['memo'][key] = res
    return res


def _solve_kit(ad: dict, cand: dict, cfg: dict, kit: dict, purpose: str):
    from planner.bedroom import solve_bedroom
    from planner.models import Item
    items = []
    for role, it in kit.items():
        for k in range(NIGHTSTANDS[purpose] if role == 'тумба прикроватная' else 1):
            items.append(Item(role=f'{role} {k + 1}' if k else role, w_cm=float(it['w']), d_cm=float(it['d']), h_cm=float(it['h'])))
    best = None
    for hinge in ad.get('hinges', HINGES):
        room, ops = build_room(cand, cfg, hinge, purpose)
        lay = solve_bedroom(room, items, purpose)
        ps = lay.placements
        if not any(base_role(p.role) == 'кровать' for p in ps):
            continue
        hard = sorted(set(TD.hard_of(room, ps)) | {f"{v.code}|{','.join(sorted(v.roles))}" for v in lay.violations if v.severity.name == 'HARD'})
        post = TR.post_check(ad, cand, ps)
        post = dict(post, problems=post['problems'] + [{'code': 'back_off_wall', 'role': r} for r in back_off_wall(ad, cand, ps)])
        post['ok'] = not post['problems']
        rec = {'placements': ps, 'hard': hard, 'post': post, 'ops': ops, 'hinge': hinge,
               'score': (len(hard) + len(post['problems']), len(lay.skipped_optional)), 'skipped': list(lay.skipped_optional),
               'reason': list(lay.meta.get('reason') or []), 'floor_pct': lay.floor_used_pct, 'room': room}
        if best is None or rec['score'] < best['score']:
            best = rec
        if rec['score'][0] == 0:
            break
    return best


def public_item(p, it: dict, msid: str | None) -> dict:
    """Предмет варианта через ОБЩИЙ фильтр сборщика (`BU.public_item`): роль, модель, размер; имена — нейтральные по роли на обеих локалях
    (`BU.neutral_names`; ширину спального места к имени кровати добавляет сборщик), цвет `colour_en` — только слова словарей цвета и
    материала (`BU.colour_en`: модель, бренд и магазин не проходят). Название товара и магазин в выход не идут; ключ товара `sid` —
    идёт (внутренний файл стадии): по нему сборщик берёт товар из каталога, как у /demo (`BU.catalog_goods`, T-20261110-25), и в данные
    страницы его не кладёт."""
    base = base_role(p.role)
    ru, en = BU.neutral_names(p.role)
    sku = {'name': ru, 'name_en': en, 'msid': msid, 'sid': (_sid(it) or '').replace(':', '_', 1) or None, 'w': it['w'], 'd': it['d'], 'h': it['h']}
    if base == 'кровать':
        sku['sleep_w'] = round(_sleep_w(it))
    c = BU.colour_en(it.get('name'), base)
    if c:
        sku['colour_en'] = c
    return BU.public_item({'role': p.role, 'x': round(p.x, 1), 'y': round(p.y, 1), 'rot': int(p.rot or 0), 'w': it['w'], 'd': it['d'],
                           'h': it['h'], 'dims_src': 'каталог', 'sku': sku, 'corner': False, 'corner_left': False, 'section': None},
                          BU.STAGE_SKU_KEYS)


def template_ok(res: dict | None, tpl: dict) -> bool:
    """Расстановка выполняет шаблон: без жёстких нарушений и проблем по контуру, кровать и ВСЕ тумбы шаблона стоят."""
    if not res or res['score'][0] != 0:
        return False
    roles = [base_role(p.role) for p in res['placements']]
    return 'кровать' in roles and roles.count('тумба прикроватная') >= tpl['nightstands']


def furnish_style(ad: dict, cfg: dict, style: str, ctx: dict, used: set, deadline: float) -> tuple[dict | None, dict | None]:
    """Стиль в спальне по ПРАВИЛУ ШАБЛОНОВ (владелец 09.11, TG 478/480): шаблоны по порядку (`templates`) → под шаблон подбираются
    товары стиля (кровать его ширины с готовой моделью, тумба; запас — соседние стили) → товаров нет или не встали ни на одном ядре —
    следующий шаблон. Первый выполненный шаблон — вариант; ни одного — (None, {style, code, templates}) с причиной по каждому шаблону:
    `too_small` (ни одно ядро меньше нормы кровати шаблона — `bed_need`; длина — по самой короткой готовой раме ширины, `frames_len`) /
    `no_bed` / `frame_too_wide` (кровати ширины есть, но рама с проходами не встаёт ни на одно ядро — `frame_need`; отсев ДО среза
    `BEDS_PER_TEMPLATE`, T-20261110-20) / `no_nightstand` (товаров нет) / `no_fit` (не встали) / `budget` (не дошли). Код стиля: что-то не встало (`no_fit` или `frame_too_wide`) — `bed_no_fit`; все шаблоны больше комнаты — `room_too_small`;
    иначе — `no_products` (подходящих по размеру товаров нет). Шкаф и комод — по месту (`fit_extras`: от самого широкого, что встаёт, к узкому)."""
    cores = ad['candidates'][:MAX_CORES]
    area = max(c['area_m2'] for c in cores)
    short = max(min(c['w'], c['d']) for c in cores)
    stand = pick_role('тумба прикроватная', ctx['bank'], style, ctx['mesh_ok'], ctx['defect'], used)
    slims = slim_stands(ctx['bank'], style, ctx['mesh_ok'], ctx['defect'], used) if stand else []
    wall_max = max(max(c['w'], c['d']) for c in cores)
    extras = {r: role_sizes(r, ctx['bank'], style, ctx['mesh_ok'], ctx['defect'], used, wall_max) for r in EXTRA_ROLES}
    log = []
    for tpl in templates(area, short):
        need = bed_need(tpl['sleep_w'], tpl['purpose'])
        if not any(fits_core(need, c) for c in cores):
            log.append({'template': tpl['id'], 'why': 'too_small'})
            continue
        pool = bed_pool(style, ctx['bank'], ctx['catalog'], ctx['mesh_ok'], ctx['defect'], ctx['thr'], tpl['sleep_w'], used,
                        ad.get('room_used', set()))
        width_beds = [b for b in pool if bed_width_bucket(_sleep_w(b)) == tpl['sleep_w']]
        # длина предпроверки — по самой короткой реальной раме этой ширины (запасная BED_LEN_MIN_CM): заведомо малые ядра — не решателю
        need = bed_need(tpl['sleep_w'], tpl['purpose'], frames_len(width_beds))
        if width_beds and not any(fits_core(need, c) for c in cores):
            log.append({'template': tpl['id'], 'why': 'too_small'})
            continue
        # рама шире ядра (с проходами) — до среза BEDS_PER_TEMPLATE, иначе широкие занимают оба места; среди годных порядок прежний.
        # Одна проба на размер w×d×h (T-20261110-20/3): цвета одной модели решатель считает одним (память `solve_kit`), а места
        # в срезе они занимали оба — в спальне 5,9 м² оба места брали Лайтси двух цветов, Лория дальше по списку не пробовалась
        fit = unique_sizes([b for b in width_beds if any(fits_core(need, c) and fits_core(frame_need(b, tpl['purpose']), c) for c in cores)])
        beds = fit[:BEDS_PER_TEMPLATE]
        if not beds or not stand:
            why = 'no_bed' if not width_beds else ('frame_too_wide' if not beds else 'no_nightstand')
            log.append({'template': tpl['id'], 'why': why})
            continue
        why, low_frames = 'no_fit', False
        for ci, cand in enumerate(cores):
            if tpl['purpose'] == 'couple' and not couple_room(cand['area_m2'], min(cand['w'], cand['d'])):
                continue
            if not fits_core(need, cand):
                continue
            tries, low_done = list(beds), False
            i = 0
            while i < len(tries):
                bed = tries[i]
                i += 1
                if not fits_core(frame_need(bed, tpl['purpose']), cand):     # рама не на это ядро — на другом из списка
                    continue
                if time.time() > deadline:
                    why = 'budget'
                    break
                core_kit = {'кровать': bed, 'тумба прикроватная': stand}     # обязательное шаблона: не встало — шкафы и комоды не пробуем
                ok = template_ok(solve_kit(ad, cand, cfg, core_kit, tpl['purpose']), tpl)
                if not ok and tpl['purpose'] == 'couple':
                    # лестница тумб пары (T-20261112-95): обе обычные не встали — узкие, потом подвесные, ДО следующего шаблона
                    # (кровать 140 — шаблон дальше по списку, как ступень 140 у сборщика банка)
                    for s in slims:
                        kit_s = dict(core_kit, **{'тумба прикроватная': s})
                        if template_ok(solve_kit(ad, cand, cfg, kit_s, tpl['purpose']), tpl):
                            core_kit, ok = kit_s, True
                            break
                if not ok:
                    # ВЫСОТА У ОКНА (T-20261110-20/3): решатель не ставит предмет выше подоконника у окна (`planner.bedroom._fits`);
                    # высокая рама не встала, а ТА ЖЕ рама ниже подоконника встаёт — мешала высота. Тогда высокие рамы не меньше
                    # этой не пробуем (`dominated`), прочие из очереди — как раньше и первыми (выбор там, где прежний подбор
                    # находил кровать, не меняется), за ними — низкие рамы этой ширины по прежнему порядку
                    if not low_done:
                        got = window_low_beds(ad, cand, cfg, core_kit, tpl, fit, tries)
                        if got is not None:
                            lim, low = got
                            low_done = True
                            tries = tries[:i] + [b for b in tries[i:] if not dominated(b, bed, lim)] + low
                            low_frames = True
                    continue
                res, kit = fit_extras(ad, cand, cfg, core_kit, extras, tpl, deadline)
                return dict(variant_from(res, ad, cand, ci, style, kit, extras, tpl, ctx), templates_tried=log), None
        # low_frames — мешала высота рамы у окна (проба `window_low_beds`), низкие тоже не встали: подсказка спросу на низкие кровати
        log.append({'template': tpl['id'], 'why': why, **({'low_frames': True} if low_frames else {})})
        if why == 'budget':
            break
    whys = {x['why'] for x in log}
    # «кровати есть, но рама не встала» (`frame_too_wide`) — для человека это «не встала», как `no_fit` (ведущий, T-20261110-20/1)
    code = 'budget' if 'budget' in whys else ('bed_no_fit' if whys & {'no_fit', 'frame_too_wide'} else
                                              ('room_too_small' if whys == {'too_small'} else 'no_products'))
    return None, {'style': style, 'code': code, 'templates': log}


BEDS_PER_TEMPLATE = 2                               # РАЗМЕРОВ кроватей одной ширины на шаблон: у соседних шанс, бюджет не съедается


def size_key(b: dict) -> tuple:
    """Размер так, как его видит решатель (ключ памяти `solve_kit` — точные w, d, h): округление склеило бы разные рамы."""
    return tuple(float(b.get(k) or 0) for k in ('w', 'd', 'h'))


def dominated(b: dict, failed: dict, lim: float) -> bool:
    """Рама выше предела у окна и не меньше по ширине и длине той, что не встала из-за высоты, — не встанет тоже."""
    return (float(b.get('h') or 0) > lim and float(b.get('w') or 0) >= float(failed.get('w') or 0)
            and float(b.get('d') or 0) >= float(failed.get('d') or 0))


def unique_sizes(beds: list) -> list:
    """Первая кровать каждого размера w×d×h (порядок прежний): одинаковые по размеру решатель ставит одинаково."""
    seen, out = set(), []
    for b in beds:
        k = size_key(b)
        if k not in seen:
            seen.add(k)
            out.append(b)
    return out


def window_limit(cand: dict, cfg: dict, purpose: str) -> float | None:
    """Высота, выше которой решатель не ставит предмет у окна этого ядра: max(подоконник, 80) (`planner.bedroom._fits`),
    по самому низкому окну. Окон нет — None."""
    room, _ = build_room(cand, cfg, HINGES[0], purpose)
    lims = [max(float(op.sill_cm or 0), 80.0) for op in room.openings if op.kind == 'window']
    return min(lims) if lims else None


def window_low_beds(ad: dict, cand: dict, cfg: dict, core_kit: dict, tpl: dict, fit: list, tried: list) -> tuple | None:
    """Высокая рама не встала: встаёт ли та же рама ниже подоконника? Да — мешала высота у окна → (предел, низкие рамы ≤ предела
    из годных по размеру `fit`, ещё не пробованные, не больше BEDS_PER_TEMPLATE). Нет (окна нет, рама и так низкая, или и низкая
    не встаёт — мешает не окно) → None, подбор как был. Проба — подсказка «мешала высота», не доказательство «только под
    окном»: поэтому прочие высокие рамы очереди не выбрасываются (см. `furnish_style`), снимаются только `dominated`."""
    bed = core_kit['кровать']
    lim = window_limit(cand, cfg, tpl['purpose'])
    if lim is None or float(bed.get('h') or 0) <= lim:
        return None
    probe = dict(core_kit, кровать=dict(bed, h=lim))
    if not template_ok(solve_kit(ad, cand, cfg, probe, tpl['purpose']), tpl):
        return None
    seen = {size_key(b) for b in tried}
    return lim, [b for b in fit if float(b.get('h') or 0) <= lim and size_key(b) not in seen][:BEDS_PER_TEMPLATE]


def variant_from(res: dict, ad: dict, cand: dict, ci: int, style: str, kit: dict, extras: dict, tpl: dict, ctx: dict) -> dict:
    """Вариант из расстановки набора `kit` (кровать, тумба и вставшие по месту шкаф/комод). Роли нет — `no_model`, если у стиля нет
    годного товара роли (`extras` пуст), иначе `no_space` (ни один размер не встал)."""
    x0, y0 = cand['rect'][0], cand['rect'][1]
    bed = kit['кровать']
    items, msid = [], ctx['msid']
    for p in res['placements']:
        it = kit[base_role(p.role)]
        items.append(public_item(p, it, msid(_sid(it))))
    placed = {base_role(p.role) for p in res['placements']}
    have = set(kit) | {r for r, xs in (extras or {}).items() if xs}
    missing = [{'role': r, 'why': 'no_model' if r not in have else 'no_space'} for r in ROOM_ROLES if r not in placed]
    return {'style': style, 'style_id': STYLE_ID.get(style, ''), 'purpose': tpl['purpose'], 'template': tpl['id'], 'core_index': ci,
            'hinge': res['hinge'], 'bed_sleep_w': round(_sleep_w(bed)), 'bed_borrowed_style': bed.get('_borrowed'),
            **({'ns_step': kit['тумба прикроватная']['_ns_step']} if (kit.get('тумба прикроватная') or {}).get('_ns_step') else {}),
            'items': items, 'missing_item': missing, 'fill_pct': res['floor_pct'], 'hard': [], 'post_ok': res['post']['ok'],
            'status': 'ok',                               # шаблон выполнен (кровать и тумбы); шкаф и комод необязательны — в `missing_item`
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
    rec.update(contour=ad['contour'], control=ad['control'], flags=list(ad['flags']),
               bed_frame_max_cm=round(bed_frame_max(ad['candidates'][:MAX_CORES])))
    deadline = time.time() + ROOM_BUDGET_S
    ad['memo'], ad['room_used'] = {}, set()
    for i, st in enumerate(STYLES):
        share = time.time() + max(deadline - time.time(), 0.0) / (len(STYLES) - i)   # доля бюджета: тяжёлый стиль не съедает бюджет остальных
        var, fail = furnish_style(ad, cfg, st, ctx, ctx['used'].setdefault(st, set()), share)
        if var is None:
            rec['style_failures'].append(fail)
            continue
        sids = var.pop('_sids')
        ctx['used'][st].update(sids)
        ad['room_used'].add(sids[0])                     # кровать этой комнаты: другим стилям — сперва другие кровати (разные стили — разные товары)
        if not rec['variants']:
            # У страницы у комнаты ОДНА геометрия (`rooms_geo`: ядро и проёмы с петлёй) — все стили комнаты на ядре и петле первого варианта
            ad['core_fixed'] = ad['candidates'][var['core_index']]
            ad['candidates'], ad['hinges'] = [ad['core_fixed']], (var['hinge'],)
        var['core_index'] = 0
        var['id'] = R.variant_id(rid, var['style_id'])
        var['room_id'] = rid
        rec['variants'].append(var)
    cand = ad.get('core_fixed') or ad['candidates'][0]                # пустая комната — первое ядро (для кадра и диагностики)
    ci = 0
    rec['core'] = {'rect': cand['rect'], 'w': cand['w'], 'd': cand['d'], 'area_m2': cand['area_m2'], 'index': ci,
                   'residues': [{k: v for k, v in r.items() if k != 'poly'} for r in cand['residues']]}
    rec['openings_full'] = [{k: v for k, v in o.items()} for o in ad['ops']]
    # проёмы ядра для страницы: у обставленной — петля вариантов; у пустой — те же стыки (комната показывается пустой, с надписью по коду)
    rec['openings_core'] = rec['variants'][0]['openings_core'] if rec['variants'] else TD.TR_strip(TR.solver_openings(cand, cfg, HINGES[0]))
    rec['outcome'] = outcome_of(rec)
    rec['seconds'] = round(time.time() - t0, 2)
    return rec


def refused(code: str, detail: str = '') -> dict:
    """Комната без мебели: `state` по коду (`CODE_STATE`; неизвестный — `failed`), `detail` — только диагностика, на страницу не идёт."""
    return {'state': CODE_STATE.get(code, 'failed'), 'code': code, 'detail': detail, 'styles_ok': 0, 'styles_total': 0}


def outcome_of(rec: dict) -> dict:
    """Исход комнаты кодом: есть хоть один вариант (шаблон выполнен в каком-то стиле) — `furnished`; ни одного — по причинам стилей:
    товаров нет или не встали ни в одном шаблоне → `no_products` (владелец 09.11: комната пустая, остальные обставляются)."""
    fails = rec['style_failures']
    total = len(rec['variants']) + len(fails)
    if not rec['variants']:
        codes = {f['code'] for f in fails}
        code = next((c for c, ok in (('room_too_small', {'room_too_small'}), ('no_products', {'no_products', 'room_too_small'}),
                                     ('bed_no_fit', {'no_products', 'room_too_small', 'bed_no_fit'})) if codes and codes <= ok), 'budget')
        return dict(refused(code), styles_total=total)
    few = len(rec['variants']) < MIN_STYLES_READY
    return {'state': 'furnished', 'code': 'few_styles' if few else ('styles_missing' if fails else None), 'detail': None,
            'styles_ok': len(rec['variants']), 'styles_total': total, 'failed_styles': sorted(f['style'] for f in fails)}


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
    neutral = {n.lower() for r in ROOM_ROLES for n in BU.neutral_names(r)}       # наши же нейтральные имена — не утечка
    return sorted(t for t in toks if len(t) >= 3 and t not in neutral)


def assert_no_shop(obj, tokens: list) -> None:
    """Проверка очисткой ВЫВОДА — общая проверка сборщика (`BU.assert_public`: запрещённые поля, ссылки, названия магазинов/товаров во всём
    JSON). Найдено — `ShopLeak`: стадия падает, а не публикует."""
    try:
        BU.assert_public(obj, tokens)
    except BU.BundleRefused as e:
        raise ShopLeak(f'{e.code}: {e.detail}') from e


APPROX_CONSENT = 'approx_consent'                            # = trial_bundle.APPROX_CONSENT


def _scale_refused(panel: dict, room: dict, rid: str) -> dict:
    return {'room_id': rid, 'src_id': room['id'], 'panel': panel['id'], 'panel_title': panel.get('title'), 'name': room.get('name'),
            'area_m2': room.get('areaM2'), 'variants': [], 'style_failures': [], 'flags': [],
            'outcome': refused('scale_unverified', 'масштаб плана не проверен')}


USER_DIMS = TR.USER_DIMS                                     # размер дал агент правкой комнаты — согласие без «примерно»


def room_fp(room: dict) -> str:
    """Отпечаток того, от чего зависит мебель спальни (имя, вид, контур, площадь, флаги; id плана): совпал — прежняя запись годна."""
    def num(v):   # число — одним видом: результат с сервера проходит JSON-сериализацию JS (433.0 → 433), а значение то же
        if isinstance(v, bool) or v is None or isinstance(v, str):
            return v
        if isinstance(v, (int, float)):
            return round(float(v), 3)
        if isinstance(v, dict):
            return {k: num(x) for k, x in v.items()}
        return [num(x) for x in v]
    key = {k: num(room.get(k)) for k in ('id', 'name', 'kind', 'contour', 'areaM2', 'flags')}
    return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _reusable(prev: dict | None, panel: dict, room: dict, dirty: set) -> dict | None:
    """Запись прежней стадии для неправленой спальни (правка комнаты, T-20261110-36): та же комната по (панель, id плана) и тот же
    отпечаток; у записей до отпечатков — те же имя и площадь. Правленая (`dirty`) или изменившаяся — None (пересобрать)."""
    if not prev or (panel['id'], str(room['id'])) in dirty:
        return None
    old = next((r for r in prev.get('rooms') or [] if r.get('panel') == panel['id'] and str(r.get('src_id')) == str(room['id'])), None)
    if not old or not old.get('variants') and (old.get('outcome') or {}).get('state') == 'scale_unverified':
        return None
    same = old['_fp'] == room_fp(room) if old.get('_fp') else (old.get('name') == room.get('name') and old.get('area_m2') == room.get('areaM2'))
    return old if same else None


def _relabel(old: dict, rid: str) -> dict:
    """Прежняя запись под нынешним id страницы (`bedroom-<n>` сдвигается, если правка сменила вид другой комнаты)."""
    rec = json.loads(json.dumps(old))
    rec['room_id'] = rid
    for v in rec.get('variants') or []:
        v['room_id'], v['id'] = rid, R.variant_id(rid, v['style_id'])
    rec['reused'] = True
    return rec


def build(trial_id: str, result: dict, ctx: dict | None = None, reuse: dict | None = None) -> dict:
    """Все спальни задания → `bedrooms.json` (папка пробы). Исходы по комнатам, отказ задания — статус `refused`, не исключение.
    `reuse` = {'prev': прежний `bedrooms.json`, 'dirty': {(панель, id плана)}} — правка комнаты: неправленые спальни берутся из прежней
    записи как есть (та же мебель, ≤ 2 мин на правку), заново обставляются только правленые; их товары не повторяют товары взятых."""
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
    # масштаб не подтверждён — никакой подгонки и вопросов агенту (Codex 09.11, TG 1377); исключение — комнаты, где агент нажал
    # «Обустроить» (флаг `approx_consent` от пересборки, Р1): обставляем «как есть», исход несёт флаг — страница пишет «размеры примерные»;
    # размер, данный агентом в правке комнаты (`user_dims`), — тоже согласие, но не «примерно»
    unverified = job['scale'] == 'not_verified'
    consent = {id(room) for _, room, _ in rooms if {APPROX_CONSENT, USER_DIMS} & set(room.get('flags') or [])} if unverified else set()
    if unverified and not consent:
        for panel, room, rid in rooms:
            job['rooms'].append(_scale_refused(panel, room, rid))
        job.update(status='refused', refusal={'code': 'scale_unverified'})
        _write(OUT, job)
        return job
    prev, dirty = (reuse or {}).get('prev'), set((reuse or {}).get('dirty') or ())
    plan = []                                                # (панель, комната, id, прежняя запись | None)
    for panel, room, rid in rooms:
        plan.append((panel, room, rid, None if unverified and id(room) not in consent else _reusable(prev, panel, room, dirty)))
    fresh = [p for p in plan if p[3] is None and not (unverified and id(p[1]) not in consent)]
    ctx = ctx or (default_ctx() if fresh else {'used': {}})  # всё взято из прежней записи — живые данные не нужны
    if ctx.get('catalog_error'):
        job['flags'].append('catalog_unavailable')
    for *_, old in plan:                                     # товары взятых спален — заняты: правленая не повторит их тумбы и комод
        for v in (old or {}).get('variants') or []:          # ключ — имя стиля (`STYLES`, как у `build_one`), не `style_id`
            ctx['used'].setdefault(v['style'], set()).update(_taken(v))
    for panel, room, rid, old in plan:
        if unverified and id(room) not in consent:
            job['rooms'].append(_scale_refused(panel, room, rid))
            continue
        if old is not None:
            job['rooms'].append(_relabel(old, rid))
            continue
        rec = furnish_room(trial_id, panel, room, rid, cfg, ctx)
        if unverified and USER_DIMS not in (room.get('flags') or []):
            rec['flags'] = list(rec.get('flags') or []) + [APPROX_CONSENT]
        rec['_fp'] = room_fp(room)
        job['rooms'].append(rec)
    states = {r['outcome']['state'] for r in job['rooms']}
    job['status'] = 'ok' if states == {'furnished'} else ('partial' if 'furnished' in states else 'refused')
    job['timings'] = {'total_s': round(time.time() - t0, 2), 'rooms_s': {r['room_id']: r.get('seconds') for r in job['rooms']},
                      'reused': [r['room_id'] for r in job['rooms'] if r.get('reused')]}
    if fresh:
        assert_no_shop(job, shop_tokens(ctx))                # проверка всего вывода; поймали — падаем, а не публикуем (взятые проверены при сборке)
    _write(OUT, job)
    return job


def _write(out: str, job: dict) -> None:
    TD._write(os.path.join(out, 'bedrooms.json'), job)


# ───────────────────────── куски для общей версии данных (trial_bundle) ─────────────────────────

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
        # комната куска находится сборщиком по (`panel`, `src_id`) (`trial_bundle._map_parts`); подписи на двух языках он строит сам
        # из `name_src` (`room_titles`); состояние для машины сборщика — ready/refused, код страницы — `furniture_outcome`
        apartment.append({'id': rid, 'panel': r['panel'], 'src_id': r['src_id'], 'kind': 'bedroom', 'ordinal': i, 'name_src': r.get('name') or '',
                          'areaM2': r.get('area_m2'), 'contentState': 'ready' if r['variants'] else 'soon',
                          'furniture_state': 'ready' if o['state'] == 'furnished' else 'refused', 'furniture_outcome': o['state'],
                          'furniture_code': o.get('code'), **({'storey': st} if st is not None else {})})
        if r.get('core') and r.get('openings_core') is not None:      # прочитанная комната — геометрия и без мебели (пустая, с надписью)
            core = r['core']
            rooms_geo[rid] = {'w': core['w'], 'd': core['d'], 'openings': BU._openings_for_page(r['openings_core']), 'radiators': [],
                              **({'storey': st} if st is not None else {})}
        if not r['variants']:
            continue
        core = r['core']
        for v in r['variants']:
            variants.append({'id': v['id'], 'room_id': rid, 'style': v['style'], 'style_id': v['style_id'], 'title': v['style'].capitalize(), 'purpose': v['purpose'],
                             'items': v['items'], 'decor': [], 'dims_unknown': [], 'missing_item': v['missing_item'], 'fill': [], 'fill_pct': v.get('fill_pct'),
                             'cams': [], 'pending': False, 'furniture_state': 'ready' if v['status'] == 'ok' else 'partial',
                             'room_size': {'w': core['w'], 'd': core['d']}})
    return {'rooms_geo': rooms_geo, 'apartment_rooms': apartment, 'variants': variants}


# ───────────────────────── А. замер покрытия ─────────────────────────

def bed_width_bucket(sleep_w: float) -> int | None:
    return next((b for b in all_widths() if abs(sleep_w - b) <= 5.0), None)


def coverage(ctx: dict | None = None) -> dict:
    """Живые готовые модели кроватей: ширина × стиль (и пустые ячейки для волны, без узких 90 см). Банк и каталог — отдельно."""
    ctx = ctx or default_ctx()
    mesh_ok, defect, thr, bank, catalog = ctx['mesh_ok'], ctx['defect'], ctx['thr'], ctx['bank'], ctx['catalog']
    widths = all_widths()                              # узкие — только когда включены (`narrow_enabled`)
    t = {s: {b: {'bank': set(), 'catalog': set()} for b in widths} for s in STYLES}
    for style in STYLES:
        rows = [('bank', it) for it in bank_pool(bank, style, 'кровать')] + [('catalog', it) for it in catalog_beds(style, thr, catalog)]
        for src, it in rows:
            b = bed_width_bucket(_sleep_w(it))
            if b is not None and _ready(it, mesh_ok, defect):
                t[style][b][src].add(_sid(it))
    table = {s: {str(b): {'bank': len(v['bank']), 'catalog': len(v['catalog'] | v['bank'])} for b, v in row.items()} for s, row in t.items()}
    empty = [{'style': s, 'sleep_w': b} for s in STYLES for b in widths if not (t[s][b]['bank'] | t[s][b]['catalog'])]
    return {'table': table, 'empty_cells': empty, 'catalog_error': ctx.get('catalog_error') or ''}


# ───────────────────────── кадры сверху ─────────────────────────

ROLE_RGB = {'кровать': (205, 110, 100), 'тумба прикроватная': (150, 120, 90), 'шкаф': (120, 120, 160), 'комод': (140, 130, 100)}


def frame_door(r: dict, v: dict, path: str) -> dict:
    """Вид от двери (кадр сцены из мешей, как `trial_demo.frame_entry` гостиной): камера у входной двери ядра, модели — по `msid` предметов."""
    import draft_render as DR
    from planner.models import Item, Placement
    ops = v['openings_core']
    core = {'w': r['core']['w'], 'd': r['core']['d']}
    cam = TD.entry_cam({'core': core}, ops)
    # дверь, у которой стоит камера, — проёмом без полотна: открытое полотно у самой камеры закрывало треть кадра (D, спальня 2; E, спальня 1)
    doors = sorted((o for o in ops if o['kind'] == 'door'), key=lambda o: (not o.get('is_entrance'), not o.get('swing_cm'), -o['width_cm']))
    at = doors[0] if doors else None
    croom = TD.core_room(core, [dict(o, swing_cm=0) if o is at else o for o in ops], render=True)
    ps = [Placement(role=q['role'], x=q['x'], y=q['y'], rot=q['rot'], elev_cm=q.get('elev') or 0,
                    item=Item(role=q['role'], w_cm=q['w'], d_cm=q['d'], h_cm=q.get('h') or 60, corner=q['corner'],
                              corner_left=q['corner_left'], corner_section_cm=q.get('section') or 95)) for q in v['items'] if q.get('w')]
    sid = {q['role']: q['sku']['msid'] for q in v['items'] if (q.get('sku') or {}).get('msid')}
    img, diag = DR.scene3d_frame(croom, ps, cam, sid, {})
    img.save(path, quality=88)
    return diag


def frames(job: dict, dst: str) -> dict:
    """Кадры всех спален задания: сверху по полному контуру (каждый вариант; комната без мебели — пустая, с кодом исхода) и от двери."""
    os.makedirs(dst, exist_ok=False)
    for k, v in ROLE_RGB.items():
        TD.ROLE_RGB.setdefault(k, v)
    out = {'top': [], 'door': [], 'clay': {}}
    for r in job['rooms']:
        if not r.get('contour'):
            continue                                       # комнату не прочитать — рисовать нечего (код исхода в отчёте)
        core = r.get('core') or {'rect': [0, 0, 0, 0], 'w': 0, 'd': 0}
        scene = {'trial_id': r['room_id'], 'room': {'contour': r['contour']}, 'core': core, 'openings_full': r.get('openings_full') or []}
        if not r['variants']:
            p = os.path.join(dst, f"{r['room_id']}-top-empty.png")
            TD.frame_top(scene, {'placements': [], 'problems': [], 'hard': []}, p, f"{r.get('name')} · {r['outcome']['state']} ({r['outcome']['code']})")
            out['top'].append(p)
            continue
        for v in r['variants']:
            p = os.path.join(dst, f"{r['room_id']}-top-{v['style_id']}.png")
            TD.frame_top(scene, {'placements': v['placements'], 'problems': [], 'hard': []}, p,
                         f"{r.get('name')} · {v['style']} · шаблон {v['template']}")
            out['top'].append(p)
            p = os.path.join(dst, f"{r['room_id']}-door-{v['style_id']}.jpg")
            diag = frame_door(r, v, p)
            out['door'].append(p)
            out['clay'][f"{r['room_id']}-{v['style_id']}"] = diag.get('clay') or []
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
    brief_out = _arg(args, '--brief')
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
                        'state': r['outcome']['state'], 'code': r['outcome'].get('code'), 'detail': r['outcome'].get('detail'),
                        'styles': [(v['style'], v['template'], v['bed_sleep_w'], [m['role'] for m in v['missing_item']], bool(v.get('bed_borrowed_style')))
                                   for v in r['variants']],
                        'style_failures': r['style_failures'], 'flags': r['flags'], 'bed_frame_max_cm': r.get('bed_frame_max_cm'),
                        'seconds': r.get('seconds')} for r in job['rooms']],
             'frames': job.get('frames')}
    print(json.dumps(brief, ensure_ascii=False, indent=1))
    if brief_out:
        TD._write(brief_out, brief)
    return {'ok': 0, 'partial': 3}.get(job['status'], 2)


if __name__ == '__main__':
    sys.exit(main())
