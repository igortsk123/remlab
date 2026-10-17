"""ПРОМПТ «РЕАЛИСТИЧНО» v2 (план demo-11, ADR-0302): блок фотографического вида, правило каталожной формы, тёплые гайды стилей.

    python tools/scout/tests/test_improve_prompt.py        # без сети и модели: только текст промпта и канон стилей
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import improve_mode as IM  # noqa: E402

fails = []


def check(name, cond, info=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    if not cond:
        fails.append(name)


check('версия промпта improve-v2', IM.PROMPT_VERSION == 'improve-v2', IM.PROMPT_VERSION)
db = json.load(open(os.path.join(HERE, '..', 'styles.json'), encoding='utf-8'))
for st in ('сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди'):
    p = IM.prompt_for(st)
    g = db['styles'][st]['render_guide']
    check(f'{st}: блок PHOTOGRAPHIC LOOK', 'PHOTOGRAPHIC LOOK — MANDATORY' in p)
    check(f'{st}: объектив — как у IMAGE 1, без «24 mm»', 'match IMAGE 1 lens and perspective' in p and '24 mm' not in p)
    check(f'{st}: правило каталожной формы в жёстких правилах',
          'never invent detachable cushions, throws or armrests' in p and p.index('never invent detachable') < p.index('STYLE GUIDE'))
    check(f'{st}: гайд стиля в промпте', g in p)
    check(f'{st}: тёплый свет с температурой в гайде', ' K)' in g and ('WARM' in g or 'warm' in g), g[:60])
    check(f'{st}: исправление обивки по эталону оставлено', 'Correct inaccurate upholstery' in p)
deny = db['_decor_policy']['deny_always']
check('запрет выдуманных подушек и подлокотников в FORBIDDEN',
      any('cushions, throws or armrests that the catalogue product does not have' == x for x in deny))
check('отпечаток промпта стабилен', IM.prompt_sha('abc') == IM.prompt_sha('abc') and len(IM.prompt_sha('abc')) == 12)
sys.exit(1 if fails else 0)
