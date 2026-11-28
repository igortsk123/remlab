"""Врезка флажка «проверь площадь» в сторож Этажей (T-171/флажок-площади, Fable ❓25/❓26; rab-7 28.11): «выкл = побайтно прежнее», «вкл = только справка», −контроли.
Синтетика, $0, без сети и чужих папок. Запуск: python tools/floorplan/etazhi/test_area_flag_storozh.py (нужны numpy, pillow, shapely).
Сам счёт площади и границу 0,222 проверяет tests/floorplan/test_area_flag.py (модуль tools/floorplan/area_flag.py); здесь — только ХУК сторожа:
  with_area_flag (его зовёт guard) при area_flag.enabled=false возвращает справку как есть и не трогает res; finish даёт тот же исход, что и без ключа area_flag в правилах;
  при enabled=true добавляет ровно одну справку «Пл», звонки/класс/префикс исхода те же; числа в правилах сверяются с модулем (расхождение — остановка)."""
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _name in ('nc_eval', 'neutral_names', 'words_on_sheet', 'vetka_a_eval', 'vetka_a_cmp_bd'):      # модули чужих папок: в CI их нет, этим проверкам они не нужны
    sys.modules.setdefault(_name, types.ModuleType(_name))
os.environ['SB_RULES'] = HERE + '/storozh_rules.json'      # правила — свои, из репо
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


def dump(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)


def box(rid, name, x0, y0, w, h, t=0.15, kind='interior', **kw):
    pts = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]
    walls = [{'id': '%s-w%d' % (rid, i), 'from': pts[i], 'to': pts[(i + 1) % 4], 'thickness': t, 'kind': kind} for i in range(4)]
    room = {'id': rid, 'name': name, 'polygon': pts}
    room.update(kw)
    return room, walls


r1, w1 = box('r1', 'Комната', 0, 0, 4.0, 3.0)
r2, w2 = box('b1', 'Балкон', 5.0, 0, 3.0, 1.0, use='balcony')
PLAN = {'units': 'm', 'levels': [{'id': 'L1', 'rooms': [r1, r2], 'walls': w1 + w2}]}
ROOMS = S.get_rooms(PLAN, 1.0)
D7 = {'rr': [{'j': 0, 'имя': 'Комната', 'цифра': 20.0, 'а': 0.55}, {'j': 1, 'имя': 'Балкон', 'цифра': 0.5, 'а': 6.0}]}      # комната: чистая 10,97 при подписи 20 → −45 %; балкон — вне флажка


def res0():
    return {'лист': 'x', 'вар': 'b', 'модель': 'opus', 'класс': 'с подписями'}


BASE_INFO = [('П4', 'сумма комнат вне полосы (синтетика)')]


def rules_with(**kv):
    r = json.loads(json.dumps(S.RULES))
    r['area_flag'].update(kv)
    return r


def with_rules(r, fn):
    old = S.RULES
    S.RULES = r
    try:
        return fn()
    finally:
        S.RULES = old


cfg = S.RULES.get('area_flag') or {}
check('A1 в правилах репо area_flag есть и ВЫКЛ по умолчанию', cfg.get('enabled') is False and cfg.get('boundary') == 0.222, str(cfg.get('enabled')))
AF = S._area_flag_module()
check('A2 числа в правилах = числам модуля (граница 0,222; 0,35/0,06; 0,40/0,15), путь модуля из правил', AF.BOUNDARY == 0.222 and AF.COND_EXT_M == 0.35 and os.path.basename(AF.__file__) == 'area_flag.py')
bad_rules = rules_with(boundary=0.5)
try:
    with_rules(bad_rules, S._area_flag_module)
    stopped = False
except RuntimeError as e:
    stopped = 'boundary' in str(e)
check('A3 −контроль: число в правилах ≠ модулю → остановка с причиной, не молча', stopped)

# выкл: хук ничего не делает, finish даёт то же, что и без ключа area_flag в правилах
res = res0()
snap = dump(res)
got = S.with_area_flag(res, list(BASE_INFO), PLAN, ROOMS, D7, 'легло', {'на_линии': 0.9})
check('B1 выкл: with_area_flag возвращает справку как есть и не трогает res', got == BASE_INFO and dump(res) == snap)
off = S.finish(res0(), [], list(got), 'легло')
no_key = json.loads(json.dumps(S.RULES))
no_key.pop('area_flag')
ref = with_rules(no_key, lambda: S.finish(res0(), [], list(with_rules(no_key, lambda: S.with_area_flag(res0(), list(BASE_INFO), PLAN, ROOMS, D7, 'легло', {'на_линии': 0.9}))), 'легло'))
check('B2 выкл: исход побайтно такой же, как у правил БЕЗ ключа area_flag (прежний сторож)', dump(off) == dump(ref), off['исход'][:80])

# вкл: ровно одна справка «Пл», исход/звонки/класс те же
on_rules = rules_with(enabled=True)
res_on = res0()
info_on = with_rules(on_rules, lambda: S.with_area_flag(res_on, list(BASE_INFO), PLAN, ROOMS, D7, 'легло', {'на_линии': 0.9}))
added = [x for x in info_on if x[0] == 'Пл']
check('C1 вкл: справка «Пл» одна, прежняя справка на месте', len(added) == 1 and info_on[:1] == BASE_INFO, str(added))
check('C2 вкл: текст — «проверь площадь: комната Комната расходится с подписью на 45 % (толщина своя)», балкон не упомянут',
      added and added[0][1] == 'проверь площадь: комната Комната расходится с подписью на 45 % (толщина своя)', added[0][1] if added else '')
fl = res_on.get('площадь_флажок') or {}
check('C3 вкл: в res детали — группа толщины, флажки, строки; схема нет', fl.get('схема') is False and len(fl.get('флажки') or []) == 1 and fl['флажки'][0]['id'] == 'r1')
on = S.finish(res_on, [], list(info_on), 'легло')
check('C4 вкл: звонки, класс, префикс исхода те же; справка = прежняя + «Пл»',
      on['звонки'] == off['звонки'] and on['класс'] == off['класс'] and on['исход'].split(' · справка')[0] == off['исход'].split(' · справка')[0] and on['справка'] == off['справка'] + ['Пл'], on['исход'][:90])
check('C5 вкл ≠ выкл (проверка чувствительна: сравнение побайтно ловит добавленную справку)', dump(on) != dump(off))
res_nolab = res0()
info_nl = with_rules(on_rules, lambda: S.with_area_flag(res_nolab, list(BASE_INFO), PLAN, ROOMS, {}, 'легло', None))
check('C6 вкл без подписей листа (d7 пуст): справки «Пл» нет, исход не падает', info_nl == BASE_INFO)
okp = box('r1', 'Комната', 0, 0, 4.0, 3.0)
plan_ok = {'units': 'm', 'levels': [{'id': 'L1', 'rooms': [okp[0]], 'walls': okp[1]}]}
d7_ok = {'rr': [{'j': 0, 'имя': 'Комната', 'цифра': 10.9725, 'а': 1.0}]}
info_ok = with_rules(on_rules, lambda: S.with_area_flag(res0(), list(BASE_INFO), plan_ok, S.get_rooms(plan_ok, 1.0), d7_ok, 'легло', None))
check('C7 −контроль: подпись = чистой площади → справки «Пл» нет (хук не метит всё подряд)', info_ok == BASE_INFO)

print('\nпроверок %d, красных %d' % (n, len(fails)))
sys.exit(1 if fails else 0)
