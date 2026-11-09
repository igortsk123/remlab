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

# 3) плашка — на картинке, внизу слева; верх не тронут; узкий кадр — влезает
src = Image.new('RGB', (1536, 1024), (240, 240, 240))
b = TH.badge(src)
px_box = b.getpixel((60, 1024 - 40))
px_top = b.getpixel((60, 40))
check('плашка: подложка тёмная внизу слева', sum(px_box) < 300, px_box)
check('плашка: верх кадра не тронут', px_top == (240, 240, 240), px_top)
row = [b.getpixel((x, 1024 - 45)) for x in range(0, 1536)]
dark = [x for x, p in enumerate(row) if sum(p) < 300]
check('плашка: ширина 40–92 % кадра (читается на телефоне)', dark and 0.40 * 1536 < (dark[-1] - dark[0]) < 0.92 * 1536,
      (dark[0], dark[-1]) if dark else None)
nb = TH.badge(Image.new('RGB', (600, 900), (240, 240, 240)))
nrow = [x for x in range(600) if sum(nb.getpixel((x, 900 - 20))) < 300]
check('плашка: узкий кадр 600 px — не вылезает за край', nrow and nrow[-1] < 595, nrow[-1] if nrow else None)
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
check('платный: на hero.jpg стоит плашка', sum(hero.getpixel((60, hero.height - 40))) < 300)
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


DR.scene_from_request = lambda p: ('room', ['pl'], {})
DR.cams_from_request = lambda room, pl, p: [_Cam(), _Cam()]


def fake_frame(room, placements, cam, sid_by_role, photos):
    rendered.append({'w': cam.width, 'h': cam.height, 'shift': getattr(cam, 'shift_y', None), 'sid': dict(sid_by_role),
                     'lite': DR.S3_LITE[0]})
    return Image.new('RGB', (cam.width, cam.height), (180, 170, 160)), {'clay': ['тв', 'ковёр']}


DR.scene3d_frame = fake_frame
DR.S3_LITE[0] = True
r = TH.run(sc3, os.path.join(base_dir, 'render'), go=False, render=True)
check('--render: один кадр одной камеры, размер запроса, полные меши', r['ok'] and len(rendered) == 1 and
      (rendered[0]['w'], rendered[0]['h']) == (1536, 1024) and rendered[0]['lite'] is False, rendered or r.get('error'))
check('--render: сдвиг камеры (поза) сохраняется', rendered and rendered[0]['shift'] == 0.02, rendered and rendered[0]['shift'])
check('--render: «стул 2» без меша берёт меш «стул»', rendered and rendered[0]['sid'].get('стул 2') == 'm-st', rendered and rendered[0]['sid'])
check('--render: время рендера и заглушки — в json (тв не считается)', 'render' in r['timing'] and r.get('rendered', {}).get('clay') == ['ковёр'],
      r.get('rendered'))

print(f'\nИТОГО: {"FAIL " + str(len(fails)) if fails else "OK"}')
sys.exit(1 if fails else 0)
