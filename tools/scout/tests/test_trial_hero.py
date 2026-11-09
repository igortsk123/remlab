"""AI-КАДР ГОСТИНОЙ ДЛЯ ПРОБЫ АГЕНТА (T-20261109-13, MASTER-agent-trial T7): `tools/scout/trial_hero.py` без сети и без модели.
Проверяем: промпт одного вида собирается из боевого improve-v4 для всех стилей без следов второго вида и полосы (иначе отказ до
оплаты); кадр режется под размер запроса; плашка стоит НА картинке и влезает в узкий кадр; сухой прогон модель не зовёт; без фото
товаров, без бюджета, при отказе шлюза и без денег — отказ с меткой, фото нет, тур идёт дальше; успех — hero.jpg с плашкой, json
с моделью, временем и ценой; папка сцены из демо берёт нужный вид листа и наследует товар комплекта.
    ~/venvs/scout/bin/python tools/scout/tests/test_trial_hero.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_trial_hero')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
os.environ['IMPROVE_PROMPT'] = 'v4'

from PIL import Image  # noqa: E402

import draft_render as DR  # noqa: E402
import improve_mode as IM  # noqa: E402
import trial_hero as TH  # noqa: E402

fails = []


def check(name, cond, info=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    if not cond:
        fails.append(name)


# 1) промпт одного вида — из боевого, для всех стилей и сочетаний декора/мягкого/штор; следов второго вида нет
styles = [s for s, rec in (IM.styles_db().get('styles') or {}).items() if (rec or {}).get('render_guide')]
check('стили с гайдом фото есть (≥ 6)', len(styles) >= 6, styles)
soft = [{'id': 1, 'item': 'cushion', 'name': 'x', 'place': 'on the sofa'}, {'id': 2, 'item': 'curtains', 'name': 'y', 'place': 'win'}]
bad = []
for st in styles + ['сканди', 'лофт', '']:
    for decor, sf in (([], []), ([{'role': 'ваза'}], []), ([], soft), ([{'role': 'ваза'}], soft)):
        base = IM.prompt_for(st, decor, None, None, None, [{'id': [1], 'role': 'диван'}], sf, room=None)
        try:
            p = TH.single_view_prompt(base)
            if 'one rendered view' not in p or 'Return ONE image with exactly the dimensions and proportions of IMAGE 1.' not in p:
                bad.append((st, len(decor), len(sf), 'нет строк одного вида'))
        except TH.HeroError as e:
            bad.append((st, len(decor), len(sf), str(e)))
check(f'промпт одного вида: {len(styles) + 3} стилей × 4 сочетания — без следов второго вида', not bad, bad[:3])
base = IM.prompt_for('сканди', [], None, None, None, None, soft, room=None)
check('промпт: всё прочее боевое сохранено (каталожная форма, радиатор, светильник, фото-вид)',
      all(x in TH.single_view_prompt(base) for x in ('the catalogue shape of every product', 'RADIATORS:', 'CEILING FIXTURE',
                                                    'PHOTOGRAPHIC LOOK', 'SOFT TEXTILES', 'FORBIDDEN')))
try:
    TH.single_view_prompt(base + '\nKeep the magenta band.')
    left = ''
except TH.HeroError as e:
    left = e.code
check('промпт: остался след листа — отказ prompt_two_view (до оплаты)', left == 'prompt_two_view', left)

# 2) кадр под размер запроса: обрезка по центру до 3:2, затем масштаб
f = TH.fit_frame(Image.new('RGB', (2048, 1489), (10, 20, 30)), '1536x1024')
check('кадр 2048×1489 → 1536×1024', f.size == (1536, 1024), f.size)
f2 = TH.fit_frame(Image.new('RGB', (1000, 1000)), '1536x1024')
check('квадратный кадр → 1536×1024 (обрезка, не растяжение)', f2.size == (1536, 1024), f2.size)

# 3) плашка — компактная пилюля внизу слева (T-13/2: ~35–45 % ширины на 1536, кегль ~2,2 % высоты); верх не тронут; узкий
#    кадр — влезает
src = Image.new('RGB', (1536, 1024), (240, 240, 240))
b = TH.badge(src)


def darker(p, base=240):
    return sum(p) < 0.6 * 3 * base


def pill_share(img, base=240):
    """Доля тёмных точек внизу слева (поле пилюли без краёв); буквы белые — поэтому доля, а не одна точка."""
    pts = [(x, y) for x in range(40, 400, 7) for y in range(img.height - 50, img.height - 30, 3)]
    return sum(darker(img.getpixel(q), base) for q in pts) / len(pts)


dark_px = [b.getpixel((x, 1024 - 40)) for x in range(40, 400, 7) if darker(b.getpixel((x, 1024 - 40)))]
px_top = b.getpixel((60, 40))
check('плашка: подложка тёмная полупрозрачная внизу слева', pill_share(b) > 0.5 and dark_px and min(map(sum, dark_px)) > 120,
      (pill_share(b), dark_px[:3]))
check('плашка: верх кадра не тронут', px_top == (240, 240, 240), px_top)
rows = {y: [x for x in range(1536) if darker(b.getpixel((x, y)))] for y in range(880, 1024)}
ys = [y for y, xs in rows.items() if xs]
w_badge = max(xs[-1] - xs[0] for xs in rows.values() if xs) if ys else 0
check('плашка: ширина 35–45 % кадра 1536', 0.35 * 1536 < w_badge < 0.45 * 1536, w_badge)
h_badge = (ys[-1] - ys[0] + 1) if ys else 0
check('плашка: высота пилюли ≈ кегль 2,2 % высоты + поля (3–6 % высоты)', 0.03 * 1024 < h_badge < 0.06 * 1024, h_badge)
check('плашка: отступ от низа и левого края есть', ys and ys[-1] < 1020 and min(xs[0] for xs in rows.values() if xs) > 10)
nb = TH.badge(Image.new('RGB', (600, 900), (240, 240, 240)))
nrow = [x for x in range(600) for y in range(820, 900) if darker(nb.getpixel((x, y)))]
check('плашка: узкий кадр 600 px — не вылезает за край', nrow and max(nrow) < 595, max(nrow) if nrow else None)
check('плашка: текст — ровно требуемый', TH.BADGE_TEXT == 'AI-generated visualisation — not a photograph')

# 4) сцена и прогоны на заглушках: фото товаров есть, модель — подставная
base_dir = tempfile.mkdtemp(prefix='trial-hero-')
scene = os.path.join(base_dir, 'scene')
os.makedirs(scene)
Image.new('RGB', (2048, 1489), (200, 190, 180)).save(os.path.join(scene, 'frame.jpg'))
items = [{'role': 'диван', 'name': 'Диван Викс Рогожка Серый', 'img': 'img/a.jpg', 'x': 150, 'y': 280, 'w': 198, 'd': 90, 'h': 83},
         {'role': 'столик', 'name': 'Журнальный стол Хостер Орех', 'img': 'img/b.jpg', 'x': 150, 'y': 180, 'w': 110, 'd': 60, 'h': 40},
         {'role': 'тв-тумба', 'name': 'ТВ-тумба Теджонс', 'img': 'img/c.jpg', 'x': 150, 'y': 20, 'w': 139, 'd': 40, 'h': 62}]
room = {'w': 439, 'd': 325, 'openings': [], 'radiators': []}
json.dump({'room': room, 'items': items, 'decor': [], 'style': 'сканди'}, open(os.path.join(scene, 'scene.json'), 'w', encoding='utf-8'),
          ensure_ascii=False)
seen_urls = []


def fake_photo(url):
    seen_urls.append(url)
    return None if 'missing' in (url or '') else Image.new('RGB', (300, 300), (120, 120, 140))


DR.photo = fake_photo
calls = []


def model_ok(imgs, prompt, size='', quality='', model=''):
    calls.append({'n': len(imgs), 'size': size, 'quality': quality, 'model': model, 'timeout': DR._GW_TIMEOUT, 'prompt': prompt})
    return Image.new('RGB', (1536, 1024), (230, 225, 215))


def model_never(*a, **k):
    raise AssertionError('модель позвали в сухом прогоне')


bal = [10.0]


def credits(max_age_s=60.0):
    return bal[0]


DR.gw_credits = credits
TH.time.sleep = lambda s: None

DR.gpt_edit = model_never
out = os.path.join(base_dir, 'dry')
r = TH.run(scene, out, go=False)
check('сухой прогон: ok, модель не звали', r['ok'] and r['dry_run'] and not calls, r.get('error'))
check('сухой прогон: в модель ушло бы 2 картинки (кадр, эталоны)', r.get('images_sent') == 2, r.get('images_sent'))
check('сухой прогон: исходники и плашка на входном кадре', all(os.path.exists(os.path.join(out, p)) for p in
      ('sources/1-frame.png', 'sources/2-ident.jpg', 'sources/prompt.txt', 'dry-badge.jpg', 'hero.json')))
check('сухой прогон: фото-результата нет', not os.path.exists(os.path.join(out, 'hero.jpg')))
check('пути товаров: относительный img → file:// от папки сцены',
      any(u.startswith('file://') and u.endswith(os.path.join(scene, 'img', 'a.jpg')) for u in seen_urls), seen_urls[:2])
check('prompt_version — боевая + метка одного вида', r.get('prompt_version') == IM.PROMPT_VERSION + '-' + TH.SINGLE_TAG,
      r.get('prompt_version'))

DR.gpt_edit = model_ok


def credits_spend(max_age_s=60.0):
    v = bal[0]
    bal[0] = round(bal[0] - 0.03, 4)
    return v


DR.gw_credits = credits_spend
out = os.path.join(base_dir, 'go')
r = TH.run(scene, out, go=True, budget_s=60)
j = json.load(open(os.path.join(out, 'hero.json'), encoding='utf-8'))
check('платный (заглушка): ok, hero.jpg есть', r['ok'] and os.path.exists(os.path.join(out, 'hero.jpg')), r.get('error'))
hero = Image.open(os.path.join(out, 'hero.jpg'))
check('платный: на hero.jpg стоит плашка', pill_share(hero, 225) > 0.5, pill_share(hero, 225))
check('платный: один вызов, модель/качество/размер из настроек', len(calls) == 1 and calls[0]['model'] == TH.MODEL
      and calls[0]['size'] == '1536x1024' and calls[0]['quality'] == TH.QUALITY, calls[:1] and {k: calls[0][k] for k in ('model', 'size')})
check('платный: потолок ожидания шлюза ≤ бюджета шага', calls and 5 <= calls[0]['timeout'] <= 60, calls and calls[0]['timeout'])
check('платный: в модель ушёл промпт одного вида', calls and 'one rendered view' in calls[0]['prompt'] and 'magenta' not in calls[0]['prompt'])
check('hero.json: модель, время (подготовка/модель/итого), цена по балансу', j['model'] == TH.MODEL and
      all(k in j['timing'] for k in ('prep', 'model', 'post', 'total')) and j['cost_usd'] == 0.03 and j['cost_source'], j.get('cost_usd'))

calls.clear()
out = os.path.join(base_dir, 'budget')
r = TH.run(scene, out, go=True, budget_s=5)
check('бюджет кончился до модели: отказ budget, модель не звали, фото нет', not r['ok'] and r['error_code'] == 'budget' and not calls
      and not os.path.exists(os.path.join(out, 'hero.jpg')), r.get('error_code'))


def model_503(*a, **k):
    raise SystemExit('шлюз отказал (HTTP 503): busy')


DR.gpt_edit = model_503
out = os.path.join(base_dir, 'fail')
r = TH.run(scene, out, go=True)
check('шлюз 503: отказ шлюз_503 (не падение процесса), фото нет', not r['ok'] and r['error_code'] == 'шлюз_503'
      and not os.path.exists(os.path.join(out, 'hero.jpg')), r.get('error_code'))


def model_402(*a, **k):
    raise DR.NoCreditsError(DR.NO_CREDITS_TEXT)


DR.gpt_edit = model_402
r = TH.run(scene, os.path.join(base_dir, 'nomoney'), go=True)
check('нет денег: отказ нет_денег', not r['ok'] and r['error_code'] == 'нет_денег', r.get('error_code'))

DR.gpt_edit = model_never
sc2 = os.path.join(base_dir, 'scene-nophoto')
os.makedirs(sc2)
Image.new('RGB', (1536, 1024)).save(os.path.join(sc2, 'frame.png'))
json.dump({'room': room, 'items': [dict(it, img='img/missing.jpg') for it in items], 'style': 'сканди'},
          open(os.path.join(sc2, 'scene.json'), 'w', encoding='utf-8'), ensure_ascii=False)
r = TH.run(sc2, os.path.join(base_dir, 'nophoto'), go=True)
# с T-20261109-17 лист «фото нет» ловит и общий `improve_mode.paid_gate` (идёт раньше `photo_gate`) — код тогда no_product_sheet
check('нет фото товаров: отказ до оплаты', not r['ok'] and r['error_code'] in ('no_product_photos', 'no_product_sheet')
      and 'фото товаров' in (r.get('error') or ''), r.get('error'))
r = TH.run(os.path.join(base_dir, 'nowhere'), os.path.join(base_dir, 'bad'), go=True)
check('нет папки сцены: отказ bad_input, json записан', not r['ok'] and r['error_code'] == 'bad_input'
      and os.path.exists(os.path.join(base_dir, 'bad', 'hero.json')), r.get('error_code'))

# 5) папка сцены из демо: вид листа по полосе, «стул 2» наследует товар «стул»
demo = os.path.join(base_dir, 'demo')
os.makedirs(demo)
json.dump({'apartment_id': 'flatX', 'room': room, 'variants': [{'id': 'set1', 'title': 'Сканди', 'style': 'сканди', 'items': [
    {'role': 'стул', 'x': 1, 'y': 2, 'w': 45, 'd': 50, 'h': 80, 'sku': {'name': 'Стул Корнер', 'img': 'img/s.jpg', 'sid': 's1'}},
    {'role': 'стул 2', 'x': 3, 'y': 4, 'w': 45, 'd': 50, 'h': 80, 'sku': {}}], 'decor': [
    {'role': 'подушка', 'sku': {'name': 'Подушка', 'img': 'img/p.jpg'}}]}]},
    open(os.path.join(demo, 'demo-data.json'), 'w', encoding='utf-8'), ensure_ascii=False)
sheet = Image.new('RGB', (2048, 3072), (50, 50, 50))
sheet.paste(Image.new('RGB', (2048, 1489), (200, 10, 10)), (0, 0))
sheet.paste(Image.new('RGB', (2048, 94), (255, 0, 255)), (0, 1489))
sheet.save(os.path.join(demo, 'sheet.png'))
sd = TH.prepare_demo(os.path.join(demo, 'demo-data.json'), 'set1', os.path.join(demo, 'sheet.png'), 0, os.path.join(base_dir, 'sd'),
                     img_base='/live/demo')
fr = Image.open(os.path.join(sd, 'frame.jpg'))
pj = json.load(open(os.path.join(sd, 'scene.json'), encoding='utf-8'))
check('демо → сцена: верхний вид листа (до полосы)', fr.size == (2048, 1489) and fr.getpixel((100, 100))[0] > 150, fr.size)
check('демо → сцена: «стул 2» наследует товар «стул»', pj['items'][1].get('name') == 'Стул Корнер' and pj['items'][1].get('sid') == 's1')
check('демо → сцена: фото — от --img-base (живое демо, только чтение)', pj['items'][0]['img'] == 'file:///live/demo/img/s.jpg'
      and pj['decor'][0]['sku']['img'] == 'file:///live/demo/img/p.jpg', pj['items'][0]['img'])

check('демо → сцена: камеры варианта переносятся (для --render)', pj.get('cams') == [], pj.get('cams'))

# 6) кадра нет: без --render — отказ bad_input; с --render — одна камера сцены, сразу в размер запроса, полные меши
sc3 = os.path.join(base_dir, 'scene-render')
os.makedirs(sc3)
json.dump({'room': room, 'items': items + [{'role': 'стул', 'name': 'Стул', 'img': 'img/s.jpg', 'msid': 'm-st', 'x': 1, 'y': 1, 'w': 45,
           'd': 50, 'h': 80}, {'role': 'стул 2', 'name': 'Стул', 'img': 'img/s.jpg', 'x': 2, 'y': 2, 'w': 45, 'd': 50, 'h': 80}],
           'style': 'сканди', 'cams': [{'name': 'C1', 'x': 400, 'y': 200, 'rot': -99, 'fov': 72, 'pose': 3}]},
          open(os.path.join(sc3, 'scene.json'), 'w', encoding='utf-8'), ensure_ascii=False)
r = TH.run(sc3, os.path.join(base_dir, 'norender'), go=False)
check('кадра нет, без --render — отказ bad_input', not r['ok'] and r['error_code'] == 'bad_input', r.get('error_code'))
rendered = []


class _Cam:
    name, eye, target, fov_deg, shift_y = 'C1', (400, 120, 200), (0, 110, 0), 72.0, 0.02


SFR, CFR, S3F = DR.scene_from_request, DR.cams_from_request, DR.scene3d_frame   # настоящие — для разделов 7–9
DR.scene_from_request = lambda p: ('room', [], {})
DR.cams_from_request = lambda room, pl, p: [_Cam(), _Cam()]


def fake_frame(room, placements, cam, sid_by_role, photos):
    rendered.append({'w': cam.width, 'h': cam.height, 'shift': getattr(cam, 'shift_y', None), 'sid': dict(sid_by_role),
                     'lite': DR.S3_LITE[0]})
    return Image.new('RGB', (cam.width, cam.height), (180, 170, 160)), {'clay': ['тв', 'ковёр']}


DR.scene3d_frame = fake_frame
DR.S3_LITE[0] = True
r = TH.run(sc3, os.path.join(base_dir, 'render'), go=False, render=True, cam_mode='scene')
check('--render: один кадр одной камеры, размер запроса, полные меши', r['ok'] and len(rendered) == 1 and
      (rendered[0]['w'], rendered[0]['h']) == (1536, 1024) and rendered[0]['lite'] is False, rendered or r.get('error'))
check('--render: сдвиг камеры (поза) сохраняется — с поправкой на широкий кадр', rendered
      and abs(rendered[0]['shift'] - 0.02 / TH.OVERSCAN) < 1e-9, rendered and rendered[0]['shift'])
check('--render: «стул 2» без меша берёт меш «стул»', rendered and rendered[0]['sid'].get('стул 2') == 'm-st', rendered and rendered[0]['sid'])
check('--render: время рендера и заглушки — в json (тв не считается)', 'render' in r['timing'] and r.get('rendered', {}).get('clay') == ['ковёр'],
      r.get('rendered'))
DR.scene_from_request, DR.cams_from_request = SFR, CFR

# 7) широкий кадр (защита от «расширения кадра», лофт 09.11): угол по тангенсу, сдвиг / k, обрезка = ровно центр
import math  # noqa: E402
k = 1.08
fv, sh = TH.overscan_camera(72.0, -0.10, k)
check('широкий кадр: tg(угол/2) растёт в k раз, сдвиг делится на k',
      abs(math.tan(math.radians(fv) / 2) - k * math.tan(math.radians(36))) < 1e-9 and abs(sh + 0.10 / k) < 1e-12, (fv, sh))
wide = Image.new('RGB', (1536, 1024), (255, 0, 0))
cw, ch = round(1536 / k), round(1024 / k)
wide.paste(Image.new('RGB', (cw, ch), (90, 90, 90)), ((1536 - cw) // 2, (1024 - ch) // 2))
cr = TH.crop_overscan(wide, k, '1536x1024')
edge_px = [cr.getpixel((x, y)) for x, y in ((0, 0), (1535, 0), (0, 1023), (1535, 1023), (768, 0), (0, 512))]
check('широкий кадр: обрезка — ровно центр (пояс ушёл), размер запроса', cr.size == (1536, 1024)
      and all(p[0] < 140 for p in edge_px), edge_px)
check('широкий кадр: k = 1 — кадр без обрезки', TH.crop_overscan(wide, 1.0).size == (1536, 1024))

# 8) ракурс героя по геометрии: диван у «северной» стены (y=D, лицом −y), столик перед ним, ТВ напротив, окно на западе
from planner.models import Item, Opening, Placement, Room  # noqa: E402


def P(role, x, y, rot, w, d, h):
    return Placement(role=role, x=x, y=y, rot=rot, item=Item(role=role, w_cm=w, d_cm=d, h_cm=h))


R = Room(width_cm=500, depth_cm=400, openings=[Opening(kind='window', wall='west', offset_cm=120, width_cm=150, sill_cm=85),
                                                Opening(kind='door', wall='east', offset_cm=40, width_cm=90, swing_cm=90)])
PL = [P('диван', 250, 350, 180, 220, 95, 85), P('столик', 250, 240, 180, 110, 60, 40), P('тв-тумба', 250, 25, 0, 160, 45, 55),
      P('ковёр', 250, 250, 180, 200, 300, 1), P('стеллаж', 470, 300, 270, 80, 35, 190)]
h = TH.pick_hero_camera(R, PL)
from planner.geometry import facing_vector, footprint  # noqa: E402
sofa_pts = list(footprint(PL[0]).exterior.coords)[:-1]
dvec = TH._view_dir(h['rot']) if h else (0, 1)
check('ракурс: найден', h is not None and h['name'] == 'hero' and h['fov'] == 72.0 and h['pose'] == 3, h)
check('ракурс: камера ПЕРЕД диваном, не со спины (y глаза < y дивана)', h and h['y'] < 350 - 95 / 2, h and (h['x'], h['y']))
check('ракурс: диван целиком в кадре', h and all(TH._ang((h['x'], h['y']), dvec, q) <= 36 for q in sofa_pts))
check('ракурс: окно в кадре', h and h['why']['window'] > 0.15, h and h['why'])
check('ракурс: глаз внутри комнаты, у стены', h and 0 < h['x'] < 500 and 0 < h['y'] < 400 and
      min(h['x'], h['y'], 500 - h['x'], 400 - h['y']) <= TH.HERO_INSET + 0.5, h and (h['x'], h['y']))
check('ракурс: до дивана ≥ порога (низ кадра не режет ножки)', h and h['why']['sofa_cm'] >= TH.HERO_MIN_SOFA_CM, h and h['why'])
h1 = TH.pick_hero_camera(R, PL, rank=1)
check('ракурс: rank=1 — другая точка глаза из списка лучших', h1 and (h1['x'], h1['y']) != (h['x'], h['y'])
      and h1['score'] <= h['score'] and len(h['alternatives']) >= 2, h1 and h['alternatives'])
check('ракурс: дивана и кресла нет — None (решает автоподбор)', TH.pick_hero_camera(R, PL[1:]) is None)
f = facing_vector(180)
check('ракурс: соглашение «лицо» rot 180 → −y (как в planner.models)', abs(f[1] + 1) < 1e-9)

# риск у края: крупный предмет сразу за краем кадра попадает в список, предмет в кадре — нет
eye, rot0 = (250.0, 20.0), 180.0                     # rot 180 → взгляд +y, на диван
side_item = P('шкаф', 250 + math.tan(math.radians(48)) * 200, 220, 270, 60, 60, 200)   # центр 48° от оси, ближний угол ~40°: за краем 36°
risk = TH.edge_risk(R, [PL[0], side_item], eye, rot0, 72.0, 1.08)
check('риск у края: шкаф за краем — в списке, диван в кадре — нет', [x['role'] for x in risk] == ['шкаф'], risk)

# 9) сцена пробы T-12 (формат `trial_demo.build`): вариант по стилю, проём без двери, товар по роли, отказы без оплаты
trial = {'trial_id': 't1', 'status': 'partial', 'core': {'w': 500, 'd': 400, 'rect': [0, 0, 500, 400]},
         'openings_core': [{'kind': 'window', 'wall': 'west', 'offset_cm': 120, 'width_cm': 150, 'sill_cm': 85, 'height_cm': 150},
                           {'kind': 'door', 'wall': 'east', 'offset_cm': 40, 'width_cm': 90, 'swing_cm': 0, '_src': 3}],
         'variants': [
             {'style': 'сканди', 'post_ok': False, 'hard': ['X'], 'items': [], 'placements_core': [
                 {'role': 'диван', 'x': 250, 'y': 350, 'rot': 180, 'w': 220, 'd': 95, 'h': 85}]},
             {'style': 'лофт', 'post_ok': True, 'hard': [], 'set_id': 's-1',
              'items': [{'role': 'диван', 'name': 'Диван Лофт', 'sid': '1_2', 'img': '//img/a.jpg'},
                        {'role': 'стул', 'name': 'Стул Л', 'sid': '3_4', 'img': '//img/s.jpg'}],
              'placements_core': [{'role': 'диван', 'x': 250, 'y': 350, 'rot': 180, 'w': 220, 'd': 95, 'h': 85, 'corner': False},
                                  {'role': 'стул 2', 'x': 60, 'y': 60, 'rot': 0, 'w': 45, 'd': 50, 'h': 80},
                                  {'role': 'тв', 'x': 1, 'y': 1, 'rot': 0}]}]}
TH._msid = lambda sid: f'm-{sid}' if sid else None
pt = TH.payload_from_trial(trial)
check('T-12: стиль не задан — первый вариант без проблем (лофт)', pt['style'] == 'лофт' and pt['source'] == 'trial:t1:лофт', pt['style'])
check('T-12: товар места по роли, «стул 2» — по базовой роли, меш — _msid(sid)',
      pt['items'][0]['name'] == 'Диван Лофт' and pt['items'][0]['msid'] == 'm-1_2' and pt['items'][1]['name'] == 'Стул Л', pt['items'])
check('T-12: место без размеров пропущено', len(pt['items']) == 2, len(pt['items']))
check('T-12: дверь без зоны открывания → проём без полотна, служебные поля сняты',
      [o['kind'] for o in pt['room']['openings']] == ['window', 'opening'] and '_src' not in pt['room']['openings'][1])
check('T-12: комната — ядро', pt['room']['w'] == 500 and pt['room']['d'] == 400)
codes = []
for bad_sc, st in ((dict(trial, status='refused'), None), (dict(trial, openings_core=None), None), (trial, 'джапанди'),
                   (dict(trial, variants=[dict(trial['variants'][1], placements_core=[])]), None)):
    try:
        TH.payload_from_trial(bad_sc, st)
        codes.append(None)
    except TH.HeroError as e:
        codes.append(e.code)
check('T-12: отказы до оплаты — trial_not_ready / trial_no_openings / bad_input / trial_empty_variant',
      codes == ['trial_not_ready', 'trial_no_openings', 'bad_input', 'trial_empty_variant'], codes)

# сцена T-12 целиком: рисуем сами ракурсом героя и широким кадром; ответ модели режется назад; json несёт камеру и риск
tsc = os.path.join(base_dir, 'trial-scene')
os.makedirs(tsc)
json.dump(trial, open(os.path.join(tsc, 'scene.json'), 'w', encoding='utf-8'), ensure_ascii=False)
rendered.clear()


def fake_frame2(room, placements, cam, sid_by_role, photos):
    rendered.append({'fov': cam.fov_deg, 'eye': cam.eye, 'w': cam.width, 'sid': dict(sid_by_role)})
    return Image.new('RGB', (cam.width, cam.height), (180, 170, 160)), {'clay': []}


DR.scene3d_frame = fake_frame2
calls.clear()


def model_wide(imgs, prompt, size='', quality='', model=''):
    calls.append({'n': len(imgs), 'size': size})
    return wide.copy()                                  # центр серый, пояс красный — после обрезки красного быть не должно


DR.gpt_edit = model_wide
DR.gw_credits = credits_spend
r = TH.run(tsc, os.path.join(base_dir, 'trial-go'), go=True, style='лофт')
j = json.load(open(os.path.join(base_dir, 'trial-go', 'hero.json'), encoding='utf-8'))
check('T-12 → кадр: ok, рисовали сами (без frame.jpg), один вызов модели', r['ok'] and len(rendered) == 1 and len(calls) == 1,
      r.get('error'))
check('T-12 → кадр: камера — ракурс героя, угол шире 72° (широкий кадр)', rendered and rendered[0]['fov'] > 72.5
      and j.get('rendered', {}).get('hero', {}).get('name') == 'hero' and j.get('overscan') == TH.OVERSCAN, rendered[:1])
hj = Image.open(os.path.join(base_dir, 'trial-go', 'hero.jpg'))
red = [hj.getpixel((x, y)) for x, y in ((2, 2), (1533, 2), (1533, 1021), (768, 2), (1533, 512))]
check('T-12 → кадр: ответ модели обрезан назад — пояса нет, размер запроса', hj.size == (1536, 1024)
      and all(p[0] - p[1] < 60 for p in red), red)
check('T-12 → кадр: широкий ответ модели сохранён для разбора — тоже с плашкой',
      os.path.exists(os.path.join(base_dir, 'trial-go', 'sources', '4-model-wide.jpg')))
check('T-12 → кадр: в json — риск у края (список) и источник', isinstance(j.get('rendered', {}).get('edge_risk'), list)
      and j.get('source') == 'trial:t1:лофт', j.get('rendered'))
DR.scene3d_frame = S3F

print(f'\nИТОГО: {"FAIL " + str(len(fails)) if fails else "OK"}')
sys.exit(1 if fails else 0)
