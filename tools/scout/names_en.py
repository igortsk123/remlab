"""АНГЛИЙСКИЕ НАЗВАНИЯ ТОВАРОВ ВИТРИНЫ (план demo-31, владелец 30.10: английское демо — временная «британская маска»).

Каждому товару `demo-data.json` — `name_en` (и `colour_en` — хвост названия про цвет/материал, его показывают кружки цветов)
без кириллицы и без домена/названия магазина. Порядок:
  1) `data/names-en.json` — переведённые вручную названия текущей витрины (ключ — `sid`, у кого его нет — исходное название);
     запись берётся, только если русское название не поменялось (магазин переименовал товар — переводим заново);
  2) словарь `data/names-en-dict.json`: тип («Диван прямой» → «straight sofa»), материал/цвет («Рогожка Серый» →
     «grey woven fabric»), рисунки фасадов, известные модели; остальное — транслитерация («Викс» → «Viks»), размеры как есть;
  3) осталась кириллица или магазин — нейтральное по роли («Sofa», «Rug») и строка в отчёте. Публикацию это не останавливает.
Форма: «Viks straight sofa, grey woven fabric» — модель, тип, размеры; после запятой — цвет и материал. Британское написание.
    ~/venvs/scout/bin/python tools/scout/names_en.py [demo-data.json]      # отчёт по витрине, файл не меняется"""
import json
import os
import re
import sys
import unicodedata
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(HERE, 'data', 'names-en.json')
DICT_PATH = os.path.join(HERE, 'data', 'names-en-dict.json')
CYR = re.compile(r'[\u0400-\u052f]')   # вся кириллица, не только русская («Ӧ» тоже не пройдёт в английское)
# домен в названии — любое «слово.ru/.com/…»; названия магазинов — из словаря (`shops`)
DOMAIN = re.compile(r'(?<![\w.])(?:www\.)?[\w-]+\.(?:ru|com|net|org|рф|su|shop|store)(?![\w])', re.I)
# размер: «120x80», «2-93x195», «d30», «h45»; с единицей, приклеенной в `clean` («10x10x34см», «30см»)
SIZE = re.compile(r'^((?:\d+(?:\.\d+)?-)?\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)+|[dhDH]\d+(?:\.\d+)?|\d+(?:\.\d+)?(?=см|мм))(см|мм)?$')
NUM = re.compile(r'^\d+(?:\.\d+)?$')
UNIT = {'см': 'cm', 'мм': 'mm'}


def load_dict(path: str = DICT_PATH) -> dict:
    return json.load(open(path, encoding='utf-8'))


def load_map(path: str = MAP_PATH) -> dict:
    try:
        m = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in m.items() if not k.startswith('_')}


def _shop_re(shops) -> re.Pattern:
    """Как `lib/configurator/label.ts:shopStripper`: домен целиком, без зоны или через пробел («divan.ru», «divan ru»)."""
    alts = set()
    for s in shops:
        s = s.strip().lower().removeprefix('www.')
        dot = s.rfind('.')
        alts.add(re.escape(s) if dot <= 0 else re.escape(s[:dot]) + r'(?:[.\s]?' + re.escape(s[dot + 1:]) + ')?')
    alts = sorted(alts, key=len, reverse=True)
    return re.compile(r'(?<![\w.])(?:www\.)?(?:' + '|'.join(alts) + r')(?![\w])', re.I)


def clean(name: str, shops_re: re.Pattern) -> str:
    """Убрать магазин, невидимые символы, латинскую «x» внутри русских слов («Ореx»), привести размеры к «120x80»."""
    s = unicodedata.normalize('NFC', str(name or '')).replace('\u200b', ' ').replace('\xa0', ' ').replace('\t', ' ')
    s = shops_re.sub(' ', DOMAIN.sub(' ', s))
    s = re.sub(r'(?<=[А-Яа-яЁё])[xX]', 'х', s)
    s = re.sub(r'(?<=\d)\s*[хХxX×*]\s*(?=\d)', 'x', s)
    s = re.sub(r'(?<=\d),(?=\d)', '.', s)
    s = re.sub(r'(?<=\d)\s*(см|мм)\.?(?![А-Яа-яЁё\w])', r'\1', s)
    return re.sub(r'\s+', ' ', s).strip()


def translit(word: str, table: dict) -> str:
    out = ''.join(table.get(ch.lower(), ch) if CYR.match(ch) else ch for ch in word)
    return '-'.join(p[:1].upper() + p[1:] for p in out.split('-'))


def neutral(role: str, D: dict) -> str:
    r = re.sub(r'\s+\d+$', '', str(role or ''))
    return D['roles'].get(r) or D['roles']['']


_SHOPS: dict = {}


def shops_re(D: dict) -> re.Pattern:
    if id(D) not in _SHOPS:
        _SHOPS.clear()
        _SHOPS[id(D)] = _shop_re(D['shops'])
    return _SHOPS[id(D)]


def translate(name: str, role: str = '', D: dict | None = None) -> dict:
    """Название по словарю. → {name, colour, how: 'dict'|'neutral', translit: [русские слова, ушедшие в транслитерацию]}."""
    D = D or load_dict()
    s = clean(name, shops_re(D))
    low = s.lower()
    # ТИП — самая ранняя и самая длинная фраза словаря (тип бывает и не первым: «Белла Кровать+ПМ», «Босс пуф»)
    best = None
    for ru, en in D['types'].items():
        for m in re.finditer(r'(?<![\w-])' + re.escape(ru) + r'(?![\w-])', low):
            cand = (m.start(), -len(ru), ru, en)
            best = cand if best is None or cand < best else best
            break
    type_en = ''
    if best:
        _, _, ru, type_en = best
        s = re.sub(r'(?<![\w-])' + re.escape(ru) + r'(?![\w-])', ' ', s, flags=re.I)   # и повтор в хвосте («… Латте Комод»)
    toks = re.findall(r'[^\s,/()+]+|[,/]', s)
    groups = [('colour', D['colours']), ('material', D['materials']), ('pattern', D['patterns']), ('model', D['models']),
              ('word', D['words'])]
    items, gone, i = [], [], 0
    while i < len(toks):
        t = toks[i]
        hit = None
        for n in (3, 2, 1):
            phrase = ' '.join(toks[i:i + n]).lower()
            for cat, table in groups:
                if phrase in table:
                    hit = (cat, table[phrase], n)
                    break
            if hit:
                break
        if hit:
            items.append((hit[0], hit[1]))
            i += hit[2]
            continue
        tl = t.lower()
        if t in ',/':
            items.append(('punct', t))
        elif SIZE.match(t):
            m = SIZE.match(t)
            items.append(('size', m.group(1) + (' ' + UNIT[m.group(2)] if m.group(2) else '')))
        elif '-' in t and all(x.lower() in D['colours'] for x in t.split('-')):
            items.append(('colour', '-'.join(D['colours'][x.lower()] for x in t.split('-'))))
        elif NUM.match(t):
            items.append(('num', t))
        elif CYR.search(t):
            gone.append(t)
            items.append(('model', translit(t, D['translit'])))
        else:
            items.append(('latin', t))
        i += 1
    # голова — до первого цвета/материала/рисунка или запятой; размеры (с единицами) — после типа
    cut = next((k for k, (c, _) in enumerate(items) if c in ('colour', 'material', 'pattern') or (c, _) == ('punct', ',')),
               len(items))
    head, tail, sizes = [], [], []
    for k, (c, v) in enumerate(items):
        if c == 'size':
            sizes.append(v)
            continue
        (head if k < cut else tail).append((c, v))
    if tail and tail[0] == ('punct', ','):
        tail = tail[1:]
    # «Рогожка Серый» → «grey woven fabric»: материал первым — уходит в конец (так пишет divan.ru); иначе порядок как был
    if tail and tail[0][0] == 'material' and any(c in ('colour', 'pattern') for c, _ in tail[1:]):
        k = next(j for j, (c, _) in enumerate(tail) if c != 'material')
        tail = tail[k:] + tail[:k]
    joined = lambda xs: re.sub(r'\s*/\s*', '/', re.sub(r'\s+,', ',', ' '.join(v for _, v in xs))).strip(' ,/')  # noqa: E731
    # «Glasar с ручками» → «Glasar vase with handles»: уточнение «с …» — после типа
    w = next((k for k, (c, v) in enumerate(head) if (c, v) == ('word', 'with')), len(head))
    head_s = ' '.join(x for x in [joined(head[:w]), type_en, joined(head[w:]), ' '.join(sizes)] if x).strip()
    tail_s = joined(tail)
    if not head_s:
        head_s, tail_s = tail_s, ''
    out = head_s + (', ' + tail_s if tail_s else '')
    out = out[:1].upper() + out[1:]
    if not out or bad(out, D):
        return {'name': neutral(role, D), 'colour': '', 'how': 'neutral', 'translit': gone}
    return {'name': out, 'colour': tail_s, 'how': 'dict', 'translit': gone}


def bad(s: str, D: dict) -> bool:
    """Ворота: кириллица, домен или название магазина в английском названии."""
    return bool(CYR.search(s) or DOMAIN.search(s) or shops_re(D).search(s))


def name_en(p: dict, role: str, M: dict, D: dict) -> dict:
    """Английское название товара: сперва ручной перевод (по `sid`, иначе по названию, если русское то же), потом словарь."""
    ru = p.get('name') or ''
    hit = M.get(p.get('sid') or '') or M.get(ru)
    if hit and hit.get('ru') == ru and hit.get('name') and not bad(hit['name'], D):
        return {'name': hit['name'], 'colour': hit.get('colour') or '', 'how': 'map', 'translit': []}
    return translate(ru, role, D)


def _walk(o, role, out):
    """Все товары данных (словарь с `name` и `price`) с ролью по месту: ленты `feeds[роль]`, `sofa_feed`, предметы вариантов
    (`role` предмета), комплекты `sets[].roles[роль]`, спальня `bedroom_catalog.roles[роль]`."""
    if isinstance(o, dict):
        if 'name' in o and 'price' in o:
            out.append((o, role))
        r = o.get('role') if isinstance(o.get('role'), str) else role
        for k, v in o.items():
            if k in ('feeds', 'roles') and isinstance(v, dict):
                for rk, rv in v.items():
                    _walk(rv, rk, out)
            elif k == 'sofa_feed':
                _walk(v, 'диван', out)
            elif isinstance(v, (dict, list)):
                _walk(v, r, out)
    elif isinstance(o, list):
        for x in o:
            _walk(x, role, out)


def products(data: dict) -> list:
    out: list = []
    _walk(data, '', out)
    return out


def annotate(data: dict, M: dict | None = None, D: dict | None = None) -> dict:
    """`name_en` и `colour_en` — каждому товару данных. → отчёт {map, dict, neutral, items, translit: Counter, neutral_names}."""
    D = D or load_dict()
    M = load_map() if M is None else M
    rep = {'map': 0, 'dict': 0, 'neutral': 0, 'items': 0, 'translit': Counter(), 'neutral_names': []}
    for p, role in products(data):
        r = name_en(p, role, M, D)
        p['name_en'] = r['name']
        p['colour_en'] = r['colour']
        rep[r['how']] += 1
        rep['items'] += 1
        rep['translit'].update(r['translit'])
        if r['how'] == 'neutral':
            rep['neutral_names'].append(p.get('name'))
    return rep


def report_lines(rep: dict) -> list:
    lines = [f"английские названия: товаров {rep['items']} — из перевода {rep['map']}, словарём {rep['dict']}, "
             f"нейтральных {rep['neutral']}"]
    if rep['translit']:
        lines.append('  в транслитерацию (топ-30): ' + ', '.join(f'{w} {n}' for w, n in rep['translit'].most_common(30)))
    for n in sorted(set(rep['neutral_names']))[:20]:
        lines.append(f'WARN:name_en_neutral: «{n}» — английского нет, показано нейтральное по роли')
    return lines


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
    data = json.load(open(path, encoding='utf-8'))
    for line in report_lines(annotate(data)):
        print(line)


if __name__ == '__main__':
    main()
