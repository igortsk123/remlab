"""Глубина дивана с чертежа (`drawing_dims.py`, conv-15) — разбор ответа модели и выбор глубины кодом. Без сети и базы.

Фикстуры — ответы в форме схемы по трём реальным чертежам mnogomebeli/divanboss (`tests/fixtures/drawing-dims/`):
угловой «Босс ХЛ» 285×156, прямой «Босс двухместный» 167×112, угловой «Кинг» 291×160 (сверху 242 — прямая часть, 65 —
сиденье). Проверяем:
  1) строгий разбор: лишний ключ, не тот тип, неизвестный вид/единица — исключение, а не глубина;
  2) выбор d: общая ширина = карточке ±max(3 см, 2 %) → общий габарит поперёк ширины; все гейты отказа;
  3) кэш ключуется по sha + модель + версия промпта/схемы;
  4) прогон: сухо — ни одного вызова модели; платно — не больше --max-calls; исходы сходятся с eligible;
  5) шлюз без прямого OpenAI: `llm_gateway.chat(direct_fallback=False)` не ходит на api.openai.com.
    python3 tools/scout/tests/test_drawing_dims.py"""
import copy
import io
import json
import os
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..')
FIX = os.path.join(HERE, 'fixtures', 'drawing-dims')
sys.path.insert(0, SCOUT)
import drawing_dims as DD  # noqa: E402
import llm_gateway  # noqa: E402

fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


def raw(name):
    return open(os.path.join(FIX, name), encoding='utf-8').read()


def raises(txt):
    try:
        DD.parse(txt)
    except (ValueError, TypeError):
        return True
    return False


XL, TWO, KING = (DD.parse(raw(f)) for f in ('boss-xl-corner.json', 'boss-2seat.json', 'king-corner.json'))


def edit(rd, **kw):
    """Копия прочтения с заменой/добавлением линий: kw[i] = новая линия или None (удалить); extra=[…] — добавить."""
    r = copy.deepcopy(rd)
    for i, ln in sorted(((int(k[1:]), v) for k, v in kw.items() if k.startswith('l')), reverse=True):
        if ln is None:
            r['lines'].pop(i)
        else:
            r['lines'][i] = {**r['lines'][i], **ln}
    r['lines'] += kw.get('extra', [])
    if 'configurations' in kw:
        r['configurations'] = kw['configurations']
    return r


def line(view, axis, typ, value, unit='см'):
    return {'view': view, 'axis': axis, 'type': typ, 'value': value, 'unit': unit, 'text': f'{value} {unit or ""}'.strip()}


# 1) разбор
check('фикстура «Босс ХЛ»: 6 линий, 1 вариант', XL['configurations'] == 1 and len(XL['lines']) == 6)
check('обёртка ```json … ``` целиком допускается', len(TWO['lines']) == 6)
good = json.loads(raw('king-corner.json'))
check('не JSON — исключение', raises('глубина 160 см'))
check('лишний ключ верхнего уровня (confidence) — исключение', raises(json.dumps({**good, 'confidence': 0.99})))
check('нет ключа lines — исключение', raises(json.dumps({'configurations': 1})))
bad = copy.deepcopy(good); bad['lines'][0]['value'] = True
check('число-булево — исключение', raises(json.dumps(bad)))
bad = copy.deepcopy(good); bad['lines'][0]['value'] = '291'
check('число строкой — исключение', raises(json.dumps(bad)))
bad = copy.deepcopy(good); bad['lines'][0]['view'] = 'iso'
check('неизвестный вид — исключение', raises(json.dumps(bad)))
bad = copy.deepcopy(good); bad['lines'][0]['unit'] = 'in'
check('неизвестная единица — исключение', raises(json.dumps(bad)))
bad = copy.deepcopy(good); bad['lines'][0]['type'] = 'depth'
check('неизвестный тип линии — исключение', raises(json.dumps(bad)))
bad = copy.deepcopy(good); bad['lines'][0]['conf'] = 1
check('лишний ключ в линии — исключение', raises(json.dumps(bad)))
check('configurations 0 — исключение', raises(json.dumps({**good, 'configurations': 0})))
check('текст вокруг JSON (не обёртка) — исключение', raises('Вот ответ: ' + raw('king-corner.json')))

# 2) выбор глубины и гейты
d = DD.decide(XL, 285, 96, 'угловой')
check(f'угловой «Босс ХЛ» 285 → d=156 (не сиденье 55): {d["outcome"]} {d["d"]}', d['outcome'] == 'accepted' and d['d'] == 156)
d = DD.decide(TWO, 167, 89, 'прямой')
check(f'прямой «Босс двухместный» 167 → d=112, высота 89 против 88 в пределах: {d["outcome"]} {d["d"]}',
      d['outcome'] == 'accepted' and d['d'] == 112)
d = DD.decide(KING, 291, 82, 'угловой')
check(f'«Кинг» 291 → d=160; 242 сверху — часть, не ширина: {d["outcome"]} {d["d"]}', d['outcome'] == 'accepted' and d['d'] == 160)
check('допуск ширины: 296 при карточке 291 (Δ5 ≤ 5,82) — принято',
      DD.decide(edit(KING, l0={'value': 296}), 291, 82, 'угловой')['outcome'] == 'accepted')
check('допуск ширины: 297 при карточке 291 — width-mismatch',
      DD.decide(edit(KING, l0={'value': 297}), 291, 82, 'угловой')['outcome'] == 'width-mismatch')
check('малая ширина — допуск 3 см: 170 при 167 принято, 171 — нет',
      DD.decide(edit(TWO, l0={'value': 170}), 167, 88, 'прямой')['outcome'] == 'accepted'
      and DD.decide(edit(TWO, l0={'value': 171}), 167, 88, 'прямой')['outcome'] == 'width-mismatch')
check('чертёж другого товара (карточка 300) — width-mismatch', DD.decide(XL, 300, 96, 'угловой')['outcome'] == 'width-mismatch')
check('242 сверху помечена общей — две общие ширины → multi-variant',
      DD.decide(edit(KING, l3={'type': 'overall'}), 291, 82, 'угловой')['outcome'] == 'multi-variant')
check('совпала бы только 242 (общей 291 на чертеже нет) — width-mismatch, не принятие',
      DD.decide(edit(KING, l0=None, l3={'type': 'overall'}), 291, 82, 'угловой')['outcome'] == 'width-mismatch')
check('нет общей ширины — no-overall-width', DD.decide(edit(KING, l0=None), 291, 82, 'угловой')['outcome'] == 'no-overall-width')
check('нет общей глубины (только сиденье) — no-overall-depth',
      DD.decide(edit(KING, l4=None), 291, 82, 'угловой')['outcome'] == 'no-overall-depth')
check('несколько вариантов на картинке — multi-variant',
      DD.decide(edit(KING, configurations=2), 291, 82, 'угловой')['outcome'] == 'multi-variant')
check('две разные общие глубины (сверху 160, сбоку 150) — multi-variant',
      DD.decide(edit(KING, extra=[line('side', 'horizontal', 'overall', 150)]), 291, 82, 'угловой')['outcome'] == 'multi-variant')
check('одна глубина на двух видах (160 и 160,4) — принято',
      DD.decide(edit(KING, extra=[line('side', 'horizontal', 'overall', 160.4)]), 291, 82, 'угловой')['outcome'] == 'accepted')
check('единица у общей линии не подписана — no-unit', DD.decide(edit(KING, l4={'unit': None}), 291, 82, 'угловой')['outcome'] == 'no-unit')
mm = edit(KING, l0={'value': 2910, 'unit': 'мм'}, l4={'value': 1600, 'unit': 'мм'})
d = DD.decide(mm, 291, 82, 'угловой')
check(f'миллиметры переводятся: 2910/1600 мм → d=160: {d["d"]}', d['outcome'] == 'accepted' and d['d'] == 160)
check('глубина не больше сиденья — implausible',
      DD.decide(edit(KING, l4={'value': 65}, l5={'value': 70}), 291, 82, 'угловой')['outcome'] == 'implausible')
check('часть глубже общей — implausible',
      DD.decide(edit(KING, extra=[line('top', 'vertical', 'subdimension', 170)]), 291, 82, 'угловой')['outcome'] == 'implausible')
check('прямой с глубиной 160 — implausible (70–150)', DD.decide(edit(TWO, l4={'value': 160}), 167, 88, 'прямой')['outcome'] == 'implausible')
check('угловой с глубиной 110 — implausible (120–260)', DD.decide(edit(KING, l4={'value': 110}), 291, 82, 'угловой')['outcome'] == 'implausible')
check('П с глубиной 300 — принято (120–400)', DD.decide(edit(KING, l4={'value': 300}), 291, 82, 'П')['outcome'] == 'accepted')
check('высота чертежа не та (карточка 100) — height-mismatch', DD.decide(KING, 291, 100, 'угловой')['outcome'] == 'height-mismatch')
check('часть модульной серии — не решаем (skipped-part)', DD.decide(KING, 291, 82, 'модуль-часть')['outcome'] == 'skipped-part')

# типы и сторона
cases = [(('Угловой диван Кинг Шенилл', 'Угловой'), 'угловой'), (('Диван Босс Мини', 'Прямой'), 'прямой'),
         (('П-образный диван Кинг Модуль', 'П-образный'), 'П'), (('Модульный п-образный диван Ричмонд', 'Модульный'), 'П'),
         (('Модульный угловой диван Ричмонд Модуль', 'Модульный'), 'модульный-угловой'),
         (('Диван Босс Софт Модуль', 'Модуль'), 'модульный'), (('Ричмонд Модуль подлокотник 2 шт.', 'Модуль'), 'модуль-часть'),
         (('Кресло Кинг Модуль', 'Модуль'), 'модуль-часть'), (('Тахта Ирис', 'Прямой'), 'прямой'), (('Диван Викс', ''), 'прямой')]
badk = [(a, DD.kind_of(*a), w) for a, w in cases if DD.kind_of(*a) != w]
check(f'тип по «Конфигурация» и имени ({len(cases)} случаев){": " + str(badk) if badk else ""}', not badk)
check('сторона — только из текста: «правый» → right, без слова → None',
      DD.side_of('Диван угловой правый Кинг Твин') == 'right' and DD.side_of('Угловой диван Сеул левый') == 'left'
      and DD.side_of('Угловой диван Кинг') is None)
check('адрес чертежа — от сайта своего магазина',
      DD.drawing_url(114082, '/upload/a.jpg') == 'https://divanboss.ru/upload/a.jpg'
      and DD.drawing_url(114667, '/upload/a.jpg') == 'https://mnogomebeli.com/upload/a.jpg' and DD.drawing_url(114667, '') is None)

# 3) кэш
k = DD.cache_key('ab' * 32)
check('ключ кэша = sha + модель + промпт + схема', k == f'{"ab" * 32}|{DD.MODEL}|{DD.PROMPT_VER}|s{DD.SCHEMA_VER}')
check('другая модель / версия промпта / схемы — другой ключ',
      len({k, DD.cache_key('ab' * 32, model='x/y'), DD.cache_key('ab' * 32, prompt_ver='v9'), DD.cache_key('ab' * 32, schema_ver=9)}) == 4)

# 4) прогон с подменой сети
IMG = {'u1': b'drawing-1', 'u2': b'drawing-2', 'u3': b'drawing-3'}
ITEMS = [
    {'mid': 114667, 'eid': 'a', 'name': 'Угловой диван Кинг', 'kind': 'угловой', 'side': None, 'w': 291.0, 'h': 82.0, 'url': 'u1'},
    {'mid': 114082, 'eid': 'b', 'name': 'Угловой диван Кинг', 'kind': 'угловой', 'side': None, 'w': 291.0, 'h': 82.0, 'url': 'u1'},
    {'mid': 114667, 'eid': 'c', 'name': 'Диван Босс двухместный', 'kind': 'прямой', 'side': None, 'w': 167.0, 'h': 88.0, 'url': 'u2'},
    {'mid': 114667, 'eid': 'd', 'name': 'Угловой диван Х', 'kind': 'угловой', 'side': None, 'w': 300.0, 'h': 90.0, 'url': 'u404'},
    {'mid': 114667, 'eid': 'e', 'name': 'Диван без чертежа', 'kind': 'прямой', 'side': None, 'w': 200.0, 'h': 90.0, 'url': None},
    {'mid': 114667, 'eid': 'f', 'name': 'Ричмонд Модуль оттоманка', 'kind': 'модуль-часть', 'side': None, 'w': 100.0, 'h': 82.0, 'url': 'u3'},
]
ANS = {b'drawing-1': raw('king-corner.json'), b'drawing-2': raw('boss-2seat.json')}
calls, saves = [], []


def fake_fetch(u):
    if u not in IMG:
        raise urllib.error.HTTPError(u, 404, 'Not Found', {}, io.BytesIO(b''))
    return IMG[u]


def fake_ask(b):
    calls.append(b)
    return {'raw': ANS[b], 'usage': None}


cache: dict = {}
res, cnt = DD.scan(ITEMS, cache, fetch_fn=fake_fetch, ask_fn=fake_ask, save_fn=saves.append)
check(f'сухо: вызовов модели 0, кэш не пишется, все с чертежом — pending: {dict(cnt)}',
      not calls and not saves and cnt['calls'] == 0 and cnt['pending'] == 3 and cnt['unique'] == 2 and cnt['miss'] == 2)
check('сухо: без чертежа — no-drawing, 404 — download-fail, часть модуля — skipped-part',
      cnt['no-drawing'] == 1 and cnt['download-fail'] == 1 and cnt['skipped-part'] == 1)
res, cnt = DD.scan(ITEMS, cache, paid=True, max_calls=1, fetch_fn=fake_fetch, ask_fn=fake_ask, save_fn=saves.append)
check(f'платно с потолком 1: ровно один вызов и одна запись кэша: вызовов {len(calls)}', len(calls) == 1 and len(saves) == 1)
check('одно прочтение чертежа — одинаковое решение обоим SKU с ним (a, b)', res[0]['outcome'] == res[1]['outcome'])
res, cnt = DD.scan(ITEMS, cache, paid=True, max_calls=5, fetch_fn=fake_fetch, ask_fn=fake_ask, save_fn=saves.append)
acc = {r['eid']: r['d'] for r in res if r['outcome'] == 'accepted'}
check(f'второй прогон: кэш-попадание не платит повторно (вызовов всего 2), принято a/b=160, c=112: {acc}',
      len(calls) == 2 and acc == {'a': 160, 'b': 160, 'c': 112} and cnt['hit'] == 1)
check('исходы SKU сходятся с eligible', sum(cnt[o] for o in DD.OUTCOMES) == cnt['eligible'] == len(ITEMS))
rd = next(iter(cache['reads'].values()))
check('в кэше прочтения — модель, версии промпта/схемы, sha', {'model', 'prompt_ver', 'prompt_sha', 'schema_ver', 'sha'} <= set(rd))


def broken_ask(b):
    calls.append(b)
    return {'raw': 'не JSON', 'usage': None}


c2: dict = {}
res, cnt = DD.scan(ITEMS[:3], c2, paid=True, max_calls=5, fetch_fn=fake_fetch, ask_fn=broken_ask, save_fn=saves.append)
check('ответ не по схеме — parse-fail, в кэш не пишется, глубины нет',
      cnt['parse-fail'] == 3 and not c2['reads'] and not any(r['d'] for r in res))


def dead_ask(b):
    raise RuntimeError('шлюз недоступен')


res, cnt = DD.scan(ITEMS[:3], {}, paid=True, max_calls=5, fetch_fn=fake_fetch, ask_fn=dead_ask, save_fn=saves.append)
check('сбой вызова — model-fail, не отказ и не глубина', cnt['model-fail'] == 3 and not any(r['d'] for r in res))
check('платно без --max-calls — стоп до любых действий', DD.main(['--paid']) == 2)

# 5) шлюз без прямого OpenAI
seen = []
_env, _open = llm_gateway._env, llm_gateway.urllib.request.urlopen
llm_gateway._env = lambda name: 'k-' + name


def fake_open(req, timeout=0):
    seen.append(req.full_url)
    raise urllib.error.HTTPError(req.full_url, 401, 'no', {}, io.BytesIO(b''))


llm_gateway.urllib.request.urlopen = fake_open
try:
    for fb in (False, True):
        try:
            llm_gateway.chat('google/x', [], tries=1, direct_fallback=fb)
        except Exception:  # noqa: BLE001 — здесь важен лишь список адресов
            pass
finally:
    llm_gateway._env, llm_gateway.urllib.request.urlopen = _env, _open
check(f'direct_fallback=False — только шлюз; по умолчанию фолбэк прежний: {seen}',
      seen == [llm_gateway.GATEWAY_URL, llm_gateway.GATEWAY_URL, llm_gateway.OPENAI_URL])

print(f'test_drawing_dims: ошибок {fails}')
sys.exit(1 if fails else 0)
