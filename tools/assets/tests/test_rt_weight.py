#!/usr/bin/env python3
"""Порог веса лёгкой копии и лестница для тяжёлой (П-4, владелец TG 2671; план painted-to-rt-01, T-20261120-150/1).
`tools/assets/runtime_mesh.py:weight_rule/ladder_steps/build_light/main` + `rules/rt-weight.json`. gltfpack подменён (как в
`test_rt_texture_guard.py`): вес копии задаёт подмена по стороне текстуры и доле граней, поэтому тест быстрый и без бинаря.
Проверяем: порог ТОЛЬКО в данных (в коде литерала нет, правка файла правила меняет поведение); лестница идёт строго по порядку
1024 → 512 → упрощение → отказ; рабочие файлы убраны при любом исходе; прежняя копия не затёрта; отказ записан в манифест с причиной,
не гоняется повторно, роняет ворота `--check`, попадает в `WARN:rt_weight`; порог в `publish_rt.sh` читается из правила.
Запуск: python tools/assets/tests/test_rt_weight.py"""
import contextlib
import io
import json
import os
import re
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.append(os.path.join(HERE, '..', '..', 'scout'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_rt_weight')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
import runtime_mesh as RM  # noqa: E402

FAILS = []
MB = 1_000_000


def ok(name, cond, extra=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    if not cond:
        FAILS.append(name)


def jpeg_bytes(px=8):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (px, px), (120, 100, 90)).save(buf, format='JPEG')
    return buf.getvalue()


def source_glb(tri=300_000, px=2048) -> bytes:
    """Исходник: один материал с картой цвета (JPEG px×px) и один примитив на `tri` треугольников (счётчик акцессора индексов)."""
    payload = jpeg_bytes(px)
    js = {'asset': {'version': '2.0'}, 'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
          'textures': [{'source': 0}], 'images': [{'bufferView': 0, 'mimeType': 'image/jpeg'}],
          'buffers': [{'byteLength': len(payload)}], 'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(payload)}],
          'accessors': [{'count': tri * 3, 'componentType': 5125, 'type': 'SCALAR'}], 'meshes': [{'primitives': [{'indices': 0}]}]}
    return RM.write_glb(js, payload)


def packed_glb(nbytes: int) -> bytes:
    """Годная «упакованная» копия (JPEG в бинарном чанке, проходит `copy_problems`) заданного веса: добиваем хвост бинарного чанка."""
    jp = jpeg_bytes()
    js = {'asset': {'version': '2.0'}, 'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
          'textures': [{'source': 0}], 'images': [{'bufferView': 0, 'mimeType': 'image/jpeg'}],
          'buffers': [{'byteLength': 0}], 'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(jp)}]}
    base = len(RM.write_glb(js, jp))
    pad = max(0, nbytes - base)
    out = RM.write_glb(js, jp + b'\x00' * pad)
    return out


def write_rule(d, name, max_bytes, ladder=None, min_tri=40000):
    p = os.path.join(d, name)
    json.dump({'max_bytes': max_bytes, 'ladder': ladder if ladder is not None else [{'size': 1024}, {'size': 512}, {'simplify': 0.6}, {'simplify': 0.4}],
               'min_triangles': min_tri, 'refuse_reason': 'rt_weight_over_limit'}, open(p, 'w'))
    return p


class FakePack:
    """gltfpack: вес копии = f(сторона текстуры из имени `.srcN.glb`, доля граней)."""
    def __init__(self, weights):
        self.weights, self.calls = weights, []

    def __call__(self, src, dst, simplify=0.0, ktx2=True):
        m = re.search(r'\.src(\d+)\.glb$', src)
        size = int(m.group(1)) if m else 0
        self.calls.append((size, simplify, ktx2))
        n = self.weights(size, simplify)
        with open(dst, 'wb') as fh:
            fh.write(packed_glb(n))
        return True, ''


def leftovers(d):
    return sorted(f for f in os.listdir(d) if re.search(r'\.(src\d*|cand|new)\.glb$|\.cand\.new\.glb$|\.cand\.glb$', f))


# ——— 1. порог — только в данных ———
rule = RM.weight_rule()
ok('порог из rules/rt-weight.json: 5 МБ (5 242 880 — решение П-4, TG 2671)', rule['max_bytes'] == 5 * 1024 * 1024, rule['max_bytes'])
ok('лестница из правила: 1024 → 512 → упрощение 0,6 → 0,4', rule['ladder'] == [{'size': 1024}, {'size': 512}, {'simplify': 0.6}, {'simplify': 0.4}], rule['ladder'])
code_files = [os.path.join(HERE, '..', f) for f in ('runtime_mesh.py', 'publish_rt.sh', 'demo_rt.sh')]
lit = re.compile(r'5242880|5\s*\*\s*1024\s*\*\s*1024|5\s*<<\s*20|5\s*\*\s*2\s*\*\*\s*20|\b5_?000_?000\b')
found = [os.path.basename(f) for f in code_files if lit.search(open(f, encoding='utf-8').read())]
ok('в коде (runtime_mesh.py, publish_rt.sh, demo_rt.sh) литерала порога нет', not found, found)

with tempfile.TemporaryDirectory(dir=os.environ.get('REMLAB_TMP') or None) as d:
    bad = os.path.join(d, 'bad.json')
    json.dump({'max_bytes': 0, 'ladder': []}, open(bad, 'w'))
    try:
        RM.weight_rule(bad)
        ok('порог 0 — ошибка правила', False)
    except ValueError:
        ok('порог 0 — ошибка правила', True)
    both = os.path.join(d, 'both.json')
    json.dump({'max_bytes': 10, 'ladder': [{'size': 512, 'simplify': 0.5}]}, open(both, 'w'))
    try:
        RM.weight_rule(both)
        ok('шаг лестницы и с size, и с simplify — ошибка правила', False)
    except ValueError:
        ok('шаг лестницы и с size, и с simplify — ошибка правила', True)

    # ——— 2. шаги лестницы ———
    lab = lambda st: [s[0] for s in st]  # noqa: E731
    ok('шаги при запуске 1024: 1024, 512, 512+si0.6, 512+si0.4', lab(RM.ladder_steps(rule, 1024, 0.0)) == ['1024', '512', '512+si0.6', '512+si0.4'], RM.ladder_steps(rule, 1024, 0.0))
    ok('у -lite (запуск 512): шаги 1024 и 512 пустые → 512, +si0.6, +si0.4', lab(RM.ladder_steps(rule, 512, 0.0)) == ['512', '512+si0.6', '512+si0.4'])
    ok('запуск уже с упрощением 0,5: шаги мягче (0,6) пропущены, 0,4 остаётся', lab(RM.ladder_steps(rule, 1024, 0.5)) == ['1024+si0.5', '512+si0.5', '512+si0.4'])

    # ——— 3. build_light: лестница по порядку ———
    src = source_glb(tri=300_000)
    real_pack, real_opt = RM.pack, RM.optimise
    LIM = 1_000_000
    r1 = write_rule(d, 'r1.json', LIM)
    rule1 = RM.weight_rule(r1)
    try:
        # 3a. первый шаг легче порога — копия с 1024, один шаг, ничего лишнего
        dst = os.path.join(d, 'a.glb')
        fp = FakePack(lambda s, si: 600_000)
        RM.pack = fp
        res = RM.build_light(src, dst, 1024, 82, 0.0, True, rule1)
        ok('первый шаг ≤ порога: копия записана, шаг один', res['ok'] and len(res['tried']) == 1 and os.path.exists(dst) and fp.calls == [(1024, 0.0, True)], (res['tried'], fp.calls))
        ok('  рабочих файлов нет', leftovers(d) == [], leftovers(d))

        # 3b. 1024 тяжелее, 512 легче → ровно два шага, берётся 512
        dst = os.path.join(d, 'b.glb')
        fp = FakePack(lambda s, si: 1_500_000 if s == 1024 else 800_000)
        RM.pack = fp
        res = RM.build_light(src, dst, 1024, 82, 0.0, True, rule1)
        ok('1024 тяжёлая, 512 годится: шаги 1024 → 512, копия 512', res['ok'] and [t['step'] for t in res['tried']] == ['1024', '512'] and os.path.getsize(dst) <= LIM, res['tried'])
        ok('  вес каждого шага записан', all(t.get('bytes') for t in res['tried']))
        ok('  рабочих файлов нет', leftovers(d) == [], leftovers(d))

        # 3c. 512 всё ещё тяжёлая, упрощение 0,6 лечит
        dst = os.path.join(d, 'c.glb')
        fp = FakePack(lambda s, si: 900_000 if si == 0.6 else 1_500_000)
        RM.pack = fp
        res = RM.build_light(src, dst, 1024, 82, 0.0, True, rule1)
        ok('упрощение 0,6 помогло: шаги 1024 → 512 → 512+si0.6', res['ok'] and [t['step'] for t in res['tried']] == ['1024', '512', '512+si0.6'], res['tried'])
        ok('  gltfpack звали в порядке 1024, 512, 512 с -si 0,6', [(c[0], c[1]) for c in fp.calls] == [(1024, 0.0), (512, 0.0), (512, 0.6)], fp.calls)

        # 3d. ничего не помогло → отказ, копии нет, прежняя не затёрта, рабочих файлов нет
        dst = os.path.join(d, 'e.glb')
        open(dst, 'wb').write(b'OLD')
        fp = FakePack(lambda s, si: 2_000_000)
        RM.pack = fp
        res = RM.build_light(src, dst, 1024, 82, 0.0, True, rule1)
        ok('лестница кончилась, всё тяжёлое: отказ по весу', not res['ok'] and res['kind'] == 'weight' and len(res['tried']) == 4, (res['kind'], res['tried']))
        ok('  прежняя копия не тронута', open(dst, 'rb').read() == b'OLD')
        ok('  рабочие файлы (.src*, .cand, .new) убраны даже при отказе', leftovers(d) == [], leftovers(d))
        e = RM.weight_entry(res, rule1, 'abcd', src)
        ok('  запись манифеста: refused, причина из правила, шаги с весом, sha и отпечаток правила',
           e['status'] == 'refused' and e['reason'] == 'rt_weight_over_limit' and len(e['steps']) == 4 and e['sha'] == 'abcd' and e['rule'] == rule1['fingerprint'] and len(e['glb_sha']) == 16, e)
        ok('  отказ действителен только для того же исходника и правила', RM.refused_here({'rt_weight': e}, '', 'abcd', rule1)
           and not RM.refused_here({'rt_weight': e}, '', 'zzzz', rule1) and not RM.refused_here({'rt_weight': e}, '-lite', 'abcd', rule1)
           and not RM.refused_here({'rt_weight': e}, '', 'abcd', {**rule1, 'fingerprint': 'другое'}))

        # 3e. мало граней: упрощение ниже min_triangles не делаем (силуэт не едим) — отказ без упрощения
        small = source_glb(tri=50_000)                  # 50 000 × 0,6 = 30 000 < 40 000
        fp = FakePack(lambda s, si: 2_000_000)
        RM.pack = fp
        res = RM.build_light(small, os.path.join(d, 'f.glb'), 1024, 82, 0.0, True, rule1)
        ok('50 тыс. граней: упрощение 0,6 дало бы <40 тыс. — не делаем, отказ после 1024 и 512', not res['ok'] and [t['step'] for t in res['tried'] if t.get('bytes')] == ['1024', '512']
           and any('skip' in t for t in res['tried']) and all(c[1] == 0.0 for c in fp.calls), (res['tried'], fp.calls))
        ok('  рабочих файлов нет', leftovers(d) == [], leftovers(d))

        # 3f. битая текстура — это не вес: отказ сразу, лестница не гоняется
        def broken(src_, dst_, simplify=0.0, ktx2=True):
            open(dst_, 'wb').write(RM.write_glb({'asset': {'version': '2.0'}, 'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}], 'textures': [{'source': 0}],
                                                  'images': [{'uri': 'data:image/png;base64,ERR/'}]}, b''))
            return True, ''
        RM.pack = broken
        bad_src = RM.write_glb({'asset': {'version': '2.0'}, 'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}], 'textures': [{'source': 0}],
                                'images': [{'uri': 'data:image/png;base64,ERR/'}]}, b'')
        RM.optimise = lambda data, size, quality, drop_mr=True: (bad_src, {'images_out': 1, 'px': size, 'triangles': 300_000})    # исходник сам с битой картинкой
        res = RM.build_light(src, os.path.join(d, 'g.glb'), 1024, 82, 0.0, True, rule1)
        RM.optimise = real_opt
        ok('битая текстура (и упаковка, и исходник): kind=texture, лестница не пошла дальше первого шага', res['kind'] == 'texture' and len(res['tried']) == 1 and bool(res['probs']), (res['kind'], res['tried']))
        ok('  рабочих файлов нет', leftovers(d) == [], leftovers(d))
        # 3g. ошибка внутри (gltfpack упал исключением) — рабочие файлы всё равно убраны

        def boom(src_, dst_, simplify=0.0, ktx2=True):
            open(dst_, 'wb').write(b'half')
            raise RuntimeError('упал')
        RM.pack = boom
        try:
            RM.build_light(src, os.path.join(d, 'h.glb'), 1024, 82, 0.0, True, rule1)
            ok('исключение пробрасывается', False)
        except RuntimeError:
            ok('исключение пробрасывается (не молчим)', True)
        ok('  рабочие файлы убраны и при исключении', leftovers(d) == [], leftovers(d))
    finally:
        RM.pack, RM.optimise = real_pack, real_opt

    # ——— 4. main: отказ в манифесте, ворота, WARN, без повторной лестницы, поменял правило — поведение другое ———
    out_d = os.path.join(d, 'rt')
    man_p = os.path.join(d, 'runtime-meshes.json')
    real_fetch = RM.fetch_source
    RM.fetch_source = lambda mid: src
    os.environ['RT_WEIGHT_RULES'] = r1

    def run(args, pack):
        RM.pack = pack
        sys_argv = sys.argv
        sys.argv = ['runtime_mesh.py'] + args
        buf, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                rc = RM.main()
        finally:
            sys.argv = sys_argv
            RM.pack = real_pack
        return rc, buf.getvalue(), err.getvalue()
    demo_p = os.path.join(d, 'demo-data.json')           # модель — вариант комнаты витрины (ворота --check смотрят только варианты)
    json.dump({'variants': [{'room_id': 'living', 'items': [{'role': 'комод', 'sku': {'msid': '111_222'}}]}], 'feeds': {}}, open(demo_p, 'w'))
    common = ['--id', '111_222', '--out', out_d, '--manifest', man_p, '--size', '1024', '--no-ktx2']
    gate = ['--ids-from-demo', demo_p, '--out', out_d, '--manifest', man_p, '--size', '1024', '--no-ktx2', '--check']
    try:
        fp = FakePack(lambda s, si: 2_000_000)
        rc, out, err = run(common, fp)
        man = json.load(open(man_p))['meshes']['111_222']
        ok('main: подложенная тяжёлая — код 1, отказ по весу в манифесте с причиной', rc == 1 and man['rt_weight']['status'] == 'refused' and man['rt_weight']['reason'] == 'rt_weight_over_limit', (rc, man))
        ok('  копии нет на диске и в таблице (size/src_sha убраны)', not os.path.exists(os.path.join(out_d, '111_222.glb')) and 'size' not in man and 'src_sha' not in man, man)
        ok('  WARN:rt_weight в сводке (последние строки), с числом и порогом', 'WARN:rt_weight:' in out, out[-300:])
        ok('  в stderr — «ОТКАЗ … rt_weight_over_limit» с шагами', 'ОТКАЗ' in err and 'rt_weight_over_limit' in err and '1024=' in err, err[-300:])
        ok('  рабочих файлов в папке нет', leftovers(out_d) == [], leftovers(out_d))
        n_calls = len(fp.calls)
        fp2 = FakePack(lambda s, si: 2_000_000)
        rc, out, err = run(common, fp2)
        ok('  повторный прогон того же исходника и правила: лестница заново не гоняется, отказ остаётся', fp2.calls == [] and rc == 1 and n_calls == 4, (fp2.calls, n_calls))
        rc, out, err = run(gate, FakePack(lambda s, si: 0))
        ok('  ворота --check: у отказанной модели варианта нет свежей копии → код 1', rc == 1 and 'вариант: 111_222' in out, out)
        rc, out, err = run(['--check-weight', '--manifest', man_p], FakePack(lambda s, si: 0))
        ok('  --check-weight: отказ по весу в таблице → код 1 и WARN:rt_weight', rc == 1 and 'WARN:rt_weight' in out, out)

        # правка ДАННЫХ — поведение другое, без правки кода: порог выше (3 МБ) — та же модель собирается
        r2 = write_rule(d, 'r2.json', 3_000_000)
        os.environ['RT_WEIGHT_RULES'] = r2
        fp3 = FakePack(lambda s, si: 2_000_000)
        rc, out, err = run(common, fp3)
        man = json.load(open(man_p))['meshes']['111_222']
        ok('поправили порог в правиле (1 → 3 МБ): та же модель собрана с первого шага, отказ снят', rc == 0 and man.get('size') and 'rt_weight' not in man and os.path.exists(os.path.join(out_d, '111_222.glb')), (rc, man, err[-200:]))
        rc, out, err = run(gate, FakePack(lambda s, si: 0))
        ok('  ворота --check теперь пускают (копия цела, ≤ порога)', rc == 0, out)
        # ужесточили порог ниже веса готовой копии — копия несвежая (собрать по лестнице), старый sha не спасает
        r3 = write_rule(d, 'r3.json', 1_000_000)
        os.environ['RT_WEIGHT_RULES'] = r3
        rc, out, err = run(gate, FakePack(lambda s, si: 0))
        ok('ужесточили порог ниже веса готовой копии: --check видит её несвежей (код 1)', rc == 1, (rc, out))
        rc, out, err = run(['--check-weight', '--manifest', man_p], FakePack(lambda s, si: 0))
        ok('  --check-weight: копия тяжелее нового порога → WARN:rt_weight, код 1', rc == 1 and 'WARN:rt_weight' in out, out)
        fp4 = FakePack(lambda s, si: 900_000 if s == 512 else 2_000_000)
        rc, out, err = run(common, fp4)
        man = json.load(open(man_p))['meshes']['111_222']
        ok('  пересборка по лестнице: ушла на 512, шаги записаны в манифест (rt_weight ok)', rc == 0 and man['rt_weight']['status'] == 'ok' and [s[0] for s in man['rt_weight']['steps']] == ['1024', '512'], (rc, man))
        ok('  сводка: «WARN:rt_weight_ladder» — собрана облегчённо', 'WARN:rt_weight_ladder' in out, out[-300:])
        ok('  рабочих файлов нет', leftovers(out_d) == [], leftovers(out_d))

        # publish_rt.sh читает порог из того же правила: папка с тяжёлым файлом — отказ ДО rsync
        heavy_dir = os.path.join(d, 'pub')
        os.makedirs(heavy_dir)
        open(os.path.join(heavy_dir, '1.glb'), 'wb').write(b'\0' * 1_200_000)
        env = {**os.environ, 'PY': sys.executable}
        pr = subprocess.run(['bash', os.path.join(HERE, '..', 'publish_rt.sh'), heavy_dir], env=env, capture_output=True, text=True, timeout=60)
        ok('publish_rt.sh: файл тяжелее порога (1,2 МБ при пороге 1 МБ) — отказ до rsync, код 1, WARN:rt_weight', pr.returncode == 1 and 'WARN:rt_weight' in pr.stdout and 'тяжелее порога' in pr.stdout, (pr.returncode, pr.stdout[-300:], pr.stderr[-200:]))
        ok('  rsync не запускался (в выводе нет «выкладываю»)', 'выкладываю' not in pr.stdout, pr.stdout)
        pr = subprocess.run([sys.executable, os.path.join(HERE, '..', 'runtime_mesh.py'), '--heavy-in', heavy_dir], env=env, capture_output=True, text=True, timeout=60)
        ok('--heavy-in: тот же отказ и список файлов', pr.returncode == 1 and '1.glb' in pr.stdout, pr.stdout)
        os.environ['RT_WEIGHT_RULES'] = r2                                       # порог 3 МБ — тот же файл проходит
        pr = subprocess.run([sys.executable, os.path.join(HERE, '..', 'runtime_mesh.py'), '--heavy-in', heavy_dir], env={**os.environ}, capture_output=True, text=True, timeout=60)
        ok('--heavy-in при пороге 3 МБ: файл 1,2 МБ проходит (правка данных, не кода)', pr.returncode == 0, pr.stdout)
    finally:
        RM.fetch_source = real_fetch
        os.environ.pop('RT_WEIGHT_RULES', None)
        RM.pack = real_pack

if FAILS:
    print(f'\n{len(FAILS)} провал(ов)')
    sys.exit(1)
print('\nвсе проверки прошли')
