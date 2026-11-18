"""МЕРКА ПЕРЕСВЕТА КАДРА (`cycles_probe/light_metrics.py`, T-20261118-08/1): известные доли на синтетическом кадре и маске; `verdict` против пределов.
python tools/scout/tests/test_light_metrics.py   (нужны numpy, PIL)"""
import os
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'cycles_probe'))
import light_metrics as LM  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


d = tempfile.mkdtemp()
a = np.full((100, 100, 3), 120, np.uint8)
a[:10] = 255                                   # 10 % кадра выбито
a[10:30, :, :] = 244                           # 20 % «почти белое», но не выбито (244 < 250)
Image.fromarray(a).save(f'{d}/f.png')
m = np.zeros((100, 100, 3), np.uint8)
m[:50, :, 1] = 255                             # верхняя половина — нейтральная стена (зелёная)
m[50:, :, 0] = 255                             # нижняя — пол
Image.fromarray(m).save(f'{d}/m.png')
r = LM.measure(f'{d}/f.png', f'{d}/m.png')
check('выбито (любой канал ≥ 250) = 10 %', abs(r['clip_any'] - 0.10) < 1e-6)
check('белое (яркость ≥ 242) = 30 % (выбитое + 244)', abs(r['white'] - 0.30) < 1e-6)
check('по маске: стена — 50 % кадра, из неё белая 60 %, выбитая 20 %', r['wall_n'] == 0.5 and abs(r['wall_white'] - 0.6) < 1e-6 and abs(r['wall_clip'] - 0.2) < 1e-6)
check('по маске: пол не белый', r['floor_white'] == 0.0 and r['floor_clip'] == 0.0)
check('без маски — только кадровые доли', 'wall_n' not in LM.measure(f'{d}/f.png'))
rules = {'limits': {'clip_any': 0.03, 'wall_white': 0.4}}
v = LM.verdict(r, rules)
check('verdict: два предела нарушены', not v['ok'] and {b['key'] for b in v['breaches']} == {'clip_any', 'wall_white'})
check('verdict: в пределах — ok, ключа нет в мерке — не проверяется', LM.verdict({'clip_any': 0.01}, rules)['ok'] and LM.verdict({}, rules)['ok'])
print('итог:', 'чисто' if not fails else f'{len(fails)} падений')
sys.exit(1 if fails else 0)
