"""Круг 3 (T-ЦП): П7с в справку только при чистом наложении — «сломал — покраснело». Синтетика + сохранённые ответы, $0, потоки=1.
Круг 3: П7с в справку только при чистом наложении (demote_to_info.clean_only).
Перенесён в репо из ~/remlab-logs/t171-nalozhenie (T-171/paket, rab-2): без сети, платного и чужих папок; правила — свой storozh_rules.json.
Запуск: python tools/floorplan/etazhi/test_krug3.py (нужны numpy, pillow, shapely)."""
import json
import os
import types
import sys

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


def rules(**kv):
    r = json.loads(json.dumps(S.RULES))
    r['p3_loggia_soft']['enabled'] = False
    r['walls_fail']['mode'] = 'off'
    r['demote_to_info']['enabled'] = True
    for k, v in kv.items():
        r['demote_to_info'][k] = v
    return r


def walls(fab_share):
    tot = 1000.0
    return [{'стена': 'w1', 'длина_px': tot * (1 - fab_share), 'класс': 'на линии'}, {'стена': 'w2', 'длина_px': tot * fab_share, 'класс': 'выдуманная'}]


def ov(line=0.80, fab=0.02, with_walls=True):
    o = {'на_линии': line}
    if with_walls:
        o['стены'] = walls(fab)
    return o


F = [('П7с', 'контур комнаты на стенах ответа: …', False)]


def hard(over='легло', o=None, rl=None):
    b, _ = S.split_features(F, 'opus', over, rl or rules(), ov=o)
    return [x[0] for x in b]


check('K1 чистое наложение (легло, на линии 0,80, выдуманных 2 %): П7с в справку, звонка нет', hard('легло', ov()) == [])
check('K2 на линии 0,70 < 0,75: П7с остаётся ЗВОНКОМ', hard('легло', ov(line=0.70)) == ['П7с'])
check('K3 выдуманных 6 % ≥ 5 %: П7с остаётся звонком', hard('легло', ov(fab=0.06)) == ['П7с'])
check('K4 статус «частично»: П7с остаётся звонком (ворота их не касаются — по умолчанию П1–П3)', hard('частично', ov()) == ['П7с'])
check('K5 нет списка стен (walls.csv не прочитан): не чистое → звонок', hard('легло', ov(with_walls=False)) == ['П7с'])
check('K6 ov не передан: звонок (как до круга 3)', hard('легло', None) == ['П7с'])
check('K7 граница: на линии ровно 0,75 → в справку', hard('легло', ov(line=0.75)) == [])
check('K8 граница: на линии 0,7499 → звонок', hard('легло', ov(line=0.7499)) == ['П7с'])
check('K9 граница: выдуманных ровно 5 % → звонок (нужно < 5 %)', hard('легло', ov(fab=0.05)) == ['П7с'])
check('K10 −КОНТРОЛЬ: clean_only=false — как в задаче 3: П7с в справку даже при ov=None (K2 краснеет)', hard('легло', None, rules(clean_only=False)) == [] and hard('легло', ov(line=0.70), rules(clean_only=False)) == [])
check('K11 −КОНТРОЛЬ: demote_to_info.enabled=false → П7с звонок и при чистом наложении (K1 краснеет)', hard('легло', ov(), rules(enabled=False)) == ['П7с'])
check('K12 −КОНТРОЛЬ: порог 0,95 → при 0,80 звонок (K1 краснеет)', hard('легло', ov(line=0.80), rules(clean_line_min=0.95)) == ['П7с'])
b, i = S.split_features([('П3', 'без входа', False), ('П7с', 'x', False)], 'opus', 'легло', rules(), ov=ov(line=0.70))
check('K13 П3 не затронут кругом 3: остаётся звонком; П7с — звонок', [x[0] for x in b] == ['П3', 'П7с'])
check('K14 clean_overlay: пустой список стен → доля 0 → чисто при на линии ≥ 0,75', S.clean_overlay('легло', {'на_линии': 0.9, 'стены': []}, rules()['demote_to_info']) is True)
check('K15 старый вызов split_features без ov (правила как в файле, clean_only=true): П7с звонок', [x[0] for x in S.split_features(F, 'opus', 'легло', S.RULES)[0]] == ['П7с'])
check('K16 по умолчанию (принятый набор): demote_to_info ВЫКЛ (круг 3 не принят; clean_only=true в файле), p3_loggia_soft ВЫКЛ, p2_few_labels ВЫКЛ', S.RULES["demote_to_info"].get("enabled") is False and S.RULES["demote_to_info"].get("clean_only") is True and S.RULES["p3_loggia_soft"].get("enabled") is False and (S.RULES.get("p2_few_labels") or {}).get("enabled") is False)
print('ИТОГ: %d проверок, красных %d' % (n, len(fails)))
sys.exit(1 if fails else 0)
