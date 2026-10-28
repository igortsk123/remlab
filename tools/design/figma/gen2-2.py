# КОПИЯ gen2.py помощника 2 (26.10, design-01 п.5): + постраничные правила "rules-h2" (список) в pages/*.json — основной gen2.py их не видит.
#   box-text      — подпись «в коробке» с многоточием (кнопка) — во всю ширину коробки, по центру: на сайте она шире замера не бывает
#                   обрезана, а Inter шире системного шрифта (иначе «Ипоте…»);
#   fit-kids      — рамка по высоте вмещает детей (на сайте текст вылезает на 1 px за коробку — проверка считает это вылетом);
#   native-radio  — нативная радиокнопка (`input` без стилей в выгрузке) -> кружок 18 px: отмечена (state=included/on/selected) —
#                   кольцо и точка цвета «Бренд/Основной», иначе — серое кольцо (index.html `.favcard .inc-l input{accent-color}`);
#   center-overlay — абсолютная надпись размером с родителя (`.nopv`, place-items:center) — по центру;
#   badge-wrap    — значок-счётчик вылезает за круглую кнопку (`.hm-fav b{top:-3px;right:-3px}`) -> вариант = прозрачная рамка
#                   вокруг кнопки и значка, без вылета за вариант.
# п.5 design-01: спецификация (build-spec, SPEC_LIMIT=0) -> данные сборщика v2 (страница Фигмы: секции -> наборы -> варианты).
#   python3 gen2.py <S> <phone|desktop> <страница RU, напр. «Бюджет»> <out-префикс>
#   S — папка выгрузки (figma-spec/, tokens.json). Пишет <out>.json (данные) и <out>.b64 (zlib+base64 для use_figma).
# Правила (критерии п.5 плана):
# - позиции детей — от родителя; auto-layout только там, где он ставит детей туда же, где они на сайте (иначе свободная раскладка);
#   ряд «слева … справа» (margin-left:auto) — auto-layout с растяжимым «Отступом»;
# - текст: кегль/вес/высота строки с сайта, ширина — из замера, число строк с сайта; в auto-layout одна строка — по содержимому;
#   обёртка ровно вокруг одного текста схлопывается в сам текст;
# - фото/холст — адрес картинки (заливается upload_assets), значки — svg, штриховка — полосы svg;
# - на набор — секция с понятным названием и строкой «что это»; у варианта — подпись.
import math, json, sys, os, glob, zlib, base64
HERE = os.path.dirname(os.path.abspath(__file__))
if len(sys.argv) > 1 and sys.argv[1] in ('img', 'up', 'install'):
    sys.path.insert(0, HERE); import transfer  # noqa: E402  картинки: скачать/WebP→PNG/залить — transfer.py
    sys.exit(transfer.main(sys.argv[1:]))
if len(sys.argv) < 5:
    sys.exit('python3 gen2.py <папка выгрузки, напр. spec/s1653> <phone|desktop> <Страница> <out-префикс>   (см. README.md)')
S, dev, PAGE, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
# словари: общие — pages/_common.json, постраничное — pages/<Страница>.json (владелец кода — один помощник, 26.10)
C = json.load(open(os.path.join(HERE, 'pages', '_common.json'), encoding='utf-8'))
PF = os.path.join(HERE, 'pages', PAGE + '.json')
if not os.path.exists(PF) and '--skeleton' not in sys.argv:
    sys.exit(f'нет pages/{PAGE}.json — создайте его (образец: pages/Шторка.json; черновик списка элементов: '
             f'python3 gen2.py {S} {dev} {PAGE} - --skeleton > pages/{PAGE}.json)')
PG = json.load(open(PF, encoding='utf-8')) if '--skeleton' not in sys.argv else {'components': {}}
COLOR, RADIUS, CAT, PROP = C['colors'], C['radius'], C['categories'], C['props']
VAL = dict(C['values'])
CLS, SUB = C['layerNames'], C['layerSub']
def text_role(size):
    return 'Заголовок' if size >= 20 else ('Подзаголовок' if size >= 16 else ('Текст' if size >= 13 else 'Подпись'))
CMP = PG['components']  # элемент сайта -> {sec, say, equalWidth?, setBg?, valueNames?, textFix?, rule?}
T = json.load(open(f"{S}/tokens.json"))
W = {300: 'Regular', 400: 'Regular', 500: 'Medium', 600: 'Semibold', 700: 'Bold', 800: 'Bold', 900: 'Bold'}
# исправления текста выгрузки (pages/*.json textFix: состояние -> {было: стало}); напр. отмеченное сердечко — «♥» (index.html:3817)
def txt_fix(n, m):
    t = n.get('text')
    if isinstance(t, dict) and t.get('content') in m: t['content'] = m[t['content']]
    for c in n.get('children') or []: txt_fix(c, m)

def hname(el, kind):
    tag, *cls = el.split('#')[0].split('.') if '#' not in el else (el.split('#')[0], *el.split('#', 1)[1].split('.')[1:])
    for c in cls:
        if c in CLS:
            nm = CLS[c]
            extra = [SUB[k] for k in cls if k in SUB and k != c]
            if c in ('sg', 'sw') and extra: nm += ' — ' + extra[0]
            return nm
    return {'HORIZONTAL': 'Ряд', 'VERTICAL': 'Колонка'}.get(kind, 'Блок')

def fmt(sz): return str(int(sz)) if sz == int(sz) else str(round(sz, 1))
def px(v):
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, dict): return float(v.get('px') or 0)
    try: return float(str(v).replace('px', ''))
    except Exception: return 0.0
def fw(v):
    try: return W.get(int(round(float(v) / 100) * 100), 'Regular')
    except Exception: return 'Regular'

def color(o):
    if not isinstance(o, dict): return None
    if 'token' in o:
        g, n = o['token'].split('.', 1)
        if g == 'color':
            if n in COLOR and n != 'warn': return {'v': 'Цвета:' + COLOR[n]}
            v = T['color'].get(n, {}).get('$value', '')
            if isinstance(v, str) and v.startswith('{color.'): return color({'token': v[1:-1]})
            return {'hex': o.get('approx') or v} if str(o.get('approx') or v).startswith('#') else None
        return None
    if o.get('hex'): return {'hex': o['hex']}
    return None
def space(o):
    if isinstance(o, dict) and str(o.get('token', '')).startswith('space.'): return {'v': 'Отступы:' + o['token'][6:], 'px': o.get('px')}
    return {'px': px(o)}
def radius(rr, w, h):
    if not rr: return None
    if rr.get('circle'): return {'px': min(w, h) / 2}
    if 'corners' in rr: return {'c': [min(w, h) / 2 if c.get('circle') else px(c.get('px', 0)) for c in rr['corners']]}
    if 'token' in rr:
        n = rr['token'].split('.', 1)[1]
        p = rr.get('px') or px(T['radius'].get(n, {}).get('$value', 0))
        if n == 'pill': p = min(p, min(w, h) / 2)
        if n in RADIUS and n not in ('literal-50_', 'pill'): return {'v': 'Скругления:' + RADIUS[n], 'px': p}
        return {'px': p}
    return {'px': px(rr.get('px', 0))}

def tstyle(n):
    """-> (имя стиля Фигмы, кегль, начертание, высота строки px)"""
    st = n['text'].get('style') or {}
    if 'token' in st:
        k = st['token'].split('.', 1)[1]; tv = T['typography'][k]; v = tv['$value']
        sz = px(v['fontSize']); w_ = W[int(v['fontWeight'])]
        lh = px(tv.get('$extensions', {}).get('remlab', {}).get('lineHeightPx') or 0) or (sz * px(v.get('lineHeight')) if px(v.get('lineHeight')) else 0)
    else:
        sz = px(st.get('size') or 14); w_ = fw(st.get('weight') or 400)
        lh = px(st.get('lineHeight')) if str(st.get('lineHeight', '')).endswith('px') else 0
    return f"{text_role(sz)}/{fmt(sz)} {w_}", sz, w_, lh

TOL = 2.5
def fits_auto(r, kids):
    """auto-layout ставит детей туда же, где на сайте? -> (да/нет, индекс «Отступа» или None)"""
    m = r.get('m')
    if m not in ('HORIZONTAL', 'VERTICAL') or r.get('wrap'): return False, None
    flow = [k for k in kids if not k.get('abs')]
    if not flow: return True, None
    p = [px(x) for x in (r.get('p') or [0, 0, 0, 0])]
    g = px(r.get('g') or 0); hor = m == 'HORIZONTAL'
    main = [k['w'] if hor else k['h'] for k in flow]
    inner = (r['w'] - p[1] - p[3]) if hor else (r['h'] - p[0] - p[2])
    start = p[3] if hor else p[0]
    pa = r.get('pa', 'MIN'); tot = sum(main) + g * (len(flow) - 1)
    if pa == 'SPACE_BETWEEN' and len(flow) > 1: gg = (inner - sum(main)) / (len(flow) - 1); pos0 = start
    else: gg = g; pos0 = start + {'CENTER': (inner - tot) / 2, 'MAX': inner - tot}.get(pa, 0)
    # поперечная ось
    ca = r.get('ca', 'MIN')
    cin = (r['h'] - p[0] - p[2]) if hor else (r['w'] - p[1] - p[3]); cst = p[0] if hor else p[3]
    for k in flow:
        cs = k['h'] if hor else k['w']; cgot = k['y'] if hor else k['x']
        if ca == 'BASELINE': continue
        want = cst + {'CENTER': (cin - cs) / 2, 'MAX': cin - cs}.get(ca, 0)
        if ca == 'STRETCH' and abs(cs - cin) > TOL: return False, None
        if abs(cgot - want) > TOL: return False, None
    # главная ось: подряд с шагом; допускается один «прыжок», после которого остальные прижаты к концу
    cur = pos0; spacer = None
    for i, (k, sz) in enumerate(zip(flow, main)):
        got = k['x'] if hor else k['y']
        if abs(got - cur) > TOL:
            if spacer is not None or pa not in ('MIN', None) or i == 0: return False, None
            end = start + inner; e2 = end
            for kk, s2 in reversed(list(zip(flow[i:], main[i:]))):
                if abs((kk['x'] if hor else kk['y']) + s2 - e2) > TOL: return False, None
                e2 = (kk['x'] if hor else kk['y']) - g
            if got - (cur - gg) < 2 * g - TOL: return False, None
            spacer = i; cur = got
        cur += sz + gg
    return True, spacer

def text_node(n, ox, oy):
    x = n['text']; sz_ = n.get('size') or {'w': 0, 'h': 0}; pos = n.get('pos') or {'x': ox, 'y': oy}
    ts, sz, w_, lh = tstyle(n)
    w, h = sz_['w'], sz_['h']
    lines = n.get('lines') or (max(1, round(h / lh)) if lh else 1)
    nowrap = x.get('wrap') is False or x.get('truncate')
    if nowrap: lines = 1
    if not lh: lh = round(h / lines, 2) if h else round(sz * 1.5, 2)
    if h and h / lines >= sz and h / lines < lh: lh = round(h / lines, 2)  # рамка сайта ниже токена — не вылезать из неё
    H = round(lines * lh, 2)
    r = {'t': 'T', 'c': x.get('content', ''), 'ts': ts, 'sz': sz, 'st': w_, 'lh': lh, 'ln': lines,
         'w': w, 'h': H, 'x': round(pos['x'] - ox, 1), 'y': round(pos['y'] - oy + (h - H) / 2, 1)}
    if nowrap: r['nw'] = 1
    if x.get('truncate'): r['tr'] = 1
    if x.get('transform') == 'uppercase': r['up'] = 1
    if x.get('decoration') == 'underline': r['ud'] = 1  # подчёркнутая ссылка (26.10, совместимо: старый сборщик поле не читает)
    c = color(x.get('color')) if x.get('color') else None
    if c: r['tc'] = c
    al = x.get('align', 'left'); r['al'] = 'C' if al == 'center' else 'R' if al in ('right', 'end') else 'L'
    if n.get('runs'):
        rr = []
        for q in n['runs']:
            o = {'s': q['s'], 'e': min(q['e'], len(r['c']))}
            if q.get('fw') and fw(q['fw']) != w_: o['st'] = fw(q['fw'])
            if q.get('size') and abs(px(q['size']) - sz) > 0.1: o['sz'] = px(q['size'])
            cc = color(q.get('color')) if q.get('color') else None
            if cc and cc != r.get('tc'): o['tc'] = cc
            if len(o) > 2 and o['e'] > o['s']: rr.append(o)
        if rr: r['runs'] = rr
    r['n'] = hname(n.get('name', ''), 'T') if any(c in CLS for c in n.get('name', '').split('.')[1:]) else None
    if not r['n']: del r['n']
    r['css'] = n.get('name', '')
    return r

STATS = {'svg': 0, 'img': 0, 'hatch': 0, 'spacer': 0, 'auto': 0, 'free': 0, 'collapsed': 0, 'text': 0}
def conv(n, ox=0, oy=0):
    """ox,oy — место родителя на сайте (от корня образца)"""
    ty = n['type']
    if ty == 'TEXT': STATS['text'] += 1; return text_node(n, ox, oy)
    pos = n.get('pos') or {'x': ox, 'y': oy}; ax, ay = pos['x'], pos['y']
    w, h = n['size']['w'], n['size']['h']
    r = {'w': w, 'h': h, 'x': round(ax - ox, 1), 'y': round(ay - oy, 1), 'css': n.get('name', '')}
    L = n.get('layout') or {}
    if n.get('positioning') == 'ABSOLUTE' or str(L.get('positioning', '')).startswith('ABSOLUTE'): r['abs'] = 1
    if ty == 'SVG': STATS['svg'] += 1; r['t'] = 'S'; r['svg'] = n['svg']; r['n'] = 'Значок'; return r
    if ty == 'IMAGE':
        STATS['img'] += 1; im = n.get('image') or {}
        r.update({'t': 'I', 'src': im.get('src', ''), 'fit': im.get('fit', 'cover'), 'n': '3D-кадр' if im.get('canvas') else 'Фото'})
        rd = radius(n.get('radius'), w, h)
        if rd: r['r'] = rd
        return r
    r['t'] = 'F'
    mode = L.get('mode', 'NONE')
    if mode == 'GRID': mode = 'NONE'
    r['m'] = mode
    if 'padding' in L: r['p'] = [space(L['padding'].get(k, 0)) for k in 'trbl']
    if 'gap' in L: r['g'] = space(L['gap'])
    if 'primaryAlign' in L: r['pa'] = L['primaryAlign']
    if 'counterAlign' in L: r['ca'] = L['counterAlign']
    if L.get('clip'): r['clip'] = 1
    if L.get('wrap'): r['wrap'] = 1
    fills = []
    for f in (n.get('fills') or []):
        if f.get('token') == 'gradient.hatch':
            STATS['hatch'] += 1; r['hatch'] = {'c1': {'v': 'Цвета:' + COLOR['bad-ink']}, 'c2': {'v': 'Цвета:' + COLOR['surface']}, 'per': 4.2, 'band': 2}
            continue
        q = color(f)
        if q: fills.append(q)
    if fills: r['f'] = fills
    if n.get('bgImage'): STATS['img'] += 1; r['bg'] = n['bgImage']
    s = n.get('stroke')
    if s:
        c = color({k: v for k, v in s.items() if k in ('token', 'hex', 'approx')})
        if c:
            wt = s.get('weight', 1)
            r['s'] = {**c, 'd': 1 if s.get('style') == 'dashed' else 0}
            if isinstance(wt, dict): r['s']['sides'] = [px(wt.get(k, 0)) for k in 'trbl']
            else: r['s']['w'] = px(wt)
    rd = radius(n.get('radius'), w, h)
    if rd: r['r'] = rd
    if n.get('effects'):
        fx = [e['token'].split('.', 1)[1] for e in n['effects'] if str(e.get('token', '')).startswith('shadow.')]
        if fx: r['fx'] = ['Тень/' + e for e in fx]
    if 'opacity' in n and n['opacity'] < 1: r['o'] = n['opacity']
    kids = [conv(c, ax, ay) for c in (n.get('children') or [])]
    # ручка шторки рисуется на сайте псевдоэлементом `.vpill::before` (44×5, сверху 7, по центру) — выгрузка его не видит
    if '.vpill' in str(n.get('name', '')) and not kids:
        kids = [{'t': 'F', 'm': 'NONE', 'n': 'Ручка', 'w': 44, 'h': 5, 'x': round(w / 2 - 22, 1), 'y': 7, 'r': {'px': 2.5},
                 'f': [{'v': 'Цвета:' + COLOR['grip']}], 'css': '.vpill::before'}]
    # подпись «в коробке» без замера — во всю ширину коробки за вычетом полей
    for k in kids:
        if k.get('t') == 'T' and not k['w']:
            p = [px(x) for x in (r.get('p') or [0, 0, 0, 0])]
            k['w'] = max(1, w - p[1] - p[3]); k['x'] = p[3]; k['y'] = round(p[0] + (h - p[0] - p[2] - k['h']) / 2, 1)
    r['n'] = hname(n.get('name', ''), mode)
    plain = not any(r.get(k) for k in ('f', 's', 'fx', 'r', 'hatch', 'p', 'bg', 'o', 'clip'))
    # обёртка ровно вокруг одного текста -> сам текст (имя обёртки)
    if plain and len(kids) == 1 and kids[0]['t'] == 'T' and abs(kids[0]['w'] - w) <= 3 and not r.get('abs'):
        k = kids[0]; STATS['collapsed'] += 1
        k['x'] = r['x']; k['w'] = w; k['y'] = round(r['y'] + (h - k['h']) / 2, 1)
        if r['n'] not in ('Ряд', 'Колонка', 'Блок'): k['n'] = r['n']
        k['css'] = r['css'] + ' > ' + k.get('css', '')
        return k
    if kids:
        ok, sp = fits_auto(r, kids)
        if ok:
            STATS['auto'] += 1
            for k in kids:
                if k['t'] == 'T' and k['ln'] == 1 and not k.get('abs') and not k.get('tr'): k['hug'] = 1
            # одна подпись с многоточием в кнопке (26.10): Inter шире Arial сайта, и по замеру сайта слово обрезалось.
            # На сайте подписи доступна вся ширина кнопки: кнопка шире текста — подпись во всю ширину (по центру);
            # кнопка по тексту (поля = ширина) — кнопка растёт по подписи (hugW, builder2), как на сайте.
            flow1 = [k for k in kids if not k.get('abs')]
            if len(flow1) == 1 and flow1[0]['t'] == 'T' and flow1[0].get('tr') and r['m'] == 'HORIZONTAL' and r.get('pa') == 'CENTER':
                k = flow1[0]; pp = [px(x) for x in (r.get('p') or [0, 0, 0, 0])]; inner = r['w'] - pp[1] - pp[3]
                if k['w'] < inner - TOL: k['w'] = round(inner, 1); k['x'] = pp[3]
                else: k['hug'] = 1; r['hugW'] = 1
            # ряд из кнопок «по подписи» (26.10, по находке помощника 2 на «Шапке»): если все дети в потоке растут по
            # содержимому (hugW или текст с hug) и хоть одна кнопка hugW — ряд тоже растёт, иначе кнопки вылезают за вариант
            if sp is None and r['m'] == 'HORIZONTAL' and flow1 and any(k.get('hugW') for k in flow1) and \
                    all(k.get('hugW') or (k['t'] == 'T' and k.get('hug')) for k in flow1):
                r['hugW'] = 1
            if sp is not None:
                STATS['spacer'] += 1
                flow = [k for k in kids if not k.get('abs')]
                kids.insert(kids.index(flow[sp]), {'t': 'F', 'sp': 1, 'n': 'Отступ', 'w': 1, 'h': 1, 'x': 0, 'y': 0, 'm': 'NONE'})
        else:
            STATS['free'] += 1; r['m'] = 'NONE'
            # одна однострочная подпись по центру коробки в свободной раскладке (26.10, «Открыть» в карточке избранного,
            # находка помощника 2): по замеру сайта Inter не влезает и сборщик ставит «Откр…» — даём ей всю ширину коробки
            flow1 = [k for k in kids if not k.get('abs')]
            if len(flow1) == 1 and len(flow1) == len(kids) and flow1[0]['t'] == 'T' and (flow1[0]['ln'] == 1 or flow1[0].get('tr') or flow1[0].get('nw')):  # h2: не при значке поверх (♥ + счётчик)
                k = flow1[0]; pp = [px(x) for x in (r.get('p') or [0, 0, 0, 0])]; inner = w - pp[1] - pp[3]
                if k['w'] < inner - TOL and abs(k['x'] + k['w'] / 2 - (pp[3] + inner / 2)) <= 2:
                    k['w'] = round(inner, 1); k['x'] = pp[3]; k['al'] = 'C'
        # в свободной раскладке пустая невидимая рамка (на сайте — пустой значок вроде #vpill) ничего не держит — выкинуть
        if r['m'] == 'NONE':
            kids = [k for k in kids if not (k['t'] == 'F' and not k.get('k') and not any(k.get(x) for x in ('f', 's', 'fx', 'hatch', 'bg', 'sp')))] or kids
        r['k'] = kids
    else:
        if r['m'] in ('HORIZONTAL', 'VERTICAL'): r['m'] = 'NONE'
    return r

def label_fix(n):
    for c in n.get('children') or []:
        if c.get('type') == 'TEXT' and 'size' not in c: c['size'] = {'w': 0, 'h': 0}; c['pos'] = dict(n.get('pos') or {'x': 0, 'y': 0})
        label_fix(c)

# ширина по правилу вёрстки (100% контейнера), а не по содержимому: варианты одного элемента — одной ширины (владелец 26.10).
# Чипы, кнопки, подписи, переключатели — ширина по содержимому, их не трогаем.
EQ_TOL = 0.15  # в одну группу — ширины в пределах 15 % от большей; дальше — другое место на сайте (напр. пузырь во всю главную на компьютере)
def widen(r, d):
    """расширить узел на d: дети во всю ширину — тоже; прижатые вправо — сдвинуть; по центру — на d/2; вертикальные ряды — по высоте содержимого"""
    ow = r['w']; r['w'] = round(ow + d, 1)
    if r.get('t') != 'F': return
    p = [px(x) for x in (r.get('p') or [0, 0, 0, 0])]
    hor_auto = r.get('m') == 'HORIZONTAL'
    flow = [k for k in r.get('k', []) if not k.get('abs') and not k.get('sp')]
    has_sp = any(k.get('sp') for k in r.get('k', []))
    if r.get('m') == 'VERTICAL' and not has_sp: r['hugH'] = 1  # с «Отступом» высота остаётся как на сайте
    for k in r.get('k', []):
        if k.get('sp'): continue
        L = k['x'] - (0 if k.get('abs') else p[3]); R = (ow - (0 if k.get('abs') else p[1])) - (k['x'] + k['w'])
        if hor_auto and not k.get('abs'):
            # в ряду растягивается только последний элемент, упёртый в правый край, и только если он сам «резиновый»
            if not has_sp and k is flow[-1] and abs(R) <= TOL and r.get('pa', 'MIN') == 'MIN' and (
                    (k['t'] == 'T' and not k.get('hug')) or (k['t'] == 'F' and k.get('m') != 'HORIZONTAL')):
                widen(k, d)
            continue
        if abs(L) <= TOL and abs(R) <= TOL: widen(k, d)
        elif abs(R) <= TOL and L > TOL: k['x'] = round(k['x'] + d, 1)
        elif abs(L - R) <= TOL and L > TOL: k['x'] = round(k['x'] + d / 2, 1)
def equalize(vs, comp):
    if not CMP.get(comp, {}).get('equalWidth') or len(vs) < 2: return []
    rep = []; left = sorted(vs, key=lambda v: -v['root']['w'])
    while left:
        top = left[0]['root']['w']; grp = [v for v in left if v['root']['w'] >= top * (1 - EQ_TOL)]
        left = [v for v in left if v not in grp]
        for v in grp:
            d = round(top - v['root']['w'], 1)
            if d > 0.4: widen(v['root'], d); rep.append((v['cap'], d))
    return rep
EQREP = {}

# Шторка на сайте целиком той же высоты и уезжает вниз (`transform`), видна только верхняя часть; выгрузка этого сдвига не видит,
# и три состояния выходили одинаковыми. Видимая высота — по правилам сайта (`tools/scout/flat215-demo/index.html` vwEdges/vwMid):
# свёрнута — до начала прокручиваемого списка (#vscroll); на половину — плюс строки-входы (#vGroups) и 30 px верха первой строки.
def sheet_clip(root, state):
    sc = next((k for k in root.get('k', []) if '#vscroll' in str(k.get('css'))), None)
    if not sc or state == 'full': return
    vmin = sc['y']; vis = vmin
    if state == 'mid':
        vl = next((k for k in sc.get('k', []) if '#vlist' in str(k.get('css'))), None)
        gr = vl and next((k for k in vl.get('k', []) if '#vGroups' in str(k.get('css'))), None)
        items = vl and any('.vitems' in str(k.get('css')) for k in vl.get('k', []))
        vis = max(vmin + 60, vmin + (vl['y'] + gr['y'] + gr['h'] if gr else 0) + (30 if items else 12))
    root['h'] = round(min(root['h'], vis), 1); root['clip'] = 1

LANG_ORDER = {'ru': 0, 'en': 1}
RULES = {'sheet-clip': sheet_clip}  # особые правила по имени (pages/*.json "rule")
def _walk(r, fn, parent=None):
    fn(r, parent)
    for k in r.get('k', []) or []: _walk(k, fn, r)
def r_box_text(root, state):
    def f(r, parent):
        if r.get('t') != 'F' or r.get('pa') != 'CENTER' or r.get('hugW'): return  # кнопка по подписи (hugW из gen2.py) — не трогаем
        fl = [k for k in r.get('k', []) if not k.get('abs')]
        if len(fl) != 1 or fl[0].get('t') != 'T' or not (fl[0].get('tr') or fl[0].get('nw') or (str(r.get('css', '')).startswith('button') and fl[0].get('ln') == 1)): return  # + однострочная подпись кнопки (Inter шире → ложное «…»)
        k = fl[0]; p = [px(x) for x in (r.get('p') or [0, 0, 0, 0])]
        k['w'] = round(r['w'] - p[1] - p[3], 1); k['x'] = p[3]; k['al'] = 'C'; k.pop('hug', None)
    _walk(root, f)
def r_fit_kids(root, state):
    def grow(r):
        for k in r.get('k', []) or []:
            if k.get('t') == 'F': grow(k)
        if r.get('t') != 'F': return
        for k in r.get('k', []) or []:
            if k.get('abs') or k.get('sp'): continue
            p = [px(x) for x in (r.get('p') or [0, 0, 0, 0])]
            if k.get('t') == 'T': k['h'] = float(math.ceil(k['h'] - 0.01))  # Фигма округляет высоту строки вверх (25.5→26)
            need = (k['y'] + k['h'] + (p[2] if r.get('m') in ('HORIZONTAL', 'VERTICAL') else 0)) if r.get('m') != 'VERTICAL' else None
            if r.get('m') == 'VERTICAL':
                fl = [q for q in r['k'] if not q.get('abs') and not q.get('sp')]
                need = p[0] + p[2] + sum(q['h'] for q in fl) + px(r.get('g') or 0) * (len(fl) - 1)
            if need and need > r['h'] + 0.05: r['h'] = round(need, 1)
    grow(root)
def r_native_radio(root, state):
    on = state in ('included', 'on', 'selected')
    def f(r, parent):
        if r.get('t') == 'F' and str(r.get('css', '')).split('.')[0] == 'input' and not r.get('k') and not r.get('f') and not r.get('s'):
            r.update({'n': 'Переключатель', 'm': 'NONE', 'f': [{'v': 'Цвета:' + COLOR['surface']}], 'r': {'px': r['w'] / 2},
                      's': {'v': 'Цвета:' + COLOR['accent' if on else 'muted'], 'w': 2 if on else 1, 'd': 0}})
            if on:
                d = round(r['w'] * 0.45, 1)
                r['k'] = [{'t': 'F', 'm': 'NONE', 'n': 'Отметка', 'w': d, 'h': d, 'x': round((r['w'] - d) / 2, 1), 'y': round((r['h'] - d) / 2, 1),
                           'r': {'px': d / 2}, 'f': [{'v': 'Цвета:' + COLOR['accent']}], 'css': 'input:checked'}]
    _walk(root, f)
def r_center_overlay(root, state):
    def f(r, parent):
        if parent and r.get('t') == 'T' and (r.get('abs') or parent.get('m') == 'NONE') and abs(r['w'] - parent['w']) <= 1: r['al'] = 'C'
    _walk(root, f)
def r_badge_wrap(root, state):
    ks = [k for k in root.get('k', []) if k.get('abs')]
    if not ks: return
    x0 = min([0] + [k['x'] for k in ks]); y0 = min([0] + [k['y'] for k in ks])
    x1 = max([root['w']] + [k['x'] + k['w'] for k in ks]); y1 = max([root['h']] + [k['y'] + k['h'] for k in ks])
    if x0 >= 0 and y0 >= 0 and x1 <= root['w'] and y1 <= root['h']: return
    btn = {kk: v for kk, v in root.items()}; btn['x'] = -x0; btn['y'] = -y0; btn['n'] = 'Кнопка'
    for k in ks: k['n'] = 'Счётчик'
    root.clear(); root.update({'t': 'F', 'm': 'NONE', 'n': 'Кнопка со значком', 'w': round(x1 - x0, 1), 'h': round(y1 - y0, 1), 'x': 0, 'y': 0,
                               'css': btn.get('css', ''), 'k': [btn]})
RULES2 = {'box-text': r_box_text, 'fit-kids': r_fit_kids, 'native-radio': r_native_radio, 'center-overlay': r_center_overlay, 'badge-wrap': r_badge_wrap}
SPECS = []
for f in sorted(glob.glob(f"{S}/figma-spec/*.json")):
    if f.endswith('order.json'): continue
    d = json.load(open(f)); cat = d['component'].split('/', 1)[0]
    if CAT.get(cat) == PAGE and any(v['props'].get('device') == dev for v in d['variants']): SPECS.append(d)
if '--skeleton' in sys.argv:
    # черновик pages/<Страница>.json: элементы этой страницы в выгрузке; названия — черновые из _common, «что это» — из выгрузки
    sk = {'_что': f'Страница «{PAGE}»: какие элементы на ней, как назвать секции, строка «что это», особые правила.', 'page': PAGE, 'order': [],
          'components': {d['component']: {'sec': C['draftSectionNames'].get(d['component'], d['component']), 'say': d.get('description', ''),
                                          **({'equalWidth': True} if d['component'] in C['draftEqualWidth'] else {})} for d in SPECS}}
    print(json.dumps(sk, ensure_ascii=False, indent=1)); sys.exit(0)
miss = [d['component'] for d in SPECS if d['component'] not in CMP]
if miss: print('ВНИМАНИЕ: в выгрузке есть, в pages/%s.json нет (пропущены): %s' % (PAGE, ', '.join(miss)), file=sys.stderr)
sections = []
for d in SPECS:
    comp = d['component']
    if comp not in CMP: continue
    cfg = CMP[comp]; cat = comp.split('/', 1)[0]
    vs = [v for v in d['variants'] if v['props'].get('device') == dev]
    vs.sort(key=lambda v: LANG_ORDER.get(v['props'].get('lang'), 2))
    sec = {'sec': cfg['sec'], 'set': CAT[cat] + '/' + cfg['sec'], 'say': cfg.get('say') or d.get('description', ''),
           'code': f"{comp} · {d.get('selector', '')} · {', '.join(d.get('source', [])[:6])}", 'variants': []}
    if cfg.get('setBg'): sec['setBg'] = cfg['setBg']
    seen = set(); vn = cfg.get('valueNames') or {}; tf = cfg.get('textFix') or {}
    for v in vs:
        props = [(PROP.get(k, k), vn.get(str(val)) or VAL.get(str(val), str(val))) for k, val in v['props'].items() if k != 'device']
        props.sort(key=lambda kv: (kv[0] != 'Язык', kv[0]))
        name = ', '.join(f'{k}={val}' for k, val in props) or 'Вариант=Обычное'
        if name in seen: continue
        seen.add(name)
        fr = v['frame']; label_fix(fr)
        if str(v['props'].get('state')) in tf: txt_fix(fr, tf[str(v['props'].get('state'))])
        root = conv(fr); root['x'] = root['y'] = 0; root.pop('abs', None)
        if root['t'] != 'F':  # корень-текст -> рамка с текстом
            root = {'t': 'F', 'm': 'NONE', 'w': fr['size']['w'], 'h': fr['size']['h'], 'x': 0, 'y': 0, 'n': 'Блок', 'css': fr.get('name', ''), 'k': [root]}
        if cfg.get('rule'): RULES[cfg['rule']](root, str(v['props'].get('state')))
        for rn in cfg.get('rules-h2') or []: RULES2[rn](root, str(v['props'].get('state')))
        cap = ' · '.join(val for _, val in props)
        sec['variants'].append({'name': name, 'cap': cap, 'lang': str(v['props'].get('lang', '')), 'screen': v.get('screen', ''), 'root': root})
    eq = equalize(sec['variants'], comp)
    if eq: EQREP[cfg['sec']] = eq
    sections.append(sec)
ORDER = PG.get('order') or []
sections.sort(key=lambda s: ORDER.index(s['sec']) if s['sec'] in ORDER else 99)
P = {'page': PAGE, 'dev': dev, 'maxW': 1240 if dev == 'phone' else 3000, 'sections': sections}
js = json.dumps(P, ensure_ascii=False, separators=(',', ':'))
open(OUT + '.json', 'w').write(js)
b = base64.b64encode(zlib.compress(js.encode('utf-8'), 9)).decode()
open(OUT + '.b64', 'w').write(b)
# перенос в Фигму: части ≤ ~5000 знаков b64 со сверкой по кускам + вызовы сборки по одной секции (transfer.py)
sys.path.insert(0, HERE); import transfer  # noqa: E402
parts = transfer.write_parts(P, OUT + '.parts')
print(json.dumps({'sections': [(s['sec'], len(s['variants'])) for s in sections], 'json': len(js), 'b64': len(b), 'parts': parts, **STATS, 'equalW': EQREP}, ensure_ascii=False))
