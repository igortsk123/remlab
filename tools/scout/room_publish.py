"""Публикация мешей КОМНАТ (room-pipeline-01 В-1б, T-20261105-47; разбор Codex `_intake/codex/room-bind-2026-11-05-answer.md`
§ «Publishing»): надстройка над `mesh_publish.py`, а не второй публикатор (место на диске прода, rsync и индекс — одни).

ЗАЧЕМ. Меши спальни сделаны и привязаны (`offer_asset_binding`, T-45), но на прод их отбор гостиной не берёт: он читает
только `products.mesh_*` и банк гостиной. Передать товары комнаты в `gallery_build.py` списком нельзя: галерея берёт
САМЫЙ СВЕЖИЙ манифест по mtime, а привязка объявила готовой конкретную попытку (`generation_key`) — уехала бы другая модель.

КАК. Без настройки — ничего (гостиная и её команды побайтно как прежде). С настройкой `ROOM_PUBLISH`:
  1. банк комнаты → offer_id (позиции и альтернативы наборов);
  2. по таблице привязки — только годные к публикации (local_3d ∧ appearance; с `ROOM_PUBLISH_READY=1` — только ready)
     → `mesh_id` владельца меша (у варианта — представитель, один раз на семью);
  3. файл в галерею — РОВНО `local_path` привязки, полный sha сверяется до и после копии; не сошёлся хоть один — комната
     отказ целиком (гостиная публикуется как обычно);
  4. уже выбранное гостиной не трогаем (её байты — её отбор); другие байты там — отметка, не перезапись.

    ROOM_PUBLISH=bedroom                    — живой банк `sets-bedroom.json` (`bank_paths.ROOM_BANKS`); нет — явный отказ
    ROOM_PUBLISH=bedroom=next               — кандидат `sets-bedroom.next.json` рядом (только по явному ключу)
    ROOM_PUBLISH=bedroom=/путь/банк.json    — явный файл
    python room_publish.py --plan [--ready-only]   # что уехало бы: меши, МБ, отказы — без копий и сети
    python room_publish.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ENV = 'ROOM_PUBLISH'
ENV_READY = 'ROOM_PUBLISH_READY'


class RoomConfigError(Exception):
    """Настройка комнаты есть, а банка нет или он не читается — комнату не публикуем (и не публикуем «всё подряд»)."""


def config(env=os.environ) -> list:
    """[(комната, путь банка)]; без ROOM_PUBLISH — [] (публикация гостиной как прежде). Нет файла банка — RoomConfigError."""
    import bank_paths as BP
    raw = (env.get(ENV) or '').strip()
    if not raw:
        return []
    out = []
    for part in [p.strip() for p in raw.split(',') if p.strip()]:
        room, _, src = part.partition('=')
        if room not in BP.ROOM_BANKS:
            raise RoomConfigError(f'{ENV}: комнаты {room!r} нет в bank_paths.ROOM_BANKS {sorted(BP.ROOM_BANKS)}')
        base = BP.ROOM_BANKS[room]
        if not src:
            path = os.path.join(HERE, f'{base}.json')            # живой банк комнаты
        elif src == 'next':
            path = os.path.join(HERE, f'{base}.next.json')       # кандидат — только по явному ключу
        else:
            path = src if os.path.isabs(src) else os.path.join(HERE, src)
        if not os.path.isfile(path):
            raise RoomConfigError(f'{ENV}: банка комнаты {room} нет ({path}) — комнату не публикую')
        out.append((room, path))
    return out


def bank_offers(bank: list) -> list:
    """offer_id позиций и альтернатив наборов, порядок появления, без повторов."""
    out, seen = [], set()

    def add(v):
        if not isinstance(v, dict):
            return
        k = v.get('sid') or (f"{v['mid']}:{v['eid']}" if v.get('mid') is not None and v.get('eid') is not None else None)
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    for s in bank:
        for v in (s.get('items') or {}).values():
            add(v)
        for lst in (s.get('alternates') or {}).values():
            for v in lst or []:
                add(v)
    return out


def eligible(row: dict, ready_only: bool) -> bool:
    """Годен к публикации: файл и вид годны (local_3d ∧ appearance); с ready_only — ещё и место в комнате (status ready)."""
    if row is None or not row.get('asset_id') or not row.get('local_path'):
        return False
    return row['status'] == 'ready' if ready_only else bool(row['local_3d'] and row['appearance'])


def plan(room: str, offers: list, rows: dict, ready_only: bool) -> dict:
    """→ {room, offers, meshes {mesh_id: {asset_id, local_path, offers[]}}, skipped {причина: n}, conflicts[]}.
    Вариант семьи → mesh_id представителя, один раз; разные байты под одним mesh_id — конфликт (комната отказ)."""
    meshes: dict = {}
    skipped: dict = {}
    conflicts = []
    for o in offers:
        r = rows.get(o)
        if r is None:
            why = 'no_binding'
        elif not eligible(r, ready_only):
            why = r['status'] if r['status'] != 'ready' else 'not_eligible'
        else:
            why = None
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        m = meshes.setdefault(r['mesh_id'], {'asset_id': r['asset_id'], 'local_path': r['local_path'], 'offers': []})
        if m['asset_id'] != r['asset_id']:
            conflicts.append(f"{r['mesh_id']}: {m['asset_id'][:19]} ≠ {r['asset_id'][:19]} ({o})")
            continue
        m['offers'].append(o)
    return {'room': room, 'offers': len(offers), 'meshes': meshes, 'skipped': skipped, 'conflicts': conflicts,
            'ready_only': ready_only}


def file_sha(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for ch in iter(lambda: f.read(1 << 20), b''):
                h.update(ch)
        return h.hexdigest()
    except OSError:
        return None


def stage(P: dict, gallery: str, living: set, sha=file_sha) -> dict:
    """Кладёт в галерею ровно файлы привязки. Сначала проверка ВСЕХ исходников (sha = asset_id), потом копии: любой сбой
    проверки — комната отказ, в галерее ничего не меняется. living — ключи «mid_eid», уже выбранные гостиной: их не трогаем.
    → {status ok|failed, staged[], same[], living_same[], living_other[], errors[], bytes}."""
    R = {'status': 'ok', 'staged': [], 'same': [], 'living_same': [], 'living_other': [], 'errors': list(P['conflicts']), 'bytes': 0}
    todo = []
    for mid, m in sorted(P['meshes'].items()):
        want = m['asset_id'].split(':', 1)[1]
        dst = os.path.join(gallery, mid, 'model.glb')
        if mid in living:
            (R['living_same'] if sha(dst) == want else R['living_other']).append(mid)
            continue
        got = sha(m['local_path'])
        if got != want:
            R['errors'].append(f"{mid}: файл привязки {m['local_path']} — sha {str(got)[:12]} ≠ {want[:12]}")
            continue
        todo.append((mid, m['local_path'], dst, want))
    if R['errors']:
        R['status'] = 'failed'
        return R
    for mid, src, dst, want in todo:
        if sha(dst) == want:
            R['same'].append(mid)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = f'{dst}.room-tmp-{os.getpid()}'
        with open(src, 'rb') as fi, open(tmp, 'wb') as fo:
            for ch in iter(lambda: fi.read(1 << 20), b''):
                fo.write(ch)
        if sha(tmp) != want:
            os.unlink(tmp)                   # свой недописанный временный файл
            R['errors'].append(f'{mid}: копия не сошлась по sha')
            R['status'] = 'failed'
            return R
        os.replace(tmp, dst)
        R['staged'].append(mid)
        R['bytes'] += os.path.getsize(dst)
    return R


def load_rows() -> tuple:
    import catalog_items as CI
    import room_bindings as RB
    return RB.load_db(CI.fetch)


def plans(env=os.environ, rows=None, ready_only=None) -> tuple:
    """([план по комнате], ошибки настройки). Без настройки — ([], [])."""
    try:
        cfg = config(env)
    except RoomConfigError as e:
        return [], [str(e)]
    if not cfg:
        return [], []
    if rows is None:
        rows, why = load_rows()
        if rows is None:
            return [], [f'привязка не читается ({why}) — комнаты не публикую']
    ro = (env.get(ENV_READY) == '1') if ready_only is None else ready_only
    out = []
    for room, path in cfg:
        try:
            bank = json.load(open(path, encoding='utf-8'))
        except Exception as e:  # noqa: BLE001
            return [], [f'банк {room} не читается ({path}): {str(e)[:120]}']
        P = plan(room, bank_offers(bank), rows, ro)
        P['bank'] = path
        P['snapshot'] = next(iter({r['snapshot_id'][:16] for r in rows.values()}), None)
        out.append(P)
    return out, []


def size_mb(P: dict) -> float:
    return sum(os.path.getsize(m['local_path']) for m in P['meshes'].values() if os.path.exists(m['local_path'])) / 2 ** 20


def summary(P: dict) -> str:
    return (f"{P['room']}: банк {os.path.basename(P['bank'])} — товаров {P['offers']}, мешей к публикации {len(P['meshes'])} "
            f"(~{size_mb(P):.0f} МБ; {'только ready' if P['ready_only'] else 'local_3d ∧ appearance'}), пропущено "
            + (', '.join(f'{k} {v}' for k, v in sorted(P['skipped'].items(), key=lambda kv: -kv[1])) or '0')
            + (f"; КОНФЛИКТЫ {len(P['conflicts'])}" if P['conflicts'] else '') + f"; привязка {P['snapshot']}")


# ---------------------------------------------------------------- селфтест: тесты Codex «Publisher tests» на подставных данных
def _selftest() -> int:
    import tempfile
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
        return bool(cond)
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as t:
        def glb(name, data):
            p = os.path.join(t, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'wb').write(data)
            return p
        old = glb('gen/1a-old/model.glb', b'OLD-GEN')                # более свежий, но не привязанный файл того же товара
        new = glb('gen/1a-bound/model.glb', b'BOUND-GEN')
        os.utime(new, (1, 1))                                       # привязанный — СТАРЕЕ по mtime
        rep = glb('gen/5r/model.glb', b'REP-GEN')
        sha = lambda b: 'sha256:' + hashlib.sha256(b).hexdigest()  # noqa: E731
        row = lambda st, aid, path, mesh, l3=True, ap=True: {'status': st, 'asset_id': aid, 'local_path': path,  # noqa: E731
                                                             'mesh_id': mesh, 'local_3d': l3, 'appearance': ap,
                                                             'snapshot_id': 'a' * 64}
        rows = {'1:a': row('ready', sha(b'BOUND-GEN'), new, '1_a'),
                '6:v': row('ready', sha(b'REP-GEN'), rep, '5_r'), '7:w': row('ready', sha(b'REP-GEN'), rep, '5_r'),
                '8:b': row('blocked', sha(b'X'), old, '8_b', l3=False),
                '9:s': row('blocked', sha(b'REP-GEN'), rep, '9_s', l3=True, ap=True)}   # годен к 3D, но не ready (solver)
        bank = [{'items': {'кровать': {'sid': '1:a'}, 'комод': {'mid': 6, 'eid': 'v'}, 'шкаф': None},
                 'alternates': {'комод': [{'sid': '7:w'}, {'sid': '8:b'}, {'sid': '1:a'}], 'шкаф': [{'sid': '9:s'}, {'sid': '0:none'}]}}]
        offers = bank_offers(bank)
        ok('банк → offer_id позиций и альтернатив, без повторов', offers == ['1:a', '6:v', '7:w', '8:b', '9:s', '0:none'])
        P = plan('bedroom', offers, rows, ready_only=False)
        ok('в публикацию — только годные привязки (blocked и без привязки — мимо)', sorted(P['meshes']) == ['1_a', '5_r', '9_s']
           and P['skipped'] == {'blocked': 1, 'no_binding': 1})
        ok('варианты семьи публикуют меш представителя ОДИН раз', P['meshes']['5_r']['offers'] == ['6:v', '7:w'])
        ok('ready_only — только ready', sorted(plan('bedroom', offers, rows, True)['meshes']) == ['1_a', '5_r'])
        gal = os.path.join(t, 'gallery')
        glb('gallery/1_a/model.glb', b'OLD-GEN')                      # галерея по mtime положила бы не тот файл
        R = stage(P, gal, living=set())
        ok('в галерее — файл ПРИВЯЗАННОГО поколения, даже если есть свежее непривязанное',
           R['status'] == 'ok' and open(os.path.join(gal, '1_a', 'model.glb'), 'rb').read() == b'BOUND-GEN'
           and sorted(R['staged']) == ['1_a', '5_r', '9_s'] and not [f for f in os.listdir(os.path.join(gal, '1_a')) if 'tmp' in f])
        ok('повтор — без копий (те же байты)', stage(P, gal, set())['same'] == ['1_a', '5_r', '9_s'])
        bad_rows = dict(rows, **{'1:a': row('ready', sha(b'SOMETHING-ELSE'), new, '1_a')})
        g2 = os.path.join(t, 'g2')
        R2 = stage(plan('bedroom', offers, bad_rows, False), g2, set())
        ok('sha файла привязки не сошёлся — комната отказ, в галерее ничего', R2['status'] == 'failed' and not os.path.exists(g2)
           and '1_a' in R2['errors'][0])
        R3 = stage(P, os.path.join(t, 'g3'), living={'5_r'})
        ok('меш, уже выбранный гостиной, не трогаем', '5_r' not in R3['staged'] and R3['living_other'] == ['5_r'])
        hand = os.path.join(t, 'g4')
        glb('g4/9_s/model.glb', b'HAND-WRONG')                        # выложено руками, байты не те
        R4 = stage(P, hand, set())
        ok('выложенные руками не те байты — заменяются файлом привязки', '9_s' in R4['staged']
           and open(os.path.join(hand, '9_s', 'model.glb'), 'rb').read() == b'REP-GEN')
        P5 = plan('bedroom', ['1:a', '2:a'], {'1:a': row('ready', sha(b'REP-GEN'), rep, '5_r'),
                                              '2:a': row('ready', sha(b'BOUND-GEN'), new, '5_r')}, False)
        ok('два разных файла под одним mesh_id — конфликт, комната отказ', P5['conflicts']
           and stage(P5, os.path.join(t, 'g5'), set())['status'] == 'failed')
        ok('без ROOM_PUBLISH — комнат нет, ошибок нет', plans({}, rows={}) == ([], []))
        pl, err = plans({ENV: 'bedroom=/нет/банка.json'}, rows=rows)
        ok('нет банка комнаты — явный отказ, а не «всё подряд»', pl == [] and err and 'банка комнаты' in err[0])
        pl, err = plans({ENV: 'kitchen'}, rows=rows)
        ok('неизвестная комната — отказ', pl == [] and 'ROOM_BANKS' in err[0])
        bp = os.path.join(t, 'bank.json')
        json.dump(bank, open(bp, 'w'))
        pl, err = plans({ENV: f'bedroom={bp}', ENV_READY: '1'}, rows=rows)
        ok('явный банк + ROOM_PUBLISH_READY=1', not err and sorted(pl[0]['meshes']) == ['1_a', '5_r'] and pl[0]['snapshot'] == 'a' * 16
           and 'только ready' in summary(pl[0]))
    print('selftest:', 'OK' if not bad else f'{bad} FAIL')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    if '--plan' in argv:
        pl, err = plans(ready_only=True if '--ready-only' in argv else None)
        for e in err:
            print('ОТКАЗ:', e)
        for P in pl:
            print(summary(P))
        return 1 if err else 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
