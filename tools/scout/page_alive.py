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
по фразе «Нет в наличии» из ШАБЛОНА страницы). Снятие требует подтверждения — `stock_truth.py`.

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
import re
import sys
import urllib.parse

PROBE_VERSION = 1

# evidence: 'sku' — ссылка ведёт на конкретный вариант; 'series' — только на страницу серии.
# signals: какие структурные признаки читаем. Текстовые маркеры не используются нигде.
SHOP_EVIDENCE = {
    'divan.ru':        {'evidence': 'sku',    'signals': ('schema',)},
    'divanboss.ru':    {'evidence': 'sku',    'signals': ('schema',)},
    'tvoydom.ru':      {'evidence': 'sku',    'signals': ('schema',)},
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
_POSITIVE = {'instock', 'instoreonly', 'onlineonly', 'limitedavailability', 'backorder',
             'preorder', 'presale'}
_NEGATIVE = {'soldout', 'outofstock', 'discontinued'}

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


def schema_state(body: str):
    """→ 'positive' | 'negative' | None. Смешанные сигналы читаем как положительные.

    На странице бывает несколько offers (варианты, аксессуары). Пока есть хоть один положительный,
    считать товар отсутствующим нельзя — иначе распродажа аксессуара утащит живой диван.
    """
    vals = [m.group(1).lower() for m in _SCHEMA_RE.finditer(body or '')]
    if not vals:
        return None
    if any(v in _POSITIVE for v in vals):
        return 'positive'
    if any(v in _NEGATIVE for v in vals):
        return 'negative'
    return None


def classify(shop: str, http_code, body: str = '', error: str = '', final_url: str = '',
             url: str = ''):
    """→ (verdict, reason). Единственное место, где решается судьба карточки."""
    c = contract(shop)
    if error:
        return 'unknown', f'не проверилось: {error[:60]}'
    # АНТИБОТ ПРОВЕРЯЕМ ПЕРВЫМ, ДО ЛЮБОГО КОДА (правило владельца 01.09: «если сразу видишь, что
    # это бот, снимать не надо — значит проверить не можем, верим Гдеслону»). Раньше ветка
    # 404/410 стояла ВЫШЕ и возвращала `gone`, не заглядывая в тело: WAF вправе отдавать любой
    # код 4xx, и магазин, закрывшийся от нашего бота ответом 404, читался как «товара нет».
    # Цена ошибки тут не «один товар из тысячи», а весь магазин разом — и повторный заход её
    # не ловит: закрытая дверь закрыта и через 15 минут, и через 6 часов.
    if _BLOCKED_URL_RE.search(final_url or '') or \
            (len(body or '') < CHALLENGE_MAX_BYTES and _CHALLENGE_RE.search(body or '')):
        return 'unknown', 'антибот/капча'
    if http_code in (404, 410):
        return 'gone', f'http {http_code}'
    if http_code in (401, 403, 429) or (isinstance(http_code, int) and http_code >= 500):
        return 'unknown', f'http {http_code} (нас не пустили)'
    if isinstance(http_code, int) and 300 <= http_code < 400:
        return 'unknown', f'http {http_code} (редирект без страницы)'
    if http_code != 200:
        return 'unknown', f'http {http_code}'
    # Редирект со страницы товара на каталог/главную — товара нет, но доказательства слабее 404:
    # магазины так маскируют и временные проблемы. Поэтому unknown, а не gone.
    if final_url and url and url_key(final_url) != url_key(url):
        return 'unknown', 'редирект на другую страницу'
    if c['evidence'] == 'series':
        return 'unknown', 'страница серии не доказывает вариант'
    if 'schema' in c['signals']:
        st = schema_state(body)
        if st == 'positive':
            return 'alive', 'schema: в продаже'
        if st == 'negative':
            return 'oos', 'schema: нет в продаже'
    return 'unknown', '200 без структурного признака наличия'


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
    print(f'page_alive selftest: случаев {len(cases) + len(pairs) + 2}, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
