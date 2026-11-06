"""Перед меша — свойство роли в данных, одно место (T-20261106-78).

Прежде направленные роли жили литералом DIRECTED в `mesh_queue.py`: прихожую не дописали, и обувницам/вешалкам
ставилась «symmetric_by_role» с поворотом без проверки (вешалка задом, обувницы боком). Теперь — карта `front`
в `rules/asset-strategies.json` + роли профилей комнат.

  1) Гостиная и спальня: множество направленных ролей побайтно то же, что было литералом.
  2) Прихожая: обувница, шкаф-купе, вешалка, консоль, прихожая — направленные; банкетка — по спинке; зеркало — не меш.
  3) Роль без записи с мешем — направленная; роль без меша — нет; кривое значение карты — ошибка, не молчание.
  4) Деньги: резерв спроса — отдельный список, он тот же, что был; новые роли в запрос резерва не попадают.
  5) Подсказки VLM для старых ролей — те же строки, что были в коде; у каждой направленной роли прихожей — своя.
  6) Каждая роль профиля комнаты с мешем имеет явную запись в `front` (новая комната не уходит «по умолчанию» молча).
    python tools/scout/tests/test_front_roles.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..')
sys.path.insert(0, SCOUT)
import asset_strategy as AS  # noqa: E402
import mesh_queue as MQ  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


# литерал mesh_queue.DIRECTED до T-78 (e6a1e01e, T-20261105-36/2)
OLD = {'диван', 'кресло', 'стул', 'тв-тумба', 'стеллаж', 'комод', 'стенка', 'витрина', 'камин', 'кровать',
       'тумба прикроватная', 'шкаф'}


def roles_of(room):
    return set(json.load(open(os.path.join(SCOUT, 'rules', 'profiles', f'{room}.json'), encoding='utf-8'))['roles'])


LB = roles_of('living') | roles_of('bedroom')
check('1) гостиная+спальня: направленные те же, что литерал', MQ.DIRECTED & LB == OLD, f'{sorted(MQ.DIRECTED & LB ^ OLD)}')
check('1) все старые направленные остались', OLD <= MQ.DIRECTED, f'{sorted(OLD - MQ.DIRECTED)}')

HALL_DIR = {'обувница', 'шкаф-купе', 'вешалка', 'консоль', 'прихожая'}
check('2) прихожая: направленные в DIRECTED', HALL_DIR <= MQ.DIRECTED, f'{sorted(HALL_DIR - MQ.DIRECTED)}')
check('2) банкетка — по спинке', AS.front('банкетка') == 'by_back' and AS.is_directed('банкетка', 'Банкетка со спинкой')
      and not AS.is_directed('банкетка', 'Банкетка Тест') and 'банкетка' not in MQ.DIRECTED)
check('2) банкетка — то же правило в спросе (mesh_queue.directed)',
      MQ.directed('банкетка', 'Банкетка со спинкой', None) and not MQ.directed('банкетка', 'Банкетка', None))
check('2) зеркало — процедурное, не меш: перед не ищем', AS.strategy('зеркало') == 'procedural_plane'
      and AS.front('зеркало') == 'none' and 'зеркало' not in MQ.DIRECTED)

check('3) роль с мешем без записи — направленная', AS.front('роль-новая') == 'directed' and AS.is_directed('?'))
check('3) роль без меша — не направленная', not AS.is_directed('ковёр') and not AS.is_directed('шторы'))
check('3) ненаправленные гостиной — как были', not any(AS.is_directed(r) for r in
                                                       ('столик', 'стол обеденный', 'кашпо', 'торшер', 'ваза', 'люстра')))
_saved = AS._load().get('front')
AS._load()['front'] = dict(_saved, **{'обувница': 'directd'})
try:
    AS.front('обувница')
    check('3) опечатка в карте — ошибка', False)
except ValueError:
    check('3) опечатка в карте — ошибка', True)
AS._load()['front'] = _saved

check('4) резерв спроса — тот же список, что был', MQ.RESERVE_ROLES == OLD, f'{sorted(MQ.RESERVE_ROLES ^ OLD)}')
check('4) резерв — только направленные', MQ.RESERVE_ROLES <= MQ.DIRECTED)
sqls = []
MQ.db = lambda sql, quiet=True: sqls.append(sql) or []
MQ.demand_reserve()
check('4) запрос резерва: роли прихожей не входят (платный спрос сам не растёт)',
      sqls and not any(f"'{r}'" in sqls[0] for r in HALL_DIR) and all(f"'{r}'" in sqls[0] for r in OLD))

# строки ROLE_HINTS из orient_worker.py до T-78 — побайтно
OLD_HINTS = {
    'стул': 'обеденный стул. СПЕРЕДИ: видно сиденье-подушку, спинка ЗА ним. СЗАДИ: только спинка во весь рост',
    'кресло': 'кресло. СПЕРЕДИ: сиденье и подлокотники раскрыты к зрителю. СЗАДИ: глухая спинка',
    'диван': 'диван. СПЕРЕДИ: сиденье и подушки. СЗАДИ: глухая спинка',
    'банкетка': 'банкетка. СПЕРЕДИ: сиденье, спинка за ним. СЗАДИ: спинка закрывает сиденье',
    'тв-тумба': 'ТВ-тумба. СПЕРЕДИ: дверцы, ящики, полки. СЗАДИ: глухая стенка',
    'комод': 'комод. СПЕРЕДИ: ящики с ручками. СЗАДИ: глухая стенка',
    'стеллаж': 'стеллаж. СПЕРЕДИ: открытые полки. СЗАДИ: задняя стенка',
    'стенка': 'мебельная стенка. СПЕРЕДИ: фасады и ниша под ТВ. СЗАДИ: глухая стенка',
    'витрина': 'витрина. СПЕРЕДИ: стеклянные дверцы. СЗАДИ: глухая стенка',
    'камин': 'камин/биокамин. СПЕРЕДИ: очаг (топка). СЗАДИ: глухой корпус',
    'кровать': 'кровать. СПЕРЕДИ: изножье, видна постель, изголовье ЗА ней. СЗАДИ: изголовье закрывает постель',
    'тумба прикроватная': 'прикроватная тумба. СПЕРЕДИ: ящики, дверца или открытая ниша. СЗАДИ: глухая стенка',
    'шкаф': 'шкаф. СПЕРЕДИ: дверцы с ручками или зеркало. СЗАДИ: глухая стенка',
}
check('5) подсказки VLM старых ролей — те же строки', all(AS.front_hint(r) == h for r, h in OLD_HINTS.items()))
check('5) у направленных ролей прихожей — своя подсказка', all(AS.front_hint(r) != r for r in HALL_DIR))
check('5) роль без подсказки — её имя', AS.front_hint('роль-новая') == 'роль-новая')

front = set(AS._load().get('front') or {})
miss = {r for room in ('living', 'bedroom', 'hall') for r in roles_of(room)
        if AS.strategy(r) == 'hunyuan3d' and r not in front}
check('6) роли с мешем гостиной, спальни, прихожей — с явной записью в front', not miss, f'{sorted(miss)}')

print('test_front_roles:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
