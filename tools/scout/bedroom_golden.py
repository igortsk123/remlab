#!/usr/bin/env python3
"""Эталон по фото на спорных карточках СПАЛЬНИ (onb-06, T-20261105-20; ответ советника — _intake/codex/onb06-enrich-…-answer.md §1).

ЗАЧЕМ. Проба 50 показала, что модель полезна узко: ящики у тумб и шкафов, есть ли изголовье, цвет при споре фида и названия.
Согласие модели с фидом — не точность (тот же текст), поэтому здесь эталон: модель смотрит ТОЛЬКО на фото, а ведущий глазами
отмечает «верно/неверно» на листе. Только три поля и только спорные карточки:
  - цвет: фид («Цвет основной» / «Цвет» / «Цвет каркаса») и хвост названия — в разных группах палитры;
  - ящики: правила по фиду и названию дают «неизвестно» (кровать, тумба, шкаф; у комода ящики по определению);
  - изголовье: у кровати в фиде нет ни одного параметра про изголовье.
Цвет — в два шага: (1) фото без названия и фида → цвет предмета; (2) сопоставление с названием и фидом — кодом, без модели,
чтобы ответ не якорился на проверяемом тексте. Приём: ящики — только «есть» («нет» = неизвестно: ящик бывает скрыт);
изголовье «нет» — только если кровать видна целиком. В базу НЕ пишет, правила не трогает.

  ~/venvs/scout/bin/python bedroom_golden.py --golden 30 --dry   # отбор и прикидка, без модели и денег
  ~/venvs/scout/bin/python bedroom_golden.py --golden 30         # гейт openai_budget + потолок $0,30, учёт трат, счётчик отказов
  ~/venvs/scout/bin/python bedroom_golden.py --style <папка>       # стиль сейчас / после поправки цвета (2 вызова скорера на 15)
  ~/venvs/scout/bin/python bedroom_golden.py --recount <папка> [--marks <отметки.json>]  # новые правила, без модели
  ~/venvs/scout/bin/python bedroom_golden.py --sheet <папка>       # пересобрать лист из golden.jsonl, без модели
  python3 bedroom_golden.py --selftest                           # спор/приём/сопоставление, без сети и базы
Выход — новая папка ~/remlab-logs/onb06-golden-<ММДД-ЧЧММ>/: golden.jsonl, meta.json, sheet.html (один файл, фото внутри), img/.
"""
import base64
import concurrent.futures as cf
import hashlib
import html
import io
import json
import os
import random
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bedroom_enrich import _COL, COLOURS, NA, PALETTE, UNK, _cls, _first, name_tail_colour, rules_fields  # noqa: E402

MODEL = os.environ.get('GOLDEN_MODEL', 'gpt-6-luna')
CAP_USD = 0.30                       # потолок всей пробы (ведущий 05.11: из прежнего лимита пробы)
QUOTA = {'кровать': 10, 'тумба прикроватная': 7, 'шкаф': 7, 'комод': 6}
FEED_COL = r'^Цвет$|^Цвет основной$|^Цвет каркаса$'
PROMPT_VER = 'golden-v1'
PHOTO_PX = 1024


# ---------- что спорно (чистые функции) ----------

def ckey(c):
    """Ключ сравнения цвета: группа палитры (белый ~ бежевый, коричневый ~ дерево тёмное), но акценты — каждый сам по себе:
    в PALETTE синий и зелёный — одна группа «акцент», а для спора фида с названием это разные цвета."""
    g = PALETTE.get(c)
    return c if g in ('акцент', 'многоцвет') else g


# составной цвет совпадает с каждой своей частью: «Серо-зеленый» в названии = «серый» на фото = «Зеленый» в фиде
COMPOSITE = {'серо-зелёный': ('серый', 'зелёный')}


def ckeys(c) -> set:
    if c in (UNK, None, ''):
        return set()
    return {ckey(x) for x in COMPOSITE.get(c, (c,))}

def name_colour(name: str) -> str:
    return name_tail_colour(name)


def feed_colour(P: dict) -> tuple:
    """(цвет, сырое) из основного цветового поля фида. Список исполнений («Бежевый Белый», «Золотистый, Белый, Черный») —
    не цвет этого предложения → неизвестно."""
    raw = _first(P, FEED_COL)
    named = {c for c in (_cls(t, _COL) for t in re.split(r'[\s,;/]+', raw) if t) if c != UNK}
    if len(named) > 1:
        return UNK, raw
    return _cls(raw, _COL), raw


def disputes(role: str, name: str, P: dict) -> list:
    """Какие из трёх полей у карточки спорны: 'colour' | 'drawers' | 'headboard'."""
    out = []
    n, (f, _) = name_colour(name), feed_colour(P)
    if n != UNK and f != UNK and not ckeys(n) & ckeys(f):
        out.append('colour')
    if role != 'комод' and rules_fields(role, name, P)['drawers'] == UNK:
        out.append('drawers')
    if role == 'кровать' and not any(re.search(r'изголов', k, re.I) and v for k, v in (P or {}).items()):
        out.append('headboard')
    return out


def accept(role: str, m: dict) -> dict:
    """Ответ модели по фото → что принимаем. Ящики: только «есть». Изголовье «нет» — только при кровати целиком в кадре."""
    dr = 'есть' if m.get('drawers') == 'есть' else UNK
    if role != 'кровать':
        hb = NA
    elif m.get('headboard') == 'есть':
        hb = 'есть'
    elif m.get('headboard') == 'нет' and m.get('bed_fully_visible'):
        hb = 'нет'
    else:
        hb = UNK
    return {'drawers': dr, 'headboard': hb}


def match_colour(photo: str, by_name: str, by_feed: str, variants: bool) -> tuple:
    """Шаг 2 — сопоставление цвета с фото и текстов, кодом. → (итог, откуда)."""
    if variants or photo in (UNK, None):
        return UNK, 'фото не решает (несколько исполнений или цвет не виден)'
    g = ckeys(photo)
    hit_n, hit_f = bool(ckeys(by_name) & g), bool(ckeys(by_feed) & g)
    # при совпадении с обоими — точный цвет фото важнее группы: фото белое, фид «Белый», название «Молочный» → белый (№6)
    if hit_n and hit_f:
        return (by_feed if by_feed == photo and by_name != photo else by_name), 'фото = название = фид'
    if hit_n:
        return by_name, 'фото = название' + (' (фид спорит)' if by_feed not in (UNK, None, '') else '')
    if hit_f:
        return by_feed, 'фото = фид' + (' (название спорит)' if by_name not in (UNK, None, '') else '')
    return UNK, 'фото не совпало ни с названием, ни с фидом — возможно, фото другого исполнения'


# ---------- отбор ----------

def pick(n_total: int, seed: int = 20) -> tuple:
    """Спорные показываемые карточки (условия показа демо, без детского, со сторожем роли), по одной на модель (без учёта магазина); роли — по
    QUOTA (масштаб под n_total), внутри роли магазины по кругу; в магазине первыми — карточки с большим числом спорных полей."""
    import room_catalog as RC
    R = RC.rules()
    rows = RC.sql(f"select role, shop_mid, external_id, shop, name, params::text, coalesce(image_url_hd, image_url), url, "
                  f"w_cm, d_cm, h_cm from room_catalog where {RC.shown_where(R)} and role in ("
                  + ','.join(RC._lit(r) for r in QUOTA) + ") order by shop_mid, external_id")
    f = lambda x: float(x) if x else None  # noqa: E731
    fam, n_disp = {}, {r: 0 for r in QUOTA}
    for r in rows:
        d = {'w': f(r[8]), 'd': f(r[9]), 'h': f(r[10])}
        P = json.loads(r[5] or '{}')
        if not r[6] or RC.child_only(r[0], r[4], R) or RC.role_guard(r[0], r[4], d, R):
            continue
        ds = disputes(r[0], r[4], P)
        if not ds:
            continue
        n_disp[r[0]] += 1
        # модель — без магазина: DIVANBOSS и МногоМебели продают одни и те же (Уна, Белла, Босс Стандарт, Рим; у МногоМебели ещё приставка «МП»)
        fam.setdefault((r[0], RC.family(re.sub(r'^МП\s+', '', re.sub(r'\s+', ' ', r[4])))), dict(role=r[0], mid=int(r[1]), eid=r[2], shop=r[3], name=r[4], params=P,
                                                            img=r[6], url=r[7], disputes=ds, **d))
    rnd = random.Random(seed)
    scale = n_total / sum(QUOTA.values())
    out = []
    for role, n in QUOTA.items():
        by: dict = {}
        for it in sorted(fam.values(), key=lambda x: (x['shop'], x['name'])):
            if it['role'] == role:
                by.setdefault(it['shop'], []).append(it)
        for v in by.values():
            rnd.shuffle(v)
            v.sort(key=lambda x: len(x['disputes']))      # pop() берёт с конца — самые спорные первыми
        got, k = [], round(n * scale)
        while len(got) < k and any(by.values()):
            for sh in sorted(by):
                if by[sh] and len(got) < k:
                    got.append(by[sh].pop())
        out += got
    short = n_total - len(out)
    return out, n_disp, len(fam), short


# ---------- фото и модель ----------

def photo(url: str, tries: int = 3) -> bytes | None:
    """Фото магазина, ужатое до 1024 px (JPEG) — одно и то же видит модель и ведущий на листе; ретраи от 403 CDN."""
    from PIL import Image
    u = 'https:' + url if url.startswith('//') else url
    for a in range(tries):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=45).read()
            im = Image.open(io.BytesIO(raw)).convert('RGB')
            im.thumbnail((PHOTO_PX, PHOTO_PX))
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=82)
            return buf.getvalue()
        except Exception:  # noqa: BLE001 — считаем в отказах фото, не глотаем
            if a < tries - 1:
                time.sleep(1.5 * (a + 1))
    return None


SCHEMA = {'type': 'object', 'additionalProperties': False,
          'required': ['colour', 'variants_shown', 'drawers', 'headboard', 'bed_fully_visible'], 'properties': {
              'colour': {'type': 'string', 'enum': COLOURS + [UNK]},
              'variants_shown': {'type': 'boolean'},
              'drawers': {'type': 'string', 'enum': ['есть', 'нет', UNK]},
              'headboard': {'type': 'string', 'enum': ['есть', 'нет', UNK, NA]},
              'bed_fully_visible': {'type': 'boolean'}}}

SYS = ('Ты смотришь на ОДНО фото товара для спальни. Название и описание товара тебе не даны — отвечай только по тому, что видно. '
       'Отвечай ТОЛЬКО по схеме JSON.\n'
       '1. colour — основной цвет САМОГО предмета (корпус, фасад, обивка), не стен, пола, белья, подушек и декора. '
       'Ножки и ручки не считаются. Дерево: светлое (дуб, сосна, берёза) или тёмное (орех, венге). Не уверен — «неизвестно».\n'
       '2. variants_shown — true, если на фото несколько исполнений или цветов этого предмета (коллаж, ряд вариантов).\n'
       '3. drawers — видны ли выдвижные ящики: у кровати — выдвижной ящик в основании или открытая ниша для белья; '
       'у тумбы, шкафа, комода — фасады ящиков. «есть» — только если ящик виден; «нет» — если предмет виден и ящиков нет; '
       'не понять — «неизвестно».\n'
       '4. headboard — у кровати: есть ли изголовье (спинка у головы); у тумбы, шкафа, комода — не_применимо.\n'
       '5. bed_fully_visible — у кровати: видна ли кровать целиком (весь край у головы, без обрезки кадром и без закрытия '
       'подушками/стеной). У не-кровати — false.')
PROMPT_HASH = hashlib.sha256((SYS + json.dumps(SCHEMA, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:12]


def ask(it: dict) -> dict:
    from llm_gateway import chat
    from openai_budget import log_spend
    b64 = base64.b64encode(it['photo']).decode()
    content = [{'type': 'text', 'text': f'Роль предмета: {it["role"]}.'},
               {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}', 'detail': 'high'}}]
    try:
        out = chat(MODEL, [{'role': 'system', 'content': SYS}, {'role': 'user', 'content': content}], reasoning_effort='low',
                   response_format={'type': 'json_schema', 'json_schema': {'name': 'bedroom_photo', 'strict': True, 'schema': SCHEMA}})
    except Exception as e:  # noqa: BLE001 — отказ считаем и показываем
        return {'err': f'{type(e).__name__}: {str(e)[:120]}'}
    log_spend(MODEL, out.get('usage'), 1, 'bedroom_golden 30')
    try:
        return {'fields': json.loads(out['choices'][0]['message']['content']), 'usage': out.get('usage'),
                'model_id': out.get('model'), 'fingerprint': out.get('system_fingerprint')}
    except (KeyError, ValueError) as e:
        return {'err': f'ответ не JSON: {str(e)[:80]}', 'usage': out.get('usage'), 'model_id': out.get('model')}


def run(n: int, dry: bool) -> int:
    from openai_budget import allow, estimate_request, price_of
    items, n_disp, n_fam, short = pick(n)
    print(f'спорных показываемых офферов по ролям: {n_disp}; моделей со спором: {n_fam}', flush=True)
    print(f'выборка {len(items)} (недобор {short}); по ролям:', {r: sum(1 for x in items if x['role'] == r) for r in QUOTA},
          '· по магазинам:', {s: sum(1 for x in items if x['shop'] == s) for s in sorted({x['shop'] for x in items})},
          '· по полям:', {f: sum(1 for x in items if f in x['disputes']) for f in ('colour', 'drawers', 'headboard')}, flush=True)
    est = estimate_request(MODEL) * 3           # фото detail=high — до ~3× к типовой оценке (low)
    print(f'прикидка ≈ ${len(items) * est:.3f} (потолок ${CAP_USD}); модель {MODEL}, промпт {PROMPT_VER}/{PROMPT_HASH}', flush=True)
    for i, it in enumerate(items, 1):
        print(f'  {i:02d} {it["role"]:<18} {it["shop"]:<13} {",".join(it["disputes"]):<24} {it["name"][:70]}', flush=True)
    if dry:
        return 0
    if len(items) * est > CAP_USD:
        print('СТОП: прикидка выше потолка пробы', flush=True)
        return 2
    if not allow(MODEL, len(items), note=f'bedroom_golden {len(items)}'):
        print('СТОП: дневной лимит OpenAI — проба не отправлена', flush=True)
        return 2
    L = os.path.expanduser('~/remlab-logs/onb06-golden-' + time.strftime('%m%d-%H%M'))
    os.makedirs(os.path.join(L, 'img'), exist_ok=False)
    photo_fail = []
    for i, it in enumerate(items, 1):            # последовательно: CDN отвечает 403 на параллельные запросы
        it['photo'] = photo(it['img'])
        if it['photo'] is None:
            photo_fail.append(it['name'])
            continue
        it['photo_file'] = f'img/{i:02d}.jpg'
        it['photo_sha256'] = hashlib.sha256(it['photo']).hexdigest()
        open(os.path.join(L, it['photo_file']), 'wb').write(it['photo'])
    todo = [it for it in items if it.get('photo')]
    with cf.ThreadPoolExecutor(6) as ex:
        got = list(ex.map(ask, todo))
    for it, g in zip(todo, got):
        it['_g'] = g
    fails = [(it['name'], it['_g']['err']) for it in todo if 'err' in it['_g']]
    tok = [it['_g']['usage'] for it in todo if it['_g'].get('usage')]
    pt, ct = sum(u.get('prompt_tokens', 0) for u in tok), sum(u.get('completion_tokens', 0) for u in tok)
    cost = price_of(MODEL, pt, ct) or 0.0
    recs = []
    for i, it in enumerate(items, 1):
        g = it.get('_g') or {}
        m = g.get('fields') or {}
        nc, (fc, fraw) = name_colour(it['name']), feed_colour(it['params'])
        rf = rules_fields(it['role'], it['name'], it['params'])
        col, why = match_colour(m.get('colour'), nc, fc, bool(m.get('variants_shown'))) if m else (UNK, 'нет ответа')
        recs.append({'n': i, **{k: it[k] for k in ('role', 'shop', 'mid', 'eid', 'name', 'img', 'url', 'disputes')},
                     'photo_file': it.get('photo_file'), 'photo_sha256': it.get('photo_sha256'),
                     'feed': {'colour_raw': fraw, 'colour': fc, 'colour_by_name': nc, 'colour_rules': rf['colour'],
                              'drawers_rules': rf['drawers'],
                              'headboard_params': {k: v for k, v in it['params'].items() if re.search(r'изголов', k, re.I)}},
                     'model': m, 'accepted': {**(accept(it['role'], m) if m else {}), 'colour': col, 'colour_why': why},
                     'model_alias': MODEL, 'model_id': g.get('model_id'), 'fingerprint': g.get('fingerprint'),
                     'prompt_ver': PROMPT_VER, 'prompt_hash': PROMPT_HASH, 'err': g.get('err'),
                     'ts': time.strftime('%Y-%m-%d %H:%M')})
    with open(os.path.join(L, 'golden.jsonl'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(json.dumps(r, ensure_ascii=False) for r in recs) + '\n')
    meta = {'model_alias': MODEL, 'model_ids': sorted({r['model_id'] for r in recs if r['model_id']}), 'prompt_ver': PROMPT_VER,
            'prompt_hash': PROMPT_HASH, 'n': len(recs), 'llm_fails': fails, 'photo_fails': photo_fail, 'pt': pt, 'ct': ct,
            'cost_usd': cost, 'cap_usd': CAP_USD, 'n_disputed_offers': n_disp, 'n_disputed_models': n_fam}
    json.dump(meta, open(os.path.join(L, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    sheet(recs, L, meta)
    print(f'ответов {len(todo) - len(fails)}, отказов модели {len(fails)}, отказов фото {len(photo_fail)}; '
          f'токены {pt}/{ct}; цена ${cost:.4f}; model_id {meta["model_ids"]}', flush=True)
    for nm, e in fails:
        print('  отказ:', nm, e, flush=True)
    print('папка:', L, flush=True)
    return 0 if not fails and not photo_fail else 1


# ---------- пересчёт 30 по сохранённым ответам и сверка с отметками ведущего (без модели и денег) ----------

def truth_colour(rec: dict, marks: dict) -> str:
    """Истинный цвет по фото: ответ модели, если ведущий отметил его верным, иначе — цвет из отметки."""
    return marks.get('photo_wrong', {}).get(str(rec['n']), rec['model'].get('colour', UNK))


def same_colour(a: str, b: str) -> bool:
    """Принятое = истина: точно, кроме синонимов «коричневый ~ дерево тёмное» (белый ≠ бежевый — №6 ведущий отметил неверным)."""
    return a == b or {a, b} == {'коричневый', 'дерево тёмное'}


def recount(L: str, marks_path: str | None) -> int:
    import room_catalog as RC
    recs = [json.loads(x) for x in open(os.path.join(L, 'golden.jsonl'), encoding='utf-8') if x.strip()]
    meta = json.load(open(os.path.join(L, 'meta.json'), encoding='utf-8'))
    out = L + '-recount-' + time.strftime('%H%M%S')
    os.makedirs(out, exist_ok=False)
    for r in recs:
        q = RC.sql(f"select params::text from room_catalog where shop_mid={int(r['mid'])} and external_id={RC._lit(r['eid'])} "
                   f"and room='{RC.ROOM}'")
        P = json.loads(q[0][0]) if q else {}
        nc, (fc, fraw) = name_colour(r['name']), feed_colour(P)
        rf = rules_fields(r['role'], r['name'], P)
        m = r['model']
        col, why = match_colour(m.get('colour'), nc, fc, bool(m.get('variants_shown'))) if m else (UNK, 'нет ответа')
        r['disputes_v1'], r['disputes'] = r['disputes'], disputes(r['role'], r['name'], P)   # пусто — спор снят правилами
        r['feed'] = {**r['feed'], 'colour_raw': fraw, 'colour': fc, 'colour_by_name': nc, 'colour_rules': rf['colour'],
                     'drawers_rules': rf['drawers']}
        r['accepted'] = {**(accept(r['role'], m) if m else {}), 'colour': col, 'colour_why': why}
        if r.get('photo_file'):
            r['photo_file'] = os.path.relpath(os.path.join(L, r['photo_file']), out)
    marks = json.load(open(marks_path, encoding='utf-8')) if marks_path else {}
    bad, unk = [], []
    for r in recs:
        a = r['accepted']['colour']
        if a == UNK:
            unk.append(r['n'])
        elif marks and not same_colour(a, truth_colour(r, marks)):
            bad.append((r['n'], a, truth_colour(r, marks)))
    with open(os.path.join(out, 'golden.jsonl'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(json.dumps(r, ensure_ascii=False) for r in recs) + '\n')
    meta['recount_of'] = L
    meta['recount'] = {'colour_known': len(recs) - len(unk), 'colour_unknown': unk, 'colour_wrong': bad,
                       'marks': marks_path}
    json.dump(meta, open(os.path.join(out, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    sheet(recs, out, meta)
    print(f'цвет принят у {len(recs) - len(unk)} из {len(recs)}, неизвестно {len(unk)} {unk}; '
          + (f'неверных по отметкам ведущего: {len(bad)} {bad}' if marks else 'отметок нет'), flush=True)
    print('папка:', out, flush=True)
    return 1 if bad else 0


# ---------- стиль: сейчас и после поправки цвета (дополнение ведущего 05.11: «и чтоб стилям соответствовало») ----------
# 5 показываемых стилей = homeModel().styles в порядке вкладок главной (quiz.json pick.tie = homeOrder; эталон
# tests/fixtures/quiz-golden.json available: scandi, modern, minimal, loft, japandi); неоклассики в витрине нет.
SHOWN = ['сканди', 'современный', 'минимализм', 'лофт', 'джапанди']
STYLE_FILE = os.environ.get('GOLDEN_STYLE_FILE', os.path.join(HERE, 'style-scores-bedroom.json'))


def _style_fns() -> dict:
    """Функции боевого скорера стиля (`style_score.py`: rows, bedroom_raw, llm_batch и словари) — по исходнику через ast:
    `import style_score` запускает полный прогон (урок про import-ловушку scout). Тот же промпт, что у оценок в файле."""
    import ast
    import subprocess
    from openai_budget import log_spend
    mod = ast.parse(open(os.path.join(HERE, 'style_score.py'), encoding='utf-8').read())
    want_f, want_a = {'rows', 'bedroom_raw', 'llm_batch'}, {'PSQL', 'SH', 'RSH', 'STYLES', 'SNAMES'}
    keep = [n for n in mod.body if (isinstance(n, ast.FunctionDef) and n.name in want_f)
            or (isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in want_a for t in n.targets))]
    ns = {'re': re, 'json': json, 'os': os, 'sys': sys, 'subprocess': subprocess, 'HERE': HERE,
          'SOURCE': 'room_catalog golden', '_log_spend': log_spend}
    exec(compile(ast.Module(body=keep, type_ignores=[]), 'style_score.py[ast]', 'exec'), ns)  # noqa: S102 — свой исходник
    missing = (want_f | want_a) - set(ns)
    assert not missing, f'в style_score.py нет {missing} — скорер переписан, СТОП'
    return ns


def top(sc: dict, names: list, k: int) -> list:
    """Первые k стилей по баллу; ничья — порядок names (для показываемых — порядок вкладок главной)."""
    return sorted(names, key=lambda st: (-sc.get(st, 0), names.index(st)))[:k]


def style_changed(x: dict) -> bool:
    """Стиль в демо сменился: другой главный из 5 показываемых или другой состав тройки. Неоклассика наверху — не смена:
    в витрине её нет."""
    return x['show3_now'][0] != x['show3_after'][0] or set(x['show3_now']) != set(x['show3_after'])


def style_summary(rows_: list) -> dict:
    fixed = [x for x in rows_ if x.get('fix') and 'after' in x]
    same = [x for x in rows_ if not x.get('fix') and 'after' in x]
    return {'colour_fixed': len(fixed), 'style_changed': sum(1 for x in fixed if style_changed(x)),
            'style_changed_n': [x['n'] for x in fixed if style_changed(x)],
            'noise_cards': len(same), 'noise_changed': sum(1 for x in same if style_changed(x)),
            'noise_changed_n': [x['n'] for x in same if style_changed(x)]}


def believed_colour(col_field: str, name: str) -> str:
    """Какой цвет видел скорер стиля: цвет фида, если он один; иначе (пусто или список исполнений) — из названия."""
    f, _ = feed_colour({'Цвет': col_field})
    return f if f != UNK else name_colour(name)


def style(L: str) -> int:
    from openai_budget import allow, estimate_request, price_of
    import llm_gateway
    from room_catalog import family
    recs = [json.loads(x) for x in open(os.path.join(L, 'golden.jsonl'), encoding='utf-8') if x.strip()]
    meta = json.load(open(os.path.join(L, 'meta.json'), encoding='utf-8'))
    ns = _style_fns()
    snames = ns['SNAMES']
    raw = ns['bedroom_raw']()
    rep, by_id = {}, {}
    for r in raw:                                  # представитель модели — как в style_score: первый в порядке пула
        rep.setdefault((r[9], family(r[3])), r)
        by_id[(int(r[1]), r[2])] = r
    scores = json.load(open(STYLE_FILE, encoding='utf-8'))
    rows_, ctrl_in, corr_in = [], [], []
    for g in recs:
        r = by_id.get((g['mid'], g['eid']))
        if not r:
            rows_.append({'n': g['n'], 'err': 'нет в пуле стиля спальни'})
            continue
        rp = rep[(r[9], family(r[3]))]
        k = f"{rp[1]}-{re.sub(r'[^A-Za-z0-9]', '_', rp[2])[:40]}"
        now = scores.get(k)
        p = dict(role=r[0], mid=int(r[1]), eid=r[2], name=r[3], mat=r[4], col=r[5], uph=r[6], stp=r[7], desc=r[8])
        acc, bel = g['accepted'].get('colour', UNK), believed_colour(r[5], r[3])
        fix = acc not in (UNK, None) and (bel == UNK or not ckeys(acc) & ckeys(bel))
        rows_.append({'n': g['n'], 'key': k, 'rep_name': rp[3], 'src': (now or {}).get('src'), 'now': now, 'fix': fix,
                      'col_before': bel, 'col_feed_raw': r[5], 'col_after': acc if fix else None})
        ctrl_in.append((g['n'], p))
        corr_in.append((g['n'], {**p, 'col': acc} if fix else p))
    calls = 2 * -(-len(ctrl_in) // 15)
    est = estimate_request(MODEL) * calls * 3
    if meta.get('cost_usd', 0) + est > CAP_USD:
        print(f'СТОП: ${meta.get("cost_usd", 0):.4f} + прикидка ${est:.3f} выше потолка ${CAP_USD}', flush=True)
        return 2
    if not allow(MODEL, calls, note=f'bedroom_golden style {calls}'):
        print('СТОП: дневной лимит OpenAI', flush=True)
        return 2
    usage, fails = [], []
    orig = llm_gateway.chat

    def counted(*a, **kw):
        out = orig(*a, **kw)
        usage.append(out.get('usage') or {})
        return out
    llm_gateway.chat = counted                     # llm_batch импортирует chat при вызове — считаем токены здесь

    def run(batch):
        res = {}
        for i in range(0, len(batch), 15):
            part = batch[i:i + 15]
            try:
                got = ns['llm_batch']([p for _, p in part])
            except Exception as e:  # noqa: BLE001 — считаем
                fails.append(f'{type(e).__name__}: {str(e)[:100]}')
                continue
            for j, (n, _) in enumerate(part):
                if j in got:
                    res[n] = got[j]
        return res
    ctrl, corr = run(ctrl_in), run(corr_in)        # раздельные вызовы: исправленный текст не видит исходного
    llm_gateway.chat = orig
    pt, ct = sum(u.get('prompt_tokens', 0) for u in usage), sum(u.get('completion_tokens', 0) for u in usage)
    cost = price_of(MODEL, pt, ct) or 0.0
    for x in rows_:
        n = x['n']
        if 'err' in x or not x['now'] or n not in ctrl or n not in corr:
            x.setdefault('err', 'нет оценки в файле или ответа скорера')
            continue
        d = {st: corr[n][st] - ctrl[n][st] for st in snames}
        after = {st: round(max(0.0, min(10.0, x['now'][st] + d[st])), 1) for st in snames}
        x.update({'ctrl': {st: ctrl[n][st] for st in snames}, 'corr': {st: corr[n][st] for st in snames}, 'after': after,
                  'top2_now': top(x['now'], snames, 2), 'top2_after': top(after, snames, 2),
                  'show3_now': top(x['now'], SHOWN, 3), 'show3_after': top(after, SHOWN, 3)})
        x['changed'] = style_changed(x)
    same = [x for x in rows_ if not x.get('fix') and 'after' in x]
    summ = {'cards': len(recs), **style_summary(rows_),
            'noise_mean_abs': round(sum(abs(x['corr'][st] - x['ctrl'][st]) for x in same for st in snames)
                                    / max(1, len(same) * len(snames)), 2),
            'calls': len(usage), 'fails': fails, 'pt': pt, 'ct': ct, 'cost_usd': cost, 'style_file': STYLE_FILE,
            'style_file_md5': hashlib.md5(open(STYLE_FILE, 'rb').read()).hexdigest()}
    with open(os.path.join(L, 'style.jsonl'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(json.dumps(x, ensure_ascii=False) for x in rows_) + '\n')
    json.dump(summ, open(os.path.join(L, 'style-meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    sheet(recs, L, meta)
    print(json.dumps(summ, ensure_ascii=False), flush=True)
    return 0 if not fails else 1


# ---------- лист для глаз (телефон 375) ----------

FIELD_RU = {'colour': 'Цвет', 'drawers': 'Ящики', 'headboard': 'Изголовье'}


def _field_block(r: dict, f: str) -> str:
    e, m, a, fd = html.escape, r['model'], r['accepted'], r['feed']
    spor = ' <span class="sp">спорно</span>' if f in r['disputes'] else ''
    if f == 'colour':
        src = f'фид: {e(fd["colour_raw"] or "—")} → {e(fd["colour"])}<br>название: {e(fd["colour_by_name"])}'
        mod = f'{e(str(m.get("colour", "—")))}' + (' · <b>несколько исполнений</b>' if m.get('variants_shown') else '')
        res = f'{e(a.get("colour", "—"))} <small>({e(a.get("colour_why", ""))})</small>'
    elif f == 'drawers':
        src = f'по фиду и названию: {e(fd["drawers_rules"])}'
        mod = e(str(m.get('drawers', '—')))
        res = e(a.get('drawers', '—')) + (' <small>(«нет» по фото не принимаем)</small>' if m.get('drawers') == 'нет' else '')
    else:
        hp = fd['headboard_params']
        src = 'в фиде: ' + (e('; '.join(f'{k}: {v}' for k, v in hp.items())) if hp else 'не задано')
        mod = e(str(m.get('headboard', '—'))) + (' · кровать целиком' if m.get('bed_fully_visible') else ' · <b>не целиком</b>')
        res = e(a.get('headboard', '—'))
    nm = f'v{r["n"]}_{f}'
    return (f'<div class="f"><div class="h">{FIELD_RU[f]}{spor}</div><div class="s">{src}</div>'
            f'<div class="m">фото → модель: <b>{mod}</b></div><div class="r">итог: <b>{res}</b></div>'
            f'<div class="v"><label><input type="radio" name="{nm}" value="верно">верно</label>'
            f'<label><input type="radio" name="{nm}" value="неверно">неверно</label></div></div>')


def _style_block(n: int, x: dict) -> str:
    e = html.escape
    radios = (f'<div class="v"><label><input type="radio" name="v{n}_style" value="верно">стиль верно</label>'
              f'<label><input type="radio" name="v{n}_style" value="неверно">стиль неверно</label></div>')
    if not x or 'after' not in x:
        return f'<div class="f"><div class="h">Стиль</div><div class="s">{e((x or {}).get("err", "нет данных"))}</div></div>'
    fmt = lambda sc, names: ' · '.join(f'{st} {sc[st]:g}' for st in names)  # noqa: E731
    out = f'<div class="m">сейчас: <b>{fmt(x["now"], x["top2_now"])}</b></div><div class="s">в демо: {", ".join(x["show3_now"])}</div>'
    if x['fix']:
        out += (f'<div class="s">цвет для стиля: {e(x["col_before"])} → {e(x["col_after"])}</div>'
                f'<div class="m">после поправки: <b>{fmt(x["after"], x["top2_after"])}</b>'
                + (' <span class="chg">стиль сменился</span>' if x['changed'] else '') + '</div>'
                f'<div class="s">в демо: {", ".join(x["show3_after"])}</div>')
    else:
        out += '<div class="s">цвет не поправлен — стиль тот же</div>'
    return f'<div class="f"><div class="h">Стиль</div>{out}{radios}</div>'


def sheet(recs: list, L: str, meta: dict) -> None:
    cards = []
    sp = os.path.join(L, 'style.jsonl')
    sty = {x['n']: x for x in (json.loads(y) for y in open(sp, encoding='utf-8') if y.strip())} if os.path.exists(sp) else None
    sm = json.load(open(os.path.join(L, 'style-meta.json'), encoding='utf-8')) if sty is not None else {}
    if sty is not None:            # флаги и счёт — по текущему правилу смены, из сохранённых ответов
        for x in sty.values():
            if 'after' in x:
                x['changed'] = style_changed(x)
        sm.update(style_summary(list(sty.values())))
    for r in recs:
        if r['photo_file']:
            b64 = base64.b64encode(open(os.path.join(L, r['photo_file']), 'rb').read()).decode()
            img = f'<img src="data:image/jpeg;base64,{b64}" alt="">'
        else:
            img = '<div class="noimg">фото не скачалось</div>'
        fields = ['colour', 'drawers'] + (['headboard'] if r['role'] == 'кровать' else [])
        body = ''.join(_field_block(r, f) for f in fields) if r['model'] else f'<div class="err">нет ответа: {html.escape(r["err"] or "")}</div>'
        x = (sty or {}).get(r['n'])
        if sty is not None:
            body += _style_block(r['n'], x)
        chg = ' chgc' if x and x.get('fix') and x.get('changed') else ''
        cards.append(f'<section class="c{chg}" id="c{r["n"]}"><div class="n">№{r["n"]} · {html.escape(r["role"])} · {html.escape(r["shop"])}</div>'
                     f'{img}<div class="t"><a href="{html.escape(r["url"] or "")}">{html.escape(r["name"])}</a></div>{body}</section>')
    css = (':root{--bg:#fff;--fg:#1a1a1a;--mute:#666;--line:#e3e3e3;--card:#fafafa;--sp:#b45309;--ok:#e6f4ea;--bad:#fde8e8}'
           '@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#eee;--mute:#aaa;--line:#333;--card:#1d1d1d;--sp:#f59e0b;'
           '--ok:#163020;--bad:#3a1717}}'
           '*{box-sizing:border-box}body{margin:0;padding:12px 16px 80px;background:var(--bg);color:var(--fg);'
           'font:15px/1.4 -apple-system,system-ui,sans-serif}main{max-width:560px;margin:0 auto}h1{font-size:18px;margin:4px 0 6px}'
           '.lead{color:var(--mute);font-size:13px;margin:0 0 12px}.c{background:var(--card);border:1px solid var(--line);'
           'border-radius:10px;padding:10px;margin:0 0 16px}.n{color:var(--mute);font-size:13px;margin-bottom:6px}'
           'img{display:block;width:100%;max-height:75vh;object-fit:contain;background:#fff;border-radius:6px}'
           '.noimg{height:200px;display:flex;align-items:center;justify-content:center;background:var(--bad);border-radius:6px}'
           '.t{margin:8px 0 4px;font-weight:600;word-break:break-word}.t a{color:inherit}.f{border-top:1px solid var(--line);'
           'padding:8px 0 4px}.h{font-weight:700}.sp{color:var(--sp);font-weight:600;font-size:12px;margin-left:4px}'
           '.s,.r small{color:var(--mute);font-size:13px;font-weight:400}.m,.r{margin-top:2px}.v{display:flex;gap:8px;margin-top:6px}'
           '.v label{flex:1;border:1px solid var(--line);border-radius:8px;padding:9px 0;text-align:center;font-size:14px}'
           '.v input{margin:0 6px 0 0}.v label:has(input[value="верно"]:checked){background:var(--ok)}'
           '.v label:has(input[value="неверно"]:checked){background:var(--bad)}.err{color:#c00;padding:8px 0}'
           '.bar{position:fixed;left:0;right:0;bottom:0;background:var(--bg);border-top:1px solid var(--line);padding:8px 16px;'
           'display:flex;gap:8px;align-items:center;justify-content:center;font-size:14px}.bar button{padding:8px 12px;'
           'border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);font-size:14px}'
           '.chg{background:var(--sp);color:#fff;border-radius:6px;padding:1px 6px;font-size:12px;font-weight:600;white-space:nowrap}'
           '.c.chgc{border:2px solid var(--sp)}')
    js = ("const K='onb06-golden-'+document.title;let s={};try{s=JSON.parse(localStorage.getItem(K)||'{}')}catch(e){}"
          "const R=[...document.querySelectorAll('input[type=radio]')];"
          "R.forEach(i=>{if(s[i.name]===i.value)i.checked=true;i.addEventListener('change',()=>{s[i.name]=i.value;"
          "try{localStorage.setItem(K,JSON.stringify(s))}catch(e){}cnt()})});"
          "const T=new Set(R.map(i=>i.name)).size;function cnt(){const v=Object.values(s);"
          "document.getElementById('cnt').textContent=`${Object.keys(s).length}/${T} · верно ${v.filter(x=>x==='верно').length}`}"
          "cnt();document.getElementById('cp').onclick=()=>{const t=Object.entries(s).sort().map(([k,v])=>k.slice(1)+' '+v).join('\\n');"
          "navigator.clipboard.writeText(t).then(()=>{document.getElementById('cp').textContent='скопировано'},()=>{prompt('Скопируйте:',t)})}")
    head = (f'<h1>Эталон спальни по фото — {len(recs)} карточек</h1><p class="lead">Модель смотрела только фото (без названия и фида). '
            f'«Итог» — что приняли бы: ящики только «есть», изголовье «нет» только при кровати целиком, цвет — сверка фото с '
            f'названием и фидом. Отметьте, <b>верно ли модель увидела фото</b> (строка «фото → модель»); итог считается из этого по правилам. {html.escape(meta["model_alias"])} '
            f'({html.escape(", ".join(meta["model_ids"]) or "—")}), промпт {meta["prompt_ver"]}/{meta["prompt_hash"]}, '
            f'${meta["cost_usd"]:.4f}.</p>')
    if sm:
        head += (f'<p class="lead"><b>Стиль.</b> «Сейчас» — первые два стиля из файла оценок спальни, «в демо» — три лучших из пяти '
                 f'показываемых (при равенстве — порядок вкладок). Поправка цвета у {sm["colour_fixed"]} карточек, стиль сменился у '
                 f'<b>{sm["style_changed"]}</b> (они в оранжевой рамке). Для сравнения: у {sm["noise_cards"]} карточек без поправки '
                 f'повторный расчёт с тем же текстом сменил стиль у {sm["noise_changed"]} — это шум модели. Стиль — +${sm["cost_usd"]:.4f}.</p>')
    open(os.path.join(L, 'sheet.html'), 'w', encoding='utf-8').write(
        '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Эталон спальни {os.path.basename(L)[-9:]}</title><style>{css}</style></head><body><main>{head}'
        + ''.join(cards) + '</main><div class="bar"><span id="cnt"></span><button id="cp">Скопировать отметки</button></div>'
        f'<script>{js}</script></body></html>')


# ---------- самопроверка ----------

def _selftest() -> int:
    bad = 0

    def ok(name, cond, info=''):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
        bad += 0 if cond else 1
    ok('фид-список исполнений («Бежевый Белый») — не цвет', feed_colour({'Цвет': 'Бежевый Белый'})[0] == UNK)
    ok('фид «Белая Шагрень» — белый; «серо-бежевый» одно слово — не список',
       (feed_colour({'Цвет основной': 'Белая Шагрень'})[0], feed_colour({'Цвет': 'серо-бежевый'})[0]) == ('белый', 'бежевый'))
    ok('спор цвета: фид Зеленый, название Серебряный', 'colour' in disputes('кровать', 'Majesty 140 Серебряный', {'Цвет': 'Зеленый'}))
    ok('нет спора внутри группы палитры (бежевый ↔ белый)', 'colour' not in disputes('шкаф', 'Шкаф Рим Белый', {'Цвет': 'Латте'}))
    ok('изголовье: параметр есть — не спорно; нет — спорно',
       'headboard' not in disputes('кровать', 'Кровать Кейт', {'Материал изголовья': 'ткань'})
       and 'headboard' in disputes('кровать', 'BoxSpring Home', {}))
    ok('комод: ящики не спорны', 'drawers' not in disputes('комод', 'Комод Тест', {}))
    ok('приём: ящики «нет» = неизвестно, «есть» = есть',
       (accept('шкаф', {'drawers': 'нет'})['drawers'], accept('шкаф', {'drawers': 'есть'})['drawers']) == (UNK, 'есть'))
    ok('приём: изголовье «нет» только при кровати целиком',
       (accept('кровать', {'headboard': 'нет', 'bed_fully_visible': True})['headboard'],
        accept('кровать', {'headboard': 'нет', 'bed_fully_visible': False})['headboard'],
        accept('тумба прикроватная', {'headboard': 'нет'})['headboard']) == ('нет', UNK, NA))
    ok('сопоставление: фото = название → название', match_colour('серый', 'серый', 'зелёный', False)[0] == 'серый')
    ok('сопоставление: фото = фид → фид', match_colour('зелёный', 'белый', 'зелёный', False)[0] == 'зелёный')
    ok('сопоставление: группа палитры (дерево тёмное ~ коричневый)', match_colour('дерево тёмное', 'коричневый', 'белый', False)[0] == 'коричневый')
    ok('сопоставление: ни с чем / несколько исполнений → неизвестно',
       match_colour('синий', 'белый', 'зелёный', False)[0] == UNK and match_colour('серый', 'серый', 'белый', True)[0] == UNK)
    ok('стиль: тройка показа — из 5 без неоклассики, ничья — порядок вкладок',
       top({'сканди': 7, 'современный': 7, 'минимализм': 5, 'лофт': 7, 'неоклассика': 9, 'джапанди': 6}, SHOWN, 3)
       == ['сканди', 'современный', 'лофт'])
    ok('стиль: видимый скорером цвет — фид, если он один; список исполнений или пусто — название',
       (believed_colour('Зеленый', 'Кровать Серебряный'), believed_colour('Бежевый Белый', 'Шкаф Серый'),
        believed_colour('', 'Тумба Латте')) == ('зелёный', 'серый', 'бежевый'))
    ns = _style_fns()
    ok('стиль: функции боевого скорера найдены по исходнику', all(k in ns for k in ('llm_batch', 'bedroom_raw', 'SNAMES')))
    ok('цвет: «Серо-зеленый» — составной; фото «серый» и фид «Зеленый» с ним совпадают (эталон №26/29)',
       name_colour('Комод divan.ru Лигес 93x87 Серо-зеленый') == 'серо-зелёный'
       and match_colour('серый', 'серо-зелёный', 'зелёный', False)[0] == 'серо-зелёный'
       and 'colour' not in disputes('комод', 'Комод Лигес 93x87 Серо-зеленый', {'Цвет основной': 'Зеленый'}))
    ok('цвет: фото = фид точно, название той же группы — берём фид (№6: белый, «Молочный»)',
       match_colour('белый', 'бежевый', 'белый', False)[0] == 'белый')
    ok('цвет: «Розетта» — не розовый, «Графитовый» — серый',
       (name_colour('Тумба Тайрон 51x48 Розетта'), name_colour('Комод Блест 200x87 Графитовый')) == (UNK, 'серый'))
    ok('цвет: «А/Б» в названии — главный первый («Дуб Барбера/Черный», «Латте/Черный»)',
       (name_colour('Шкаф Кимбол-1-50x210 Дуб Барбера/Черный'), name_colour('Шкаф Кимбол 3.1-170x280 Латте/Черный'))
       == ('дерево светлое', 'бежевый'))
    ok('промпт: в системном тексте нет подсказок цвета из карточки', '{' not in SYS and len(PROMPT_HASH) == 12)
    print('FAILS', bad)
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if '--recount' in sys.argv:    # правила поменялись — пересчёт по сохранённым ответам, сверка с отметками ведущего
        D = os.path.expanduser(sys.argv[sys.argv.index('--recount') + 1]).rstrip('/')
        sys.exit(recount(D, sys.argv[sys.argv.index('--marks') + 1] if '--marks' in sys.argv else None))
    if '--sheet' in sys.argv:      # пересобрать лист из сохранённых ответов, без модели и денег
        D = os.path.expanduser(sys.argv[sys.argv.index('--sheet') + 1]).rstrip('/')
        sheet([json.loads(x) for x in open(os.path.join(D, 'golden.jsonl'), encoding='utf-8') if x.strip()], D,
              json.load(open(os.path.join(D, 'meta.json'), encoding='utf-8')))
        sys.exit(print('лист:', os.path.join(D, 'sheet.html')))
    if '--style' in sys.argv:      # стиль сейчас и после поправки цвета; лист пересобирается
        sys.exit(style(os.path.expanduser(sys.argv[sys.argv.index('--style') + 1]).rstrip('/')))
    if '--golden' in sys.argv:
        sys.exit(run(int(sys.argv[sys.argv.index('--golden') + 1]), '--dry' in sys.argv))
    print(__doc__)
