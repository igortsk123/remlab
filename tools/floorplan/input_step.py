"""Одношаговый вход листа (T-20261126-98/4, Fable otvet-5): весь вход одним вызовом `run(sheet)`.

Что делает по порядку (каждый шаг за своим флагом, по умолчанию ВЫКЛ; общий `FP_INPUT_ALL=1` включает все сразу):
  1. выпрямление по линиям         FP_CLEAN_RECT   (меняет геометрию → шаг 'rectify' в inputTransform)
  2. чистка фона скана             FP_CLEAN_BG
  3. снятие сетки «в клетку»       FP_CLEAN_GRID
  4. усиление бледных линий        FP_CLEAN_LINES
  5. вырезка нашей квартиры        FP_CUT_APT      (меняет геометрию → шаг 'crop')
Прозрачность: вырезка заливает всё вне квартиры белым (не прозрачным: дальше конвейер работает с RGB-листом без альфа-канала).
Результат — один объект: {'sheet': PIL RGB, 'ops': [...], 'steps': [...геометрия для обратного преобразования...], 'cut': {...}}.
Любой сбой шага — лист как был (чистка и вырезка уже ловят свои исключения). Выключено всё — тот же объект листа, ops == [], steps == [].
Обратное преобразование ответа нейросети на исходный лист — `apartment_cut.source_point(steps, x, y)`."""
import os

import apartment_cut
import cleanup


def flag_all() -> bool:
    return os.environ.get('FP_INPUT_ALL', '0') == '1'


def run(sheet):
    """PIL RGB → {'sheet', 'ops', 'steps', 'cut'}"""
    ops, steps = [], []
    if flag_all():
        env = {k: os.environ.get(k) for k in ('FP_CLEAN_RECT', 'FP_CLEAN_BG', 'FP_CLEAN_GRID', 'FP_CLEAN_LINES', 'FP_CUT_APT')}
        for k in env:
            os.environ[k] = '1'
        try:
            return _run(sheet)
        finally:
            for k, v in env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return _run(sheet)


def _run(sheet):
    sheet, ops, steps = cleanup.clean_sheet_steps(sheet)
    sheet, cut = apartment_cut.cut_sheet(sheet)
    if cut.get('status') == 'cut':
        ops = list(ops) + ['cut']
        steps = list(steps) + [{'op': 'crop', **cut['transform']}]
    return {'sheet': sheet, 'ops': ops, 'steps': steps, 'cut': cut}
