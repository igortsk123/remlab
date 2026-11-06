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
check('лист есть, список собран — проходит', raises(lambda: IM.paid_gate({'ident': img, 'prods_failed': False})) == '')
check('исходник с диска с листом (from_sources, поля prods_failed нет) — проходит', raises(lambda: IM.paid_gate({'ident': img})) == '')
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
DR.photo = lambda url: None
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
DR._identity = _orig_identity
sys.exit(1 if fails else 0)
