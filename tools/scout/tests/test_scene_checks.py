"""Артефакты сцены демо (demo-05 п.1): наезд считается по следу предмета (Г-диван — 6 точек), а не по габаритам —
один расчёт у ворот (`scene_checks.overlap_pairs`) и ночного отчёта (`scene_artifacts.py`); текстура в лёгкой копии —
есть, не пустая, разбирается; ковёр и ваза — в данных. Без сети, базы и файлов витрины.
    ~/venvs/scout/bin/python tools/scout/tests/test_scene_checks.py"""
import io
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


from shapely.geometry import box  # noqa: E402

import scene_artifacts as A  # noqa: E402
import scene_checks as SC  # noqa: E402


def it(role, x, y, w, d, rot=0, **kw):
    return {'role': role, 'x': x, 'y': y, 'w': w, 'd': d, 'rot': rot, 'sku': {}, **kw}


# ——— наезды (диван 200×90 у стены: y 5…95)
sofa = it('диван', 100, 50, 200, 90)
check('нет наезда: столик в 30 см перед диваном', SC.overlap_pairs([sofa, it('столик', 100, 150, 100, 50)]) == [])
p = SC.overlap_pairs([sofa, it('столик', 100, 115, 100, 50)])
check(f'наезд 5 см: {p}', len(p) == 1 and p[0]['depth_cm'] == 5 and p[0]['len_cm'] == 100)
p = SC.overlap_pairs([sofa, it('тумба', 100, 115, 50, 100, rot=90)])
check('наезд 5 см у повёрнутого предмета', len(p) == 1 and p[0]['depth_cm'] == 5)
check('наезд 1 см — ниже порога 2 см', SC.overlap_pairs([sofa, it('столик', 100, 119, 100, 50)]) == [])
check('ковёр — подложка, не наезд', SC.overlap_pairs([sofa, it('ковёр', 100, 100, 230, 160)]) == [])
check('строка ворот не изменилась', SC.overlaps([sofa, it('столик', 100, 115, 100, 50)]) == ['наезд диван × столик: 100×5 см'])

# Г-диван 186×151, оттоманка 95 справа (как лофт 18.10): x 86…272, y 0…151; столик 75×75 в «вырезе» слева
corner = it('диван', 179, 75.5, 186, 151, corner=True, corner_left=False, section=95)
table = it('столик', 107.5, 175, 75, 75)
check('Г-след: столик в вырезе — наезда нет', SC.overlap_pairs([corner, table]) == [])
bb = box(86, 0, 272, 151).intersection(box(70, 137.5, 145, 212.5)).bounds
check(f'по прямоугольному габариту тот же столик дал бы ложный наезд {bb[2] - bb[0]:g}×{bb[3] - bb[1]:g} см',
      bb[3] - bb[1] > 10)
p = SC.overlap_pairs([dict(corner, corner_left=True), table])
check(f'Г-след зеркальный: столик въезжает в оттоманку на {p and p[0]["depth_cm"]} см', len(p) == 1 and p[0]['depth_cm'] > 2)


# ——— текстуры в GLB
def glb(img: bytes, mime: str, with_material=True) -> bytes:
    j = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(img)}],
         'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(img)}],
         'images': [{'bufferView': 0, 'mimeType': mime}], 'textures': [{'source': 0}],
         'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}} if with_material else {}}]}
    js = json.dumps(j).encode()
    js += b' ' * (-len(js) % 4)
    bn = img + b'\0' * (-len(img) % 4)
    body = struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(bn), 0x004E4942) + bn
    return struct.pack('<III', 0x46546C67, 2, 12 + len(body)) + body


from PIL import Image  # noqa: E402

buf = io.BytesIO()
Image.new('RGB', (8, 8), (200, 180, 160)).save(buf, 'PNG')
png = buf.getvalue()
check('PNG-текстура под материалом — годна', A.glb_textures(glb(png, 'image/png')) == (1, []))
check('битый PNG — 0 годных', A.glb_textures(glb(png[:20], 'image/png'))[0] == 0)
check('материал без карты цвета — 0 текстур', A.glb_textures(glb(png, 'image/png', with_material=False)) == (0, []))


def ktx2(level_len=16) -> bytes:
    hdr = A.KTX2_ID + struct.pack('<9I', 0, 1, 8, 8, 0, 0, 1, 1, 2) + struct.pack('<4I2Q', 0, 0, 0, 0, 0, 0)
    return hdr + struct.pack('<3Q', len(hdr) + 24, level_len, level_len) + b'\x01' * level_len


check('KTX2 по спецификации — цел', A.check_image(ktx2(), 'image/ktx2') == '')
check('KTX2 в GLB — годна', A.glb_textures(glb(ktx2(), 'image/ktx2')) == (1, []))
check('KTX2 обрезан — уровень за концом файла', A.check_ktx2(ktx2()[:-8]) != '')
check('KTX2 с пустым уровнем — битый', A.check_ktx2(ktx2(level_len=0)) != '')
check('пустая картинка — битая', A.check_image(b'', 'image/ktx2') != '')

# ——— ковёр и декор
good = {'items': [it('ковёр', 1, 1, 2, 2, sku={'img': 'https://x/y.jpg', 'price': 9990})],
        'decor': [{'role': 'ваза', 'sku': {'price': 1790, 'msid': '1_2'}}]}
check('ковёр с фото и ценой, ваза с ценой и моделью — чисто', A.check_rug_decor(good, '') == [])
bad = {'items': [it('ковёр', 1, 1, 2, 2, sku={'img': '', 'price': 0})], 'decor': []}
probs = {x['problem'] for x in A.check_rug_decor(bad, '')}
check('ковёр без фото и цены, нет вазы — три находки', probs == {'ковёр без фото', 'ковёр без цены', 'нет вазы в декоре'})

check('фото ковра на диске: нет файла — не видно', not A.photo_exists('/nonexistent-dir', 'img/x.jpg'))

# ——— вердикт ночного шага: красное — одна WARN-строка с названиями вариантов, зелёное — одна строка OK с числами
def summ(vid, title, **kw):
    return {'variant': vid, 'style': title.lower(), 'title': title, 'overlaps_gt_thr': 0, 'max_overlap_cm': 0.0,
            'models': 8, 'models_without_texture': 0, 'chaise_notes': 0, 'rug_decor_problems': 0, **kw}


green = {'threshold_cm': 2.0, 'rows': [], 'summary': [summ('set1', 'Сканди'), summ('set6', 'Современный')]}
v = A.verdict(green)
check(f'зелёное — одна строка OK с числами: {v}', len(v) == 1 and v[0].startswith('scene_artifacts: OK')
      and 'вариантов 2' in v[0] and 'моделей 16' in v[0] and not v[0].startswith('WARN'))
red = {'threshold_cm': 2.0, 'summary': [summ('set1', 'Сканди', overlaps_gt_thr=1, max_overlap_cm=3.5),
                                        summ('set6', 'Современный'),
                                        summ('set11', 'Лофт', models_without_texture=1, rug_decor_problems=1)],
       'rows': [{'variant': 'set11', 'check': 'ж', 'problem': 'нет вазы в декоре'}]}
v = A.verdict(red)
check(f'красное — одна WARN-строка со всеми красными вариантами: {v}',
      len(v) == 1 and v[0].startswith('WARN:scene_artifacts: красных 2 из 3') and 'Сканди (set1): наезд 3.5 см' in v[0]
      and 'Лофт (set11): без текстуры 1, нет вазы в декоре' in v[0] and 'Современный' not in v[0])
check('заметка об оттоманке — не красное', A.verdict({**green, 'summary': [summ('set1', 'Сканди', chaise_notes=1)]})[0]
      .startswith('scene_artifacts: OK'))
check('нет вариантов — тревога', A.verdict({**green, 'summary': []})[0].startswith('WARN:scene_artifacts:'))

print('ИТОГ:', 'всё OK' if not fails else f'{fails} FAIL')
sys.exit(1 if fails else 0)
