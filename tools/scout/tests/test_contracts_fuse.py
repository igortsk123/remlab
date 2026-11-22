"""Шаги банка не молчат и пара кресел — одна модель (conv-12 п.1–2, T-20261020-05/07).
- contracts: отказ предохранителя — строка `WARN:` (статус шага refresh_daily — warn), банк не тронут, бэкап не пишется;
  нет модуля предохранителя — исключение (шаг FAIL);
- heal: отказ предохранителя — `WARN:heal_fuse_partial` + тревога; снятое «кресло 2» при мёртвом основном — с coverage_gap;
- ворота слота: сбой любой проверки — кандидат отклонён и посчитан, команда печатает `WARN:slot_gate`;
- sync_pairs / --sync-pairs: экземпляр пары = основное кресло, журнал pair_sync, отказ предохранителя — `WARN:pairs_fuse`;
- refresh: каждая замена — в журнал (refresh_upgrade).
Банк — фикстура во временной папке, не живой sets3.json. Без сети и базы: БД, фото, меши, журнал, тревоги и compose2
(исполняет сборку при импорте) — заглушки.
    ~/venvs/scout/bin/python tools/scout/tests/test_contracts_fuse.py"""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import types
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_contracts_fuse')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


def stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m


def run(fn, *a, **k):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(*a, **k)
    return out.getvalue().splitlines()


# compose2 при импорте пересобирает sets2.json — ворота его больше не импортируют; заглушка — страховка теста
import slot_rules  # noqa: E402
stub('compose2', slot_ideal=slot_rules.slot_ideal, _SLOT_ENV=slot_rules.slot_envelopes())
stub('img_alive', alive_now=lambda url: True)                  # без сетевой проверки фото
stub('mesh_gate', verdict_for_photo=lambda img, root: None)    # без numpy/trimesh
stub('mesh_ready', gate_active=lambda: False, mesh_ready=lambda sku: True)
stub('slot_contract', photo_ok=lambda sku, context='heal': True, substitute_ok=lambda sku, strict=None: True)
stub('proportions', check=lambda role, cand, ctx, sub: (True, None, None))   # proportions.json вне git — в CI его нет
import heal_policy as _hp  # noqa: E402 — настоящий предохранитель; журнал и БД — заглушки ниже
JOURNAL = []
SUSP_REAL = [False]    # heal-тесты держат «всё подозрительно»; contracts-тесты — настоящее правило надёжности причины
stub('heal_policy', run_allowed=_hp.run_allowed, MAX_PER_SET_PER_DAY=1,
     contracts_allowed=_hp.contracts_allowed, MAX_CONTRACT_SETS_SHARE=_hp.MAX_CONTRACT_SETS_SHARE,
     record=lambda sid, slot, old, new, reason, source_sha=None: JOURNAL.append((sid, slot, old, new, reason)),
     journal_reason=lambda r: 'archived', suspicious=lambda reason, mid, trusted: _hp.suspicious(reason, mid, trusted) if SUSP_REAL[0] else True,
     trusted_archive_mids=lambda: set(), quarantined=lambda sku: False, budget_left=lambda sid: True)

import sets_incremental as si  # noqa: E402

tmp = tempfile.mkdtemp()
bank = os.path.join(tmp, 'sets3.json')
sha = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()  # noqa: E731


def arm(eid, **kw):
    return dict({'mid': 1, 'eid': eid, 'name': f'Кресло {eid}', 'w': 80, 'd': 80, 'price': 500, 'qty': 1}, **kw)


def write_bank(sets):
    json.dump(sets, open(bank, 'w', encoding='utf-8'), ensure_ascii=False)
    for ext in ('.bak', '.bak-contracts', '.bak-pairs'):
        if os.path.exists(bank + ext):
            os.remove(bank + ext)
    if os.path.exists(os.path.join(tmp, 'contracts-state.json')):   # счёт «прогонов подряд» — на каждый сценарий с нуля
        os.remove(os.path.join(tmp, 'contracts-state.json'))
    return sha(bank)


si.SETS = bank
real_slot_ok, real_live = si._slot_ok, si._live_candidates
si._rows = lambda q: []                                   # БД не нужна

# --- contracts: ширина — много РАЗНЫХ товаров вне контракта (пустой/сломанный фид, сломанная проверка) → стоп ---
def liv(i, vase=None, pill=None, **over):
    """Комплект гостиной: обязательное ядро (диван, столик, носитель ТВ) + необязательные ваза/подушка."""
    def it(role, eid):
        return {'mid': 1, 'eid': eid, 'name': f'{role} {eid}', 'w': 60, 'd': 40, 'price': 100, 'qty': 1}
    items = {'диван': it('диван', f'd{i}'), 'столик': it('столик', f't{i}'), 'тв-тумба': it('тв-тумба', f'tv{i}'),
             'ваза': it('ваза', vase or f'v{i}')}
    if pill:
        items['подушка'] = it('подушка', pill)
    items.update({k: it(k, v) for k, v in over.items()})
    return {'set_id': f'set-c{i}', 'm2': 18, 'style': 'сканди', 'items': items}


import bank_invariants as si_bi
SUSP_REAL[0] = True
BAD = set()                                               # eid позиций вне контракта
si._slot_ok = lambda role, cand, s, chosen=None, current=False: cand.get('eid') not in BAD
si._live_candidates = lambda *a, **k: []                  # замен нет → снятие


def wlines(lines):
    return [ln for ln in lines if ln.startswith('WARN:')]


before = write_bank([liv(i, pill=f'p{i}') for i in range(4)])        # всего 20 разных товаров
BAD.update({f'v{i}' for i in range(4)} | {f'p{i}' for i in range(4)})   # вне контракта 8 из 20 (40 %) — все магазина, ушедшего из фида
warn = wlines(run(si.enforce_contracts, apply=True))
check('contracts: много разных товаров — WARN:contracts_fuse', any(ln.startswith('WARN:contracts_fuse:') for ln in warn))
check('contracts: в WARN причина «отдельных товаров 8 из 20»', any('отдельных товаров 8 из 20' in ln for ln in warn))
check('contracts: банк не тронут (sha256 тот же)', sha(bank) == before)
check('contracts: бэкап .bak-contracts при отказе не пишется', not os.path.exists(bank + '.bak-contracts'))
warn2 = wlines(run(si.enforce_contracts, apply=True))
check('contracts: второй стоп подряд — WARN:contracts_stuck ПЕРВОЙ строкой (в дайджест идёт первая строка WARN), затем fuse',
      [ln.split(':')[1] for ln in warn2] == ['contracts_stuck', 'contracts_fuse'])
BAD.clear()

saved = sys.modules['heal_policy']
sys.modules['heal_policy'] = None                         # нет модуля предохранителя — писать без проверки нельзя
try:
    run(si.enforce_contracts, apply=True)
    check('contracts: нет heal_policy — исключение', False)
except ImportError:
    check('contracts: нет heal_policy — исключение', True)
sys.modules['heal_policy'] = saved
check('contracts: нет heal_policy — банк не тронут', sha(bank) == before)

# --- contracts: радиус — ОДИН товар во всех комплектах (авария 29.08: «один товар выбросило из всех 126») → стоп всегда ---
before = write_bank([liv(i, vase='V') for i in range(10)])              # одна ваза V в 10 из 10; всего 31 разный товар (3 %)
BAD.add('V')
warn = wlines(run(si.enforce_contracts, apply=True))
check('contracts: один товар в 10 из 10 комплектов — WARN:contracts_fuse «в одиночку»',
      any(ln.startswith('WARN:contracts_fuse:') and 'в одиночку трогают' in ln for ln in warn))
check('contracts: …банк и бэкап не тронуты', sha(bank) == before and not os.path.exists(bank + '.bak-contracts'))
BAD.clear()

# --- contracts: «110 из 126» — один товар в ПОЛОВИНЕ комплектов лечится (было: 32 ночи стоп) ---
before = write_bank([liv(i, vase='V' if i < 5 else None) for i in range(10)])   # V в 5 из 10 комплектов, 1 из 36 товаров
BAD.add('V')
JOURNAL.clear()
lines = run(si.enforce_contracts, apply=True)
after = json.load(open(bank, encoding='utf-8'))
check('contracts: один товар в 5 из 10 комплектов — предохранитель пропускает, банк записан', sha(bank) != before and not wlines(lines))
check('contracts: …снят во всех 5 комплектах, ядро цело', all('ваза' not in s['items'] and not si_bi.core_missing(s) for s in after[:5]))
check('contracts: …каждое снятие — coverage_gap и журнал с new_sku=None',
      all(any('coverage_gap: ваза' in g for g in s.get('gaps', [])) for s in after[:5])
      and sorted(j[0] for j in JOURNAL if j[3] is None and j[4] == 'contract_fail') == [f'set-c{i}' for i in range(5)])
BAD.clear()

# --- contracts: порция — товары по возрастанию охвата, пока объединение комплектов ≤ 60 %; остальное — следующим прогоном ---
before = write_bank([liv(i, vase='A' if i < 6 else None, pill='B' if i >= 4 else None) for i in range(10)])   # A в 0–5, B в 4–9
BAD.update({'A', 'B'})
JOURNAL.clear()
lines = run(si.enforce_contracts, apply=True)
after = json.load(open(bank, encoding='utf-8'))
check('contracts: порция — A (6 комплектов = 60 %) снят, B ждёт', all('ваза' not in s['items'] for s in after[:6])
      and all('подушка' in s['items'] for s in after[4:]))
check('contracts: порция — строка «отложено порцией: 1 товаров»', any(ln.startswith('отложено порцией: 1 товаров') for ln in lines))
check('contracts: порция — отложенное идёт в счёт «подряд» (streak 1), WARN нет', not wlines(lines)
      and json.load(open(os.path.join(tmp, 'contracts-state.json')))['streak'] == 1)
lines = run(si.enforce_contracts, apply=True)
after = json.load(open(bank, encoding='utf-8'))
check('contracts: следующий прогон добирает B (охват 6 ≤ 60 %)', all('подушка' not in s['items'] for s in after)
      and not any(ln.startswith('отложено порцией') for ln in lines))
check('contracts: порция выполнена — счёт «подряд» обнулён', json.load(open(os.path.join(tmp, 'contracts-state.json')))['streak'] == 0)
BAD.clear()

# --- contracts: подозрительная причина («карточка мертва») не снимается; надёжная («нет в наличии» по странице) снимается ---
write_bank([liv(i, vase='S' if i < 3 else None, pill='R' if 3 <= i < 6 else None) for i in range(10)])
BAD.update({'S', 'R'})
si._rows = lambda q: ([['1', 'S', 'карточка мертва'], ['1', 'R', 'нет в наличии (страница)']] if 'e.status <>' in q else [])
lines = run(si.enforce_contracts, apply=True)
after = json.load(open(bank, encoding='utf-8'))
check('contracts: «карточка мертва» — позиция остаётся в 3 комплектах', all('ваза' in s['items'] for s in after[:3]))
check('contracts: «нет в наличии (страница)» — снята в 3 комплектах', all('подушка' not in s['items'] for s in after[3:6]))
check('contracts: подозрительное — WARN:contracts_deferred с причиной и числом',
      any(ln.startswith('WARN:contracts_deferred:') and 'карточка мертва — 3' in ln for ln in lines))
lines = run(si.enforce_contracts, apply=True)
check('contracts: подозрительное висит 2 прогона подряд — WARN:contracts_stuck первой строкой',
      [ln.split(':')[1] for ln in wlines(lines)][:1] == ['contracts_stuck'])
BAD.clear()
si._rows = lambda q: []

# --- contracts: ядро — снятие без замены, после которого комплект теряет столик/диван, не применяется ---
before = write_bank([liv(i, **{'столик': 'T'}) for i in range(3)] + [liv(i) for i in range(3, 10)])
BAD.add('T')
lines = run(si.enforce_contracts, apply=True)
after = json.load(open(bank, encoding='utf-8'))
check('contracts: ядро — столик без замены не снят (3 комплекта), файл не тронут', sha(bank) == before
      and all('столик' in s['items'] for s in after[:3]))
check('contracts: ядро — WARN:contracts_core_held с ролью', any(ln.startswith('WARN:contracts_core_held:') and 'столик' in ln
                                                                  for ln in lines))
BAD.clear()

# --- предохранитель contracts_allowed: таблица пределов; run_allowed (heal/pairs) не тронут ---
ca = _hp.contracts_allowed
check('contracts_allowed: 25 из 100 товаров и 60 из 100 комплектов — можно', ca(25, 100, 60, 100)[0])
check('contracts_allowed: 26 из 100 товаров — стоп (ширина)', not ca(26, 100, 10, 100)[0])
check('contracts_allowed: 61 из 100 комплектов — стоп (радиус)', not ca(5, 100, 61, 100)[0])
check('contracts_allowed: ядро ухудшилось — стоп', not ca(5, 100, 10, 100, core_regress=[3])[0])
check('contracts_allowed: в отказе названы крупнейшие по охвату', 'X — 63 компл.' in ca(26, 100, 10, 100, top=[('X', 63)])[1])
check('run_allowed (heal/pairs): прежний предел 25 % комплектов', not _hp.run_allowed(32, 126)[0] and _hp.run_allowed(31, 126)[0])

# --- надёжность причины выбытия (таблица состояний фид/страница/доверие) ---
tr = {'112923'}
sp = _hp.suspicious
check('причина: archived доверенного магазина — надёжна', not sp('archived', 112923, tr))
check('причина: archived недоверенного магазина — подозрительна', sp('archived', 99272, tr))
check('причина: «нет в наличии (страница)» — надёжна', not sp('нет в наличии (страница)', 99272, tr))
check('причина: «карточка мертва» — подозрительна даже у доверенного', sp('карточка мертва', 112923, tr))
check('причина: «роль снята каталогом» — подозрительна', sp('роль снята каталогом', 112923, tr))

SUSP_REAL[0] = False    # дальше heal-тесты: «всё подозрительно», как было
# --- heal: основное кресло и «кресло 2» выбыли, замен нет ---
si._load = lambda: {}
alerts = []
si.subprocess = types.SimpleNamespace(run=lambda args, **k: alerts.append(args[-1]))   # alert.sh не зовём


def dead_rows(eids):
    # индекс кандидатов с «используемыми» товарами: пустой индекс = нечего спрашивать у БД (_dead_reasons не ходит с пустым списком)
    si._load = lambda: {f'1:{e}': {'used': True} for e in eids}
    return lambda q: [['1', e, 'archived'] for e in eids] if 'e.status <>' in q else []


before = write_bank([{'set_id': f'set-h{i}', 'm2': 28, 'style': 'сканди',
                      'items': {'кресло': arm(f'm{i}'), 'кресло 2': arm(f'm{i}', alt=True)}} for i in range(4)])
si._rows = dead_rows([f'm{i}' for i in range(4)])
lines = run(si.heal, apply=True)
check('heal: 4 из 4 касаний — WARN:heal_fuse_partial', any(ln.startswith('WARN:heal_fuse_partial:') for ln in lines))
check('heal: тревога alert.sh — как прежде', any('подозрительных касаний много' in a for a in alerts))
check('heal: при отказе банк не тронут', sha(bank) == before)

sets8 = [{'set_id': f'set-g{i}', 'm2': 28, 'style': 'сканди',
          'items': {'кресло': arm(f'g{i}'), 'кресло 2': arm(f'g{i}', alt=True)}} for i in range(8)]
write_bank(sets8)
si._rows = dead_rows(['g0'])                                  # выбыл один комплект из 8 — предохранитель пропускает
run(si.heal, apply=True)
s0 = json.load(open(bank, encoding='utf-8'))[0]
check('heal: «кресло 2» при мёртвом основном снято', 'кресло 2' not in s0['items'])
check('heal: …и записан coverage_gap про кресло 2', any('кресло 2' in g for g in s0.get('gaps', [])))

# --- sync_pairs / --sync-pairs ---
JOURNAL.clear()
sets8 = [{'set_id': f'set-p{i}', 'm2': 28, 'items': {'кресло': arm(f'a{i}'), 'кресло 2': arm(f'a{i}', alt=True)}}
         for i in range(8)]
sets8[0]['items']['кресло 2'] = arm('old', alt=True, price=300)      # основное сменили, пара отстала
sets8[1]['items']['кресло 3'] = arm('p3')
sets8[1]['items']['кресло 4'] = arm('p4')                             # pod-пара разных моделей
write_bank(sets8)
plan = si.sync_pairs(json.load(open(bank, encoding='utf-8')))
check('sync_pairs: найдены 2 расхождения (кресло 2, кресло 4)', sorted(p[2] for p in plan) == ['кресло 2', 'кресло 4'])
lines = run(si.pairs_step, apply=True)
after = json.load(open(bank, encoding='utf-8'))
check('--sync-pairs: кресло 2 = основное кресло', after[0]['items']['кресло 2']['eid'] == 'a0')
check('--sync-pairs: кресло 4 = кресло 3', after[1]['items']['кресло 4']['eid'] == 'p3')
check('--sync-pairs: сумма комплекта пересчитана', after[0]['total'] == 1000)
check('--sync-pairs: журнал pair_sync на каждую правку', sorted(j[1] for j in JOURNAL if j[4] == 'pair_sync') == ['кресло 2', 'кресло 4'])
check('--sync-pairs: бэкап .bak-pairs', os.path.exists(bank + '.bak-pairs'))
check('--sync-pairs: повтор — расхождений 0', si.sync_pairs(after) == [])

JOURNAL.clear()
before = write_bank([{'set_id': f'set-f{i}', 'm2': 28, 'items': {'кресло': arm(f'x{i}'), 'кресло 2': arm('y', alt=True)}}
                     for i in range(4)])
lines = run(si.pairs_step, apply=True)
check('--sync-pairs: 4 из 4 — WARN:pairs_fuse', any(ln.startswith('WARN:pairs_fuse:') for ln in lines))
check('--sync-pairs: при отказе банк не тронут, журнал пуст', sha(bank) == before and not JOURNAL)
run(si.pairs_step, apply=False)
check('--sync-pairs без --apply: банк не тронут', sha(bank) == before)

# --- refresh: замена в журнал ---
JOURNAL.clear()
write_bank([{'set_id': 'set-r0', 'm2': 18, 'style': 'сканди',
             'items': {'диван': {'mid': 1, 'eid': 'old', 'name': 'Диван старый', 'w': 200, 'd': 90, 'price': 1000}}}])
si._CAND_CACHE.clear()
si._CAND_CACHE['items'] = {'1:old': {'styles': {'сканди': 'низкая'}}, '1:new': {'styles': {'сканди': 'высокая'}}}
si._live_candidates = lambda role, it, *a, **k: ([{'mid': 1, 'eid': 'new', 'name': 'Диван новый', 'w': 200, 'd': 90,
                                                   'price': 1000}] if role == 'диван' else [])
si._slot_ok = lambda role, cand, s, chosen=None, current=False: True
stub('catalog_media', media=lambda mid, eid: None)
stub('testmode', skip=lambda n: False)
run(si.refresh, apply=True)
check('refresh: замена — в журнал (refresh_upgrade)', JOURNAL == [('set-r0', 'диван', '1:old', '1:new', 'refresh_upgrade')])

# --- ворота слота: сбой проверки → отказ + счёт + WARN ---
si._slot_ok, si._live_candidates = real_slot_ok, real_live
stub('compose2')            # пустой: если ворота снова потянут compose2, «рабочие проверки» ниже упадут на конверте
cand ={'mid': 1, 'eid': '9', 'name': 'Диван', 'w': 200, 'd': 90, 'img': 'http://x/1.jpg'}
room = {'m2': 0, 'items': {}}


def boom(*a, **k):
    raise ValueError('сбой')


si._GATE_ERRORS.clear()
stub('catalog_media', media=boom)
check('ворота: сбой каталога — кандидат отклонён', si._slot_ok('диван', cand, room) is False)
stub('catalog_media', media=lambda mid, eid: {'state': 'available', 'w': 200, 'd': 90, 'h': 85, 'dia': None})
for mod, attr in (('slot_contract', 'photo_ok'), ('img_alive', 'alive_now'), ('mesh_gate', 'verdict_for_photo')):
    good = getattr(sys.modules[mod], attr)
    setattr(sys.modules[mod], attr, boom)
    check(f'ворота: сбой {mod}.{attr} — кандидат отклонён', si._slot_ok('диван', cand, room) is False)
    setattr(sys.modules[mod], attr, good)
check('ворота: сбои посчитаны по проверкам',
      si._GATE_ERRORS == {'каталог:ValueError': 1, 'фото:ValueError': 1, 'живое фото:ValueError': 1, 'меш:ValueError': 1})
w = run(si._warn_gate_errors)
check('ворота: строка WARN:slot_gate с числом сбоев', len(w) == 1 and w[0].startswith('WARN:slot_gate:') and 'упали 4 раз' in w[0])
si._GATE_ERRORS.clear()
check('ворота: рабочие проверки, размер известен — пропускает', si._slot_ok('диван', cand, room) is True)
stub('catalog_media', media=lambda mid, eid: {'state': 'available', 'w': 270, 'd': None, 'h': 86, 'dia': None})
check('ворота: глубина неизвестна (Р1) — отклоняет', si._slot_ok('диван', cand, room) is False)
check('ворота: без сбоев — WARN нет', run(si._warn_gate_errors) == [])

# --- catalog_media._load: БД недоступна → исключение, пустой каталог в кэш не попадает ---
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location('catalog_media_real', os.path.join(HERE, '..', 'catalog_media.py'))
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)
cm.PSQL = ['false']                                        # psql вернул ошибку
try:
    cm._load()
    check('catalog_media: psql rc≠0 — исключение', False)
except RuntimeError:
    check('catalog_media: psql rc≠0 — исключение', True)
check('catalog_media: пустой каталог не закэширован', cm._CACHE is None)

print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
