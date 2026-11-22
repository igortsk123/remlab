#!/usr/bin/env python3
"""Локальный просмотр страницы /lab/cutout-check до выкладки (T-20261119-104): кладёт карточки прогона в локальный `next dev`
(не в прод!), копии картинок — в `public/test/cutout-check/<run>/`, снимает страницу Playwright: телефон 375×667 и компьютер 1280×900.

  ~/venvs/scout/bin/python tools/scout/cutout_check_preview.py --run 1119-a --skus 112923:13224664101879413845,114667:11634594969038554503 \
      --base http://127.0.0.1:3104 --out ~/remlab-logs/t104-1119/preview/shots-<метка>

Секреты тут свои, пробные (`preview-secret` / `preview-token`) — `next dev` запускается с ними; боевых значений не читаем.
"""
import argparse
import hashlib
import hmac
import json
import os
import shutil
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cutout_check_sync as S  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, '..', '..'))


def post(base: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(base + path, method='POST', data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer preview-token', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--skus', default='', help='через запятую; пусто — первые 3 готовые')
    ap.add_argument('--base', default='http://127.0.0.1:3104')
    ap.add_argument('--out', required=True)
    ap.add_argument('--label', default='prev', help='метка прогона на локальной странице')
    a = ap.parse_args()
    d = os.path.join(S.ROOT, a.run)
    S.cmd_site(d)
    items = S.build_items(d, a.label)
    want = [x for x in a.skus.split(',') if x]
    items = [i for i in items if i['sku'] in want] if want else items[:3]
    if not items:
        raise SystemExit('нет готовых карточек для просмотра')
    dst = os.path.join(REPO, 'public', 'test', 'cutout-check', a.label)
    for i in items:
        sd = S.sku_dir(i['sku'])
        os.makedirs(os.path.join(dst, sd), exist_ok=True)
        for f in ('photo.webp', 'cut.webp'):
            shutil.copy(os.path.join(d, 'site', sd, f), os.path.join(dst, sd, f))
    for n, i in enumerate(items):
        i['position'] = n
    print('карточек:', post(a.base, '/api/lab/cutout-check/items', {'run': a.label, 'items': items}))
    cookie = hmac.new(b'preview-secret', b'mesh-review-ok', hashlib.sha256).hexdigest()
    import subprocess
    os.makedirs(a.out, exist_ok=True)
    r = subprocess.run(['node', os.path.join(REPO, 'tools', 'ops', 'cutout-check-shots.mjs'), a.base, a.out, cookie], cwd=REPO, env={**os.environ, 'SHOT_BAD': '1'}, timeout=300)
    if r.returncode:
        return r.returncode
    print('снимки:', a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
