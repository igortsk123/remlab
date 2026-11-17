"""Золотой ключ ответа standard со СТАРОГО `improve_mode` (ветка main до тарифов): python tests/_tariff_golden_key.py → печатает ключи для теста."""
import os
import subprocess
import sys
import types

import _tariff_fixture as F

HERE = os.path.dirname(os.path.abspath(__file__))
src = subprocess.run(['git', 'show', 'main:tools/scout/improve_mode.py'], cwd=HERE, capture_output=True, text=True, check=True).stdout
old = types.ModuleType('im_main')
old.__file__ = os.path.join(HERE, '..', 'improve_mode.py')
exec(compile(src, 'main:improve_mode.py', 'exec'), old.__dict__)
print('has_tariff_param:', 'tariff' in old.frames_key.__code__.co_varnames)
for name, kw in (('decor', dict(with_decor=True)), ('nodecor', dict(with_decor=False)), ('portrait', dict(with_decor=True))):
    pl = F.payload(**kw)
    if name == 'portrait':
        pl['sheet'] = 'portrait'
    print(name, old.frames_key(pl, 'openai/gpt-image-2.5-sunburst', 'medium'))
