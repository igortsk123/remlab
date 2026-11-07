#!/usr/bin/env python3
"""ОБЩИЕ ЧИСТЫЕ ФУНКЦИИ СБОРЩИКОВ НАБОРОВ (план onb-06 Т3, вариант Б): цвет товара по фото, палитра, акцентные пары стиля.

Вынесены из `compose2.py` БЕЗ изменений (живой банк гостиной до/после выноса — побайтно равен, отчёт T-20261105-31).
Импорт лёгкий: каталог и сборка не запускаются (у `compose2.py` импорт исполняет полную сборку — урок «import-ловушка scout»),
поэтому сборщик спальни `compose_bedroom.py` берёт их отсюда, а не из `compose2`.
"""
import colorsys
import concurrent.futures as cf
import io
import math
import os
import re
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
THUMBS = os.path.join(HERE, 'thumbs')

# акцентная пара под стиль (из дизайнерских гармоний PAIRS ниже)
STYLE_PAIR={'сканди':('terra','green'),'современный':('blue','yellow'),'минимализм':('green','yellow'),
            'лофт':('terra','cyan'),'неоклассика':('blue','yellow'),'джапанди':('terra','green')}


def thumb_path(mid,eid): return os.path.join(THUMBS, f"{mid}-{re.sub(r'[^A-Za-z0-9]','_',eid)[:40]}.png")
def get_thumb(url,mid,eid):
    p=thumb_path(mid,eid)
    if os.path.exists(p): return p
    try:
        small=url.replace('/big.jpg','/small.jpg').replace('/big.png','/small.png')
        if small.startswith('//'): small='https:'+small
        req=urllib.request.Request(small,headers={'User-Agent':'Mozilla/5.0'})
        data=urllib.request.urlopen(req,timeout=20).read()
        im=Image.open(io.BytesIO(data)).convert('RGB'); im.thumbnail((110,82)); im.save(p,'PNG')
        return p
    except Exception: return None

# ---------- Ф2: цвет — ДВА кластера + температура ----------
def dominant2(p):
    try:
        im=Image.open(p).convert('RGB'); w,h=im.size
        px=list(im.getdata())
        bw=max(2,int(min(w,h)*0.10))
        border=[px[y*w+x] for y in range(h) for x in range(w) if x<bw or x>=w-bw or y<bw or y>=h-bw]
        bq=Image.new('RGB',(len(border),1)); bq.putdata(border)
        bq=bq.quantize(3).convert('RGB')
        bc={}
        for c in bq.getdata(): bc[c]=bc.get(c,0)+1
        bg=[c for c,n in bc.items() if n>=len(border)*0.18]
        def near_bg(c):
            if c[0]>232 and c[1]>232 and c[2]>232: return True
            return any(abs(c[0]-b[0])+abs(c[1]-b[1])+abs(c[2]-b[2])<95 for b in bg)
        inner=[px[y*w+x] for y in range(int(h*.12),int(h*.88)) for x in range(int(w*.12),int(w*.88))]
        obj=[c for c in inner if not near_bg(c)]
        if len(obj)<len(inner)*0.06 or len(obj)<30:
            obj=[c for c in inner if not (c[0]>225 and c[1]>225 and c[2]>225)] or inner
        q=Image.new('RGB',(len(obj),1)); q.putdata(obj)
        q=q.quantize(5).convert('RGB')
        counts={}
        for c in q.getdata(): counts[c]=counts.get(c,0)+1
        top=sorted(counts,key=counts.get,reverse=True)[:2]
        return top[0], (top[1] if len(top)>1 else top[0])
    except Exception: return None,None
def classify(rgb):
    if rgb is None: return 'unknown'
    r,g,b=[x/255 for x in rgb]; h,s,v=colorsys.rgb_to_hsv(r,g,b); hue=h*360
    if s<0.13:
        return 'neutral_light' if v>0.72 else ('neutral_dark' if v<0.3 else 'neutral_grey')
    if 15<=hue<=50 and s<0.55:
        return 'wood_light' if v>0.55 else 'wood_dark'
    for name,(lo,hi) in {'terra':(5,30),'yellow':(30,70),'green':(70,165),'cyan':(165,205),
                          'blue':(205,255),'violet':(255,300),'pink':(300,345),'red':(345,365)}.items():
        if lo<=hue<hi or (name=='red' and hue<5): return 'accent_'+name
    return 'accent_other'
def temperature(rgb):
    if rgb is None: return 'mid'
    r,g,b=rgb
    return 'warm' if r>b+10 else ('cold' if b>r+10 else 'mid')
NEUTRALS={'neutral_light','neutral_grey','neutral_dark','wood_light','wood_dark','unknown'}
# дизайнерские акцентные ПАРЫ (60-30-10: два дружащих акцента на сет)
PAIRS=[('terra','green'),('blue','yellow'),('green','yellow'),('terra','cyan'),
       ('pink','green'),('violet','yellow'),('cyan','terra')]
def palette_score(cls1,cls2,pair,set_temp,rgb1):
    s=0.0
    ac={'accent_'+p for p in pair}
    for cls in (cls1,cls2):
        if cls in NEUTRALS: s+=1.0
        elif cls in ac: s+=1.6
        else: s-=2.2          # чужой акцент — главный источник «пестроты»
    if cls1 in ('neutral_light','neutral_grey') and set_temp!='mid':
        t=temperature(rgb1)
        s+= 0.8 if t==set_temp or t=='mid' else -1.2   # тёплые и холодные нейтрали не смешивать
    return s


# ---------- общие чистые функции сборщиков комнат (вынесены из `compose_bedroom.py` без изменений, T-20261105-48) ----------
def num(v):
    try:
        f = float(v)
        return f if f > 0 and math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def side(it: dict, k: str):
    """Сторона товара для полосы: w/d/h, у ковра — длинная (`long`; в фидах `w` бывает короткой)."""
    if k == 'long':
        a, b = num(it.get('w')), num(it.get('d'))
        return max(a, b) if a and b else (a or b)
    return num(it.get(k))


def band_of(slot: dict, tol: tuple) -> dict:
    """Полоса слота: {сторона: [lo, hi]} по `band` и идеалу, допуск tol = (0.8, 1.1)."""
    lo, hi = tol
    return {k: [round(slot['ideal'][k] * lo, 1), round(slot['ideal'][k] * hi, 1)] for k in slot.get('band', [])}


def slot_sizes(slot: dict) -> list:
    """Типоразмеры слота (T-20261106-90, К9): основной (сам `ideal` слота) + `sizes` правил — [{id, ideal}], ideal типоразмера
    поверх основного (не заданная сторона — как у основного). Допуск полосы — тот же −20…+10 % внутри КАЖДОГО (`band_of`).
    Без `sizes` — один основной (спальня и гостиная — как было). → список слотов с полем `size` (id типоразмера)."""
    base = {k: v for k, v in slot.items() if k != 'sizes'}
    out = [dict(base, size=slot.get('size') or 'основной')]
    for s in slot.get('sizes') or ():
        out.append(dict(base, ideal=dict(slot.get('ideal') or {}, **s['ideal']), size=s['id']))
    return out


def tier_range(prices: list, q: tuple) -> tuple:
    """Квантили цены тира (как `compose2.tier_band`): q = (низ, верх) доли."""
    ps = sorted(prices)
    if not ps:
        return (0, 10 ** 9)

    def pc(p):
        return ps[max(0, min(len(ps) - 1, int(p * len(ps))))]
    return (pc(q[0]), pc(q[1]))


def dominated(it: dict, cands: list) -> set:
    """Не встал предмет Ш×Г — не встанут и все, что не меньше по обеим сторонам (спальня 2, 13,2 м²: 12 попыток подряд
    на кроватях 220–230 в глубину, ячейка пустела, хотя 213 встаёт). Отсекаем их разом, а не по одной."""
    return {c['sid'] for c in cands if c['w'] >= it['w'] and c['d'] >= it['d']} | {it['sid']}


def temp_score(cls1, set_temp, rgb1) -> float:
    """Температура нейтрали к набору — та же часть `palette_score` (тёплые и холодные нейтрали не смешивать), без пары акцентов:
    у крупной мебели пара стиля больше не награждает (style-color-01)."""
    if cls1 in ('neutral_light', 'neutral_grey') and set_temp != 'mid':
        t = temperature(rgb1)
        return 0.8 if t == set_temp or t == 'mid' else -1.2
    return 0.0


# ---------- цвет по стилю и роли (план style-color-01, шаг 1): правила — rules/style-color-policy.json ----------
COLOR_POLICY = os.path.join(HERE, 'rules', 'style-color-policy.json')
_POLICY: dict = {}
_WORD = re.compile(r'[а-яё]+(?:-[а-яё]+)*')


def color_policy(path: str | None = None) -> dict:
    """Правила цвета (кэш по пути) с проверкой полноты: у каждого стиля — ярус на каждую группу × категорию. Слова — в регэкспы."""
    import json
    path = path or COLOR_POLICY
    if path in _POLICY:
        return _POLICY[path]
    P = json.load(open(path, encoding='utf-8'))
    tiers, cats = set(P['tiers']), P['categories']
    bad = []
    for st, S in P['styles'].items():
        for g in P['groups']:
            row = (S.get('tiers') or {}).get(g) or {}
            bad += [f'{st}/{g}/{c}: {row.get(c)!r}' for c in cats if row.get(c) not in tiers]
        for g, by in (S.get('rank') or {}).items():
            bad += [f'{st}/rank/{g}/{t}: {r!r}' for t, r in by.items()
                    if g not in P['groups'] or t not in P['tier_rank'] or not isinstance(r, int)]
        for g, by in (S.get('family_tiers') or {}).items():
            bad += [f'{st}/{g}/{c}/{f}: {t!r}' for c, fm in by.items() for f, t in fm.items() if t not in tiers]
    if not P.get('version') or not P.get('provenance'):
        bad.append('нет version/provenance')
    if bad:
        raise ValueError('style-color-policy: ' + '; '.join(bad[:8]))
    N = P['names']
    full = lambda rx: re.compile(f'(?:{rx})', re.I)  # noqa: E731
    P['_rx'] = {'families': [(f, full(rx)) for f, rx in N['families'].items()], 'material': full(N['material']),
                'neutral': full(N['neutral']), 'vivid': re.compile(N['vivid'], re.I), 'muted_mod': re.compile(N['muted_mod'], re.I)}
    P['_role_group'] = {r: g for g, rs in P['groups'].items() for r in rs}
    _POLICY[path] = P
    return P


def color_group(role: str, P: dict) -> str:
    """Группа роли (`groups` правил); «тумба прикроватная 2» → без номера; нет в правилах — `default_group`."""
    return P['_role_group'].get(re.sub(r'\s+\d+$', '', role or ''), P['default_group'])


def _name_tokens(name: str, P: dict) -> list:
    """Цветовые слова названия по порядку: (вид, семья, приглушённое, яркое). Вид — chroma | material | neutral."""
    rx, out = P['_rx'], []
    for w in _WORD.findall((name or '').lower()):
        parts = w.split('-')
        fam = next(((f, p) for p in parts for f, r in rx['families'] if r.fullmatch(p)), None)
        if fam:
            others = [p for p in parts if p != fam[1]]
            muted = any(rx['muted_mod'].match(p + '-') or rx['neutral'].fullmatch(p) for p in others)
            out.append(('chroma', fam[0], muted, bool(rx['vivid'].search(fam[1]))))
        elif any(rx['material'].fullmatch(p) for p in parts):
            out.append(('material', None, False, False))
        elif any(rx['neutral'].fullmatch(p) for p in parts):
            out.append(('neutral', None, False, False))
    return out


def _hsv(rgb):
    if not rgb:
        return None
    h, s, v = colorsys.rgb_to_hsv(*[x / 255 for x in rgb])
    return h * 360, s, v


def color_evidence(it: dict, P: dict) -> tuple:
    """Цвет товара без стиля → (категория, семья, источник). Название — главный признак (цвет из каталога); нет цвета в
    названии — фото (`cls`/`rgb` из `palette`): уверенный только при насыщенности ≥ confident_min, оттенок дерева — материал."""
    S = P['saturation']
    tk = _name_tokens(it.get('name'), P)
    hsv = _hsv(it.get('rgb'))
    if tk:
        kind, fam, muted, vivid = tk[0]
        if kind == 'chroma':
            ph = P['photo_family'].get(it.get('cls') or '')
            strong = bool(hsv and ph == fam and hsv[1] >= S['vivid_min'] and hsv[2] >= S['vivid_v_min'])
            return ('vivid' if (vivid or strong) and not muted else 'muted'), fam, 'название'
        sec = next((t for t in tk[1:] if t[0] == 'chroma'), None)
        if sec:
            return 'secondary', sec[1], 'название (второй цвет)'
        return kind, None, 'название'
    cls = it.get('cls') or 'unknown'
    if not cls.startswith('accent_') or not hsv:
        return ('material' if cls.startswith('wood_') else 'neutral'), None, 'фото' if it.get('cls') else 'нет данных'
    hue, s, v = hsv
    if S['wood_hue'][0] <= hue <= S['wood_hue'][1] and cls in ('accent_terra', 'accent_yellow'):
        return 'material', None, 'фото (оттенок дерева)'
    fam = P['photo_family'].get(cls, 'other')
    if s < S['confident_min']:
        return 'weak', fam, f'фото, насыщенность {s:.2f}'
    if s >= S['vivid_min'] and v >= S['vivid_v_min']:
        return 'vivid', fam, f'фото, насыщенность {s:.2f}'
    return 'muted', fam, f'фото, насыщенность {s:.2f}'


CAT_RU = {'neutral': 'нейтральный', 'material': 'материал', 'weak': 'неуверенный цвет', 'muted': 'приглушённый цвет',
          'vivid': 'яркий цвет', 'secondary': 'второй цвет'}


def color_eval(it: dict, role: str, style: str, P: dict | None = None, ctx: dict | None = None) -> dict:
    """ОДИН оценщик цвета (сборщики спальни, прихожей и квота мешей). Чистая функция: товар (name, cls, rgb) × роль × стиль
    → {tier, rank, delta, why, cat, family, group, major, anchor}; rank — место в ключе ранжирования (`styles.<стиль>.rank`
    переопределяет `tier_rank` по группе). ctx['chroma'] — сколько цветных якорей уже в наборе: сверх
    `max_chromatic_anchors` стиля следующий цветной крупный — discouraged. Стиля нет в правилах — allowed без причины."""
    P = P or color_policy()
    S = P['styles'].get(style)
    g = color_group(role, P)
    major = g in P['major_groups']
    if S is None:
        return {'tier': 'allowed', 'rank': P['tier_rank']['allowed'], 'delta': 0.0, 'why': '', 'cat': None, 'family': None, 'group': g, 'major': major,
                'anchor': False}
    cat, fam, src = color_evidence(it, P)
    if cat in ('muted', 'vivid', 'secondary') and fam in S.get('material_families', ()):
        cat, src = 'material', src + f', {fam} — материал стиля'
    tier = S['tiers'][g][cat]
    tier = ((S.get('family_tiers') or {}).get(g) or {}).get(cat, {}).get(fam, tier)
    anchor = major and cat in P['anchor_categories']
    why = f'цвет: {CAT_RU[cat]}' + (f' {fam}' if fam else '') + f' ({src}) → {tier}'
    lim = S.get('max_chromatic_anchors')
    if anchor and tier != 'forbidden' and lim is not None and (ctx or {}).get('chroma', 0) >= lim:
        if P['tier_rank'][tier] < P['tier_rank']['discouraged']:
            tier = 'discouraged'
            why += f' → discouraged (цветных якорей в наборе уже {ctx["chroma"]}, предел {lim})'
    rank = ((S.get('rank') or {}).get(g) or {}).get(tier, P['tier_rank'].get(tier))
    return {'tier': tier, 'rank': rank, 'delta': P['delta'].get(tier, 0.0), 'why': why, 'cat': cat, 'family': fam, 'group': g,
            'major': major, 'anchor': anchor}


def color_tier(it: dict, role: str, style: str, P: dict | None = None, ctx: dict | None = None) -> tuple:
    """(ярус, дельта, причина) — короткая форма `color_eval`."""
    e = color_eval(it, role, style, P, ctx)
    return e['tier'], e['delta'], e['why']


def color_rank(tier: str | None, P: dict | None = None) -> int:
    """Место яруса в ключе ранжирования: preferred 0 → allowed 1 → discouraged 2 (forbidden в ранжирование не попадает)."""
    return (P or color_policy())['tier_rank'].get(tier or 'allowed', 1)


def color_anchors(chosen: dict, style: str, P: dict | None = None) -> int:
    """Сколько цветных якорей в наборе {роль: товар} (для предела `max_chromatic_anchors`)."""
    return sum(1 for r, c in chosen.items() if color_eval(c, r, style, P)['anchor'])


def pillow_pair(style: str | None, fallback=None, P: dict | None = None) -> tuple:
    """Цель-цвет подушек гостиной (шаг 2б, T-20261107-25/3): `pillow_pair` стиля правил, нет — `pair`; стиля нет в правилах —
    `fallback` (прежняя пара сборщика). Пустой кортеж — подушки без цели-цвета (минимализм, джапанди)."""
    P = P or color_policy()
    S = P['styles'].get(style or '')
    if S is None:
        return tuple(fallback or ())
    return tuple(S.get('pillow_pair', S.get('pair') or ()))


def color_split(scored: list, role: str, style: str | None, chosen: dict | None = None, P: dict | None = None,
                groups: tuple | None = None) -> list:
    """ЯРУС ЦВЕТА ДО МЕША В ГОСТИНОЙ (style-color-01 шаг 2а, T-20261107-25/2): [(балл, товар)] уже отсортирован → группы по
    рангу яруса (preferred → allowed → discouraged), forbidden выбывает, порядок внутри группы прежний. Бонус готовому мешу
    (`bank_keep.mesh_tiebreak`) сборщик применяет внутри группы — меш не поднимает товар через ярус (как у спальни).
    Роль не из крупных групп или стиль без правил — одна группа, как было. `chosen` — уже выбранное набора (предел цветных
    якорей `max_chromatic_anchors`); у товара — name, cls, rgb (как у `color_eval`). `groups` — группы ролей, которые делим
    (по умолчанию `major_groups`; мягкое гостиной — шаг 2б, сборщик добавляет soft_textile)."""
    P = P or color_policy()
    if not style or style not in P['styles'] or color_group(role, P) not in (groups or P['major_groups']):
        return [list(scored)] if scored else []
    ctx = {'chroma': color_anchors({r: c for r, c in (chosen or {}).items() if c}, style, P)}
    out: dict = {}
    for x in scored:
        e = color_eval(x[1], role, style, P, ctx)
        if e['tier'] == 'forbidden':
            continue
        out.setdefault(e['rank'], []).append(x)
    return [out[k] for k in sorted(out)]


def palette(items: list) -> None:
    """Цвет по фото (`compose_common`): маленькая картинка в кэш thumbs/, два доминанта и класс — в товар."""
    os.makedirs(THUMBS, exist_ok=True)

    def one(it):
        p = get_thumb(it['img'], it['mid'], it['eid']) if it.get('img') else None
        d1, d2 = dominant2(p) if p else (None, None)
        return it, d1, d2
    with cf.ThreadPoolExecutor(8) as ex:
        for it, d1, d2 in ex.map(one, [i for i in items if 'cls' not in i]):
            it['rgb'], it['cls'], it['cls2'] = (list(d1) if d1 else None), classify(d1), classify(d2)
