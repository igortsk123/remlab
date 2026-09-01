#!/usr/bin/env python3
"""СКОЛЬКО ПРЕДМЕТОВ В ОДНОЙ ПОКУПКЕ — разметка каталога (владелец 01.09).

Зачем. Стулья магазины продают комплектами: «Стул АСТИ 2 шт.», бывает 1, 2, 4 и 6. Расстановка
ставит в комнату несколько стульев, а мы покупаем ОДИН товар — и без числа штук смета считает
столько покупок, сколько мест за столом. Владелец: «мы моделим стул один, а их обычно больше
в группе, 2 или 4 бывает часто».

Почему отдельным проходом, а не полем в обогащении. Схема обогащения строгая (`golden_label.
SCHEMA`, `strict: true`), и любое новое поле обязано попасть в `required` → меняется
`SCHEMA_VERSION` → `enrich.todo()` считает необогащёнными ВСЕ 20 452 товара и гонит их заново.
Ради одного числа это неоправданно. Здесь тот же канал и тот же учёт денег, но вопрос один и
задаётся только тем ролям, где комплекты вообще бывают.

Порядок источников — от бесплатного к платному, дороже спрашиваем только то, что дешевле не
узнать:
  1. НАЗВАНИЕ («2 шт.», «комплект из 4») — даром, но покрывает мало: замер 01.09 по каталогу
     нашёл число лишь у 16 стульев из 906;
  2. ОПИСАНИЕ — ещё 23 из 906;
  3. ФОТО+НАЗВАНИЕ через модель — остальные ~96%. На карточке видно, что входит в поставку:
     два одинаковых стула на снимке это пара, а стул рядом с накрытым столом — всё ещё один.
  4. не удалось — 1 (безопасное значение: покажем и посчитаем одну штуку, а не выдуманные три).

Результат живёт в своей таблице `product_pack` со ССЫЛКОЙ НА ИСТОЧНИК: через месяц должно быть
видно, откуда взято число и чему верить. Прод и демо читают готовое значение — модели на проде нет.

  pack_qty.py --roles стул --limit 15 --dry-run   # пробная партия, ничего не пишем
  pack_qty.py --roles стул,табурет,пуф            # разметить (с дневным лимитом денег)
  pack_qty.py --report                            # что размечено и по каким источникам
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PSQL = ["docker", "exec", "-i", "remlab-devdb", "psql", "-U", "remlab", "-d", "remlab",
        "-q", "-v", "ON_ERROR_STOP=1", "-tAc"]
MODEL = 'gpt-5.6-luna'
PACK_MAX = 12
DEFAULT_ROLES = ('стул', 'табурет', 'пуф')

DDL = """
create table if not exists product_pack (
  shop_mid   integer not null,
  external_id text   not null,
  pack_qty   integer not null,
  src        text    not null,          -- name | desc | vision | default
  model      text,
  confidence text,
  why        text,
  checked_at timestamptz not null default now(),
  primary key (shop_mid, external_id)
);
"""

# «2 шт», «2шт», «комплект 4», «набор из 6», «пара». Число берём ТОЛЬКО рядом со словом-маркером:
# «Стул 45х52х95» иначе читался бы как 45 штук.
_RE_PCS = re.compile(r'(\d{1,2})\s*(?:шт|штук)', re.I)
_RE_SET = re.compile(r'(?:комплект|набор)\D{0,12}?(\d{1,2})', re.I)
_RE_PAIR = re.compile(r'\bпара\b', re.I)


# ОПИСАНИЕ ЧИТАЕМ СТРОЖЕ, ЧЕМ НАЗВАНИЕ (01.09). В названии «2 шт.» почти всегда про поставку.
# В описании — нет: первый же товар пробной партии дал «Стулья GENIUS можно ШТАБЕЛИРОВАТЬ ПО
# 5 ШТУК», и правило «любое число рядом со „шт“» записало ему комплект из пяти. Поэтому в
# описании число засчитывается только рядом со словом о ПОСТАВКЕ.
_RE_DESC = re.compile(
    r'(?:в\s+комплект\w*|в\s+набор\w*|в\s+упаковк\w*|в\s+поставк\w*|комплект\w*\s+из|'
    r'набор\w*\s+из)\D{0,15}(\d{1,2})', re.I)
_RE_DESC_BACK = re.compile(r'(\d{1,2})\s*(?:шт|штук)\w*\.?\s+в\s+(?:комплект|набор|упаковк|поставк)',
                           re.I)


def parse_pack(text: str | None, strict: bool = False) -> int | None:
    """Число штук из текста, либо None. Проверяемо селфтестом, без сети и без модели.

    `strict=True` — режим описания: число засчитывается только рядом со словом о поставке.
    """
    if not text:
        return None
    rules = (_RE_DESC, _RE_DESC_BACK) if strict else (_RE_PCS, _RE_SET)
    for rx in rules:
        m = rx.search(text)
        if m:
            n = int(m.group(1))
            if 1 <= n <= PACK_MAX:
                return n
    if strict:
        return None
    return 2 if _RE_PAIR.search(text) else None


def db(sql: str) -> list:
    r = subprocess.run(PSQL + [sql], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip('\n').split('\n') if ln]


def q(v) -> str:
    if v is None:
        return 'null'
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


VISION_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['pack_qty', 'confidence', 'why'],
    'properties': {
        'pack_qty': {'type': 'integer', 'minimum': 1, 'maximum': PACK_MAX,
                     'description': 'сколько ОДИНАКОВЫХ предметов входит в эту покупку'},
        'confidence': {'type': 'string', 'enum': ['высокая', 'средняя', 'низкая']},
        'why': {'type': 'string', 'description': 'коротко: по чему решил'},
    },
}
SYS = ('Ты размечаешь карточки мебели российских магазинов. Отвечай строго по схеме.')
ASK = ('Сколько ОДИНАКОВЫХ предметов входит в ОДНУ покупку этого товара?\n'
       '- Считай только сам товар. Стол, посуда, ковёр и прочая обстановка на фото в счёт '
       'НЕ идут — их продают отдельно.\n'
       '- Если на фото один предмет показан с разных сторон или в разных цветах — это ОДИН '
       'предмет, а не комплект.\n'
       '- Если в названии или на фото прямо сказано «2 шт.», «комплект из 4» — бери это число.\n'
       '- Сомневаешься — ставь 1 и confidence «низкая».')


def ask_vision(name: str, img_url: str) -> dict | None:
    from golden_label import _image_b64
    from llm_gateway import chat
    from openai_budget import log_spend
    b64 = _image_b64(img_url) if img_url else None
    content = [{'type': 'text', 'text': f'{ASK}\n\nНазвание товара: {name}'}]
    if b64:
        content.append({'type': 'image_url',
                        'image_url': {'url': f'data:image/jpeg;base64,{b64}', 'detail': 'low'}})
    try:
        r = chat(MODEL, [{'role': 'system', 'content': SYS},
                         {'role': 'user', 'content': content}],
                 response_format={'type': 'json_schema',
                                  'json_schema': {'name': 'pack', 'strict': True,
                                                  'schema': VISION_SCHEMA}},
                 reasoning_effort='low')
        log_spend(MODEL, r.get('usage'), 1, 'pack_qty+vision')
        msg = r['choices'][0]['message']
        if msg.get('refusal'):
            return None
        return json.loads(msg['content'])
    except Exception as e:  # noqa: BLE001 — один товар не должен ронять проход
        print(f'    модель не ответила: {type(e).__name__}: {str(e)[:80]}', flush=True)
        return None


def candidates(roles: tuple, limit: int, redo: bool) -> list:
    where_role = ','.join(q(r) for r in roles)
    skip = '' if redo else 'and pk.shop_mid is null'
    rows = db(f"""
    select p.shop_mid||'\x1f'||p.external_id||'\x1f'||p.name||'\x1f'
           ||coalesce(p.image_url_hd, p.image_url, '')||'\x1f'||coalesce(left(p.description,600),'')
      from products p
      join product_enrichment e on e.shop_mid=p.shop_mid and e.external_id=p.external_id
      left join product_pack pk on pk.shop_mid=p.shop_mid and pk.external_id=p.external_id
     where coalesce(e.payload->'rules'->>'role_feed','') in ({where_role})
       and coalesce(p.status,'active')='active' {skip}
     order by p.shop_mid, p.external_id
     limit {int(limit)};""")
    return [{'mid': int(r[0]), 'eid': r[1], 'name': r[2], 'img': r[3], 'desc': r[4]}
            for r in rows if len(r) >= 5]


def save(rows: list) -> None:
    if not rows:
        return
    vals = ','.join(f"({r['mid']}, {q(r['eid'])}, {r['pack']}, {q(r['src'])}, {q(r.get('model'))},"
                    f" {q(r.get('confidence'))}, {q((r.get('why') or '')[:200])}, now())"
                    for r in rows)
    db('insert into product_pack (shop_mid, external_id, pack_qty, src, model, confidence, why,'
       ' checked_at) values ' + vals +
       ' on conflict (shop_mid, external_id) do update set pack_qty=excluded.pack_qty,'
       ' src=excluded.src, model=excluded.model, confidence=excluded.confidence,'
       ' why=excluded.why, checked_at=now();')


_CACHE: dict | None = None


def lookup() -> dict:
    """(mid, eid) → сколько штук в покупке. Читают сборка демо и смета; модели тут нет.

    Кэш на процесс: таблица маленькая (тысячи строк), а спрашивают её на каждый слот.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    # ДВА ИСТОЧНИКА, ОДИН ОТВЕТ. Новые товары получают число в ОБЩЕМ запросе обогащения
    # (`golden_label.SCHEMA.pack_qty`) — это бесплатно, за карточку платим один раз. Старые,
    # обогащённые до 01.09, добираются разовой разметкой в `product_pack`. Приоритет у
    # обогащения: оно свежее и видит фото вместе с остальными признаками.
    out = {}
    try:
        for r in db("select shop_mid::text||'\x1f'||external_id||'\x1f'||pack_qty::text"
                    ' from product_pack'):
            if len(r) >= 3:
                out[(int(r[0]), r[1])] = int(r[2])
    except Exception:  # noqa: BLE001 — таблицы ещё нет: работаем без разметки
        pass
    try:
        for r in db("select shop_mid::text||'\x1f'||external_id||'\x1f'"
                    "||(payload->'model'->>'pack_qty')"
                    " from product_enrichment where payload->'model'->>'pack_qty' is not null"):
            if len(r) >= 3 and r[2]:
                n = int(r[2])
                if 1 <= n <= PACK_MAX:
                    out[(int(r[0]), r[1])] = n
    except Exception:  # noqa: BLE001 — поля ещё нет ни у кого: остаётся разметка
        pass
    _CACHE = out
    return out


def pack_of(mid, eid, name: str | None = None) -> int:
    """Штук в покупке: сначала разметка каталога, потом название, иначе 1."""
    n = lookup().get((int(mid), str(eid))) if mid and eid else None
    return n or parse_pack(name) or 1


def report() -> None:
    for ln in db("select src||'\x1f'||pack_qty::text||'\x1f'||count(*)::text"
                 ' from product_pack group by src, pack_qty order by src, pack_qty'):
        print(f'  {ln[0]:<8} {ln[1]} шт → {ln[2]} товаров')
    tot = db('select count(*)::text from product_pack')
    print(f'  всего размечено: {tot[0][0] if tot else 0}')


def selftest() -> int:
    cases = [('Стул АСТИ 2 шт. Велюр', 2), ('Стулья 4 шт', 4), ('Комплект из 6 стульев', 6),
             ('Набор 4 стула', 4), ('Пара стульев Лофт', 2), ('Стул Лофт 45х52х95', None),
             ('Стул обеденный', None), ('Стул 100 шт', None), (None, None)]
    # описание: засчитываем только поставку, а не любое число рядом со «шт»
    desc_cases = [('В комплекте 4 стула', 4), ('В упаковке 2 шт.', 2),
                  ('6 шт. в комплекте', 6), ('комплект из 4 предметов', 4),
                  ('Стулья можно штабелировать по 5 штук', None),   # ловушка из прода 01.09
                  ('Выдерживает до 5 штук сверху', None),
                  ('Доставим за 3 дня', None), ('Пара — это про обувь', None)]
    bad = 0
    for text, want in cases:
        got = parse_pack(text)
        if got != want:
            bad += 1
            print(f'  FAIL название {text!r}: получили {got}, ждали {want}')
    for text, want in desc_cases:
        got = parse_pack(text, strict=True)
        if got != want:
            bad += 1
            print(f'  FAIL описание {text!r}: получили {got}, ждали {want}')
    print(f'pack_qty selftest: случаев {len(cases) + len(desc_cases)}, ошибок {bad}')
    return 1 if bad else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return selftest()
    db(DDL)
    if '--report' in sys.argv:
        report()
        return 0
    roles = tuple((sys.argv[sys.argv.index('--roles') + 1]).split(',')) \
        if '--roles' in sys.argv else DEFAULT_ROLES
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 2000
    dry = '--dry-run' in sys.argv
    redo = '--redo' in sys.argv
    items = candidates(roles, limit, redo)
    print(f'к разметке: {len(items)} (роли: {", ".join(roles)})', flush=True)
    if not items:
        return 0
    out, need_vision = [], []
    for it in items:
        n = parse_pack(it['name'])
        if n:
            out.append({**it, 'pack': n, 'src': 'name'})
            continue
        n = parse_pack(it['desc'], strict=True)
        if n:
            out.append({**it, 'pack': n, 'src': 'desc'})
            continue
        need_vision.append(it)
    print(f'  из названия: {sum(1 for r in out if r["src"] == "name")}; '
          f'из описания: {sum(1 for r in out if r["src"] == "desc")}; '
          f'останется модели: {len(need_vision)}', flush=True)
    if need_vision and not dry:
        from openai_budget import allow
        if not allow(MODEL, len(need_vision), note='pack_qty'):
            print('дневной лимит не пускает — разметку по фото отложил', flush=True)
            need_vision = []
    # ПИШЕМ ПАЧКАМИ, А НЕ В КОНЦЕ. Проход по 900 карточкам — это ~45 минут сетевых вызовов;
    # одна запись в самом конце означала бы, что обрыв стирает всю ОПЛАЧЕННУЮ работу.
    save(out)
    out, batch = [], []
    for i, it in enumerate(need_vision, 1):
        if dry:
            break
        r = ask_vision(it['name'], it['img'])
        if not r:
            batch.append({**it, 'pack': 1, 'src': 'default'})
        else:
            batch.append({**it, 'pack': int(r['pack_qty']), 'src': 'vision', 'model': MODEL,
                          'confidence': r.get('confidence'), 'why': r.get('why')})
        if len(batch) >= 25:
            save(batch); out += batch; batch = []
            print(f'    по фото {i}/{len(need_vision)} (записано {len(out)})', flush=True)
    if batch:
        save(batch); out += batch
    if dry:
        print('\n--dry-run: в базу не пишу. Что дал бесплатный разбор:')
        for r in out[:40]:
            print(f"    {r['pack']} шт [{r['src']}]  {r['name'][:60]}")
        return 0
    print(f'записано за прогон: {len(out)}', flush=True)
    report()
    return 0


if __name__ == '__main__':
    sys.exit(main())
