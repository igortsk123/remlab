#!/usr/bin/env python3
"""Сторож карточки в рецепте пути покраски (T-20261127-174/2): шаг, чей скрипт принимает карточку/запись товара, получает её в `rules/paint-run-all.json`.
Причина: этап 07 запускался БЕЗ --card-json → у всех типовых правил «воздержался: тип не определён (no_type)», верх — top_skip=no_card (находка T-174).
Запуск: python3 tools/scout/tests/test_paint_run_all_card.py"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assets'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_paint_run_all_card')
import paint_run_all as RA  # noqa: E402

FAIL = 0
REAL = RA.load_rules()
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
REC = {'sid': 'k', 'name': 'Стол', 'role': 'стол обеденный', 'params': {'Размеры: Высота габаритная': '75'}}


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


def ctx(rec):
    c = RA.make_ctx('/r', 'k', {'native': 'n', 'photo': 'p', 'product_role': 'стол обеденный', 'channels': '', 'root': ROOT}, REAL)
    c['_record'] = rec
    c['card'] = os.path.join(c['work'], 'card.json') if rec else ''
    c['parts_args'] = []                                           # подставляется dynamic_ctx по факту этапа 3; здесь не важно
    return c


def drop_flag(rules, stage, script, flag):
    """Копия правил, где у шага скрипта `script` этапа `stage` убран флаг и его значение."""
    r = copy.deepcopy(rules)
    for s in r['stages'][stage]['steps']:
        a = s['argv']
        if any(t.endswith(script) for t in a) and flag in a:
            i = a.index(flag)
            del a[i:i + 2]
    return r


# 1. боевой рецепт: все шаги, чьи скрипты принимают карточку, её получают
ok(RA.card_gaps(REAL, ROOT) == [], 'боевой рецепт: у каждого шага со скриптом «принимает карточку» она в argv: ' + '; '.join(RA.card_gaps(REAL, ROOT)))
ok(set(REAL.get('card_flags') or []) >= {'--card', '--card-json'}, 'флаги карточки — в данных рецепта (card_flags), не в коде')
ok(all(isinstance(v, str) and len(v) > 20 for v in (REAL.get('card_exempt') or {}).values()), 'каждое исключение card_exempt — с причиной')

# 2. сторож краснеет: из рецепта убрана карточка
for stage, script, flag in (('07', 'tex_fill.py', '--card-json'), ('06', 'part_grain_stage.py', '--card'), ('06', 'part_material_stage.py', '--card')):
    g = RA.card_gaps(drop_flag(REAL, stage, script, flag), ROOT)
    ok(len(g) == 1 and script in g[0] and flag in g[0], f'нет {flag} у {script} (этап {stage}) → красный: {g}')
no_ex = copy.deepcopy(REAL)
no_ex['card_exempt'] = {}
g = RA.card_gaps(no_ex, ROOT)
ok(any('tex_visible.py' in x and '--product-json' in x for x in g), 'исключение card_exempt действует: без него tex_visible.py --product-json — находка')
bad = copy.deepcopy(REAL)
bad['stages']['07']['steps'][0]['argv'][2] = '{root}/tools/scout/нет_такого.py'
ok(any('не разобран' in x for x in RA.card_gaps(bad, ROOT)), 'скрипт шага не найден → находка, сторож не слепнет молча')

# 3. этап 07: карточка идёт в команду и файл пишется; нет записи каталога — как раньше (флаг выпадает, файла нет)
c_on = ctx(REC)
argv = next(s['argv'] for s in RA.resolve_steps(REAL['stages']['07'], c_on))
ok('--card-json' in argv and argv[argv.index('--card-json') + 1].endswith('work/card.json'), '07 с записью каталога: --card-json = work/card.json')
c_off = ctx(None)
argv0 = next(s['argv'] for s in RA.resolve_steps(REAL['stages']['07'], c_off))
ok('--card-json' not in argv0 and argv0[-1] != '--card-json', '07 без записи каталога: флаг выпадает целиком (как до правки)')
fl = RA.resolve_files(REAL['stages']['07'], c_on)
ok(list(fl.values()) == [{'name': 'Стол', 'role': 'стол обеденный', 'Размеры: Высота габаритная': '75'}], '07: card.json плоский (name, role + params), пишет сам шаг — 06 мог быть пропущен')
ok(RA.resolve_files(REAL['stages']['07'], c_off) == {}, '07 без записи каталога: служебных файлов нет')

# 4. карточка из рецепта доходит до паспорта типа: роль «стол обеденный» → тип найден (раньше no_type)
import mesh_type_passports as MTP  # noqa: E402
pol = MTP.paint_policy(REC['role'])
ok(pol.get('type') == 'стол обеденный' and not pol.get('reason'), f"роль из карточки → паспорт типа найден (тип {pol.get('type')}, причина {pol.get('reason')})")
pol0 = MTP.paint_policy('стол')
ok(pol0.get('reason') == 'no_type', 'роль без типа в паспортах («стол») → по-прежнему no_type: вторая причина воздержаний — каталог ролей, не рецепт')

# 5. сторож окружения рядом со сторожем карточки (T-175/12-дыра): скрипты рецепта читают только учтённые переменные (метка видит их все)
eg = RA.env_gaps(REAL, ROOT)
ok(eg == [], 'боевой рецепт: каждое чтение окружения в скриптах конвейера есть в rules-label.json (env / env_ignore с причиной): ' + '; '.join(eg[:3]))
import rules_label as RL  # noqa: E402
cfg0 = RL.load_cfg(os.path.join(ROOT, 'tools', 'scout', 'rules', 'rules-label.json'))
cfg1 = dict(cfg0, env=[x for x in cfg0['env'] if x != 'POSE_JUNCTION'])
g1 = RL.env_gaps(ROOT, cfg1)
ok(len(g1) == 1 and 'POSE_JUNCTION' in g1[0] and 'pose_fit.py:' in g1[0], 'убрал POSE_JUNCTION из env → красный с именем и файлом:строкой: ' + (g1[0] if g1 else '—'))
cfg2 = dict(cfg0, env_ignore={k: v for k, v in cfg0['env_ignore'].items() if k != 'THREADS'})
g2 = RL.env_gaps(ROOT, cfg2)
ok(len(g2) == 1 and 'THREADS' in g2[0] and 'paint_delight.py:' in g2[0], 'убрал THREADS из «не влияет» → красный: ' + (g2[0] if g2 else '—'))

print(f'paint_run_all_card: ошибок {FAIL}')
sys.exit(1 if FAIL else 0)
