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
     предметы «у стены» над нишей — к НАСТОЯЩЕЙ стене контура (`push_to_walls`; ядро кадра расширяется, `core.ext_cm`);
     не встал, но спинка наполовину у стены (стена ступенькой) — флаг `partly_at_wall`, «в воздухе» — стиль снимаем;
     необязательный предмет, из-за которого нарушены жёсткие нормы, — снимаем (`drop_norm_breakers`, `dropped_for_norms`);
     проверка `planner.validate` и `post_check` для каждого стиля.
T-12/2: наборы и модели — правилом живого демо (`item_has_mesh`: годная модель, не чужого цвета; без неё ключевая роль делает
набор негодным → полоса ниже, прочее снимается); выход — коды и разрешённые поля (`ROW_KEYS`, `assert_no_shop`), исход
`furnished | no_products | pending | refused | failed` (`outcome_of`); картинки для кадров — внутренний `media.json`.
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
import signal
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
# свой набор стиля запускаем, только если до `STOP_S` остаётся на прогон (замер 10.11: прямой диван 12 с, угловой 23–25 с); иначе стиль
# сразу идёт подстановкой на обставленную геометрию (`slot_fit`), а не в прогон, который снимут через 4 с (тур 4y0opq…, T-20261110-37)
OWN_MIN_S = 12.0
BANDS = [('14-16', 14), ('17-20', 17), ('21-25', 21), ('26-30', 26), ('31-40', 31), ('41-50', 41), ('50+', 50)]
STYLES = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
BEARERS = ('стенка', 'тв-тумба')
RETRY_SETS = 2           # T-20261112-122: сколько следующих наборов стиля пробовать, если обязательное у его набора не встало
CORE_PLACE = ('диван', 'столик') + BEARERS   # T-20261112-122: обязательное ядро гостиной — есть в наборе, не встало → следующий набор
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


STATES = ('furnished', 'no_products', 'pending', 'refused', 'failed')


def outcome_of(scene: dict) -> dict:
    """ИСХОД ПО КОМНАТЕ — КОДАМИ, без готовых строк интерфейса (владелец TG 486–488: проба на RU и EN; текст на языке подставляют
    сборщик и страница). `state`:
      furnished   — есть что показать (хотя бы один стиль); `code` = null, если показаны все стили, иначе `styles_missing`;
      no_products — комната остаётся ПУСТОЙ: «нет подходящих товаров согласно действующим шаблонам» (владелец 09.11) — ни на одной
                    полосе банка набор не влез в ядро, ни одна расстановка не вышла, или все стили сняты проверкой;
                    `code` = `no_space_walkthrough` / `no_space` (T-20261110-09), когда товары были, а МЕСТА не нашлось (`_no_space`):
                    дверей в комнате две и больше — «проходная», одна — просто «нет места под диван и ТВ»;
      pending     — подбор идёт (сцена записана до солвера);
      refused     — комнату не обставляем: план не годится (масштаб, нет окна, нет ядра — код адаптера), не «нет товаров»;
      failed      — технический сбой (очередь машины), повторить позже.
    `codes` — все коды причин (проблемы сцены и стилей), `styles_missing` — какие стили не показаны."""
    variants = scene.get('variants') or []
    ok = [v for v in variants if v.get('post_ok') and not v.get('hard')]
    codes = sorted({p['code'] for p in scene.get('problems') or [] if p.get('code')}
                   | {p['code'] for v in variants for p in v.get('problems') or [] if p.get('code')}
                   | {h.split('|')[0] for v in variants for h in v.get('hard') or []})
    base = {'styles_ok': len(ok), 'styles_total': len(variants), 'codes': codes,
            'styles_missing': [v['style'] for v in variants if v not in ok]}
    status = scene.get('status')
    ref = scene.get('refusal') or next(iter(scene.get('problems') or []), None) or {}
    if status == 'pending':
        return dict(base, state='pending', code=None)
    if status in ('ok', 'partial') and ok:
        return dict(base, state='furnished', code='styles_missing' if base['styles_missing'] else None)
    if status in ('ok', 'partial', 'no_products'):
        if _no_space(scene):
            return dict(base, state='no_products', code='no_space_walkthrough' if entries_of(scene) >= 2 else 'no_space')
        return dict(base, state='no_products', code=ref.get('code') or 'no_products')
    if status == 'refused':
        return dict(base, state='refused', code=ref.get('code') or 'unknown')
    return dict(base, state='failed', code=ref.get('code') or 'unknown')


# неудачи прогона солвера, которые — сбой, а не «места нет» (`build.one`: `error` / `rc`)
TECH_FAILS = ('solver_error', 'no_artifact', 'timeout', 'stopped')
SPACE_CODES = ('no_space', 'no_space_walkthrough')


def entries_of(scene: dict) -> int:
    """Входы гостиной (двери и проёмы полного контура, `adapter.ops`): две и больше — комната проходная."""
    if scene.get('entries') is not None:
        return int(scene['entries'])
    return sum(1 for o in scene.get('openings_full') or [] if o.get('kind') in ('door', 'opening'))


def _no_space(scene: dict) -> bool:
    """ТОВАРЫ БЫЛИ, МЕСТА НЕТ (T-20261110-09, наш пример /try): наборы стилей подобраны и влезают в ядро по площади (иначе отказ
    `living_core_small` — это «нет подходящих товаров»), но солвер не нашёл расстановки (`MEDIA_MISSING`, нет шаблона дивана) или все
    расстановки сняты проверкой по контуру (`route_blocked`, дуга двери …). Сбой прогона (ошибка, таймаут) — не «места нет»."""
    if scene.get('refusal'):
        return False
    probs = scene.get('problems') or []
    if not probs:
        return False
    for p in probs:
        code = p.get('code')
        if code == 'queue_timeout':
            return False
        if code == 'layout_failed' and (p.get('why') is None or p.get('why') in TECH_FAILS):
            return False
        if code == 'solver_failed':
            tries = scene.get('tries') or []
            if not tries or any(t.get('error') or t.get('rc') in TECH_FAILS for t in tries):
                return False
    return True


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


def drop_gone(sets: list) -> int:
    """Снять из банка товары, которых уже нет в продаже, — ТЕМ ЖЕ рубежом, что у сборки /demo (`flat215_demo.drop_unavailable`,
    владелец 01.09: «диван с карточкой 404»). Прежде тур ставил такой товар (T-20261112-96). Каталог недоступен — банк как есть, WARN.
    Тем же рубежом — мягкое, у которого каталог снял роль (детская линия: лягушка «Вигге» подушкой, `flat215_demo.drop_soft_lost`,
    одно правило с /demo; T-20261113-07/2): ночное лечение банка его не снимает (предохранитель `heal_policy`)."""
    try:
        import flat215_demo as FD
    except Exception as e:  # noqa: BLE001
        print(f'WARN:trial_drop_gone: банк не проверен ({repr(e)[:120]})', flush=True)
        return 0
    try:
        n = FD.drop_unavailable(sets)
    except Exception as e:  # noqa: BLE001 — без каталога наличие не проверить: банк как есть, но громко
        print(f'WARN:trial_drop_gone: наличие не проверено ({repr(e)[:120]})', flush=True)
        n = 0
    if n:
        print(f'банк: снято не в продаже — {n}', flush=True)
    k = FD.drop_soft_lost(sets)          # сама не падает: нет базы — пусто (WARN внутри `soft_lost`)
    if k:
        print(f'банк: снято мягкое без роли в каталоге (детские линии) — {k}', flush=True)
    return n + k


def band_for(area_m2: float) -> tuple[str, list]:
    """Полоса банка по площади ЯДРА (мебель стоит в нём): наибольшая, чья нижняя граница ≤ площади."""
    if area_m2 < BANDS[0][1]:
        return BANDS[0][0], ['band_below_min']
    return [b for b, lo in BANDS if lo <= area_m2][-1], []


def _base(role: str) -> str:
    return re.sub(r'\s+\d+$', '', role)


def _sid(it: dict | None) -> str | None:
    return f"{it['mid']}_{it['eid']}" if it and it.get('mid') else None


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
    src = {r: {'style': best[r][0], 'role': best[r][2], 'sid': _sid(best[r][1])} for r in sorted(keep)}
    # T-20261112-98/2: декор (роли вне пола: лампа, шторы…) в геометрию не входит, но решателю нужен его список — комод считается
    # светом только под лампу (services/planner-solver/rules/zones.json light_carriers.requires_decor). Правило то же, что у ролей.
    dcount: dict = {}
    for st in styles:
        for r in decor_roles(st):
            dcount[r] = dcount.get(r, 0) + 1
    decor = sorted(r for r, n in dcount.items() if n >= need_n)
    return {'band': band, 'style': 'геометрия', 'm2': None, 'items': items, 'set_id': 'trial-geometry',
            'decor_roles': decor}, src


def decor_roles(st: dict) -> list:
    """Роли набора вне пола (нет в `typical-dims.json`: лампа, шторы, подушки…) — список для решателя (`solver_run.py`
    DECOR_ROLES), состав набора не меняется (T-20261112-98/2)."""
    floor = set(json.load(open(os.path.join(HERE, 'typical-dims.json'), encoding='utf-8')))
    return sorted({_base(r) for r, it in (st.get('items') or {}).items() if it and _base(r) not in floor and r not in BEARERS})


def trim_to_geometry(st: dict, geo: dict) -> dict:
    """Свой набор стиля для солвера — только роли его геометрии. Полный набор несёт вторые диваны, третьи кресла и обеденные
    группы, которых в геометрии нет: солвер тратит на них время и на большом ядре даёт жёсткие нарушения (E, замер 09.11).
    Показывается всё равно то, что расставлено, — тот же состав, что у стилей на общей геометрии. Товары не меняются."""
    keep = {}
    for role, it in (st.get('items') or {}).items():
        if role == _base(role) and ('тв-тумба' if role in BEARERS else role) in geo['items']:
            keep[role] = it
    return dict(st, items=keep, decor_roles=decor_roles(st))   # T-98/2: декор стиля — решателю списком (лампа → комод = свет)


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
    for k in ('SCENE_CONTOUR', 'LAYOUT_SIGNATURE_FILE', 'SCENE_ROOM_KIND', 'SCENE_ROOM_TITLE'):
        env.pop(k, None)
    for k, v in (('SCENE_ROOM_KIND', cand.get('room_kind')), ('SCENE_ROOM_TITLE', cand.get('room_title'))):
        if v:
            env[k] = str(v)
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


KEEP_ROLES = ('диван', 'стенка', 'тв-тумба', 'столик', 'ковёр')   # без них гостиная — не гостиная: не снимаем ради норм
NORM_DROP_MAX = 2


def drop_norm_breakers(hard_fn, ps: list) -> tuple[list, list]:
    """Необязательный предмет, из-за которого расстановка стиля нарушает жёсткие нормы, — снимаем, стиль остаётся (T-12/2).

    Обобщение `drop_window_chairs`: у геометрии, общей для нескольких стилей, кресло солвер ставит за угловым диваном
    (E, замер 09.11: ARMCHAIR_BEHIND_SOFA / DEAD_ZONE_BEHIND_SOFA) — из-за одного кресла снимались три стиля. Снимаем по
    одному предмету (сперва тот, что в большем числе нарушений), не больше `NORM_DROP_MAX`; `KEEP_ROLES` и последний стул
    не трогаем. Нарушения не ушли все — возвращаем как было (стиль снимет общая проверка). `hard_fn(ps)` → список «код|роли»."""
    hard, cur, gone = hard_fn(ps), list(ps), []
    while hard and len(gone) < NORM_DROP_MAX:
        chairs = [p.role for p in cur if _base(p.role) == 'стул']
        cnt = {}
        for h in hard:
            for r in h.split('|')[1].split(','):
                if r in {p.role for p in cur} and _base(r) not in KEEP_ROLES and not (r in chairs and len(chairs) == 1):
                    cnt[r] = cnt.get(r, 0) + 1
        if not cnt:
            break
        role = max(sorted(cnt), key=lambda r: cnt[r])
        cur = [p for p in cur if p.role != role]
        gone.append(role)
        hard = hard_fn(cur)
    return (cur, gone) if gone and not hard else (ps, [])


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
        # строка «что поставлено» — БЕЗ полей магазина; сам товар (`_it`) — только внутри сборки (`public_row` его снимает)
        rows[p.role] = {'role': p.role, 'style_role': srole, 'sid': _sid(it), 'w': q.item.w_cm,
                        'd': q.item.d_cm, 'h': it.get('h'), 'x': round(q.x, 1), 'y': round(q.y, 1), 'rot': q.rot,
                        'corner': q.item.corner, 'shift_cm': [round(dxy[0], 1), round(dxy[1], 1)], '_it': it}

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


# ───────────────────────── мебель «у стены» — к НАСТОЯЩЕЙ стене контура ─────────────────────────

WALL_ROLES = ('тв-тумба', 'стенка', 'диван', 'стеллаж', 'комод')   # стоят спинкой к стене
TOGETHER = {'тв-тумба': ('тв',), 'стенка': ('тв',), 'диван': ('столик',)}   # едут вместе с предметом (ТВ на тумбе, столик у дивана)
BACK_GAP_CM = 12.0        # кромка спинки дальше от стены — «стоит в воздухе» (как у спален, `trial_bedroom.BACK_GAP_CM`)
BACK_MIN_SHARE = 0.8      # доля точек кромки, которым положено быть у стены
HALF_AT_WALL = 0.5        # не встал к стене, но половина спинки у стены — стоит у стены со ступенькой за частью (флаг, не отказ)
SLIDE_MAX_CM = 40.0       # насколько можно сдвинуть вдоль стены, чтобы встать в нишу целиком
SLIDE_STEP_CM = 5.0
PUSH_MAX_CM = 150.0       # глубже — уже не ниша, а соседняя часть комнаты
_EDGE_T = (0.02, 0.15, 0.3, 0.5, 0.7, 0.85, 0.98)
SIDE_OF = {(-1, 0): 'west', (1, 0): 'east', (0, -1): 'south', (0, 1): 'north'}


def _back(p) -> tuple[int, int]:
    from planner.geometry import facing_vector
    fx, fy = (round(v) for v in facing_vector(p.rot))
    return -fx, -fy


def _edge_gaps(P, x0: float, y0: float, p, dx: float = 0.0, dy: float = 0.0) -> list:
    """Точки задней кромки предмета (кадр ядра, сдвиг dx, dy) → расстояние от каждой до стены ПОЛНОГО контура в сторону спинки."""
    from shapely.geometry import LineString
    from planner.geometry import footprint
    bx, by = _back(p)
    fb = footprint(p).bounds
    if bx:
        xb = fb[2] if bx > 0 else fb[0]
        pts = [(xb, fb[1] + (fb[3] - fb[1]) * t) for t in _EDGE_T]
    else:
        yb = fb[3] if by > 0 else fb[1]
        pts = [(fb[0] + (fb[2] - fb[0]) * t, yb) for t in _EDGE_T]
    out = []
    for x, y in pts:
        X, Y = x0 + x + dx, y0 + y + dy
        hit = LineString([(X - bx, Y - by), (X + bx * 1000, Y + by * 1000)]).intersection(P.exterior)
        geoms = [] if hit.is_empty else (list(hit.geoms) if hasattr(hit, 'geoms') else [hit])
        ds = [(c[0] - X) * bx + (c[1] - Y) * by for g in geoms for c in g.coords]
        ds = [d for d in ds if d >= -1.0]
        out.append(max(min(ds), 0.0) if ds else 1000.0)
    return out


def _core_gap(p, W: float, D: float) -> float:
    from planner.geometry import footprint
    fb = footprint(p).bounds
    return {(-1, 0): fb[0], (1, 0): W - fb[2], (0, -1): fb[1], (0, 1): D - fb[3]}[_back(p)]


def _wall_share(gaps: list, gap0: float) -> float:
    return sum(1 for g in gaps if g <= gap0 + BACK_GAP_CM) / len(gaps)


def _at_wall(gaps: list, gap0: float) -> bool:
    return _wall_share(gaps, gap0) >= BACK_MIN_SHARE


def overhang(ps: list, W: float, D: float) -> dict:
    """Насколько расстановка выходит за прямоугольник ядра по сторонам (после прижима к стене ниши) → {сторона: см}."""
    from planner.geometry import footprint
    ext = {'west': 0.0, 'east': 0.0, 'south': 0.0, 'north': 0.0}
    for p in ps:
        if p.item is None:
            continue
        b = footprint(p).bounds
        ext['west'] = max(ext['west'], -b[0])
        ext['south'] = max(ext['south'], -b[1])
        ext['east'] = max(ext['east'], b[2] - W)
        ext['north'] = max(ext['north'], b[3] - D)
    return {k: float(-(-round(v, 1) // 1)) if v > 0.05 else 0.0 for k, v in ext.items()}


def shift_ops(ops: list, ext: dict) -> list:
    """Проёмы ядра → в кадр ядра, расширенного на `ext` (смещение вдоль стены растёт на запад/юг)."""
    out = []
    for o in ops:
        o = dict(o)
        o['offset_cm'] = round(o['offset_cm'] + (ext.get('west', 0.0) if o['wall'] in ('south', 'north') else ext.get('south', 0.0)), 1)
        out.append(o)
    return out


def ext_room(W: float, D: float, ops: list, ext: dict, render: bool = False):
    return core_room({'w': W + ext['west'] + ext['east'], 'd': D + ext['south'] + ext['north']}, shift_ops(ops, ext), render=render)


def push_to_walls(ad: dict, cand: dict, ps: list, check) -> tuple[list, list, list]:
    """ПРЕДМЕТЫ «У СТЕНЫ» — К НАСТОЯЩЕЙ СТЕНЕ КОНТУРА (T-12/2). Солвер ставит мебель в прямоугольное ЯДРО; сторона ядра бывает
    не стеной, а краем ниши (E: тумба ТВ в 55 см от стены, за ней «воздух»). Правило общее, не под план: предмет из `WALL_ROLES`,
    стоящий спинкой у стороны ядра (≤ `WALL_NEAR_CM`), а настоящей стены там нет (меньше `BACK_MIN_SHARE` точек кромки в
    пределах `BACK_GAP_CM`), едет спинкой к стене контура — с тем же зазором, что у ядра; не встаёт в нишу целиком — сдвиг вдоль
    стены до `SLIDE_MAX_CM`. Зависимые (`TOGETHER`) едут с ним. Сдвиг принимается, только если `check(новая, прежняя)` —
    без новых проблем (контур, двери, проход, нормы: окно, ось ТВ, наезды). Не вышло: спинка хотя бы наполовину у настоящей
    стены (`HALF_AT_WALL`; стена ступенькой, за частью — проход или эркер) — роль в `partly` (флаг), иначе — в `stuck`
    (проблема `back_off_wall`, как у спален; стиль не показываем). → (расстановка, сдвиги [{role, by_cm}], stuck, partly)."""
    from planner.geometry import footprint
    P, x0, y0, W, D = ad['poly'], cand['rect'][0], cand['rect'][1], cand['w'], cand['d']
    cur = list(ps)
    pushes, stuck, partly = [], [], []
    slides = sorted({0.0} | {s * k * SLIDE_STEP_CM for k in range(1, int(SLIDE_MAX_CM / SLIDE_STEP_CM) + 1) for s in (1, -1)},
                    key=abs)
    for role in [p.role for p in ps if _base(p.role) in WALL_ROLES and p.item is not None]:
        p = next(q for q in cur if q.role == role)
        gap0 = _core_gap(p, W, D)
        if gap0 > WALL_NEAR_CM:
            continue                                        # стоит не у стены ядра (диван посреди комнаты) — не наш случай
        share0 = _wall_share(_edge_gaps(P, x0, y0, p), gap0)
        if share0 >= BACK_MIN_SHARE:
            continue                                        # стена ядра = настоящая стена
        bx, by = _back(p)
        ax, ay = (0, 1) if bx else (1, 0)
        mates = {role} | {q.role for q in cur if _base(q.role) in TOGETHER.get(_base(role), ())}
        done = False
        for t in slides:
            gaps = _edge_gaps(P, x0, y0, p, ax * t, ay * t)
            s = min(gaps) - gap0
            if s <= 1.0 or s > PUSH_MAX_CM or not _at_wall([g - s for g in gaps], gap0):
                continue
            dx, dy = ax * t + bx * s, ay * t + by * s
            new = [_moved(q, dx, dy) if q.role in mates else q for q in cur]
            if not ad['poly'].buffer(0.5).contains(_full_fp(footprint(next(q for q in new if q.role == role)), x0, y0)):
                continue
            if check(new, cur):
                cur = new
                pushes.append({'role': role, 'by_cm': [round(dx, 1), round(dy, 1)], 'with': sorted(mates - {role})})
                done = True
                break
        if not done:
            (partly if share0 >= HALF_AT_WALL else stuck).append(role)
    return cur, pushes, stuck, partly


def _full_fp(fp, x0: float, y0: float):
    from shapely.affinity import translate
    return translate(fp, x0, y0)


def push_checker(ad: dict, cand: dict, ops: list):
    """Проверка сдвига для `push_to_walls`: проблемы полного контура (`post_check`) и жёсткие нормы на ядре, расширенном под
    расстановку (`ext_room`), — у новой расстановки не больше, чем у прежней на той же комнате."""
    W, D = cand['w'], cand['d']

    def bad(ps, ext):
        pc = TR.post_check(ad, cand, ps)
        sh = [_moved(p, ext['west'], ext['south']) for p in ps]
        return {(q['code'], q.get('role')) for q in pc['problems']} | set(hard_of(ext_room(W, D, ops, ext), sh))

    def check(new, old):
        ext = overhang(new, W, D)
        return bad(new, ext) <= bad(old, ext)
    return check


# ───────────────────────── выход без данных магазина ─────────────────────────

SHOP_LINKS = re.compile(r'(https?:|//[a-z0-9.-]+\.[a-z]{2,}|gdeslon|\berid=)', re.I)   # как `trial_bedroom.SHOP_LINKS`
BANNED_KEYS = {'url', 'url_direct', 'shop', 'img', 'img_hd', 'price', 'brand'}        # как `trial_bedroom.BANNED_KEYS`
OWN_TEXT_KEYS = ('name_en', 'colour_en')   # наш перевод (`names_en` сам не пускает магазин): латинское имя модели — не утечка
ROW_KEYS = ('role', 'style_role', 'sid', 'msid', 'mesh', 'name_en', 'colour_en', 'w', 'd', 'h', 'x', 'y', 'rot', 'corner',
            'shift_cm')


class ShopLeak(RuntimeError):
    pass


_NE: dict = {}


def _names_en(it: dict, role: str) -> dict:
    """`name_en`/`colour_en` — тем же правилом, что живое демо (`names_en.name_en`: ручной перевод → словарь → нейтральное по роли;
    без кириллицы, домена и названия магазина)."""
    import names_en as NE
    if not _NE:
        _NE.update(M=NE.load_map(), D=NE.load_dict())
    r = NE.name_en({'name': it.get('name') or '', 'sid': _sid(it)}, _base(role), _NE['M'], _NE['D'])
    return {'name_en': r['name'], 'colour_en': r['colour']}


def public_row(r: dict, mesh_ok) -> dict:
    """Строка предмета варианта по РАЗРЕШЁННОМУ списку (`ROW_KEYS`): роли, ключи товара и модели, размеры, место, английское
    название по контракту двух языков. Русское название, ссылка, картинка, цена и магазин в выход НЕ идут (советник 09.11c)."""
    it = r.get('_it') or {}
    out = {k: v for k, v in r.items() if k in ROW_KEYS}
    if mesh_ok is None:                                      # подставной банк тестов: моделей не проверяем
        out.update(msid=None, mesh='unchecked')
    elif not mesh_role(r['role']):
        out.update(msid=None, mesh='not_needed')            # ковёр и пр. — фото/плоскость, модель не положена
    elif mesh_ok(it):
        import flat215_demo as FD
        out.update(msid=FD._msid(r['sid']), mesh='model')
    else:
        out.update(msid=None, mesh='none')                  # в кадре — серая форма; в наборе такого быть не должно
    if it.get('name'):
        out.update(_names_en(it, r.get('style_role') or r['role']))
    return {k: out.get(k) for k in ROW_KEYS if k in out}


def lamp_rows(st: dict, rows: list, room_wd: tuple, mesh_ok, bank: list | None = None, idx: int | None = None) -> list:
    """ЛАМПА НАБОРА НА КОМОДЕ ТУРА (T-20261112-101) — тем же правилом, что у /demo (`flat215_demo.lamp_decor` → `dependent_decor`):
    место — решатель паспорта на комоде варианта (строки `rows` после прижима к стенам), товар — лампа набора, иначе следующая лампа
    ТОГО ЖЕ СТИЛЯ по банку (`bank` и номер набора в нём `idx`, как у /demo — T-20261112-122; без банка — только своя) с годной
    моделью (`mesh_ok`; подставной банк тестов — без проверки). Строка декора — по разрешённому списку, как
    предмет (`public_row`) + `strategy` и `place`; товар (цена, фото) сборщик берёт из каталога по `sid` (`trial_bundle._decor_item`).
    Лампы или комода нет — пусто; не встала ни одна — громко, пусто (комод тогда снимает `place`: атом «комод + лампа»)."""
    import dependent_decor as DD
    if not any(DD.is_lamp(r) and it for r, it in (st.get('items') or {}).items()):
        return []
    objs = [{'role': r['role'], 'x': r['x'], 'y': r['y'], 'rot': r.get('rot') or 0, 'w': r.get('w'), 'd': r.get('d'), 'h': r.get('h'),
             'sku': {'name': (r.get('_it') or {}).get('name')}} for r in rows]
    if not DD.carrier_objs(objs, DD.LAMP_CARRIERS):
        return []

    def model(it):                                  # габариты меша — для высоты лампы без высоты в карточке (`DD.lamp_pick`)
        if mesh_ok is None:
            return True, None
        if not mesh_ok(it):
            return None, 'нет годной модели'
        import flat215_demo as FD
        return FD._mesh_extents(FD._msid(_sid(it))) or True, None
    if bank is not None and idx is not None and 0 <= idx < len(bank):
        pool, at = list(bank), idx
        pool[at] = st                               # свой набор — каким он стоит в варианте (замены ленты), остальное — банк
    else:
        pool, at = [st], 0
    it, pl, why = DD.lamp_pick(pool, at, objs, room_wd, model)
    if not it:
        print(f"WARN:lamp: {st.get('style')} — лампы на комоде нет ни в цене, ни в 3D: {'; '.join(why) or 'нет кандидатов'}", flush=True)
        return []
    row = DD.lamp_row(pl, objs, None)
    del row['sku']
    pub = public_row({'role': DD.LAMP_ROLE, 'sid': _sid(it), 'w': it['w'], 'd': it['d'], 'h': it['h'], '_it': it},
                     None if mesh_ok is None else (lambda _x: True))
    if mesh_ok is not None:                         # модель проверена выше (`model`): лампа не из `PLACEABLE`, `public_row` её не ставит
        import flat215_demo as FD
        pub.update(msid=FD._msid(_sid(it)), mesh='model')
    return [{**row, **{k: v for k, v in pub.items() if k != 'role'}}]


def shop_tokens(styles: list) -> list:
    """Что нельзя выдать: имена магазинов (словарь `names_en`), домены ссылок и русские названия товаров наборов пробы."""
    import names_en as NE
    from urllib.parse import urlparse
    toks = {str(s).lower() for s in (NE.load_dict().get('shops') or [])}
    for st in styles:
        for it in (st.get('items') or {}).values():
            if not isinstance(it, dict):
                continue
            for k in ('shop', 'name', 'brand'):
                if it.get(k):
                    toks.add(str(it[k]).lower())
            for k in ('url', 'img'):
                host = urlparse(('https:' + it[k]) if str(it.get(k) or '').startswith('//') else str(it.get(k) or '')).hostname
                if host:
                    toks.add(host.lower().removeprefix('www.'))
    return sorted(t for t in toks if len(t) >= 3)


def assert_no_shop(obj, tokens: list) -> None:
    """Проверка ВЫВОДА целиком (как `trial_bedroom.assert_no_shop`): ни запрещённых полей, ни ссылок, ни названий магазинов и
    товаров. Найдено — `ShopLeak` (громко: это ошибка кода, а не данных)."""
    pats = [re.compile(r'(?<!\w)' + re.escape(t) + r'(?!\w)') for t in tokens]

    def walk(v, path, own=False):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in BANNED_KEYS or (isinstance(k, str) and (k.endswith('_url') or k == 'href')):
                    raise ShopLeak(f'запрещённое поле {path}.{k}')
                walk(x, f'{path}.{k}', k in OWN_TEXT_KEYS)
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                walk(x, f'{path}[{i}]')
        elif isinstance(v, str):
            s = v.lower()
            if SHOP_LINKS.search(s) or (not own and any(p.search(s) for p in pats)):
                raise ShopLeak(f'значение в {path}: {v[:80]}')
    walk(obj, '$')


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


def _write_scene(out: str, scene: dict, tokens: list = ()) -> None:
    """Сцена комнаты — с исходом кодом (`outcome_of`) и проверкой «без данных магазина» по всему JSON (`assert_no_shop`)."""
    scene['outcome'] = outcome_of(scene)
    assert_no_shop(scene, list(tokens))
    _write(os.path.join(out, 'scene.json'), scene)


def _no_slot(label: str):
    """Подставной решатель (тесты) не грузит машину — очередь не нужна."""
    return contextlib.nullcontext({'waited_s': 0.0})


def item_has_mesh(it: dict | None) -> bool:
    """МОДЕЛЬ ТОВАРА ГОДИТСЯ ДЛЯ КАДРА — то же правило, что у живого демо (`flat215_demo`, `has_mesh` сборки вариантов): модель
    лежит на сервере, подходит товару по цвету (`color_ok`), это не модель семейства другого цвета (`mesh_dark.family_colour_mismatch`)
    и привязка не отмечена «меш не того цвета» (`colour_flagged`). Проба брала только «модель есть в индексе» — и рисовала чужую
    модель семейства: у джапанди E оливковый «Филс» стал тёмной моделью представителя (привязка заблокирована, T-12/2)."""
    import flat215_demo as FD
    import mesh_dark as MDK
    if not it or not it.get('mid'):
        return False
    sid = f"{it['mid']}_{it['eid']}"
    m = FD._msid(sid)
    return bool(m) and m in FD._mesh_index() and FD.color_ok(m, it.get('name') or '') \
        and MDK.family_colour_mismatch(sid, m) is None and not FD.colour_flagged(sid)


def mesh_role(role: str) -> bool:
    """Роль рисуется моделью (ковёр, картина и прочее из `NOMESH_ROLES` — фото/плоскостью, модель им не положена)."""
    import flat215_demo as FD
    b = _base(role)
    # роль из двух слов («стол обеденный») — целиком: по первому слову («стол») её нет в `PLACEABLE`, и обеденный стол считался
    # «моделью не положена» — в туре серая коробка без модели (T-20261110-37, тур 4y0opq…)
    return (b in FD.PLACEABLE or b.split(' ')[0] in FD.PLACEABLE) and b not in FD.NOMESH_ROLES


def no_mesh_roles(st: dict) -> list:
    """Роли набора, которым модель положена, а годной (`item_has_mesh`) нет."""
    return sorted(r for r, it in (st.get('items') or {}).items() if it and mesh_role(r) and not item_has_mesh(it))


CORE_ROLES = ('диван',) + BEARERS     # без годной модели этих ролей набор не показываем (их не снять из комнаты)


def eligible(st: dict, mesh_ok=None) -> bool:
    """Набор годен для пробы: диван и носитель ТВ (если он есть) — с годной моделью. Прочее без модели снимается из набора
    (`usable_set`): лучше на кресло меньше, чем серая коробка или модель чужого цвета."""
    mesh_ok = mesh_ok or item_has_mesh
    items = st.get('items') or {}
    return bool(items.get('диван')) and all(mesh_ok(items[r]) for r in CORE_ROLES if items.get(r))


def usable_set(st: dict, mesh_ok, picker=None) -> dict:
    """Копия набора без предметов, которым положена модель, а годной нет (`mesh_ok=None` — подставной банк тестов: как есть).
    С лентой витрины (`picker`, T-20261110-37) такой предмет не снимается, а ЗАМЕНЯЕТСЯ товаром ленты своего стиля с годной моделью,
    ближайшим по размеру (`FeedPicker.nearest`): «обеденного стола нет» (владелец 10.11 TG 869) — у набора без модели стола. Заменённые
    роли — `no_mesh_swapped`; заменить нечем — снимается, как раньше (`no_mesh_dropped`)."""
    if mesh_ok is None:
        return st
    items = dict(st.get('items') or {})
    bad = sorted(r for r, it in items.items() if it and mesh_role(r) and not mesh_ok(it))
    swapped = []
    for r in bad:
        alt = picker.nearest(_base(r), st.get('style'), items[r]) if picker is not None and _base(r) not in CORE_ROLES else None
        if alt is not None:
            items[r] = alt
            swapped.append(r)
    gone = [r for r in bad if r not in swapped]
    return dict(st, items={r: it for r, it in items.items() if r not in gone}, no_mesh_dropped=gone,
                **({'no_mesh_swapped': swapped} if swapped else {}))


# ───────────────────────── товары ленты витрины под место (T-20261110-37, план `tour-as-demo-01`) ─────────────────────────

def feed_item(row: dict) -> dict | None:
    """Строка ленты витрины (`demo_feeds`) → товар набора, как у банка: ключ поставщика, название, размеры, цена и ссылка. Фото — нет:
    у строки витрины только её плитка, а не адрес магазина (кадр DEV тогда рисует ковёр ровным, `render_inputs`); товар в туре
    сборщик берёт из каталога по ключу (`trial_bundle.catalog_goods`, плитка — витрины)."""
    sid = row.get('sid') or ''
    if '_' not in sid or not row.get('name'):
        return None
    mid, eid = sid.split('_', 1)
    return {'mid': mid, 'eid': eid, 'name': row['name'], 'w': row.get('w'), 'd': row.get('d'), 'h': row.get('h'),
            'price': row.get('price'), 'url': row.get('url'), 'shop': row.get('shop'), 'from_feed': True}


def _dims_of(it: dict) -> tuple:
    return (it.get('w') or it.get('dia') or 0, it.get('d') or it.get('dia') or 0)


class FeedPicker:
    """Товар ленты витрины своего стиля на место предмета: модель — правилом пробы (`mesh_ok`, по умолчанию `item_has_mesh`),
    у дивана — та же форма, что у места (`_sofa_corner`)."""

    def __init__(self, data: dict, mesh_ok=None, kind: str = 'living'):
        self.data, self.mesh_ok, self.kind, self._ok = data or {}, mesh_ok, kind, {}

    def ok(self, role: str, row: dict) -> bool:
        if not mesh_role(role):
            return True
        sid = row.get('sid')
        if sid not in self._ok:
            it = feed_item(row)
            self._ok[sid] = bool(it) and (self.mesh_ok is None or bool(self.mesh_ok(it)))
        return self._ok[sid]

    def for_slot(self, role: str, style: str, slot: tuple, corner: bool | None = None, hmax: float | None = None) -> dict | None:
        """Самый крупный товар стиля, который влезает в место (`demo_feeds.slot_pick`) → товар набора. `hmax` — не выше предмета места
        (геометрия берёт высоту самого низкого стиля: высокий диван у окна — `WINDOW_BLOCKED`)."""
        import demo_feeds as DF
        row = DF.slot_pick(self.data, self.kind, role, style, slot,
                           ok=lambda r: self.ok(role, r) and (corner is None or _sofa_corner(feed_item(r)) == bool(corner))
                           and (not hmax or not r.get('h') or r['h'] <= hmax + DF.FIT_TOL_CM))
        return feed_item(row) if row else None

    def nearest(self, role: str, style: str, it: dict) -> dict | None:
        """Замена товару без модели: влезающий в его размер (как `for_slot`), иначе ближайший по ширине и глубине."""
        import demo_feeds as DF
        w, d = _dims_of(it)
        got = self.for_slot(role, style, (w, d)) if w and d else None
        if got is not None:
            return got
        best = None
        for r in DF.kind_rows(self.data, self.kind, role):
            if style not in DF.styles_of(r) or not DF.model_ok(role, r) or not self.ok(role, r) or not (r.get('w') and r.get('d')):
                continue
            key = (abs(r['w'] - w) + abs(r['d'] - d), r.get('name') or '')
            if best is None or key < best[0]:
                best = (key, r)
        return feed_item(best[1]) if best else None


def window_caps(room, ps: list) -> dict:
    """Потолок высоты предмета на месте у окна — тем же правилом, что `WINDOW_BLOCKED` (`planner/validate.py`: выше max(подоконник, 80)
    и ближе 10 см к окну): {роль места: см}. Место не у окна — без потолка. Высоты у мест геометрии нет (решатель её не пишет)."""
    from planner.geometry import footprint, opening_polygon
    caps: dict = {}
    for op in getattr(room, 'openings', None) or []:
        if op.kind != 'window':
            continue
        win, top = opening_polygon(room, op), max(op.sill_cm, 80)
        for p in ps:
            if p.item is not None and footprint(p).distance(win) < 10:
                caps[p.role] = min(caps.get(p.role, top), top)
    return caps


def screen_caps(room, ps: list) -> dict:
    """Потолок ширины ВИРТУАЛЬНОГО экрана носителя ТВ, что стоит спиной к стене с окном, — тем же правилом, что `SCREEN_OVER_WINDOW`
    (`planner/validate.py`: носитель ближе 40 см к стене окна, экран заходит на проём больше 10 см): {роль места: см экрана}. Свой
    носитель геометрии мог пройти по вейверу решателя (`SCREEN_WINDOW_WAIVED` — на время одного решения), подстановка его не имеет —
    лофт 4y0opq падал так на геометрии 1 (T-37). Носитель не у окна — без потолка."""
    from planner.geometry import footprint
    caps: dict = {}
    for op in getattr(room, 'openings', None) or []:
        if op.kind != 'window':
            continue
        o0, o1 = op.offset_cm, op.offset_cm + op.width_cm
        for p in ps:
            if p.item is None or _base(p.role) not in ('тв-тумба', 'стенка'):
                continue
            back = {0: 'south', 180: 'north', 90: 'west', 270: 'east'}.get(int(p.rot) % 360)
            if back != op.wall:
                continue
            fb = footprint(p).bounds
            gap = {'south': fb[1], 'north': room.depth_cm - fb[3], 'west': fb[0], 'east': room.width_cm - fb[2]}[op.wall]
            if gap > 40:
                continue
            c = p.x if op.wall in ('south', 'north') else p.y
            lo, hi = 0.0, 1000.0
            for _ in range(40):                      # наибольший экран с заходом на проём ≤ 10 см (заход растёт с шириной)
                s = (lo + hi) / 2
                if min(c + s / 2, o1) - max(c - s / 2, o0) > 10:
                    hi = s
                else:
                    lo = s
            caps[p.role] = min(caps.get(p.role, lo), lo)
    return caps


def _screen_of(it: dict, key: str) -> float:
    from planner.tv import screen_width_cm
    return screen_width_cm(float(_dims_of(it)[0] or 0), 'стенка' if _base(key or '') == 'стенка' else 'тв-тумба', 'min')


def slot_fit(st: dict, geo_ps: list, picker: FeedPicker, mesh_ok=None, full: bool = False, caps: dict | None = None,
             screens: dict | None = None) -> tuple[dict, list]:
    """Набор стиля → товары под МЕСТА расстановки чужой геометрии (подстановка упавшего стиля, план `tour-as-demo-01` Б): свой товар
    остаётся, если влезает в место предмета геометрии и у него годная модель; иначе — самый крупный влезающий товар ленты витрины своего
    стиля (`FeedPicker.for_slot`); нечем — роли нет. `full` — заменить все предметы товарами ленты под место (вторая попытка, когда свои
    товары на этих местах нарушают правила). `caps` — потолок высоты мест у окна (`window_caps`), `screens` — потолок экрана носителя ТВ
    у окна (`screen_caps`). → (набор, заменённые роли)."""
    import demo_feeds as DF
    from planner.tv import screen_width_cm
    items = dict(st.get('items') or {})
    style, swaps = st.get('style'), []
    for p in geo_ps:
        base = _base(p.role)
        if base == 'тв' or p.item is None:
            continue
        srole, it = _style_item(dict(st, items=items), p.role)
        slot, hmax, smax = (p.item.w_cm, p.item.d_cm), (caps or {}).get(p.role), (screens or {}).get(p.role)
        own_ok = bool(it) and DF.fits(base, dict(zip(('w', 'd'), _dims_of(it))), slot) and \
            (not hmax or not it.get('h') or it['h'] <= hmax + DF.FIT_TOL_CM) and \
            (smax is None or _screen_of(it, srole or p.role) <= smax) and \
            (not mesh_role(p.role) or mesh_ok is None or bool(mesh_ok(it)))
        if own_ok and not full:
            continue
        if smax is not None:                         # тумба ленты — не шире, чем даёт экран вне окна
            slot = (min(slot[0], smax / max(screen_width_cm(1.0, 'тв-тумба', 'min'), 1e-6)), slot[1])
        alt = picker.for_slot(base, style, slot, corner=bool(p.item.corner) if base == 'диван' else None, hmax=hmax)
        if alt is None:
            if not own_ok and it is not None:
                items.pop(srole or p.role, None)
            continue
        if base == 'тв-тумба':
            items.pop('стенка', None)
        key = 'тв-тумба' if base == 'тв-тумба' else (srole or p.role)
        items[key] = alt
        swaps.append(key)
    return dict(st, items=items), sorted(set(swaps))


def _style_ranking(sets: list, band: str) -> dict:
    """ПЕРЕБОР ШАБЛОНОВ ПО СТИЛЮ (владелец 09.11: шаблон → товары под него → нет → следующий; не подошёл ни один — пусто).
    Наборы каждого стиля по очереди предпочтения: годный (`eligible`) набор этой полосы или ниже (у стиля нет годного набора в
    полосе — следующая полоса ВНИЗ: товары мельче, в ядро влезут). Ключ — общий с /demo `bank_invariants.selection_key`
    (T-20261112-122): полное ядро (диван, столик, носитель ТВ) → годные модели ядра → годные модели прочего («без модели» —
    СТРОГО, правилом демо `item_has_mesh`) → дыры состава → номер. Число предметов НЕ награждается: лишний комод не делает набор
    «лучше» (прежде набор без столика, но с комодом выигрывал, и гостиная выходила пустой). → {стиль: [номера наборов]}."""
    import bank_invariants as BI
    import flat215_demo as FD
    names = [b for b, _ in BANDS]
    lower = names[:names.index(band) + 1][::-1] if band in names else [band]
    rank: dict = {}
    for i, st in enumerate(sets, 1):
        items = st.get('items') or {}
        if st.get('band') not in lower or 'диван' not in items or FD.hidden(st) or not eligible(st):
            continue
        nm = no_mesh_roles(st)
        core_nm = sum(1 for r in nm if ('тв-тумба' if _base(r) in BEARERS else _base(r)) in BI.CORE_ROLES)
        key = (lower.index(st['band']),) + BI.selection_key(st, core_nm, len(nm)) + (i,)
        rank.setdefault(st.get('style') or '', []).append((key, i))
    return {s: [i for _, i in sorted(v)] for s, v in rank.items()}


def _pick_styles(sets: list, band: str) -> list:
    """По ОДНОМУ набору на стиль — первый по `_style_ranking`; порядок стилей — `STYLES`."""
    rank = _style_ranking(sets, band)
    picked = [rank[s][0] for s in STYLES if s in rank]
    picked += [v[0] for k, v in sorted(rank.items()) if k not in STYLES]
    return picked[:len(STYLES)]


def build(trial_id: str, result: dict, sets: list | None = None, solver=run_solver, pick=_pick_styles, slot=None,
          mesh_ok=None, feeds: dict | None = None) -> dict:
    """Проба целиком → сцена (`scene.json`). Отказ адаптера — сцена со статусом `refused`, не исключение. Исход для конвейера
    и страницы — поле `outcome` (`outcome_of`). Подбор и расстановка — под общей очередью машины (`machine_slot`).
    `mesh_ok` — правило «годная модель» (по умолчанию у настоящего отбора — `item_has_mesh`; у подставного банка тестов — не
    проверяется). Картинки товаров для кадров — `media.json` рядом (внутренний файл пробы, в выход комнаты не входит).
    `feeds` — ленты витрины (`demo_feeds.load`; у настоящего отбора — по умолчанию): замена товара без модели и подстановка упавшего
    стиля на обставленную геометрию товарами под место (T-20261110-37). Подставной банк тестов без `feeds` — без них."""
    t0 = time.time()
    if mesh_ok is None and pick is _pick_styles:
        mesh_ok = item_has_mesh
    if feeds is None and pick is _pick_styles:
        import demo_feeds as DF
        feeds = DF.load()
    picker = FeedPicker(feeds, mesh_ok) if feeds else None
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
    # T-20261112-98/2: тип и название комнаты — решателю (кухня-гостиная → стол обязателен; правило — в zones.json
    # `scenario_needs.by_room_kind`, передача — env SCENE_ROOM_KIND/SCENE_ROOM_TITLE в `run_solver`)
    for c in ad['candidates']:
        c.setdefault('room_kind', (ad.get('room') or {}).get('kind'))
        c.setdefault('room_title', (ad.get('room') or {}).get('name'))
    # входы комнаты — для исхода «нет места» (проходная или нет, `outcome_of`); пишем до солвера: ранние выходы тоже его читают
    scene['entries'] = sum(1 for o in ad['ops'] if o['kind'] in ('door', 'opening'))
    scene.update(status='pending')                         # подбор идёт: читатель сцены видит `pending`, а не пустоту
    _write_scene(OUT, scene)
    # ── полоса, стили, геометрия (часть «адаптера»: это ещё до солвера) ──
    # ПЕРЕБОР ШАБЛОНОВ (владелец 09.11): полоса → наборы стилей (`pick`: у стиля нет годного набора — его полоса ниже) → влезает
    # ли обязательная группа в ядро → нет — полоса ниже; не влезло нигде — комната ПУСТАЯ, исход `no_products`
    if sets is None:
        sets = json.load(open(sets_path(), encoding='utf-8'))
        drop_gone(sets)
    band, bflags = band_for(ad['candidates'][0]['area_m2'])
    flags = list(ad['flags']) + bflags
    i_band = [b for b, _ in BANDS].index(band)
    picked, groups, cands, chosen_sets = [], [], [], {}
    while i_band >= 0:
        band = BANDS[i_band][0]
        picked = pick(sets, band)
        if picked:
            chosen_sets = {i: usable_set(sets[i - 1], mesh_ok, picker) for i in picked}
            groups = shape_groups([chosen_sets[i] for i in picked], band)
            for g in groups:                                     # номер набора в банке — для отчёта
                g['styles'] = [(st, next(i for i in picked if chosen_sets[i] is st)) for st, _ in g['styles']]
            # ядро годно, если обязательная группа влезает реальными товарами КАЖДОЙ геометрии
            cands = [c for c in ad['candidates'] if all(TR.group_fits(c['w'], c['d'], g['need']) for g in groups)]
            if cands:
                break
        i_band -= 1
        flags.append('band_lowered')
    tokens = shop_tokens([sets[i - 1] for i in picked]) if picked else []
    if not cands:
        scene.update(status='no_products', refusal={'code': 'living_core_small',
                                                    'detail': 'диван и ТВ реальных товаров не влезают ни в одно ядро ни на одной полосе'})
        scene['timings'] = {'adapter_s': round(time.time() - t0, 3), 'solver_s': 0, 'assembly_s': 0,
                            'total_s': round(time.time() - t0, 3)}
        _write_scene(OUT, scene, tokens)
        return scene
    styles = [chosen_sets[i] for i in picked]
    if len(styles) < len(STYLES):
        flags.append(f'styles_{len(styles)}_of_{len(STYLES)}')
    flags += sorted(f"style_band_lowered:{st.get('style')}" for st in styles if st.get('band') != band)
    flags += sorted(f"no_mesh_dropped:{st.get('style')}" for st in styles if st.get('no_mesh_dropped'))
    flags += sorted(f"no_mesh_swapped:{st.get('style')}" for st in styles if st.get('no_mesh_swapped'))
    sets_file = os.path.join(OUT, 'trial-sets.json')
    # геометрии — первые номера снимка; за ними свои наборы стилей, урезанные до ролей геометрии (см. `trim_to_geometry`)
    geo_of = {id(st): g['set'] for g in groups for st, _ in g['styles']}
    snap = [g['set'] for g in groups] + [trim_to_geometry(st, geo_of[id(st)]) for st in styles]
    _write(sets_file, snap)
    # очередь наборов стиля — для «следующего набора того же стиля» (настоящий отбор; у подставного `pick` тестов — нет)
    alt_rank = _style_ranking(sets, band) if pick is _pick_styles else {}
    used = {}
    for i, st in chosen_sets.items():
        used.setdefault(st.get('style'), set()).add(i)
    _write(os.path.join(OUT, 'adapter.json'), TR.summary(ad))
    t_prep = time.time() - t0 - t_ad
    # ── солвер: по ОДНОЙ геометрии на форму дивана (обе — параллельно); проверка по полному контуру; есть проблемы —
    #    вторая петля дверей. Геометрию не расставить (крупнейшие товары не сходятся, напр. носитель ТВ) — стили этой
    #    формы СРАЗУ считаются своими наборами на том же ядре (не дожидаясь второй формы). Кончился бюджет и что-то уже
    #    расставлено — оставшиеся прогоны снимаем, результат честно частичный; не расставлено ничего — ждём аварийный предел.
    #    Потом — следующее ядро, пока в бюджете ──
    t1 = time.time()
    tries, chosen, media = [], None, {}
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
            if sr.get('stderr'):                           # текст ошибки солвера — в журнал папки пробы, не в сцену
                with _RUN_LOCK, open(os.path.join(OUT, 'solver-stderr.log'), 'a', encoding='utf-8') as f:
                    f.write(f"== {tag}\n{sr['stderr']}\n")
            # снят по бюджету (`_stop_running` → SIGTERM, rc −15) — не сбой решателя: прежде писалось `no_artifact` (тур 4y0opq…,
            # T-20261110-37: свои наборы трёх стилей запущены на 51-й с и сняты на 55-й)
            if sr.get('rc') == -signal.SIGTERM:
                return dict(rec, error='stopped'), None
            return dict(rec, error='solver_error' if sr.get('stderr') else 'no_artifact'), None
        ps = placements_of(sr['art'])
        if not any(_base(p.role) == 'диван' for p in ps):
            # солвер честно сказал «не расставить» (`_infeasible_reason`) — пустая комната не результат
            inf = sr['art'].get('_infeasible_reason')
            return dict(rec, rc='empty', infeasible=inf.get('code') if isinstance(inf, dict) else inf), None
        pc = TR.post_check(ad, cand, ps)
        hard = hard_of(core_room(cand, sr['openings']), ps)
        # предмет у стены ядра, которому не встать к настоящей стене (ниша) — тоже изъян расстановки: такая геометрия хуже
        _, _, stuck, _ = push_to_walls(ad, cand, ps, push_checker(ad, cand, sr['openings']))
        rec.update(post_ok=pc['ok'], problems=pc['problems'], hard=hard, off_wall=stuck)
        return rec, {'sr': sr, 'ps': ps, 'pc': pc, 'hard': hard,
                     'score': (len(pc['problems']) + len(hard) + len(stuck), len(sr.get('missing') or []))}

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
                elif res is None and u['kind'] == 'geometry' and len(u['styles']) > 1 and \
                        (STOP_S - elapsed() >= OWN_MIN_S or not (best or have) or picker is None):
                    own = own_units(u, u['styles'])
                    units = [x for x in units if x is not u] + own
                    for v in own:
                        submit(v, 'left')
        return best, units

    def own_units(u, styles):
        return [{'tag': f"s{n}", 'kind': 'own', 'n': n_geo + picked.index(n) + 1, 'shape': u['shape'], 'source': None,
                 'styles': [(st, n)], 'from': u['tag']} for st, n in styles]

    def next_unit(style, frm):
        """СЛЕДУЮЩИЙ НАБОР ТОГО ЖЕ СТИЛЯ (T-20261112-122, как /demo `flat215_demo.choose_banks`): обязательное у набора стиля не встало —
        его свой набор следующего по очереди `_style_ranking` (ещё не пробованный) → единица «свой набор»; снимок наборов дополняется
        (номера прежних не меняются, прогоны к этому моменту закончены). Пробовать нечего — None."""
        for j in alt_rank.get(style, []):
            if j in used.setdefault(style, set()):
                continue
            used[style].add(j)
            st2 = usable_set(sets[j - 1], mesh_ok, picker)
            shape = 'corner' if _sofa_corner((st2.get('items') or {}).get('диван')) else 'straight'
            geo = next((g['set'] for g in groups if g['shape'] == shape), None) or geometry_set([st2], band)[0]
            snap.append(trim_to_geometry(st2, geo))
            _write(sets_file, snap)
            chosen_sets[j] = st2
            return {'tag': f's{j}', 'kind': 'own', 'n': len(snap), 'shape': shape, 'source': None, 'styles': [(st2, j)],
                    'from': frm, 'next_set': True}
        return None

    def retry_next(ci, cand, best, units, pool):
        """Стиль, у которого обязательное не встало (своя расстановка не вышла, её проверка не прошла или роль ядра — диван, столик,
        носитель ТВ — есть в наборе, но в комнату не встала), — следующим набором того же стиля (до `RETRY_SETS`), пока есть время.
        Встал чисто и ядра потеряно меньше — вместо прежнего; нет — прежний остаётся (дальше `rescue`). → units."""
        def lost(v):
            """Сколько обязательного потеряно: сбой/жёсткое/проверка — больше любой потери ядра; иначе — роли ядра вне комнаты."""
            if v.get('failed') or v['hard'] or not v['post_ok']:
                return 99
            return sum(1 for r in v.get('absent_roles') or [] if _base(r) in CORE_PLACE) + \
                (0 if any(_base(r['role']) == 'диван' for r in v['items']) else 1)
        _, draft, _ = assemble(ci, cand, best, units)
        was = {v['style']: lost(v) for v in draft}
        fails = [st for st, k in was.items() if k]
        for style in fails:
            for _ in range(RETRY_SETS):
                if STOP_S - elapsed() < OWN_MIN_S:
                    return units
                old = next(((u, x) for u in units for x in u['styles'] if x[0].get('style') == style), None)
                nu = next_unit(style, old[0]['tag'] if old else None) if old else None
                if nu is None:
                    break
                got, _ = solve_units([nu], ci, cand, pool, have=True)
                if nu['tag'] not in got:
                    continue
                st2, j = nu['styles'][0]
                nv = place(0, got[nu['tag']], st2, j, cand)
                if lost(nv) >= was[style]:
                    continue
                ou, ox = old
                ou['styles'] = [x for x in ou['styles'] if x is not ox]
                units = [u for u in units if u['styles']] + [nu]
                best[nu['tag']] = got[nu['tag']]
                flags.append(f'style_next_set:{style}')
                break
        return units

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
                why = next((t.get('infeasible') or t.get('error') or t.get('rc') for t in reversed(tries)
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
            for st, n in u['styles']:
                variants.append(place(gi, b, st, n, cand))
        return geometries, variants, problems

    def place(gi, b, st, n, cand):
        """Товары стиля `st` на места расстановки `b` (геометрия `gi`) → вариант: подстановка, прижим к стенам, снятие нарушителей
        норм, проверка по контуру. Одна функция для своей геометрии стиля и для подстановки упавшего стиля (`rescue`)."""
        x0, y0 = cand['rect'][0], cand['rect'][1]
        croom = core_room(cand, b['sr']['openings'])
        check = push_checker(ad, cand, b['sr']['openings'])
        ps, absent, rows = substitute(b['ps'], st, cand['w'], cand['d'])
        ps, gone = drop_window_chairs(croom, ps)
        absent = absent + gone
        rows = [r for r in rows if r['role'] not in gone]
        ps, pushes, stuck, partly = push_to_walls(ad, cand, ps, check)

        def hard_ext(q):
            e = overhang(q, cand['w'], cand['d'])
            return hard_of(ext_room(cand['w'], cand['d'], b['sr']['openings'], e),
                           [_moved(p, e['west'], e['south']) for p in q])
        ps, dropped = drop_norm_breakers(hard_ext, ps)
        absent = absent + dropped
        rows = [r for r in rows if r['role'] not in dropped]
        at = {p.role: p for p in ps}
        for r in rows:                              # место строки — после прижима к стене
            if r['role'] in at:
                r.update(x=round(at[r['role']].x, 1), y=round(at[r['role']].y, 1))
        # АТОМ «КОМОД + ЛАМПА» (T-20261112-122, паспорт living.json light.dresser_lamp): комод показываем только с лампой на нём.
        # Лампа не встала (нет в наборе, не влезла на столешницу, без модели) — комода в варианте нет: необязательный предмет,
        # строкой `skipped_optional`; обязательное (диван, столик, ТВ) от этого не меняется
        decor = lamp_rows(st, rows, (cand['w'], cand['d']), mesh_ok, sets, n - 1)
        import bank_invariants as BI
        lone = BI.dresser_atom_drop([r['role'] for r in rows], bool(decor))
        if lone:
            ps = [p for p in ps if p.role not in lone]
            rows = [r for r in rows if r['role'] not in lone]
            absent = absent + lone
        media[st.get('style')] = {r['role']: (r.get('_it') or {}).get('img') for r in rows}
        ext = overhang(ps, cand['w'], cand['d'])
        spc = TR.post_check(ad, cand, ps)
        probs = spc['problems'] + [{'code': 'back_off_wall', 'role': r} for r in stuck]
        shard = hard_of(ext_room(cand['w'], cand['d'], b['sr']['openings'], ext),
                        [_moved(p, ext['west'], ext['south']) for p in ps])
        return {'style': st.get('style'), 'set_index': n, 'set_id': st.get('set_id'), 'geometry': gi,
                'items': [public_row(r, mesh_ok) for r in rows], 'absent_roles': absent,
                'decor': decor,                     # лампа на комоде (T-20261112-101)
                'skipped_optional': [{'role': r, 'why': 'lamp_not_placed'} for r in lone],
                'no_mesh_dropped': st.get('no_mesh_dropped') or [], 'pushed': pushes,
                'dropped_for_norms': dropped, 'partly_at_wall': partly,
                'hard': shard, 'post_ok': not probs, 'problems': probs, 'placements': _ps_json(ps, x0, y0),
                'placements_core': _ps_json(ps), '_ext': ext,
                # МЕСТО ПРЕДМЕТА (T-20261110-37 А): след расстановки, на которую встал стиль (у геометрии — крупнейший товар роли, прошедший
                # правила) — по нему сборщик режет ленту замен «влезает в своё место» (`trial_bundle.feeds_for`), а не по нынешнему товару
                'slots': {p.role: [round(p.item.w_cm, 1), round(p.item.d_cm, 1)] for p in b['ps'] if p.item is not None}}

    def rescue(variants, cand, best, units):
        """ВСЕ СТИЛИ (план `tour-as-demo-01` Б, владелец 10.11 TG 873): стиль, чья геометрия не вышла (`layout_failed`: снят по
        бюджету, сбой, таймаут) или снят проверкой (`style_rejected`), ставится на ОБСТАВЛЕННУЮ геометрию (той же формы дивана —
        первой) товарами под её места (`slot_fit`): сперва свои товары, что влезают, остальное — лентой витрины; не прошло — все
        предметы лентой под место. Не встал нигде — остаётся упавшим со своей причиной. → сколько подставлено."""
        if picker is None:
            return 0
        hosts = sorted(((gi, u, best[u['tag']]) for gi, u in enumerate(units) if u['tag'] in best),
                       key=lambda h: h[2]['score'])
        got = 0
        for k, v in enumerate(variants):
            st = chosen_sets.get(v.get('set_index'))
            if not v.get('failed') or st is None or not hosts:
                continue
            why = (v.get('problems') or [{}])[0].get('code')
            done, tried = None, []
            # свой набор, затем следующие наборы того же стиля (T-20261112-122, до `RETRY_SETS`): подстановка без решателя — дёшево,
            # а у соседнего набора стиля может найтись свой товар под место (низкий диван под окном), которого нет в ленте
            queue = [(st, v['set_index'])] + [(usable_set(sets[j - 1], mesh_ok, picker), j) for j in
                                               [j for j in alt_rank.get(v['style'], []) if j != v['set_index']][:RETRY_SETS]]
            for cst, cn in queue:
                shape = 'corner' if _sofa_corner((cst.get('items') or {}).get('диван')) else 'straight'
                for gi, u, b in sorted(hosts, key=lambda h: h[1]['shape'] != shape):
                    croom = core_room(cand, b['sr']['openings'])
                    caps, screens = window_caps(croom, b['ps']), screen_caps(croom, b['ps'])
                    for full in (False, True):
                        fst, swaps = slot_fit(cst, b['ps'], picker, mesh_ok, full, caps, screens)
                        nv = place(gi, b, fst, cn, cand)
                        sofa = any(_base(r['role']) == 'диван' for r in nv['items'])
                        if nv['post_ok'] and not nv['hard'] and sofa:
                            done = dict(nv, substituted={'why': why, 'from_geometry': v.get('geometry'), 'swapped': swaps,
                                                         'mode': 'all' if full else 'misfit'})
                            break
                        # почему не встал — кодом (правило и роль), для разбора и журнала
                        tried.append({'set_index': cn, 'geometry': gi, 'mode': 'all' if full else 'misfit', 'no_sofa': not sofa,
                                      'hard': nv['hard'], 'problems': sorted({p.get('code') for p in nv['problems']}),
                                      'absent': nv['absent_roles'], 'swapped': swaps})
                    if done:
                        break
                if done:
                    if cn != v['set_index']:
                        chosen_sets[cn] = cst
                        flags.append(f"style_next_set:{v['style']}")
                    break
            if done:
                variants[k] = done
                flags.append(f"style_substituted:{v['style']}")
                got += 1
            elif tried:
                v['rescue_tried'] = tried
        return got

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
                if bad and STOP_S - elapsed() >= (OWN_MIN_S if picker is not None else 0):
                    for u in [u for u in units if u['kind'] == 'geometry' and any(st.get('style') in bad for st, _ in u['styles'])]:
                        move = [(st, n) for st, n in u['styles'] if st.get('style') in bad]
                        u['styles'] = [x for x in u['styles'] if x not in move]
                        own = own_units(u, move)
                        got, _ = solve_units(own, ci, cand, pool, have=True)
                        units = units + own
                        best.update(got)
                    chosen = (chosen[0], ci, cand, best, units)
                # обязательное у стиля так и не встало — следующий набор того же стиля (T-20261112-122, как у /demo)
                if alt_rank:
                    units = retry_next(ci, cand, best, units, pool)
                    chosen = (chosen[0], ci, cand, best, units)
            elif alt_rank:
                # ни одна расстановка не вышла ни на одном ядре — по следующему набору каждого стиля, своими наборами
                retry = [nu for nu in (next_unit(st.get('style'), None) for st in styles) if nu is not None]
                for ci, cand in enumerate(cands):
                    if not retry or elapsed() > STOP_S:
                        break
                    best, units = solve_units(retry, ci, cand, pool)
                    if best:
                        lost = sum(len(u['styles']) for u in units if u['tag'] not in best)
                        chosen = ((lost, sum(b['score'][0] for b in best.values())), ci, cand, best, units)
                        flags += sorted(f"style_next_set:{st.get('style')}" for u in units if u['tag'] in best
                                        for st, _ in u['styles'])
                        break
    except Exception as e:  # noqa: BLE001 — разбираем только очередь машины, остальное — наверх
        if not _slot_timeout(e):
            raise
        scene.update(status='failed', flags=flags, problems=[{'code': 'queue_timeout',
                                                              'detail': f'нет места в очереди тяжёлых задач за {SLOT_TIMEOUT_S:.0f} с'}])
        scene['timings'] = {'adapter_s': round(t_ad + t_prep, 3), 'solver_s': 0, 'assembly_s': 0,
                            'total_s': round(time.time() - t0, 3), 'queue_s': round(time.time() - t1, 3)}
        _write_scene(OUT, scene, tokens)
        return scene
    t_sol = time.time() - t1 - clock['queue']
    scene['tries'] = tries
    if chosen is None:
        # ни одна расстановка этих товаров не вышла ни на одном ядре — «нет подходящих товаров под шаблоны», комната пустая
        scene.update(status='no_products', flags=flags, problems=[{'code': 'solver_failed',
                                                                   'detail': 'ни одна расстановка не получилась ни на одном ядре'}])
        scene['timings'] = {'adapter_s': round(t_ad + t_prep, 3), 'solver_s': round(t_sol, 3), 'assembly_s': 0,
                            'total_s': round(elapsed(), 3), 'queue_s': round(clock['queue'], 3)}
        _write_scene(OUT, scene, tokens)
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
    t_res = time.time()
    rescued = rescue(variants, cand, best, units)
    t_res = time.time() - t_res
    order = {s: i for i, s in enumerate(STYLES)}
    variants.sort(key=lambda v: order.get(v['style'], 99))
    ok_styles = [v for v in variants if v['post_ok'] and not v['hard']]
    # ни один стиль не прошёл — комната ПУСТАЯ с исходом «нет подходящих товаров» (владелец 09.11), а не «частично»
    status = 'no_products' if not ok_styles else ('ok' if not problems and len(ok_styles) == len(variants) else 'partial')
    if elapsed() > BUDGET_S:
        flags.append('over_budget')
    if solver is run_solver and beam_off(cand):
        flags.append('beam_off_large')
    # ── ядро, расширенное под мебель, прижатую к стенам ниш: прямоугольник кадра и все координаты «в ядре» — в нём ──
    ext = {s: max([(v.get('_ext') or {}).get(s, 0.0) for v in ok_styles] or [0.0]) for s in ('west', 'east', 'south', 'north')}
    for v in variants:
        v.pop('_ext', None)
    sx, sy = ext['west'], ext['south']

    def sh_ps(ps):
        return [dict(q, x=round(q['x'] + sx, 1), y=round(q['y'] + sy, 1)) for q in ps]

    def sh_j(juncs):
        return [(w, round(a + (sx if w in ('south', 'north') else sy), 1), round(b + (sx if w in ('south', 'north') else sy), 1))
                for w, a, b in juncs]
    for g in geometries:
        g.update(placements_core=sh_ps(g['placements_core']), openings_core=shift_ops(g['openings_core'], ext))
    for v in variants:
        v['placements_core'] = sh_ps(v['placements_core'])
        for r in v['items']:
            r.update(x=round(r['x'] + sx, 1), y=round(r['y'] + sy, 1))
    x0, y0, x1, y1 = cand['rect']
    W2, D2 = cand['w'] + ext['west'] + ext['east'], cand['d'] + ext['south'] + ext['north']
    scene.update(status=status, flags=sorted(set(flags + cand['flags'] + (['core_extended'] if any(ext.values()) else []))),
                 problems=problems, band=band, room={**ad['room'], 'panel': ad['panel']},
                 # `rect`, `w`, `d` — ядро кадра (с прижатой к стенам ниш мебелью); `solver_rect` — ядро, в котором считал солвер;
                 # `ext_cm` — на сколько расширено по сторонам (координаты «в ядре» сдвинуты на запад/юг)
                 core={'rect': [x0 - sx, y0 - sy, x1 + ext['east'], y1 + ext['north']], 'w': W2, 'd': D2,
                       'area_m2': cand['area_m2'], 'solver_rect': cand['rect'], 'ext_cm': ext,
                       'core_share': cand['core_share'], 'index': ci,
                       'residues': [dict({k: v for k, v in r.items() if k != 'poly'}, junctions=sh_j(r['junctions']))
                                    for r in cand['residues']]},
                 openings_full=[{k: v for k, v in o.items()} for o in ad['ops']],
                 # проёмы ядра (кадр ядра, `planner/models.py:Opening`) — общие для всех геометрий, кроме стороны петли
                 # двери (`geometries[i].openings_core` — точные для своей расстановки)
                 openings_core=TR_strip(geometries[0]['openings_core']),
                 geometries=geometries, variants=variants, styles_ok=len(ok_styles))
    t_asm = time.time() - t2
    scene['timings'] = {'adapter_s': round(t_ad + t_prep, 3), 'solver_s': round(t_sol, 3), 'assembly_s': round(t_asm, 3),
                        'total_s': round(elapsed(), 3), 'solver_runs': len(tries), 'queue_s': round(clock['queue'], 3),
                        'adapter_only_s': round(t_ad, 3), 'rescue_s': round(t_res, 3), 'styles_substituted': rescued}
    _write(os.path.join(OUT, 'media.json'), {v['style']: media.get(v['style']) or {} for v in ok_styles})
    _write_scene(OUT, scene, tokens)
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


def render_inputs(variant: dict, media: dict) -> tuple[dict, dict]:
    """Что кадру рисовать моделью и что — фото: модель — только ГОДНАЯ (`items[].msid`, правило `item_has_mesh`; нет — честная
    серая форма, а не модель семейства чужого цвета); фото — по картинке товара (`media.json`): без фото ковёр не рисуется
    вовсе (`draft_render._paste_rug` → «пропал ковёр», T-12/2). Экземпляры пары («стул 2») наследуют фото роли."""
    import draft_render as DR
    sid = {r['role']: r['msid'] for r in variant['items'] if r.get('msid')}
    photos = {}
    for role, url in (media or {}).items():
        if url:
            ph = DR.photo(url)
            if ph is not None:
                photos[role] = ph
    for q in variant.get('placements_core') or []:
        if q['role'] not in photos and _base(q['role']) in photos:
            photos[q['role']] = photos[_base(q['role'])]
    for q in variant.get('placements_core') or []:
        if _base(q['role']) == 'ковёр' and q['role'] not in photos:
            # фото ковра не скачалось (ссылка магазина умерла: E, замер 09.11 — лофт и неоклассика без ковра) — ровный нейтральный
            # ковёр того же размера, а не пустой пол; `rugs_plain` в отчёте кадров
            from PIL import Image
            photos[q['role']] = Image.new('RGB', (400, 300), PLAIN_RUG_RGB)
            photos.setdefault('_plain', []).append(q['role'])
    return sid, photos


PLAIN_RUG_RGB = (206, 200, 190)   # светлый тёплый серый — нейтрален к любому стилю


def frame_entry(scene: dict, variant: dict, path: str, media: dict | None = None) -> dict:
    import draft_render as DR
    from planner.models import Item, Placement
    ops = scene['geometries'][variant['geometry']]['openings_core']
    croom = core_room({'w': scene['core']['w'], 'd': scene['core']['d']}, ops, render=True)
    ps = [Placement(role=q['role'], x=q['x'], y=q['y'], rot=q['rot'], elev_cm=q.get('elev') or 0,
                    item=Item(role=q['role'], w_cm=q['w'], d_cm=q['d'], h_cm=q.get('h') or 60, corner=q['corner'],
                              corner_left=q['corner_left'], corner_section_cm=q.get('section') or 95))
          for q in variant['placements_core'] if q.get('w')]
    sid, photos = render_inputs(variant, media or {})
    plain = photos.pop('_plain', [])
    img, diag = DR.scene3d_frame(croom, ps, entry_cam(scene, ops), sid, photos)
    img.save(path, quality=88)
    return dict(diag, rugs_plain=plain)


def frames(scene: dict, dst: str) -> dict:
    os.makedirs(dst, exist_ok=True)
    t = time.time()
    tag = scene['trial_id']
    out = {'top': [], 'entry': [], 'clay': {}}
    try:
        media = json.load(open(os.path.join(scene['out'], 'media.json'), encoding='utf-8'))
    except (OSError, ValueError):
        media = {}
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
        diag = frame_entry(scene, v, p, media.get(v['style']))
        out['entry'].append(p)
        out['clay'][v['style']] = diag.get('clay') or []
        if diag.get('rugs_plain'):
            out.setdefault('rugs_plain', {})[v['style']] = diag['rugs_plain']
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
