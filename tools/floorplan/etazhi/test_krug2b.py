"""Круг 2б (T-ЦП): «Ст» — широкая доля «на линии» и «бледная линия» — «сломал — покраснело». Синтетика, $0, потоки=1.
Круг 2б: «Ст» — широкая доля «на линии» (wide_line) и «бледная линия» (pale_line).
Перенесён в репо из ~/remlab-logs/t171-nalozhenie (T-171/paket, rab-2): без сети, платного и чужих папок; правила — свой storozh_rules.json.
Запуск: python tools/floorplan/etazhi/test_krug2b.py (нужны numpy, pillow, shapely)."""
import copy
import json
import os
import types
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _name in ('nc_eval', 'neutral_names', 'words_on_sheet', 'vetka_a_eval', 'vetka_a_cmp_bd'):      # модули чужих папок: в CI их нет, сторожу эти проверки не нужны
    sys.modules.setdefault(_name, types.ModuleType(_name))
os.environ['SB_RULES'] = HERE + '/storozh_rules.json'      # правила — свои, из репо (выключатели кругов ВКЛ по умолчанию)
os.environ['LABELS_SRC'] = 'labels5'
import storozh as S  # noqa: E402

fails = []
n = 0


def check(name, ok, info=''):
    global n
    n += 1
    print(('OK    ' if ok else 'КРАСНЫЙ ') + name + ((' — ' + info) if info else ''))
    if not ok:
        fails.append(name)


def rules(wide=None, pale=None, mode='on'):
    r = copy.deepcopy(S.RULES)
    r['demote_to_info']['enabled'] = False
    r['p3_loggia_soft']['enabled'] = False
    r['overlay_fail']['enabled'] = False
    r['walls_fail']['mode'] = mode
    r['walls_fail']['wide_line'] = {**dict(enabled=False, variant='thickness'), **(wide or {})}
    r['walls_fail']['pale_line'] = {**dict(enabled=False, rel_max=225, min_share=0.6), **(pale or {})}
    return r


def wall(wid, ln, cls):
    return {'стена': wid, 'длина_px': ln, 'класс': cls}


def ext(wide_t=0.72, wide_s=0.72, pale_w3=0.8, ln_m=5.0):
    return {'статус': 'ok', 'на_линии_широко_толщина': wide_t, 'на_линии_широко_лист': wide_s,
            'стены': [{'стена': 'w1', 'длина_м': 10.0, 'бледная': {'225': 0.0}}, {'стена': 'w3', 'длина_м': ln_m, 'бледная': {'225': pale_w3}}]}


def ov(line=0.55, extra=0.0, e=None, fab=False):
    walls = [wall('w1', 800.0, 'на линии'), wall('w2', 100.0, 'на линии'), wall('w3', 400.0 if fab else 100.0, 'выдуманная' if fab else 'на линии')]
    o = {'на_линии': line, 'лишнее_м': extra, 'стены': walls}
    if e is not None:
        o['ext2b'] = e
    return o


def calls(r, o):
    res = S.finish({'класс': 'с подписями'}, [], [], 'легло', r, ov=o)
    return res['звонки'], res.get('тень_стены')


def st(r, o):
    return 'Ст' in calls(r, o)[0]


check('W1 база (выключатели выключены): на линии 0,55 < 0,60 → звонок Ст', st(rules(), ov(e=ext())))
check('W2 (а) широко 0,72 ≥ 0,60 → Ст не звонит', not st(rules(wide={'enabled': True}), ov(e=ext(wide_t=0.72))))
check('W3 (а) широко 0,50 < 0,60 → Ст звонит и пишет «широко 0.50»', st(rules(wide={'enabled': True}), ov(e=ext(wide_t=0.50))) and 'широко 0.50' in (S.finish({'класс': 'с подписями'}, [], [], 'легло', rules(wide={'enabled': True}, mode='shadow'), ov=ov(e=ext(wide_t=0.50))).get('тень_стены') or ''))
check('W4 (а) variant=sheet берёт «широко_лист», не «толщина»: толщина 0,72, лист 0,30 → звонок', st(rules(wide={'enabled': True, 'variant': 'sheet'}), ov(e=ext(wide_t=0.72, wide_s=0.30))) and not st(rules(wide={'enabled': True, 'variant': 'thickness'}), ov(e=ext(wide_t=0.72, wide_s=0.30))))
check('W5 (а) у листа нет ext2b → звонок как раньше', st(rules(wide={'enabled': True}), ov(e=None)))
check('W6 (б) выдуманная w3 (доля 44 % длины) с бледной линией 0,8 → Ст не звонит', not st(rules(pale={'enabled': True}), ov(line=0.9, e=ext(pale_w3=0.8), fab=True)))
check('W7 (б) бледная доля 0,3 < 0,6 → w3 остаётся выдуманной → звонок', st(rules(pale={'enabled': True}), ov(line=0.9, e=ext(pale_w3=0.3), fab=True)))
o8 = ov(line=0.9, extra=9.0, e=ext(pale_w3=0.8, ln_m=5.0), fab=True)
o8['стены'][2]['длина_px'] = 20.0      # доля выдуманных мала, звонит только «лишнее 9 м»
check('W8б (б) лишнее 9 м без бледной → звонок; с бледной w3 (5 м) → 4 м, не звонит', st(rules(), o8) and not st(rules(pale={'enabled': True}), o8))
check('W9 −КОНТРОЛЬ (б): pale_line выключен → W6 краснеет (звонок)', st(rules(pale={'enabled': False}), ov(line=0.9, e=ext(pale_w3=0.8), fab=True)))
check('W10 −КОНТРОЛЬ (а): wide_line выключен → W2 краснеет (звонок)', st(rules(wide={'enabled': False}), ov(e=ext(wide_t=0.72))))
check('W11 (б) rel_max=215 (данных нет — только 225) → доля 0 → звонок', st(rules(pale={'enabled': True, 'rel_max': 215}), ov(line=0.9, e=ext(pale_w3=0.8), fab=True)))
check('W12 (а)+(б) вместе: и на линии 0,55 (широко 0,72), и выдуманная бледная → не звонит', not st(rules(wide={'enabled': True}, pale={'enabled': True}), ov(line=0.55, e=ext(wide_t=0.72, pale_w3=0.8), fab=True)))
check('W13 (а) не прячет выдуманные: широко 0,72, но выдуманная w3 без бледной линии (доля 44 %) → звонок', st(rules(wide={'enabled': True}, pale={'enabled': True}), ov(line=0.55, e=ext(wide_t=0.72, pale_w3=0.2), fab=True)))
check('W14 mode=shadow: звонка нет, причина в `тень_стены`', not st(rules(mode='shadow'), ov(e=ext())) and calls(rules(mode='shadow'), ov(e=ext()))[1])
with tempfile.TemporaryDirectory() as td:
    p = td + '/ext2b.json'
    json.dump(ext(), open(p, 'w'))
    o = S.with_ext(ov(), p)
    json.dump({'статус': 'не сошлось с walls.csv'}, open(p, 'w'))
    o2 = S.with_ext(ov(), p)
    check('W15 with_ext: файл ok → ov[ext2b]; статус не ok / нет файла → ov без ext2b', 'ext2b' in o and 'ext2b' not in o2 and 'ext2b' not in S.with_ext(ov(), td + '/нет.json'))
check('W16 файл правил: wide_line ВКЛ по умолчанию (принят), pale_line ВЫКЛ (в пакет не входит)', (S.RULES['walls_fail'].get('wide_line') or {}).get('enabled') is True and (S.RULES['walls_fail'].get('pale_line') or {}).get('enabled') is False)
print('ИТОГ: %d проверок, красных %d' % (n, len(fails)))
sys.exit(1 if fails else 0)
