"""Шаг контрактов банка не молчит (conv-12 п.1, T-20261020-05): отказ предохранителя — строка `WARN:` (статус шага
refresh_daily — warn), банк не тронут, бэкап не пишется; нет модуля предохранителя — исключение (шаг FAIL); сбой
проверки каталога в воротах слота — кандидат отклонён и посчитан, команда печатает `WARN:`. Банк — фикстура во
временной папке, не живой sets3.json. Без сети и базы: БД, фото, меши и compose2 (исполняет сборку при импорте) — заглушки.
    ~/venvs/scout/bin/python tools/scout/tests/test_contracts_fuse.py"""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import types

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


# compose2 при импорте пересобирает sets2.json — подменяем тем, что из него берут (идеал слота — slot_rules)
import slot_rules  # noqa: E402
stub('compose2', slot_ideal=slot_rules.slot_ideal, _SLOT_ENV=slot_rules.slot_envelopes())
stub('img_alive', alive_now=lambda url: True)                  # без сетевой проверки фото
stub('mesh_gate', verdict_for_photo=lambda img, root: None)    # без numpy/trimesh
stub('mesh_ready', gate_active=lambda: False, mesh_ready=lambda sku: True)
stub('slot_contract', photo_ok=lambda sku, context='heal': True)

import sets_incremental as si  # noqa: E402

tmp = tempfile.mkdtemp()
bank = os.path.join(tmp, 'sets3.json')
sets = [{'set_id': f'set-t{i}', 'm2': 18, 'style': 'сканди',
         'items': {'диван': {'mid': 1, 'eid': str(i), 'name': f'Диван {i}', 'w': 200, 'd': 90, 'price': 1000, 'qty': 1}}}
        for i in range(4)]
json.dump(sets, open(bank, 'w', encoding='utf-8'), ensure_ascii=False)
sha = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()  # noqa: E731
before = sha(bank)

si.SETS = bank
si._rows = lambda q: []                                   # «живых» товаров нет — БД не нужна
si._slot_ok = lambda role, cand, s, chosen=None: False    # все позиции вне контракта
si._live_candidates = lambda *a, **k: []                  # замен нет → снятие → затронуты все 4 из 4
out = io.StringIO()
with contextlib.redirect_stdout(out):
    si.enforce_contracts(apply=True)
lines = out.getvalue().splitlines()
warn = [ln for ln in lines if ln.startswith('WARN:')]
check('отказ предохранителя — строка WARN:contracts_fuse', any(ln.startswith('WARN:contracts_fuse:') for ln in warn))
check('в WARN — причина «затронуло бы 4 комплектов из 4»', any('затронуло бы 4 комплектов из 4' in ln for ln in warn))
check('банк не тронут (sha256 тот же)', sha(bank) == before)
check('бэкап .bak-contracts при отказе не пишется', not os.path.exists(bank + '.bak-contracts'))

# нет модуля предохранителя — писать без проверки нельзя: исключение, шаг FAIL (раньше except пропускал запись)
saved = sys.modules.get('heal_policy')
sys.modules['heal_policy'] = None
try:
    with contextlib.redirect_stdout(io.StringIO()):
        si.enforce_contracts(apply=True)
    check('нет heal_policy — исключение', False)
except ImportError:
    check('нет heal_policy — исключение', True)
finally:
    if saved is not None:
        sys.modules['heal_policy'] = saved
    else:
        sys.modules.pop('heal_policy', None)
check('нет heal_policy — банк не тронут', sha(bank) == before)

# ворота слота: сбой каталога → кандидат отклонён и посчитан; рабочий каталог → пропускает
import importlib  # noqa: E402
si = importlib.reload(si)


def broken_media(mid, eid):
    raise ValueError('битая строка каталога')


stub('catalog_media', media=broken_media)
cand = {'mid': 1, 'eid': '9', 'name': 'Диван', 'w': 200, 'd': 90, 'img': 'http://x/1.jpg'}
check('сбой каталога — кандидат отклонён', si._slot_ok('диван', cand, {'m2': 0, 'items': {}}) is False)
check('сбой каталога посчитан', si._GATE_ERRORS.get('ValueError') == 1)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    si._warn_gate_errors()
check('сбой каталога — строка WARN:slot_gate_catalog', out.getvalue().startswith('WARN:slot_gate_catalog:'))

si._GATE_ERRORS.clear()
stub('catalog_media', media=lambda mid, eid: {'state': 'available', 'w': 200, 'd': 90, 'h': 85, 'dia': None})
check('рабочий каталог, размер известен — пропускает', si._slot_ok('диван', cand, {'m2': 0, 'items': {}}) is True)
stub('catalog_media', media=lambda mid, eid: {'state': 'available', 'w': 270, 'd': None, 'h': 86, 'dia': None})
check('глубина неизвестна (Р1) — отклоняет', si._slot_ok('диван', cand, {'m2': 0, 'items': {}}) is False)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    si._warn_gate_errors()
check('без сбоев — WARN нет', out.getvalue() == '')

print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
