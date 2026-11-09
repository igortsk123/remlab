#!/usr/bin/env python3
"""ПРОБА АГЕНТА: ГОСТИНАЯ С МЕБЕЛЬЮ НА ЗАГРУЖЕННОМУ ПЛАНЕ — обёртка над адаптером и солвером
(план agent-trial-03-living, L-B; T-20261109-12; поправки Codex 09.11 главнее «Решения» плана).

Отдельная от `flat215_demo.py` обёртка с ЯВНЫМ входом и своей папкой — путь живого демо не меняется (общие функции только
импортируются: выбор наборов стиля `pick_banks`, индекс моделей прода):
  1. адаптер `trial_room.adapt` → ядро гостиной (прямоугольник), проёмы и стыки ядра; отказ — честный код причины;
  2. полоса банка — по площади ядра; по ОДНОМУ набору на стиль (6 стилей) — `flat215_demo.pick_banks`;
  3. ОДНА геометрия на все стили (Codex 09.11): «набор-геометрия» из самых крупных реальных товаров каждой роли среди
     шести стилей (консервативно: что влезло крупным — влезет и мельче) → ОДИН прогон солвера на ядро;
  4. проверка по ПОЛНОМУ контуру (`trial_room.post_check`): не прошла — вторая петля дверей, потом следующее ядро, пока
     укладываемся в бюджет 60 с; иначе честный частичный результат (`partial` с перечнем проблем); 150 с — аварийный предел;
  5. подстановка товаров каждого стиля на места геометрии: у стены — по стене (не «парит»), прочее — по центру;
     проверка `planner.validate` и `post_check` для каждого стиля.
Пишет ТОЛЬКО в `~/scout-scenes/trial/<trial_id>/` (корень — `TRIAL_SCENES_ROOT`): `trial-sets.json`, `layouts/`,
`adapter.json`, `scene.json`, кадры `--frames`. Живые `~/scout-scenes/flat215-demo` и `tools/scout/v3set*` не трогает.

  ~/venvs/scout/bin/python trial_demo.py <trial_id> <floorplanResult.json> [--frames]
  ~/venvs/scout/bin/python trial_demo.py <trial_id> --bench model-E-0.json [--frames]
Банк — `TRIAL_SETS` (по умолчанию `tools/scout/sets3.json` этой копии). Код выхода: 0 — готово, 3 — частично, 2 — отказ.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trial_room as TR  # noqa: E402  (кладёт солвер в sys.path)

_RUNNING: set = set()
_RUN_LOCK = threading.Lock()

TRIAL_ROOT = os.path.expanduser(os.environ.get('TRIAL_SCENES_ROOT') or '~/scout-scenes/trial')
LIVE_PATHS = (os.path.expanduser('~/scout-scenes/flat215-demo'), HERE)
BUDGET_S = 60.0          # Codex 09.11: целевой бюджет пробы, дальше — честный частичный результат
EMERGENCY_S = 150.0      # аварийный предел одного прогона солвера
STOP_S = 55.0            # когда снимать незавершённые прогоны, если показать уже есть что (запас на сборку до 60 с)
BANDS = [('14-16', 14), ('17-20', 17), ('21-25', 21), ('26-30', 26), ('31-40', 31), ('41-50', 41), ('50+', 50)]
STYLES = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
BEARERS = ('стенка', 'тв-тумба')
GEOMETRY_MIN_STYLES = 3  # роль входит в геометрию, если она есть хотя бы у половины стилей группы (не больше 3; диван и носитель ТВ — всегда)


SLOT_MIN_GB = 3.0        # свободной памяти перед тяжёлым шагом (замер — `heavy-slot.sh --stats`, тип trial)
SLOT_TIMEOUT_S = 900.0   # очередь машины дольше — честный отказ `queue_timeout`, не молчаливое ожидание


class TrialPathError(RuntimeError):
    pass


@contextlib.contextmanager
def machine_slot(label: str):
    """ТЯЖЁЛЫЙ ШАГ — ЧЕРЕЗ ОБЩУЮ ОЧЕРЕДЬ МАШИНЫ (`tools/ops/heavy_slot.py`): подбор и расстановка съедают память так же, как
    прочие прогоны DEV. Ожидание очереди в бюджет шага не входит (пишется отдельно, `timings.queue_s`). → info (`waited_s`)."""
    ops = os.path.abspath(os.path.join(HERE, '..', 'ops'))
    if ops not in sys.path:
        sys.path.insert(0, ops)
    import heavy_slot as HS
    with HS.heavy_slot(label, min_gb=SLOT_MIN_GB, timeout=SLOT_TIMEOUT_S, cmd=f'trial_demo {label}') as info:
        yield info


def _slot_timeout(e: Exception) -> bool:
    return type(e).__name__ == 'SlotTimeout'


def outcome_of(scene: dict) -> dict:
    """ИСХОД ПО КОМНАТЕ — одно явное поле для конвейера и страницы: `state` ∈ ready | partial | refused, `code` и `detail` —
    причина (для ready — null), `styles_ok`/`styles_total` — сколько стилей можно показать."""
    variants = scene.get('variants') or []
    total, ok = len(variants), sum(1 for v in variants if v.get('post_ok') and not v.get('hard'))
    base = {'styles_ok': ok, 'styles_total': total}
    status = scene.get('status')
    if status == 'ok':
        return dict(base, state='ready', code=None, detail=None)
    if status == 'partial':
        codes = sorted({p['code'] for p in scene.get('problems') or [] if p.get('code')}
                       | {p['code'] for v in variants for p in v.get('problems') or [] if p.get('code')}
                       | {h.split('|')[0] for v in variants for h in v.get('hard') or []})
        bad = [v['style'] for v in variants if not v.get('post_ok') or v.get('hard')]
        return dict(base, state='partial', code='styles_missing' if bad or not codes else codes[0],
                    detail=f"нет стилей: {', '.join(bad)}; причины: {', '.join(codes)}" if bad else ', '.join(codes))
    ref = scene.get('refusal') or next(iter(scene.get('problems') or []), None) or {'code': 'unknown'}
    return dict(base, state='refused', code=ref.get('code'), detail=ref.get('detail') or ref.get('why'))


def out_dir(trial_id: str) -> str:
    """Папка пробы: строго внутри `TRIAL_ROOT`, не живая папка демо и не папка скриптов."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', trial_id or ''):
        raise TrialPathError(f'trial_id «{trial_id}»: только буквы, цифры, _ . -')
    root = os.path.realpath(TRIAL_ROOT)
    out = os.path.realpath(os.path.join(root, trial_id))
    if os.path.dirname(out) != root:
        raise TrialPathError(f'{out} вне {root}')
    for live in LIVE_PATHS:
        lv = os.path.realpath(live)
        if out == lv or out.startswith(lv + os.sep) or lv.startswith(out + os.sep):
            raise TrialPathError(f'{out} пересекается с живым путём {lv}')
    return out


def sets_path() -> str:
    return os.environ.get('TRIAL_SETS') or os.path.join(HERE, 'sets3.json')


def band_for(area_m2: float) -> tuple[str, list]:
    """Полоса банка по площади ЯДРА (мебель стоит в нём): наибольшая, чья нижняя граница ≤ площади."""
    if area_m2 < BANDS[0][1]:
        return BANDS[0][0], ['band_below_min']
    return [b for b, lo in BANDS if lo <= area_m2][-1], []


def _base(role: str) -> str:
    return re.sub(r'\s+\d+$', '', role)


def _area(it: dict) -> float:
    w = float(it.get('w') or it.get('dia') or 0)
    d = float(it.get('d') or it.get('dia') or 0)
    return w * d


def _sofa_corner(it: dict | None) -> bool:
    import sofa_shape
    return bool(it) and sofa_shape.is_corner(it.get('name'), it.get('d'))


def geometry_set(styles: list[dict], band: str) -> tuple[dict, dict]:
    """Набор-геометрия: по каждой роли — САМЫЙ КРУПНЫЙ реальный товар этой роли среди стилей (размер не придумывается).
    Стенка и ТВ-тумба — один носитель ТВ: берётся крупнейший из обоих под ролью `тв-тумба`. → (набор, откуда что)."""
    typical = json.load(open(os.path.join(HERE, 'typical-dims.json'), encoding='utf-8'))
    count: dict = {}
    best: dict = {}
    low: dict = {}                                          # роль → самая низкая высота среди стилей
    for st in styles:
        seen = set()
        for role, it in (st.get('items') or {}).items():
            if not it or role != _base(role) or not (it.get('w') or it.get('dia')):
                continue
            key = 'тв-тумба' if role in BEARERS else role
            if key not in typical or key in seen:
                continue
            seen.add(key)
            count[key] = count.get(key, 0) + 1
            if it.get('h') and (key not in low or it['h'] < low[key][0]):
                low[key] = (it['h'], st.get('style'))
            if key not in best or _area(it) > _area(best[key][1]):
                best[key] = (st.get('style'), it, role)
    need_n = min(GEOMETRY_MIN_STYLES, (len(styles) + 1) // 2)    # у геометрии из 2 стилей — роль хотя бы одного
    keep = {r for r, n in count.items() if n >= need_n or r in ('диван', 'тв-тумба')}
    items = {}
    for r in sorted(keep):
        it = dict(best[r][1])
        if r == 'тв-тумба' and best[r][2] == 'стенка':
            it['_bearer_from'] = 'стенка'
        if r in LOW_HEIGHT_ROLES and r in low and low[r][0] < (it.get('h') or 0):
            # Высота дивана в солвере — только «не закрывает ли окно» (спинка > 80 см у окна — жёсткий отказ).
            # Крупнейший по площади диван бывает и самым высоким (E-0: 86 см) — тогда вся форма теряет расстановку
            # (MEDIA_MISSING). Геометрия берёт площадь крупнейшего и высоту самого низкого; товар выше 80 см у окна
            # честно ловит проверка каждого стиля (hard WINDOW_BLOCKED в варианте).
            it['_h_from'] = {'h': it.get('h'), 'low_style': low[r][1]}
            it['h'] = low[r][0]
        items[r] = it
    src = {r: {'style': best[r][0], 'role': best[r][2], 'name': best[r][1].get('name')} for r in sorted(keep)}
    return {'band': band, 'style': 'геометрия', 'm2': None, 'items': items, 'set_id': 'trial-geometry'}, src


def trim_to_geometry(st: dict, geo: dict) -> dict:
    """Свой набор стиля для солвера — только роли его геометрии. Полный набор несёт вторые диваны, третьи кресла и обеденные
    группы, которых в геометрии нет: солвер тратит на них время и на большом ядре даёт жёсткие нарушения (E, замер 09.11).
    Показывается всё равно то, что расставлено, — тот же состав, что у стилей на общей геометрии. Товары не меняются."""
    keep = {}
    for role, it in (st.get('items') or {}).items():
        if role == _base(role) and ('тв-тумба' if role in BEARERS else role) in geo['items']:
            keep[role] = it
    return dict(st, items=keep)


def shape_groups(styles: list[dict], band: str) -> list[dict]:
    """Стили → геометрии по ФОРМЕ дивана. Угловой и прямой диван — разные расстановки (у углового спинка может стоять
    в «воздухе», столик — у оттоманки): подстановка прямого на место углового даёт щель за спинкой и столик в диване
    (замер E-0 09.11). Одна геометрия на форму — не больше двух прогонов солвера, они идут параллельно."""
    by: dict = {}
    for st in styles:
        shape = 'corner' if _sofa_corner((st.get('items') or {}).get('диван')) else 'straight'
        by.setdefault(shape, []).append(st)
    out = []
    for shape in ('straight', 'corner'):
        if shape not in by:
            continue
        geo, src = geometry_set(by[shape], band)
        geo['set_id'] = f'trial-geometry-{shape}'
        out.append({'shape': shape, 'set': geo, 'source': src, 'need': need_from(geo, band),
                    'styles': [(st, None) for st in by[shape]]})
    return out


MAX_PARALLEL = 4
LOW_HEIGHT_ROLES = ('диван',)


def need_from(geo: dict, band: str) -> dict:
    it = geo['items']
    dims = {'диван': [it['диван'].get('w') or 190, it['диван'].get('d') or 95]}
    if 'тв-тумба' in it:
        dims['тв-тумба'] = [it['тв-тумба'].get('w') or 90, it['тв-тумба'].get('d') or 42]
    return TR.need_group(dims, band)


# ───────────────────────── солвер ─────────────────────────

def TR_strip(ops: list) -> list:
    return [{k: v for k, v in o.items() if not k.startswith('_')} for o in ops]


def beam_off(cand: dict) -> bool:
    """Большое ядро (`room_map.room_mode` = large): перебор гипотез расстановки дольше бюджета шага (E 690×505: 71 с против 45 с
    без него, замер 09.11). Прогон — первой, «жадной» расстановкой (`LAYOUT_BEAM=0`, она и так всегда среди кандидатов); в сцене флаг."""
    from planner.models import Room
    from planner.room_map import room_mode
    return room_mode(Room(width_cm=cand['w'], depth_cm=cand['d'])) == 'large'


def run_solver(cand: dict, cfg: dict, sets_file: str, layouts: str, hinge: str, tag: str, timeout: float,
               n: int = 1) -> dict:
    ops = TR_strip(TR.solver_openings(cand, cfg, hinge))
    env = dict(os.environ, SETS_SNAPSHOT=sets_file, SCENE_OPENINGS=json.dumps(ops, ensure_ascii=False),
               SCENE_RADIATORS='[]', LAYOUT_SUFFIX=f'-{tag}', LAYOUT_OUT_DIR=layouts)
    for k in ('SCENE_CONTOUR', 'LAYOUT_SIGNATURE_FILE'):
        env.pop(k, None)
    if beam_off(cand):
        env.setdefault('LAYOUT_BEAM', '0')
    t = time.time()
    p = subprocess.Popen([sys.executable, 'solver_run.py', str(n), '--v3', str(int(cand['w'])), str(int(cand['d']))],
                         cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    with _RUN_LOCK:
        _RUNNING.add(p)
    try:
        stdout, stderr = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise
    finally:
        with _RUN_LOCK:
            _RUNNING.discard(p)
    art_path = os.path.join(layouts, f'v3set{n}-layout-{tag}.json')
    out = {'rc': p.returncode, 'seconds': round(time.time() - t, 2), 'artifact': art_path, 'openings': ops,
           'stderr': stderr[-600:] if p.returncode else ''}
    out['art'] = json.load(open(art_path, encoding='utf-8')) if p.returncode == 0 and os.path.exists(art_path) else None
    out['missing'] = [ln.split(':', 1)[1].strip() for ln in stdout.splitlines() if ln.startswith('НЕ размещены:')]
    return out


def _stop_running() -> None:
    """Бюджет вышел: снять свои ещё идущие прогоны солвера (только дочерние процессы этой пробы)."""
    with _RUN_LOCK:
        for p in list(_RUNNING):
            p.terminate()


def _placed(art: dict) -> dict:
    return {k: v for k, v in art.items() if not k.startswith('_') and isinstance(v, dict) and 'x' in v}


def placements_of(art: dict) -> list:
    from planner.models import Item, Placement
    ps = []
    for k, v in _placed(art).items():
        ps.append(Placement(role=k, x=v['x'], y=v['z'], rot=v.get('rot') or 0, elev_cm=float(v.get('elev') or 0),
                            item=Item(role=k, w_cm=v['w'], d_cm=v['d'], h_cm=v.get('h') or 60, corner=bool(v.get('corner')),
                                      corner_section_cm=float(v.get('section') or 95),
                                      corner_left=bool(v.get('corner_left')))))
    return ps


def core_room(cand: dict, ops: list, render: bool = False):
    """Комната солвера для ядра; `render` — стыки-проходы как проёмы без двери (кадру не рисовать дверь в проходе)."""
    from planner.models import Opening, Room
    out = []
    for o in ops:
        o = {k: v for k, v in o.items() if not k.startswith('_')}
        if render and o['kind'] == 'door' and not o.get('swing_cm'):
            o = dict(o, kind='opening')
        out.append(Opening(**o))
    return Room(width_cm=cand['w'], depth_cm=cand['d'], openings=out)


def hard_of(room, ps) -> list:
    from planner.validate import validate
    return sorted({f"{v.code}|{','.join(sorted(v.roles))}" for v in validate(room, ps).violations
                   if v.severity.name == 'HARD'})


def drop_window_chairs(room, ps: list) -> tuple[list, list]:
    """Стул выше подоконника у самого окна — лишний: убираем его, стол остаётся с остальными стульями.

    Солвер ставит дополнительные стулья без учёта их высоты; из-за одного стула спинкой в окно весь стиль снимать незачем
    (E, замер 09.11: джапанди, стул 93 см при подоконнике 85). Последний стул не убираем — такой стиль снимет общая проверка."""
    near = {r for h in hard_of(room, ps) if h.startswith('WINDOW_BLOCKED|') for r in h.split('|')[1].split(',')}
    chairs = [p.role for p in ps if _base(p.role) == 'стул']
    gone = sorted(r for r in near if r in chairs)
    if not gone or len(gone) == len(chairs):
        return ps, []
    return [p for p in ps if p.role not in gone], gone


# ───────────────────────── подстановка товаров стиля ─────────────────────────

def _style_item(st: dict, role: str):
    items = st.get('items') or {}
    base = _base(role)
    if base == 'тв-тумба':
        for r in ('тв-тумба', 'стенка'):
            if items.get(r) and (items[r].get('w') or items[r].get('dia')):
                return r, items[r]
        return None, None
    it = items.get(role) or (items.get(base) if role != base else None)
    return (role if items.get(role) else base), it


def _moved(p, dx: float, dy: float, item=None):
    from planner.models import Placement
    return Placement(role=p.role, x=p.x + dx, y=p.y + dy, rot=p.rot, item=item or p.item, elev_cm=p.elev_cm)


def _wall_align(g: tuple, s: tuple, W: float, D: float, back: tuple | None) -> tuple[float, float]:
    """Сдвиг товара стиля (след `s`) к месту геометрии (след `g`): сторона у стены ядра (≤ WALL_NEAR_CM) остаётся на том же
    расстоянии от стены, `back` (знак оси спинки) — спинка на месте геометрии; прочее — по центру."""
    out = []
    for ax, (lo, hi, L) in enumerate(((0, 2, W), (1, 3, D))):
        sgn = back[ax] if back else 0
        if sgn < 0 or (not sgn and g[lo] <= WALL_NEAR_CM):
            out.append(g[lo] - s[lo])
        elif sgn > 0 or (not sgn and g[hi] >= L - WALL_NEAR_CM):
            out.append(g[hi] - s[hi])
        else:
            out.append(0.0)
    return out[0], out[1]


def _follow_front(anchor_g, anchor_s, dep_g, dep_item):
    """Зависимый перед якорем (столик перед диваном): тот же зазор от фронта якоря, то же смещение вбок от его центра."""
    from planner.geometry import facing_vector, footprint
    fx, fy = (round(v) for v in facing_vector(anchor_g.rot))
    ag, as_, dg = footprint(anchor_g).bounds, footprint(anchor_s).bounds, footprint(dep_g).bounds
    q = _moved(dep_g, 0, 0, dep_item)
    s = footprint(q).bounds
    dx = dy = 0.0
    if fx:
        gap = (dg[0] - ag[2]) if fx > 0 else (ag[0] - dg[2])
        dx = (as_[2] + gap - s[0]) if fx > 0 else (as_[0] - gap - s[2])
        dy = ((as_[1] + as_[3]) - (ag[1] + ag[3])) / 2 + ((dg[1] + dg[3]) - (s[1] + s[3])) / 2
    else:
        gap = (dg[1] - ag[3]) if fy > 0 else (ag[1] - dg[3])
        dy = (as_[3] + gap - s[1]) if fy > 0 else (as_[1] - gap - s[3])
        dx = ((as_[0] + as_[2]) - (ag[0] + ag[2])) / 2 + ((dg[0] + dg[2]) - (s[0] + s[2])) / 2
    return _moved(q, dx, dy), (dx, dy)


def _follow_table(tbl_g, tbl_s, ch_g, ch_item):
    """Стул у обеденного стола: тот же зазор до своей стороны стола; вдоль стороны — пропорционально длине стола."""
    from planner.geometry import footprint
    tg, ts, cg = footprint(tbl_g).bounds, footprint(tbl_s).bounds, footprint(ch_g).bounds
    q = _moved(ch_g, 0, 0, ch_item)
    s = footprint(q).bounds
    ccx, ccy = (cg[0] + cg[2]) / 2, (cg[1] + cg[3]) / 2
    tcx, tcy, ncx, ncy = (tg[0] + tg[2]) / 2, (tg[1] + tg[3]) / 2, (ts[0] + ts[2]) / 2, (ts[1] + ts[3]) / 2
    scx, scy = (s[0] + s[2]) / 2, (s[1] + s[3]) / 2
    kx = (ts[2] - ts[0]) / max(tg[2] - tg[0], 1.0)
    ky = (ts[3] - ts[1]) / max(tg[3] - tg[1], 1.0)
    if cg[3] <= tg[1] + 1 or cg[1] >= tg[3] - 1:          # стул над/под столом — сторона по y
        dy = (ts[1] - (tg[1] - cg[3]) - s[3]) if cg[3] <= tg[1] + 1 else (ts[3] + (cg[1] - tg[3]) - s[1])
        dx = ncx + (ccx - tcx) * kx - scx
    else:
        dx = (ts[0] - (tg[0] - cg[2]) - s[2]) if ccx < tcx else (ts[2] + (cg[0] - tg[2]) - s[0])
        dy = ncy + (ccy - tcy) * ky - scy
    return _moved(q, dx, dy), (dx, dy)


WALL_NEAR_CM = 20.0   # предмет геометрии ближе к стене ядра — товар стиля держит ту же щель до стены (не «парит», не щель)
FOLLOW = {'столик': 'диван', 'тв': 'тв-тумба'}       # зависимый → якорь (стулья — за обеденным столом, отдельно)


def substitute(geo_ps: list, st: dict, W: float, D: float) -> tuple[list, list, list]:
    """Товары стиля на места геометрии → (расстановка, роли без товара стиля, строки «что поставлено»).

    Порядок: самостоятельные предметы (у стены — по стене, диван — спинкой на место геометрии), затем зависимые от своего
    якоря: столик — тот же зазор от фронта дивана и та же ось, стулья — тот же зазор до стороны стола, ТВ — за носителем."""
    from planner.geometry import facing_vector, footprint
    from planner.models import Item
    by_geo = {p.role: p for p in geo_ps}
    new: dict = {}
    absent, rows, shifts = [], {}, {}

    def item_for(p):
        srole, it = _style_item(st, p.role)
        if not it:
            return None, None, None
        w = float(it.get('w') or it.get('dia'))
        d = float(it.get('d') or it.get('dia'))
        corner = _base(p.role) == 'диван' and _sofa_corner(it)
        item = Item(role=p.role, w_cm=w, d_cm=d, h_cm=it.get('h') or (p.item.h_cm if p.item else 60), name=it.get('name'),
                    corner=corner, corner_section_cm=p.item.corner_section_cm if p.item else 95,
                    corner_left=p.item.corner_left if (p.item and p.item.corner) else False,
                    round_shape=bool(it.get('dia') and not it.get('w')))
        return srole, it, item

    def row(p, q, srole, it, dxy):
        rows[p.role] = {'role': p.role, 'style_role': srole, 'name': it.get('name'), 'mid': it.get('mid'),
                        'eid': it.get('eid'), 'sid': f"{it['mid']}_{it['eid']}" if it.get('mid') else None,
                        'price': it.get('price'), 'url': it.get('url'), 'img': it.get('img'), 'w': q.item.w_cm,
                        'd': q.item.d_cm, 'h': it.get('h'), 'x': round(q.x, 1), 'y': round(q.y, 1), 'rot': q.rot,
                        'corner': q.item.corner, 'shift_cm': [round(dxy[0], 1), round(dxy[1], 1)]}

    def dependent(role):
        return _base(role) in FOLLOW or _base(role) == 'стул'

    for p in geo_ps:                                       # 1) самостоятельные
        if dependent(p.role):
            continue
        srole, it, item = item_for(p)
        if not it:
            absent.append(p.role)
            continue
        q0 = _moved(p, 0, 0, item)
        back = None
        if _base(p.role) == 'диван':
            fx, fy = (round(v) for v in facing_vector(p.rot))
            back = (-fx, -fy)
        g_b, s_b = footprint(p).bounds, footprint(q0).bounds
        dxy = _wall_align(g_b, s_b, W, D, back)
        bearer = next((by_geo[r] for r in BEARERS if r in by_geo), None)
        if back and bearer is not None:
            # диван уже места геометрии: вдоль стены — к оси носителя ТВ, не выходя из следа геометрии
            # (иначе узкий диван по центру старого места теряет ось ТВ — TV_OFF_AXIS, замер D-1 09.11)
            ax = 0 if back[0] == 0 else 1
            lo, hi = g_b[ax] - s_b[ax], g_b[ax + 2] - s_b[ax + 2]
            want = (bearer.x if ax == 0 else bearer.y) - (p.x if ax == 0 else p.y)
            lat = max(lo, min(hi, want))
            dxy = (lat, dxy[1]) if ax == 0 else (dxy[0], lat)
        new[p.role] = _moved(q0, *dxy)
        shifts[p.role] = dxy
        row(p, new[p.role], srole, it, dxy)
    for p in geo_ps:                                       # 2) зависимые — за своим якорем
        if not dependent(p.role):
            continue
        base = _base(p.role)
        anchor = 'стол обеденный' if base == 'стул' else FOLLOW[base]
        if anchor not in new:
            if anchor in by_geo or base == 'стул':
                absent.append(p.role)
                continue
        if base == 'тв':                                   # панель ТВ — служебная, едет за носителем
            dxy = shifts.get(anchor, (0.0, 0.0))
            new[p.role] = _moved(p, *dxy)
            continue
        srole, it, item = item_for(p)
        if not it:
            absent.append(p.role)
            continue
        if anchor not in new:
            q, dxy = _moved(p, 0, 0, item), (0.0, 0.0)
        elif base == 'стул':
            q, dxy = _follow_table(by_geo[anchor], new[anchor], p, item)
        else:
            q, dxy = _follow_front(by_geo[anchor], new[anchor], p, item)
        new[p.role] = q
        row(p, q, srole, it, dxy)
    order = [p.role for p in geo_ps if p.role in new]
    return [new[r] for r in order], absent, [rows[r] for r in order if r in rows]


def _ps_json(ps: list, x0: float = 0.0, y0: float = 0.0) -> list:
    return [{'role': p.role, 'x': round(p.x + x0, 1), 'y': round(p.y + y0, 1), 'rot': p.rot,
             'w': p.item.w_cm if p.item else None, 'd': p.item.d_cm if p.item else None,
             'h': p.item.h_cm if p.item else None, 'elev': p.elev_cm,
             'corner': bool(p.item and p.item.corner), 'corner_left': bool(p.item and p.item.corner_left),
             'section': p.item.corner_section_cm if p.item else None} for p in ps]


# ───────────────────────── сборка ─────────────────────────

def load_result(args: list) -> dict:
    if args and args[0] == '--bench':
        return TR.from_bench_models([json.load(open(a, encoding='utf-8')) for a in args[1:]])
    return json.load(open(args[0], encoding='utf-8'))


def _write(path: str, data) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)


def _write_scene(out: str, scene: dict) -> None:
    scene['outcome'] = outcome_of(scene)
    _write(os.path.join(out, 'scene.json'), scene)


def _no_slot(label: str):
    """Подставной решатель (тесты) не грузит машину — очередь не нужна."""
    return contextlib.nullcontext({'waited_s': 0.0})


def _pick_styles(sets: list, band: str) -> list:
    import flat215_demo as FD
    return FD.pick_banks(sets, band, len(STYLES))


def build(trial_id: str, result: dict, sets: list | None = None, solver=run_solver, pick=_pick_styles, slot=None) -> dict:
    """Проба целиком → сцена (`scene.json`). Отказ адаптера — сцена со статусом `refused`, не исключение. Исход для конвейера
    и страницы — поле `outcome` (`outcome_of`). Подбор и расстановка — под общей очередью машины (`machine_slot`)."""
    t0 = time.time()
    OUT = out_dir(trial_id)
    layouts = os.path.join(OUT, 'layouts')
    os.makedirs(layouts, exist_ok=True)
    cfg = TR.rules()
    scene = {'trial_id': trial_id, 'version': 1, 'status': None, 'flags': [], 'problems': [],
             'timings': {}, 'out': OUT}
    try:
        ad = TR.adapt(result, cfg=cfg)
    except TR.Refusal as e:
        scene.update(status='refused', refusal={'code': e.code, 'detail': e.detail})
        scene['timings'] = {'adapter_s': round(time.time() - t0, 3), 'solver_s': 0, 'assembly_s': 0,
                            'total_s': round(time.time() - t0, 3)}
        _write_scene(OUT, scene)
        return scene
    t_ad = time.time() - t0
    # ── полоса, стили, геометрия (часть «адаптера»: это ещё до солвера) ──
    sets = sets if sets is not None else json.load(open(sets_path(), encoding='utf-8'))
    band, bflags = band_for(ad['candidates'][0]['area_m2'])
    flags = list(ad['flags']) + bflags
    i_band = [b for b, _ in BANDS].index(band)
    picked, groups, cands = [], [], []
    while i_band >= 0:
        band = BANDS[i_band][0]
        picked = pick(sets, band)
        if picked:
            groups = shape_groups([sets[i - 1] for i in picked], band)
            for g in groups:                                     # номер набора в банке — для отчёта
                g['styles'] = [(st, next(i for i in picked if sets[i - 1] is st)) for st, _ in g['styles']]
            # ядро годно, если обязательная группа влезает реальными товарами КАЖДОЙ геометрии
            cands = [c for c in ad['candidates'] if all(TR.group_fits(c['w'], c['d'], g['need']) for g in groups)]
            if cands:
                break
        i_band -= 1
        flags.append('band_lowered')
    if not cands:
        scene.update(status='refused', refusal={'code': 'living_core_small',
                                                'detail': 'диван и ТВ реальных товаров не влезают ни в одно ядро ни на одной полосе'})
        scene['timings'] = {'adapter_s': round(time.time() - t0, 3), 'solver_s': 0, 'assembly_s': 0,
                            'total_s': round(time.time() - t0, 3)}
        _write_scene(OUT, scene)
        return scene
    styles = [sets[i - 1] for i in picked]
    if len(styles) < len(STYLES):
        flags.append(f'styles_{len(styles)}_of_{len(STYLES)}')
    sets_file = os.path.join(OUT, 'trial-sets.json')
    # геометрии — первые номера снимка; за ними свои наборы стилей, урезанные до ролей геометрии (см. `trim_to_geometry`)
    geo_of = {id(st): g['set'] for g in groups for st, _ in g['styles']}
    _write(sets_file, [g['set'] for g in groups] + [trim_to_geometry(st, geo_of[id(st)]) for st in styles])
    _write(os.path.join(OUT, 'adapter.json'), TR.summary(ad))
    t_prep = time.time() - t0 - t_ad
    # ── солвер: по ОДНОЙ геометрии на форму дивана (обе — параллельно); проверка по полному контуру; есть проблемы —
    #    вторая петля дверей. Геометрию не расставить (крупнейшие товары не сходятся, напр. носитель ТВ) — стили этой
    #    формы СРАЗУ считаются своими наборами на том же ядре (не дожидаясь второй формы). Кончился бюджет и что-то уже
    #    расставлено — оставшиеся прогоны снимаем, результат честно частичный; не расставлено ничего — ждём аварийный предел.
    #    Потом — следующее ядро, пока в бюджете ──
    t1 = time.time()
    tries, chosen = [], None
    n_geo = len(groups)
    clock = {'queue': 0.0}

    def elapsed() -> float:
        return time.time() - t0 - clock['queue']

    def one(u, ci, cand, hinge):
        tag = f"trial-{u['tag']}-c{ci}-{hinge[0]}"
        rec = {'unit': u['tag'], 'cand': ci, 'hinge': hinge}
        try:
            sr = solver(cand, cfg, sets_file, layouts, hinge, tag, EMERGENCY_S, n=u['n'])
        except subprocess.TimeoutExpired:
            return dict(rec, rc='timeout', seconds=EMERGENCY_S), None
        rec.update(rc=sr['rc'], seconds=sr['seconds'], missing=sr.get('missing'))
        if sr['art'] is None:
            return dict(rec, stderr=sr.get('stderr')), None
        ps = placements_of(sr['art'])
        if not any(_base(p.role) == 'диван' for p in ps):
            # солвер честно сказал «не расставить» (`_infeasible_reason`) — пустая комната не результат
            return dict(rec, rc='empty', infeasible=sr['art'].get('_infeasible_reason')), None
        pc = TR.post_check(ad, cand, ps)
        hard = hard_of(core_room(cand, sr['openings']), ps)
        rec.update(post_ok=pc['ok'], problems=pc['problems'], hard=hard)
        return rec, {'sr': sr, 'ps': ps, 'pc': pc, 'hard': hard,
                     'score': (len(pc['problems']) + len(hard), len(sr.get('missing') or []))}

    def solve_units(units, ci, cand, pool, have=False):
        """Прогоны солвера по мере готовности → (лучшие расстановки по `tag`, итоговый список единиц)."""
        best, pending, units, stopped = {}, {}, list(units), False

        def submit(u, hinge):
            pending[pool.submit(one, u, ci, cand, hinge)] = (u, hinge)

        for u in units:
            submit(u, 'left')
        while pending:
            left = STOP_S - elapsed()
            if left <= 0 and (best or have) and not stopped:         # есть что показать — снимаем то, что не успело
                stopped = True
                _stop_running()
            hold = None if stopped or (left <= 0 and not (best or have)) else max(left, 0.05)
            done, _ = wait(list(pending), timeout=hold, return_when=FIRST_COMPLETED)
            for f in done:
                u, hinge = pending.pop(f)
                rec, res = f.result()
                tries.append(rec)
                if res and (u['tag'] not in best or res['score'] < best[u['tag']]['score']):
                    best[u['tag']] = dict(res, hinge=hinge)
                if stopped or elapsed() > STOP_S:
                    continue
                if res and res['score'][0] and hinge == 'left':
                    submit(u, 'right')                     # проблемы у дверей — вторая петля
                elif res is None and u['kind'] == 'geometry' and len(u['styles']) > 1:
                    own = own_units(u, u['styles'])
                    units = [x for x in units if x is not u] + own
                    for v in own:
                        submit(v, 'left')
        return best, units

    def own_units(u, styles):
        return [{'tag': f"s{n}", 'kind': 'own', 'n': n_geo + picked.index(n) + 1, 'shape': u['shape'], 'source': None,
                 'styles': [(st, n)], 'from': u['tag']} for st, n in styles]

    def assemble(ci, cand, best, units):
        """Товары каждого стиля на места СВОЕЙ расстановки → (геометрии, варианты, проблемы)."""
        x0, y0 = cand['rect'][0], cand['rect'][1]
        geometries, variants, problems = [], [], []
        for gi, u in enumerate(units):
            b = best.get(u['tag'])
            head = {'id': u['tag'], 'kind': u['kind'], 'shape': u['shape'], 'snapshot_index': u['n'],
                    'styles': [st.get('style') for st, _ in u['styles']], 'source': u['source']}
            if u.get('from'):
                head['replaces'] = u['from']
                flags.append('own_layouts')
            if b is None:                                   # не расставить — стили без сцены, с причиной
                why = next((t.get('infeasible') or t.get('stderr') or t.get('rc') for t in reversed(tries)
                            if t['unit'] == u['tag'] and t['cand'] == ci), None)
                geometries.append(dict(head, failed=why, placements=[], placements_core=[], problems=[], hard=[],
                                       openings_core=TR_strip(TR.solver_openings(cand, cfg))))
                problems.append({'code': 'layout_failed', 'geometry': gi, 'why': why})
                for st, n in u['styles']:
                    variants.append({'style': st.get('style'), 'set_index': n, 'set_id': st.get('set_id'), 'geometry': gi,
                                     'items': [], 'absent_roles': [], 'hard': [], 'post_ok': False,
                                     'problems': [{'code': 'layout_failed', 'why': why}], 'placements': [],
                                     'placements_core': [], 'failed': True})
                continue
            geometries.append(dict(head, missing=b['sr'].get('missing'), hinge=b['hinge'], openings_core=b['sr']['openings'],
                                   problems=b['pc']['problems'], hard=b['hard'], placements=_ps_json(b['ps'], x0, y0),
                                   placements_core=_ps_json(b['ps']), artifact=os.path.relpath(b['sr']['artifact'], OUT)))
            problems += [dict(p, geometry=gi) for p in b['pc']['problems']]
            problems += [{'code': h.split('|')[0], 'roles': h.split('|')[1], 'geometry': gi} for h in b['hard']]
            croom = core_room(cand, b['sr']['openings'])
            for st, n in u['styles']:
                ps, absent, rows = substitute(b['ps'], st, cand['w'], cand['d'])
                ps, gone = drop_window_chairs(croom, ps)
                absent = absent + gone
                rows = [r for r in rows if r['role'] not in gone]
                spc = TR.post_check(ad, cand, ps)
                shard = hard_of(croom, ps)
                variants.append({'style': st.get('style'), 'set_index': n, 'set_id': st.get('set_id'), 'geometry': gi,
                                 'items': rows, 'absent_roles': absent, 'hard': shard, 'post_ok': spc['ok'],
                                 'problems': spc['problems'], 'placements': _ps_json(ps, x0, y0),
                                 'placements_core': _ps_json(ps)})
        return geometries, variants, problems

    geo_units = [{'tag': f'g{gi}', 'kind': 'geometry', 'n': gi + 1, 'shape': g['shape'], 'source': g['source'],
                  'styles': g['styles']} for gi, g in enumerate(groups)]
    slot_ctx = (slot or (machine_slot if solver is run_solver else _no_slot))(f'trial-living-{trial_id}')
    try:
        with slot_ctx as info, ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
            clock['queue'] = float((info or {}).get('waited_s') or 0.0)
            for ci, cand in enumerate(cands):
                best, units = solve_units(geo_units, ci, cand, pool)
                if best:
                    # лучше ядро, где расставлено больше стилей; среди них — меньше проблем
                    lost = sum(len(u['styles']) for u in units if u['tag'] not in best)
                    total = (lost, sum(b['score'][0] for b in best.values()))
                    if chosen is None or total < chosen[0]:
                        chosen = (total, ci, cand, best, units)
                    if total == (0, 0):
                        break
                if elapsed() > STOP_S:
                    break
            if chosen is not None:
                # стиль, чей товар на месте геометрии нарушает правила (высокий диван у окна) — своим набором, пока есть время
                _, ci, cand, best, units = chosen
                _, draft, _ = assemble(ci, cand, best, units)
                bad = {v['style'] for v in draft if not v.get('failed') and (v['hard'] or not v['post_ok'])}
                if bad and elapsed() <= STOP_S:
                    for u in [u for u in units if u['kind'] == 'geometry' and any(st.get('style') in bad for st, _ in u['styles'])]:
                        move = [(st, n) for st, n in u['styles'] if st.get('style') in bad]
                        u['styles'] = [x for x in u['styles'] if x not in move]
                        own = own_units(u, move)
                        got, _ = solve_units(own, ci, cand, pool, have=True)
                        units = units + own
                        best.update(got)
                    chosen = (chosen[0], ci, cand, best, units)
    except Exception as e:  # noqa: BLE001 — разбираем только очередь машины, остальное — наверх
        if not _slot_timeout(e):
            raise
        scene.update(status='failed', flags=flags, problems=[{'code': 'queue_timeout',
                                                              'detail': f'нет места в очереди тяжёлых задач за {SLOT_TIMEOUT_S:.0f} с'}])
        scene['timings'] = {'adapter_s': round(t_ad + t_prep, 3), 'solver_s': 0, 'assembly_s': 0,
                            'total_s': round(time.time() - t0, 3), 'queue_s': round(time.time() - t1, 3)}
        _write_scene(OUT, scene)
        return scene
    t_sol = time.time() - t1 - clock['queue']
    scene['tries'] = tries
    if chosen is None:
        scene.update(status='failed', flags=flags, problems=[{'code': 'solver_failed',
                                                              'detail': 'ни одна расстановка не получилась ни на одном ядре'}])
        scene['timings'] = {'adapter_s': round(t_ad + t_prep, 3), 'solver_s': round(t_sol, 3), 'assembly_s': 0,
                            'total_s': round(elapsed(), 3), 'queue_s': round(clock['queue'], 3)}
        _write_scene(OUT, scene)
        return scene
    # ── сборка: товары каждого стиля на места СВОЕЙ расстановки; что и после своей расстановки нарушает правила — не показываем ──
    t2 = time.time()
    _, ci, cand, best, units = chosen
    geometries, variants, problems = assemble(ci, cand, best, units)
    for v in variants:
        if v.get('failed') or (not v['hard'] and v['post_ok']):
            continue
        why = sorted({h.split('|')[0] for h in v['hard']} | {p['code'] for p in v['problems']})
        problems.append({'code': 'style_rejected', 'style': v['style'], 'why': why, 'geometry': v['geometry']})
        v.update(items=[], placements=[], placements_core=[], post_ok=False, failed=True, hard=[],
                 problems=[{'code': 'style_rejected', 'why': why}])
    order = {s: i for i, s in enumerate(STYLES)}
    variants.sort(key=lambda v: order.get(v['style'], 99))
    ok_styles = [v for v in variants if v['post_ok'] and not v['hard']]
    status = 'ok' if not problems and len(ok_styles) == len(variants) else 'partial'
    if elapsed() > BUDGET_S:
        flags.append('over_budget')
    if solver is run_solver and beam_off(cand):
        flags.append('beam_off_large')
    scene.update(status=status, flags=sorted(set(flags + cand['flags'])), problems=problems, band=band,
                 room={**ad['room'], 'panel': ad['panel']},
                 core={'rect': cand['rect'], 'w': cand['w'], 'd': cand['d'], 'area_m2': cand['area_m2'],
                       'core_share': cand['core_share'], 'index': ci,
                       'residues': [{k: v for k, v in r.items() if k != 'poly'} for r in cand['residues']]},
                 openings_full=[{k: v for k, v in o.items()} for o in ad['ops']],
                 # проёмы ядра (кадр ядра, `planner/models.py:Opening`) — общие для всех геометрий, кроме стороны петли
                 # двери (`geometries[i].openings_core` — точные для своей расстановки)
                 openings_core=geometries[0]['openings_core'],
                 geometries=geometries, variants=variants, styles_ok=len(ok_styles))
    t_asm = time.time() - t2
    scene['timings'] = {'adapter_s': round(t_ad + t_prep, 3), 'solver_s': round(t_sol, 3), 'assembly_s': round(t_asm, 3),
                        'total_s': round(elapsed(), 3), 'solver_runs': len(tries), 'queue_s': round(clock['queue'], 3),
                        'adapter_only_s': round(t_ad, 3)}
    _write_scene(OUT, scene)
    return scene


# ───────────────────────── кадры (замер L-C) ─────────────────────────

ROLE_RGB = {'диван': (196, 120, 90), 'кресло': (210, 160, 100), 'столик': (150, 110, 80), 'ковёр': (225, 215, 190),
            'тв-тумба': (110, 110, 130), 'тв': (40, 40, 50), 'стеллаж': (120, 150, 120), 'комод': (140, 120, 160),
            'стол обеденный': (170, 130, 90), 'стул': (190, 150, 110)}


def frame_top(scene: dict, layer: dict, path: str, label: str) -> None:
    """Вид сверху по ПОЛНОМУ контуру: контур, ядро (пунктир), остатки, проёмы с дугами обеих петель, следы мебели."""
    from PIL import Image, ImageDraw, ImageFont
    from planner.geometry import footprint
    from planner.models import Item, Placement
    pts = scene['room']['contour']
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    S, pad = 1.2, 50
    Wp, Hp = int((max(xs) - min(xs)) * S + 2 * pad), int((max(ys) - min(ys)) * S + 2 * pad + 40)
    im = Image.new('RGB', (Wp, Hp), (250, 250, 247))
    dr = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 13)
    except OSError:
        font = ImageFont.load_default()

    def P(x, y):
        return (pad + (x - min(xs)) * S, pad + 40 + (y - min(ys)) * S)
    dr.polygon([P(*p) for p in pts], fill=(236, 232, 222), outline=(30, 30, 30), width=3)
    x0, y0, x1, y1 = scene['core']['rect']
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        n = 24
        for i in range(0, n, 2):
            pa = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
            pb = (a[0] + (b[0] - a[0]) * (i + 1) / n, a[1] + (b[1] - a[1]) * (i + 1) / n)
            dr.line([P(*pa), P(*pb)], fill=(200, 60, 60), width=2)
    for o in scene['openings_full']:
        cx, cy = o['c']
        h = o['w'] / 2
        a, b = ((cx - h, cy), (cx + h, cy)) if o['axis'] == 'x' else ((cx, cy - h), (cx, cy + h))
        col = (60, 120, 220) if o['kind'] == 'window' else (40, 160, 70)
        dr.line([P(*a), P(*b)], fill=col, width=7)
        if o['kind'] == 'door' and o.get('leaf'):
            arcs = TR.door_arcs(dict(o, c=tuple(o['c']), edge_q=tuple(o['edge_q']), n_in=tuple(o['n_in'])))
            for g in ([arcs] if arcs.geom_type == 'Polygon' else list(getattr(arcs, 'geoms', []))):
                if g.geom_type == 'Polygon' and not g.is_empty:
                    dr.line([P(*c) for c in g.exterior.coords], fill=(40, 160, 70), width=1)
    ps = layer['placements']
    for q in sorted(ps, key=lambda q: 0 if _base(q['role']) == 'ковёр' else 1):
        if not q.get('w'):
            continue
        pl = Placement(role=q['role'], x=q['x'], y=q['y'], rot=q['rot'],
                       item=Item(role=q['role'], w_cm=q['w'], d_cm=q['d'], corner=q['corner'],
                                 corner_left=q['corner_left'], corner_section_cm=q.get('section') or 95))
        fp = footprint(pl)
        col = ROLE_RGB.get(_base(q['role']), (160, 160, 160))
        dr.polygon([P(*c) for c in fp.exterior.coords], fill=col, outline=(20, 20, 20))
        c = fp.centroid
        dr.text(P(c.x - 20, c.y - 6), q['role'][:12], fill=(0, 0, 0), font=font)
    t = f"{scene['trial_id']} · {label} · ядро {scene['core']['w']:.0f}×{scene['core']['d']:.0f} (пунктир)"
    probs = list(layer.get('problems') or []) + [{'code': h} for h in layer.get('hard') or []]
    dr.text((10, 8), t, fill=(0, 0, 0), font=font)
    dr.text((10, 24), 'проблемы: ' + (', '.join(sorted({p['code'] for p in probs})) or 'нет'), fill=(150, 0, 0), font=font)
    im.save(path)


def entry_cam(scene: dict, ops: list):
    """Камера «от входа»: откуда человек войдёт в ядро, на высоте глаз, взгляд в центр ядра. Порядок: настоящая дверь ядра
    (вход — первым) → стык с остатком-проходом (`passage`: в нём дверь квартиры) → стык с хвостом → прочие порталы."""
    from planner.scene import Camera
    W, D = scene['core']['w'], scene['core']['d']
    real = sorted((o for o in ops if o['kind'] == 'door' and o.get('swing_cm')),
                  key=lambda o: (not o.get('is_entrance'), -o['width_cm']))
    places = [(o['wall'], o['offset_cm'] + o['width_cm'] / 2) for o in real]
    for kind in ('passage', 'tail'):
        juncs = [j for r in scene['core'].get('residues') or [] if r['kind'] == kind for j in r['junctions']]
        places += [(w, (a + b) / 2) for w, a, b in sorted(juncs, key=lambda j: j[1] - j[2])]
    places += [(o['wall'], o['offset_cm'] + o['width_cm'] / 2) for o in ops if o['kind'] in ('door', 'opening') and not o.get('swing_cm')]
    if not places:
        return Camera(name='entry', eye=(W - 25, 160.0, D - 25), target=(W / 2, 100.0, D / 2), fov_deg=72, width=1152, height=768)
    wall, m = places[0]
    pos = {'south': (m, 20.0), 'north': (m, D - 20.0), 'west': (20.0, m), 'east': (W - 20.0, m)}[wall]
    return Camera(name='entry', eye=(pos[0], 160.0, pos[1]), target=(W / 2, 95.0, D / 2), fov_deg=72, width=1152, height=768)


def frame_entry(scene: dict, variant: dict, path: str) -> dict:
    import draft_render as DR
    import flat215_demo as FD
    from planner.models import Item, Placement
    ops = scene['geometries'][variant['geometry']]['openings_core']
    croom = core_room({'w': scene['core']['w'], 'd': scene['core']['d']}, ops, render=True)
    ps = [Placement(role=q['role'], x=q['x'], y=q['y'], rot=q['rot'], elev_cm=q.get('elev') or 0,
                    item=Item(role=q['role'], w_cm=q['w'], d_cm=q['d'], h_cm=q.get('h') or 60, corner=q['corner'],
                              corner_left=q['corner_left'], corner_section_cm=q.get('section') or 95))
          for q in variant['placements_core'] if q.get('w')]
    sid = {r['role']: FD._msid(r['sid']) for r in variant['items'] if r.get('sid')}
    img, diag = DR.scene3d_frame(croom, ps, entry_cam(scene, ops), {k: v for k, v in sid.items() if v}, {})
    img.save(path, quality=88)
    return diag


def frames(scene: dict, dst: str) -> dict:
    os.makedirs(dst, exist_ok=True)
    t = time.time()
    tag = scene['trial_id']
    out = {'top': [], 'entry': [], 'clay': {}}
    for g in scene.get('geometries') or []:
        if g.get('failed'):
            continue
        p = os.path.join(dst, f"{tag}-top-layout-{g['id']}.png")
        what = 'геометрия' if g['kind'] == 'geometry' else f"свой набор ({', '.join(g['styles'])})"
        frame_top(scene, g, p, f"{what}, {'угловой' if g['shape'] == 'corner' else 'прямой'} диван")
        out['top'].append(p)
    for v in scene.get('variants') or []:
        if v.get('failed'):
            continue
        sid = {'сканди': 'scandi', 'современный': 'modern', 'минимализм': 'minimal', 'лофт': 'loft',
               'неоклассика': 'neoclassic', 'джапанди': 'japandi'}.get(v['style'], 'x')
        p = os.path.join(dst, f'{tag}-top-{sid}.png')
        frame_top(scene, v, p, v['style'])
        out['top'].append(p)
        p = os.path.join(dst, f'{tag}-entry-{sid}.jpg')
        diag = frame_entry(scene, v, p)
        out['entry'].append(p)
        out['clay'][v['style']] = diag.get('clay') or []
    out['seconds'] = round(time.time() - t, 2)
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if a != '--frames']
    if len(args) < 2:
        print(__doc__)
        return 0
    scene = build(args[0], load_result(args[1:]))
    if '--frames' in sys.argv and scene['status'] in ('ok', 'partial'):
        t = time.time()
        with machine_slot(f"trial-frames-{scene['trial_id']}"):      # рендер кадров — тоже тяжёлый шаг
            fr = frames(scene, os.path.join(scene['out'], 'frames'))
        scene['frames'] = fr
        scene['timings']['frames_s'] = round(time.time() - t, 3)
        _write(os.path.join(scene['out'], 'scene.json'), scene)
    brief = {k: scene.get(k) for k in ('trial_id', 'status', 'outcome', 'band', 'flags', 'problems', 'timings', 'refusal', 'styles_ok')}
    brief['core'] = {k: (scene.get('core') or {}).get(k) for k in ('rect', 'w', 'd', 'area_m2')} if scene.get('core') else None
    brief['variants'] = [(v['style'], f"g{v['geometry']}", len(v['items']), v['post_ok'], v['hard'],
                          [p['code'] for p in v['problems']], v['absent_roles'])
                         for v in scene.get('variants') or []]
    print(json.dumps(brief, ensure_ascii=False, default=str))
    return {'ok': 0, 'partial': 3}.get(scene['status'], 2)


if __name__ == '__main__':
    sys.exit(main())
