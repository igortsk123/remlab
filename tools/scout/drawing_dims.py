#!/usr/bin/env python3
"""ГЛУБИНА ДИВАНА С ЧЕРТЕЖА (план conv-15-drawing-depth). У mnogomebeli.com (114667) и divanboss.ru (114082) глубины нет
текстом — только картинка «Изображение с размерами» (вид спереди и сверху с подписанными размерами). Нейросеть-зритель
(через шлюз Vercel, как `rug_kids.py`) лишь ПЕРЕЧИСЛЯЕТ размерные линии: вид, ось, тип, число, единица. Какая из них — общая
глубина, решает код (`decide`): общая ширина чертежа должна совпасть с карточкой `|Δ| ≤ max(3 см, 2 %)`, глубина — общий
габарит поперёк ширины (вертикаль вида сверху / горизонталь вида сбоку), затем гейты единицы, вариантов и правдоподобия
по типу дивана. Уверенность модели ничего не разрешает: её в ответе нет вовсе.

Ответ модели кэшируется по sha256 байтов чертежа + модель + версия промпта и схемы (`~/scout-scenes/drawing-dims.json`):
один чертёж висит на десятке SKU разных тканей — платим за уникальную картинку, не за товар. Решение по SKU не кэшируется,
а пересчитывается из прочтения и карточки каждый раз. Ошибка скачивания/вызова/разбора — «не решено», не отказ и не
глубина; счётчики печатаются громко. В базу и в банк сетов этот шаг НЕ пишет (подмешивание в `load3` — шаг 6 плана).

    ~/venvs/scout/bin/python drawing_dims.py [--out f.jsonl]                    # сухо: скачать чертежи, счётчики, без вызовов
    ~/venvs/scout/bin/python drawing_dims.py --cache-only                        # ночью до load3: сверить адрес → sha, без вызовов
    ~/venvs/scout/bin/python drawing_dims.py --paid --max-calls 20 [--only sha,…] # платно: прочитать не более N новых чертежей

Загрузчик (`load3.assign` → `overlay`) подмешивает принятую d из кэша без сети: sha чертежа по адресу из фида (или,
пока новый адрес не сверен, последний сверенный sha этого SKU) прочитан и прошёл `decide`. Карточка главнее. Старая сверка
d НЕ снимает (держим последнее подтверждённое — вариант Б, T-20261104-06/4): снимает только свежее доказательство — адрес
сверен на непрочитанный sha или `decide` отказал. Возраст сверки — громкий WARN загрузчика. Включён оверлей — `load3` до
записи в БД проверяет кэш (`loader_preflight`) и долю подмешанных (`loader_gate`), иначе СТОП; `DRAWING_OVERLAY=0` — выключить.
"""
import base64
import collections
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser(os.environ.get('DRAWING_DIMS_CACHE', '~/scout-scenes/drawing-dims.json'))
MODEL = os.environ.get('DRAWING_DIMS_MODEL', 'google/gemini-3.8-flash')
PROMPT_VER = 'drawing-dims-v1'
SCHEMA_VER = 1
PARAM = 'Изображение с размерами'
SHOPS = {114667: 'mnogomebeli.com', 114082: 'divanboss.ru'}
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-At', '-F', '\x1f', '-q']
MAX_CALLS_CAP = 400                     # потолок одного платного прогона, даже если попросили больше (уникальных чертежей ~106)
INDEX_MAX_AGE_DAYS = 7                  # адрес → sha старше — в счётчике загрузчика «сверка старая» (d держим — вариант Б)
SCAN_WARN_DAYS = 1                      # последняя сверка шага старше — WARN загрузчика: ночной шаг drawing_dims не работает
# доля подмешанных среди кандидатов (диван двух магазинов без d в карточке, с чертежом, не часть модуля) — ниже порога load3
# стоит ДО записи в БД: кэш не тот, ключи прочтений не совпали (смена модели/промпта), сверка пустая. 04.11: 1 148 из 1 294
# = 0,887; порог — 80 % от этого. Меньше GATE_MIN_CANDIDATES кандидатов (фикстуры, карантин фида) — доля не проверяется
DRAWING_MIN_SHARE = 0.70
GATE_MIN_CANDIDATES = 100
POLICY_VER = 1                          # версия правил выбора d (`decide`) — в evidence; смена = контролируемая миграция
STOP_STREAK = 3                         # столько сбоев модели/разбора подряд — стоп прогона (шлюз лёг или ответ не по схеме)

VIEWS, AXES = ('front', 'top', 'side'), ('horizontal', 'vertical')
TYPES = ('overall', 'subdimension', 'seat', 'sleeping')
UNITS = {'см': 1.0, 'cm': 1.0, 'мм': 0.1, 'mm': 0.1}
# ось чертежа → ось товара: спереди и сверху горизонталь — ширина; сверху вертикаль и сбоку горизонталь — глубина
SEM = {('front', 'horizontal'): 'w', ('front', 'vertical'): 'h', ('top', 'horizontal'): 'w', ('top', 'vertical'): 'd',
       ('side', 'horizontal'): 'd', ('side', 'vertical'): 'h'}
# правдоподобная общая глубина по типу (Codex 04.11). Модульный без «углов»/«П» в имени — как прямой: собранный прямой
# модульный 240 см глубиной 100 иначе ушёл бы в отказ как «неправдоподобный», а угловой 160 — как прямой — тоже в отказ
RANGE = {'прямой': (70, 150), 'угловой': (120, 260), 'П': (120, 400), 'модульный-угловой': (120, 400), 'модульный': (70, 150)}
# исходы по SKU: ровно один на товар, сумма = eligible
OUTCOMES = ('accepted', 'no-overall-width', 'width-mismatch', 'height-mismatch', 'no-overall-depth', 'multi-variant',
            'implausible', 'no-unit', 'no-drawing', 'download-fail', 'model-fail', 'parse-fail', 'pending', 'skipped-part')

PROMPT = (
    'Это чертёж дивана с размерами из интернет-магазина. Перечисли ВСЕ размерные линии, у которых на картинке подписано число.\n'
    'Для каждой линии:\n'
    '- view — на каком виде линия: "front" (вид спереди), "top" (вид сверху), "side" (вид сбоку);\n'
    '- axis — направление самой линии на картинке: "horizontal" или "vertical";\n'
    '- type — "overall", если линия идёт от одного крайнего края ВСЕГО изделия до противоположного крайнего края на этом виде '
    '(общий габарит); "subdimension" — часть изделия (прямая часть, оттоманка, модуль, подлокотник, расстояние между '
    'подлокотниками); "seat" — глубина или высота сиденья; "sleeping" — спальное место;\n'
    '- value — число ровно как подписано, без пересчёта;\n'
    '- unit — единица, подписанная у числа: "см", "мм", "cm" или "mm"; если у числа единицы нет — null;\n'
    '- text — подпись как на картинке.\n'
    'configurations — сколько разных вариантов изделия (разных размеров или схем сборки) нарисовано на картинке; обычно 1.\n'
    'Не придумывай линий и чисел, которых нет на картинке. Если не уверен, к какому виду относится линия, не включай её.\n'
    'Верни только JSON без markdown: {"configurations": 1, "lines": [{"view": "front", "axis": "horizontal", '
    '"type": "overall", "value": 0, "unit": "см", "text": "0 см"}]}')
PROMPT_SHA = hashlib.sha1(PROMPT.encode()).hexdigest()[:12]


# --- чистые функции (тест без сети: tests/test_drawing_dims.py) ----------------------------------------------------------
def cache_key(sha: str, model: str = MODEL, prompt_ver: str = PROMPT_VER, schema_ver: int = SCHEMA_VER) -> str:
    return f'{sha}|{model}|{prompt_ver}|s{schema_ver}'


def kind_of(name: str | None, conf: str | None) -> str:
    """Тип по «Конфигурация» фида и имени. Часть модульной серии (подлокотник, оттоманка, спальный модуль, кресло-модуль —
    в имени нет «диван») — отдельный тип: её чертёж — габарит части, не дивана."""
    nm, c = (name or '').lower(), (conf or '').lower()
    if 'п-образ' in c or 'п-образ' in nm:
        return 'П'
    if c.startswith('модул') or 'модул' in nm:
        if 'диван' not in nm:
            return 'модуль-часть'
        return 'модульный-угловой' if 'углов' in nm else 'модульный'
    if c.startswith('углов') or 'углов' in nm:
        return 'угловой'
    return 'прямой'


def side_of(name: str | None) -> str | None:
    """Сторона угла — только из явного текста имени (`sofa_shape.side_fixed`); по картинке не определяем."""
    sys.path.insert(0, HERE)
    import sofa_shape  # noqa: E402 — лёгкий импорт
    if not sofa_shape.side_fixed(name):
        return None
    return 'left' if sofa_shape.corner_left(name) else 'right'


def parse(txt: str) -> dict:
    """Строго по схеме: лишний/недостающий ключ, не тот тип, неизвестный вид/ось/тип/единица — исключение («не решено»).
    Допускается лишь обёртка ```json … ``` целиком вокруг ответа."""
    s = (txt or '').strip()
    m = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', s, re.S)
    if m:
        s = m.group(1)
    d = json.loads(s)
    if not isinstance(d, dict) or set(d) != {'configurations', 'lines'}:
        raise ValueError(f'ответ не по форме: {s[:120]}')
    cf = d['configurations']
    if isinstance(cf, bool) or not isinstance(cf, int) or cf < 1 or not isinstance(d['lines'], list):
        raise ValueError(f'configurations/lines не по форме: {s[:120]}')
    lines = []
    for ln in d['lines']:
        if not isinstance(ln, dict) or set(ln) != {'view', 'axis', 'type', 'value', 'unit', 'text'}:
            raise ValueError(f'линия не по форме: {str(ln)[:120]}')
        v = ln['value']
        if (ln['view'] not in VIEWS or ln['axis'] not in AXES or ln['type'] not in TYPES
                or isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0
                or (ln['unit'] is not None and ln['unit'] not in UNITS) or not isinstance(ln['text'], str)):
            raise ValueError(f'линия не по схеме: {str(ln)[:120]}')
        lines.append({k: ln[k] for k in ('view', 'axis', 'type', 'value', 'unit', 'text')})
    return {'configurations': cf, 'lines': lines}


def tol(card: float) -> float:
    return max(3.0, 0.02 * card)


def clusters(vals: list[float], eps: float = 1.0) -> list[float]:
    """Разные значения с точностью до eps см (одна и та же цифра на двух видах — одно значение)."""
    out: list[list[float]] = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= eps:
            out[-1].append(v)
        else:
            out.append([v])
    return [round(sum(g) / len(g), 1) for g in out]


def decide(read: dict, card_w: float, card_h: float | None, kind: str) -> dict:
    """Прочтение модели + карточка → {'outcome', 'd', 'w_read', 'dw', 'detail'}. accepted только когда прошли ВСЕ гейты."""
    def res(outcome, detail='', **kw):
        return {'outcome': outcome, 'd': None, 'detail': detail, **kw}
    if kind not in RANGE:
        return res('skipped-part', kind)
    if read['configurations'] > 1:
        return res('multi-variant', f'вариантов на чертеже: {read["configurations"]}')
    by = collections.defaultdict(list)          # (ось товара, тип) → значения в см
    d_views = set()
    for ln in read['lines']:
        ax = SEM[(ln['view'], ln['axis'])]
        if ax == 'd' and ln['type'] == 'overall' and ln['unit'] is not None:
            d_views.add(ln['view'])
        if ln['unit'] is None:
            if ln['type'] == 'overall':
                return res('no-unit', f'{ln["view"]}/{ln["axis"]} {ln["value"]} без единицы')
            continue                            # подразмер без единицы в выбор не идёт и не мешает
        by[(ax, ln['type'])].append(ln['value'] * UNITS[ln['unit']])
    ws = clusters(by[('w', 'overall')])
    if not ws:
        return res('no-overall-width')
    if len(ws) > 1:
        return res('multi-variant', f'общих ширин несколько: {ws}')
    w_read, dw = ws[0], round(ws[0] - card_w, 1)
    info = {'w_read': w_read, 'dw': dw, 'dw_pct': round(100 * dw / card_w, 2)}
    if abs(dw) > tol(card_w):
        return res('width-mismatch', f'чертёж {w_read} ≠ карточка {card_w}', **info)
    hs = clusters(by[('h', 'overall')])
    if card_h and hs and not any(abs(h - card_h) <= tol(card_h) for h in hs):
        return res('height-mismatch', f'высота чертежа {hs} ≠ карточка {card_h}', **info)
    ds = clusters(by[('d', 'overall')])
    if not ds:
        return res('no-overall-depth', **info)
    if len(ds) > 1:
        return res('multi-variant', f'общих глубин несколько: {ds}', **info)
    d = ds[0]
    seat = by[('d', 'seat')]
    if any(s >= d for s in seat):
        return res('implausible', f'глубина {d} не больше сиденья {max(seat)}', **info)
    part = by[('d', 'subdimension')] + by[('d', 'sleeping')]
    if any(p > d for p in part):
        return res('implausible', f'часть {max(part)} глубже общей {d}', **info)
    lo, hi = RANGE[kind]
    if not lo <= d <= hi:
        return res('implausible', f'{kind}: {d} вне {lo}–{hi}', **info)
    return {'outcome': 'accepted', 'd': d, 'detail': '', 'd_view': sorted(d_views), **info}


# --- сеть и данные ----------------------------------------------------------------------------------------------------
class CacheError(RuntimeError):
    """Кэш чертежей не читается: битый JSON, не объект, нет файла там, где он обязателен."""


def load_cache(required: bool = False) -> dict:
    """Нет файла — пустой кэш (первый прогон шага), кроме загрузчика (`required`). Битый JSON / не объект — ОШИБКА:
    молча `{}` дал бы перезапись накопленных прочтений пустым кэшем (Codex T6)."""
    if not os.path.exists(CACHE):
        if required:
            raise CacheError(f'кэш чертежей не найден: {CACHE}')
        return {}
    try:
        c = json.load(open(CACHE, encoding='utf-8'))
    except ValueError as e:
        raise CacheError(f'кэш чертежей битый ({CACHE}): {e}') from e
    if not isinstance(c, dict):
        raise CacheError(f'кэш чертежей не объект ({CACHE})')
    return c


_BACKED_UP: set = set()


def save_cache(c: dict) -> None:
    """Атомарно: временный файл процесса → rename. Перед первой перезаписью в процессе — копия прежней версии рядом
    с меткой времени (старые копии не удаляются)."""
    os.makedirs(os.path.dirname(CACHE) or '.', exist_ok=True)
    if os.path.exists(CACHE) and CACHE not in _BACKED_UP:
        shutil.copy2(CACHE, f'{CACHE}.bak-{time.strftime("%Y%m%d-%H%M%S")}')
        _BACKED_UP.add(CACHE)
    tmp = f'{CACHE}.tmp-{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CACHE)


def drawing_url(mid: int, raw: str | None) -> str | None:
    """В фиде путь относительный (`/upload/iblock/…`) — от сайта магазина (у divanboss чужой хост отвечает 404)."""
    if not raw:
        return None
    if raw.startswith('//'):
        return 'https:' + raw
    if raw.startswith('/'):
        return f'https://{SHOPS[mid]}{raw}'
    return raw if raw.startswith('http') else None


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 remlab-drawing-dims'})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def prep_image(img: bytes) -> bytes:
    """Чертёж → JPEG для модели. PNG с прозрачностью — на белый фон: простой `convert('RGB')` красит прозрачное в цвет
    скрытых пикселей (у divanboss — чёрный), и чёрные линии с цифрами пропадают на чёрном (лист Т1, № 12 и 40)."""
    from PIL import Image
    im = Image.open(io.BytesIO(img))
    if im.mode in ('RGBA', 'LA', 'PA') or (im.mode == 'P' and 'transparency' in im.info):
        rgba = im.convert('RGBA')
        bg = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, rgba)
    im = im.convert('RGB')
    im.thumbnail((2048, 2048))                  # цифры чертежа мелкие — не ужимать сильнее
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=90)
    return buf.getvalue()


def ask(img: bytes) -> dict:
    """Платный вызов: только шлюз Vercel (`llm_gateway.chat(direct_fallback=False)`) — прямой OpenAI для модели google/…
    некорректен и тратит другие деньги (Codex 04.11)."""
    sys.path.insert(0, HERE)
    import llm_gateway  # noqa: E402
    # max_tokens с запасом: у думающих моделей рассуждение входит в ответ — пилот Т3: gemini-3.1-pro на П-образном съел
    # 3 838 из 4 000 на рассуждение, JSON оборвался (finish=length)
    msg = [{'role': 'user', 'content': [
        {'type': 'text', 'text': PROMPT},
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(prep_image(img)).decode()}}]}]
    out = llm_gateway.chat(MODEL, msg, timeout=180, tries=3, direct_fallback=False, temperature=0, max_tokens=16000)
    ch = out['choices'][0]
    return {'raw': ch['message']['content'] or '', 'usage': out.get('usage'), 'finish': ch.get('finish_reason'),
            'meta': {k: v for k, v in out.items() if k not in ('choices', 'usage')}}


def eligible() -> list[dict]:
    """Диваны двух магазинов в продаже без глубины — из БД (только чтение)."""
    sql = ("select shop_mid, external_id, coalesce(w_cm::text,''), coalesce(h_cm::text,''), coalesce(params->>'" + PARAM + "',''), "
           "coalesce(params->>'Конфигурация',''), replace(name, chr(9), ' ') from products "
           f"where shop_mid in ({','.join(map(str, SHOPS))}) and cat_role = 'диван' and status = 'active' "
           # и те, кому глубину уже дал чертёж: иначе после включения их адреса перестанут сверяться и глубина «состарится»
           "and (d_cm is null or dims_evidence->'d'->>'source' = 'drawing')")
    r = subprocess.run(PSQL, capture_output=True, text=True, input=sql)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    out = []
    for ln in r.stdout.strip().split('\n'):
        f = ln.split('\x1f')
        if len(f) < 7:
            continue
        mid = int(f[0])
        out.append({'mid': mid, 'eid': f[1], 'w': float(f[2]) if f[2] else None, 'h': float(f[3]) if f[3] else None,
                    'url': drawing_url(mid, f[4]), 'kind': kind_of(f[6], f[5]), 'side': side_of(f[6]), 'name': f[6]})
    return out


# --- прогон -----------------------------------------------------------------------------------------------------------
def scan(items: list[dict], cache: dict, paid: bool = False, max_calls: int = 0, only: set | None = None,
         fetch_fn=fetch, ask_fn=ask, save_fn=save_cache, index: bool = False,
         today: str | None = None) -> tuple[list[dict], collections.Counter]:
    """→ (решение по каждому SKU, счётчики). Сухо (`paid=False`) — ни одного вызова модели: чертежи без прочтения в кэше
    — `pending`. Платно — не больше `max_calls` вызовов за прогон; каждое удачное прочтение сразу пишется в кэш."""
    cnt: collections.Counter = collections.Counter()
    reads = cache.setdefault('reads', {})
    cnt['eligible'] = len(items)
    sha_of, fails = {}, {}
    todo = [it for it in items if it['url'] and it['kind'] in RANGE and it['w']]
    for url in sorted({it['url'] for it in todo}):
        try:
            b = fetch_fn(url)
            sha_of[url] = (hashlib.sha256(b).hexdigest(), b)
            if index:                           # адрес → sha СЕГОДНЯ: загрузчик берёт d по sha этого адреса
                cache.setdefault('urls', {})[url] = {'sha': sha_of[url][0], 'at': today or _today()}
        except Exception as e:  # noqa: BLE001 — не решено; громкий счётчик ниже
            fails[url] = str(e)[:120]
    by_sha: dict[str, bytes] = {s: b for s, b in sha_of.values()}
    cnt['unique'] = len(by_sha)
    calls = streak = 0
    for sha, b in sorted(by_sha.items()):
        if streak >= STOP_STREAK:
            cnt['stopped'] = 1
            print(f'  СТОП: {streak} сбоя подряд — дальше не зову', flush=True)
            break
        k = cache_key(sha)
        if k in reads:
            cnt['hit'] += 1
            continue
        cnt['miss'] += 1
        if not paid or calls >= max_calls or (only and sha[:12] not in only and sha not in only):
            continue
        calls += 1
        try:
            a = ask_fn(b)
        except Exception as e:  # noqa: BLE001 — сбой вызова ≠ вердикт
            fails[sha] = 'model: ' + str(e)[:120]
            streak += 1
            print(f'  ОТКАЗ МОДЕЛИ {sha[:12]}: {str(e)[:120]}', flush=True)
            continue
        try:
            rd = parse(a['raw'])
        except (ValueError, TypeError) as e:
            fails[sha] = 'parse: ' + str(e)[:120]
            streak += 1
            # журнал сбоев (не прочтение: следующий прогон спросит снова) — сырой ответ, причина обрыва и цена вызова
            # история попыток по ключу: удачное прочтение потом её не стирает — цена неудачных вызовов остаётся в учёте
            cache.setdefault('failed', {}).setdefault(k, []).append(
                {'sha': sha, 'model': MODEL, 'prompt_ver': PROMPT_VER, 'error': str(e)[:200], 'raw': a['raw'][:8000],
                 'finish': a.get('finish'), 'usage': a.get('usage')})
            save_fn(cache)
            print(f'  НЕ РАЗОБРАН {sha[:12]}: {str(e)[:120]} · ответ: {a["raw"][:200]!r}', flush=True)
            continue
        streak = 0
        reads[k] = {**rd, 'sha': sha, 'model': MODEL, 'prompt_ver': PROMPT_VER, 'prompt_sha': PROMPT_SHA,
                    'schema_ver': SCHEMA_VER, 'raw': a['raw'][:8000], 'usage': a.get('usage'), 'finish': a.get('finish'),
                    'meta': a.get('meta')}
        save_fn(cache)
    cnt['calls'] = calls
    if index:
        # SKU → последний сверенный (адрес, sha): адрес в фиде сменился, а новый ещё не сверен (шаг смотрит вчерашнюю БД) или
        # не скачался — загрузчик держит этот sha, а не снимает d (вариант Б). Время сверки шага — для WARN загрузчика
        for it in todo:
            if it['url'] in sha_of:
                cache.setdefault('sku', {})[f"{it['mid']}:{it['eid']}"] = {'url': it['url'], 'sha': sha_of[it['url']][0],
                                                                           'at': today or _today()}
        cache['scan_at'] = today or _today()
        save_fn(cache)
    out = []
    for it in items:
        base = {k: it.get(k) for k in ('mid', 'eid', 'name', 'kind', 'side', 'w', 'h', 'url')}
        if it['kind'] not in RANGE:
            r = {'outcome': 'skipped-part', 'd': None, 'detail': it['kind']}
        elif not it['url'] or not it['w']:
            r = {'outcome': 'no-drawing', 'd': None, 'detail': 'нет чертежа' if not it['url'] else 'нет ширины в карточке'}
        elif it['url'] in fails:
            r = {'outcome': 'download-fail', 'd': None, 'detail': fails[it['url']]}
        else:
            sha = sha_of[it['url']][0]
            base['sha'] = sha
            rd = reads.get(cache_key(sha))
            if rd:
                r = decide(rd, it['w'], it['h'], it['kind'])
            elif str(fails.get(sha, '')).startswith('model'):
                r = {'outcome': 'model-fail', 'd': None, 'detail': fails[sha]}
            elif str(fails.get(sha, '')).startswith('parse'):
                r = {'outcome': 'parse-fail', 'd': None, 'detail': fails[sha]}
            else:
                r = {'outcome': 'pending', 'd': None, 'detail': 'нет прочтения в кэше'}
        cnt[r['outcome']] += 1
        out.append({**base, **r})
    assert sum(cnt[o] for o in OUTCOMES) == cnt['eligible'], 'счётчики исходов не сходятся с eligible'
    return out, cnt


def _today() -> str:
    import datetime
    return datetime.date.today().isoformat()


# --- загрузчик (load3.assign): только кэш, без сети ---------------------------------------------------------------------
_LOADER_CACHE = None
STATS: collections.Counter = collections.Counter()      # счётчики оверлея за прогон загрузчика — для `loader_gate`


def loader_cache() -> dict:
    global _LOADER_CACHE
    if _LOADER_CACHE is None:
        _LOADER_CACHE = load_cache(required=True)
    return _LOADER_CACHE


def overlay(mid: int, name: str, params: dict | None, role: str | None, dims: dict, ev: dict | None, dsrc: str | None,
            cache: dict | None = None, today: str | None = None, eid: str | None = None) -> tuple[dict, dict | None, str | None]:
    """Принятая глубина с чертежа поверх разбора карточки (`load3.assign` после `resolve_dims`), сети нет. Ничего не меняет:
    не диван этих двух магазинов; глубина уже есть из карточки (карточка главнее); нет чертежа или часть модуля; адрес
    и SKU ни разу не сверялись (новинка — сверка следующей ночью); sha не прочитан (чертёж сменился); `decide` отказал.
    Адрес не сверен (сменился или не скачался), а SKU сверялся — берётся последний сверенный sha SKU. Старая сверка d
    не снимает — только счётчик."""
    if role != 'диван' or mid not in SHOPS or dims.get('d') is not None or not dims.get('w'):
        return dims, ev, dsrc
    p = params or {}
    url, kind = drawing_url(mid, p.get(PARAM)), kind_of(name, p.get('Конфигурация'))
    if not url or kind not in RANGE:
        return dims, ev, dsrc
    STATS['candidates'] += 1
    c = loader_cache() if cache is None else cache
    ix, basis = c.get('urls', {}).get(url), 'url'
    if not ix:
        ix, basis = ((c.get('sku') or {}).get(f'{mid}:{eid}') if eid is not None else None), 'sku_last'
        if not ix:
            STATS['no_index'] += 1
            return dims, ev, dsrc
        STATS['kept_unverified_url'] += 1
    if _age_days(ix.get('at'), today) > INDEX_MAX_AGE_DAYS:
        STATS['old_index'] += 1
    rd = c.get('reads', {}).get(cache_key(ix['sha']))
    if not rd:
        STATS['new_sha'] += 1
        return dims, ev, dsrc
    r = decide(rd, dims['w'], dims.get('h'), kind)
    if r['outcome'] != 'accepted':
        STATS['rejected'] += 1
        return dims, ev, dsrc
    STATS['applied'] += 1
    ev_d = {'raw': r['d'], 'unit': 'cm', 'source': 'drawing', 'semantic': 'overall_depth', 'view': r['d_view'],
            'sha': ix['sha'], 'url': ix.get('url', url), 'basis': basis, 'model': rd['model'], 'prompt_ver': rd['prompt_ver'],
            'schema_ver': rd['schema_ver'], 'policy_ver': POLICY_VER, 'w_read': r['w_read'], 'w_card': dims['w'],
            'dw': r['dw'], 'dw_pct': r['dw_pct'], 'status': 'accepted', 'checked': ix.get('at')}
    return {**dims, 'd': r['d']}, {**(ev or {}), 'd': ev_d}, ((dsrc or '') + ' drawing:1').strip()


def loader_preflight() -> str | None:
    """`load3.main` ДО записи в БД: None — кэш годен; иначе причина СТОПа (нет/битый, пустая сверка, нет прочтений
    текущей модели-промпта-схемы)."""
    try:
        c = loader_cache()
    except (CacheError, OSError) as e:
        return str(e)
    if not c.get('urls') or not c.get('scan_at'):
        return f'в кэше нет сверки адресов (шаг drawing_dims --cache-only не отработал ни разу): {CACHE}'
    suffix = f'|{MODEL}|{PROMPT_VER}|s{SCHEMA_VER}'
    if not any(k.endswith(suffix) for k in c.get('reads', {})):
        return f'в кэше нет прочтений {MODEL}/{PROMPT_VER}/s{SCHEMA_VER} — модель или промпт сменились без дочитывания'
    return None


def loader_gate(today: str | None = None) -> tuple[list[str], str | None]:
    """После разбора фидов, до записи в БД: строки для лога (сводка, WARN возраста сверки) и причина СТОПа или None."""
    s, c = STATS, loader_cache()
    out = [f"глубина с чертежа: кандидатов {s['candidates']}, подмешано {s['applied']} (из них по последней сверке SKU — "
           f"адрес не сверен {s['kept_unverified_url']}), сверка старше {INDEX_MAX_AGE_DAYS} дн {s['old_index']}, "
           f"чертёж сменился на непрочитанный {s['new_sha']}, отказ {s['rejected']}, не сверялись {s['no_index']}"]
    age = _age_days(c.get('scan_at'), today)
    if age > SCAN_WARN_DAYS:
        out.append(f"WARN:drawing_index_old: последняя сверка адресов чертежей {c.get('scan_at')} ({age} дн назад) — ночной шаг "
                   f"drawing_dims не работает; глубины держим последние подтверждённые")
    if s['candidates'] >= GATE_MIN_CANDIDATES and s['applied'] / s['candidates'] < DRAWING_MIN_SHARE:
        return out, (f"подмешано {s['applied']} из {s['candidates']} ({s['applied'] / s['candidates']:.0%}) < "
                     f"{DRAWING_MIN_SHARE:.0%} — кэш или сверка не те")
    return out, None


def _age_days(at: str | None, today: str | None = None) -> int:
    import datetime
    try:
        return (datetime.date.fromisoformat(today or _today()) - datetime.date.fromisoformat(at)).days
    except (TypeError, ValueError):
        return 10 ** 6


def main(a: list[str]) -> int:
    paid = '--paid' in a
    cache_only = '--cache-only' in a
    max_calls = int(a[a.index('--max-calls') + 1]) if '--max-calls' in a else 0
    if paid and max_calls <= 0:
        print('СТОП: платный режим только с явным потолком --max-calls N', flush=True)
        return 2
    max_calls = min(max_calls, MAX_CALLS_CAP)
    only = set(a[a.index('--only') + 1].split(',')) if '--only' in a else None
    if paid and cache_only:
        print('СТОП: --paid и --cache-only вместе не бывают', flush=True)
        return 2
    cache = load_cache()                 # битый — CacheError: шаг FAIL, кэш не перезаписан
    res, cnt = scan(eligible(), cache, paid=paid, max_calls=max_calls, only=only, index=paid or cache_only)
    if '--out' in a:
        with open(a[a.index('--out') + 1], 'w', encoding='utf-8') as f:
            for r in res:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'drawing_dims [{"ПЛАТНО" if paid else "только кэш" if cache_only else "сухо"}] модель {MODEL}, промпт {PROMPT_VER}/{PROMPT_SHA}, схема {SCHEMA_VER}', flush=True)
    print('  чертежи: ' + ', '.join(f'{k} {cnt[k]}' for k in ('eligible', 'unique', 'hit', 'miss', 'calls')), flush=True)
    if cnt['stopped']:
        print(f'WARN:drawing_dims_stopped: {STOP_STREAK} сбоя подряд', flush=True)
    print('  исходы SKU: ' + ', '.join(f'{k} {cnt[k]}' for k in OUTCOMES if cnt[k]), flush=True)
    for line in warn_lines(cnt, cache_only):
        print(line, flush=True)
    return 0


DEAD_SHARE_WARN = 0.10   # ночной cache-only: мёртвые ссылки магазина (34–42 из 1 564 на 04.11) — фон, WARN только при обвале


def warn_lines(cnt: dict, cache_only: bool) -> list[str]:
    """Строки итога. Платный/сухой ручной прогон — WARN на любой сбой. Ночной cache-only — без вызовов модели: мёртвые ссылки
    WARN только выше доли DEAD_SHARE_WARN от скачиваемых (иначе шаг жёлтый каждую ночь и прячет настоящие WARN дайджеста),
    новые чертежи без прочтения — строкой-сводкой (глубины у них нет, пока не дочитаем платно)."""
    dead, bad = cnt['download-fail'], cnt['download-fail'] + cnt['model-fail'] + cnt['parse-fail']
    if not cache_only:
        return [f'WARN:drawing_dims_failed: {bad}'] if bad else []
    out = [f'  мёртвых ссылок {dead}, новых чертежей без прочтения (pending) {cnt["pending"]} SKU']
    fetched = sum(cnt[o] for o in OUTCOMES if o not in ('no-drawing', 'skipped-part'))
    if fetched and dead / fetched > DEAD_SHARE_WARN:
        out.append(f'WARN:drawing_dims_dead_links: {dead} из {fetched} ({dead / fetched:.0%}) — сайт магазина или адреса чертежей сменились?')
    return out


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
