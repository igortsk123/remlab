#!/usr/bin/env python3
"""Этажи: добавочные числа наложения для звонка «Ст» — считаются НА ЛИСТЕ (T-171/paket-ext; круги 2б и 2в).

Раньше числа лежали готовыми файлами: cikl/c2b-ext/<лист>/ext2b.json (круг 2б: wide_line, pale_line) и cikl/c2c-ext/<лист>/ext2c.json (круг 2в: windows).
В живом прогоне этих папок нет → выключатели молча ничего не делали. Этот модуль считает те же числа по тем же входам: ответ (plan-clean.json / plan.json), наложение (fit.json, walls.csv),
картинка листа. Код — перенос stolb2b_ext.py / stolb2c_ext.py БЕЗ смены арифметики (сверка на всех листах с готовыми файлами — в OTCHET-ext.md); путей к папкам прогонов и к ~/remlab-logs здесь нет —
всё приходит аргументами; код привязки/чернил (vetka_fit) приходит аргументом `vf` (модуль vetka_fit той же сборки, что у сторожа), сам модуль его не импортирует.

Что даёт: словарь ТОЙ ЖЕ формы, что читал storozh.with_ext / with_ext2c (поле «статус»: ok | не сошлось с walls.csv | нет входа | нет картинки листа | сбой: … | отказ: …; не «ok» — сторож считает «Ст» как раньше).
Тяжёлое (пиксели) считается только при вызове; сеть, диск (кроме чтения картинки через vf.load_gray), платное — нет.

Входы функций:
  sid     — id листа (в результат);
  cands   — [(метка, plan_dict, картинка)] в порядке предпочтения (см. candidates()); картинка — путь (читает vf.load_gray) или готовый gray-массив numpy;
  fit     — fit.json наложения (dict: scale_px_per_unit_cm, shift_px, flipy, rot_deg, rot_center_cm, sheet_px);
  rows    — стены наложения (walls.csv как список dict: стена, длина_px, класс, доля_на_чернилах);
  vf      — модуль vetka_fit (load_gray, ink_mask, segs_of, rot_about, bg_kernel, TOL_MIN).
Чистая арифметика — numpy + cv2; импортируются при первом вызове.
"""
import collections
import math

GRID = (215, 225, 235)          # сетка порогов «бледной линии» (rel_max); основное значение — 225 (задано заранее, круг 2б)
GRAY_MAX = 170                  # строгий потолок яркости «чернил» для бледной линии
SHEET_TOL = 0.03                # лист «сошёлся с walls.csv», если узкая доля по каждой стене отличается не более чем на это
WINDOW_TYPES = ('window',)      # виды проёмов ответа, считающиеся окном (круг 2в)


def vf_refusal(vf):
    """Причина отказа (строка) или None. Числа кругов 2б/2в мерены на чернилах с V2=1, SOFT_INK=1 и БЕЗ INK_PALE / INK_THICK / INK_LAYERS (настройки vetka_fit из окружения запуска);
    при другой настройке чернила другие → числа не те, что в мерке. Лучше отказ с причиной, чем тихо другие числа."""
    bad = []
    if not getattr(vf, 'V2', False):
        bad.append('CORRECT_V2 не включён')
    if not getattr(vf, 'SOFT_INK', False):
        bad.append('SOFT_INK не включён')
    for nm in ('INK_PALE', 'INK_THICK'):
        if getattr(vf, nm, False):
            bad.append('%s включён' % nm)
    if getattr(vf, 'INK_LAYERS', ''):
        bad.append('INK_LAYERS задан')
    return ('настройки vetka_fit не те, на которых мерены числа 2б/2в: ' + ', '.join(bad)) if bad else None


def applicable(ov, rows):
    """Лист годится для чисел 2б/2в: наложение «легло», вход «как есть», есть стены наложения (как отбирала мерка)."""
    return bool(ov and ov.get('overlay_status') == 'легло' and ov.get('вход', 'как есть') == 'как есть' and rows)


def candidates(plans, images):
    """[(метка, plan, картинка)] в порядке мерки: plan-clean.json/plan.json × картинка d/b.
    plans — {'plan-clean.json': dict|None, 'plan.json': dict|None}; images — {'d': путь|gray|None, 'b': …}. Нет плана или картинки — вариант пропускается."""
    out = []
    for pn in ('plan-clean.json', 'plan.json'):
        for var in ('d', 'b'):
            p, im = plans.get(pn), images.get(var)
            if p and im is not None:
                out.append(('%s/%s' % (pn, var), p, im))
    return out


def current_hit(rows, ov, wf):
    """Звонит ли «Ст» по базовым числам (walls_fail: выдуманных ≥ доли, лишнее ≥ м, на линии < порога) — для 2б нужны только такие листы (экономия времени; мерка считала так же)."""
    tot = sum(float(r['длина_px']) for r in rows)
    fab = sum(float(r['длина_px']) for r in rows if r['класс'] == 'выдуманная')
    share = fab / tot if tot else 0.0
    line = ov.get('на_линии')
    extra = ov.get('лишнее_м')
    return (share >= wf['fabricated_share_min']) or (isinstance(extra, (int, float)) and extra >= wf['extra_m_min']) or (isinstance(line, (int, float)) and line < wf['on_line_min'])


def _gray(vf, im):
    return im if hasattr(im, 'shape') else vf.load_gray(im)


def _setup(vf, plan, fit, im):
    """Картинка листа → чернила, расстояния до чернил, стены плана в пикселях. None — размер картинки не равен sheet_px наложения."""
    import cv2
    import numpy as np
    g = _gray(vf, im)
    if list(g.shape[::-1]) != list(fit.get('sheet_px') or []):
        return None
    ink = vf.ink_mask(g)
    dt = cv2.distanceTransform((~ink).astype(np.uint8), cv2.DIST_L2, 3)
    segs = vf.segs_of(plan)
    s = float(fit['scale_px_per_unit_cm'])
    tx, ty = fit['shift_px']
    flipy = bool(fit.get('flipy'))
    if abs(fit.get('rot_deg') or 0.0) > 1e-9 and fit.get('rot_center_cm'):
        c_r = fit['rot_center_cm']
        segs = [tuple(vf.rot_about(np.array([[x0, y0], [x1, y1]]), fit['rot_deg'], c_r).ravel()) + (th, wid) for (x0, y0, x1, y1, th, wid) in segs]
    Hh, Ww = g.shape
    return {'g': g, 'dt': dt, 'segs': segs, 's': s, 'tx': tx, 'ty': ty, 'flipy': flipy, 'H': Hh, 'W': Ww}


def _wall_pts(st, seg):
    """Ось стены в пикселях: (pa, pb, L, band_половина_толщины, число точек, расстояния до чернил по точкам оси, pts)."""
    import numpy as np
    x0, y0, x1, y1, th, wid = seg
    A, B = np.array([x0, y0], float), np.array([x1, y1], float)
    if st['flipy']:
        A[1], B[1] = -A[1], -B[1]
    pa, pb = A * st['s'] + [st['tx'], st['ty']], B * st['s'] + [st['tx'], st['ty']]
    L = float(np.hypot(*(pb - pa)))
    nn = max(2, int(L / 2) + 1)
    tt = np.linspace(0, 1, nn)
    pts = pa[None] + (pb - pa)[None] * tt[:, None]
    Hh, Ww = st['H'], st['W']
    xs = np.clip(np.round(pts[:, 0]).astype(int), 0, Ww - 1)
    ys = np.clip(np.round(pts[:, 1]).astype(int), 0, Hh - 1)
    inside = (np.round(pts[:, 0]) >= 0) & (np.round(pts[:, 0]) < Ww) & (np.round(pts[:, 1]) >= 0) & (np.round(pts[:, 1]) < Hh)
    dd = np.where(inside, st['dt'][ys, xs], 1e9)
    return pa, pb, L, tt, pts, dd


def _fail(sid, status):
    return {'лист': sid, 'статус': status}


def ext2b(sid, cands, fit, rows, vf):
    """Круг 2б: «на линии — широко» (допуск от толщины стены и от размера листа) и «бледная линия» у стен «выдуманная». → словарь формы ext2b.json."""
    why = vf_refusal(vf)
    if why:
        return _fail(sid, 'отказ: ' + why)
    if not fit:
        return _fail(sid, 'нет входа')
    try:
        import cv2
        import numpy as np
        best = None
        for label, plan, im in cands:
            st = _setup(vf, plan, fit, im)
            if st is None:
                continue
            g, Hh, Ww, s = st['g'], st['H'], st['W'], st['s']
            k = vf.bg_kernel(g)
            bg = cv2.GaussianBlur(cv2.morphologyEx(g, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8)), (0, 0), k)
            rel = g.astype(np.float32) * 255.0 / np.maximum(bg.astype(np.float32), 1)
            tol = vf.TOL_MIN + 1.0
            frac_tol = 0.012 * max(Hh, Ww)
            walls, maxdiff = [], 0.0
            for i, seg in enumerate(st['segs']):
                x0, y0, x1, y1, th, wid = seg
                pa, pb, L, _tt, pts, dd = _wall_pts(st, seg)
                band = 0.5 * th * s + vf.TOL_MIN
                narrow = float(np.mean(dd <= tol))
                w_thick = float(np.mean(dd <= max(tol, band)))
                w_frac = float(np.mean(dd <= max(tol, frac_tol)))
                nrm = np.array([-(pb - pa)[1], (pb - pa)[0]]) / max(L, 1e-9)       # бледная линия: в полосе вдоль оси (±band) есть пиксель темнее местной бумаги и ярче строгого порога
                pale = {r: [] for r in GRID}
                for p in pts:
                    best_rel = 1e9
                    for off in range(-int(round(band)), int(round(band)) + 1):
                        xi, yi = int(round(p[0] + nrm[0] * off)), int(round(p[1] + nrm[1] * off))
                        if 0 <= xi < Ww and 0 <= yi < Hh and g[yi, xi] < GRAY_MAX:
                            best_rel = min(best_rel, float(rel[yi, xi]))
                    for r in GRID:
                        pale[r].append(best_rel < r)
                row = rows[i] if i < len(rows) else None
                if row is not None:
                    maxdiff = max(maxdiff, abs(narrow - float(row['доля_на_чернилах'])))
                walls.append({'стена': wid or '#%d' % i, 'длина_px': round(L, 1), 'длина_м': round(L / s / 100.0, 3), 'узко': round(narrow, 3), 'широко_толщина': round(w_thick, 3), 'широко_лист': round(w_frac, 3),
                              'бледная': {str(r): round(float(np.mean(pale[r])), 3) for r in GRID}})
            if best is None or maxdiff < best[0]:
                best = (maxdiff, label, walls, tol, frac_tol)
            if maxdiff <= SHEET_TOL:
                break
        if best is None:
            return _fail(sid, 'нет картинки листа')
        maxdiff, label, walls, tol, frac_tol = best
        tot = sum(w['длина_px'] for w in walls) or 1.0
        return {'лист': sid, 'статус': 'ok' if maxdiff <= SHEET_TOL else 'не сошлось с walls.csv', 'расхождение_узкой_доли_макс': round(maxdiff, 3), 'картинка': label, 'допуск_узкий_px': tol, 'допуск_лист_px': round(frac_tol, 1),
                'на_линии_узко': round(sum(w['длина_px'] * w['узко'] for w in walls) / tot, 3),
                'на_линии_широко_толщина': round(sum(w['длина_px'] * w['широко_толщина'] for w in walls) / tot, 3),
                'на_линии_широко_лист': round(sum(w['длина_px'] * w['широко_лист'] for w in walls) / tot, 3), 'стены': walls}
    except Exception as ex:      # noqa: BLE001  (лист не берём в 2б, причину пишем — как мерка)
        return _fail(sid, 'сбой: %s: %s' % (type(ex).__name__, str(ex)[:200]))


def win_intervals(plan, types=WINDOW_TYPES):
    """{id стены: [(t0, t1)...]} по окнам ОТВЕТА (levels[].openings, type ∈ types: wall, offset, width — в единицах плана); t — доля вдоль стены from→to, offset отсчитан ОТ `from` (проверено диагностикой круга 2в)."""
    out = collections.defaultdict(list)
    for lv in plan.get('levels') or []:
        walls = {w.get('id'): w for w in lv.get('walls') or []}
        for op in lv.get('openings') or []:
            if op.get('type') not in types:
                continue
            w = walls.get(op.get('wall'))
            try:
                off, wd = float(op['offset']), float(op['width'])
                Lu = math.hypot(w['to'][0] - w['from'][0], w['to'][1] - w['from'][1])
            except (TypeError, KeyError, ValueError):
                continue
            if Lu <= 0 or wd <= 0:
                continue
            out[op['wall']].append((off / Lu, (off + wd) / Lu))
    return out


def ext2c(sid, cands, fit, rows, vf, types=WINDOW_TYPES):
    """Круг 2в: участки стены, где В ОТВЕТЕ стоит окно, не считать ни в «выдуманные», ни в долю «на линии» (без порога). → словарь формы ext2c.json."""
    why = vf_refusal(vf)
    if why:
        return _fail(sid, 'отказ: ' + why)
    if not fit:
        return _fail(sid, 'нет входа')
    types = set(types)
    try:
        import numpy as np
        best = None
        for label, plan, im in cands:
            st = _setup(vf, plan, fit, im)
            if st is None:
                continue
            s = st['s']
            wins = win_intervals(plan, types)
            tol = vf.TOL_MIN + 1.0
            walls, maxdiff = [], 0.0
            for i, seg in enumerate(st['segs']):
                x0, y0, x1, y1, th, wid = seg
                pa, pb, L, tt, pts, dd = _wall_pts(st, seg)
                band = 0.5 * th * s + vf.TOL_MIN
                nn = len(tt)
                on_n = dd <= tol
                on_w = dd <= max(tol, band)
                inwin = np.zeros(nn, bool)
                for t0, t1 in wins.get(wid, []):
                    inwin |= (tt >= t0) & (tt <= t1)
                out_ = ~inwin
                narrow = float(on_n.mean())
                row = rows[i] if i < len(rows) else None
                if row is not None:
                    maxdiff = max(maxdiff, abs(narrow - float(row['доля_на_чернилах'])))
                nar_ex = float(on_n[out_].mean()) if out_.any() else None
                wid_ex = float(on_w[out_].mean()) if out_.any() else None
                cls_csv = row['класс'] if row else ''
                cls_ex = cls_csv
                if cls_csv == 'выдуманная':
                    cls_ex = 'окно' if nar_ex is None else ('на линии' if nar_ex >= 0.7 else ('неполная' if nar_ex >= 0.35 else 'выдуманная'))
                walls.append({'стена': wid or '#%d' % i, 'длина_px': round(L, 1), 'длина_м': round(L / s / 100.0, 3), 'окно_доля': round(float(inwin.mean()), 3), 'узко': round(narrow, 3),
                              'узко_без_окон': None if nar_ex is None else round(nar_ex, 3), 'широко_толщина': round(float(on_w.mean()), 3),
                              'широко_толщина_без_окон': None if wid_ex is None else round(wid_ex, 3), 'класс': cls_csv, 'класс_без_окон': cls_ex})
            if best is None or maxdiff < best[0]:
                best = (maxdiff, label, walls, plan)
            if maxdiff <= SHEET_TOL:
                break
        if best is None:
            return _fail(sid, 'нет картинки листа')
        maxdiff, label, walls, plan = best

        def wsum(key):
            num = sum(w['длина_px'] * (1 - w['окно_доля']) * w[key] for w in walls if w[key] is not None)
            den = sum(w['длина_px'] * (1 - w['окно_доля']) for w in walls if w[key] is not None)
            return round(num / den, 3) if den else None
        return {'лист': sid, 'статус': 'ok' if maxdiff <= SHEET_TOL else 'не сошлось с walls.csv', 'расхождение_узкой_доли_макс': round(maxdiff, 3), 'картинка': label,
                'окон': sum(len(v) for v in win_intervals(plan, types).values()), 'стен_с_окном': sum(1 for w in walls if w['окно_доля'] > 0),
                'на_линии_узко': wsum('узко'), 'на_линии_узко_без_окон': wsum('узко_без_окон'), 'на_линии_широко_толщина_без_окон': wsum('широко_толщина_без_окон'), 'стены': walls}
    except Exception as ex:      # noqa: BLE001  (лист не берём, причину пишем — как мерка)
        return _fail(sid, 'сбой: %s: %s' % (type(ex).__name__, str(ex)[:200]))


class ExtStop(Exception):
    """СТОП: лист по своим признакам ОБЯЗАН иметь числа 2б/2в (наложение «легло», вход «как есть»), но вход для расчёта пропал (нет walls.csv, fit.json, картинки или ответа листа).
    Это ошибка потери файла, а не «лист не годится»: молча считать «Ст» как раньше нельзя — иначе выключатели тихо перестают работать (как было без ext-папок)."""


APPLIES, SKIP, STOP = 'применяется', 'не применяется', 'СТОП'


def coverage(ov, rows, fit, cands):
    """Куда относится лист: (APPLIES, '') | (SKIP, причина с пометкой) | (STOP, причина).
    SKIP — наложения нет или оно не «легло» / вход не «как есть»: числам 2б/2в считаться не из чего, это НЕ ошибка — пометка в guard.json («не применяется: …»), звонок «Ст» как раньше.
    STOP — наложение «легло», вход «как есть», а файла/картинки/ответа для расчёта нет: файл пропал по ошибке.
    «Нет наложения» = нет overlay.json (прогон не дошёл) или статус «нет наложения»."""
    if not ov:
        return SKIP, 'нет наложения (overlay.json не получен)'
    stt = ov.get('overlay_status')
    if stt != 'легло':
        return SKIP, 'наложение не «легло» (статус: %s)' % (stt if stt else 'нет')
    if ov.get('вход', 'как есть') != 'как есть':
        return SKIP, 'вход не «как есть» (вход: %s)' % ov.get('вход')
    lost = []
    if not rows:
        lost.append('нет walls.csv (или пуст)')
    if not fit:
        lost.append('нет fit.json')
    if not cands:
        lost.append('нет картинки листа или ответа (plan*.json)')
    if lost:
        return STOP, '; '.join(lost)
    return APPLIES, ''


def with_ext_numbers(ov, sid, cands, fit, rows, vf, want_2b=True, want_2c=True, stop=True):
    """Копия чисел наложения + ov['ext2b'] / ov['ext2c'] — как storozh.with_ext / with_ext2c, но числа считаются здесь. Статус не «ok» → поле не добавляется (звонок «Ст» как раньше).
    Возвращает (ov, {'ext2b': статус|None, 'ext2c': статус|None, 'лист_для_ext': 'применяется'|'не применяется'|'СТОП', 'причина': …}) — статусы и пометка для guard.json (не молча).
    Нет наложения / не «легло» / вход не «как есть» → числа не считаются, пометка «не применяется: …». Пропал вход при «легло» → ExtStop (stop=True) либо пометка «СТОП» (stop=False)."""
    o = dict(ov or {})
    if not (want_2b or want_2c):                      # выключатели 2б и 2в оба выключены — числа не нужны, листы не классифицируем
        return o, {'ext2b': None, 'ext2c': None, 'лист_для_ext': None, 'причина': ''}
    kind, why = coverage(ov, rows, fit, cands)
    st = {'ext2b': None, 'ext2c': None, 'лист_для_ext': kind, 'причина': why}
    if kind == STOP and stop:
        raise ExtStop('%s: %s' % (sid, why))
    if kind != APPLIES:
        if kind == SKIP:
            st['ext2b'] = st['ext2c'] = 'не применяется: ' + why
        else:
            st['ext2b'] = st['ext2c'] = 'СТОП: ' + why
        return o, st
    if want_2b:
        e = ext2b(sid, cands, fit, rows, vf)
        st['ext2b'] = e['статус']
        if e['статус'] == 'ok':
            o['ext2b'] = e
    if want_2c:
        e = ext2c(sid, cands, fit, rows, vf)
        st['ext2c'] = e['статус']
        if e['статус'] == 'ok':
            o['ext2c'] = e
    return o, st
