"""Одношаговый вход листа (T-20261126-98/4, Fable otvet-5): весь вход одним вызовом `run(sheet, flags=None)`.

Что делает по порядку (каждый шаг за своим флагом, по умолчанию ВЫКЛ):
  0. доворот повёрнутого листа      deskew (FP_CLEAN_DESKEW; главный угол линий 1,5…30° → поворот, угол в паспорт `source.inputDeskewDeg`;
                                    меняет геометрию → шаг 'deskew' в inputTransform; после него rect не применяется)
  1. выпрямление по линиям         rect   (FP_CLEAN_RECT; меняет геометрию → шаг 'rectify' в inputTransform)
  2. чистка фона скана             bg     (FP_CLEAN_BG)
  3. снятие сетки «в клетку»       grid   (FP_CLEAN_GRID)
  4. усиление бледных линий        lines  (FP_CLEAN_LINES)
  5. вырезка нашей квартиры        cut    (FP_CUT_APT; меняет геометрию → шаг 'crop')
Флаги — ЯВНЫЙ набор `flags` = {'rect','bg','grid','lines','cut': bool}; os.environ читается один раз и только здесь (`flags_from_env`),
поэтому в службе с потоками параллельные вызовы с разными наборами не влияют друг на друга. `FP_INPUT_ALL=1` — все шаги сразу.
Прозрачность: вырезка заливает всё вне квартиры белым (не прозрачным: дальше конвейер работает с RGB-листом без альфа-канала).
Результат — один объект: {'sheet': PIL RGB, 'ops': [...], 'steps': [...геометрия для обратного преобразования...], 'cut': {...}}.
Любой сбой шага — лист как был (чистка и вырезка уже ловят свои исключения). Выключено всё — тот же объект листа, ops == [], steps == [].
Обратное преобразование ответа нейросети на исходный лист — `apartment_cut.source_point(steps, x, y)`."""
import os

import apartment_cut
import cleanup

ENV = {'deskew': 'FP_CLEAN_DESKEW', 'rect': 'FP_CLEAN_RECT', 'bg': 'FP_CLEAN_BG', 'grid': 'FP_CLEAN_GRID', 'lines': 'FP_CLEAN_LINES', 'layers': 'FP_CLEAN_LAYERS', 'cut': 'FP_CUT_APT'}
ENV_OWN = {'quarter': 'FP_CLEAN_QUARTER', 'quarter_after': 'FP_CLEAN_QUARTER_AFTER', 'deskew_guard': 'FP_CLEAN_DESKEW_GUARD', 'deskew_min5': 'FP_CLEAN_DESKEW_MIN5', 'deskew_k6': 'FP_CLEAN_DESKEW_K6'}      # четверть оборота по OCR (Fable otvet-36): ТОЛЬКО своим флагом, FP_INPUT_ALL=1 его не включает (нужен OCR-оценщик `scorer`)


def flag_all() -> bool:
    return os.environ.get('FP_INPUT_ALL', '0') == '1'


def flags_from_env() -> dict:
    """единственное место чтения окружения: набор флагов шагов (FP_INPUT_ALL=1 включает все, кроме quarter)"""
    allf = flag_all()
    f = {k: allf or os.environ.get(v, '0') == '1' for k, v in ENV.items()}
    f.update({k: os.environ.get(v, '0') == '1' for k, v in ENV_OWN.items()})
    return f


def _quarter(sheet, scorer):
    """шаг «четверть оборота» (до всех остальных): → (лист, ops, steps, k). Не применён / нет оценщика / сбой — лист как был."""
    import cv2
    import numpy as np
    import quarter_turn
    from PIL import Image
    try:
        bgr = cv2.cvtColor(np.asarray(sheet.convert('RGB')), cv2.COLOR_RGB2BGR)
        out, info = quarter_turn.quarter_turn(bgr, scorer)
    except Exception:  # noqa: BLE001 — сбой шага: лист как был
        return sheet, [], [], None
    if out is None:
        return sheet, [], [], None
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)), ['quarter'], [{'op': 'quarter', 'k': info['k'], 'turn': info['turn'], 'H': info['H']}], info['k']


def run(sheet, flags=None, scorer=None):
    """PIL RGB → {'sheet', 'ops', 'steps', 'cut', 'deskew_deg', 'quarter_k'}; flags=None — из окружения.
    scorer(k, img_bgr) → оценка поворота k по OCR (нужен только шагу quarter; без него шаг молча пропущен — флаг без оценщика ничего не делает)."""
    if flags is None:
        flags = flags_from_env()
    q_ops, q_steps, q_k = [], [], None
    if flags.get('quarter') and scorer is not None:
        sheet, q_ops, q_steps, q_k = _quarter(sheet, scorer)
    sheet, ops, steps = cleanup.clean_sheet_steps(sheet, flags)
    ops, steps = list(q_ops) + list(ops), list(q_steps) + list(steps)
    if flags.get('quarter') and flags.get('quarter_after') and scorer is not None and q_k is None and 'deskew' in ops \
            and not any(s.get('op') == 'quarter' and 'fail' in s for s in q_steps):
        # T-171/k6-zashchita (Fable otvet-48): первый проход четверти шёл на ещё наклонном листе — OCR на нём плохо читает при любом k (ekb-14444966: 43 против 61, ×2 не набрано);
        # второй проход — на довёрнутом листе, только если доворот сработал и первый проход не повернул. Шаг — в конец steps (порядок применения; source_point разворачивает с конца)
        sheet, q2_ops, q2_steps, q_k = _quarter(sheet, scorer)
        ops, steps = list(ops) + list(q2_ops), list(steps) + list(q2_steps)
    sheet, cut = apartment_cut.cut_sheet(sheet, flags)
    if cut.get('status') == 'cut':
        ops = list(ops) + ['cut']
        steps = list(steps) + [{'op': 'crop', **cut['transform']}]
    deg = next((s['angle_deg'] for s in steps if s.get('op') == 'deskew' and 'angle_deg' in s), None)      # запись «защита доворота сработала» ({'op':'deskew','skip':…}) угла не несёт
    return {'sheet': sheet, 'ops': ops, 'steps': steps, 'cut': cut, 'deskew_deg': deg, 'quarter_k': q_k}
