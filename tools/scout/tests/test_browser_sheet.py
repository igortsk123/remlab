"""ЛИСТ ИЗ КАДРОВ БРАУЗЕРА (план demo-10): размер под запрос, полоса на месте, порядок C1/C2, резка обратно, ключ ответа.

    python tools/scout/tests/test_browser_sheet.py        # без сети и модели
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
# `draft_render` ищет солвер по пути машины DEV — в CI это свой чекаут (python:3.12, 17.10: ModuleNotFoundError: planner)
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))
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
# лист телефона: два вертикальных вида бок о бок, вертикальная полоса; резка — слева/справа
pw_, ph_ = (int(x) for x in IM.SIZE_PORTRAIT.split('x'))
pv = ((pw_ - DR.BAND_PX) // 2, ph_)
ps = IM.sheet_from_views([Image.new('RGB', (1489, 2048), (200, 30, 30)), Image.new('RGB', (1117, 1536), (30, 30, 200))], 'portrait')
check('вертикальный лист ровно под запрос', ps.size == (pw_, ph_), str(ps.size))
check('C1 слева, C2 справа, полоса посередине', ps.getpixel((10, 10))[0] > 150 and ps.getpixel((pw_ - 10, 10))[2] > 150
      and ps.getpixel((pv[0] + DR.BAND_PX // 2, ph_ // 2)) == DR.BAND_RGB)
pp = [DR._trim_band(x) for x in DR._split_pair(ps)]
check('резка по вертикальной полосе возвращает оба вида', [p.size for p in pp] == [pv, pv], str([p.size for p in pp]))
slant = ps.copy()
from PIL import ImageDraw as _D
_D.Draw(slant).rectangle((pv[0] - 4, 0, pv[0] - 1, ph_ // 2), fill=DR.BAND_RGB)   # полоса чуть наклонно: остаток у края левого вида
pp2 = [DR._trim_band(x) for x in DR._split_pair(slant)]
check('остаток наклонной полосы у края вида срезан', pp2[0].width <= pv[0] - 4 and pp2[1].size == pv, str([p.size for p in pp2]))
p_port = IM.prompt_for('сканди', orient='portrait')
check('промпт листа телефона: виды слева/справа, вертикальная полоса', 'LEFT half is view 1' in p_port and 'vertical magenta band' in p_port
      and 'position, width and colour' in p_port)
check('промпт обычного листа — как был', 'stacked vertically' in IM.prompt_for('сканди') and 'position, height and colour' in IM.prompt_for('сканди'))
pl = {'views': [{'camera': 'C2', 'id': 'b' * 64}, {'camera': 'C1', 'id': 'a' * 64}], 'style': 'сканди',
      'items': [{'role': 'диван', 'name': 'Диван', 'img': 'x'}]}
k1 = IM.frames_key(pl, 'm', 'medium')
check('ключ ответа не зависит от порядка видов в запросе', k1 == IM.frames_key({**pl, 'views': pl['views'][::-1]}, 'm', 'medium'))
check('ключ различает ориентацию листа', k1 != IM.frames_key({**pl, 'sheet': 'portrait'}, 'm', 'medium'))
check('ключ меняется с моделью и кадрами', k1 != IM.frames_key(pl, 'm2', 'medium')
      and k1 != IM.frames_key({**pl, 'views': [{'camera': 'C1', 'id': 'c' * 64}, pl['views'][0]]}, 'm', 'medium'))
try:
    IM.load_frame('../etc/passwd')
    check('неверное имя кадра отвергается', False)
except ValueError:
    check('неверное имя кадра отвергается', True)
sys.exit(1 if fails else 0)
