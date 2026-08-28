#!/usr/bin/env python3
"""Мост DEV ↔ страница /lab/mesh-review (ADR-0131): спорные ориентации — человеку.

--push: для orientation_state review_pending собирает задачу (фото карточки + 4 ракурса
        КАНОНИЗИРОВАННОГО меша, data-URL) и идемпотентно POST-ит в прод (upsert по task_key).
--pull: забирает решения курсором after_id; курсор двигается ТОЛЬКО после применения (q25).
        Решение владельца финально: front_<yaw> докручивает канон так, чтобы фронт встал
        на 180 (наша конвенция), и пишется human_resolved.

Секреты: MESH_REVIEW_MACHINE_TOKEN и MESH_REVIEW_URL — из окружения или ~/.config/remlab/env
(значения — только в _secrets/ACCESS.md и на сервере, правило проекта).
"""
import base64
import io
import json
import math
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
CURSOR = os.path.join(SCENE_DIR, 'orientation', 'decisions.cursor')

from mesh_queue import db, q  # noqa: E402


def _env() -> tuple[str, str]:
    cfg = os.path.expanduser('~/.config/remlab/env')
    if os.path.exists(cfg):
        for ln in open(cfg):
            if '=' in ln and not ln.strip().startswith('#'):
                k, v = ln.strip().split('=', 1)
                os.environ.setdefault(k, v)
    url = os.environ.get('MESH_REVIEW_URL', 'https://remont-lab.online')
    tok = os.environ.get('MESH_REVIEW_MACHINE_TOKEN', '')
    if not tok:
        raise SystemExit('нет MESH_REVIEW_MACHINE_TOKEN (см. _secrets/ACCESS.md)')
    return url.rstrip('/'), tok


def _api(method: str, path: str, body: dict | None = None) -> dict:
    url, tok = _env()
    req = urllib.request.Request(url + path, method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={'Authorization': f'Bearer {tok}',
                                          'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def _durl(img) -> str:
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'JPEG', quality=80)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()


def _renders(glb: str, R: list[list[float]]) -> dict:
    from PIL import Image

    from mesh_render import render
    from orient_worker import canonical_parts
    parts = canonical_parts(glb, R)
    out = {}
    for y in (0, 90, 180, 270):
        im = render(parts, float(y), 10.0, size=(320, 320))
        bg = Image.new('RGB', im.size, (255, 255, 255))
        bg.paste(im, (0, 0), im)
        out[str(y)] = _durl(bg)
    return out


def _photo(sku: str) -> str | None:
    from PIL import Image
    rows = db(f"select image_url from mesh_demand where sku={q(sku)} and image_url is not null")
    url = rows[0][0] if rows and rows[0][0] else None
    if not url:   # SKU вне текущего спроса (старый кэш) — фото из каталога
        rows = db(f"""select image_url from products
                      where shop_mid||':'||external_id={q(sku)} and image_url is not null""")
        url = rows[0][0] if rows and rows[0][0] else None
    if not url:
        return None
    if url.startswith('//'):
        url = 'https:' + url
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            im = Image.open(io.BytesIO(r.read()))
        im.thumbnail((320, 320))
        return _durl(im)
    except Exception:  # noqa: BLE001 — задача без фото хуже, но не бесполезна
        return None


def _glb_of(rev_key: str) -> str | None:
    """GLB локального кэша по revision_key (sku|sha16|contract)."""
    import glob
    import hashlib
    sku, sha = rev_key.split('|')[0], rev_key.split('|')[1]
    pat = os.path.join(SCENE_DIR, 'meshes', sku.replace(':', '_') + '*.glb')
    for p in glob.glob(pat):
        if hashlib.sha256(open(p, 'rb').read()).hexdigest()[:16] == sha:
            return p
    return None


def push(limit: int = 30) -> None:
    rows = db(f"""select revision_key, sku, resolution from orientation_state
                  where status='review_pending' order by updated limit {limit}""")
    tasks = []
    for rk, sku, res_j in rows:
        res = json.loads(res_j)
        glb = _glb_of(rk)
        payload = {'name': res.get('glb'), 'source': res.get('source'),
                   'photo': _photo(sku)}
        if glb and res.get('R'):
            payload['renders'] = _renders(glb, res['R'])
        elif glb and res.get('raw_to_canonical_quat_wxyz'):
            payload['renders'] = _renders(glb, _quat_to_R(res['raw_to_canonical_quat_wxyz']))
        tasks.append({'taskKey': rk, 'sku': sku, 'role': res.get('role'),
                      'contract': res.get('contract', 'orient-v1'), 'payload': payload})
    if not tasks:
        print('[review] спорных нет', flush=True)
        return
    r = _api('POST', '/api/lab/mesh-review/tasks', {'tasks': tasks})
    print(f"[review] отправлено задач: {r.get('put')}", flush=True)


def _quat_to_R(qw: list[float]) -> list[list[float]]:
    w, x, y, z = qw
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def _ry(deg: float) -> list[list[float]]:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def _matmul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def apply_decision(rk: str, choice: str) -> None:
    rows = db(f"select resolution from orientation_state where revision_key={q(rk)}")
    if not rows:
        return
    res = json.loads(rows[0][0])
    res['human'] = {'choice': choice}
    if choice.startswith('front_'):
        y = int(choice.split('_')[1])
        # фронт оказался на ракурсе y → докрутить канон, чтобы фронт встал на 180
        extra = (180 - y) % 360
        if res.get('R'):
            res['R'] = _matmul(_ry(extra), res['R'])
            from orient_infer import quat_wxyz  # noqa: PLC0415 — лёгкий импорт без torch
            import numpy as np
            res['raw_to_canonical_quat_wxyz'] = quat_wxyz(np.asarray(res['R']))
        res['legacy_front_yaw'] = (res.get('legacy_front_yaw', 0) - extra) % 360
        res.update(status='human_resolved', source=f'human:{choice}')
    elif choice == 'symmetric':
        res.update(status='human_resolved', source='human:symmetric',
                   equivalence=[0, 90, 180, 270])
    elif choice in ('bad_up', 'bad_mesh'):
        # непригоден: ориентация не решается — меш на перегенерацию/замену (слот-контракт)
        res.update(status='human_resolved', source=f'human:{choice}', unusable=True)
    else:
        return  # skip не двигает состояние
    db(f"""update orientation_state set status={q(res['status'])},
           resolution={q(json.dumps(res, ensure_ascii=False))}::jsonb, updated=now()
           where revision_key={q(rk)}""")


def pull() -> None:
    after = 0
    if os.path.exists(CURSOR):
        after = int(open(CURSOR).read().strip() or 0)
    r = _api('GET', f'/api/lab/mesh-review/decisions?after_id={after}')
    n = 0
    for d in r.get('decisions', []):
        apply_decision(d['taskKey'], d['choice'])
        open(CURSOR, 'w').write(str(d['id']))   # курсор — после применения (q25)
        n += 1
    print(f'[review] применено решений: {n}', flush=True)


if __name__ == '__main__':
    if '--push' in sys.argv:
        push()
    elif '--pull' in sys.argv:
        pull()
    else:
        print(__doc__)
