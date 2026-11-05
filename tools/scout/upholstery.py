#!/usr/bin/env python3
"""ТКАНЬ ОБИВКИ мягкой мебели — признак с источником (план onb-04 Т4, ADR-0330).

ЗАЧЕМ. Опрос-знакомство спрашивает про питомцев и детей; ответить «этот диван подойдёт» можно только зная обивку.
Сегодня «Обивка» читается лишь стилем (`style_score.py:42`), отдельно ткань не хранится.

ЧТО ДАЁТ. Для дивана, кресла, пуфа гостиной (`products`) и кровати с мягким изголовьем спальни (`room_catalog`):
тип ткани (велюр, микровелюр, рогожка, букле, шенилл, флок, жаккард, вельвет, экокожа, кожа …), «антикоготь»,
«легко чистится», источник (параметр магазина / название / описание) и версия правил. Тип не найден — честное
«неизвестно» (None), не догадка. Своя таблица `upholstery` (`015-upholstery.sql`), ключ — (откуда, магазин, оффер).

ЧТО ПИШУТ МАГАЗИНЫ (замер фидов 05.11): divan.ru — «Материал обивки» (велюр/букле/…) и «Обивка: Ткань 1» («Кларинс 100
букле»), «Легкий уход за обивкой: да»; МногоМебели/ДиванБосс — «Ткань»/«Тип ткани» («Велюр Монолит», «velyur-monolit»);
tvoydom — «Материал обшивки»; Орматек — в названии в скобках «(Ткань: Микровелюр …)», «(Экокожа Слива)».

ПИТОМЦЫ И ДЕТИ — ТОЛЬКО ЯВНОЕ (нормы расходятся, 05.11): иностранные обзоры называют букле самым рискованным для когтей
(петли), русские советуют «антивандальное букле», рогожку и микровелюр; общего у всех — решает плотность и
переплетение, а не название ткани (revolutionfabrics.com «best upholstery fabric for cats», catster.com «couch materials
for cat hair and claws», realty.rbc.ru 12.07.2024, expertcen.ru «лучшая обивка для дивана»). Поэтому «антикоготь»
ставим только по слову магазина (антикоготь/антивандальная), а не по типу; «легко чистится» — по параметру магазина
(«Легкий уход за обивкой», «Водоотталкивающ…») или слову в названии/ткани. Из описания — помечается источником `desc`
(слабее: описания у магазинов шаблонные).

ФЛАГ. `rules/upholstery.json` `enabled=false`: признак считается и пишется в свою таблицу, но никто его не читает, пока
выборка 50 не принята ведущим (точность ≥ 90 %, покрытие ≥ 60 % — иначе «не использовать»).

  python3 upholstery.py --selftest
  ~/venvs/scout/bin/python upholstery.py --measure              # покрытие по ролям и магазинам, без базы
  ~/venvs/scout/bin/python upholstery.py --sample 50 --out DIR  # лист «фото + карточка + признак» ведущему
  ~/venvs/scout/bin/python upholstery.py --run                  # запись в таблицу upholstery (только при enabled)
"""
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RULES = os.path.join(HERE, 'rules', 'upholstery.json')
RULES_VER = 'uph-1'
SOFT_LIVING = ('диван', 'кресло', 'пуф')
SOFT_BED = ('кровать', 'кровать детская')

# Порядок важен: частное раньше общего (микровелюр раньше велюра, экокожа раньше кожи, «шенильная рогожка» — рогожка)
TYPES = [
    ('микровелюр', r'микро-?велюр'),
    ('экозамша', r'эко-?замш|искусственн\w* замш'),
    ('экокожа', r'эко-?кож|искусственн\w* кож|кожзам|иск\.\s?кож|\bpu\b'),
    ('кожа', r'натуральн\w* кож|\bкожа\b|\bкож\.'),
    # «Альпака 08 искусственная шерсть» (divan.ru «Ланси») — ворсовый мех, не шерсть (разметка ведущего 05.11, №9)
    ('искусственный мех', r'\bмех\b|меховая|\bмеха\b|искусственн\w* шерст|альпак'),
    ('рогожка', r'шенильн\w* рогожк'),       # «Шанен … шенильная рогожка» — в названии divan.ru «Рогожка»
    ('шенилл', r'шенил|shenill'),
    ('букле', r'букле|boucle|bukle'),
    ('рогожка', r'рогожк|rogozh'),
    ('флок', r'\bфлок'),
    ('жаккард', r'жаккард|jacquard'),
    ('гобелен', r'гобелен'),
    ('вельвет', r'вельвет|velvet-kord|\bкорд\b'),
    ('бархат', r'бархат'),
    ('трикотаж', r'трикотаж'),
    ('замша', r'замш'),
    ('микрофибра', r'микрофибр'),
    ('шерсть', r'шерст'),
    ('велюр', r'велюр|velyur|алькантар'),
]
_TYPES = [(t, re.compile(p, re.I)) for t, p in TYPES]
# одна ткань под разными словами — не спор названия с параметром («Ланси Шерсть» при «искусственная шерсть»)
SAME = ({'велюр', 'микровелюр', 'бархат'}, {'искусственный мех', 'шерсть'})
GENERIC = re.compile(r'ткан|текстил', re.I)
# Параметры обивки по убыванию доверия (замер 05.11)
PARAM_KEYS = ('Тип ткани', 'Ткань', 'Обивка: Ткань 1', 'Материал обивки', 'Материал обшивки', 'Тип обивки: Материал сиденья',
              'Обивка: Основная', 'Материал изголовья', 'Основной материал')
ANTI_CLAW = re.compile(r'анти-?когот|антивандальн|anti-?claw|когтеустойчив', re.I)
EASY = re.compile(r'easy ?clean|легк\w* (уход|чистк)|легко чист|водоотталкив|антипятн|грязеотталк', re.I)
EASY_KEYS = ('Легкий уход за обивкой', 'Водоотталкивающее покрытие', 'Водоотталкивающая ткань')


def fabrics_in(text: str) -> list:
    """Все ткани текста по порядку упоминания: «велюр,букле (HYP),Экокожа» → [велюр, букле, экокожа]. Частное раньше
    общего: место, занятое «микровелюром», «велюр» уже не берёт."""
    found, taken = [], []
    for t, rx in _TYPES:
        for m in rx.finditer(text or ''):
            if not any(a < m.end() and m.start() < b for a, b in taken):
                taken.append((m.start(), m.end()))
                found.append((m.start(), t))
    out = []
    for _pos, t in sorted(found):
        if t not in out:
            out.append(t)
    return out


def fabric_of(text: str) -> str | None:
    """Первая названная ткань (у смешанной обивки магазин ставит основную первой)."""
    f = fabrics_in(text)
    return f[0] if f else None


def classify(name: str, params: dict, desc: str = '') -> dict:
    """→ {fabric, generic, anti_claw, easy_clean, evidence, conflict, rules_ver}. Чистая функция (селфтест).
    fabric=None и generic=True — магазин сказал только «ткань»; оба пусто — про обивку ничего нет."""
    p = params or {}
    fab, ev, generic, mixed = None, '', False, []
    for k in PARAM_KEYS:
        v = (p.get(k) or '').strip()
        if not v:
            continue
        ts = fabrics_in(v)
        if ts:
            fab, ev = ts[0], f'param:{k}={v[:40]}'
            mixed = ts[1:]
            break
        generic = generic or bool(GENERIC.search(v))
    nm = name or ''
    t_name = fabric_of(re.sub(r'\bкровать\b', '', nm, flags=re.I))
    # ВАРИАНТ В СКОБКАХ НАЗВАНИЯ главнее параметра: у Орматека «Материал обивки» — ткани всей линейки («Ткань: Микровелюр»
    # у «Castello (Экокожа Слива)»), а скобка — этот вариант (замер 05.11: 81 спор у кроватей Орматека)
    # скобка, которая НАЧИНАЕТСЯ тканью, — вариант: «(Экокожа Слива)», «(Ткань: Микровелюр Laska (…))»; «Como (Veda)» — нет
    t_var = next((t for t in (fabric_of(m) for m in re.findall(r'\((?:ткань\s*:?\s*|(?:массив|лдсп|мдф|металл)[^/()]*/\s*)?([^\s()/,]+)', nm, re.I)) if t), None)
    conflict = ''
    if t_var and t_var != fab:
        if fab:
            conflict = f'параметр {fab} — у линейки, вариант в названии {t_var}'
        fab, ev = t_var, 'name(вариант)'
    elif fab is None and t_name:
        fab, ev = t_name, 'name'
    elif fab and t_name and t_name != fab and not any({fab, t_name} <= g for g in SAME):
        conflict = f'в названии {t_name}'
    if mixed and not conflict:
        conflict = 'смешанная: ещё ' + ', '.join(mixed)
    vals = ' '.join(str(v) for v in p.values())
    claw, claw_src = None, ''
    if ANTI_CLAW.search(nm) or ANTI_CLAW.search(vals):
        claw, claw_src = True, 'name/param'
    elif ANTI_CLAW.search(desc or ''):
        claw, claw_src = True, 'desc'
    easy, easy_src = None, ''
    if any(re.match(r'\s*да\b', p.get(k) or '', re.I) for k in EASY_KEYS):
        easy, easy_src = True, 'param'
    elif EASY.search(nm) or any(EASY.search(p.get(k) or '') for k in PARAM_KEYS):
        easy, easy_src = True, 'name/param'
    elif EASY.search(desc or ''):
        easy, easy_src = True, 'desc'
    return {'fabric': fab, 'generic': fab is None and (generic or bool(GENERIC.search(nm))), 'anti_claw': claw,
            'anti_claw_src': claw_src, 'easy_clean': easy, 'easy_clean_src': easy_src, 'evidence': ev, 'conflict': conflict,
            'rules_ver': RULES_VER}


def soft_bed(name: str, params: dict) -> bool:
    """Кровать с мягким изголовьем: магазин так и пишет («Вид кровати: мягкая») или у изголовья/обивки/названия — ткань
    или экокожа. ЛДСП/массив/металл — не мягкая, ткани у неё нет (в знаменатель покрытия не идёт)."""
    p = params or {}
    if re.search(r'мягк', p.get('Вид кровати') or '', re.I):
        return True
    txt = ' '.join([name or ''] + [p.get(k) or '' for k in ('Материал изголовья', 'Материал обивки', 'Тип ткани', 'Ткань',
                                                            'Обивка: Ткань 1')])
    return bool(fabric_of(txt) or re.search(r'ткан', txt, re.I))


def rules() -> dict:
    try:
        return json.load(open(RULES, encoding='utf-8'))
    except FileNotFoundError:
        return {'enabled': False}


def collect() -> list:
    """Мягкая мебель из свежих фидов: гостиная — роль загрузчика `load3` (диван/кресло/пуф → `products`), спальня — роль
    `room_catalog.role_of` (кровать с мягким изголовьем → `room_catalog`). Без базы."""
    import glob
    import zipfile
    import category_map
    import load3 as L
    import room_catalog as RC
    R = RC.rules()
    catrole, known = L.load_roles()
    fresh = L.load_fresh()
    out = []
    for z in sorted(glob.glob(os.path.join(L.FEEDS, '*.zip'))):
        st = (fresh.get(os.path.basename(z).split('.')[0]) or {}).get('state')
        if st in ('broken', 'stale', 'empty') or not zipfile.is_zipfile(z):
            continue
        offs, _raw = L.parse_feed(z, catrole, known)
        for o in offs:
            if o.get('role') in SOFT_LIVING:
                o['src'], o['u_role'] = 'products', o['role']
            else:
                r = RC.role_of(o['mid'], o['cid'], o['name'], R, category_map.is_kids)
                if r not in SOFT_BED or not soft_bed(o['name'], o['params']):
                    continue
                o['src'], o['u_role'] = 'room_catalog', r
            o['uph'] = classify(o['name'], o['params'], o.get('desc') or '')
            out.append(o)
    seen, uniq = set(), []
    for o in out:
        k = (o['src'], o['mid'], o['eid'])
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    return uniq


def measure() -> int:
    items = collect()
    cells: dict = {}
    for o in items:
        cells.setdefault((o['u_role'], o['shop']), []).append(o)
    print('| роль | магазин | мягких | тип известен | только «ткань» | ничего | антикоготь (из них desc) | легко чистится (из них desc) | спор с названием |')
    print('|---|---|---|---|---|---|---|---|---|')
    tot = [0, 0]
    for (r, sh), lst in sorted(cells.items(), key=lambda x: (x[0][0], -len(x[1]))):
        u = [o['uph'] for o in lst]
        known = sum(1 for x in u if x['fabric'])
        tot[0] += len(u)
        tot[1] += known
        print(f"| {r} | {sh} | {len(u)} | {known} ({known * 100 // len(u)} %) | {sum(1 for x in u if x['generic'])} | "
              f"{sum(1 for x in u if not x['fabric'] and not x['generic'])} | {sum(1 for x in u if x['anti_claw'])} "
              f"({sum(1 for x in u if x['anti_claw_src'] == 'desc')}) | {sum(1 for x in u if x['easy_clean'])} "
              f"({sum(1 for x in u if x['easy_clean_src'] == 'desc')}) | {sum(1 for x in u if x['conflict'])} |")
    types: dict = {}
    for o in items:
        types[o['uph']['fabric']] = types.get(o['uph']['fabric'], 0) + 1
    print(f"\nпокрытие типом: {tot[1]} из {tot[0]} ({tot[1] * 100 // max(tot[0], 1)} %); типы: " +
          ', '.join(f'{k or "неизвестно"} {v}' for k, v in sorted(types.items(), key=lambda x: -x[1])))
    return 0


def sample(n: int, out_dir: str, seed: int = 50) -> int:
    """Выборка n по магазинам и типам (каждая клетка «магазин × тип» — хотя бы раз, остальное — пропорционально) →
    `sheet.html` (фото + название + параметры обивки + описание + признак + графа «верно?») и `sample.jsonl`."""
    import hashlib
    import html
    import urllib.request
    items = collect()
    rnd = random.Random(seed)
    cells: dict = {}
    for o in items:
        cells.setdefault((o['shop'], o['u_role'] in SOFT_BED, o['uph']['fabric'] or ('ткань?' if o['uph']['generic'] else '—')), []).append(o)
    keys = sorted(cells)
    rnd.shuffle(keys)
    pick = [rnd.choice(cells[k]) for k in keys][:n]
    rest = [o for o in items if o not in pick]
    pick += rnd.sample(rest, max(0, n - len(pick)))
    os.makedirs(os.path.join(out_dir, 'img'), exist_ok=True)

    def grab(u):
        if not u:
            return None
        f = hashlib.md5(u.encode()).hexdigest()[:16] + '.jpg'
        try:
            req = urllib.request.Request(('https:' + u) if u.startswith('//') else u,
                                         headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://remont-lab.online/'})
            with urllib.request.urlopen(req, timeout=20) as r:
                open(os.path.join(out_dir, 'img', f), 'wb').write(r.read())
            return 'img/' + f
        except Exception:  # noqa: BLE001 — нет фото: в листе ссылка на карточку
            return None
    rows = []
    with open(os.path.join(out_dir, 'sample.jsonl'), 'w', encoding='utf-8') as js:
        for i, o in enumerate(pick, 1):
            img = grab(o.get('pic_hd') or o.get('pic'))
            u = o['uph']
            keep = {k: v for k, v in o['params'].items() if k in PARAM_KEYS + EASY_KEYS + ('Вид кровати',) or ANTI_CLAW.search(v)}
            js.write(json.dumps({'n': i, 'src': o['src'], 'mid': o['mid'], 'eid': o['eid'], 'role': o['u_role'], 'shop': o['shop'],
                                 'name': o['name'], 'url': o['direct_url'] or o['url'], 'params': keep, 'uph': u,
                                 'verdict': None}, ensure_ascii=False) + '\n')
            claw = 'да (' + u['anti_claw_src'] + ')' if u['anti_claw'] else '—'
            easy = 'да (' + u['easy_clean_src'] + ')' if u['easy_clean'] else '—'
            rows.append(f"<tr><td>{i}</td><td>{f'<img src={img!r}>' if img else 'нет фото'}</td><td><b>{html.escape(o['name'])}</b><br>"
                        f"{html.escape(o['shop'])} · {o['u_role']} · <a href={html.escape(o['direct_url'] or o['url'])!r}>карточка</a>"
                        f"<br><small>{html.escape('; '.join(f'{k}: {v}' for k, v in keep.items()))}</small>"
                        f"<br><small class=d>{html.escape((o.get('desc') or '')[:400])}</small></td>"
                        f"<td><b>{u['fabric'] or ('ткань, тип неизвестен' if u['generic'] else 'неизвестно')}</b><br>"
                        f"<small>{html.escape(u['evidence'])}{(' · спор: ' + u['conflict']) if u['conflict'] else ''}</small>"
                        f"<br>антикоготь: {claw}<br>легко чистится: {easy}</td><td>☐ верно<br>☐ неверно: ____</td></tr>")
    open(os.path.join(out_dir, 'sheet.html'), 'w', encoding='utf-8').write(
        '<!doctype html><meta charset=utf-8><title>Ткань обивки — выборка</title><style>body{font:14px sans-serif;margin:16px}'
        'table{border-collapse:collapse}td{border:1px solid #ccc;padding:6px;vertical-align:top}img{width:220px}'
        '.d{color:#666}</style>'
        f'<h1>Ткань обивки — выборка {len(pick)} (правила {RULES_VER})</h1><p>Сверить признак с фото и карточкой магазина: '
        'тип ткани верен? «антикоготь»/«легко чистится» — подтверждены карточкой? Отметить «верно/неверно».</p>'
        '<table><tr><th>№</th><th>фото</th><th>товар</th><th>признак</th><th>проверка</th></tr>' + ''.join(rows) + '</table>')
    print(f'лист: {os.path.join(out_dir, "sheet.html")} ({len(pick)} строк, фото {sum("<img" in r for r in rows)})')
    return 0


def run() -> int:
    """Запись в таблицу `upholstery` — только при `enabled` (ночной шаг ставит onb-12 после приёмки выборки)."""
    if not rules().get('enabled'):
        print('ткань обивки: выключено (rules/upholstery.json enabled=false) — не пишу', flush=True)
        return 0
    import room_catalog as RC
    RC.sql(open(os.path.join(HERE, '015-upholstery.sql'), encoding='utf-8').read())
    items = collect()
    rows = []
    for o in items:
        u = o['uph']
        rows.append('(' + ','.join(RC._lit(x) for x in (
            o['src'], o['mid'], str(o['eid']), u['fabric'], u['generic'], u['anti_claw'], u['anti_claw_src'] or None,
            u['easy_clean'], u['easy_clean_src'] or None, u['evidence'] or None, u['conflict'] or None, RULES_VER)) + ', now())')
    q = ['begin;']
    for i in range(0, len(rows), 500):
        q.append('insert into upholstery (source_table, shop_mid, external_id, fabric, generic, anti_claw, anti_claw_src, easy_clean, '
                 'easy_clean_src, evidence, conflict, rules_ver, updated_at) values ' + ','.join(rows[i:i + 500]) +
                 ' on conflict (source_table, shop_mid, external_id) do update set fabric=excluded.fabric, generic=excluded.generic, '
                 'anti_claw=excluded.anti_claw, anti_claw_src=excluded.anti_claw_src, easy_clean=excluded.easy_clean, '
                 'easy_clean_src=excluded.easy_clean_src, evidence=excluded.evidence, conflict=excluded.conflict, '
                 'rules_ver=excluded.rules_ver, updated_at=now();')
    q.append('commit;')
    RC.sql('\n'.join(q))
    known = sum(1 for o in items if o['uph']['fabric'])
    print(f'ткань обивки: записано {len(rows)}, тип известен {known}', flush=True)
    return 0


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    c = lambda nm, p=None, d='': classify(nm, p or {}, d)  # noqa: E731
    # реальные карточки фидов 05.11
    ok('divan.ru: «Материал обивки: велюр»', c('Диван прямой divan.ru Динс Велюр Серый', {'Материал обивки': 'велюр'})['fabric'] == 'велюр')
    ok('divan.ru: общий «Ткань» → «Обивка: Ткань 1» Кларинс 100 букле',
       c('Кресло divan.ru Тейт', {'Материал обивки': 'Ткань', 'Обивка: Ткань 1': 'Кларинс 100 букле'})['fabric'] == 'букле')
    ok('divan.ru: «Ткань: Микровелюр» — микровелюр, не велюр', c('Пуф divan.ru', {'Материал обивки': 'Ткань: Микровелюр'})['fabric'] == 'микровелюр')
    ok('divan.ru: «шенильная рогожка» — рогожка', c('Диван', {'Материал обивки': 'шенильная рогожка'})['fabric'] == 'рогожка')
    ok('МногоМебели: «Ткань: Велюр Монолит»', c('Диван Босс Мини велюр Монолит латте', {'Ткань': 'Велюр Монолит'})['fabric'] == 'велюр')
    ok('ДиванБосс: транслит «velyur-monolit»', c('Кровать Босс', {'Тип ткани': 'velyur-monolit'})['fabric'] == 'велюр')
    ok('ДиванБосс: «Вельвет Корд»', c('Диван Лофт', {'Ткань': 'Вельвет Корд'})['fabric'] == 'вельвет')
    ok('Орматек: тип из названия «(Экокожа Слива)»', c('Кровать Орматек Corso-6 BS (Экокожа Слива) 140x190', {'Материал': 'ЛДСП'})['fabric'] == 'экокожа')
    ok('Орматек: «(Ткань: Микровелюр Manhattan …)»', c('Кровать Verda Lark (Ткань: Микровелюр Manhattan Тихий океан)')['fabric'] == 'микровелюр')
    ok('искусственная кожа (экокожа) — экокожа, не кожа', c('Кресло', {'Материал обивки': 'искусственная кожа (экокожа)'})['fabric'] == 'экокожа')
    ok('«Ткань: Экозамша» — экозамша', c('Диван', {'Материал обивки': 'Ткань: Экозамша'})['fabric'] == 'экозамша')
    ok('tvoydom: «Кресло ТС 52х40х97 см флок коричневый»', c('Кресло ТС 52х40х97 см флок коричневый')['fabric'] == 'флок')
    g = c('Диван угловой', {'Материал обивки': 'Ткань'})
    ok('только «Ткань» — тип неизвестен, но не «ничего»', g['fabric'] is None and g['generic'])
    ok('ничего про обивку — неизвестно', c('Пуф Glasar 40x40')['fabric'] is None and not c('Пуф Glasar 40x40')['generic'])
    ok('«Легкий уход за обивкой: да» — легко чистится (параметр)',
       c('Диван', {'Материал обивки': 'велюр', 'Легкий уход за обивкой': 'да'})['easy_clean_src'] == 'param')
    ok('«Водоотталкивающее покрытие: Да»', c('Кресло', {'Водоотталкивающее покрытие': 'Да'})['easy_clean'])
    ok('«Легкий уход: нет» — не ставим', c('Диван', {'Легкий уход за обивкой': 'нет'})['easy_clean'] is None)
    ok('антикоготь — только по слову магазина', c('Диван велюр антикоготь')['anti_claw'] and c('Диван микровелюр')['anti_claw'] is None)
    ok('антикоготь из описания — источник desc', c('Диван', {}, 'Ткань антивандальная, устойчива к когтям')['anti_claw_src'] == 'desc')
    ok('букле не делает «антикоготь» и не «против питомцев» — нормы расходятся', c('Диван букле')['anti_claw'] is None)
    ok('спор: параметр «велюр», в названии «букле» — пишем параметр и спор',
       c('Диван Букле Серый', {'Материал обивки': 'велюр'})['conflict'] == 'в названии букле')
    o = c('Кровать Орматек Castello (Экокожа Слива) 140x190', {'Материал обивки': 'Ткань: Микровелюр'})
    ok('Орматек: параметр линейки «Микровелюр», вариант «(Экокожа Слива)» — экокожа', (o['fabric'], o['evidence']) == ('экокожа', 'name(вариант)'))
    ok('Орматек: вложенные скобки «(Ткань: Микровелюр Laska 01 Белая смородина (…))»', c(
        'Кровать Спальная система Verda Royal Compact (Ткань: Микровелюр Laska 01 Белая смородина (Красный)) 160x200',
        {'Материал обивки': 'Ткань: Флок'})['fabric'] == 'микровелюр')
    ok('divan.ru: «Шанен Молочный шенильная рогожка» при «Рогожка» в названии — рогожка, без спора',
       c('Кровать divan.ru Молсон 140 Рогожка', {'Обивка: Ткань 1': 'Шанен Молочный шенильная рогожка'})['conflict'] == '')
    ok('divan.ru: «Танго 670 велюр», в названии «Шенилл» — параметр, спор виден',
       c('Кровать divan.ru Кевия 160 Шенилл Мятный', {'Обивка: Ткань 1': 'Танго 670 велюр'})['conflict'] == 'в названии шенилл')
    m = c('Кресло TC Murano/Мурано опора 360, велюр/букле (HYP)/Экокожа', {'Материал обшивки': 'велюр,букле (HYP),Экокожа'})
    ok('tvoydom: «велюр,букле (HYP),Экокожа» — первая названная (велюр), пометка «смешанная»',
       (m['fabric'], m['conflict']) == ('велюр', 'смешанная: ещё букле, экокожа'))
    ok('«Кресло divan.ru Ланси Шерсть Белый» — шерсть', c('Кресло divan.ru Ланси Шерсть Белый')['fabric'] == 'шерсть')
    la = c('Кресло divan.ru Ланси Шерсть Белый', {'Обивка: Ткань 1': 'Альпака 08 искусственная шерсть'})
    ok('«Альпака … искусственная шерсть» — искусственный мех, «Шерсть» в названии — не спор',
       (la['fabric'], la['conflict']) == ('искусственный мех', ''))
    ok('«альпака» без «шерсти» — искусственный мех', c('Пуф Тест', {'Ткань': 'Альпака 03'})['fabric'] == 'искусственный мех')
    ok('Орматек: «Como (Veda) 4 Grand … (Экокожа Athens …)» — вариант во второй скобке', c(
        'Кровать Орматек Como (Veda) 4 Grand с подъёмным механизмом (Экокожа Athens Белый) 160x200',
        {'Материал обивки': 'Ткань: Микровелюр'})['fabric'] == 'экокожа')
    ok('Орматек: «(Массив/Рогожка Антик …)» — рамка/ткань, вариант рогожка', c(
        'Кровать Орматек Wood Home 2 с подъёмным механизмом (Массив/Рогожка Антик (сосна)/Savana Grey) 160x200',
        {'Материал обивки': 'Массив/Букле'})['fabric'] == 'рогожка')
    ok('мягкая кровать: «Вид кровати: мягкая»', soft_bed('Кровать divan.ru Кейт', {'Вид кровати': 'мягкая'}))
    ok('кровать ЛДСП — не мягкая', not soft_bed('Кровать Орматек Twin (ЛДСП Белый) 140x190', {'Материал': 'ЛДСП'}))
    ok('выключено по умолчанию (никто не читает до приёмки выборки)', rules().get('enabled') is False)
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if '--measure' in sys.argv:
        sys.exit(measure())
    if '--sample' in sys.argv:
        sys.exit(sample(int(sys.argv[sys.argv.index('--sample') + 1]), sys.argv[sys.argv.index('--out') + 1]))
    if '--run' in sys.argv:
        sys.exit(run())
    print(__doc__)
