"""Круг 2г (T-ЦП, Fable otvet-38): «частично → звонок» за выключателем overlay_fail.partial_alarm — «сломал — покраснело». Синтетика + сквозная проверка мерки на сохранённых ответах ($0, потоки=1).
Круг 2г: «частично → звонок» (overlay_fail.partial_alarm). Сквозная проверка на сохранённых ответах (мерка) осталась в cikl/ и идёт в сверке пакета.
Перенесён в репо из ~/remlab-logs/t171-nalozhenie (T-171/paket, rab-2): без сети, платного и чужих папок; правила — свой storozh_rules.json.
Запуск: python tools/floorplan/etazhi/test_krug2g.py (нужны numpy, pillow, shapely)."""
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

fails = []
n = 0


def check(name, ok, info=''):
    global n
    n += 1
    print(('OK    ' if ok else 'КРАСНЫЙ ') + name + ((' — ' + str(info)) if info and not ok else ''))
    if not ok:
        fails.append(name)


def rules(on=False, feature=None, of_on=True):
    r = copy.deepcopy(S.RULES)
    r['demote_to_info']['enabled'] = False
    r['p3_loggia_soft']['enabled'] = False
    r['walls_fail']['mode'] = 'off'
    r['overlay_fail']['enabled'] = of_on
    pa = {'enabled': on}
    if feature:
        pa['feature'] = feature
    r['overlay_fail']['partial_alarm'] = pa
    return r


def fin(r, overlay, klass='с подписями', bad=None, line=0.7):
    return S.finish({'класс': klass}, list(bad or []), [], overlay, r, ov={'на_линии': line})


# ---- G1: выключено — как раньше
r0 = fin(rules(False), 'частично')
check('G1 выкл: «частично» → «сверено частично», звонков нет', r0['исход'].startswith('сверено частично') and r0['звонки'] == [], r0['исход'])
# ---- G2: включено — звонок с честной причиной
r1 = fin(rules(True), 'частично')
check('G2 вкл: «частично» → «на правку», звонок «Нал»', r1['исход'].startswith('на правку') and r1['звонки'] == ['Нал'], r1)
check('G3 вкл: причина — «план лёг на лист частично», с числом на линии', 'план лёг на лист частично' in r1['исход'] and 'на линии 0.70' in r1['исход'], r1['исход'])
check('G4 вкл: verdict() — «звонок Нал»', S.verdict(r1) == 'звонок Нал', S.verdict(r1))
# ---- G5: класс Д (только объявление) — тоже звонок
rd = fin(rules(True), 'частично', klass='Д')
check('G5 вкл, класс Д + «частично» → на правку', rd['исход'].startswith('на правку') and rd['звонки'] == ['Нал'], rd['исход'])
check('G5б выкл, класс Д + «частично» → «сверено только с объявлением … частично» (как раньше)', fin(rules(False), 'частично', klass='Д')['исход'].startswith('сверено только'))
# ---- G6: другие статусы не затронуты
for st, line, want_start in (('легло', 0.8, 'готово'), ('не проверено', None, 'готово')):
    rr = fin(rules(True), st, line=line)
    check('G6 вкл: статус «%s» не затронут' % st, rr['исход'].startswith(want_start) and rr['звонки'] == [], rr['исход'])
rn = fin(rules(True), 'не легло', line=0.50)        # «не легло» с «на линии» ≥ 0,45 → «сверено частично (чернила не объяснены)», НЕ звонок 2г
check('G7 вкл: «не легло», на линии 0,50 → по-прежнему «сверено частично» (чернила листа не объяснены), не звонок 2г', rn['исход'].startswith('сверено частично') and 'чернила листа не объяснены' in rn['исход'] and rn['звонки'] == [], rn['исход'])
rn2 = fin(rules(True), 'не легло', line=0.30)
check('G8 вкл: «не легло», на линии 0,30 → звонок «Нал» прежним текстом «рисунок не подтвердил»', rn2['звонки'] == ['Нал'] and 'рисунок не подтвердил' in rn2['исход'] and 'лёг на лист частично' not in rn2['исход'], rn2['исход'])
# ---- G9: уже есть звонок — не меняется (не дублируется)
rb = fin(rules(True), 'частично', bad=[('П7', 'x')])
check('G9 вкл: у листа уже звонок П7 → звонки = [П7], без добавки', rb['звонки'] == ['П7'] and 'лёг на лист частично' not in rb['исход'], rb['звонки'])
# ---- G10: весь overlay_fail выключен — молчит
roff = fin(rules(True, of_on=False), 'частично')
check('G10 overlay_fail.enabled=false → звонка 2г нет (правило наложения выключено целиком: исход как до него — «готово»)', roff['звонки'] == [] and roff['исход'].startswith('готово'), roff['исход'])
# ---- G11: имя звонка из правил
rf = fin(rules(True, feature='Чст'), 'частично')
check('G11 feature из правил: «Чст»', rf['звонки'] == ['Чст'], rf['звонки'])
# ---- G12: в боевых правилах ключ есть и ВЫКЛ
pa = (S.RULES.get('overlay_fail') or {}).get('partial_alarm')
check('G12 storozh_rules.json: overlay_fail.partial_alarm есть, enabled=true (ВКЛ по умолчанию, принят), feature=Нал', isinstance(pa, dict) and pa.get('enabled') is True and pa.get('feature') == 'Нал', pa)
# ---- G13: нет числа на линии — звонок с «н/д»
rnd = S.finish({'класс': 'с подписями'}, [], [], 'частично', rules(True), ov=None)
check('G13 вкл: нет overlay-чисел → звонок, «на линии н/д»', rnd['звонки'] == ['Нал'] and 'н/д' in rnd['исход'], rnd['исход'])


print('проверок %d, красных %d' % (n, len(fails)))
sys.exit(1 if fails else 0)
