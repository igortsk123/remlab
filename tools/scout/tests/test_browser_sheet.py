"""ЛИСТ ИЗ КАДРОВ БРАУЗЕРА (план demo-10): размер под запрос, полоса на месте, порядок C1/C2, резка обратно, ключ ответа.

    python tools/scout/tests/test_browser_sheet.py        # без сети и модели
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from PIL import Image  # noqa: E402

import draft_render as DR  # noqa: E402
import improve_mode as IM  # noqa: E402

fails = []


def check(name, cond, info=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    if not cond:
        fails.append(name)


rw, rh = (int(x) for x in IM.SIZE.split('x'))
per = (rh - DR.BAND_PX) // 2
c1, c2 = Image.new('RGB', (2048, 1489), (200, 30, 30)), Image.new('RGB', (1536, 1117), (30, 30, 200))
sheet = IM.sheet_from_views([c1, c2])
check('лист ровно под запрос', sheet.size == (rw, per * 2 + DR.BAND_PX), str(sheet.size))
check('пропорция листа = пропорция запроса', abs(sheet.width / sheet.height - rw / rh) < 0.01, f'{sheet.size} vs {IM.SIZE}')
check('C1 сверху', sheet.getpixel((10, 10))[0] > 150 and sheet.getpixel((10, 10))[2] < 80)
check('полоса маджента между видами', sheet.getpixel((rw // 2, per + DR.BAND_PX // 2)) == DR.BAND_RGB)
check('C2 снизу (мелкий кадр растянут до размера вида)', sheet.getpixel((10, sheet.height - 10))[2] > 150)
wide = IM.sheet_from_views([Image.new('RGB', (2400, 1200), (0, 200, 0)), c2])
check('кадр другой пропорции — обрезан по центру, лист тот же', wide.size == sheet.size)
pieces = [DR._trim_band(x) for x in DR._split_pair(sheet)]
check('резка по полосе возвращает оба вида', [p.size for p in pieces] == [(rw, per), (rw, per)], str([p.size for p in pieces]))
pl = {'views': [{'camera': 'C2', 'id': 'b' * 64}, {'camera': 'C1', 'id': 'a' * 64}], 'style': 'сканди',
      'items': [{'role': 'диван', 'name': 'Диван', 'img': 'x'}]}
k1 = IM.frames_key(pl, 'm', 'medium')
check('ключ ответа не зависит от порядка видов в запросе', k1 == IM.frames_key({**pl, 'views': pl['views'][::-1]}, 'm', 'medium'))
check('ключ меняется с моделью и кадрами', k1 != IM.frames_key(pl, 'm2', 'medium')
      and k1 != IM.frames_key({**pl, 'views': [{'camera': 'C1', 'id': 'c' * 64}, pl['views'][0]]}, 'm', 'medium'))
try:
    IM.load_frame('../etc/passwd')
    check('неверное имя кадра отвергается', False)
except ValueError:
    check('неверное имя кадра отвергается', True)
sys.exit(1 if fails else 0)
