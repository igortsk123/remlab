#!/usr/bin/env python3
"""СВИДЕТЕЛЬСТВО О КАРТОЧКЕ ТОВАРА — чистый классификатор ответа магазина (31.08.2026).

Здесь нет сети и нет записи в БД: на вход — что ответил магазин, на выход — вердикт и причина.
Так его можно гонять селфтестом на зафиксированных случаях, а не «на живом каталоге».
Сеть и запись — в `stock_check.py`.

ЧЕТЫРЕ ВЕРДИКТА, И ТОЛЬКО ОДИН ИЗ НИХ СНИМАЕТ ТОВАР МОЛЧА — НИКАКОЙ.
  alive   — есть положительное свидетельство продажи ЭТОГО товара;
  oos     — есть точное свидетельство, что он не продаётся (schema OutOfStock, qty=0);
  gone    — страницы товара больше нет (404/410);
  unknown — доказательств нет: антибот, капча, таймаут, редирект, 200 без сигнала.
`unknown` НИКОГДА не приговор (уроки 320/326: прежняя версия убила 119 живых товаров divan.ru
по фразе «Нет в наличии» из ШАБЛОНА страницы). Снятие — с первого отказа (ADR-0148); защита —
якорь домена и карантин магазина в `stock_check`, негатив только по текущей ссылке (Н1).
Помимо вердикта `classify_full()` отдаёт СТРУКТУРУ: response_kind (http|transport_error|redirect),
failure_kind (почему не смогли проверить), evidence_kind (чем доказан вердикт) — доменному автомату
и полю уверенности нужны именно они, а не текст reason.

ЧТО ЗНАЧИТ `unknown` ДЛЯ НАЛИЧИЯ: ВЕРИМ ФИДУ ГДЕСЛОНА (решение владельца 01.09, ADR-0147).
Товар, про который мы НЕ СМОГЛИ узнать сами, остаётся ровно в том наличии, какое отдал фид, —
`reconcile` в `stock_truth.py` вердикты `unknown` не применяет. Это осознанное решение, а не
недоделка: у gipfel.ru и mdm-complect.ru антибот, своего свидетельства по ним не будет, и
единственная альтернатива — либо снимать 1095 живых товаров без доказательств, либо доверять
партнёрке. Выбрана партнёрка. НЕ «чинить» это, добавив снятие по `unknown`.

КОНТРАКТ МАГАЗИНА ВАЖНЕЕ HTTP-КОДА. Ссылка ведёт либо на карточку конкретного варианта (`sku`),
либо на страницу серии (`series`). Страница серии физически не может доказать наличие конкретного
цвета — для неё HTTP 200 это `unknown`, и никакие слова из названия этого не меняют.
`series` сейчас не назначен никому: 01.09 выяснилось, что у mnogomebeli мы сами обрезали ссылку
до раздела (`reflink.py`, ADR-0144) и потом честно записали «доказать ничего нельзя». Ставить
магазину `series` можно, только если ТАК ОТДАЁТ ПАРТНЁРКА, а не мы так обрезали.

ЧЕМ ЧИТАЕТСЯ НАЛИЧИЕ (замеры 31.08 на живых и снятых карточках):
  divan.ru      JSON-LD `schema.org/InStock` у живого, `OutOfStock` у снятого (страница жива, 200);
                при этом «нет в наличии» встречается в шаблоне живой страницы 10 раз — текст не судья;
  divanboss.ru  JSON-LD `schema.org/InStock`; снятый вариант отдаёт 404 (проверено 6 живых → 200,
                6 снятых → 404);
  tvoydom.ru    микроразметка `itemprop="availability" content="InStock|backorder|OutOfStock"`;
                снятый товар — 404. Прежнее правило health по `"quantity":N` УСТАРЕЛО: этого поля
                на страницах больше нет (31.08), оно молча превращало проверку в «по маркеру»;
  mnogomebeli   JSON-LD `schema.org/InStock` на карточке варианта (`/!вариант/`); снятый вариант
                отдаёт 404, а вот его РОДИТЕЛЬ (путь без `/!`) 404 отдаёт всегда — по нему и
                ошиблись 26.08, когда решили резать ссылку до раздела (замеры 01.09: 19 живых
                и 11 мёртвых карточек из 30, обрезанные разделы — 30 из 30 «живы»);
  mdm-complect  антибот: 307-цикл на `?_ycch=` → unknown;
  gipfel.ru     антибот: 403 DDoS-guard → unknown.
"""
import hashlib
import json
import os
import re
import sys
import urllib.parse

# ПАРСЕР v2 (план stock-and-dims-honesty, Н0) — ТОЛЬКО В ТЕНИ, пока не пройден gold-замер:
# snake_case значений (`content="in_stock"` у tvoydom — 3 332 карточки читались как «без признака»),
# `href=` рядом с `content=` при любом порядке атрибутов (gipfel), JSON-LD только объекта Product,
# inline-JSON остаток tvoydom (`overallStock`/`availableShops`) как часть ОДНОГО вердикта.
# Включение: STOCK_PARSER_V2=1 (shadow-прогон); после gold — переключить дефолт и PROBE_VERSION.
PARSER_V2 = os.environ.get('STOCK_PARSER_V2', '0') == '1'
PROBE_VERSION = 2 if PARSER_V2 else 1

# evidence: 'sku' — ссылка ведёт на конкретный вариант; 'series' — только на страницу серии.
# signals: какие структурные признаки читаем. Текстовые маркеры не используются нигде.
SHOP_EVIDENCE = {
    'divan.ru':        {'evidence': 'sku',    'signals': ('schema',)},
    'divanboss.ru':    {'evidence': 'sku',    'signals': ('schema',)},
    'tvoydom.ru':      {'evidence': 'sku',    'signals': ('schema', 'inline_stock')},
    'mdm-complect.ru': {'evidence': 'sku',    'signals': ('schema',)},
    'gipfel.ru':       {'evidence': 'sku',    'signals': ('schema',)},
    'h-f-l.ru':        {'evidence': 'sku',    'signals': ('schema',)},
    'mnogomebeli.com': {'evidence': 'sku',    'signals': ('schema',)},
}
DEFAULT_CONTRACT = {'evidence': 'sku', 'signals': ('schema',)}   # незнакомый магазин — без эвристик

# schema.org/Availability: и JSON-LD ("availability":"https://schema.org/InStock"), и микроразметка
# (<meta itemprop="availability" content="backorder">). BackOrder/PreOrder — товар ПРОДАЁТСЯ (под
# заказ), это не отсутствие; Discontinued/SoldOut/OutOfStock — не продаётся.
_SCHEMA_RE = re.compile(
    r'(?:availability["\']?\s*[:=]\s*["\']?(?:https?://schema\.org/)?|itemprop=["\']availability["\'][^>]{0,80}?content=["\'])'
    r'(InStock|InStoreOnly|OnlineOnly|LimitedAvailability|BackOrder|PreOrder|PreSale|SoldOut|OutOfStock|Discontinued)',
    re.I)
# v2: те же значения в snake_case/с дефисом, форма href=, любой порядок атрибутов в теге
_AVAIL_VALUE = r'(in[_ -]?stock|in[_ -]?store[_ -]?only|online[_ -]?only|limited[_ -]?availability|back[_ -]?order|pre[_ -]?order|pre[_ -]?sale|sold[_ -]?out|out[_ -]?of[_ -]?stock|discontinued)'
_SCHEMA_RE_V2 = re.compile(
    r'(?:availability["\']?\s*[:=]\s*["\']?(?:https?://schema\.org/)?|'
    r'itemprop=["\']availability["\'][^>]{0,120}?(?:content|href)=["\'](?:https?://schema\.org/)?|'
    r'(?:content|href)=["\'](?:https?://schema\.org/)?)' + _AVAIL_VALUE, re.I)
_TAG_AVAIL_RE = re.compile(r'<(?:meta|link)\b[^>]*itemprop=["\']availability["\'][^>]*>', re.I)
_POSITIVE = {'instock', 'instoreonly', 'onlineonly', 'limitedavailability', 'backorder',
             'preorder', 'presale'}
_NEGATIVE = {'soldout', 'outofstock', 'discontinued'}
_INLINE_STOCK_RE = re.compile(r'"overallStock"\s*:\s*(-?\d+)|"availableShops"\s*:\s*(-?\d+)')
_LDJSON_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.I | re.S)


def _norm_avail(v: str) -> str:
    return re.sub(r'[_ -]', '', (v or '').lower())

# Признаки, что нас не пустили (а не что товара нет). Ловим до любых выводов о наличии.
# ОСТОРОЖНО С СЛОВОМ «captcha»: на живой карточке divanboss оно встречается 18 раз — это
# `recaptcha_response` в форме обратной связи. Первая версия по нему объявляла живые товары
# «антиботом» (6 из 8 в первом же прогоне). Тот же класс ошибки, что и «Нет в наличии»
# из шаблона (урок 320): маркер судит только там, где он не может быть частью нормальной страницы.
_BLOCKED_URL_RE = re.compile(r'showcaptcha|/captcha|_ycch|challenge', re.I)
_CHALLENGE_RE = re.compile(r'ddos-guard|ddos guard|checking your browser|cf-browser-verification|'
                           r'attention required|доступ ограничен|подтвердите, что вы не робот', re.I)
CHALLENGE_MAX_BYTES = 60_000     # заглушка антибота — маленькая; каталожная страница — сотни КБ
_TRACKING = re.compile(r'^(erid|utm_[a-z]+|_ycch|yclid|gclid|from|frommarket)$', re.I)


def contract(shop: str) -> dict:
    """Контракт магазина по имени хоста (`products.shop`)."""
    return SHOP_EVIDENCE.get((shop or '').lower().replace('www.', ''), DEFAULT_CONTRACT)


def url_key(url: str) -> str:
    """Стабильный ключ ссылки: без рекламных хвостов, регистра хоста и `:443`.

    Нужен, чтобы отрицательное свидетельство было привязано к КОНКРЕТНОЙ ссылке: 26.08 мы чинили
    формирование реф-ссылок, и старый 404 не должен гасить товар с новой, исправленной ссылкой.
    """
    u = (url or '').strip()
    p = urllib.parse.urlsplit(u)
    host = (p.hostname or '').lower()
    # ОДНА И ТА ЖЕ КАРТОЧКА В ДВУХ КОДИРОВКАХ — ОДИН КЛЮЧ (01.09, замечание Codex): у mnogomebeli
    # вариант отделяется символом `!`, и `/!divan-…/` против `/%21divan-…/` — это один адрес
    # (обе формы отдают 200). Без нормализации смена кодировки в загрузчике молча обнулила бы
    # накопленные отрицательные свидетельства по всему магазину: `fold()` считает голоса только
    # по ТЕКУЩЕМУ url_hash.
    raw = p.path or '/'
    # `%2F` внутри сегмента — часть имени, а не разделитель пути: раскодировав, мы склеили бы
    # разные адреса в один. Такие пути (у нас их единицы) оставляем как есть.
    path = raw if '%2f' in raw.lower() else \
        urllib.parse.quote(urllib.parse.unquote(raw), safe="/-._~!$&'()*+,;=:@")
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
         if not _TRACKING.match(k)]
    norm = urllib.parse.urlunsplit((p.scheme.lower() or 'https', host, path,
                                    urllib.parse.urlencode(sorted(q)), ''))
    return hashlib.sha1(norm.encode('utf-8')).hexdigest()[:16]


def _ldjson_product_avail(body: str) -> list:
    """v2: availability ТОЛЬКО из объектов Product в JSON-LD (не из аксессуаров/списков)."""
    out = []
    for m in _LDJSON_RE.finditer(body or ''):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:  # noqa: BLE001 — битый блок JSON-LD не судья
            continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x); continue
            if not isinstance(x, dict):
                continue
            t = x.get('@type')
            types = t if isinstance(t, list) else [t]
            if any(str(tt).lower() == 'product' for tt in types if tt):
                offers = x.get('offers')
                for o in (offers if isinstance(offers, list) else [offers]):
                    if isinstance(o, dict) and o.get('availability'):
                        out.append(_norm_avail(str(o['availability']).split('/')[-1]))
            for k in ('@graph', 'mainEntity', 'itemListElement'):
                if k in x:
                    stack.append(x[k])
    return out


def _micro_avail(body: str) -> list:
    """v2: значения availability из тегов микроразметки, content= или href=, любой порядок атрибутов."""
    out = []
    for m in _TAG_AVAIL_RE.finditer(body or ''):
        tag = m.group(0)
        v = re.search(r'(?:content|href)=["\']([^"\']+)["\']', tag, re.I)
        if v:
            out.append(_norm_avail(v.group(1).split('/')[-1]))
    return out


def schema_state(body: str):
    """→ 'positive' | 'negative' | None. Смешанные сигналы читаем как положительные.

    На странице бывает несколько offers (варианты, аксессуары). Пока есть хоть один положительный,
    считать товар отсутствующим нельзя — иначе распродажа аксессуара утащит живой диван.
    v2: JSON-LD только Product, микроразметка content/href, snake_case; v1 — прежняя регулярка.
    """
    if PARSER_V2:
        vals = _ldjson_product_avail(body) + _micro_avail(body)
        if not vals:
            vals = [_norm_avail(m.group(1)) for m in _SCHEMA_RE_V2.finditer(body or '')]
    else:
        vals = [m.group(1).lower() for m in _SCHEMA_RE.finditer(body or '')]
    if not vals:
        return None
    if any(v in _POSITIVE for v in vals):
        return 'positive'
    if any(v in _NEGATIVE for v in vals):
        return 'negative'
    return None


def inline_stock_state(body: str):
    """v2, tvoydom: остаток из inline-JSON карточки → 'positive' | 'negative' | None."""
    stock = shops = None
    for m in _INLINE_STOCK_RE.finditer(body or ''):
        if m.group(1) is not None and stock is None:
            stock = int(m.group(1))
        if m.group(2) is not None and shops is None:
            shops = int(m.group(2))
    if stock is None and shops is None:
        return None
    if (stock or 0) > 0 or (shops or 0) > 0:
        return 'positive'
    return 'negative'


def classify_full(shop: str, http_code, body: str = '', error: str = '', final_url: str = '',
                  url: str = '') -> dict:
    """→ {verdict, reason, response_kind, failure_kind, evidence_kind}. Единственное место, где
    решается судьба карточки."""
    def out(verdict, reason, response_kind, failure_kind=None, evidence_kind='none'):
        return {'verdict': verdict, 'reason': reason, 'response_kind': response_kind,
                'failure_kind': failure_kind, 'evidence_kind': evidence_kind}
    c = contract(shop)
    if error:
        low = error.lower()
        kind = ('timeout' if 'timed out' in low or 'timeout' in low else
                'dns' if 'name or service' in low or 'getaddrinfo' in low or 'nodename' in low else
                'tls' if 'ssl' in low or 'certificate' in low else 'transport')
        return out('unknown', f'не проверилось: {error[:60]}', 'transport_error', kind)
    # АНТИБОТ ПРОВЕРЯЕМ ПЕРВЫМ, ДО ЛЮБОГО КОДА (правило владельца 01.09: «если сразу видишь, что
    # это бот, снимать не надо — значит проверить не можем, верим Гдеслону»). WAF вправе отдавать
    # любой код 4xx, и магазин, закрывшийся от нашего бота ответом 404, читался бы как «товара нет».
    # Маркеры ищем в ПЕРВЫХ 60 КБ независимо от общей длины тела (Д5: заглушка WAF, обрезанная
    # чтением на 65 536 байт, была длиннее порога, и проверка не выполнялась вовсе).
    head = (body or '')[:CHALLENGE_MAX_BYTES]
    if _BLOCKED_URL_RE.search(final_url or '') or _CHALLENGE_RE.search(head):
        return out('unknown', 'антибот/капча', 'http', 'challenge')
    if http_code in (404, 410):
        return out('gone', f'http {http_code}', 'http', None, 'http_gone')
    if http_code == 429:
        return out('unknown', 'http 429 (нас ограничили)', 'http', 'rate_limit')
    if http_code in (401, 403):
        return out('unknown', f'http {http_code} (нас не пустили)', 'http', 'challenge')
    if isinstance(http_code, int) and http_code >= 500:
        return out('unknown', f'http {http_code} (сбой магазина)', 'http', 'server_error')
    if isinstance(http_code, int) and 300 <= http_code < 400:
        return out('unknown', f'http {http_code} (редирект без страницы)', 'redirect', 'redirected')
    if http_code != 200:
        return out('unknown', f'http {http_code}', 'http', 'http_error')
    # Редирект со страницы товара на каталог/главную — товара нет, но доказательства слабее 404:
    # магазины так маскируют и временные проблемы. Поэтому unknown, а не gone.
    if final_url and url and url_key(final_url) != url_key(url):
        return out('unknown', 'редирект на другую страницу', 'redirect', 'redirected')
    if c['evidence'] == 'series':
        return out('unknown', 'страница серии не доказывает вариант', 'http', 'no_signal')
    if 'schema' in c['signals']:
        st = schema_state(body)
        if PARSER_V2 and 'inline_stock' in c['signals']:
            ist = inline_stock_state(body)
            # один вердикт из двух сигналов одной страницы (Codex): положительный побеждает,
            # отрицательный — только без положительного, конфликт → unknown
            if st == 'positive' or ist == 'positive':
                if (st == 'negative' and ist == 'positive') or (st == 'positive' and ist == 'negative'):
                    return out('unknown', 'конфликт schema ↔ inline-остаток', 'http', 'no_signal')
                src = 'schema' if st == 'positive' else 'inline_stock'
                return out('alive', f'{src}: в продаже', 'http', None, src)
            if st == 'negative' or ist == 'negative':
                src = 'schema' if st == 'negative' else 'inline_stock'
                return out('oos', f'{src}: нет в продаже', 'http', None, src)
        if st == 'positive':
            return out('alive', 'schema: в продаже', 'http', None, 'schema')
        if st == 'negative':
            return out('oos', 'schema: нет в продаже', 'http', None, 'schema')
    return out('unknown', '200 без структурного признака наличия', 'http', 'no_signal')


_PRICE_LD_RE = re.compile(r'"price"\s*:\s*"?(\d+(?:[.,]\d+)?)')
_PRICE_META_RE = re.compile(r'itemprop=["\']price["\'][^>]{0,80}?content=["\'](\d+(?:[.,]\d+)?)', re.I)
_TITLE_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']{3,200})', re.I)
_TITLE2_RE = re.compile(r'<title>\s*([^<]{3,200}?)\s*</title>', re.I | re.S)
_CANON_RE = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', re.I)


def extract_page_facts(body: str) -> dict:
    """Что ещё дёшево взять со страницы (Н3): цена, имя, канонический адрес — как НАБЛЮДЕНИЯ.
    Цена: JSON-LD Product.offers.price → microdata itemprop=price → inline `"price":N` (tvoydom).
    Страница читается до первого положительного признака, поэтому поля могут быть пустыми — это норма."""
    out = {'price_seen': None, 'name_seen': None, 'canonical_url': None}
    b = body or ''
    for m in _LDJSON_RE.finditer(b):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:  # noqa: BLE001
            continue
        stack = [data]
        while stack and out['price_seen'] is None:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x); continue
            if not isinstance(x, dict):
                continue
            t = x.get('@type'); types = t if isinstance(t, list) else [t]
            if any(str(tt).lower() == 'product' for tt in types if tt):
                offers = x.get('offers')
                for o in (offers if isinstance(offers, list) else [offers]):
                    if isinstance(o, dict) and o.get('price') not in (None, ''):
                        try:
                            out['price_seen'] = float(str(o['price']).replace(',', '.')); break
                        except ValueError:
                            pass
                if out['name_seen'] is None and x.get('name'):
                    out['name_seen'] = str(x['name'])[:200]
            for k in ('@graph', 'mainEntity'):
                if k in x:
                    stack.append(x[k])
    if out['price_seen'] is None:
        m = _PRICE_META_RE.search(b) or _PRICE_LD_RE.search(b)
        if m:
            try:
                out['price_seen'] = float(m.group(1).replace(',', '.'))
            except ValueError:
                pass
    if out['name_seen'] is None:
        m = _TITLE_RE.search(b) or _TITLE2_RE.search(b)
        if m:
            out['name_seen'] = re.sub(r'\s+', ' ', m.group(1)).strip()[:200]
    m = _CANON_RE.search(b)
    if m:
        out['canonical_url'] = m.group(1).strip()[:900]
    return out


def classify(shop: str, http_code, body: str = '', error: str = '', final_url: str = '',
             url: str = ''):
    """→ (verdict, reason) — совместимая обёртка над classify_full()."""
    r = classify_full(shop, http_code, body, error, final_url, url)
    return r['verdict'], r['reason']


# --- селфтест: таблица случаев вместо «проверим на живом каталоге» ---------------------------
def _selftest() -> int:
    JSONLD_IN = '{"@type":"Product","offers":{"availability":"https://schema.org/InStock"}}'
    JSONLD_OUT = '{"@type":"Product","offers":{"availability":"https://schema.org/OutOfStock"}}'
    META_BACKORDER = '<meta itemprop="availability" content="backorder">'
    TEMPLATE_OOS_TEXT = 'Нет в наличии' * 10 + JSONLD_IN     # шаблонный текст на ЖИВОЙ странице
    cases = [
        # (магазин, код, тело, ошибка, финальный url, url, ожидаемый вердикт)
        ('divanboss.ru', 404, '', '', '', '', 'gone'),
        ('divanboss.ru', 410, '', '', '', '', 'gone'),
        ('divanboss.ru', 200, JSONLD_IN, '', '', '', 'alive'),
        ('divan.ru',     200, JSONLD_OUT, '', '', '', 'oos'),
        ('divan.ru',     200, TEMPLATE_OOS_TEXT, '', '', '', 'alive'),   # урок 320: текст не судья
        ('divan.ru',     200, 'нет в наличии', '', '', '', 'unknown'),   # без schema — не знаем
        ('tvoydom.ru',   200, META_BACKORDER, '', '', '', 'alive'),      # под заказ = продаётся
        ('tvoydom.ru',   404, 'x' * 1000, '', '', '', 'gone'),
        ('gipfel.ru',    403, 'DDoS-GUARD', '', '', '', 'unknown'),
        ('mdm-complect.ru', 307, '', '', '', '', 'unknown'),
        ('mdm-complect.ru', 200, '<html>DDoS-Guard</html>',
         '', 'https://www.mdm-complect.ru/catalog/1/?_ycch=2', '', 'unknown'),
        # живая карточка с формой обратной связи: recaptcha_response — НЕ антибот
        ('divanboss.ru', 200, ('<input name="recaptcha_response">' * 18) + JSONLD_IN + 'x' * 300000,
         '', '', '', 'alive'),
        # а вот короткая заглушка антибота на 200 — именно антибот
        ('divanboss.ru', 200, '<html><body>Checking your browser…</body></html>', '', '', '',
         'unknown'),
        ('divan.ru',     429, '', '', '', '', 'unknown'),
        ('divan.ru',     503, '', '', '', '', 'unknown'),
        ('divan.ru',     None, '', 'timed out', '', '', 'unknown'),
        # WAF ВПРАВЕ ОТДАТЬ ЛЮБОЙ КОД 4xx, в том числе 404 (01.09). Пока ветка 404 стояла выше
        # проверки антибота, магазин, закрывшийся от нашего бота, читался как «товара нет» —
        # и снялся бы ВЕСЬ. Теперь тело и адрес осматриваются первыми.
        ('divanboss.ru', 404, '<html><body>Checking your browser…</body></html>', '', '', '',
         'unknown'),
        ('gipfel.ru',    404, '<html>DDoS-Guard</html>', '', '', '', 'unknown'),
        ('mdm-complect.ru', 404, '', '', 'https://www.mdm-complect.ru/tmgrdfrend/showcaptchafast?d=1',
         '', 'unknown'),
        # но обычный 404 без признаков антибота по-прежнему снимает товар
        ('divanboss.ru', 404, '<html><body>Страница не найдена</body></html>', '', '', '', 'gone'),
        # карточка варианта mnogomebeli читается как у всех — по schema (ADR-0144, 01.09)
        ('mnogomebeli.com', 200, JSONLD_IN, '', '', '', 'alive'),
        ('mnogomebeli.com', 200, JSONLD_OUT, '', '', '', 'oos'),
        ('mnogomebeli.com', 404, '', '', '', '', 'gone'),
        ('mnogomebeli.com', 200, 'страница без разметки', '', '', '', 'unknown'),
        ('divan.ru', 200, JSONLD_IN, '', 'https://www.divan.ru/category/divany',
         'https://www.divan.ru/product/x', 'unknown'),                   # увели с карточки
        ('shop-unknown.ru', 200, 'что угодно', '', '', '', 'unknown'),   # незнакомый магазин
        ('shop-unknown.ru', 404, '', '', '', '', 'gone'),
    ]
    bad = 0
    for shop, code, body, err, final, url, want in cases:
        got, why = classify(shop, code, body, err, final, url)
        if got != want:
            bad += 1
            print(f'  FAIL {shop} http={code} → {got} ({why}), ожидалось {want}')
    # Ветка `series` сейчас никому не назначена, но она рабочая и должна остаться рабочей:
    # проверяем на временно зарегистрированном магазине, а не на боевом контракте.
    SHOP_EVIDENCE['series-only.test'] = {'evidence': 'series', 'signals': ('schema',)}
    try:
        if classify('series-only.test', 200, JSONLD_IN)[0] != 'unknown':
            bad += 1
            print('  FAIL страница серии с InStock обязана оставаться unknown')
        if classify('series-only.test', 404, '')[0] != 'gone':
            bad += 1
            print('  FAIL 404 на серии — это всё равно gone')
    finally:
        SHOP_EVIDENCE.pop('series-only.test', None)
    # ключ ссылки: рекламный хвост и регистр хоста не меняют идентичность
    pairs = [
        ('https://DIVANBOSS.RU/a/b/?erid=X', 'https://divanboss.ru/a/b/', True),
        ('https://www.divan.ru/product/x?utm_source=1&erid=2', 'https://www.divan.ru/product/x', True),
        ('https://divanboss.ru/a/b/', 'https://divanboss.ru/a/c/', False),
        # `!` и `%21` — одна карточка (иначе смена кодировки обнулит все голоса магазина)
        ('https://mnogomebeli.com/divany/boss/x/!divan-a/',
         'https://mnogomebeli.com/divany/boss/x/%21divan-a/', True),
        ('https://mnogomebeli.com/divany/boss/x/!divan-a/',
         'https://mnogomebeli.com/divany/boss/x/!divan-b/', False),
    ]
    for a, b, same in pairs:
        if (url_key(a) == url_key(b)) is not same:
            bad += 1
            print(f'  FAIL url_key: {a} vs {b} — ожидалось {"совпадение" if same else "различие"}')
    # структура ответа (Н1): виды сбоев и свидетельств
    kinds = [
        (('divan.ru', None, '', 'URLError: <urlopen error timed out>', '', ''), ('transport_error', 'timeout', 'none')),
        (('divan.ru', 404, 'Страница не найдена', '', '', ''), ('http', None, 'http_gone')),
        (('divan.ru', 429, '', '', '', ''), ('http', 'rate_limit', 'none')),
        (('divan.ru', 503, '', '', '', ''), ('http', 'server_error', 'none')),
        (('divan.ru', 200, JSONLD_IN, '', '', ''), ('http', None, 'schema')),
        (('divan.ru', 200, 'без разметки', '', '', ''), ('http', 'no_signal', 'none')),
        (('gipfel.ru', 403, 'DDoS-GUARD', '', '', ''), ('http', 'challenge', 'none')),
        # WAF-заглушка длиннее 60 КБ: маркер в начале тела всё равно найден (Д5)
        (('divanboss.ru', 404, '<html>Checking your browser…</html>' + 'x' * 70000, '', '', ''), ('http', 'challenge', 'none')),
    ]
    for args, want in kinds:
        r = classify_full(*args)
        got = (r['response_kind'], r['failure_kind'], r['evidence_kind'])
        if got != want:
            bad += 1
            print(f'  FAIL kinds {args[0]} http={args[1]}: {got}, ожидалось {want}')
    # v2-разбор (Н0): snake_case, href, любой порядок атрибутов, JSON-LD только Product, inline-остаток
    v2 = [
        (_micro_avail('<meta content="in_stock" itemprop="availability">'), ['instock']),
        (_micro_avail('<link itemprop="availability" href="http://schema.org/InStock">'), ['instock']),
        (_micro_avail('<meta itemprop="availability" content="out_of_stock"/>'), ['outofstock']),
        (_ldjson_product_avail('<script type="application/ld+json">{"@type":"Product","offers":{"availability":"https://schema.org/OutOfStock"}}</script>'), ['outofstock']),
        (_ldjson_product_avail('<script type="application/ld+json">{"@type":"BreadcrumbList","offers":{"availability":"https://schema.org/InStock"}}</script>'), []),
        (_ldjson_product_avail('<script type="application/ld+json">{"@graph":[{"@type":"Product","offers":[{"availability":"http://schema.org/InStock"},{"availability":"http://schema.org/SoldOut"}]}]}</script>'), ['instock', 'soldout']),
        (inline_stock_state('"price":5399,"overallStock":4,"availableShops":3'), 'positive'),
        (inline_stock_state('"overallStock":0,"availableShops":0'), 'negative'),
        (inline_stock_state('нет таких полей'), None),
    ]
    for got, want in v2:
        if got != want:
            bad += 1
            print(f'  FAIL v2: {got!r} != {want!r}')
    facts = extract_page_facts('<title>Диван Босс</title><link rel="canonical" href="https://x.ru/p/1"><script type="application/ld+json">{"@type":"Product","name":"Диван Босс ХО","offers":{"price":"26990.00","availability":"https://schema.org/InStock"}}</script>')
    if facts != {'price_seen': 26990.0, 'name_seen': 'Диван Босс ХО', 'canonical_url': 'https://x.ru/p/1'}:
        bad += 1; print('  FAIL facts:', facts)
    f2 = extract_page_facts('<meta property="og:title" content="Люстра X"> :cards=\'[{"price":5399,"overallStock":4}]\'')
    if (f2['price_seen'], f2['name_seen']) != (5399.0, 'Люстра X'):
        bad += 1; print('  FAIL facts inline:', f2)
    print(f'page_alive selftest: случаев {len(cases) + len(pairs) + len(kinds) + len(v2) + 4}, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
