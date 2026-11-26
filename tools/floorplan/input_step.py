"""Одношаговый вход листа (T-20261126-98/4, Fable otvet-5): весь вход одним вызовом `run(sheet, flags=None)`.

Что делает по порядку (каждый шаг за своим флагом, по умолчанию ВЫКЛ):
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

ENV = {'rect': 'FP_CLEAN_RECT', 'bg': 'FP_CLEAN_BG', 'grid': 'FP_CLEAN_GRID', 'lines': 'FP_CLEAN_LINES', 'cut': 'FP_CUT_APT'}


def flag_all() -> bool:
    return os.environ.get('FP_INPUT_ALL', '0') == '1'


def flags_from_env() -> dict:
    """единственное место чтения окружения: набор флагов шагов (FP_INPUT_ALL=1 включает все)"""
    allf = flag_all()
    return {k: allf or os.environ.get(v, '0') == '1' for k, v in ENV.items()}


def run(sheet, flags=None):
    """PIL RGB → {'sheet', 'ops', 'steps', 'cut'}; flags=None — из окружения"""
    if flags is None:
        flags = flags_from_env()
    sheet, ops, steps = cleanup.clean_sheet_steps(sheet, flags)
    sheet, cut = apartment_cut.cut_sheet(sheet, flags)
    if cut.get('status') == 'cut':
        ops = list(ops) + ['cut']
        steps = list(steps) + [{'op': 'crop', **cut['transform']}]
    return {'sheet': sheet, 'ops': ops, 'steps': steps, 'cut': cut}
