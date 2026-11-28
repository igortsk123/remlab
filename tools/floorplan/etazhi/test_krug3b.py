"""Круг 3б (T-ЦП): П2 при 1–2 подписях (p2_few_labels) — «сломал — покраснело». Синтетика, $0, потоки=1.
Круг 3б: П2 при 1–2 подписях (p2_few_labels, ВЫКЛ по умолчанию — проверяется явным включением).
Перенесён в репо из ~/remlab-logs/t171-nalozhenie (T-171/paket, rab-2): без сети, платного и чужих папок; правила — свой storozh_rules.json.
Запуск: python tools/floorplan/etazhi/test_krug3b.py (нужны numpy, pillow, shapely)."""
import copy
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
from shapely.geometry import box  # noqa: E402

fails = []
n = 0


def check(name, ok, info=''):
    global n
    n += 1
    print(('OK    ' if ok else 'КРАСНЫЙ ') + name + ((' — ' + info) if info else ''))
    if not ok:
        fails.append(name)


ROOMS = [{'name': 'Кухня', 'area': 10.0, 'geom': box(0, 0, 4, 2.5)}, {'name': 'Комната', 'area': 15.0, 'geom': box(5, 0, 9, 3.75)}, {'name': 'Ванная', 'area': 4.0, 'geom': box(0, 4, 2, 6)}]
TR = {'ax': 1.0, 'bx': 0.0, 'ay': 1.0, 'by': 0.0, 'n': 0, 'how': 'по площадям'}
L_OK2 = [(2.0, 1.0, 10.0), (7.0, 2.0, 15.0)]          # в двух разных комнатах
L_OUT = [(2.0, 1.0, 10.0), (20.0, 20.0, 15.0)]        # вторая вне комнат
L_ONE = [(2.0, 1.0, 10.0)]
FT_BAD = {'sup': 0.1, 'ctrl': 0.05, 's': 1.0, 'tx': 0, 'ty': 0}
BASE = copy.deepcopy(S.RULES)


def setr(**kv):
    S.RULES['p2_few_labels'] = dict(BASE.get('p2_few_labels') or {})
    S.RULES['p2_few_labels'].update(kv)


check('F0 файл правил: p2_few_labels есть и выключен по умолчанию (прежнее поведение)', (BASE.get('p2_few_labels') or {}).get('enabled') is False)
setr(enabled=False)
check('F1 выключено: p2_min_labels = 3', S.p2_min_labels() == 3)
check('F2 выключено: 2 подписи → П2 не считается (класс Д), как раньше', S.f2(ROOMS, L_OK2, None, TR)[0] is None)
setr(enabled=True, min_labels=1, unregistered='fail')
check('F3 включено: p2_min_labels = 1', S.p2_min_labels() == 1)
ROOMS2 = ROOMS[:2]                                    # две комнаты, две подписи — каждая комната с подписью
check('F4 включено: 2 подписи в двух комнатах (2 комнаты), привязка есть → П2 верно', S.f2(ROOMS2, L_OK2, None, TR)[0] is True)
check('F4б включено (буквально): 2 подписи, 3 комнаты → П2 нет «лишних комнат (без подписи)» — поэтому режим on-soft', S.f2(ROOMS, L_OK2, None, TR)[0] is False and 'лишних комнат 1' in S.f2(ROOMS, L_OK2, None, TR)[1])
setr(enabled=True, min_labels=1, unregistered='fail', ignore_empty=True)
check('F4в ignore_empty: 2 подписи, 3 комнаты → П2 верно (комнат без подписи не считаем)', S.f2(ROOMS, L_OK2, None, TR)[0] is True)
check('F4г ignore_empty не прячет другое: подпись вне комнат → П2 нет', S.f2(ROOMS, L_OUT, None, TR)[0] is False)
S.RULES['p2_few_labels']['ignore_empty'] = False
check('F4д −КОНТРОЛЬ: ignore_empty=false → F4в краснеет (лишних комнат 1)', S.f2(ROOMS, L_OK2, None, TR)[0] is False)
check('F4е ignore_empty не действует при ≥3 подписях: комната без подписи по-прежнему «лишняя»', (S.RULES['p2_few_labels'].update(ignore_empty=True), S.f2(ROOMS, [(2.0, 1.0, 10.0), (7.0, 2.0, 15.0), (7.5, 2.5, 15.0)], None, TR))[1][1].count('лишних комнат') == 1)
check('F5 включено: вторая подпись вне комнат → П2 нет («комната пропущена»)', S.f2(ROOMS, L_OUT, None, TR)[0] is False and 'вне комнат' in S.f2(ROOMS, L_OUT, None, TR)[1])
check('F6 включено, 1 подпись → считается', S.f2(ROOMS, L_ONE, None, TR)[0] is not None)
check('F7 включено: 0 подписей / None → П2 не считается', S.f2(ROOMS, [], None, TR)[0] is None and S.f2(ROOMS, None, None, TR)[0] is None)
check('F8 включено, 2 подписи, не привязать (tr нет, подгонка слабая), unregistered=fail → П2 нет «не могу проверить»', S.f2(ROOMS, L_OK2, FT_BAD, None)[0] is False)
setr(enabled=True, min_labels=1, unregistered='none')
check('F9 unregistered=none: те же 2 подписи не привязать → П2 не считается', S.f2(ROOMS, L_OK2, FT_BAD, None)[0] is None)
check('F10 unregistered=none не трогает ≥3 подписей: «не могу проверить» остаётся', S.f2(ROOMS, L_OK2 + [(1.0, 5.0, 4.0)], FT_BAD, None)[0] is False)
setr(enabled=True, min_labels=2, unregistered='fail')
check('F11 −КОНТРОЛЬ: min_labels=2 → 1 подпись не считается (F6 краснеет), 2 — считается', S.f2(ROOMS, L_ONE, None, TR)[0] is None and S.f2(ROOMS2, L_OK2, None, TR)[0] is True)
setr(enabled=False, min_labels=1)
check('F12 −КОНТРОЛЬ: enabled=false при min_labels=1 → снова 3 (F4 краснеет)', S.p2_min_labels() == 3 and S.f2(ROOMS2, L_OK2, None, TR)[0] is None)
check('F13 П1 при 1–2 подписях НЕ тронут: «нет подписей на листе (класс Д)» даже при включённом p2_few_labels', (setr(enabled=True), S.f1(ROOMS, L_OK2))[1][0] is None)
S.RULES.clear()
S.RULES.update(BASE)
print('ИТОГ: %d проверок, красных %d' % (n, len(fails)))
sys.exit(1 if fails else 0)
