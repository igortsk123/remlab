#!/usr/bin/env python3
"""ТЕНЬ «ГАЛЕРЕЯ ПО ПРИВЯЗКЕ» (хвост В-1б, T-20261105-50) — только чтение: какой GLB гостиная публикует сегодня и какой
дала бы привязка товар→меш. Поведение `salad/gallery_build.py` не меняется.

ЗАЧЕМ. `gallery_build.py` берёт на SKU папку поколения с САМЫМ СВЕЖИМ `manifest.json` (по mtime), привязка
(`offer_asset_binding`, T-45) — текущую попытку ревизии ТЕКУЩЕГО фото (`asset_revisions.current_generation_key`). Под одним
ключом каталога мешей (`mid_eid`) на проде может лежать не тот файл, что считает годным привязка (находка T-47: 5177 —
галерея выложила поколение ba602495, привязка указывает 3c40e6c7). Прежде чем переключать гостиную, нужен счёт: сколько
расхождений, какие видны на демо, чем отличаются.

ПРАВИЛО ГАЛЕРЕИ ПОВТОРЕНО, А НЕ ИМПОРТИРОВАНО: `gallery_build` при импорте удаляет `orient.json` из папки публикации
(побочный эффект модуля). Повтор (`mtime_pick`) сверяется с фактом — sha файла в `~/scout-scenes/mesh-pilot-gallery/<key>/`
(строка «повтор правила совпал с галереей» в отчёте).

Классы расхождений (`classify`):
  no_binding_file — у привязки нет файла (нет ревизии текущего фото / файл не цел) — галерея показывает то, что есть;
  newer_reseed    — галерея взяла более свежий перегон того же фото, а текущая попытка ревизии — другое поколение;
  old_photo       — галерея взяла поколение по СТАРОМУ фото (фото товара сменилось, ревизия нового — другая);
  older_pick      — галерея взяла поколение старше привязанного (у свежего брак владельца / нет model.glb / нет манифеста);
  unregistered    — папка галереи не записана в `mesh_generations`;
  other           — прочее (в таблице оба ключа).
Плюс статус разворота каждого из двух файлов (`orientation_state`, ключ `sku|sha16|orient-v1` — разворот решается по файлу).

  ~/venvs/scout/bin/python gallery_binding_shadow.py --out DIR [--skus FILE|all] [--sheet N]   # all — вся галерея
  python3 gallery_binding_shadow.py --selftest
"""
import glob
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'salad'))

SRC = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
GALLERY = os.path.expanduser('~/scout-scenes/mesh-pilot-gallery')
DEMO = os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
MAIN_SCOUT = '/home/pakar/igor/remlab/tools/scout'          # список и живой банк ночного крона — в основной копии
SKUS_DEFAULT = os.path.join(MAIN_SCOUT, '.mesh-publish-only.txt')
SETS_DEFAULT = os.path.join(MAIN_SCOUT, 'sets3.json')


# ---------------------------------------------------------------- правило галереи (повтор gallery_build.build)
def mtime_pick(dirs: list) -> dict | None:
    """dirs — [{dir, manifest_mtime|None, has_glb, owner_reject, role_mesh}] папок поколений ОДНОГО SKU → выбранная
    `gallery_build`: самый свежий manifest.json, без owner_reject.json, роль — меш, с model.glb (папка без model.glb SKU
    не занимает — галерея идёт к следующей)."""
    ok = [d for d in dirs if d.get('manifest_mtime') is not None and not d.get('owner_reject') and d.get('role_mesh')
          and d.get('has_glb')]
    return max(ok, key=lambda d: (d['manifest_mtime'], d['dir'])) if ok else None


def scan(sku_key: str, src: str = SRC) -> list:
    import asset_strategy as AS
    out = []
    for d in sorted(glob.glob(os.path.join(src, sku_key, '*', ''))):
        man_p = os.path.join(d, 'manifest.json')
        mt = os.path.getmtime(man_p) if os.path.exists(man_p) else None
        role = None
        if mt is not None:
            try:
                role = json.load(open(man_p, encoding='utf-8')).get('role')
            except Exception:  # noqa: BLE001
                mt = None
        out.append({'dir': d.rstrip('/'), 'manifest_mtime': mt, 'has_glb': os.path.exists(os.path.join(d, 'model.glb')),
                    'owner_reject': os.path.exists(os.path.join(d, 'owner_reject.json')),
                    'role_mesh': AS.strategy(role) == 'hunyuan3d' if role else False, 'role': role})
    return out


# ---------------------------------------------------------------- классы
def classify(gal: dict | None, bind: dict | None, gens: dict) -> tuple:
    """(same|класс, пояснение). gal — {dir, sha}; bind — строка привязки (local_path, asset_id, generation_key, source_sha,
    status, reasons); gens — dir → {generation_key, source_sha, generated_at, owner_verdict}."""
    if gal is None:
        return 'no_gallery', 'галерея этот SKU не публикует (нет годной папки)'
    if bind is None or not bind.get('local_path') or not bind.get('asset_id'):
        why = ', '.join((bind or {}).get('reasons') or []) or 'строки привязки нет'
        return 'no_binding_file', f'у привязки нет файла: {why[:120]}'
    bdir = os.path.dirname(bind['local_path'])
    if os.path.normpath(bdir) == os.path.normpath(gal['dir']) or bind['asset_id'] == f"sha256:{gal.get('sha')}":
        return 'same', ''
    g, b = gens.get(os.path.normpath(gal['dir'])), gens.get(os.path.normpath(bdir))
    if g is None:
        return 'unregistered', 'папки галереи нет в mesh_generations'
    if b is None:
        return 'other', 'папки привязки нет в mesh_generations'
    if g['source_sha'] != (bind.get('source_sha') or b['source_sha']):
        return 'old_photo', f"галерея: фото {g['source_sha'][:8]}, привязка (текущее фото): {(bind.get('source_sha') or b['source_sha'])[:8]}"
    if (g.get('generated_at') or '') > (b.get('generated_at') or ''):
        return 'newer_reseed', f"то же фото; галерея — перегон {g['generated_at'][:16]}, текущая попытка ревизии — {b['generated_at'][:16]}"
    if (g.get('generated_at') or '') < (b.get('generated_at') or ''):
        return 'older_pick', f"галерея — старше ({g['generated_at'][:16]} < {b['generated_at'][:16]}): у свежего mtime манифеста старее"
    return 'other', 'то же фото и время, разные папки'


def file_sha(p: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            for ch in iter(lambda: f.read(1 << 20), b''):
                h.update(ch)
        return h.hexdigest()
    except OSError:
        return None


# ---------------------------------------------------------------- данные
def demo_sets(demo_path: str, sets_path: str, fetch) -> tuple:
    """(видно на демо {msid}, лента {msid}, банк гостиной {msid}). msid банка — через представителя (как ready_skus)."""
    shown, feed = set(), set()
    try:
        d = json.load(open(demo_path, encoding='utf-8'))
        shown = {(i.get('sku') or {}).get('msid') for v in d.get('variants') or [] for i in v.get('items') or []} - {None}
        feed = {p['msid'] for lst in (d.get('feeds') or {}).values() for p in lst if p.get('msid')}
    except Exception as e:  # noqa: BLE001
        print(f'WARN: демо не прочитано ({str(e)[:80]})', flush=True)
    bank = set()
    try:
        skus = sorted({f"{it['mid']}:{it['eid']}" for s in json.load(open(sets_path, encoding='utf-8'))
                       for _r, it in (s.get('items') or {}).items() if it and it.get('mid')})
        arr = ','.join("'" + s.replace("'", "''") + "'" for s in skus)
        rep = {r[0]: r[1] for r in fetch(f"""select shop_mid||':'||external_id, coalesce(mesh_family_rep, shop_mid||':'||external_id)
            from products where shop_mid||':'||external_id = any(array[{arr}]::text[])""")}
        bank = {rep.get(s, s).replace(':', '_') for s in skus}
    except Exception as e:  # noqa: BLE001
        print(f'WARN: банк гостиной не прочитан ({str(e)[:80]})', flush=True)
    return shown, feed, bank


def generations(fetch) -> dict:
    return {os.path.normpath(r[0]): {'generation_key': r[1], 'source_sha': r[2], 'generated_at': r[3] or '',
                                     'owner_verdict': r[4], 'glb_sha': r[5]}
            for r in fetch("select path, generation_key, source_sha, generated_at::text, owner_verdict, glb_sha from mesh_generations")}


def run(skus_file: str, sets_path: str, demo_path: str) -> dict:
    import catalog_items as CI
    import room_bindings as RB
    if skus_file == 'all':      # вся локальная галерея: что лежит на проде под ключами (лента замен — из прошлых выкладок)
        keys = sorted(k for k in os.listdir(GALLERY) if os.path.exists(os.path.join(GALLERY, k, 'model.glb')))
    else:
        keys = sorted({l.strip().replace(':', '_', 1) for l in open(skus_file, encoding='utf-8') if l.strip()})
    rows, why = RB.load_db(CI.fetch)
    if rows is None:
        raise SystemExit(f'привязка не читается ({why})')
    gens = generations(CI.fetch)
    orient = {(r[0], r[1]): r[2] for r in CI.fetch("select sku, split_part(revision_key,'|',2), status from orientation_state "
                                                    "where split_part(revision_key,'|',2) <> ''")}
    shown, feed, bank = demo_sets(demo_path, sets_path, CI.fetch)
    out, agree, checked = [], 0, 0
    for k in keys:
        pick = mtime_pick(scan(k))
        gal = None
        if pick:
            gal = {'dir': pick['dir'], 'sha': file_sha(os.path.join(pick['dir'], 'model.glb')), 'role': pick.get('role')}
            gfile = os.path.join(GALLERY, k, 'model.glb')
            if os.path.exists(gfile):                     # повтор правила против факта галереи
                checked += 1
                agree += file_sha(gfile) == gal['sha']
        offer = k.replace('_', ':', 1)
        b = rows.get(offer)
        cls, note = classify(gal, b, gens)
        bdir = os.path.dirname(b['local_path']) if b and b.get('local_path') else None
        o = (b or {}).get('orientation') or {}
        bsha = ((b or {}).get('asset_id') or '').replace('sha256:', '') or None
        out.append({'key': k, 'role': (gal or {}).get('role') or ((b or {}).get('passport') or {}).get('role'),
                    'class': cls, 'note': note, 'status': (b or {}).get('status'), 'reasons': (b or {}).get('reasons') or [],
                    'gal_dir': (gal or {}).get('dir'), 'gal_gen': (gens.get(os.path.normpath(gal['dir'])) or {}).get('generation_key') if gal else None,
                    'gal_sha': (gal or {}).get('sha'), 'bind_dir': bdir, 'bind_gen': (b or {}).get('generation_key'),
                    'bind_sha': bsha,
                    'orient_gal': orient.get((offer, (gal or {}).get('sha', '')[:16] if gal and gal.get('sha') else '')) or 'нет',
                    'orient_bind': orient.get((offer, bsha[:16])) if bsha else None, 'yaw': o.get('yaw_deg'),
                    'shown': k in shown, 'feed': k in feed, 'bank': k in bank})
    return {'rows': out, 'agree': agree, 'checked': checked, 'keys': len(keys), 'skus_file': skus_file,
            'snapshot': next(iter({r['snapshot_id'][:16] for r in rows.values()}), None)}


def gen_short(g: str | None) -> str:
    """generation_key `sku|фото16|конвейер|seed|glb8` → `фото8 · seed N · glb8` (артикул в подписи лишний)."""
    p = (g or '').split('|')
    return f'фото {p[1][:8]} · seed {p[3]} · glb {p[4][:8]}' if len(p) >= 5 else (g or '—')


def where(r: dict) -> str:
    return 'демо (предмет варианта)' if r['shown'] else ('банк гостиной' if r['bank'] else ('только лента замен' if r['feed'] else 'не на демо'))


def summary(R: dict) -> dict:
    diff = [r for r in R['rows'] if r['class'] not in ('same', 'no_gallery')]
    by = {}
    for r in diff:
        by.setdefault(r['class'], {}).setdefault(where(r), 0)
        by[r['class']][where(r)] += 1
    return {'keys': R['keys'], 'same': sum(r['class'] == 'same' for r in R['rows']),
            'no_gallery': sum(r['class'] == 'no_gallery' for r in R['rows']), 'diff': len(diff),
            'visible_demo': sum(r['shown'] or r['bank'] for r in diff), 'feed_only': sum(r['feed'] and not (r['shown'] or r['bank']) for r in diff),
            'not_on_demo': sum(not (r['shown'] or r['bank'] or r['feed']) for r in diff),
            'by_class': by, 'replica_agree': f"{R['agree']}/{R['checked']}", 'binding_snapshot': R['snapshot']}


def report_md(R: dict, S: dict) -> str:
    L = ["# Галерея по привязке — тень (T-20261105-50)", '',
         f"Список гостиной: `{R['skus_file']}` — {S['keys']} ключей. Привязка {S['binding_snapshot']}. "
         f"Повтор правила галереи совпал с фактом галереи: {S['replica_agree']}.",
         f"Совпадает: {S['same']}; галерея не публикует: {S['no_gallery']}; **расхождений: {S['diff']}** — видно на демо (вариант "
         f"или банк гостиной): {S['visible_demo']}, только лента замен: {S['feed_only']}, не на демо: {S['not_on_demo']}.", '',
         '| класс | где | штук |', '|---|---|---|']
    for c, d in sorted(S['by_class'].items()):
        for w, n in sorted(d.items()):
            L.append(f'| {c} | {w} | {n} |')
    L += ['', '| ключ | роль | класс | где | привязка | галерея: поколение / sha | привязка: поколение / sha | разворот: галерея / привязка | пояснение |',
          '|---|---|---|---|---|---|---|---|---|']
    for r in sorted((r for r in R['rows'] if r['class'] not in ('same', 'no_gallery')), key=lambda r: (not r['shown'], not r['bank'], r['class'], r['key'])):
        L.append(f"| {r['key']} | {r['role']} | {r['class']} | {where(r)} | {r['status']} | {gen_short(r['gal_gen'])} / {(r['gal_sha'] or '—')[:12]} | "
                 f"{gen_short(r['bind_gen'])} / {(r['bind_sha'] or '—')[:12]} | {r['orient_gal']} / {r['orient_bind'] or 'нет'} | {r['note']} |")
    return '\n'.join(L) + '\n'


# ---------------------------------------------------------------- лист «сейчас | по привязке»
def sheet(R: dict, out_png: str, n: int = 8) -> list:
    """6–8 расхождений из демо/банка: фото товара | GLB галереи | GLB привязки (одна камера: 3/4 сверху, yaw 30, pitch 20)."""
    import mesh_render as MR
    from PIL import Image, ImageDraw, ImageFont
    cand = [r for r in R['rows'] if r['class'] not in ('same', 'no_gallery', 'no_binding_file') and (r['shown'] or r['bank'])
            and r['gal_dir'] and r['bind_dir']]
    seen, pick = {}, []
    for r in sorted(cand, key=lambda r: (not r['shown'], r['class'], r['key'])):     # разнообразие классов
        if seen.get(r['class'], 0) < max(2, n // 3) and len(pick) < n:
            pick.append(r)
            seen[r['class']] = seen.get(r['class'], 0) + 1
    for r in cand:
        if len(pick) >= n:
            break
        if r not in pick:
            pick.append(r)
    W, H, CAP = 300, 300, 46
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 13)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    canvas = Image.new('RGB', (W * 3, (H + CAP) * max(1, len(pick)) + 30), 'white')
    dr = ImageDraw.Draw(canvas)
    dr.text((8, 8), 'фото товара  |  СЕЙЧАС (галерея, свежий манифест)  |  ПО ПРИВЯЗКЕ (текущая ревизия фото)', fill='black', font=font)

    def fit(img):
        img = img.convert('RGBA')
        img.thumbnail((W - 10, H - 10))
        bg = Image.new('RGBA', (W, H), (244, 244, 242, 255))
        bg.alpha_composite(img, ((W - img.width) // 2, (H - img.height) // 2))
        return bg.convert('RGB')

    def render(d):
        try:
            return fit(MR.render(MR.load_parts(os.path.join(d, 'model.glb')), yaw_deg=30.0, pitch_deg=20.0, size=(600, 600)))
        except Exception as e:  # noqa: BLE001
            im = Image.new('RGB', (W, H), (250, 230, 230))
            ImageDraw.Draw(im).text((10, 10), f'не отрисовалось: {str(e)[:40]}', fill='black', font=font)
            return im
    for i, r in enumerate(pick):
        y = 30 + i * (H + CAP)
        ph = next((os.path.join(d, f) for d in (r['bind_dir'], r['gal_dir']) for f in ('input.png', 'cutout.png')
                   if os.path.exists(os.path.join(d, f))), None)
        canvas.paste(fit(Image.open(ph)) if ph else Image.new('RGB', (W, H), (235, 235, 235)), (0, y))
        canvas.paste(render(r['gal_dir']), (W, y))
        canvas.paste(render(r['bind_dir']), (2 * W, y))
        dr.text((8, y + H + 4), f"{r['key']} · {r['role']} · {r['class']} · {where(r)} · привязка {r['status']}", fill='black', font=font)
        dr.text((8, y + H + 22), f"сейчас {gen_short(r['gal_gen'])}  →  по привязке {gen_short(r['bind_gen'])}",
                fill=(90, 90, 90), font=font)
    canvas.save(out_png)
    return [r['key'] for r in pick]


# ---------------------------------------------------------------- селфтест
def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    D = lambda d, mt, **kw: dict({'dir': d, 'manifest_mtime': mt, 'has_glb': True, 'owner_reject': False, 'role_mesh': True}, **kw)  # noqa: E731
    ok('галерея: самый свежий манифест', mtime_pick([D('a', 1), D('b', 3), D('c', 2)])['dir'] == 'b')
    ok('свежий без model.glb / с браком владельца / без манифеста — пропуск к следующему',
       mtime_pick([D('a', 1), D('b', 3, has_glb=False), D('c', 4, owner_reject=True), D('d', None)])['dir'] == 'a')
    ok('роль не меш — не публикуется', mtime_pick([D('a', 1, role_mesh=False)]) is None)
    gens = {'/g/old': {'generation_key': 'G0', 'source_sha': 'p0', 'generated_at': '2026-09-01'},
            '/g/cur': {'generation_key': 'G1', 'source_sha': 'p1', 'generated_at': '2026-10-01'},
            '/g/re': {'generation_key': 'G2', 'source_sha': 'p1', 'generated_at': '2026-10-02'}}
    B = lambda d='/g/cur', **kw: dict({'local_path': d + '/model.glb', 'asset_id': 'sha256:bb', 'source_sha': 'p1',  # noqa: E731
                                       'status': 'ready', 'reasons': []}, **kw)
    ok('та же папка — same', classify({'dir': '/g/cur', 'sha': 'x'}, B(), gens)[0] == 'same')
    ok('тот же sha в другой папке — same', classify({'dir': '/g/re', 'sha': 'bb'}, B(), gens)[0] == 'same')
    ok('галерея — перегон того же фото новее текущей попытки — newer_reseed',
       classify({'dir': '/g/re', 'sha': 'x'}, B(), gens)[0] == 'newer_reseed')
    ok('галерея — по старому фото — old_photo', classify({'dir': '/g/old', 'sha': 'x'}, B(), gens)[0] == 'old_photo')
    ok('галерея старше привязанной (то же фото) — older_pick',
       classify({'dir': '/g/cur', 'sha': 'x'}, B('/g/re'), gens)[0] == 'older_pick')
    ok('нет файла у привязки — no_binding_file с причиной',
       classify({'dir': '/g/cur', 'sha': 'x'}, B(local_path=None, asset_id=None, reasons=['no_revision']), gens)
       == ('no_binding_file', 'у привязки нет файла: no_revision'))
    ok('папки галереи нет в реестре — unregistered', classify({'dir': '/g/zzz', 'sha': 'x'}, B(), gens)[0] == 'unregistered')
    ok('галерея не публикует — no_gallery', classify(None, B(), gens)[0] == 'no_gallery')
    R = {'rows': [dict(key='k1', shown=True, bank=False, feed=True, **{'class': 'old_photo'}),
                  dict(key='k2', shown=False, bank=True, feed=False, **{'class': 'newer_reseed'}),
                  dict(key='k3', shown=False, bank=False, feed=True, **{'class': 'newer_reseed'}),
                  dict(key='k4', shown=False, bank=False, feed=False, **{'class': 'same'})],
         'keys': 4, 'agree': 1, 'checked': 1, 'snapshot': 's'}
    S = summary(R)
    ok('подпись поколения без артикула', gen_short('112923:1|9e924685cbb35c05|v1|0|f74d7c2f') == 'фото 9e924685 · seed 0 · glb f74d7c2f')
    ok('счёт: видно на демо (вариант или банк) 2, только лента 1', S['diff'] == 3 and S['visible_demo'] == 2 and S['feed_only'] == 1)
    print(f'итог: {"OK" if not bad else f"FAIL {bad}"}')
    return 1 if bad else 0


def main(a: list) -> int:
    if '--selftest' in a:
        return _selftest()
    arg = lambda k, d=None: a[a.index(k) + 1] if k in a else d  # noqa: E731
    out = arg('--out')
    if not out:
        print(__doc__)
        return 64
    os.makedirs(out, exist_ok=True)
    R = run(arg('--skus', SKUS_DEFAULT), arg('--sets', SETS_DEFAULT), arg('--demo', DEMO))
    S = summary(R)
    json.dump({'summary': S, 'rows': R['rows']}, open(os.path.join(out, 'gallery-binding-shadow.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    open(os.path.join(out, 'gallery-binding-shadow.md'), 'w', encoding='utf-8').write(report_md(R, S))
    n = int(arg('--sheet', 8))
    keys = sheet(R, os.path.join(out, 'sheet-now-vs-binding.png'), n) if n else []
    print(json.dumps(S, ensure_ascii=False, indent=1))
    print(f'лист: {len(keys)} — {", ".join(keys)}; отчёт {out}/gallery-binding-shadow.md', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
