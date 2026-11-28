"""Круг 2в (T-ЦП): «Ст» — участки стены под окном ОТВЕТА не считаются ни в «выдуманные», ни в «на линии» — «сломал — покраснело». Синтетика + сквозная проверка мерки на сохранённых ответах ($0, потоки=1).
Круг 2в: окна (walls_fail.windows) в звонке «Ст». Сквозная проверка (мерка на сохранённых ответах) осталась в cikl/ и идёт в сверке пакета.
Перенесён в репо из ~/remlab-logs/t171-nalozhenie (T-171/paket, rab-2): без сети, платного и чужих папок; правила — свой storozh_rules.json.
Запуск: python tools/floorplan/etazhi/test_krug2v.py (нужны numpy, pillow, shapely)."""
import copy
import json
import os
import types
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _name in ('nc_eval', 'neutral_names', 'words_on_sheet', 'vetka_a_eval', 'vetka_a_cmp_bd'):      # модули чужих папок: в CI их нет, сторожу эти проверки не нужны
    sys.modules.setdefault(_name, types.ModuleType(_name))
os.environ['SB_RULES'] = HERE + '/storozh_rules.json'      # правила — свои, из репо (выключатели кругов ВКЛ по умолчанию)
os.environ['LABELS_SRC'] = 'labels5'
import storozh as S  # noqa: E402

W2C = getattr(S, 'with_ext2c', lambda ov_, p_: dict(ov_ or {}))      # старый код без with_ext2c: проверка V15 краснеет, а не падает
fails = []
n = 0


def check(name, ok, info=''):
    global n
    n += 1
    print(('OK    ' if ok else 'КРАСНЫЙ ') + name + ((' — ' + str(info)) if info and not ok else ''))
    if not ok:
        fails.append(name)


def rules(win=False, wide=False, mode='on'):
    r = copy.deepcopy(S.RULES)
    r['demote_to_info']['enabled'] = False
    r['p3_loggia_soft']['enabled'] = False
    r['overlay_fail']['enabled'] = False
    r['walls_fail']['mode'] = mode
    r['walls_fail']['wide_line'] = {'enabled': wide, 'variant': 'thickness'}
    r['walls_fail']['pale_line'] = {'enabled': False, 'rel_max': 225, 'min_share': 0.6}
    r['walls_fail']['windows'] = {'enabled': win}
    return r


def wall(wid, ln, cls):
    return {'стена': wid, 'длина_px': ln, 'класс': cls}


def e3(win_w3=0.6, cls_w3='на линии', line=0.9, wide=0.9, ln_m=4.0):
    """ext2c: у w3 окно занимает win_w3 длины; класс_без_окон — что с оставшимся участком"""
    return {'статус': 'ok', 'на_линии_узко_без_окон': line, 'на_линии_широко_толщина_без_окон': wide,
            'стены': [{'стена': 'w1', 'длина_px': 800.0, 'длина_м': 8.0, 'окно_доля': 0.0, 'класс': 'на линии', 'класс_без_окон': 'на линии'},
                      {'стена': 'w3', 'длина_px': 400.0, 'длина_м': ln_m, 'окно_доля': win_w3, 'класс': 'выдуманная', 'класс_без_окон': cls_w3}]}


def ov(line=0.9, extra=0.0, ext3=None, ext2=None, w3px=400.0):
    o = {'на_линии': line, 'лишнее_м': extra, 'стены': [wall('w1', 800.0, 'на линии'), wall('w2', 100.0, 'на линии'), wall('w3', w3px, 'выдуманная')]}
    if ext3 is not None:
        o['ext2c'] = ext3
    if ext2 is not None:
        o['ext2b'] = ext2
    return o


def st(r, o):
    return 'Ст' in S.finish({'класс': 'с подписями'}, [], [], 'легло', r, ov=o)['звонки']


# ---- синтетика
check('V1 база (окна выкл): выдуманная w3 (31 % длины) → звонок Ст', st(rules(), ov(ext3=e3())))
check('V2 окна вкл: на оставшемся участке w3 чернила есть (класс без окон «на линии») → не звонит', not st(rules(win=True), ov(ext3=e3(cls_w3='на линии'))))
check('V3 окна вкл: класс без окон «неполная» — тоже не выдуманная → не звонит', not st(rules(win=True), ov(ext3=e3(cls_w3='неполная'))))
check('V4 окна вкл: вся w3 под окном (класс «окно») → не звонит', not st(rules(win=True), ov(ext3=e3(win_w3=1.0, cls_w3='окно'))))
check('V5 окна вкл, но вне окна чернил НЕТ (остаётся выдуманной): окно 30 % → 280 из 1180 = 24 % ≥ 15 % → ЗВОНИТ (окно не прячет выдуманную стену)', st(rules(win=True), ov(ext3=e3(win_w3=0.3, cls_w3='выдуманная'))))
check('V5б граница без порога: окно 80 % у стены без чернил → остаток 80 px из 980 = 8 % → не звонит (участок окна исключён из знаменателя и числителя)', not st(rules(win=True), ov(ext3=e3(win_w3=0.8, cls_w3='выдуманная'))))
check('V6 «на линии» без окон: 0,55 < 0,60 → звонок; окна вкл, без окон 0,75 → не звонит', st(rules(), ov(line=0.55, ext3=e3(cls_w3='на линии', line=0.75), w3px=20.0)) and not st(rules(win=True), ov(line=0.55, ext3=e3(cls_w3='на линии', line=0.75), w3px=20.0)))
check('V6б окна вкл, без окон тоже 0,50 < 0,60 → ЗВОНИТ', st(rules(win=True), ov(line=0.55, ext3=e3(cls_w3='на линии', line=0.50), w3px=20.0)))
ext2b = {'статус': 'ok', 'на_линии_широко_толщина': 0.5, 'на_линии_широко_лист': 0.5, 'стены': []}
check('V7 широкая доля без окон: (а) вкл, широко с окнами 0,50 → звонок; окна вкл, широко без окон 0,85 → не звонит', st(rules(wide=True), ov(line=0.55, ext2=ext2b, w3px=20.0)) and not st(rules(win=True, wide=True), ov(line=0.55, ext2=ext2b, ext3=e3(cls_w3='на линии', line=0.55, wide=0.85), w3px=20.0)))
check('V8 «лишнее, м»: 9 м ≥ 8 → звонок; w3 (4 м) перестала быть выдуманной → 5 м → не звонит', st(rules(), ov(extra=9.0, ext3=e3(), w3px=20.0)) and not st(rules(win=True), ov(extra=9.0, ext3=e3(cls_w3='на линии'), w3px=20.0)))
check('V8б «лишнее, м»: w3 осталась выдуманной, окно 50 % (2 м) → 9 − 2 = 7 м < 8 → не звонит; окно 10 % (0,4 м) → 8,6 ≥ 8 → звонит', not st(rules(win=True), ov(extra=9.0, ext3=e3(win_w3=0.5, cls_w3='выдуманная'), w3px=20.0)) and st(rules(win=True), ov(extra=9.0, ext3=e3(win_w3=0.1, cls_w3='выдуманная'), w3px=20.0)))
check('V9 нет ext2c листа (не сошлось/не посчитан) → звонок как раньше', st(rules(win=True), ov(ext3=None)))
check('V10 −КОНТРОЛЬ: windows.enabled=false → V2 краснеет (звонок)', st(rules(win=False), ov(ext3=e3(cls_w3='на линии'))))
check('V11 −КОНТРОЛЬ: windows.enabled=false → V6 краснеет (звонок по «на линии»)', st(rules(win=False), ov(line=0.55, ext3=e3(cls_w3='на линии', line=0.75), w3px=20.0)))
check('V12 mode=off: окна ничего не меняют (звонка нет)', not st(rules(win=True, mode='off'), ov(ext3=e3(win_w3=0.3, cls_w3='выдуманная'))))
r_sh = rules(win=True, mode='shadow')
res = S.finish({'класс': 'с подписями'}, [], [], 'легло', r_sh, ov=ov(ext3=e3(win_w3=0.3, cls_w3='выдуманная')))
check('V13 mode=shadow: звонка нет, причина в `тень_стены`, у стены w3 класс «выдуманная»', 'Ст' not in res['звонки'] and 'w3 выдуманная' in (res.get('тень_стены') or ''))
res2 = S.finish({'класс': 'с подписями'}, [], [], 'легло', rules(win=False), ov=ov(ext3=e3(win_w3=0.6, cls_w3='на линии')))
check('V14 окна выкл: ext2c в ov игнорируется (звонок как раньше)', 'Ст' in res2['звонки'])
with tempfile.TemporaryDirectory() as td:
    p = td + '/ext2c.json'
    json.dump(e3(), open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    o1 = W2C({'на_линии': 0.5}, p)
    json.dump({**e3(), 'статус': 'не сошлось с walls.csv'}, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    o2 = W2C({'на_линии': 0.5}, p)
    o3 = W2C({'на_линии': 0.5}, td + '/нет.json')
check('V15 with_ext2c: статус ok → ov["ext2c"]; не ok / нет файла → ov без изменений', 'ext2c' in o1 and 'ext2c' not in o2 and 'ext2c' not in o3)


check('V16 по умолчанию (storozh_rules.json пакета): walls_fail.mode=on, windows ВКЛ', S.RULES['walls_fail'].get('mode') == 'on' and (S.RULES['walls_fail'].get('windows') or {}).get('enabled') is True)
print('ИТОГ: %d проверок, красных %d' % (n, len(fails)))
sys.exit(1 if fails else 0)
