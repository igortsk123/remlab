#!/usr/bin/env python3
"""Проба обогащения карточек СПАЛЬНИ (план onb-06 Т2): что даёт модель по тексту и фото сверх фида и названия.

ЗАЧЕМ. Отбор спальни (Т3) решает по материалу, цвету, хранению (ящики, подъёмный механизм) и изголовью. «Без обогащения» —
то, что даром достаётся из параметров фида и названия (правила ниже); «с обогащением» — ответ gpt-6-luna по тому же тексту
плюс фото товара (низкое разрешение). Сравнение на одних и тех же карточках: заполненность поля без/с, согласие там, где
известно обоим, и случаи, где ответ модели меняет решение отбора. Решение «обогащать ли всё» — ведущий, после второго
мнения; этот скрипт в базу НЕ пишет.

  ~/venvs/scout/bin/python bedroom_enrich.py --probe 50 --dry    # выборка и прикидка цены, без LLM
  ~/venvs/scout/bin/python bedroom_enrich.py --probe 50          # проба: гейт openai_budget, учёт трат, счётчик отказов
  ~/venvs/scout/bin/python bedroom_enrich.py --recount <папка>   # пересчёт «без» по новым правилам на тех же ответах, бесплатно
  python3 bedroom_enrich.py --selftest                           # правила «без обогащения», без сети и базы
Выход — новая папка ~/remlab-logs/onb06-enrich-probe-<ММДД-ЧЧММ>/ (probe.jsonl, report.md, sheet.html).
"""
import concurrent.futures as cf
import html
import json
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
MODEL = os.environ.get('ENRICH_MODEL', 'gpt-6-luna')
ROLES = {'кровать': 20, 'тумба прикроватная': 10, 'шкаф': 10, 'комод': 10}
FIELDS = ['material', 'upholstery', 'colour', 'drawers', 'lift', 'headboard', 'headboard_soft']
UNK = 'неизвестно'
NA = 'не_применимо'

MATERIALS = ['массив', 'шпон', 'плита', 'металл', 'ротанг', 'ткань', 'экокожа']
# порядок — от явного к общему: «массив» сказан прямо; плита в смеси («Труба стальная, ДСП», «Дерево, МДФ») — корпус из плиты
_MAT = [('массив', r'массив|натуральн\w* дерев'), ('шпон', r'шпон'), ('плита', r'лдсп|мдф|дсп|хдф|двп|плит|фанер|мебельн\w* щит'),
        ('металл', r'металл|стал[ьи]|труба'), ('ротанг', r'ротанг'), ('массив', r'\bдерево\b|сосн|берёз|берез|\bбук\b'),
        ('экокожа', r'экокож|кожзам|искусств\w* кож'), ('ткань', r'ткан|велюр|рогожк|букле|шенилл|вельвет|бархат|мех')]
# группы палитры: решение отбора меняет только смена группы («Древесный тёмный»: коричневый ↔ дерево тёмное — одно и то же)
PALETTE = {'белый': 'светлый', 'бежевый': 'светлый', 'серый': 'серый', 'чёрный': 'тёмный', 'дерево светлое': 'дерево светлое',
           'дерево тёмное': 'коричневый', 'коричневый': 'коричневый', 'зелёный': 'акцент', 'синий': 'акцент', 'розовый': 'акцент',
           'жёлтый': 'акцент', 'красный': 'акцент', 'многоцвет': 'многоцвет', 'серо-зелёный': 'серо-зелёный'}
COLOURS = ['белый', 'бежевый', 'серый', 'чёрный', 'дерево светлое', 'дерево тёмное', 'зелёный', 'синий', 'розовый', 'жёлтый',
           'красный', 'коричневый', 'многоцвет']
# составные первыми: «Серо-зеленый» — не серый и не зелёный, а свой (эталон 30, №26/29: фото «серый», фид «Зеленый» — оба правы);
# «Графитовый» — тёмно-серый (на фото и в фиде серый, №27/28); «Розетта» — декор дерева, не розовый (№17/30)
_COL = [('серо-зелёный', r'серо-?зел|зел[её]но-?сер|шалфе'),
        ('бежевый', r'беж|латте|кашемир|крем|молочн|песочн|капучино|шампань|слонов|ванил|айвори|ivory'),
        ('белый', r'бел'), ('чёрный', r'ч[её]рн|антрацит|венге'), ('серый', r'сер|графит|сталь|агат|платин'),
        ('дерево тёмное', r'орех|т[её]мн\w* дуб|древесн\w* т[её]мн|палисандр|махагон'),
        ('дерево светлое', r'дуб|сосн|берёз|берез|ясень|бук|натуральн|древесн|сонома|клён|клен'),
        ('зелёный', r'зел[её]н|олив|изумруд|мятн|шалфе|хаки'), ('синий', r'син|голуб|аква|бирюз|индиго|navy'),
        ('розовый', r'розов|пудр|лаванд|сирен|фиолет'), ('жёлтый', r'ж[её]лт|горчичн|охр'),
        ('красный', r'красн|бордо|терракот|кирпичн|коралл'), ('коричневый', r'коричн|шоколад|мокко|какао|карамел|корица')]


def _first(P: dict, pat: str) -> str:
    for k, v in (P or {}).items():
        if re.search(pat, k, re.I) and v:
            return str(v)
    return ''


def _cls(txt: str, table: list) -> str:
    for c, rx in table:
        if re.search(rx, txt or '', re.I):
            return c
    return UNK


def _cm(s: str):
    m = re.search(r'(\d{2,3})(?:[.,]\d+)?', s or '')
    return float(m.group(1)) if m else None


def head_class(h) -> str:
    if h is None:
        return UNK
    return 'низкое' if h < 95 else 'среднее' if h <= 120 else 'высокое'


def name_tail_colour(name: str) -> str:
    """Цвет ЭТОГО предложения — в хвосте названия («… Кейт 160 Букле Серый»). «Латте/Черный», «Дуб Барбера/Черный» — основной
    цвет первым (как в опросе: первая часть — главная), вторая часть — отделка или ножки."""
    tail = ' '.join(re.sub(r'[()]', ' ', name or '').split()[-3:])
    return _cls(tail.split('/')[0], _COL)


def rules_fields(role: str, name: str, P: dict) -> dict:
    """«Без обогащения»: поля из параметров фида и названия. Варианты в одном поле («без механизма с механизмом»,
    «95 см 110 см 130 см») — неизвестно: магазин перечисляет все исполнения модели, а не это предложение. Чистая функция."""
    nm = name or ''
    bed = role == 'кровать'
    mat_txt = ' '.join(_first(P, p) for p in (r'^Материал корпуса$', r'^Материал каркаса$', r'^Основной материал$', r'^Материал$'))
    # у кровати «Материал корпуса» — смесь ДВП/ткань/фанера: ткань там про обивку, каркас — плита
    m = _cls(re.sub(r'ткан\w*|ппу|микровелюр', ' ', mat_txt, flags=re.I) if bed else mat_txt, _MAT)
    if m == UNK:          # у шкафов МногоМебели/DIVANBOSS корпуса нет — только фасад
        m = _cls(_first(P, r'^Материал фасада$'), _MAT)
    uph_txt = _first(P, r'^Материал обивки$|^Обивка')
    soft = [(c, rx) for c, rx in _MAT if c in ('экокожа', 'ткань')]
    up = _cls(uph_txt, soft) if uph_txt and not re.search(r'лдсп|мдф', uph_txt, re.I) else _cls(nm, soft)
    if not bed:
        up = NA
    # цвет ЭТОГО предложения — в хвосте названия («… Кейт 160 Букле Серый»); «Цвет основной» divan.ru перечисляет исполнения
    # модели («Белый Бежевый»), поэтому он — запасной, как и цвет фасада
    col = name_tail_colour(nm)
    for p in (r'^Цвет шкафа: Цвет фасада$', r'^Цвет$|^Цвет основной$|^Цвет каркаса$|^Цвет корпуса$'):
        if col == UNK:
            col = _cls(_first(P, p), _COL)
    # хранение; «без ПМ» в названии — общее поле МногоМебели «Бельевой ящик и подъемный механизм: Да» не про это предложение
    no_pm = bool(re.search(r'без (пм|подъ[её]мн)', nm, re.I))
    if role == 'комод':
        dr = 'есть'
    else:
        v = ' '.join(_first(P, p) for p in (r'Наличие ящика для белья', r'^Ящик для белья$', r'^Количество ящиков$', r'^Выдвижной ящик$')
                     + (() if no_pm else (r'Бельевой ящик и подъемный',)))
        n = _cm(_first(P, r'^Количество ящиков$'))
        if re.search(r'без ящика', v) and re.search(r'с ящиком|\d ящик', v):
            dr = UNK
        elif (re.search(r'с ящиком|^да\b|\bда\b', v, re.I) or (n and n > 0) or re.search(r'ящик', nm, re.I)
              or _first(P, r'нагрузка на ящик|Цвет дна ящиков')):
            dr = 'есть'
        elif re.search(r'без ящика|\bнет\b', v, re.I) or n == 0:
            dr = 'нет'
        else:
            dr = UNK
    if bed:
        v = _first(P, r'^Подъемный механизм$') + ' ' + _first(P, r'Бельевой ящик и подъемный')
        if no_pm:
            lift = 'нет'
        elif re.search(r'без механизма', v) and re.search(r'(?<!без )с механизмом', v):
            lift = UNK
        elif re.search(r'(?<!без )с механизмом|\bда\b', v, re.I) or re.search(r'подъ[её]мн|\bпм\b', nm, re.I):
            lift = 'есть'
        elif re.search(r'без механизма|\bнет\b', v, re.I):
            lift = 'нет'
        else:
            lift = UNK
        hh = _first(P, r'^Высота изголовья$')
        if len(re.findall(r'\d{2,3}', hh)) > 1:
            hd = UNK
        else:
            hd = head_class(_cm(hh) or _cm(_first(P, r'^Размеры: Высота габаритная$|^Высота$')))
        hm = _first(P, r'^Материал изголовья$')
        hs = 'мягкое' if re.search(r'ткан', hm, re.I) else 'твёрдое' if hm else ('мягкое' if up in ('ткань', 'экокожа') else UNK)
    else:
        lift, hd, hs = NA, NA, NA
    return {'material': m, 'upholstery': up, 'colour': col, 'drawers': dr, 'lift': lift, 'headboard': hd, 'headboard_soft': hs}


def _enum(vals):
    return {'type': 'string', 'enum': vals}


SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': FIELDS + ['evidence'], 'properties': {
    'material': _enum(MATERIALS + [UNK]), 'upholstery': _enum(['ткань', 'экокожа', 'нет', UNK, NA]),
    'colour': _enum(COLOURS + [UNK]), 'drawers': _enum(['есть', 'нет', UNK]), 'lift': _enum(['есть', 'нет', UNK, NA]),
    'headboard': _enum(['нет', 'низкое', 'среднее', 'высокое', UNK, NA]),
    'headboard_soft': _enum(['мягкое', 'твёрдое', UNK, NA]),
    'evidence': {'type': 'object', 'additionalProperties': False, 'required': FIELDS,
                 'properties': {f: _enum(['текст', 'фото', 'нет']) for f in FIELDS}}}}

SYS = ('Ты размечаешь карточку мебели для спальни. Отвечай ТОЛЬКО по схеме JSON.\n'
       '1. material — основной материал корпуса/каркаса (не обивки): массив дерева, шпон, плита (ЛДСП/МДФ/ДСП), металл, '
       'ротанг; ткань/экокожа — только если каркас целиком обтянут и материала под ним не видно.\n'
       '2. upholstery — обивка кровати; у тумбы, шкафа, комода — не_применимо.\n'
       '3. colour — основной видимый цвет предмета. Дерево по цвету: светлое (дуб, сосна, берёза) или тёмное (орех, венге).\n'
       '4. drawers — есть ли ящики (у кровати — бельевой ящик), lift — подъёмный механизм кровати; у не-кроватей lift и '
       'headboard — не_применимо.\n'
       '5. headboard — высота изголовья над матрасом по фото/тексту: нет, низкое (до ~95 см от пола), среднее (95–120), '
       'высокое (>120); headboard_soft — мягкое (обито тканью/экокожей) или твёрдое.\n'
       '6. Не выдумывай: если из текста и фото не понять — «неизвестно». Если магазин перечисляет несколько исполнений '
       '(«без механизма с механизмом»), а по фото не видно — «неизвестно».\n'
       '7. evidence — откуда каждое значение: текст, фото или нет (неизвестно).')


def prompt(it: dict) -> str:
    P = {k: v for k, v in (it['params'] or {}).items() if re.search(r'материал|цвет|ящик|механизм|изголов|высот|обивк|стиль|тип', k, re.I)}
    return (f'Роль: {it["role"]}\nНазвание: {it["name"]}\nРазмеры, см: Ш{it["w"] or "?"} × Г{it["d"] or "?"} × В{it["h"] or "?"}\n'
            f'Параметры фида: {json.dumps(P, ensure_ascii=False)[:1500]}')


def ask(it: dict) -> dict:
    """Один вызов: текст + фото (low). → {'fields': {...}, 'img': bool} или {'err': ...}; учёт трат — openai_budget."""
    from golden_label import _image_b64
    from llm_gateway import chat
    from openai_budget import log_spend
    b64 = _image_b64(it['img']) if it['img'] else None
    content = [{'type': 'text', 'text': prompt(it)}] + (
        [{'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}', 'detail': 'low'}}] if b64 else [])
    try:
        out = chat(MODEL, [{'role': 'system', 'content': SYS}, {'role': 'user', 'content': content}], reasoning_effort='low',
                   response_format={'type': 'json_schema', 'json_schema': {'name': 'bedroom_card', 'strict': True, 'schema': SCHEMA}})
    except Exception as e:  # noqa: BLE001 — отказ считаем и показываем, не глотаем
        return {'err': f'{type(e).__name__}: {str(e)[:120]}', 'img': bool(b64)}
    log_spend(MODEL, out.get('usage'), 1, 'bedroom_enrich probe')
    try:
        return {'fields': json.loads(out['choices'][0]['message']['content']), 'img': bool(b64), 'usage': out.get('usage')}
    except (KeyError, ValueError) as e:
        return {'err': f'ответ не JSON: {str(e)[:80]}', 'img': bool(b64)}


def sample(n_total: int, seed: int = 50) -> list:
    """Показываемые товары спальни (условия показа демо, без детского, со сторожем роли), по одной на модель; роли — по
    ROLES (масштаб под n_total), внутри роли магазины по кругу — бедные фиды в выборке, а не только divan.ru."""
    import room_catalog as RC
    R = RC.rules()
    rows = RC.sql(f"select role, shop_mid, external_id, shop, name, params::text, coalesce(image_url_hd, image_url), url, "
                  f"w_cm, d_cm, h_cm from room_catalog where {RC.shown_where(R)} and role in ("
                  + ','.join(RC._lit(r) for r in ROLES) + ") order by shop_mid, external_id")
    f = lambda x: float(x) if x else None  # noqa: E731
    fam = {}
    for r in rows:
        d = {'w': f(r[8]), 'd': f(r[9]), 'h': f(r[10])}
        if RC.child_only(r[0], r[4], R) or RC.role_guard(r[0], r[4], d, R):
            continue
        fam.setdefault((r[0], r[3], RC.family(r[4])), dict(role=r[0], mid=int(r[1]), eid=r[2], shop=r[3], name=r[4],
                                                            params=json.loads(r[5] or '{}'), img=r[6], url=r[7], **d))
    rnd = random.Random(seed)
    scale = n_total / sum(ROLES.values())
    out = []
    for role, n in ROLES.items():
        by: dict = {}
        for it in sorted(fam.values(), key=lambda x: (x['shop'], x['name'])):
            if it['role'] == role:
                by.setdefault(it['shop'], []).append(it)
        for v in by.values():
            rnd.shuffle(v)
        got, k = [], round(n * scale)
        while len(got) < k and any(by.values()):
            for sh in sorted(by):
                if by[sh] and len(got) < k:
                    got.append(by[sh].pop())
        out += got
    return out, len(rows), len(fam)


def changed(role: str, a: dict, b: dict) -> list:
    """Поля, где обогащение меняет решение отбора: было неизвестно → стало известно, или модель спорит с фидом.
    Ящики комода — по определению, не решение."""
    out = []
    for f in FIELDS:
        x, y = a[f], b.get(f, UNK)
        if x == NA or (f == 'drawers' and role == 'комод'):
            continue
        if x == UNK and y not in (UNK, NA):
            out.append((f, 'заполнено', x, y))
        elif x != UNK and y not in (UNK, NA) and x != y and (f != 'colour' or PALETTE.get(x) != PALETTE.get(y)):
            out.append((f, 'спор', x, y))
    return out


def recount(L: str) -> int:
    """Пересчёт пробы по сохранённым ответам модели (без LLM и без денег): «без» — по текущим правилам и параметрам из
    базы. Нужен, когда правила «без обогащения» поправили, — сравнение честное, а модель не оплачиваем второй раз."""
    import room_catalog as RC
    recs = [json.loads(ln) for ln in open(os.path.join(L, 'probe.jsonl'), encoding='utf-8')]
    for r in recs:
        P = RC.sql(f"select params::text from room_catalog where shop_mid={int(r['mid'])} and external_id={RC._lit(r['eid'])} "
                   f"and room='{RC.ROOM}'")
        r['without'] = rules_fields(r['role'], r['name'], json.loads(P[0][0]) if P else {})
        r['changed'] = changed(r['role'], r['without'], r['llm']) if r['llm'] else []
    meta = json.load(open(os.path.join(L, 'meta.json'), encoding='utf-8'))
    out = L + '-recount-' + time.strftime('%H%M%S')
    os.makedirs(out, exist_ok=False)
    with open(os.path.join(out, 'probe.jsonl'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(json.dumps(r, ensure_ascii=False) for r in recs))
    rep = report(recs, meta['fails'], meta['pt'], meta['ct'], meta['cost'], meta['n_rows'], meta['n_fam'])
    open(os.path.join(out, 'report.md'), 'w', encoding='utf-8').write(rep)
    sheet(recs, out)
    print(rep, flush=True)
    print('папка:', out, flush=True)
    return 0


def run(n: int, dry: bool) -> int:
    from openai_budget import allow, estimate_request
    items, n_rows, n_fam = sample(n)
    print(f'выборка {len(items)} карточек (по одной на модель) из {n_fam} моделей / {n_rows} показываемых офферов', flush=True)
    print('по ролям:', {r: sum(1 for x in items if x['role'] == r) for r in ROLES},
          '· по магазинам:', {s: sum(1 for x in items if x['shop'] == s) for s in sorted({x['shop'] for x in items})}, flush=True)
    est = estimate_request(MODEL)
    print(f'прикидка: проба {len(items)} запр. {MODEL} ≈ ${len(items) * est:.3f}; всё — {n_rows} офферов ≈ ${n_rows * est:.2f}, '
          f'{n_fam} моделей ≈ ${n_fam * est:.2f} (типовые токены rules/openai_prices.json — с запасом)', flush=True)
    if dry:
        return 0
    if not allow(MODEL, len(items), note=f'bedroom_enrich probe {len(items)}'):
        print('СТОП: дневной лимит OpenAI — проба не отправлена', flush=True)
        return 2
    L = os.path.expanduser('~/remlab-logs/onb06-enrich-probe-' + time.strftime('%m%d-%H%M'))
    os.makedirs(L, exist_ok=False)
    with cf.ThreadPoolExecutor(6) as ex:
        got = list(ex.map(ask, items))
    fails = [(it['name'], g['err']) for it, g in zip(items, got) if 'err' in g]
    tok = [g['usage'] for g in got if g.get('usage')]
    pt, ct = sum(u.get('prompt_tokens', 0) for u in tok), sum(u.get('completion_tokens', 0) for u in tok)
    from openai_budget import price_of
    cost = price_of(MODEL, pt, ct) or 0.0
    recs = []
    for it, g in zip(items, got):
        a = rules_fields(it['role'], it['name'], it['params'])
        b = g.get('fields') or {}
        recs.append({**{k: it[k] for k in ('role', 'shop', 'mid', 'eid', 'name', 'img', 'url', 'w', 'd', 'h')}, 'without': a,
                     'llm': b, 'photo_sent': g.get('img'), 'err': g.get('err'), 'changed': changed(it['role'], a, b) if b else []})
    with open(os.path.join(L, 'probe.jsonl'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(json.dumps(r, ensure_ascii=False) for r in recs))
    json.dump({'fails': fails, 'pt': pt, 'ct': ct, 'cost': cost, 'n_rows': n_rows, 'n_fam': n_fam},
              open(os.path.join(L, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    rep = report(recs, fails, pt, ct, cost, n_rows, n_fam)
    open(os.path.join(L, 'report.md'), 'w', encoding='utf-8').write(rep)
    sheet(recs, L)
    print(rep, flush=True)
    print('папка:', L, flush=True)
    return 0 if not fails else 1


def report(recs: list, fails: list, pt: int, ct: int, cost: float, n_rows: int, n_fam: int) -> str:
    ok = [r for r in recs if r['llm']]
    lines = [f'# onb-06 Т2 — проба обогащения {len(recs)} карточек спальни', '',
             f'Модель {MODEL}, текст + фото (low). Ответов {len(ok)}, отказов {len(fails)}, фото ушло {sum(1 for r in recs if r["photo_sent"])}.',
             f'Токены: вход {pt}, выход {ct}; цена пробы ${cost:.4f} (${cost / max(1, len(ok)):.5f} на карточку).',
             f'Прикидка на всё по факту пробы: {n_rows} офферов ≈ ${cost / max(1, len(ok)) * n_rows:.2f}, '
             f'{n_fam} моделей ≈ ${cost / max(1, len(ok)) * n_fam:.2f}.', '',
             '| поле | карточек с полем | без (фид+название) | с обогащением (без ∪ модель) | только модель | согласие где известно обоим |',
             '|---|---|---|---|---|---|']
    for f in FIELDS:
        rel = [r for r in ok if r['without'][f] != NA and not (f == 'drawers' and r['role'] == 'комод')]
        a = sum(1 for r in rel if r['without'][f] != UNK)
        m = sum(1 for r in rel if r['llm'].get(f) not in (UNK, NA, None))
        u = sum(1 for r in rel if r['without'][f] != UNK or r['llm'].get(f) not in (UNK, NA, None))
        both = [r for r in rel if r['without'][f] != UNK and r['llm'].get(f) not in (UNK, NA, None)]
        agree = sum(1 for r in both if r['without'][f] == r['llm'][f])
        lines.append(f'| {f} | {len(rel)} | {a} ({a * 100 // max(1, len(rel))} %) | {u} ({u * 100 // max(1, len(rel))} %) | {m} | '
                     f'{agree}/{len(both)} |')
    ev = {}
    for r in ok:
        for f, e in (r['llm'].get('evidence') or {}).items():
            ev.setdefault(f, {}).setdefault(e, 0)
            ev[f][e] += 1
    lines += ['', 'Откуда модель взяла значение (evidence): ' + '; '.join(f'{f}: {v}' for f, v in ev.items()), '',
              f'Карточек, где обогащение меняет решение: {sum(1 for r in ok if r["changed"])} из {len(ok)}', '']
    for r in [r for r in ok if r['changed']][:40]:
        lines.append(f'- [{r["role"]} · {r["shop"]}] {r["name"]}: ' + '; '.join(f'{f} {k}: {x} → {y}' for f, k, x, y in r['changed']))
    if fails:
        lines += ['', 'Отказы:'] + [f'- {n}: {e}' for n, e in fails]
    return '\n'.join(lines) + '\n'


def sheet(recs: list, L: str) -> None:
    from golden_label import _image_b64
    import base64
    os.makedirs(os.path.join(L, 'img'), exist_ok=True)
    cards = []
    for i, r in enumerate(recs, 1):
        src = ''
        b = _image_b64(r['img']) if r['img'] else None
        if b:
            fn = f'{i:02d}.jpg'
            open(os.path.join(L, 'img', fn), 'wb').write(base64.b64decode(b))
            src = f'img/{fn}'
        rows = ''.join(f'<tr{" class=ch" if any(c[0] == f for c in r["changed"]) else ""}><td>{f}</td><td>{html.escape(str(r["without"][f]))}</td>'
                       f'<td>{html.escape(str(r["llm"].get(f, "—")))} <small>{html.escape(str((r["llm"].get("evidence") or {}).get(f, "")))}</small></td></tr>'
                       for f in FIELDS if r['without'][f] != NA)
        cards.append(f'<div class="c"><div class="n">{i}. {html.escape(r["role"])} · {html.escape(r["shop"])}</div>'
                     + (f'<img src="{src}">' if src else '<div class="noimg">нет фото</div>')
                     + f'<div><a href="{html.escape(r["url"] or "")}">{html.escape(r["name"])}</a></div>'
                     f'<table><tr><th></th><th>без</th><th>модель</th></tr>{rows}</table></div>')
    open(os.path.join(L, 'sheet.html'), 'w', encoding='utf-8').write(
        '<!doctype html><meta charset="utf-8"><title>onb-06 обогащение спальни</title><style>body{font:13px sans-serif;margin:16px}'
        '.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}.c{border:1px solid #ccc;padding:8px;border-radius:6px}'
        'img{width:100%;height:180px;object-fit:contain;background:#f6f6f6}.noimg{height:180px;background:#fee}.n{color:#666;font-size:12px}'
        'table{width:100%;border-collapse:collapse;margin-top:6px}td,th{border-bottom:1px solid #eee;padding:2px 4px;text-align:left}'
        'tr.ch td{background:#fff3cd}small{color:#888}</style>'
        f'<h2>onb-06 Т2 — без / с обогащением, {len(recs)} карточек (жёлтым — обогащение меняет решение)</h2><div class="g">'
        + ''.join(cards) + '</div>')


def _selftest() -> int:
    bad = 0

    def ok(name, cond, info=''):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
        bad += 0 if cond else 1
    a = rules_fields('кровать', 'Кровать divan.ru Кейт 160 Букле Серый', {
        'Материал корпуса': 'ДВП ткань фанера ДСП', 'Материал обивки': 'букле', 'Цвет основной': 'Серый',
        'Подъемный механизм': 'без механизма с механизмом', 'Бельевой ящик: Наличие ящика для белья': 'без ящика для белья',
        'Размеры: Высота габаритная': '110см', 'Материал изголовья': 'ткань мебельный щит'})
    ok('кровать divan.ru: плита, букле → ткань, серый, без ящика', (a['material'], a['upholstery'], a['colour'], a['drawers'])
       == ('плита', 'ткань', 'серый', 'нет'), a)
    ok('«без механизма с механизмом» — неизвестно (варианты модели, не этого предложения)', a['lift'] == UNK, a)
    ok('изголовье: 110 см — среднее, мягкое', (a['headboard'], a['headboard_soft']) == ('среднее', 'мягкое'), a)
    b = rules_fields('кровать', 'Кровать Босс 160 с подъемным механизмом Латте', {
        'Материал': 'ДСП 16 мм, ППУ , ЛДСП 16 мм, ткань', 'Бельевой ящик и подъемный механизм': 'Да', 'Высота': '118'})
    ok('МногоМебели: «Да» в ящике и механизме — есть оба; латте — бежевый', (b['drawers'], b['lift'], b['colour']) ==
       ('есть', 'есть', 'бежевый'), b)
    c = rules_fields('кровать', 'Кровать Тест', {'Высота изголовья': '95 см 110 см 130 см'})
    ok('высота изголовья списком вариантов — неизвестно', c['headboard'] == UNK, c)
    d = rules_fields('шкаф', 'Босс Стандарт 120*236 шкаф распашной 3Д+ящики Кашемир', {'Высота': '236', 'Материал фасада': 'ЛДСП'})
    ok('шкаф МногоМебели: ящики по названию, кашемир — бежевый, корпуса нет — материал по фасаду',
       (d['drawers'], d['colour'], d['material'], d['lift']) == ('есть', 'бежевый', 'плита', NA), d)
    e = rules_fields('тумба прикроватная', 'Тумба прикроватная divan.ru Селтик 35x35 Черный',
                     {'Материал корпуса': 'Металл', 'Цвет основной': 'Черный'})
    ok('тумба Селтик: металл, чёрный, ящиков не сказано — неизвестно', (e['material'], e['colour'], e['drawers']) ==
       ('металл', 'чёрный', UNK), e)
    f = rules_fields('кровать', 'Белла Кровать без ПМ 140*200 Велюр Монолит аква', {
        'Материал': 'ДСП 16 мм, ППУ , ЛДСП 16 мм, ткань', 'Бельевой ящик и подъемный механизм': 'Да'})
    ok('«без ПМ» в названии: механизма нет, общее поле «ящик и механизм: Да» не про это предложение', (f['lift'], f['drawers']) ==
       ('нет', UNK), f)
    g = rules_fields('шкаф', 'Распашной шкаф divan.ru Монблан 3-139x215 Грань Белый', {
        'Цвет основной': 'Белый Бежевый', 'Материал корпуса': 'ЛДСП 16 мм', 'Максимальная нагрузка на ящик': '5кг'})
    ok('divan.ru: цвет из хвоста названия, а не «Белый Бежевый»; нагрузка на ящик — ящики есть', (g['colour'], g['drawers']) ==
       ('белый', 'есть'), g)
    h = rules_fields('кровать', 'Босс ХО Кровать 180*200 велюр Монолит латте', {'Материал': 'Труба стальная профильная, ДСП, ППУ, ЛДСП'})
    k = rules_fields('комод', 'Комод-бюро Glasar', {'Материал каркаса': 'Дерево, МДФ'})
    m = rules_fields('шкаф', 'Рим 90 шкаф распашной 2Д 01 Кашемир', {'Материал фасада': 'ЛДСП'})
    ok('материал: плита в смеси со сталью и «деревом» — плита; без корпуса — по фасаду', (h['material'], k['material'], m['material'])
       == ('плита', 'плита', 'плита'), (h['material'], k['material'], m['material']))
    ok('changed: цвет внутри группы палитры (коричневый ↔ дерево тёмное) — не смена решения',
       changed('тумба прикроватная', {**e, 'colour': 'коричневый'}, {**e, 'colour': 'дерево тёмное'}) == [])
    ok('changed: заполнено и спор; ящики комода — не решение',
       changed('кровать', a, {**a, 'lift': 'есть', 'colour': 'бежевый'}) == [('colour', 'спор', 'серый', 'бежевый'), ('lift', 'заполнено', UNK, 'есть')]
       and changed('комод', {**a, 'drawers': 'есть'}, {**a, 'drawers': 'нет'}) == [])
    print('FAILS', bad)
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if '--recount' in sys.argv:
        sys.exit(recount(os.path.expanduser(sys.argv[sys.argv.index('--recount') + 1]).rstrip('/')))
    if '--probe' in sys.argv:
        sys.exit(run(int(sys.argv[sys.argv.index('--probe') + 1]), '--dry' in sys.argv))
    print(__doc__)
