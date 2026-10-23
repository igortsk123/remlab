"""ПРОМПТ «РЕАЛИСТИЧНО» v3 (demo-11 ADR-0302, demo-13): фотографический вид, каталожная форма, гайды стилей v2.1 и конфликты гайдов.

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


import re

_want = 'improve-v4.3' if os.environ.get('IMPROVE_PROMPT') == 'v4' else 'improve-v3.3'   # v4 — у рисующего процесса прода
check(f'версия промпта {_want}', IM.PROMPT_VERSION == _want, IM.PROMPT_VERSION)
db = json.load(open(os.path.join(HERE, '..', 'styles.json'), encoding='utf-8'))
# ДОБАВЛЕНИЯ, КОТОРЫЕ ГАЙД ДЕЛАТЬ НЕ ВПРАВЕ (demo-13): светильники, ниши, экраны радиатора, ковры, мебель. Ссылки на уже стоящее
# («behind the sofa», «over the sofa») и образ («as if through paper screens») — не добавление.
# Исключение (demo-20 Г4, владелец 22.10): ровно одна строка CEILING LIGHT — единственный светильник; в прочих строках светильников нет
BANNED = re.compile(r'\b(lamps?|lighting|coves?|chandeliers?|pendants?|lanterns?|fixtures?|sconces?|spotlights?|covers?|rugs?|'
                    r'armchairs?)\b', re.I)
SOFA_OK = re.compile(r'\b(behind|over) the sofa\b', re.I)
NEVER_OK = ('never the furniture',)   # неоклассика: «симметрия — не мебель» — защита, а не абсолют стиля
for st in ('сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди'):
    g = db['styles'][st]['render_guide']
    p = IM.prompt_for(st)
    lines = g.splitlines()
    check(f'{st}: шесть блоков гайда', all(any(l.startswith(h) for l in lines) for h in
          ('WALLS:', 'FLOOR:', 'TRIM & DOOR:', 'LIGHT:', 'WINDOW DRESSING:', 'ART & DECOR:', 'STYLE NO:')), g[:60])
    check(f'{st}: гайд целиком в промпте (без выбора застройщика)', g in p)
    check(f'{st}: префикс-защита один раз', p.count('STYLE GUIDE — OPTIONAL PRIORITIES') == 1)
    cl = [l for l in lines if l.startswith('CEILING LIGHT:')]
    check(f'{st}: строка CEILING LIGHT ровно одна — один выключенный светильник у центральной точки потолка', len(cl) == 1 and
          cl[0].startswith('CEILING LIGHT: one ') and cl[0].rstrip('.').endswith('switched off') and
          re.search(r'central ceiling point|centred in the room', cl[0]), str(cl))
    body = '\n'.join(l for l in lines if not l.startswith(('STYLE NO:', 'CEILING LIGHT:')))
    hit = BANNED.findall(body)
    check(f'{st}: вне CEILING LIGHT нет добавления светильников, ниш, экранов, ковров, мебели', not hit, str(hit))
    sofa = [m.start() for m in re.finditer(r'\bsofa\b', body, re.I)]
    check(f'{st}: «sofa» — только как ссылка на стоящий диван', all(SOFA_OK.search(body[max(0, k - 12):k + 5]) for k in sofa))
    check(f'{st}: нет чисел с см/К', not re.search(r'\d+\s*(cm|K)\b', g), g[:80])
    nev = [m.group(0) for m in re.finditer(r'\b(never|exactly)\b[^.;,]*', body, re.I)]
    check(f'{st}: нет абсолютов вне STYLE NO', all(any(n.lower().startswith(ok) for ok in NEVER_OK) for n in nev), str(nev))
    pd = IM.prompt_for(st, None, 'Ламинат «Дуб светлый»', 'Белая матовая')
    fl = next(l for l in lines if l.startswith('FLOOR:')); wl = next(l for l in lines if l.startswith('WALLS:'))
    check(f'{st}: пол и стены застройщика — строк гайда FLOOR/WALLS нет', fl not in pd and wl not in pd and 'TRIM & DOOR:' in pd)
    check(f'{st}: блок PHOTOGRAPHIC LOOK', 'PHOTOGRAPHIC LOOK — MANDATORY' in p)
    check(f'{st}: объектив — как у IMAGE 1, без «24 mm»', 'match IMAGE 1 lens and perspective' in p and '24 mm' not in p)
    check(f'{st}: правило каталожной формы в жёстких правилах',
          'never invent detachable cushions, throws or armrests' in p and p.index('never invent detachable') < p.index('STYLE GUIDE'))
    check(f'{st}: исправление обивки по эталону оставлено', 'Correct inaccurate upholstery' in p)
deny = db['_decor_policy']['deny_always']
check('запрет выдуманных подушек и подлокотников в FORBIDDEN',
      any('cushions, throws or armrests that the catalogue product does not have' == x for x in deny))
# РАДИАТОР ПОД КАЖДЫМ ОКНОМ (demo-20 Г3): одно общее правило для всех стилей, без экрана; уже нарисованный — оставить
for st in ('сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди'):
    _pr = IM.prompt_for(st)
    check(f'{st}: правило радиатора под окном — один раз, без экрана', _pr.count('RADIATORS: under every window') == 1 and
          'with no cover, screen or box' in _pr and 'keep it exactly as rendered' in _pr)
# ПОТОЛОЧНЫЙ СВЕТИЛЬНИК (demo-20 Г4): заглушка сцены заменяется светильником стиля; прочий свет и второй светильник запрещены; без
# противоречий — ни одного общего «не добавлять свет» и «ничего больше» без исключения светильника
for st in ('сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди'):
    for dec in (None, ['ваза']):
        _pr = IM.prompt_for(st, dec)
        _tag = f'{st}{" + декор IMAGE 3" if dec else ""}'
        check(f'{_tag}: блок CEILING FIXTURE один раз, до RENOVATION и до гайда',
              _pr.count('CEILING FIXTURE — THE ONLY NEW LIGHTING') == 1 and
              _pr.index('CEILING FIXTURE — THE ONLY') < _pr.index('RENOVATION') < _pr.index('STYLE GUIDE — OPTIONAL'))
        check(f'{_tag}: белый диск — заглушка, заменить светильником CEILING LIGHT (не «сохранить»)',
              'The flat white disc at the ceiling centre in IMAGE 1 is a schematic placeholder' in _pr and
              'replace it with the fixture described by CEILING LIGHT' in _pr)
        check(f'{_tag}: нет общего запрета света без исключения', 'Do not add visible or concealed lighting' not in _pr and
              'Do not add any visible or concealed lighting except that single ceiling fixture' in _pr)
        check(f'{_tag}: «Nothing else may be added» — только с исключением светильника',
              all(_pr[m.end():m.end() + 7] == ' except' for m in re.finditer('Nothing else may be added', _pr)))
        # с третьим листом (demo-24) новым объектом названы и его предметы: декор и мягкое — купленный товар, светильник — единственный сверх них
        check(f'{_tag}: TASK называет светильник единственным новым объектом',
              re.search(r'The only new object(?: besides the items of IMAGE 3)? is the single ceiling fixture', _pr) is not None)
        check(f'{_tag}: камеру ради светильника не трогать, без свечения',
              'do not move, tilt, widen or raise the camera' in _pr and 'The fixture emits no glow' in _pr)
check('FORBIDDEN: прочий свет и второй светильник; прежнего общего запрета ламп нет',
      any(x.startswith('any lighting other than the single ceiling fixture') for x in deny) and 'a second ceiling fixture' in deny
      and not any(x.startswith('lamps, chandeliers') for x in deny))
check('ALLOWED: светильник стиля — запись решения владельца',
      any('ceiling fixture' in k for k in db['_decor_policy']['allow_now']) and 'ceiling fixture' in IM.prompt_for('сканди').split('Explicitly ALLOWED')[1])
check('отпечаток промпта стабилен', IM.prompt_sha('abc') == IM.prompt_sha('abc') and len(IM.prompt_sha('abc')) == 12)
# improve-v4 (demo-14): список товаров — только по флагу; без флага промпт и версия прежние
check('без флага — improve-v3.3 и без списка товаров', (os.environ.get('IMPROVE_PROMPT') == 'v4') or
      (IM.PROMPT_VERSION == 'improve-v3.3' and 'PRODUCT LIST' not in IM.prompt_for('сканди')))
_pl = [{'id': [1], 'role': 'диван', 'name': 'Диван Викс Рогожка Серый', 'material': 'woven matting fabric', 'colour_name': 'Серый',
        'colour_hex': '#82828C', 'confidence': 0.8}]
_p4 = IM.prompt_for('сканди', products=_pl)
check('список товаров — после правила эталонов, до заглушек', 'PRODUCT LIST' in _p4 and
      _p4.index('Ignore catalogue backgrounds') < _p4.index('PRODUCT LIST') < _p4.index('A grey schematic'))
check('список товаров — тон как базовый, не точный RGB', 'not an exact RGB' in _p4)
sys.exit(1 if fails else 0)
