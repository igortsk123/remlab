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
import collections as C
import io
import json
import os
import sys
import urllib.error
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_drawing_dims')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

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
check('ответ не по схеме — parse-fail, в прочтения не пишется, глубины нет',
      cnt['parse-fail'] == 3 and not c2['reads'] and not any(r['d'] for r in res))
check('сбой разбора — в журнал failed с сырым ответом (цена и разбор), следующий прогон спросит снова',
      len(c2['failed']) == 2 and all(v[0]['raw'] == 'не JSON' for v in c2['failed'].values()))
res, cnt = DD.scan(ITEMS[:3], c2, paid=True, max_calls=5, fetch_fn=fake_fetch, ask_fn=fake_ask, save_fn=saves.append)
check('удачное повторное прочтение пишется, журнал неудачной попытки остаётся (её цена в учёте)',
      len(c2['reads']) == 2 and all(len(v) == 1 for v in c2['failed'].values()) and cnt['accepted'] == 3)


def dead_ask(b):
    raise RuntimeError('шлюз недоступен')


res, cnt = DD.scan(ITEMS[:3], {}, paid=True, max_calls=5, fetch_fn=fake_fetch, ask_fn=dead_ask, save_fn=saves.append)
check('сбой вызова — model-fail, не отказ и не глубина', cnt['model-fail'] == 3 and not any(r['d'] for r in res))
check('платно без --max-calls — стоп до любых действий', DD.main(['--paid']) == 2)
IMG5 = {f'v{i}': f'drawing-v{i}'.encode() for i in range(5)}
ITEMS5 = [{'mid': 114667, 'eid': f'v{i}', 'name': 'Диван Х', 'kind': 'прямой', 'side': None, 'w': 167.0, 'h': 88.0, 'url': f'v{i}'}
          for i in range(5)]
dead = []
res, cnt = DD.scan(ITEMS5, {}, paid=True, max_calls=5, fetch_fn=IMG5.__getitem__,
                   ask_fn=lambda b: dead.append(b) or (_ for _ in ()).throw(RuntimeError('502')), save_fn=saves.append)
check(f'{DD.STOP_STREAK} сбоя подряд — стоп: вызовов {len(dead)} из 5, остальные pending',
      len(dead) == DD.STOP_STREAK and cnt['stopped'] == 1 and cnt['pending'] == 5 - DD.STOP_STREAK)

# подложка прозрачного PNG (лист Т1 № 12 и 40: на чёрном линии не видны)
from PIL import Image  # noqa: E402
png = Image.new('RGBA', (40, 20), (0, 0, 0, 0))
for x in range(5, 35):
    png.putpixel((x, 10), (0, 0, 0, 255))          # чёрная размерная линия на прозрачном (скрытый цвет — чёрный)
buf = io.BytesIO(); png.save(buf, 'PNG')
out = Image.open(io.BytesIO(DD.prep_image(buf.getvalue())))
check(f'прозрачный PNG → JPEG на белом: фон {out.getpixel((1, 1))}, линия {out.getpixel((20, 10))}',
      out.format == 'JPEG' and min(out.getpixel((1, 1))) > 240 and max(out.getpixel((20, 10))) < 80)
buf = io.BytesIO(); Image.new('RGB', (3000, 1000), (255, 255, 255)).save(buf, 'JPEG')
check('крупный JPEG ужимается до 2048 по длинной стороне', Image.open(io.BytesIO(DD.prep_image(buf.getvalue()))).size == (2048, 683))

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

def _raises(f) -> bool:
    try:
        f()
    except DD.CacheError:
        return True
    return False


# 6) Т6 — подмешивание в загрузчик (load3.assign → overlay), только кэш, без сети
SHA_K = DD.hashlib.sha256(b'drawing-1').hexdigest()
URL_K = 'https://mnogomebeli.com/upload/king.jpg'
CK = {'reads': {DD.cache_key(SHA_K): {**KING, 'sha': SHA_K, 'model': DD.MODEL, 'prompt_ver': DD.PROMPT_VER, 'schema_ver': DD.SCHEMA_VER}},
      'urls': {URL_K: {'sha': SHA_K, 'at': '2026-11-04'}}}
PK = {DD.PARAM: '/upload/king.jpg', 'Конфигурация': 'Угловой'}
DIMS = {'w': 291.0, 'd': None, 'h': 82.0, 'len': None, 'dia': None}
dm, ev, src = DD.overlay(114667, 'Угловой диван Кинг', PK, 'диван', DIMS, {'w': {'source': 'param'}}, 'param:2', CK, today='2026-11-05')
check(f'sha сверен и прочтение принято → d=160, evidence drawing, источник +drawing:1: {dm["d"]} {src}',
      dm['d'] == 160 and ev['d']['source'] == 'drawing' and ev['d']['sha'] == SHA_K and ev['d']['view'] == ['top']
      and ev['w'] == {'source': 'param'} and src == 'param:2 drawing:1' and DIMS['d'] is None)
check('в evidence — модель, версии промпта/схемы/правил, ширины и Δ',
      {'model', 'prompt_ver', 'schema_ver', 'policy_ver', 'w_read', 'w_card', 'dw', 'dw_pct', 'url', 'unit'} <= set(ev['d']))
same = lambda r: r == (DIMS, None, 'x')  # noqa: E731
CKX = {**CK, 'urls': {URL_K: {'sha': 'f' * 64, 'at': '2026-11-04'}}}
check('по адресу сегодня другой sha (чертёж сменили) — ничего', same(DD.overlay(114667, 'Угловой диван Кинг', PK, 'диван', DIMS, None, 'x', CKX, today='2026-11-05')))
DD.STATS.clear()
check(f'Б: сверка старше {DD.INDEX_MAX_AGE_DAYS} дней — d держим (последнее подтверждённое), счётчик «сверка старая»',
      DD.overlay(114667, 'Угловой диван Кинг', PK, 'диван', DIMS, None, 'x', CK, today='2026-11-30')[0]['d'] == 160
      and DD.STATS['old_index'] == 1)
check('адрес и SKU ни разу не сверялись (новинка) — ничего',
      same(DD.overlay(114667, 'Угловой диван Кинг', {**PK, DD.PARAM: '/upload/new.jpg'}, 'диван', DIMS, None, 'x', CK, eid='zz')))
CKS = {**CK, 'sku': {'114667:a1': {'url': URL_K, 'sha': SHA_K, 'at': '2026-11-03'}}}
dmS, evS, _ = DD.overlay(114667, 'Угловой диван Кинг', {**PK, DD.PARAM: '/upload/new.jpg'}, 'диван', DIMS, None, 'x', CKS,
                         today='2026-11-05', eid='a1')
check('Б: адрес в фиде сменился, новый ещё не сверен — держим последний сверенный sha SKU',
      dmS['d'] == 160 and evS['d']['basis'] == 'sku_last' and evS['d']['url'] == URL_K)
CKS2 = {**CKS, 'urls': {**CK['urls'], 'https://mnogomebeli.com/upload/new.jpg': {'sha': 'e' * 64, 'at': '2026-11-05'}}}
check('Б: новый адрес сверен на непрочитанный sha — свежее доказательство, d снимается',
      same(DD.overlay(114667, 'Угловой диван Кинг', {**PK, DD.PARAM: '/upload/new.jpg'}, 'диван', DIMS, None, 'x', CKS2,
                      today='2026-11-05', eid='a1')))
dd = {**DIMS, 'd': 150.0}
check('глубина из карточки есть — карточка главнее, кэш не трогает',
      DD.overlay(114667, 'Угловой диван Кинг', PK, 'диван', dd, None, 'x', CK, today='2026-11-05') == (dd, None, 'x'))
check('другой магазин / не диван — ничего',
      same(DD.overlay(5794, 'Угловой диван Кинг', PK, 'диван', DIMS, None, 'x', CK, today='2026-11-05'))
      and same(DD.overlay(114667, 'Кресло Кинг', PK, 'кресло', DIMS, None, 'x', CK, today='2026-11-05')))
check('ширина карточки не та (чертёж чужой) — decide отказал, ничего',
      DD.overlay(114667, 'Угловой диван Кинг', PK, 'диван', {**DIMS, 'w': 300.0}, None, 'x', CK, today='2026-11-05')[0]['d'] is None)
check('часть модуля — ничего', same(DD.overlay(114667, 'Кинг Модуль оттоманка', PK, 'диван', DIMS, None, 'x', CK, today='2026-11-05')))

# cache-only: сверка адресов пишется, вызовов нет
calls.clear(); saves.clear()
c3 = {'reads': dict(cache['reads'])}
res, cnt = DD.scan(ITEMS, c3, index=True, today='2026-11-04', fetch_fn=fake_fetch, ask_fn=fake_ask, save_fn=saves.append)
check(f'только кэш: 0 вызовов, адрес → sha записан для скачанных; 404 и части модулей — без записи: {sorted(c3["urls"])}',
      not calls and sorted(c3['urls']) == ['u1', 'u2'] and c3['urls']['u1']['at'] == '2026-11-04' and len(saves) == 1)
check('только кэш: прочтения из кэша решают (hit), новых чертежей нет — pending не платится', cnt['hit'] == 2 and cnt['calls'] == 0)
W = C.Counter({'accepted': 1145, 'download-fail': 42, 'skipped-part': 270, 'no-drawing': 77, 'pending': 0})
check('cache-only: 42 мёртвых ссылки из 1 187 — не WARN (фон), сводка строкой',
      [x for x in DD.warn_lines(W, True) if x.startswith('WARN')] == [] and 'мёртвых ссылок 42' in DD.warn_lines(W, True)[0])
check('cache-only: обвал ссылок (> 10 %) — WARN', any(x.startswith('WARN:drawing_dims_dead_links')
      for x in DD.warn_lines(C.Counter({'accepted': 100, 'download-fail': 900}), True)))
check('платный/сухой прогон: любой сбой — WARN', DD.warn_lines(W, False) == ['WARN:drawing_dims_failed: 42'])
check('--paid и --cache-only вместе — стоп', DD.main(['--paid', '--max-calls', '1', '--cache-only']) == 2)
check('cache-only: SKU → последний сверенный (адрес, sha) и время сверки шага записаны',
      c3['sku']['114667:a']['sha'] == DD.hashlib.sha256(b'drawing-1').hexdigest() and '114667:d' not in c3['sku']
      and c3['scan_at'] == '2026-11-04')

# кэш: битый — ошибка, запись атомарная с копией прежней версии
import tempfile  # noqa: E402
_cache0 = DD.CACHE
with tempfile.TemporaryDirectory() as td:
    DD.CACHE = os.path.join(td, 'dd.json')
    check('нет файла: шагу — пустой кэш, загрузчику — ошибка', DD.load_cache() == {} and _raises(lambda: DD.load_cache(required=True)))
    open(DD.CACHE, 'w').write('{"reads": {')
    check('битый JSON — CacheError, не {}', _raises(lambda: DD.load_cache()))
    open(DD.CACHE, 'w').write('[1]')
    check('не объект — CacheError', _raises(lambda: DD.load_cache()))
    open(DD.CACHE, 'w').write('{"reads": {"k": 1}}')
    DD._BACKED_UP.discard(DD.CACHE)
    DD.save_cache({'reads': {'k': 2}})
    DD.save_cache({'reads': {'k': 3}})
    baks = sorted(f for f in os.listdir(td) if '.bak-' in f)
    check(f'запись: новая версия на месте, одна копия прежней на процесс, временных файлов нет: {sorted(os.listdir(td))}',
          DD.load_cache() == {'reads': {'k': 3}} and len(baks) == 1
          and json.load(open(os.path.join(td, baks[0]))) == {'reads': {'k': 1}} and not [f for f in os.listdir(td) if '.tmp' in f])

    # загрузчик: проверка кэша до записи в БД и доля подмешанных
    def pre(c):
        json.dump(c, open(DD.CACHE, 'w'))
        DD._LOADER_CACHE = None
        return DD.loader_preflight()
    check('preflight: годный кэш — можно', pre({**CK, 'scan_at': '2026-11-04'}) is None)
    check('preflight: нет сверки шага — СТОП', 'сверки' in (pre({'reads': CK['reads']}) or ''))
    check('preflight: прочтения другой модели — СТОП',
          'прочтений' in (pre({**CK, 'scan_at': '2026-11-04', 'reads': {SHA_K + '|other/model|v0|s1': {}}}) or ''))
    os.rename(DD.CACHE, DD.CACHE + '.x')
    DD._LOADER_CACHE = None
    check('preflight: кэша нет — СТОП с путём', DD.CACHE in (DD.loader_preflight() or ''))
    json.dump({**CK, 'scan_at': '2026-11-01'}, open(DD.CACHE, 'w'))
    DD._LOADER_CACHE = None
    DD.STATS.clear(); DD.STATS.update(candidates=1294, applied=1148)
    lines, why = DD.loader_gate(today='2026-11-04')
    check(f'gate: 1 148 из 1 294 — можно; сверка 3 дня назад — WARN: {lines[-1][:60]}',
          why is None and lines[-1].startswith('WARN:drawing_index_old'))
    DD.STATS.clear(); DD.STATS.update(candidates=1294, applied=300)
    check('gate: доля ниже порога — СТОП', DD.loader_gate(today='2026-11-01')[1] is not None)
    DD.STATS.clear(); DD.STATS.update(candidates=3, applied=0)
    check('gate: кандидатов мало (фикстура, карантин фида) — доля не проверяется', DD.loader_gate(today='2026-11-01')[1] is None)
    DD.STATS.clear()

    # load3.main: битый кэш — СТОП ДО первой записи в БД
    os.environ.setdefault('SCOUT_PRIORS_PATH', os.path.join(SCOUT, 'tests', 'fixtures', 'unit-priors-mini.json'))
    import load3  # noqa: E402 — лёгкий импорт: функции, без прогона
    open(DD.CACHE, 'w').write('{битый')
    DD._LOADER_CACHE = None
    sql_calls = []
    _sql0, load3.sql = load3.sql, (lambda q, inp=None: sql_calls.append(q))
    _sr0, load3.sql_rows = load3.sql_rows, (lambda q: sql_calls.append(q) or [])
    rc = load3.main()
    load3.sql, load3.sql_rows = _sql0, _sr0
    check(f'load3.main: битый кэш чертежей — rc 2, в БД ни одного запроса: rc={rc}, запросов {len(sql_calls)}', rc == 2 and not sql_calls)
DD.CACHE = _cache0

# исключение чертежа из эталонов приоров — одна константа
import re  # noqa: E402
import dimless  # noqa: E402
check('dimless.NOT_REFERENCE_RX: чертёж и выведенное — не эталон, параметр фида — эталон',
      all(re.match(dimless.NOT_REFERENCE_RX, x) for x in ('drawing', 'role_prior', 'mesh_ratio', 'shape_rule:sphere'))
      and not re.match(dimless.NOT_REFERENCE_RX, 'param'))
srcs = {f: open(os.path.join(SCOUT, f), encoding='utf-8').read() for f in ('dim_prior.py', 'mesh_dims.py', 'dimless.py', 'load3.py')}
old_lit = [f for f, t in srcs.items() if "^(role_prior|mesh_ratio|shape_rule)'" in t]
check(f'старого списка без чертежа нигде нет: {old_lit}', not old_lit)
check('dim_prior (калибровка) и mesh_dims (эталоны меша) берут общую константу',
      "!~ '{DL.NOT_REFERENCE_RX}'" in srcs['dim_prior.py'] and "{DL.NOT_REFERENCE_RX}" in srcs['mesh_dims.py'])

# load3: подключение после resolve_dims, версия хешей
DD._LOADER_CACHE = {**CK, 'urls': {URL_K: {'sha': SHA_K, 'at': DD._today()}}}
prm = {'Ширина': '291', 'Высота': '82', DD.PARAM: '/upload/king.jpg', 'Конфигурация': 'Угловой'}
dims0, ev0, src0 = load3.resolve_dims(114667, 'Угловой диван Кинг', prm, 'диван')
dims1, ev1, src1 = load3._drawing_overlay({'mid': 114667, 'name': 'Угловой диван Кинг', 'params': prm}, 'диван', dims0, ev0, src0)
check(f'load3: резолвер даёт 291×—×82, оверлей → d 160 с evidence drawing: {dims0["w"]}/{dims0["d"]} → {dims1["d"]}',
      dims0['w'] == 291 and dims0['d'] is None and dims1['d'] == 160 and ev1['d']['source'] == 'drawing')
DD._LOADER_CACHE = {}
check('load3: пустой кэш — размеры как из карточки',
      load3._drawing_overlay({'mid': 114667, 'name': 'Угловой диван Кинг', 'params': prm}, 'диван', dims0, ev0, src0) == (dims0, ev0, src0))
src_l = srcs['load3.py']
check('load3.assign: оверлей сразу после resolve_dims', re.search(r"resolve_dims\(o\['mid'\].*?\n(?:\s*#.*\n)*\s*dims, ev, dsrc = _drawing_overlay", src_l) is not None)
i_main = src_l.index('def main() -> int:')
check('load3.main: проверка кэша до DDL, доля подмешанных — до первого чтения/записи товаров',
      i_main < src_l.index('loader_preflight()') < src_l.index('    sql(DDL)', i_main)
      and src_l.index('loader_gate()') < src_l.index('baseline = {int(r[0])', i_main))
check('load3: ошибку оверлея не глотает (try/except вокруг overlay нет)', '_DRAWING_WARNED' not in src_l)
load3.DRAWING_OVERLAY = False
DD._LOADER_CACHE = None
check('DRAWING_OVERLAY=0 — оверлея нет вовсе, кэш не читается',
      load3._drawing_overlay({'mid': 114667, 'name': 'Угловой диван Кинг', 'params': prm}, 'диван', dims0, ev0, src0) == (dims0, ev0, src0)
      and DD._LOADER_CACHE is None)
load3.DRAWING_OVERLAY = True
import bank_ready  # noqa: E402
check('bank_ready: глубина с чертежа — доказательство собранных размеров трансформера',
      "p.dims_evidence->'d'->>'source' = 'drawing'" in bank_ready.PROVEN_SQL)
check(f'HASH_VERSION поднят до 9 (один раз — baseline без stale): {load3.HASH_VERSION}', load3.HASH_VERSION == 9)
import dim_resolver  # noqa: E402
check('правила резолвера не менялись — отпечаток прежний', dim_resolver.rules_fingerprint() == load3.RULES_FINGERPRINT)
rd_src = open(os.path.join(SCOUT, 'refresh_daily.sh'), encoding='utf-8').read()
i_dd, i_l3 = rd_src.find('step drawing_dims "$PY" drawing_dims.py --cache-only'), rd_src.find('step load3 "$PY" load3.py')
check('ночной шаг: drawing_dims --cache-only до load3, платного дочитывания в кроне нет',
      0 < i_dd < i_l3 and 'drawing_dims.py --paid' not in rd_src)

# снимок до/после (drawing_snapshot.diff): что поменялось по SKU и в счётчиках
import drawing_snapshot as SN  # noqa: E402
row = {'sku': '114667:a', 'w': 291, 'd': None, 'h': 82, 'dims_source': 'prior:2', 'geometry_hash': 'g1', 'mesh_required': False,
       'mesh_family': 'f1', 'rep': '114667:a', 'enrichment_status': 'current'}
sa = {'skus': [row], 'totals': {'d_drawing': 0, 'mesh_required': 10}, 'candidates': {'total': 5, 'shops_keys': []}}
sb = {'skus': [{**row, 'd': 160, 'dims_source': 'prior:2 drawing:1', 'geometry_hash': 'g2', 'mesh_required': True}],
      'totals': {'d_drawing': 1, 'mesh_required': 11}, 'candidates': {'total': 6, 'shops_keys': ['114667:a']}}
dfs = SN.diff(sa, sb)
check(f'снимок: d пусто→есть, хеш, mesh_required, счётчики и кандидаты — в сводке: {dfs["skus"]}',
      dfs['skus'] == {'d: пусто → есть': 1, 'dims_source изменился': 1, 'geometry_hash изменился': 1, 'mesh_required изменился': 1}
      and dfs['enrichment_status'] == {} and dfs['totals'] == {'d_drawing': [0, 1], 'mesh_required': [10, 11]}
      and dfs['candidates_shops'] == {'+': 1, '-': 0})

print(f'test_drawing_dims: ошибок {fails}')
sys.exit(1 if fails else 0)
