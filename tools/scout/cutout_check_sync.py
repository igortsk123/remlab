#!/usr/bin/env python3
"""Страница проверки вырезок /lab/cutout-check (T-20261119-104): DEV → сервер и обратно, по образцу `mesh_audit_sync.py`.

Вход — папка прогона `cutout_redo.py` (`products.json`, `photos/<sha>.img`, `cut/<sha>.png`, `chain.jsonl`). Что делает:
  site     веб-копии для страницы: `<run>/site/<sku>/photo.webp` (фото магазина) и `cut.webp` (вырезка с прозрачностью), ≤ 1000 px по длинной
           стороне; в карточку попадает только товар с готовой вырезкой (`status: ok` в chain.jsonl). generation_key = sha256 файла вырезки
           (новая вырезка → другой ключ → отметка и текст карточки сбрасываются, журнал остаётся).
  publish  rsync `site/` на сервер в `/opt/remlab/test/cutout-check/<run>/` (раздаётся как `/test/cutout-check/<run>/…`).
  push     карточки на страницу: POST /api/lab/cutout-check/items пачками по 200 (Bearer конвейера); порядок = роль, имя.
  export   отметки владельца списком → `<run>/owner-marks-<метка>.json` + печать «не ок» с текстом (вход для перегона цепочки).
  all      site → publish → push.
Секреты: MESH_REVIEW_MACHINE_TOKEN / MESH_REVIEW_URL из окружения или ~/.config/remlab/env (значения не читаем и не печатаем).

  ~/venvs/scout/bin/python cutout_check_sync.py all --run 1119-a
  ~/venvs/scout/bin/python cutout_check_sync.py export --run 1119-a
  ~/venvs/scout/bin/python cutout_check_sync.py --selftest
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.expanduser('~/remlab-logs/t104-1119')
REMOTE = 'root@89.167.127.0:/opt/remlab/test/cutout-check'
SSH = 'ssh -p 22222 -o BatchMode=yes -o ConnectTimeout=20'
MAX_SIDE = 1000
BATCH = 200


def say(*a) -> None:
    print(time.strftime('%H:%M:%S', time.gmtime()), *a, flush=True)


def _env() -> tuple[str, str]:
    cfg = os.path.expanduser('~/.config/remlab/env')
    if os.path.exists(cfg):
        for ln in open(cfg):
            if '=' in ln and not ln.strip().startswith('#'):
                k, v = ln.strip().split('=', 1)
                os.environ.setdefault(k, v)
    tok = os.environ.get('MESH_REVIEW_MACHINE_TOKEN', '')
    if not tok:
        raise SystemExit('нет MESH_REVIEW_MACHINE_TOKEN (см. _secrets/ACCESS.md)')
    return os.environ.get('MESH_REVIEW_URL', 'https://remont-lab.online').rstrip('/'), tok


def api(method: str, path: str, body: dict | None = None) -> dict:
    url, tok = _env()
    req = urllib.request.Request(url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def jl_read(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    for ln in open(path, encoding='utf-8'):
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass  # оборванная строка — пропускаем, остальные читаем
    return out


def sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''):
            h.update(ch)
    return h.hexdigest()


def sku_dir(sku: str) -> str:
    return sku.replace(':', '_').replace('/', '_')  # как sid в /demo


def ready_rows(d: str) -> list[tuple[dict, dict]]:
    """Товары с готовой вырезкой: (строка products.json, последняя ok-запись chain.jsonl). Порядок на странице — роль, имя."""
    rows = {r['sku']: r for r in json.load(open(os.path.join(d, 'products.json'), encoding='utf-8'))}
    last: dict[str, dict] = {}
    for rec in jl_read(os.path.join(d, 'chain.jsonl')):
        last[rec['sku']] = rec  # поздняя запись по товару главнее ранней
    pairs = [(rows[s], c) for s, c in last.items() if c.get('status') == 'ok' and s in rows and os.path.exists(os.path.join(d, 'cut', c['sha'] + '.png'))]
    pairs.sort(key=lambda p: (not p[0].get('role'), p[0].get('role') or '', p[0].get('name') or '', p[0]['sku']))
    return pairs


def build_items(d: str, run: str) -> list[dict]:
    items = []
    for pos, (r, c) in enumerate(ready_rows(d)):
        sd = sku_dir(r['sku'])
        cut = os.path.join(d, 'site', sd, 'cut.webp')
        items.append({
            'sku': r['sku'], 'position': pos, 'role': r.get('role'), 'name': r.get('name'), 'nameEn': r.get('name_en'),
            'shop': r.get('shop'), 'shopUrl': r.get('shop_url'),
            'photoUrl': f'/test/cutout-check/{run}/{sd}/photo.webp', 'cutUrl': f'/test/cutout-check/{run}/{sd}/cut.webp',
            'generationKey': sha_file(cut)[:32] if os.path.exists(cut) else c['sha'][:32],
            'info': {'verdict': c.get('verdict'), 'reason': c.get('reason'), 'frameWh': c.get('frame_wh'), 'cutWh': c.get('cut_wh'), 'sha': c['sha'][:16]},
        })
    return items


def to_webp(src: str, dst: str, alpha: bool) -> None:
    from PIL import Image
    im = Image.open(src)
    im = im.convert('RGBA') if alpha else im.convert('RGB')
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    tmp = dst + '.part'
    im.save(tmp, 'WEBP', quality=92, method=4)
    os.replace(tmp, dst)


def cmd_site(d: str) -> int:
    pairs = ready_rows(d)
    done = fail = 0
    for r, c in pairs:
        out = os.path.join(d, 'site', sku_dir(r['sku']))
        os.makedirs(out, exist_ok=True)
        try:
            to_webp(os.path.join(d, 'photos', c['sha'] + '.img'), os.path.join(out, 'photo.webp'), alpha=False)
            to_webp(os.path.join(d, 'cut', c['sha'] + '.png'), os.path.join(out, 'cut.webp'), alpha=True)
            done += 1
        except Exception as e:  # noqa: BLE001 — отказ считаем и пишем с причиной, карточка этого товара не уйдёт
            fail += 1
            say(f'  ✗ {r["sku"]}: {type(e).__name__}: {str(e)[:120]}')
    say(f'веб-копии: {done} из {len(pairs)}, отказов {fail} ({d}/site)')
    return 0 if not fail else 2


def cmd_publish(d: str, run: str) -> int:
    r = subprocess.run(['rsync', '-aq', '--mkpath', '-e', SSH, os.path.join(d, 'site') + '/', f'{REMOTE}/{run}/'], capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        say(f'rsync не удался: {r.stderr.strip()[-200:]}')
        return 2
    say(f'выложено на сервер: /test/cutout-check/{run}/')
    return 0


def cmd_push(d: str, run: str) -> int:
    items = build_items(d, run)
    if not items:
        say('нечего пушить: нет готовых вырезок (сначала chain и site)')
        return 2
    put = 0
    for i in range(0, len(items), BATCH):
        put += api('POST', '/api/lab/cutout-check/items', {'run': run, 'items': items[i:i + BATCH]}).get('put', 0)
    say(f'карточек на странице: {put} из {len(items)}')
    return 0 if put == len(items) else 2


def cmd_export(d: str, run: str) -> int:
    data = api('GET', f'/api/lab/cutout-check/export?run={run}')
    out = os.path.join(d, f'owner-marks-{time.strftime("%Y%m%d-%H%M%S")}.json')  # новый файл с меткой, старые не трогаем
    json.dump(data, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    say(f'прогон {data["run"]}: просмотрено {data.get("viewed", data["ok"] + data["bad"])} из {data["total"]} · не ок {data["bad"]} · журнал {data["journal"]} строк → {out}')
    for m in data['marks']:
        if m['mark'] == 'bad':
            print(f'  ✕ {m["sku"]} · {m.get("role") or "—"} · {m.get("name") or ""}' + (f' — {m["note"]}' if m.get('note') else ''))
    return 0


def _selftest() -> int:
    import remlab_tmp
    from PIL import Image
    remlab_tmp.use('cutout_check_sync-selftest')
    import tempfile
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    d = tempfile.mkdtemp(prefix='ccs-')
    for sub in ('photos', 'cut'):
        os.makedirs(os.path.join(d, sub))
    rows = [{'sku': '1:a', 'role': 'диван', 'name': 'Б'}, {'sku': '1:b', 'role': 'диван', 'name': 'А'}, {'sku': '2:c', 'role': None, 'name': 'Я'},
            {'sku': '3:d', 'role': 'комод', 'name': 'Д'}]
    json.dump(rows, open(os.path.join(d, 'products.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    recs = []
    for i, r in enumerate(rows[:3]):
        sha = f'{i:02d}' * 32
        Image.new('RGB', (40, 30), (200, 10, 10)).save(os.path.join(d, 'photos', sha + '.img'), 'PNG')
        Image.new('RGBA', (40, 30), (10, 200, 10, 128)).save(os.path.join(d, 'cut', sha + '.png'))
        recs.append({'sku': r['sku'], 'sha': sha, 'status': 'ok', 'verdict': 'ok'})
    recs.append({'sku': '3:d', 'sha': 'ff' * 32, 'status': 'fail', 'error': 'x'})              # отказ цепочки — карточки нет
    recs.insert(0, {'sku': '1:a', 'sha': '99' * 32, 'status': 'ok'})                           # ранняя запись, файла вырезки нет — не берём
    with open(os.path.join(d, 'chain.jsonl'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(json.dumps(x) for x in recs) + '\n{оборванная')
    pairs = ready_rows(d)
    ok('в карточки идут только товары с готовой вырезкой; оборванная строка журнала не роняет', [p[0]['sku'] for p in pairs] == ['1:b', '1:a', '2:c'])
    ok('порядок: роль, имя; без роли — в конец', [p[0]['sku'] for p in pairs][-1] == '2:c')
    ok('поздняя запись товара главнее ранней', pairs[1][1]['sha'] == '00' * 32)
    ok('sku в адресе: двоеточие → «_» (как sid в /demo)', sku_dir('112923:13224664101879413845') == '112923_13224664101879413845')
    ok('веб-копии без отказов', cmd_site(d) == 0 and os.path.exists(os.path.join(d, 'site', '1_a', 'cut.webp')))
    from PIL import Image as I
    w = I.open(os.path.join(d, 'site', '1_a', 'cut.webp'))
    ok('прозрачность вырезки в webp сохранена', w.mode == 'RGBA' and w.getpixel((5, 5))[3] < 255)
    items = build_items(d, 'r1')
    ok('карточка: адреса /test/cutout-check/<run>/<sku>/…, ключ вырезки 32 знака', items[0]['cutUrl'] == '/test/cutout-check/r1/1_b/cut.webp' and len(items[0]['generationKey']) == 32)
    ok('новая вырезка → другой ключ', (lambda a: (I.new('RGBA', (40, 30), (1, 2, 3, 255)).save(os.path.join(d, 'site', '1_b', 'cut.webp'), 'WEBP'), build_items(d, 'r1')[0]['generationKey'] != a)[1])(items[0]['generationKey']))
    print('ИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not bad else f'{bad} провалов')
    return 1 if bad else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['site', 'publish', 'push', 'export', 'all'])
    ap.add_argument('--run', required=True, help='метка прогона cutout_redo.py')
    a = ap.parse_args()
    d = os.path.join(ROOT, a.run)
    if not os.path.isdir(d):
        raise SystemExit(f'нет папки прогона {d}')
    steps = {'site': [lambda: cmd_site(d)], 'publish': [lambda: cmd_publish(d, a.run)], 'push': [lambda: cmd_push(d, a.run)],
             'export': [lambda: cmd_export(d, a.run)], 'all': [lambda: cmd_site(d), lambda: cmd_publish(d, a.run), lambda: cmd_push(d, a.run)]}[a.cmd]
    for s in steps:
        rc = s()
        if rc:
            return rc
    return 0


if __name__ == '__main__':
    sys.exit(main())
