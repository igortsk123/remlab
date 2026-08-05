#!/usr/bin/env python3
"""Уровень 0 каскада: всё, что достаётся из текста БЕЗ модели и без единого рубля.

Модель нужна для суждения (какая это функция, подходит ли стиль), а не для чтения того, что и так
написано в названии: цвет, материал, форма, бренд, размеры. Чем больше вытянут регулярки, тем
короче промпт, дешевле прогон и надёжнее проверка — уровень 1 сверяется с уровнем 0, и расхождение
роли снижает итоговое качество записи.

  ~/venvs/scout/bin/python rules0.py            # замер покрытия по пулу гостиной
  ~/venvs/scout/bin/python rules0.py --sample 5 # показать разбор на примерах
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from style_tags import tag as style_tag  # noqa: E402

PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

COLOURS = {
    'белый': r'\bбел(ый|ая|ое|ые|о)\b|молочн|снежн|white',
    'бежевый': r'беж|крем|песочн|ваниль|латте|слонов',
    'серый': r'сер(ый|ая|ое|ые)\b|графит|антрацит|стальн|дымчат|мокко сер|галька',
    'чёрный': r'ч[её]рн|black|карбон|уголь',
    'коричневый': r'коричнев|шоколад|венге|орех|кофейн|капучино|терракот',
    'синий': r'син(ий|яя|ее|ие)|голуб|индиго|бирюз|blue|навы|деним',
    'зелёный': r'зел[её]н|олив|мятн|изумруд|хаки|фисташ',
    'жёлтый': r'ж[ёе]лт|горчичн|янтарн|золотист',
    'красный': r'красн|бордо|вишн|марсал|терракотов',
    'розовый': r'розов|пудров|фуксия|коралл',
    'фиолетовый': r'фиолет|лаванд|сирен|слив',
    'оранжевый': r'оранж|апельсин|манго|тыкв',
}
MATERIALS = {
    'велюр': r'велюр|микровелюр', 'рогожка': r'рогожк', 'шенилл': r'шенилл',
    'экокожа': r'экокож|кожзам|искусств\w* кожа', 'кожа': r'\bкож[аи]\b|натур\w* кожа',
    'ткань': r'ткан|текстиль|букле|жаккард|бархат|плюш',
    'дерево': r'массив|дерев|дуб|сосн|бук|берёз|ясен|орех',
    'ЛДСП': r'лдсп|дсп', 'МДФ': r'\bмдф\b',
    'металл': r'металл|сталь|хром|латун|железн|чугун',
    'стекло': r'стекл|glass', 'камень': r'мрамор|камен|гранит|оникс|травертин',
    'пластик': r'пластик|полипропилен|акрил', 'ротанг': r'ротанг|плет[ёе]н|лоза',
    'керамика': r'керамик|фарфор|фаянс',
}
SHAPES = {
    'круглая': r'кругл|round', 'овальная': r'овальн', 'квадратная': r'квадратн',
    'угловая': r'углов|corner', 'прямоугольная': r'прямоугольн',
}
FEATURES = {
    'раскладной': r'раскладн|разложен|еврокнижк|дельфин|аккордеон|тик-так|клик-кляк|трансформер',
    'с ящиком': r'ящик|бельев\w* короб|с хранением',
    'на колёсах': r'на колес|на колёс|колёсик|роликов',
}


def _find(text: str, table: dict) -> str | None:
    for name, rx in table.items():
        if re.search(rx, text):
            return name
    return None


def _find_all(text: str, table: dict) -> list[str]:
    return [name for name, rx in table.items() if re.search(rx, text)]


def extract(it: dict) -> dict:
    """Разбор карточки правилами. Всё, чего нет в тексте, остаётся None — не выдумываем."""
    name = (it.get('name') or '').lower()
    desc = (it.get('desc') or '').lower()[:600]
    params = {k.lower(): str(v).lower() for k, v in (it.get('params') or {}).items()}
    par_txt = ' '.join(f'{k} {v}' for k, v in params.items())
    both = f'{name} {par_txt}'
    st = style_tag(it.get('name') or '')

    w, d, h, dia = it.get('w'), it.get('d'), it.get('h'), it.get('dia')
    have = sum(1 for v in (w, d, h) if v)
    dims_quality = 'полные' if have == 3 else ('частичные' if have or dia else 'нет')
    # правдоподобие: диван шириной 12 см или высотой 4 м — это мусор фида, не товар
    sane = True
    for v in (w, d, h):
        if v and not (5 <= float(v) <= 400):
            sane = False

    brand = None
    m = re.match(r'^[А-ЯЁA-Z][\w-]*\s+([А-ЯЁA-Z][\w-]+)', it.get('name') or '')
    if m:
        brand = m.group(1)

    return {
        'role_feed': it.get('role_feed'),
        'primary_color': _find(both, COLOURS) or _find(desc, COLOURS),
        'materials': _find_all(both, MATERIALS) or _find_all(desc, MATERIALS),
        'shape': _find(both, SHAPES),
        'features': _find_all(f'{name} {desc}', FEATURES),
        'style_hint': st.get('style'),
        'wood': st.get('wood'), 'metal': st.get('metal'), 'fabric': st.get('fabric'),
        'brand_hint': brand,
        'dims_quality': dims_quality,
        'dims_sane': sane,
        'has_desc': bool(it.get('desc')),
        'name_generic': len((it.get('name') or '').split()) <= 2,
    }


def flags(r0: dict) -> list[str]:
    """Чего не хватает карточке — по этим флагам каскад решает, звать ли vision."""
    f = []
    if not r0['has_desc']:
        f.append('нет_описания')
    if r0['dims_quality'] != 'полные':
        f.append('размеры_неполные')
    if r0['name_generic']:
        f.append('название_общее')
    if not r0['dims_sane']:
        f.append('размеры_неправдоподобны')
    if not r0['primary_color']:
        f.append('цвет_не_определён')
    if not r0['materials']:
        f.append('материал_не_определён')
    return f or ['нет']


def _rows(q: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[:400])
        sys.exit(1)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]


def pool(limit: int = 0) -> list[dict]:
    """Пул гостиной: то, что вообще может попасть в комплект."""
    lim = f'limit {limit}' if limit else ''
    q = f"""
    select l.shop_mid, l.external_id, l.name, coalesce(p.description,''), l.category_path,
           coalesce(l.price_rub,0), coalesce(l.w_cm,0), coalesce(l.d_cm,0), coalesce(l.h_cm,0),
           coalesce(l.dia_cm,0), coalesce(p.params::text,'{{}}'), l.role, coalesce(l.image_url,'')
      from lr_roles l join products p using (shop_mid, external_id)
      left join product_enrichment e using (shop_mid, external_id)
     where l.role is not null and l.price_rub is not null
       and coalesce(e.status,'active')='active'
     order by l.shop_mid, l.external_id {lim}
    """
    out = []
    for r in _rows(q):
        out.append(dict(mid=int(r[0]), eid=r[1], name=r[2], desc=r[3][:900], cat=r[4],
                        price=int(r[5]), w=float(r[6]) or None, d=float(r[7]) or None,
                        h=float(r[8]) or None, dia=float(r[9]) or None,
                        params=json.loads(r[10]), role_feed=r[11], img=r[12]))
    return out


def main() -> None:
    n = int(sys.argv[sys.argv.index('--sample') + 1]) if '--sample' in sys.argv else 0
    items = pool(n or 0)
    if n:
        for it in items[:n]:
            r0 = extract(it)
            print(f'\n{it["name"][:70]}')
            print(f'  {json.dumps(r0, ensure_ascii=False)}')
            print(f'  флаги: {flags(r0)}')
        return
    cov = {'цвет': 0, 'материал': 0, 'форма': 0, 'стиль': 0, 'размеры полные': 0, 'описание': 0}
    need_vision = 0
    for it in items:
        r0 = extract(it)
        cov['цвет'] += bool(r0['primary_color'])
        cov['материал'] += bool(r0['materials'])
        cov['форма'] += bool(r0['shape'])
        cov['стиль'] += bool(r0['style_hint'])
        cov['размеры полные'] += r0['dims_quality'] == 'полные'
        cov['описание'] += r0['has_desc']
        if not r0['has_desc'] and r0['name_generic']:
            need_vision += 1
    total = len(items)
    print(f'пул гостиной: {total} товаров\n')
    for k, v in cov.items():
        print(f'  {k:16s} {v:6d}  {v / total * 100:5.1f}%')
    print(f'\nтребуют картинки (нет описания И общее название): {need_vision} '
          f'({need_vision / total * 100:.1f}%)')


if __name__ == '__main__':
    main()
