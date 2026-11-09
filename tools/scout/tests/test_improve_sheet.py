"""ЛИСТ ТОВАРОВ ОБЯЗАТЕЛЕН (план room-photos-07 п.3, T-20261106-88): без листа эталонов или списка товаров платное улучшение не
делается — `improve_mode.paid_gate` бросает `draft_render.NoProductSheet` ДО вызова модели, сервис кадров отвечает 422; после замены
товара лист и список пересобираются и содержат новый SKU.

    python tools/scout/tests/test_improve_sheet.py        # без сети и модели: заглушки сборки листа и вызова модели
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))   # см. test_browser_sheet.py
from PIL import Image  # noqa: E402

import draft_render as DR  # noqa: E402
import improve_mode as IM  # noqa: E402

fails = []


def check(name, cond, info=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    if not cond:
        fails.append(name)


def raises(fn):
    try:
        fn()
    except DR.NoProductSheet as e:
        return str(e)
    return ''


# 1) ворота: нет листа эталонов — отказ; список товаров v4 не собрался — отказ; всё есть — проходит
img = Image.new('RGB', (8, 8))
check('нет листа эталонов — отказ до оплаты', 'нет листа товаров' in raises(lambda: IM.paid_gate({'ident': None, 'sheet': img})))
check('список товаров (v4) не собрался — отказ', 'список товаров' in raises(lambda: IM.paid_gate({'ident': img, 'prods_failed': True})))
check('лист есть, список собран — проходит',
      raises(lambda: IM.paid_gate({'ident': img, 'prods_failed': False, 'n_items': 7, 'n_photos': 7})) == '')
check('исходник с диска с листом (from_sources, поля prods_failed нет) — проходит',
      raises(lambda: IM.paid_gate({'ident': img, 'n_items': 5, 'n_photos': 5})) == '')

# 1б) ФОТО НА ЛИСТЕ (T-20261109-17): лист из карточек «фото нет» — отказ; порог 3/4; счёт неизвестен — отказ
e0 = raises(lambda: IM.paid_gate({'ident': img, 'n_items': 9, 'n_photos': 0}))
check('0 фото из 9 — отказ, причина словами', 'фото товаров на листе 0 из 9' in e0, e0)
check('3 из 4 (ровно порог) — проходит', raises(lambda: IM.paid_gate({'ident': img, 'n_items': 4, 'n_photos': 3})) == '')
check('2 из 4 — отказ', 'фото товаров на листе 2 из 4' in raises(lambda: IM.paid_gate({'ident': img, 'n_items': 4, 'n_photos': 2})))
check('6 из 9 (0,67) — отказ, 7 из 9 — проходит',
      raises(lambda: IM.paid_gate({'ident': img, 'n_items': 9, 'n_photos': 6})) != ''
      and raises(lambda: IM.paid_gate({'ident': img, 'n_items': 9, 'n_photos': 7})) == '')
check('лист без позиций (0 из 0) — отказ', raises(lambda: IM.paid_gate({'ident': img, 'n_items': 0, 'n_photos': 0})) != '')
check('счёт фото неизвестен (старая сборка) — отказ', 'неизвестно' in raises(lambda: IM.paid_gate({'ident': img})))
check('порог — константа 3/4', IM.MIN_PHOTO_SHARE == 0.75)

# 1в) счёт как у листа (`_identity`): без названия — не позиция; «стул» и «стул 2» одного товара — одна карточка; фото — первой роли
_px = Image.new('RGB', (4, 4))
_its = [{'role': 'стул', 'name': 'Стул Асти', 'img': 'u1'}, {'role': 'стул 2', 'name': 'Стул Асти', 'img': 'u1'},
        {'role': 'диван', 'name': 'Диван Викс', 'img': 'u2'}, {'role': 'тв', 'name': None},
        {'role': 'кресло', 'name': 'Кресло Оскар', 'img': None}]
check('счёт: 3 позиции, 2 с фото', IM.sheet_counts(_its, {'стул': _px, 'стул 2': _px, 'диван': _px}) == (3, 2),
      IM.sheet_counts(_its, {'стул': _px, 'стул 2': _px, 'диван': _px}))
check('счёт: «стул 2» с фото не спасает «стул» без фото (карточка — первой роли)',
      IM.sheet_counts(_its, {'стул 2': _px, 'диван': _px}) == (3, 1))
check('отказ — свой тип, а не общий RuntimeError запасного пути', issubclass(DR.NoProductSheet, RuntimeError)
      and DR.NoProductSheet is not DR.NoCreditsError)

# 2) ворота стоят В ПЛАТНОМ ПУТИ перед вызовом модели, а сервис отвечает на отказ 4xx (прод не повторяет запасным рендером)
src = open(os.path.join(HERE, '..', 'draft_render.py'), encoding='utf-8').read()
i_gate, i_call = src.find('IM.paid_gate(built)'), src.find('out = gpt_edit(imgs, prompt, size=built.get(')
check('draft_render: paid_gate перед gpt_edit улучшения', 0 < i_gate < i_call, (i_gate, i_call))
svc = open(os.path.join(HERE, '..', 'draft_service.py'), encoding='utf-8').read()
check('draft_service: NoProductSheet → 422 no_product_sheet', "except DR.NoProductSheet" in svc and "'code': 'no_product_sheet'" in svc
      and svc.find('except DR.NoProductSheet') < svc.find('except Exception as e:                       # noqa: BLE001 — наружу'))

# 3) build_from_views: сбой листа эталонов → ident None → отказ; замена товара → новый лист с новым SKU в эталонах и в списке
seen = []
IM.load_frame = lambda fid: Image.new('RGB', (2048, 1489), (120, 120, 120))
_BROKEN = set()                      # адреса, по которым фото «не скачалось» (неверный путь `img/`)
DR.photo = lambda url: None if (not url or url in _BROKEN or '/img/' in url) else Image.new('RGB', (32, 32), (200, 150, 100))
DR._publish_sources = lambda *a, **k: None
_orig_identity = DR._identity


def ident_ok(anchors, photos, skus):
    seen.append(sorted((v or {}).get('name') for v in skus.values()))
    return Image.new('RGB', (64, 64), (255, 255, 255))


def ident_fail(anchors, photos, skus):
    raise OSError('фото не скачалось')


def payload(sofa):
    return {'style': 'сканди', 'views': [{'camera': 'C1', 'id': 'a'}, {'camera': 'C2', 'id': 'b'}],
            'items': [{'role': 'диван', 'name': sofa, 'img': f'https://x/{sofa}.jpg'},
                      {'role': 'кресло', 'name': 'Кресло Оскар', 'img': 'https://x/k.jpg'}]}


IM.PROMPT_V4 = True
IM._IDENT_CACHE.clear()
DR._identity = ident_fail
b = IM.build_from_views(payload('Диван Лонг'), 'сканди', stamp='t1')
check('сбой листа эталонов — сборка возвращает ident None (раньше так и уходило в модель)', b['ident'] is None)
check('…и ворота отказывают', 'нет листа товаров' in raises(lambda: IM.paid_gate(b)))
DR._identity = ident_ok
b1 = IM.build_from_views(payload('Диван Лонг'), 'сканди', stamp='t2')
b2 = IM.build_from_views(payload('Диван Ричмонд'), 'сканди', stamp='t3')
check('замена товара — лист эталонов пересобран (не из кэша прежнего набора)', len(seen) == 2, seen)
check('новый SKU в листе эталонов, прежнего нет', seen[-1] == ['Диван Ричмонд', 'Кресло Оскар'], seen)
check('новый SKU в списке товаров промпта v4, прежнего нет', 'Диван Ричмонд' in b2['prompt'] and 'Диван Лонг' not in b2['prompt'])
check('после замены ворота пропускают', raises(lambda: IM.paid_gate(b2)) == '' and raises(lambda: IM.paid_gate(b1)) == '')
IM.build_from_views(payload('Диван Ричмонд'), 'сканди', stamp='t4')
check('тот же набор — лист из кэша (повтор не пересобирает)', len(seen) == 2, seen)
_orig_pl = IM.product_list
IM.product_list = lambda *a, **k: (_ for _ in ()).throw(ValueError('сбой'))
b3 = IM.build_from_views(payload('Диван Ричмонд'), 'сканди', stamp='t5')
check('список товаров v4 упал — ворота отказывают', 'список товаров' in raises(lambda: IM.paid_gate(b3)))
IM.product_list = _orig_pl
IM.PROMPT_V4 = False
b4 = IM.build_from_views(payload('Диван Ричмонд'), 'сканди', stamp='t6')
check('промпт v3 (без списка товаров) — лист эталонов есть, ворота пропускают', raises(lambda: IM.paid_gate(b4)) == '')
check('сборка отдаёт счёт фото (2 из 2)', (b4.get('n_items'), b4.get('n_photos')) == (2, 2), (b4.get('n_items'), b4.get('n_photos')))

# 4) ДЫРА T-17: лист собран, но у всех 9 карточек «фото нет» (неверный путь `img/`) — отказ ДО вызова модели, модель не звали
calls = []


def paid_path(built):
    """Порядок платного пути `draft_render` (ворота → `gpt_edit`), вызов модели — заглушка-счётчик."""
    IM.paid_gate(built)
    calls.append('gpt_edit')


nine = {'style': 'сканди', 'views': [{'camera': 'C1', 'id': 'a'}, {'camera': 'C2', 'id': 'b'}],
        'items': [{'role': f'предмет {i}', 'name': f'Товар {i}', 'img': f'https://x/demo/img/{i}.jpg'} for i in range(9)]}
b9 = IM.build_from_views(nine, 'сканди', stamp='t7')
check('лист из 9 карточек собран (ident есть), фото 0 из 9', b9['ident'] is not None and (b9['n_items'], b9['n_photos']) == (9, 0),
      (b9.get('n_items'), b9.get('n_photos')))
e9 = raises(lambda: paid_path(b9))
check('0 из 9 — отказ, модель не вызвана', 'фото товаров на листе 0 из 9' in e9 and calls == [], (e9, calls))
four = {**nine, 'items': [{'role': f'предмет {i}', 'name': f'Товар {i}', 'img': f'https://x/ok/{i}.jpg'} for i in range(4)]}
_BROKEN.add('https://x/ok/3.jpg')
b34 = IM.build_from_views(four, 'сканди', stamp='t8')
check('3 из 4 — модель вызвана', raises(lambda: paid_path(b34)) == '' and calls == ['gpt_edit'] and b34['n_photos'] == 3, (calls, b34.get('n_photos')))
nothing = {**nine, 'items': [{'role': 'диван', 'name': None, 'img': None}]}
DR._identity = _orig_identity
b0 = IM.build_from_views(nothing, 'сканди', stamp='t9')
check('лист без товаров — прежний отказ «нет листа товаров»', 'нет листа товаров' in raises(lambda: paid_path(b0)) and calls == ['gpt_edit'])

# 5) from_sources: счёт фото — из легенды исходника; папка без счёта (до T-17) — пересборка, а не платный вызов вслепую
import json as _json  # noqa: E402
import tempfile  # noqa: E402
_tmpd = tempfile.TemporaryDirectory(prefix='improve-src-')      # убирается сам по выходу
_tmp = DR.SRC_DIR = _tmpd.name
_w, _h = (int(x) for x in IM.SIZE.split('x'))
for sid, meta in (('old', {'версия промпта': IM.PROMPT_VERSION, 'качество': 'full'}),
                  ('new', {'версия промпта': IM.PROMPT_VERSION, 'качество': 'full', **IM._photo_meta(9, 0)})):
    os.makedirs(os.path.join(_tmp, sid))
    Image.new('RGB', (_w // 8, _h // 8)).save(os.path.join(_tmp, sid, '1-ОТПРАВЛЯЕМ-лист-двух-видов.jpg'))
    Image.new('RGB', (64, 64)).save(os.path.join(_tmp, sid, '2-ОТПРАВЛЯЕМ-эталоны-товаров.jpg'))
    open(os.path.join(_tmp, sid, 'prompt.txt'), 'w', encoding='utf-8').write('p')
    open(os.path.join(_tmp, sid, 'meta.json'), 'w', encoding='utf-8').write(_json.dumps(meta, ensure_ascii=False))
check('исходник без счёта фото — пересборка (None)', IM.from_sources('old') is None)
fs = IM.from_sources('new')
check('исходник со счётом — счёт в сборке, ворота отказывают на 0 из 9',
      fs is not None and (fs['n_items'], fs['n_photos']) == (9, 0) and '0 из 9' in raises(lambda: IM.paid_gate(fs)))
sys.exit(1 if fails else 0)
