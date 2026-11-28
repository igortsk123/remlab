"""T-171/steny-ten · правка положения стен ДВУМ классам, проба в тени (задача 4 плана Fable, otvet-33). Рабочий файл (снимок voronka/versii/20261126-2234 не тронут: работаем в его копии work/).
Класс 1 — «уверенно сдвинутые»: walls.csv класс «сдвинута», сдвиг ≥ MIN_SHIFT_CM, доля на чернилах после сдвига ≥ MIN_AFTER_SHARE (как считал Fable).
Класс 2 — «ось на наружной грани толстой стены»: стена «на линии» (ось в допуске от чернил), но чернила идут ТОЛЬКО в одну сторону от оси полосой толщиной ≥ THICK_MIN_CM → ось переносится на середину полосы (вариант 'centre')
          или на дальнюю (внутреннюю) грань полосы (вариант 'inner').
Привязку плана к листу после правки НЕ подгоняем (fit.json «до» замораживается: vetka_fit --no-fit --frame).
Ворота — прежние (vetka_correct: сторож поворота ≤2°, цифры паспорта, STRICT_A: ухудшил площадь комнаты с цифрой хоть на 0,02 м² — перенос этой стены откатывается; комната без цифры — перенос не применять, флажок)."""
import copy
import csv
import json
import math
import os
import subprocess
import sys

W = os.environ.get('STENY_WORK', '/home/pakar/remlab-logs/t171-steny-ten/work')   # копия рабочего 6 (vetka_fit, vetka_correct, passport_load, overlay_status): чужой work/ только читаем; в CI его нет — тесты с ним пропускаются (SKIP)
sys.dont_write_bytecode = True
os.environ.update({'CORRECT_V2': '1', 'SOFT_INK': '1', 'STRICT_A': '1', 'PASSPORT_ONLY': '1', 'OMP_NUM_THREADS': '1'})
os.environ.pop('INK_PALE', None)
os.environ.pop('KEEP_FRAME', None)
sys.path.insert(0, W)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import vetka_fit as vf  # noqa: E402
import vetka_correct as VC  # noqa: E402
import passport_load as PL  # noqa: E402
import overlay_status as OV  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hold_b as HB  # noqa: E402      # рабочий 10, круг Б 4в: подгонка стыков и проверка замкнутости

UNIT = vf.UNIT
# --- числа (стартовые, названы ДО замера; новые пороги — в реестр правил при включении) ---
CFG = json.load(open(os.path.dirname(os.path.abspath(__file__)) + '/steny_ten_config.json', encoding='utf-8'))   # реестр чисел с причинами (_why_*)
MIN_SHIFT_CM = CFG['class1_min_shift_cm']        # класс 1: сдвиг не меньше (Fable)
MIN_AFTER_SHARE = CFG['class1_min_after_share']     # класс 1: после сдвига на чернилах не меньше (Fable)
THICK_MIN_CM = CFG['class2_thick_min_cm']        # класс 2: полоса чернил толще этого — «толстая стена»
EDGE_FRAC = CFG['class2_edge_frac']           # класс 2: ось ближе к краю полосы, чем эта доля толщины (на самой грани — 0)
EDGE_MIN_SHIFT_CM = CFG['class2_edge_min_shift_cm']    # класс 2: перенос на середину не меньше (иначе — шум)
BAND_SHARE_MIN = CFG['class2_band_share_min']      # класс 2: доля точек вдоль стены, где полоса найдена и согласна по стороне и толщине
BAND_SPREAD_CM = CFG['class2_band_spread_cm']       # класс 2: разброс толщины полосы вдоль стены не больше (иначе — не стена, а пятно/мебель)
GAP_PX = CFG['gap_px']                 # допустимый разрыв чернил вдоль нормали
MAX_BAND_CM = CFG['max_band_cm']         # дальше полосу не ищем
PAIR_K, PAIR_CAP_CM = CFG['pair_gap_walls_thickness'], CFG['pair_gap_cap_cm']   # вторая линия — не дальше PAIR_K толщин стены и не дальше PAIR_CAP_CM
PARALLEL = CFG.get('parallel_transfer', False)       # КРУГ 4: ВЫКЛ; драйвер включает ключом --parallel (steny_ten.py)
COLLINEAR_DEG = CFG.get('collinear_angle_deg', 3.0)
CLOSED_TOL_CM = CFG.get('closed_tol_cm', 3.0)
EVIDENCE = CFG.get('evidence_gate', False)           # КРУГ 4: ВЫКЛ; драйвер включает ключом --evidence
EV_MIN_GAIN = CFG.get('evidence_min_gain', 0.30)     # прирост доли на чернилах «до → на цели» не меньше (Fable 27.11; rab-2: любое X в 0,10–0,47 даёт тот же результат — не подгонка)
WHOLE_MISS = CFG.get('whole_miss_gate', False)           # КРУГ 4: ВЫКЛ; драйвер включает ключом --whole-miss
WHOLE_INL_MIN = CFG.get('whole_miss_inl_min', 0.40)
WHOLE_RESID_MAX_PX = CFG.get('whole_miss_resid_max_px', 7.0)
EV_MIN_LEFT_FRAC = CFG.get('evidence_min_left_frac', 0.30)   # Fable otvet-42: после вычета проёмов от стены остаётся не меньше 30 % длины ...
EV_MIN_LEFT_PTS = CFG.get('evidence_min_left_pts', 10)        # ... и не меньше 10 точек замера (шаг ≈2 px); иначе «неоднозначно», без переноса. Числа названы до замера, не подбирались
EV_PAIR_MAX_MID = CFG.get('evidence_pair_max_mid', 0.30)   # пара линий пускает только полую стену: доля на оси цели меньше (Fable otvet-39, число названо до замера)
PROFILE = CFG.get('evidence_profile', False)          # КРУГ 4в (2): ВЫКЛ; драйвер включает ключом --profile: «цель там, где линия» вместо порога 0,80
PR_WIN_CM = CFG.get('profile_window_cm', 40.0)         # окно поперёк стены вокруг цели, см
PR_STEP_CM = CFG.get('profile_step_cm', 2.0)
PR_EPS_PEAK = CFG.get('profile_eps_peak', 0.05)        # цель — «наибольший пик»: P(0) ≥ max P − 0,05
PR_PAIR_EQ = CFG.get('profile_pair_equal', 0.10)       # два пика «равные»: отличаются не больше
PR_FLOOR = CFG.get('profile_floor', 0.448)             # 10-й процентиль доли у 84 стен, верных по глазу на старом месте (an_4v_floor.py)
PR_OLD_ON_INK = CFG.get('profile_old_on_ink', False)    # КРУГ 4в: ВЫКЛ; ключ --old-on-ink: до ≥ нижнего предела профиля (0,448) → «неоднозначно», флажок (kazan-14429871 w8, «ДО верно», перенесена шагом 3)
NODIGIT_FLAG = CFG.get('nodigit_flag_only', False)      # КРУГ 4в, Fable (шаг 3 после защиты «заливка»): ВЫКЛ; ключ --nodigit-flag: комната без цифры не блокирует перенос, вместо блока — флажок «площадь не проверена»
SHEET_GRAY = None                                     # серый лист (uint8); ставит драйвер перед cands_class1 — для защиты «старое место внутри заливки»
SHEET_BLUR = None                                       # он же, размытый 5×5 (float32)
PR_FILL_DELTA = CFG.get('profile_fill_delta', 25.0)     # КРУГ 4в: старое место и середина пути темнее бумаги вокруг не меньше чем на столько уровней серого (из 255) — лист заливает толстую стену, перенос на её кромку — «неоднозначно»
PR_FILL_WIN_CM = CFG.get('profile_fill_win_cm', 60.0)
NEIGHBOR_DRIFT = CFG.get('neighbor_drift_gate', False)      # рабочий 6, Fable 28.11: ВЫКЛ; ключ --neighbor-drift: у соседа (не переносимая стена) мерка — увод конца поперёк его линии, не поворот >2°
HOLD_NEIGHBORS = CFG.get('hold_neighbors', False)      # рабочий 10, круг Б 4в (директор 28.11): ВЫКЛ; ключ --hold-neighbors: соседи держатся на своей линии, стык переносимой подгоняется к ним; замкнутость комнат — обязательная проверка, красная → перенос отменён
HOLD_BREAK = ''                                          # ТОЛЬКО тест (−контроль): 'nofit' — стык не подгоняется
DRIFT_MAX_CM = CFG.get('neighbor_drift_max_cm', 5.0)       # порог увода, см (один, абсолютный; причина — _why_neighbor_drift_max_cm)
AREA_FLAG_ONLY = CFG.get('area_flag_only', False)      # КРУГ 4в (4), Fable otvet-46: ВЫКЛ; драйвер включает ключом --area-flag: отмены по площади нет, вместо неё строка в отчёт (флажок не считается — прибор не калиброван)
PR_GAIN = CFG.get('profile_gain', 0.20)               # «заметно больше», чем на старом месте
EV_MAX_BEFORE = CFG.get('evidence_max_before', 0.50)   # на старом месте чернил нет: доля «до» меньше


def frame_args(fit):
    s = float(fit['scale_px_per_unit_cm'])
    tx, ty = fit['shift_px']
    a = ['--no-fit', '--frame', '%r,%r,%r' % (-tx / s, -ty / s, s)]
    if fit.get('flipy'):
        a.append('--flipy')
    if fit.get('rot_deg'):
        a += ['--rot', '%r,%r,%r' % (fit['rot_deg'], fit['rot_center_cm'][0], fit['rot_center_cm'][1])]
    return a


def run_fit_frozen(plan_path, sheet_path, out_dir, fit):
    os.makedirs(out_dir, exist_ok=True)
    env = dict(os.environ, CORRECT_V2='1', SOFT_INK='1', OMP_NUM_THREADS='1')
    r = subprocess.run([sys.executable, '-I', os.path.join(W, 'vetka_fit.py'), '--plan', plan_path, '--sheet', sheet_path, '--out', out_dir] + frame_args(fit),
                       env=env, capture_output=True, text=True, timeout=900)
    return r.returncode, r.stderr[-300:]


def measure_frozen(plan_path, sheet_path, out_dir, fit, cfg):
    """то же, что overlay_status.measure, но привязка ЗАМОРОЖЕНА (fit «до»); 4c — не повторяем (лист берётся тот, по которому мерили «до»)."""
    OV._run_fit = lambda p, s, o: run_fit_frozen(p, s, o, fit)
    m = OV._measure_once(plan_path, sheet_path, out_dir, cfg)
    return m, OV.column(m, cfg)


def rows_of(walls_csv):
    return {r['стена']: r for r in csv.DictReader(open(walls_csv, encoding='utf-8'))}


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def whole_plan_miss(fit):
    """КРУГ 4, «весь план мимо» (замер a/f 27.11 на 228: 18 из 25 таких листов ловятся; из 33 помеченных — 28 косяк, 4 не видно, 1 верно): привязка плана к чернилам не держится —
    доля точек ≤3 px < WHOLE_INL_MIN или медианный остаток > WHOLE_RESID_MAX_PX. Сдвигать отдельные стены на такой привязке бессмысленно: «сдвиг» там — это сдвиг всего плана.
    → текст причины или None"""
    inl, res_ = fit.get('inliers_share_le_3px'), fit.get('residual_median_px')
    if inl is not None and inl < WHOLE_INL_MIN:
        return 'весь план мимо: доля точек плана на чернилах ≤3 px %.2f < %.2f — стены не двигаем (нужна привязка плана целиком, круг 4 — «привязка восстановлена»)' % (inl, WHOLE_INL_MIN)
    if res_ is not None and res_ > WHOLE_RESID_MAX_PX:
        return 'весь план мимо: медианный остаток привязки %.1f px > %.1f px — стены не двигаем' % (res_, WHOLE_RESID_MAX_PX)
    return None


def plan_walls(plan):
    k = UNIT.get(plan.get('units', 'cm'), 1.0)
    out = []
    for lv in plan['levels']:
        for w in lv.get('walls', []):
            th = float(w['thickness']) * k if w.get('thickness') else {'exterior': 30.0, 'partition': 8.0}.get(w.get('kind'), 12.0)
            out.append({'id': w.get('id', ''), 'a': (w['from'][0] * k, w['from'][1] * k), 'b': (w['to'][0] * k, w['to'][1] * k), 'th': th, 'kind': w.get('kind', 'interior')})
    return out, k


def _px(fit, A, B):
    """концы стены плана (см) → пиксели листа (поворот листа, отражение по y, масштаб, сдвиг — как vetka_fit); → (2×2 px, масштаб)"""
    s = float(fit['scale_px_per_unit_cm'])
    tx, ty = fit['shift_px']
    Q = np.array([A, B], float)
    if fit.get('rot_deg'):
        Q = vf.rot_about(Q, float(fit['rot_deg']), fit['rot_center_cm'])
    if fit.get('flipy'):
        Q[:, 1] = -Q[:, 1]
    return Q * s + [tx, ty], s


def plan_openings(plan, k):
    """{id стены: [(начало_см, ширина_см)]} — окна, двери, проходы ответа (участки стены, где чернил на листе быть не обязано; правило круга 2в)"""
    out = {}
    for lv in plan['levels']:
        for o in lv.get('openings') or []:
            if o.get('wall') is None:
                continue
            out.setdefault(o['wall'], []).append((float(o.get('offset') or 0) * k, float(o.get('width') or 0.8) * k))
    return out


def share_on_ink(dt, fit, A, B, tol_px=None, skip=None):
    """доля точек вдоль стены A–B (середина 5–95 %, шаг ≈2 px), у которых чернила ближе tol_px (по карте расстояний dt); вне листа — не на чернилах.
    skip — участки проёмов [(t0, t1)] в долях длины стены: их точки не считаются (правило 2в, Fable otvet-39); остаётся <3 точек — доля 0 (доказывать нечем)"""
    tol_px = vf.TOL_MIN + 1.0 if tol_px is None else tol_px
    P, s = _px(fit, A, B)
    L = float(np.hypot(*(P[1] - P[0])))
    n = max(3, int(0.9 * L / 2))
    t = np.linspace(0.05, 0.95, n)
    pts = P[0] + (P[1] - P[0]) * t[:, None]
    xi, yi = np.rint(pts[:, 0]).astype(int), np.rint(pts[:, 1]).astype(int)
    inb = (xi >= 0) & (xi < dt.shape[1]) & (yi >= 0) & (yi < dt.shape[0])
    ok = np.zeros(n, bool)
    ok[inb] = dt[yi[inb], xi[inb]] <= tol_px
    keep = np.ones(n, bool)
    for t0, t1 in skip or []:
        keep &= ~((t >= t0) & (t <= t1))
    if keep.sum() < 3:
        return 0.0
    return float(ok[keep].mean())


def remainder(fit, A, B, skip):
    """что остаётся от стены после вычета проёмов: (доля длины стены вне проёмов 0…1, число точек замера вне проёмов, шаг ≈2 px, середина 5–95 %)"""
    P, _s = _px(fit, A, B)
    L = float(np.hypot(*(P[1] - P[0])))
    n = max(3, int(0.9 * L / 2))
    t = np.linspace(0.05, 0.95, n)
    keep = np.ones(n, bool)
    cover = np.zeros(1001, bool)
    grid = np.linspace(0.0, 1.0, 1001)
    for t0, t1 in skip or []:
        keep &= ~((t >= t0) & (t <= t1))
        cover |= (grid >= t0) & (grid <= t1)
    return float(1.0 - cover.mean()), int(keep.sum())


def fill_inside(fit, A, B, d):
    """КРУГ 4в: «старое место внутри заливки толстой стены». Серость (медиана размытого листа вдоль стены, середина 10–90 %) на старом месте и на середине пути к цели,
    против бумаги вокруг (90-й процентиль серости в окне ±PR_FILL_WIN_CM вокруг стены). → (внутри: оба тёмнее бумаги ≥ PR_FILL_DELTA, на сколько старое, на сколько середина) либо None, если листа нет."""
    if SHEET_GRAY is None or SHEET_BLUR is None or PR_FILL_DELTA <= 0:
        return None
    t = np.linspace(0.1, 0.9, 40)

    def lvl(a, b):
        P, _s = _px(fit, a, b)
        pts = P[0] + (P[1] - P[0]) * t[:, None]
        xi, yi = np.rint(pts[:, 0]).astype(int), np.rint(pts[:, 1]).astype(int)
        h, w = SHEET_BLUR.shape
        m = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
        return (float(np.median(SHEET_BLUR[yi[m], xi[m]])) if m.any() else None), pts
    l0, _p0 = lvl(A, B)
    lm, pm = lvl(A + d / 2.0, B + d / 2.0)
    if l0 is None or lm is None:
        return None
    s = float(fit['scale_px_per_unit_cm'])
    c, hw = pm.mean(axis=0), int(PR_FILL_WIN_CM * s)
    x0, y0 = int(max(c[0] - hw, 0)), int(max(c[1] - hw, 0))
    win = SHEET_GRAY[y0:int(c[1] + hw), x0:int(c[0] + hw)]
    if win.size == 0:
        return None
    paper = float(np.percentile(win, 90))
    d0, dm = paper - l0, paper - lm
    return (d0 >= PR_FILL_DELTA and dm >= PR_FILL_DELTA), round(d0, 1), round(dm, 1)


def evidence_profile(A, B, d, kind, fit, dt, skip, before, after, L):
    """КРУГ 4в (2), Fable reshenie-krug4v: «цель стоит там, где линия» (вместо порога 0,80): профиль P(o) — доля на чернилах для стены, сдвинутой от ЦЕЛИ поперёк на o ∈ [−40; +40] см, шаг 2 см.
    Сплошная: P(0) ≥ max P − 0,05 (цель — наибольший пик) и P(0) ≥ PR_FLOOR. Двойная линия: два равных пика (оба ≥ max P − 0,05, отличаются ≤ 0,10) на ±o*, цель между ними, меньший ≥ PR_FLOOR.
    Заметно больше, чем на старом месте: доказательство − «до» ≥ PR_GAIN. Остаток после проёмов — как в evidence_class1 (otvet-42)."""
    u = (B - A) / L
    n = np.array([-u[1], u[0]])
    offs = np.arange(-PR_WIN_CM, PR_WIN_CM + 0.01, PR_STEP_CM)
    P = {round(float(o), 1): (after if abs(o) < 1e-9 else share_on_ink(dt, fit, A + d + n * o, B + d + n * o, skip=skip)) for o in offs}
    pmax = max(P.values())
    omax = min((o for o, v in P.items() if v >= pmax - 1e-9), key=lambda o: abs(o))
    solid_ok = after >= pmax - PR_EPS_PEAK
    maxo = (vf.PAIR_EXT_CM if kind == 'exterior' else vf.PAIR_INT_CM) / 2.0 + 2.0
    pair, pair_o = 0.0, None
    for o in offs:
        if o < 3.0 or o > maxo + 1e-9:
            continue
        a_, b_ = P.get(round(float(o), 1), 0.0), P.get(round(float(-o), 1), 0.0)
        if a_ >= pmax - PR_EPS_PEAK and b_ >= pmax - PR_EPS_PEAK and abs(a_ - b_) <= PR_PAIR_EQ and min(a_, b_) > pair:
            pair, pair_o = min(a_, b_), float(o)
    if solid_ok and after >= PR_FLOOR:
        vid, ev = 'сплошная', after
    elif pair_o is not None and pair >= PR_FLOOR:
        vid, ev = 'полая', pair
    else:
        vid, ev = 'не доказано', after
    left_frac, left_pts = remainder(fit, A + d, B + d, skip)
    thin = bool(skip) and (left_frac < EV_MIN_LEFT_FRAC or left_pts < EV_MIN_LEFT_PTS)
    if thin and vid in ('сплошная', 'полая'):
        vid = 'неоднозначно'
    fill = fill_inside(fit, A, B, d) if vid in ('сплошная', 'полая') else None
    in_fill = bool(fill and fill[0])
    if in_fill:
        vid = 'неоднозначно'      # старое место внутри заливки толстой стены: цель — другая грань той же полосы, ось внутри верна
    old_on = bool(PR_OLD_ON_INK and vid in ('сплошная', 'полая') and before >= PR_FLOOR)
    if old_on:
        vid = 'неоднозначно'      # КРУГ 4в: на старом месте чернил не меньше, чем у стен, верных по глазу (нижний предел 0,448) — старая линия тоже линия, ось может быть на ней
    return {'до': round(before, 3), 'после': round(after, 3), 'пара': round(pair, 3), 'доказательство': round(ev, 3), 'прирост': round(ev - before, 3), 'вид': vid,
            'остаток_доля': round(left_frac, 3), 'остаток_точек': left_pts, 'тонкий_остаток': thin, 'пик_макс': round(pmax, 3), 'пик_смещение_см': omax, 'пара_смещение_см': pair_o,
            'старое_на_линии': old_on, 'заливка': in_fill, 'темнее_бумаги': None if fill is None else {'старое': fill[1], 'середина': fill[2]}}


def evidence_class1(c, kind, fit, dt, openings=None):
    """КРУГ 4, ворота доказательства (Fable 27.11, условие 1): доля на чернилах СЧИТАЕТСЯ ТАМ, КУДА СТЕНА РЕАЛЬНО ВСТАЁТ (ось + вектор переноса), а не берётся из walls.csv, где это доля на
    ЛУЧШЕМ смещении (vetka_fit.py:432 `best = (best[0], target)` — доля прежняя, смещение заменено серединой полосы/пары; у 52 из 349 строк ворота «после ≥0,8» этим обмануты — разбор rab-2).
    Пара линий (двойная линия БТИ): ось по построению между линиями — чернил на самой оси нет; тогда доказательство = обе линии пары (одинаковое смещение ±o от цели, оба ≥ порога).
    Fable otvet-39: пара пускает ТОЛЬКО полую стену — середина пуста (после < EV_PAIR_MAX_MID = 0,30). Середина 0,30–0,80 — «неоднозначно»: флажок, без переноса (пара такую не спасает).
    Проёмы ответа (openings = [(начало_см, ширина_см)] этой стены) из долей вычитаются: сплошная полоса с окнами/дверями проходит обычные ворота ≥0,8 без пары.
    → {'до': доля на старом месте, 'после': доля на цели, 'пара': доля у обеих линий пары (считается всегда, пускает только при после<0,30), 'доказательство': после, либо пара у полой стены,
       'прирост': доказательство − до, 'вид': 'сплошная' | 'полая' | 'неоднозначно' | 'не доказано'}"""
    A, B, d = np.array(c['a'], float), np.array(c['b'], float), np.array(c['d'], float)
    L = float(np.hypot(*(B - A))) or 1.0
    skip = [(o / L, (o + w) / L) for o, w in (openings or [])]
    before = share_on_ink(dt, fit, A, B, skip=skip)
    after = share_on_ink(dt, fit, A + d, B + d, skip=skip)
    if PROFILE:
        return evidence_profile(A, B, d, kind, fit, dt, skip, before, after, L)
    pair = 0.0
    if after < MIN_AFTER_SHARE:
        u = (B - A) / L
        n = np.array([-u[1], u[0]])
        maxo = (vf.PAIR_EXT_CM if kind == 'exterior' else vf.PAIR_INT_CM) / 2.0 + 2.0
        for o in np.arange(3.0, maxo + 0.01, 1.0):
            pair = max(pair, min(share_on_ink(dt, fit, A + d + n * o, B + d + n * o, skip=skip), share_on_ink(dt, fit, A + d - n * o, B + d - n * o, skip=skip)))
    if after >= MIN_AFTER_SHARE:
        vid, ev = 'сплошная', after
    elif after < EV_PAIR_MAX_MID:
        vid, ev = ('полая', pair) if pair >= MIN_AFTER_SHARE else ('не доказано', after)
    else:
        vid, ev = ('неоднозначно' if pair >= MIN_AFTER_SHARE else 'не доказано'), after
    left_frac, left_pts = remainder(fit, A + d, B + d, skip)
    thin = bool(skip) and (left_frac < EV_MIN_LEFT_FRAC or left_pts < EV_MIN_LEFT_PTS)
    if thin and vid in ('сплошная', 'полая'):
        vid = 'неоднозначно'      # Fable otvet-42: доказательство держится на малом остатке после вычета проёмов — не переносим
    return {'до': round(before, 3), 'после': round(after, 3), 'пара': round(pair, 3), 'доказательство': round(ev, 3), 'прирост': round(ev - before, 3), 'вид': vid,
            'остаток_доля': round(left_frac, 3), 'остаток_точек': left_pts, 'тонкий_остаток': thin}


def cands_class1(plan, rows, dt=None, fit=None, rej=None, evidence=None):
    """evidence (по умолчанию SC.EVIDENCE, ВЫКЛ): ворота доказательства вместо доли «после сдвига» из walls.csv — см. evidence_class1; dt — карта расстояний до чернил листа, fit — привязка «до».
    Не прошедшие → rej (список {'стена', 'до','после','пара','доказательство','прирост','причина'})."""
    ev_on = EVIDENCE if evidence is None else evidence
    ws, k = plan_walls(plan)
    ops = plan_openings(plan, k)
    out = []
    for w in ws:
        r = rows.get(w['id'])
        if not r or r['класс'] != 'сдвинута' or r['сдвиг_dx_см'] == '':
            continue
        sh, aft = fnum(r['сдвиг_см']), fnum(r['доля_на_чернилах_после_сдвига'])
        if sh is None or sh < MIN_SHIFT_CM:
            continue
        d = (float(r['сдвиг_dx_см']), float(r['сдвиг_dy_см']))
        ev = None
        if ev_on and dt is not None and fit is not None:
            ev = evidence_class1({'a': w['a'], 'b': w['b'], 'd': d}, w['kind'], fit, dt, openings=ops.get(w['id']))
            why = []
            if ev['вид'] == 'неоднозначно':
                if rej is not None:
                    why_a = ('старое место внутри заливки толстой стены (серость старого/середины темнее бумаги на %s/%s ≥ %.0f), цель — другая грань той же полосы, ось внутри верна' % (ev['темнее_бумаги']['старое'], ev['темнее_бумаги']['середина'], PR_FILL_DELTA)
                             if ev.get('заливка') else
                             'на старом месте чернил %.2f ≥ %.3f (как у стен, верных по глазу на старом месте): старая линия тоже линия, ось может быть на ней' % (ev['до'], PR_FLOOR)
                             if ev.get('старое_на_линии') else
                             'после вычета проёмов остаток %.0f %% длины и %d точек (нужно ≥%.0f %% и ≥%d) — доказательство на малом остатке' % (100 * ev['остаток_доля'], ev['остаток_точек'], 100 * EV_MIN_LEFT_FRAC, EV_MIN_LEFT_PTS)
                             if ev.get('тонкий_остаток') else 'середина полосы закрыта чернилами на %.2f (0,30–0,80), пара линий не спасает' % ev['после'])
                    rej.append(dict(ev, стена=w['id'], флаг=True, dx_см=d[0], dy_см=d[1], причина='неоднозначно: %s — флажок, без переноса' % why_a))
                continue
            if PROFILE:
                if ev['вид'] == 'не доказано':
                    why.append('цель не на линии: на цели %.2f, наибольший пик %.2f на %+.0f см от цели (нужно: цель — наибольший пик и ≥%.3f, либо два равных пика вокруг неё)' % (ev['после'], ev['пик_макс'], ev['пик_смещение_см'], PR_FLOOR))
                elif ev['прирост'] < PR_GAIN:
                    why.append('на цели не заметно больше, чем на старом месте: прирост %.2f < %.2f' % (ev['прирост'], PR_GAIN))
            else:
                if ev['доказательство'] < MIN_AFTER_SHARE:
                    why.append('на цели чернил %.2f < %.2f' % (ev['доказательство'], MIN_AFTER_SHARE))
                if ev['до'] >= EV_MAX_BEFORE:
                    why.append('на старом месте чернила есть (%.2f ≥ %.2f)' % (ev['до'], EV_MAX_BEFORE))
                if ev['прирост'] < EV_MIN_GAIN:
                    why.append('прирост %.2f < %.2f' % (ev['прирост'], EV_MIN_GAIN))
            if why:
                if rej is not None:
                    rej.append(dict(ev, стена=w['id'], причина='ворота доказательства: ' + '; '.join(why)))
                continue
        elif aft is None or aft < MIN_AFTER_SHARE:
            continue
        out.append({'id': w['id'], 'a': w['a'], 'b': w['b'], 'd': d, 'tol': max(w['th'] / 2, 5.0) + 2.0, 'класс': 1, 'shift_cm': sh, 'вид': w['kind'], 'доказательство': ev})
    return out


def band_profile(ink, p, n, s, tol, gmax_px):
    """полоса чернил вдоль нормали n (px) от точки p: → (lo, hi) в px от оси (lo ≤ 0 ≤ hi по знаку нормали) или None. Полоса = непрерывный (с разрывом ≤ GAP_PX) кусок чернил, ближайший к оси в пределах tol;
    стена, нарисованная ДВУМЯ тонкими линиями (лист рисует грани, не залитую полосу): за разрывом до gmax_px с ОДНОЙ стороны есть вторая линия — она входит в полосу. Вторая линия с обеих сторон сразу — None (неоднозначно)."""
    Hh, Ww = ink.shape
    D = int(MAX_BAND_CM * s)

    def at(d):
        xi, yi = int(round(p[0] + n[0] * d)), int(round(p[1] + n[1] * d))
        return 0 <= xi < Ww and 0 <= yi < Hh and bool(ink[yi, xi])
    start = None
    for d in sorted(range(-int(tol), int(tol) + 1), key=abs):
        if at(d):
            start = d
            break
    if start is None:
        return None
    hi = start
    gap = 0
    for d in range(start + 1, D + 1):
        if at(d):
            hi, gap = d, 0
        else:
            gap += 1
            if gap > GAP_PX:
                break
    lo = start
    gap = 0
    for d in range(start - 1, -D - 1, -1):
        if at(d):
            lo, gap = d, 0
        else:
            gap += 1
            if gap > GAP_PX:
                break

    def hop(edge, step):
        """вторая линия за разрывом: → её дальний край или None"""
        d0 = next((d for d in range(edge + step * (GAP_PX + 1), edge + step * (int(gmax_px) + 1), step) if at(d)), None)
        if d0 is None:
            return None
        e, gp = d0, 0
        for d in range(d0 + step, step * (D + 1), step):
            if at(d):
                e, gp = d, 0
            else:
                gp += 1
                if gp > GAP_PX:
                    break
        return e
    h_hi, h_lo = hop(hi, 1), hop(lo, -1)
    if h_hi is not None and h_lo is not None:
        return None
    if h_hi is not None:
        hi = h_hi
    elif h_lo is not None:
        lo = h_lo
    return lo, hi


def cands_class2(plan, rows, fit, ink, flip_sign):
    """класс 2 по стенам «на линии» (доля ≥0,7) без пары линий (между_гранями пусто). Возвращает (кандидаты, список проверенных стен с причиной отказа)."""
    ws, k = plan_walls(plan)
    s = float(fit['scale_px_per_unit_cm'])
    tx, ty = fit['shift_px']
    flip = bool(fit.get('flipy'))
    out, info = [], []
    if fit.get('rot_deg'):
        return out, [{'стена': '*', 'причина': 'лист повёрнут (rot_deg≠0) — класс 2 не считаем'}]
    for w in ws:
        r = rows.get(w['id'])
        if not r or r['класс'] != 'на линии' or r['между_гранями'] != '':
            continue
        A = np.array(w['a'], float)
        B = np.array(w['b'], float)
        if flip:
            A[1], B[1] = -A[1], -B[1]
        pa, pb = A * s + [tx, ty], B * s + [tx, ty]
        L = float(np.hypot(*(pb - pa)))
        if L < 30 * s:
            continue
        n = np.array([-(pb - pa)[1], (pb - pa)[0]]) / L
        t = np.linspace(0.1, 0.9, max(3, int(0.8 * L / 3)))
        los, his = [], []
        for tt in t:
            bp = band_profile(ink, pa + (pb - pa) * tt, n, s, vf.TOL_MIN + 1.0, min(PAIR_K * w['th'], PAIR_CAP_CM) * s)
            if bp is not None:
                los.append(bp[0])
                his.append(bp[1])
        if len(los) < BAND_SHARE_MIN * len(t):
            info.append({'стена': w['id'], 'причина': 'полоса найдена на %d%% длины' % (100 * len(los) / len(t))})
            continue
        lo, hi = np.array(los, float), np.array(his, float)
        width = hi - lo
        wm = float(np.median(width))
        if wm / s < THICK_MIN_CM:
            continue
        spread = float(np.percentile(width, 90) - np.percentile(width, 10)) / s
        if spread > BAND_SPREAD_CM:
            info.append({'стена': w['id'], 'причина': 'толщина полосы гуляет на %.1f см' % spread})
            continue
        c = float(np.median((lo + hi) / 2))                    # середина полосы относительно оси, px по нормали n
        lo_m, hi_m = float(np.median(lo)), float(np.median(hi))
        near = min(abs(lo_m), abs(hi_m))
        if near > EDGE_FRAC * wm or abs(c) / s < EDGE_MIN_SHIFT_CM:
            continue
        same = float(np.mean(np.sign((lo + hi) / 2) == np.sign(c)))
        if same < BAND_SHARE_MIN:
            info.append({'стена': w['id'], 'причина': 'сторона полосы не одна вдоль стены (%.0f%%)' % (100 * same)})
            continue
        far = hi_m if abs(hi_m) > abs(lo_m) else lo_m          # дальняя грань полосы — «внутренняя линия»
        out.append({'id': w['id'], 'a': w['a'], 'b': w['b'], 'tol': max(w['th'] / 2, 5.0) + 2.0, 'класс': 2, 'вид': w['kind'], 'толщина_см': round(wm / s, 1), 'n': n,
                    'c_px': c, 'far_px': far, 'shift_centre_cm': round(abs(c) / s, 1), 'shift_inner_cm': round(abs(far) / s, 1), 'flip': flip, 's': s})
    return out, info


def class2_vec(c, variant):
    px = c['c_px'] if variant == 'centre' else c['far_px']
    dpx = c['n'] * px
    return (round(float(dpx[0]) / c['s'], 2), round(float(dpx[1]) / c['s'] * (-1 if c['flip'] else 1), 2))


def expand_collinear(ws, rows, shifted, angle_deg=None):
    """КРУГ 4, «перенос без поворота»: к каждой сдвигаемой стене добавляем соосных соседей — стены на ТОЙ ЖЕ линии (угол ≤ angle_deg, обе точки в допуске от линии, концы
    стыкуются), чей класс в walls.csv не «на линии» (на чернилах-то линия стоит — её не трогаем). Они переносятся ЦЕЛИКОМ на тот же вектор: стена, сдвинутая одним концом
    (так делал vetka_correct.apply), поворачивалась на atan(сдвиг/длина) и отменялась воротами «поворот >2°».
    → (список для VC.apply: сдвигаемые + виртуальные, {id виртуальной стены: id сдвигаемой-родителя})"""
    ang = COLLINEAR_DEG if angle_deg is None else angle_deg
    out, parent = list(shifted), {}
    have = {s['id'] for s in shifted}
    queue = list(shifted)
    while queue:
        s = queue.pop()
        sa, sb = np.array(s['a'], float), np.array(s['b'], float)
        sl = float(np.hypot(*(sb - sa)))
        if sl < 1e-6:
            continue
        su = (sb - sa) / sl
        nrm = np.array([-su[1], su[0]])
        for w in ws:
            if w['id'] in have:
                continue
            r = rows.get(w['id'])
            if r is not None and r['класс'] == 'на линии':
                continue
            wa, wb = np.array(w['a'], float), np.array(w['b'], float)
            wl = float(np.hypot(*(wb - wa)))
            if wl < 1e-6:
                continue
            if math.degrees(math.acos(min(1.0, abs(float(su @ (wb - wa)) / wl)))) > ang:
                continue
            if max(abs(float((wa - sa) @ nrm)), abs(float((wb - sa) @ nrm))) > s['tol']:
                continue
            tol_w = max(w['th'] / 2, 5.0) + 2.0
            if min(float(np.hypot(*(p - q))) for p in (sa, sb) for q in (wa, wb)) > max(s['tol'], tol_w):
                continue
            v = {'id': w['id'], 'a': w['a'], 'b': w['b'], 'd': s['d'], 'tol': tol_w, 'класс': s.get('класс'), 'виртуальный': True}
            out.append(v)
            parent[w['id']] = parent.get(s['id'], s['id'])
            have.add(w['id'])
            queue.append(v)
    return out, parent


def check_closed(plan0, plan1, k, tol_cm=None):
    """тест замкнутого контура: стык двух стен, замкнутый «до» (конец одной лежит на другой в пределах tol), после переноса не должен разойтись больше tol.
    → список разрывов [{'стена','конец','с_стеной','разрыв_см'}] (пусто = контур замкнут)"""
    tol = CLOSED_TOL_CM if tol_cm is None else tol_cm

    def segs(plan):
        return {w.get('id', ''): ((w['from'][0] * k, w['from'][1] * k), (w['to'][0] * k, w['to'][1] * k)) for lv in plan['levels'] for w in lv.get('walls', []) if w.get('id')}
    s0, s1 = segs(plan0), segs(plan1)
    out = []
    for i, ends in s0.items():
        for ei, p in enumerate(ends):
            for j, (c, d) in s0.items():
                if j == i or VC.seg_dist(p, c, d)[0] > tol:
                    continue
                g = VC.seg_dist(s1[i][ei], s1[j][0], s1[j][1])[0]
                if g > tol:
                    out.append({'стена': i, 'конец': ei, 'с_стеной': j, 'разрыв_см': round(g, 1)})
    return out


def _outdoor_room(r):
    return r.get('use') in ('balcony', 'outdoor') or r.get('ceiling') is False or any(x in str(r.get('name', '')).lower() for x in ('балкон', 'лодж', 'balcon', 'loggia', 'terrace'))


def judge_area(plan0, plan1, k, printed, sid):
    """КРУГ 4 (Fable, условие 4): НЕЗАВИСИМЫЙ судья — площади, а не чернила. Чернила двигают сами стены, поэтому «доля на чернилах» после правки растёт по построению.
    Число от чернил не зависит: у скольких комнат с цифрой листа площадь контура сходится с подписью (как в воротах: ±8 % при ≥6 м², иначе ±0,4 м²), до и после;
    и общая площадь комнат (без балконов/лоджий) против объявления (listing.json square_total), до и после, в %."""
    from shapely.geometry import Polygon
    tab0, tab1 = VC.room_table(plan0, k, printed), VC.room_table(plan1, k, printed)

    def match(P_, N_):
        return abs(N_ - P_) <= (0.08 * P_ if P_ >= 6 else 0.4)
    m0 = sum(1 for v in tab0.values() if match(v[1], v[2]))
    m1 = sum(1 for rid, v in tab0.items() if match(v[1], tab1.get(rid, v)[2]))

    def total(plan):
        t = 0.0
        for lv in plan['levels']:
            for r in lv.get('rooms', []):
                if _outdoor_room(r) or len(r['polygon']) < 3:
                    continue
                g = Polygon([(x * k, y * k) for x, y in r['polygon']])
                t += (g if g.is_valid else g.buffer(0)).area / 1e4
        return t
    try:
        tot = float(str(json.load(open(PL._listing(sid), encoding='utf-8')).get('square_total')).replace(',', '.'))
    except Exception:   # noqa: BLE001  (нет объявления — общую площадь не судим)
        tot = None
    t0, t1 = total(plan0), total(plan1)
    return {'комнат_с_цифрой': len(tab0), 'сходится_до': m0, 'сходится_после': m1, 'итог_до_м2': round(t0, 2), 'итог_после_м2': round(t1, 2), 'объявление_м2': tot,
            'откл_до_%': None if not tot else round(100 * (t0 / tot - 1), 1), 'откл_после_%': None if not tot else round(100 * (t1 / tot - 1), 1)}


def neighbor_drift(plan0, plan1, k, skip_ids):
    """→ {id стены: (увод_см, поворот_град)} для стен, которых нет в skip_ids (соседи: не переносимые и не виртуальные соосные). Увод — наибольшее смещение конца стены поперёк ЕЁ ИСХОДНОЙ линии, см
    (смещение вдоль линии уводом не считается). Поворот — угол между старым и новым положением, град."""
    old = {w['id']: w for lv in plan0['levels'] for w in lv.get('walls', []) if w.get('id')}
    out = {}
    for lv in plan1['levels']:
        for w in lv.get('walls', []):
            i = w.get('id')
            o = old.get(i)
            if not o or i in skip_ids:
                continue
            oa, ob = np.array(o['from'], float) * k, np.array(o['to'], float) * k
            na, nb = np.array(w['from'], float) * k, np.array(w['to'], float) * k
            L = float(np.hypot(*(ob - oa)))
            if L < 1e-6:
                continue
            u = (ob - oa) / L
            n = np.array([-u[1], u[0]])
            drift = max(abs(float((na - oa) @ n)), abs(float((nb - ob) @ n)))
            a0, a1 = math.atan2(ob[1] - oa[1], ob[0] - oa[0]), math.atan2(nb[1] - na[1], nb[0] - na[0])
            out[i] = (drift, abs((math.degrees(a1 - a0) + 180) % 360 - 180))
    return out


def correct(plan0, k, cand, printed, pstat, rows=None, parallel=False, info=None):
    """Ворота — копия цикла vetka_correct.main (V2 + PASSPORT_ONLY + STRICT_A), без ввода-вывода. cand — список {'id','a','b','d','tol',...}.
    parallel=True (КРУГ 4; нужны rows = walls.csv листа): соосные соседи переносятся целиком (expand_collinear). info (dict) — сюда кладём {'соседи': {родитель: [id]}, 'разрывы': [...]}.
    → (план после, перенесённые [cand], отказы [{'стена','причина'}], флажки [{'стена','dx_см','dy_см','причина'}], таблица комнат {rid: (имя, P, N0, N1)})"""
    shifted = list(cand)
    ws_, _k = plan_walls(plan0)

    def cls_of(w):          # Б-2: класс наложения стены в walls.csv листа; нет строки — считаем «чернила есть» (не схлопываем)
        r_ = (rows or {}).get(w)
        return r_['класс'] if r_ else None

    def mk_collapse(ex):
        return lambda w: HB.collapse_check(plan0, ex, k, w, cls_of, brk=('niche' if 'niche' in str(HOLD_BREAK).split(',') else ''))

    def expanded(sh):
        return expand_collinear(ws_, rows, sh) if (parallel and rows is not None) else (list(sh), {})
    untouched, gate_cancel, flags = [], [], []
    partial_done = False        # Б-3: частичная отмена (только виновные) уже была — повторная красная = отмена всей группы
    partial_log = []
    skip_hb = False             # ТОЛЬКО −контроль теста: 'norecheck' — после частичной отмены ворота повторно НЕ гонять
    hb_flags = set(str(HOLD_BREAK).split(','))
    tab0 = VC.room_table(plan0, k, printed)
    outdoor = {r.get('id', '') for lv in plan0['levels'] for r in lv.get('rooms', [])
               if r.get('use') in ('balcony', 'outdoor') or r.get('ceiling') is False or any(x in str(r.get('name', '')).lower() for x in ('балкон', 'лодж', 'balcon', 'loggia', 'terrace'))}
    plan = copy.deepcopy(plan0)
    tab1 = {}
    area_rows = []
    nodigit = {}
    for _ in range(2 * len(cand) + 2):
        exp, par = expanded(shifted)
        up = (lambda i, par=par: par.get(i, i))
        plan, moved, rot, infl, raff = VC.apply(plan0, [{'id': s['id'], 'a': s['a'], 'b': s['b'], 'd': s['d'], 'tol': s['tol']} for s in exp], k)
        raff = {rid: {up(x) for x in who} for rid, who in raff.items()}
        exp_ids = {s['id'] for s in exp}
        if HOLD_NEIGHBORS:
            plan = HB.hold_fit(plan0, exp, k, fit=('nofit' not in str(HOLD_BREAK).split(',')), brk=str(HOLD_BREAK))
            rot = HB.rot_of(plan0, plan)
            _rows, nl_viol, _mx = HB.neighbor_limits(plan0, plan, exp, k, collapse=mk_collapse(exp))      # Fable: (а) поперечный увод концов соседей = 0; (б) изменение длины соседа ≤ переноса стены лоджии
            if nl_viol:
                sh_ids0 = {s['id'] for s in shifted}
                culp0 = {up(v['M']) for v in nl_viol if v['M']} & sh_ids0
                if not culp0:
                    culp0 = sh_ids0
                for s in [s for s in shifted if s['id'] in culp0]:
                    vs = [v for v in nl_viol if v['M'] and up(v['M']) == s['id']] or nl_viol
                    v0 = max(vs, key=lambda v: v['см'])
                    why = ('сосед %s: увод конца поперёк %.2f см (допуск 0)' % (v0['стена'], v0['см'])) if v0['вид'] == 'увод' else \
                        ('сосед %s удлиняется на %.1f см > переноса %.1f см (стык с %s)' % (v0['стена'], v0['см'], v0['предел_см'], v0['M']))
                    untouched.append({'стена': s['id'], 'причина': why, 'соседи': [{'стена': v['стена'], 'конец': v['конец'], 'вид': v['вид'], 'см': v['см'], 'предел_см': v['предел_см']} for v in vs[:3]]})
                shifted = [s for s in shifted if s['id'] not in culp0]
                if not shifted:
                    plan, moved, rot, infl, raff = VC.apply(plan0, [], k)
                    break
                continue
        drift = neighbor_drift(plan0, plan, k, exp_ids) if NEIGHBOR_DRIFT else {}
        if NEIGHBOR_DRIFT:      # соседей меряем уводом конца (см), переносимых и виртуальных — поворотом >2°
            bad = {w for w, d in rot.items() if w in exp_ids and d > VC.MAX_ROT_DEG} | {w for w, (u_, _a) in drift.items() if u_ > DRIFT_MAX_CM}
        else:
            bad = {w for w, d in rot.items() if d > VC.MAX_ROT_DEG}
        if bad:
            culprits = set()
            for w in bad:
                culprits |= {up(x) for x in infl.get(w, set())}
            if not culprits:
                break
            for s in [s for s in shifted if s['id'] in culprits]:
                rw = sorted(((w, d) for w in bad for d in [rot[w]] if s['id'] in {up(x) for x in infl.get(w, set())}), key=lambda t: -t[1])[:2]
                nbr = sorted(((w, drift[w][0]) for w in bad if w in drift and drift[w][0] > DRIFT_MAX_CM and s['id'] in {up(x) for x in infl.get(w, set())}), key=lambda t: -t[1])
                if nbr:
                    untouched.append({'стена': s['id'], 'причина': 'сосед %s уводится на %.1f см (> %s см)' % (nbr[0][0], nbr[0][1], DRIFT_MAX_CM),
                                      'соседи': [{'стена': w, 'увод_см': round(u_, 1), 'град': round(rot.get(w, 0.0), 1)} for w, u_ in nbr[:3]]})
                else:
                    untouched.append({'стена': s['id'], 'причина': 'поворот >%s°' % VC.MAX_ROT_DEG, 'повернулись': [{'стена': w, 'град': round(d, 1), 'виртуальная': w in par} for w, d in rw]})
            shifted = [s for s in shifted if s['id'] not in culprits]
            if not shifted:
                plan, moved, rot, infl, raff = VC.apply(plan0, [], k)
                break
            continue
        skip_now, skip_hb = skip_hb, False
        if HOLD_NEIGHBORS and not skip_now:
            hb = HB.check_all(plan0, plan, k, collapse=mk_collapse(exp))
            if not hb['зелёная']:
                sh_ids = {s['id'] for s in shifted}
                culp = set()
                for b_ in hb['разрывы']:
                    for x in (b_['стена'], b_['с_стеной']):
                        culp |= {up(y) for y in infl.get(x, set())} | ({up(x)} if up(x) in sh_ids else set())
                for lv in plan0['levels']:
                    for r in lv.get('rooms', []):
                        if r.get('id') in hb['комнаты_красные']:
                            pc = np.array(r['polygon'], float) * k
                            culp |= {s['id'] for s in shifted if HB.borders(pc, s)}
                culp &= sh_ids
                if not culp:
                    culp = sh_ids
                why = '; '.join(hb['красные'][:2]) or ('стык разошёлся: %s' % hb['разрывы'][:2])
                share = {}
                if not partial_done and 'allgroup' not in hb_flags:
                    guilty = set()
                    for s in [s for s in shifted if s['id'] in culp]:       # виновный: один его перенос (со своими соосными) уже не замыкает контур
                        ex_s = expanded([s])[0]
                        plan_s = HB.hold_fit(plan0, ex_s, k, fit=('nofit' not in hb_flags), brk=str(HOLD_BREAK))
                        if not HB.check_all(plan0, plan_s, k, collapse=mk_collapse(ex_s))['зелёная']:
                            guilty.add(s['id'])
                    if guilty:
                        for s in shifted:                                    # + переносы, делящие с виновным вершину (концы стен в допуске)
                            if s['id'] in guilty:
                                continue
                            for g in [g for g in shifted if g['id'] in guilty]:
                                tolg = max(float(s['tol']), float(g['tol']))
                                if any(float(np.hypot(p[0] - q[0], p[1] - q[1])) <= tolg for p in (s['a'], s['b']) for q in (g['a'], g['b'])):
                                    share[s['id']] = g['id']
                                    break
                        partial_done = True
                        skip_hb = 'norecheck' in hb_flags
                        partial_log.append({'виновные': sorted(guilty), 'делят_вершину': dict(share), 'было_в_группе': sorted(culp)})
                        culp = guilty | set(share)
                for s in [s for s in shifted if s['id'] in culp]:
                    untouched.append({'стена': s['id'], 'причина': ('контур не замыкается: делит вершину с отменённой %s' % share[s['id']]) if s['id'] in share else 'контур не замыкается: ' + why})
                shifted = [s for s in shifted if s['id'] not in culp]
                if not shifted:
                    plan, moved, rot, infl, raff = VC.apply(plan0, [], k)
                    break
                continue
        tab1 = VC.room_table(plan, k, printed)
        blocked = [(rid, who) for rid, who in raff.items() if rid not in tab0 and rid not in outdoor]
        if blocked and NODIGIT_FLAG:
            for s in shifted:
                rr = sorted(str(r) for r, who in blocked if s['id'] in who)
                if rr:
                    nodigit[s['id']] = {'стена': s['id'], 'класс': s.get('класс'), 'dx_см': s['d'][0], 'dy_см': s['d'][1], 'причина': 'перенесена; площадь не проверена — задета комната без цифры: ' + ', '.join(rr)}
            blocked = []
        if blocked:
            drop = {w for _, who in blocked for w in who} & {s['id'] for s in shifted}
            if drop:
                for s in [s for s in shifted if s['id'] in drop]:
                    flags.append({'стена': s['id'], 'класс': s.get('класс'), 'dx_см': s['d'][0], 'dy_см': s['d'][1], 'причина': 'задета комната без цифры: ' + ', '.join(sorted(str(r) for r, who in blocked if s['id'] in who))})
                shifted = [s for s in shifted if s['id'] not in drop]
                if not shifted:
                    plan, moved, rot, infl, raff = VC.apply(plan0, [], k)
                    break
                continue
        failed = None
        area_rows = []
        for rid, who in raff.items():
            if rid not in tab0:
                continue
            nm, P_, N0 = tab0[rid]
            N1 = tab1[rid][2]
            if abs(N1 - P_) > abs(N0 - P_) + VC.STRICT_EPS:
                if AREA_FLAG_ONLY:
                    # Fable otvet-46: отмену по площади снимаем; строка в отчёт (флажком не считается, пока прибор rab-7 не откалиброван)
                    area_rows.append({'комната': rid, 'имя': nm, 'цифра': round(P_, 2), 'до': round(N0, 2), 'после': round(N1, 2), 'стены': sorted(who & {s['id'] for s in shifted})})
                    continue
                failed = (rid, nm, who, P_, N0, N1)
                break
        if not failed:
            break
        rid, nm, who, P_, N0, N1 = failed
        c = max([s for s in shifted if s['id'] in who], key=lambda s: math.hypot(*s['d']), default=None)
        if c is None:
            break
        gate_cancel.append({'стена': c['id'], 'класс': c.get('класс'), 'причина': f'комната {nm}: цифра {P_:.2f}, было {N0:.2f}, после {N1:.2f}', 'комната': rid})
        shifted = [s for s in shifted if s['id'] != c['id']]
        if not shifted:
            plan, moved, rot, infl, raff = VC.apply(plan0, [], k)
            tab1 = VC.room_table(plan, k, printed)
            break
    rooms = {rid: (tab0[rid][0], tab0[rid][1], tab0[rid][2], tab1.get(rid, tab0[rid])[2]) for rid in tab0}
    flags = flags + [f for w, f in nodigit.items() if w in {s['id'] for s in shifted}]      # перенесённые стены, у которых площадь комнаты без цифры не проверена
    if info is not None:
        info['площадь_строки'] = area_rows
        _, par = expanded(shifted)
        nb = {}
        for v, p_ in par.items():
            nb.setdefault(p_, []).append(v)
        info['соседи'] = nb
        info['разрывы'] = ((HB.joint_breaks(plan0, plan, k) if HOLD_NEIGHBORS else check_closed(plan0, plan, k)) if shifted else [])
        ids_f = {s['id'] for s in expanded(shifted)[0]} if shifted else set()
        nd = neighbor_drift(plan0, plan, k, ids_f) if shifted else {}      # в отчёт — rot и увод КАЖДОГО соседа, чей конец сдвинулся (независимо от ключа)
        info['соседи_увод'] = [{'стена': w, 'rot_град': round(a_, 2), 'увод_см': round(u_, 2)} for w, (u_, a_) in sorted(nd.items(), key=lambda t: -t[1][0]) if u_ > 0.05 or a_ > 0.05]
    if info is not None and HOLD_NEIGHBORS:
        ex_f = expanded(shifted)[0] if shifted else []
        coll_l = []
        info['замкнутость'] = HB.check_all(plan0, plan, k, collapse=mk_collapse(ex_f), collapsed=coll_l) if shifted else None
        info['схлопнуто'] = coll_l
        info['частичная_отмена'] = partial_log           # Б-2: ступеньки, схлопнувшиеся по трём условиям Fable (длина, чернил нет, контур цел)
        if shifted:
            rows_, _v, mx_ = HB.neighbor_limits(plan0, plan, ex_f, k, collapse=mk_collapse(ex_f))
            info['соседи_стыки'], info['увод_соседей_макс_см'] = rows_, round(mx_, 3)
        else:
            info['соседи_стыки'], info['увод_соседей_макс_см'] = [], 0.0
    return plan, shifted, untouched + gate_cancel, flags, rooms
