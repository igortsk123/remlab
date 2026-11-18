"""«УЛУЧШИТЬ» ИЗ РЕНДЕРА (T-20261117-19/2, ADR-0419: мебель как есть). Вход — кадры Cycles: задание — только фотографическая доводка (свет, тени,
фактура, резкость), без гайда стиля, листа эталонов, третьего листа и слов «дорисуй». Живое GPT-фото (кадры браузера) идёт прежним путём.
    python tools/scout/tests/test_improve_render_source.py        # без сети и модели
"""
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))
sys.path.append(os.path.join(HERE, '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_improve_render_source')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
from PIL import Image  # noqa: E402

import draft_render as DR  # noqa: E402
import improve_mode as IM  # noqa: E402

fails = []


def check(name, cond, info=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    if not cond:
        fails.append(name)


REND = {'key': 'k' * 32, 'scene_hash': 'h' * 64}
check('признак «вход — рендер»: только словарь с ключом рендера', IM.render_source({'render': REND}) and not IM.render_source({})
      and not IM.render_source({'render': {}}) and not IM.render_source({'render': 'x'}) and not IM.render_source(None))
check('версия промпта у рендера своя, у живого фото прежняя', IM.prompt_version({'render': REND}) == IM.PROMPT_VERSION_RENDER
      and IM.prompt_version({}) == IM.PROMPT_VERSION and IM.PROMPT_VERSION_RENDER != IM.PROMPT_VERSION)

# промпт: что разрешено и что нет — одно задание для всех комнат
for orient, word in ((None, 'stacked vertically'), ('portrait', 'side by side')):
    p = IM.render_polish_prompt(orient)
    check(f'промпт ({orient or "landscape"}): раскладка листа названа', word in p and '{layout}' not in p)
check('промпт: запрещены добавление, удаление, замена, перекраска; пол, обивка, шторы названы', all(w in IM.render_polish_prompt() for w in (
    'Do NOT add, remove, replace', 'chandeliers', 'curtains', 'Never turn leather into linen', 'never darken or lighten the floor', 'magenta band',
    'colour truth', 'never becomes natural wood', 'never becomes darker, warmer or more saturated wood', 'when in doubt, change less', 'not darker, not greyer, not pinker', 'do not lower the overall exposure')))
check('промпт: нет примера цвета конкретного пола («pale»/«honey»/«golden» — формулировка общая)', not any(w in IM.render_polish_prompt() for w in ('honey', 'golden', 'walnut', 'taupe', 'pale, slightly grey')))
check('промпт: разрешены свет, тени, фактура, резкость', all(w in IM.render_polish_prompt() for w in ('lighting realism', 'sharpness', 'micro-detail')))
check('промпт: нет гайда стиля, листов эталонов/декора и «дорисуй»', not any(w in IM.render_polish_prompt() for w in (
    'STYLE GUIDE', 'IMAGE 2', 'IMAGE 3', 'CEILING LIGHT', 'renovated room', 'draw')))

# ворота оплаты: у рендера листа эталонов нет по замыслу; у обычного заказа без листа — отказ, как было
def _gate(built):
    try:
        IM.paid_gate(built)
        return ''
    except DR.NoProductSheet as e:
        return str(e)


check('paid_gate: вход-рендер проходит без листа эталонов', _gate({'render': True, 'ident': None, 'n_items': 0, 'n_photos': 0}) == '')
check('paid_gate: обычный заказ без листа — по-прежнему отказ', 'нет листа товаров' in _gate({'ident': None}))

# сборка: два кадра рендера → один лист и промпт доводки; прежняя ветка не задета
tmp = tempfile.mkdtemp()
IM.frame_path = lambda fid: os.path.join(tmp, fid + '.jpg')
import hashlib  # noqa: E402
ids = []
for col in ((200, 180, 160), (160, 180, 200)):
    buf = io.BytesIO()
    Image.new('RGB', (1536, 1116), col).save(buf, 'JPEG')
    fid = hashlib.sha256(buf.getvalue()).hexdigest()           # имя кадра = sha256 его байтов, как у кадров браузера и рендера
    open(IM.frame_path(fid), 'wb').write(buf.getvalue())
    ids.append(fid)
DR._publish_sources = lambda *a, **k: None
pay = {'views': [{'camera': 'C1', 'id': ids[0]}, {'camera': 'C2', 'id': ids[1]}], 'items': [{'role': 'диван', 'name': 'Диван', 'img': 'x'}],
       'decor': [{'role': 'люстра', 'strategy': 'ceiling_over'}], 'style': 'сканди', 'render': REND}
b = IM.build_from_views(pay, 'сканди')
check('сборка из рендера: один лист, без эталонов и декора, промпт доводки', b['render'] is True and b['ident'] is None and b['dsheet'] is None
      and b['prompt'] == IM.render_polish_prompt(None) and b['sheet'].height > b['sheet'].width * 0.9 and b['prods_failed'] is False)
check('сборка из рендера: ворота оплаты пропускают', _gate(b) == '')
check('сборка из рендера: размер запроса и ориентация как у листа', b['size'] == IM.size_for(None) and b['orient'] == 'landscape')
pay_p = {**pay, 'sheet': 'portrait'}
bp = IM.build_from_views(pay_p, 'сканди')
check('сборка из рендера: лист телефона — виды бок о бок', bp['orient'] == 'portrait' and 'side by side' in bp['prompt'])

# ключ ответа: тот же кадр, но другой вход (рендер/браузер) — разные задания
k_render = IM.frames_key(pay, 'm', 'medium')
k_browser = IM.frames_key({k: v for k, v in pay.items() if k != 'render'}, 'm', 'medium')
check('ключ ответа: рендер и браузер с теми же кадрами — разные ключи (повтор не отдаёт чужое)', k_render != k_browser)
check('ключ ответа: тот же рендер — тот же ключ', IM.frames_key(pay, 'm', 'medium') == k_render)

print('итог:', 'чисто' if not fails else f'{len(fails)} провал(ов): {fails}')
sys.exit(1 if fails else 0)
