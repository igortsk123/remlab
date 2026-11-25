#!/usr/bin/env python3
"""Нормали лёгкой копии — только там, где их видно (T-64/3; замер порога — план/отчёт в `rules/rt-weight.json:normals._why`).
`tools/assets/runtime_mesh.py:has_normals/strip_normals/normals_dropped/normals_tag/recipe_for/build_light` + блок `normals` правила.
gltfpack подменён (как в `test_rt_weight.py`): тест смотрит, ЧТО ему отдали на упаковку (есть ли NORMAL во входе), без бинаря.
Проверяем: порог — только данные (правка файла правила меняет поведение, блока нет — нормали остаются, как раньше); граница «граней ≥ порога — убрать»;
решение по граням ШАГА лестницы (упрощение 0,6 возвращает нормали); у исходника без NORMAL ничего не меняется; метка в рецепте копии; рабочие файлы убраны.
Запуск: python tools/assets/tests/test_rt_normals.py"""
import io
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.append(os.path.join(HERE, '..', '..', 'scout'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_rt_normals')
import runtime_mesh as RM  # noqa: E402

FAILS = []


def ok(name, cond, extra=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    if not cond:
        FAILS.append(name)


def jpeg_bytes(px=8):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (px, px), (120, 100, 90)).save(buf, format='JPEG')
    return buf.getvalue()


def source_glb(tri=300_000, normals=True, px=512) -> bytes:
    """Исходник: цвет JPEG + один примитив на `tri` треугольников (счётчик индексов); `normals` — есть ли атрибут NORMAL."""
    payload = jpeg_bytes(px)
    attrs = {'POSITION': 1, **({'NORMAL': 2} if normals else {})}
    js = {'asset': {'version': '2.0'}, 'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
          'textures': [{'source': 0}], 'images': [{'bufferView': 0, 'mimeType': 'image/jpeg'}],
          'buffers': [{'byteLength': len(payload)}], 'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(payload)}],
          'accessors': [{'count': tri * 3, 'componentType': 5125, 'type': 'SCALAR'}, {'count': tri, 'componentType': 5126, 'type': 'VEC3'},
                        {'count': tri, 'componentType': 5126, 'type': 'VEC3'}],
          'meshes': [{'primitives': [{'indices': 0, 'attributes': attrs}]}]}
    return RM.write_glb(js, payload)


def packed_glb(nbytes: int) -> bytes:
    jp = jpeg_bytes()
    js = {'asset': {'version': '2.0'}, 'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
          'textures': [{'source': 0}], 'images': [{'bufferView': 0, 'mimeType': 'image/jpeg'}],
          'buffers': [{'byteLength': 0}], 'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(jp)}]}
    base = len(RM.write_glb(js, jp))
    return RM.write_glb(js, jp + b'\x00' * max(0, nbytes - base))


class SpyPack:
    """gltfpack: вес копии задаёт `weights(simplify)`; запоминает, был ли во входном файле NORMAL и как он назван."""
    def __init__(self, weights):
        self.weights, self.seen = weights, []

    def __call__(self, src, dst, simplify=0.0, ktx2=True):
        has = RM.has_normals(RM.parse_glb(open(src, 'rb').read())[0])
        self.seen.append((has, simplify, bool(re.search(r'\.src\d+\.glb$', src))))
        open(dst, 'wb').write(packed_glb(self.weights(simplify)))
        return True, ''


def leftovers(d):
    return sorted(f for f in os.listdir(d) if re.search(r'\.(src\d*(-m\d+)?|cand|new|nn)\b.*\.glb$|\.cand\.glb$', f))


def write_rule(d, name, max_faces=None, ladder=None):
    p = os.path.join(d, name)
    r = {'max_bytes': 1_000_000, 'ladder': ladder if ladder is not None else [{'simplify': 0.6}, {'simplify': 0.4}], 'min_triangles': 40000,
         'refuse_reason': 'rt_weight_over_limit', 'texture': {'size': 512, 'quality': 82}}
    if max_faces is not None:
        r['normals'] = {'max_faces': max_faces}
    json.dump(r, open(p, 'w'))
    return p


# ——— 1. правило: блок normals — данные, с проверкой ———
real = RM.weight_rule()
ok('боевое правило: блок normals с целым max_faces > 0', isinstance(real.get('normals', {}).get('max_faces'), int) and real['normals']['max_faces'] > 0, real.get('normals'))
_code = open(os.path.join(HERE, '..', 'runtime_mesh.py'), encoding='utf-8').read()
ok('порога граней в коде нет (число только в rules/rt-weight.json)', not re.search(rf'\b{real["normals"]["max_faces"]}\b|\b{real["normals"]["max_faces"] // 1000}_?000\b', _code), 'литерал порога в runtime_mesh.py')

with tempfile.TemporaryDirectory(dir=os.environ.get('REMLAB_TMP') or None) as d:
    for label, blk in (('0', {'max_faces': 0}), ('строка', {'max_faces': '200000'}), ('bool', {'max_faces': True}), ('без числа', {}), ('не словарь', 5)):
        p = os.path.join(d, 'bad.json')
        json.dump({'max_bytes': 10, 'ladder': [], 'texture': {'size': 512, 'quality': 82}, 'normals': blk}, open(p, 'w'))
        try:
            RM.weight_rule(p)
            ok(f'normals {label} — ошибка правила', False)
        except ValueError:
            ok(f'normals {label} — ошибка правила', True)

    # ——— 2. помощники ———
    src = source_glb(300_000)
    js = RM.parse_glb(src)[0]
    ok('has_normals: у исходника с NORMAL — да, без — нет', RM.has_normals(js) and not RM.has_normals(RM.parse_glb(source_glb(10, normals=False))[0]))
    st = RM.strip_normals(src)
    sj = RM.parse_glb(st)[0]
    ok('strip_normals: NORMAL убран, POSITION и индексы на месте, GLB разбирается', not RM.has_normals(sj) and 'POSITION' in sj['meshes'][0]['primitives'][0]['attributes']
       and sj['meshes'][0]['primitives'][0]['indices'] == 0)
    r_off = RM.weight_rule(write_rule(d, 'off.json'))
    r_200 = RM.weight_rule(write_rule(d, 'r200.json', 200_000))
    ok('нет блока normals — нормали не убираем никогда', not RM.normals_dropped(r_off, 10_000_000))
    ok('граней ровно порог — убираем (≥)', RM.normals_dropped(r_200, 200_000))
    ok('граней на одну меньше порога — оставляем', not RM.normals_dropped(r_200, 199_999))
    ok('метка рецепта: нет блока — пусто; есть — с порогом', RM.normals_tag(r_off) == '' and RM.normals_tag(r_200) == 'nrm<200000', (RM.normals_tag(r_off), RM.normals_tag(r_200)))
    ok('рецепт копии: у исходника с NORMAL метка порога добавлена', RM.recipe_for(src, 'r', r_200).endswith(';nrm<200000'), RM.recipe_for(src, 'r', r_200))
    ok('  у исходника без NORMAL рецепт прежний (старые копии остаются свежими)', RM.recipe_for(source_glb(10, normals=False), 'r', r_200) == 'r')
    ok('  без блока normals рецепт прежний', RM.recipe_for(src, 'r', r_off) == 'r')

    # ——— 3. build_light: что уходит на упаковку ———
    real_pack = RM.pack
    try:
        def run(rule_name, max_faces, source, weights, ladder=None):
            rule = RM.weight_rule(write_rule(d, rule_name, max_faces, ladder))
            spy = SpyPack(weights)
            RM.pack = spy
            dst = os.path.join(d, rule_name.replace('.json', '.glb'))
            res = RM.build_light(source, dst, 512, 82, 0.0, True, rule)
            return res, spy

        res, spy = run('a.json', 200_000, src, lambda s: 500_000)
        ok('300 тыс. граней при пороге 200 тыс.: на упаковку ушёл вход БЕЗ NORMAL, шаг записан «dropped»',
           res['ok'] and spy.seen == [(False, 0.0, True)] and res['tried'][0]['normals'] == 'dropped', (res['tried'], spy.seen))
        res, spy = run('b.json', 400_000, src, lambda s: 500_000)
        ok('300 тыс. граней при пороге 400 тыс.: NORMAL на месте, шаг «kept»', res['ok'] and spy.seen == [(True, 0.0, True)] and res['tried'][0]['normals'] == 'kept', (res['tried'], spy.seen))
        res, spy = run('c.json', None, src, lambda s: 500_000)
        ok('блока нет: NORMAL на месте, пометки normals в шагах нет (как до T-64/3)', res['ok'] and spy.seen == [(True, 0.0, True)] and 'normals' not in res['tried'][0], (res['tried'], spy.seen))
        res, spy = run('d.json', 200_000, source_glb(300_000, normals=False), lambda s: 500_000)
        ok('исходник без NORMAL: ничего не меняется, пометки нет', res['ok'] and spy.seen == [(False, 0.0, True)] and 'normals' not in res['tried'][0], (res['tried'], spy.seen))
        # решение — по граням ШАГА: тяжёлая копия идёт по лестнице, на 0,6 граней 180 тыс. < 200 тыс. — нормали возвращаются
        res, spy = run('e.json', 200_000, src, lambda s: 800_000 if s == 0.4 else 1_500_000, ladder=[{'simplify': 0.6}, {'simplify': 0.4}])
        seq = [(t['step'], t.get('normals')) for t in res['tried']]
        ok('лестница: 300к → dropped, 0,6 (180к) → kept; вход упаковщику без/с NORMAL', [n for _s, n in seq][:2] == ['dropped', 'kept'] and [x[0] for x in spy.seen][:2] == [False, True], (seq, spy.seen))
        ok('  рабочих файлов нет (в т. ч. «.nn.»)', leftovers(d) == [], leftovers(d))
    finally:
        RM.pack = real_pack

if FAILS:
    print(f'\n{len(FAILS)} провал(ов)')
    sys.exit(1)
print('\nвсе проверки прошли')
