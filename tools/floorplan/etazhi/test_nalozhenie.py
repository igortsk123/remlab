"""T-171/nalozhenie · тесты правила «наложение — часть исхода» (storozh.finish / storozh.verdict / overlay_fail в storozh_rules.json). $0, без сети и нейросетей, только чтение.
Нал: A — finish на синтетике (в т.ч. −контроль) · B — счётчик opus_agent знает новые ярлыки. Части C (прогонщики run_sb100) и D (регресс по сохранённым guard.json) остались в work/ и идут в сверке пакета.
Перенесён в репо из ~/remlab-logs/t171-nalozhenie (T-171/paket, rab-2): без сети, платного и чужих папок; правила — свой storozh_rules.json.
Запуск: python tools/floorplan/etazhi/test_nalozhenie.py (нужны numpy, pillow, shapely)."""
import glob
import importlib.util
import itertools
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
sys.path.insert(1, os.path.dirname(HERE))      # tools/floorplan: opus_agent.py
import storozh as S  # noqa: E402

assert os.path.abspath(S.__file__) == os.path.join(HERE, 'storozh.py'), 'импортирован не рабочий storozh: %s' % S.__file__
import opus_agent as AG  # noqa: E402

STATUSES = ['легло', 'частично', 'не легло', 'не проверено', None]
RULES_ON = json.loads(json.dumps(S.RULES))
RULES_ON["overlay_fail"]["enabled"] = True
RULES_ON["overlay_fail"]["partial_alarm"] = {"enabled": False}      # круг 2г (частично → звонок) здесь не проверяем — он в test_krug2g.py
RULES_OFF = json.loads(json.dumps(RULES_ON))
RULES_OFF['overlay_fail']['enabled'] = False
RULES_EMPTY = json.loads(json.dumps(RULES_ON))
RULES_EMPTY['overlay_fail']['fail_statuses'] = []
RULES_EMPTY['overlay_fail']['partial_statuses'] = []
SP = [('П2', 'подписей вне комнат 1')]
BAD7 = [('П7', 'геометрия ≠ цифре листа')]
RES = []


def check(name, cond, extra=''):
    RES.append((name, bool(cond)))
    print('%s  %s%s' % ('OK  ' if cond else 'FAIL', name, (' — ' + extra) if (extra and not cond) else ''))


def fin(klass, bad, info, overlay, rules, line=None):
    """line — «на_линии» из overlay.json (None — числа нет)"""
    return S.finish({'класс': klass}, bad, info, overlay, rules, ov=None if line is None else {'на_линии': line})


def old_finish(klass, bad, info):
    """эталон: сборка исхода ДО правки (копия прежних строк guard(), без наложения)"""
    sp = ('' if not info else ' · справка (не звонок): ' + '; '.join('%s: %s' % b for b in info))
    if klass == 'Д':
        return ('сверено только с объявлением (П1, П2, П7 проверить нечем)' + sp) if not bad else 'на правку — ' + '; '.join('%s: %s' % b for b in bad) + sp
    return ('готово' + sp) if not bad else 'на правку — ' + '; '.join('%s: %s' % b for b in bad) + sp


# ---------- A. finish на синтетике ----------
def case_fail_goes_to_pravka(rules):
    """«не легло» (лист с подписями, жёстких звонков нет) → исход «на правку», звонок «Нал», ярлык «звонок Нал»"""
    g = fin('с подписями', [], SP, 'не легло', rules)
    return g['исход'].startswith('на правку') and g['звонки'] == ['Нал'] and S.verdict(g) == 'звонок Нал (справка: П2)'


check('A1 «не легло» → на правку, звонок Нал, ярлык «звонок Нал»', case_fail_goes_to_pravka(RULES_ON))
check('A2 −КОНТРОЛЬ: правило выключено → тест A1 красный', not case_fail_goes_to_pravka(RULES_OFF))
check('A2б −КОНТРОЛЬ: список статусов пуст → тест A1 красный', not case_fail_goes_to_pravka(RULES_EMPTY))
g = fin('Д', [], [], 'не легло', RULES_ON)
check('A3 класс Д + «не легло» → на правку Нал (раньше «сверено только с объявлением»)', g['исход'].startswith('на правку') and g['звонки'] == ['Нал'])
g = fin('с подписями', BAD7, SP, 'не легло', RULES_ON)
check('A4 «не легло» + жёсткий П7 → ОБА признака в исходе и в звонках, справка рядом', g['звонки'] == ['П7', 'Нал'] and 'П7: ' in g['исход'] and 'Нал: ' in g['исход'] and 'справка (не звонок): П2' in g['исход'], g['исход'])
g = fin('с подписями', [], SP, 'частично', RULES_ON)
check('A5 «частично» → «сверено частично», не звонок; ярлык «проверено частично (рисунок лёг частично)»',
      g['исход'].startswith('сверено частично') and g['звонки'] == [] and S.verdict(g) == 'проверено частично (рисунок лёг частично) (справка: П2)', g['исход'] + ' | ' + S.verdict(g))
g = fin('Д', [], [], 'частично', RULES_ON)
check('A6 класс Д + «частично» → «сверено только…» + пометка про рисунок, звонка нет', g['исход'].startswith('сверено только') and 'лёг частично' in g['исход'] and g['звонки'] == [])
g = fin('с подписями', BAD7, [], 'частично', RULES_ON)
check('A7 «частично» + жёсткий П7 → «на правку» как раньше, Нал не добавлен', g['исход'].startswith('на правку') and g['звонки'] == ['П7'])
ok = True
for kl, bad, info in itertools.product(('с подписями', 'Д'), ([], BAD7), ([], SP)):
    for ov in ('легло', 'не проверено', None):
        a = fin(kl, bad, info, ov, RULES_ON)
        ok &= a['исход'] == old_finish(kl, bad, info) and a['звонки'] == [n for n, _ in bad]
    for ov in STATUSES:
        b = fin(kl, bad, info, ov, RULES_OFF)
        ok &= b['исход'] == old_finish(kl, bad, info) and b['звонки'] == [n for n, _ in bad] and b['справка'] == [n for n, _ in info]
check('A8 «легло» / «не проверено» / без наложения — исход прежний (эталон-копия старых строк); правило ВЫКЛ — прежний при любом статусе', ok)
diff_only = True
for kl, bad, info in itertools.product(('с подписями', 'Д'), ([], BAD7), ([], SP)):
    for ov in STATUSES:
        same = fin(kl, bad, info, ov, RULES_ON)['исход'] == old_finish(kl, bad, info)
        if ov in ('легло', 'не проверено', None):
            diff_only &= same
        elif ov == 'не легло':
            diff_only &= not same
        else:
            diff_only &= same or (not bad)           # «частично» меняет исход только если жёстких звонков нет
check('A9 включено: меняется ТОЛЬКО у «не легло» (всегда) и «частично» (когда жёстких звонков нет)', diff_only)

# ---------- A10. порог по числу (решение Fable 27.11): «не легло» звонит Нал только при «на линии» < fail_line_max ----------
LMAX = S.RULES['overlay_fail'].get('fail_line_max')
check('A10 порог лежит в файле правил (fail_line_max = 0,45), а не в коде', LMAX == 0.45, str(LMAX))


def case_low_line_bell(rules):
    g = fin('с подписями', [], SP, 'не легло', rules, 0.30)
    return g['исход'].startswith('на правку') and g['звонки'] == ['Нал'] and 'на линии 0.30' in g['исход'] and S.verdict(g) == 'звонок Нал (справка: П2)'


def case_high_line_partial(rules):
    g = fin('с подписями', [], SP, 'не легло', rules, 0.70)
    return (g['исход'].startswith('сверено частично') and 'чернила листа не объяснены ответом' in g['исход'] and g['звонки'] == []
            and S.verdict(g) == 'проверено частично (чернила листа не объяснены ответом) (справка: П2)')


check('A11 «не легло» + на линии 0,30 → звонок Нал (на правку), в причине число', case_low_line_bell(RULES_ON))
check('A12 «не легло» + на линии 0,70 → «сверено частично», причина «чернила листа не объяснены ответом», без звонка', case_high_line_partial(RULES_ON))
check('A13 −КОНТРОЛЬ: правило ВЫКЛ → тесты A11 и A12 красные (оба: исход прежний «готово»)', not case_low_line_bell(RULES_OFF) and not case_high_line_partial(RULES_OFF))
RULES_NOLMAX = json.loads(json.dumps(RULES_ON))
RULES_NOLMAX['overlay_fail']['fail_line_max'] = None
check('A13б −КОНТРОЛЬ: порог убран из правил → тест A12 красный (на 0,70 снова звонок)', not case_high_line_partial(RULES_NOLMAX))
g45 = fin('с подписями', [], [], 'не легло', RULES_ON, 0.45)
g449 = fin('с подписями', [], [], 'не легло', RULES_ON, 0.449)
check('A14 граница: на линии ровно 0,45 → сверено частично (≥ порога); 0,449 → звонок Нал', g45['звонки'] == [] and g45['исход'].startswith('сверено частично') and g449['звонки'] == ['Нал'])
g = fin('Д', [], [], 'не легло', RULES_ON, 0.70)
check('A15 класс Д + «не легло» + 0,70 → «сверено только с объявлением» + пометка, звонка нет', g['исход'].startswith('сверено только') and 'чернила листа не объяснены ответом' in g['исход'] and g['звонки'] == [])
g = fin('Д', [], [], 'не легло', RULES_ON, 0.30)
check('A16 класс Д + «не легло» + 0,30 → на правку Нал', g['исход'].startswith('на правку') and g['звонки'] == ['Нал'])
g = fin('с подписями', BAD7, SP, 'не легло', RULES_ON, 0.70)
check('A17 «не легло» + 0,70 + жёсткий П7 → на правку по П7, Нал не добавлен, справка рядом', g['звонки'] == ['П7'] and g['исход'].startswith('на правку') and 'Нал' not in g['исход'])
g = fin('с подписями', [], [], 'не легло', RULES_ON, None)
check('A18 «не легло», числа «на_линии» нет → звонок Нал (как до порога; нет числа — не смягчаем)', g['звонки'] == ['Нал'] and 'на линии н/д' in g['исход'])
ok = True
for kl, bad, info in itertools.product(('с подписями', 'Д'), ([], BAD7), ([], SP)):
    for ov in ('легло', 'не проверено', None):
        for ln in (None, 0.30, 0.70):
            a = fin(kl, bad, info, ov, RULES_ON, ln)
            ok &= a['исход'] == old_finish(kl, bad, info)
check('A19 число «на линии» ничего не меняет при «легло» / «не проверено» / без наложения (исход прежний)', ok)

# ---------- B. счётчик исходов opus_agent ----------
cases = [('с подписями', [], [], 'не легло'), ('с подписями', BAD7, SP, 'не легло'), ('Д', [], [], 'не легло'), ('с подписями', [], SP, 'частично'), ('Д', [], [], 'частично'),
         ('с подписями', [], [], 'легло'), ('Д', [], [], 'легло'), ('с подписями', BAD7, [], 'легло'), ('с подписями', [], [], 'не проверено'), ('с подписями', [], [], None)]
b_ok = {}
for kl, bad, info, ov in cases:
    v = S.verdict(fin(kl, bad, info, ov, RULES_ON))
    b_ok[(kl, bool(bad), bool(info), ov)] = (v, AG.outcome_of(v, ov))
nal = [x for k, x in b_ok.items() if k[3] == 'не легло']
check('B1 «на правку — Нал» → счётчик «звонок» (не «верно», не «прочее»)', all(o == AG.K_BELL for _, o in nal), str(nal))
part = [x for k, x in b_ok.items() if k[3] == 'частично' and not k[1]]
check('B2 «сверено частично» → счётчик «проверено частично» (не «верно», не «прочее»)', all(o == AG.K_PART for _, o in part), str(part))
check('B3 никакой из новых ярлыков не попал ни в «верно», ни в «проверено, но не легло», ни в «отказ/прочее»',
      all(o not in (AG.K_OK, AG.K_OK_NOLAID, AG.K_OTHER) for _, o in nal + part))
check('B4 «легло» + «готово» → по-прежнему «верно (проверено И легло)»', b_ok[('с подписями', False, False, 'легло')][1] == AG.K_OK and b_ok[('Д', False, False, 'легло')][1] == AG.K_PART)
c = AG.count_outcomes([{'opus': S.verdict(fin('с подписями', [], [], 'не легло', RULES_ON)), 'overlay': {'overlay_status': 'не легло'}},
                       {'opus': S.verdict(fin('с подписями', [], [], 'частично', RULES_ON)), 'overlay': {'overlay_status': 'частично'}},
                       {'opus': S.verdict(fin('с подписями', [], [], 'легло', RULES_ON)), 'overlay': {'overlay_status': 'легло'}}])
check('B5 count_outcomes: звонок 1, частично 1, верно 1, остальное 0', c[AG.K_BELL] == 1 and c[AG.K_PART] == 1 and c[AG.K_OK] == 1 and c[AG.K_OK_NOLAID] == 0 and c[AG.K_OTHER] == 0, str(c))

v70 = S.verdict(fin('с подписями', [], [], 'не легло', RULES_ON, 0.70))
check('B6 ярлык «чернила листа не объяснены ответом» → счётчик «проверено частично» (не «верно», не «проверено но не легло», не «звонок»)',
      AG.outcome_of(v70, 'не легло') == AG.K_PART, v70)


check('A99 по умолчанию (storozh_rules.json пакета): overlay_fail ВКЛ (Нал), partial_alarm ВКЛ', S.RULES['overlay_fail'].get('enabled') is True and (S.RULES['overlay_fail'].get('partial_alarm') or {}).get('enabled') is True)

bad_n = sum(1 for _, ok_ in RES if not ok_)
print('\nИТОГ: %d проверок, красных %d' % (len(RES), bad_n))
sys.exit(1 if bad_n else 0)
