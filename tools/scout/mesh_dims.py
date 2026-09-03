#!/usr/bin/env python3
"""Глубина товара из 3D-меша (план catalog-load-hardening П3.4; решение владельца 03.09: недостающие размеры
достраивать по мешу, а не читать чертежи нейросетью).

Идея: меш даёт ПРОПОРЦИИ. Известная ширина (и высота) из фида задаёт масштаб: d = ext_z × (w_cm / ext_x).
Гейт геометрии (Codex 03.09): не `mesh_ready()`, а точное совпадение
  asset_revisions.glb_sha (16 знаков) == префикс orientation_state.resolution.glb_sha (64) == sha256(model.glb на диске),
статус ориентации auto_resolved|human_resolved, без `unusable`, ревизия accepted|generated и не legacy.
Канонический фрейм — матрица R из ориентации (up=+Y, фронт −Z): X — ширина, Y — высота, Z — глубина.
Масштаб проверяется ПО ДВУМ осям: s_w = w/ext_x и s_h = h/ext_y; расходятся сильнее SCALE_TOL — глубину не
выводим (меш не пропорционален фото или ширина/высота в фиде врут).

Провенанс — dims_evidence.d = {source:'mesh_ratio', ref:'w', ratio, ext, glb_sha, revision_key, orient, role,
formula:'v1', confidence}. Фид с ИЗМЕРЕННОЙ глубиной сильнее (load3 не затирает mesh-глубину только когда
в фиде глубины нет). Смена меша/ориентации → значение stale (glb_sha в провенансе не совпадает) → пересчёт.

  mesh_dims.py --calibrate           # прямые диваны с глубиной из фида: ошибка формулы, вердикт (файл mesh-dims-calibration.json)
  mesh_dims.py --apply [--limit N]   # записать глубину товарам без неё (только роли/страты, прошедшие калибровку)
  mesh_dims.py --report
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MESH_DIR = os.path.expanduser(os.environ.get('MESH_DIR') or '~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
CALIB = os.path.join(HERE, 'mesh-dims-calibration.json')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
SCALE_TOL = 0.25        # |s_w/s_h − 1| больше — масштаб по осям не сходится, глубину не выводим
FORMULA = 'v1'
# Страты: только прямые диваны (угловые/модульные — другая геометрия, отдельная калибровка)
CORNER = re.compile(r'углов|модульн|п-образ|u-образ|г-образ|с оттоманк|с канапе|шезлонг', re.I)
ROLES_APPLY = {'диван'}
GATE_OK_SHARE = 0.80    # доля |Δ| ≤ 10 % в калибровке, ниже — не включаем
GATE_GROSS = 0.10       # доля грубых ошибок > 20 % — выше не включаем


def db(q: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:600])
    return [line.split('\x1f') for line in r.stdout.split('\n') if line]


def q(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


ELIGIBLE_SQL = """
select p.shop_mid, p.external_id, p.cat_role, p.name, p.w_cm, p.d_cm, p.h_cm,
       r.revision_key, o.resolution->>'glb_sha' as glb_sha, o.revision_key as orient_key, o.resolution::text, r.created
  from products p
  join asset_revisions r on r.sku = p.shop_mid||':'||p.external_id
   and r.status in ('accepted','generated') and r.origin <> 'legacy-local' and r.glb_sha is not null
  join orientation_state o on split_part(o.revision_key,'|',1) = r.sku
   and o.status in ('auto_resolved','human_resolved')
   and left(o.resolution->>'glb_sha',16) = r.glb_sha   -- в asset_revisions хеш обрезан до 16 знаков, в ориентации полный
   and coalesce(o.resolution->>'unusable','') <> 'true'
 where p.in_stock and p.w_cm is not null and p.h_cm is not null and p.cat_role in ({roles}) {extra}
 order by p.shop_mid, p.external_id, r.created desc
"""


def find_glb(sku: str, glb_sha: str) -> str | None:
    d = os.path.join(MESH_DIR, sku.replace(':', '_', 1))
    if not os.path.isdir(d):
        return None
    for job in sorted(os.listdir(d)):
        f = os.path.join(d, job, 'model.glb')
        if os.path.exists(f) and hashlib.sha256(open(f, 'rb').read()).hexdigest() == glb_sha:
            return f
    return None


_EXTENTS_CHILD = r"""
import json, sys, numpy as np, trimesh
glb, R = sys.argv[1], json.loads(sys.argv[2])
tm = trimesh.load(glb, force='mesh')
V = np.asarray(tm.vertices, np.float64)
if len(V) == 0:
    print('null'); sys.exit(0)
Vc = V @ np.asarray(R, np.float64).T          # как canonical_parts: apply_transform с R в блоке 3×3
ex = Vc.max(axis=0) - Vc.min(axis=0)
print(json.dumps([float(ex[0]), float(ex[1]), float(ex[2])]))
"""


def extents(glb: str, R: list[list[float]]) -> tuple[float, float, float] | None:
    """(ext_x=ширина, ext_y=высота, ext_z=глубина) в канонической системе ориентации.
    Считается в ДОЧЕРНЕМ процессе: trimesh на плотных Hunyuan-мешах не отдаёт память (03.09: +100 МБ на
    меш, 3,6 ГБ к 40-му, earlyoom снял процесс — тот же урок, что с topview_render)."""
    r = subprocess.run([sys.executable, '-c', _EXTENTS_CHILD, glb, json.dumps(R)], capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not r.stdout.strip() or r.stdout.strip() == 'null':
        return None
    ex = json.loads(r.stdout)
    return float(ex[0]), float(ex[1]), float(ex[2])


def rows(roles: set, extra: str = '') -> list[dict]:
    out, seen = [], set()
    for r in db(ELIGIBLE_SQL.format(roles=','.join(q(x) for x in roles), extra=extra)):
        if len(r) < 12:
            continue
        mid, eid, role, name, w, d, h, rk, sha, ok_, res, _created = r
        if f'{mid}:{eid}' in seen:      # одна (самая свежая) ревизия на товар
            continue
        seen.add(f'{mid}:{eid}')
        out.append({'sku': f'{mid}:{eid}', 'mid': int(mid), 'eid': eid, 'role': role, 'name': name,
                    'w': float(w) if w else None, 'd': float(d) if d else None, 'h': float(h) if h else None,
                    'revision_key': rk, 'glb_sha': sha, 'orient_key': ok_, 'resolution': json.loads(res)})
    return out


def estimate(it: dict) -> dict | None:
    glb = find_glb(it['sku'], it['glb_sha'])
    if not glb:
        return {'sku': it['sku'], 'skip': 'glb с таким sha не найден на диске'}
    ex = extents(glb, it['resolution']['R'])
    if not ex or min(ex) <= 0:
        return {'sku': it['sku'], 'skip': 'пустая геометрия'}
    ex_w, ex_h, ex_d = ex
    s_w, s_h = it['w'] / ex_w, it['h'] / ex_h
    consistency = s_w / s_h
    d_est = ex_d * s_w
    return {'sku': it['sku'], 'name': it['name'][:60], 'ext': [round(ex_w, 4), round(ex_h, 4), round(ex_d, 4)],
            's_w': round(s_w, 3), 's_h': round(s_h, 3), 'consistency': round(consistency, 3),
            'd_est': round(d_est, 1), 'd_feed': it['d'], 'w': it['w'], 'h': it['h'],
            'ok_scale': abs(consistency - 1) <= SCALE_TOL, 'glb_sha': it['glb_sha'],
            'revision_key': it['revision_key'], 'orient_key': it['orient_key']}


def calibrate() -> int:
    items = [it for it in rows(ROLES_APPLY, extra='and p.d_cm is not null') if not CORNER.search(it['name'])]
    print(f'калибровка: прямых диванов с глубиной из фида, мешом и ориентацией по тому же glb: {len(items)}', flush=True)
    res = []
    t0 = time.time()
    for it in items:
        e = estimate(it)
        if e and 'skip' not in e:
            e['ape'] = round(abs(e['d_est'] - e['d_feed']) / e['d_feed'], 3)
            e['under'] = round((e['d_feed'] - e['d_est']) / e['d_feed'], 3)   # >0 — недооценка
        res.append(e)
    good = [e for e in res if 'ape' in e]
    scaled = [e for e in good if e['ok_scale']]
    skipped = [e for e in res if 'skip' in e]

    def stats(xs: list[dict], label: str) -> dict:
        if not xs:
            print(f'  {label}: пусто'); return {}
        apes = sorted(e['ape'] for e in xs)
        n = len(apes)
        med = apes[n // 2]; p90 = apes[min(n - 1, int(0.9 * n))]
        within10 = sum(1 for a in apes if a <= 0.10) / n
        gross = sum(1 for a in apes if a > 0.20) / n
        max_under = max(e['under'] for e in xs)
        st = {'n': n, 'median_ape': med, 'p90_ape': p90, 'within10': round(within10, 3), 'gross20': round(gross, 3),
              'max_under': round(max_under, 3)}
        print(f'  {label}: n={n} медиана APE {med:.1%}, P90 {p90:.1%}, |Δ|≤10 %: {within10:.0%}, грубых >20 %: {gross:.0%}, '
              f'макс. недооценка {max_under:.0%}')
        return st
    print(f'посчитано {len(good)}, пропущено {len(skipped)} (нет glb с нужным sha и т.п.), {time.time() - t0:.0f} с')
    s_all = stats(good, 'все')
    s_ok = stats(scaled, f'с согласованным масштабом (|s_w/s_h−1| ≤ {SCALE_TOL})')
    verdict = bool(s_ok) and s_ok['within10'] >= GATE_OK_SHARE and s_ok['gross20'] <= GATE_GROSS
    print('ВЕРДИКТ:', 'включаем для прямых диванов' if verdict else 'НЕ включаем — порог не пройден, результат владельцу')
    worst = sorted(good, key=lambda e: -e['ape'])[:8]
    print('худшие:')
    for e in worst:
        print(f"  {e['sku']} {e['name'][:40]:40s} фид d={e['d_feed']} меш d={e['d_est']} (APE {e['ape']:.0%}, масштаб {e['consistency']})")
    json.dump({'date': time.strftime('%Y-%m-%d'), 'formula': FORMULA, 'roles': sorted(ROLES_APPLY), 'strata': 'straight sofas',
               'scale_tol': SCALE_TOL, 'gate': {'within10': GATE_OK_SHARE, 'gross20': GATE_GROSS}, 'all': s_all,
               'scaled': s_ok, 'verdict': verdict, 'items': res}, open(CALIB, 'w'), ensure_ascii=False, indent=1)
    print('файл калибровки:', CALIB)
    return 0 if verdict else 3


def apply(limit: int = 0) -> int:
    if not os.path.exists(CALIB):
        print('нет калибровки — сначала --calibrate'); return 2
    cal = json.load(open(CALIB))
    if not cal.get('verdict'):
        print('калибровка не пройдена — запись запрещена'); return 3
    items = [it for it in rows(set(cal['roles']), extra="and p.d_cm is null and p.dims_source is distinct from 'manual' and p.dims_source is distinct from 'scrape'")
             if not CORNER.search(it['name'])]
    if limit:
        items = items[:limit]
    print(f'кандидатов на глубину из меша: {len(items)}', flush=True)
    done = skipped = 0
    for it in items:
        e = estimate(it)
        if not e or 'skip' in e or not e['ok_scale']:
            skipped += 1
            continue
        ev = {'raw': e['ext'][2], 'unit': 'ratio', 'source': 'mesh_ratio', 'ref': 'w', 'ratio': e['s_w'],
              'ext': e['ext'], 'glb_sha': e['glb_sha'], 'revision_key': e['revision_key'], 'orient': e['orient_key'],
              'role': it['role'], 'formula': FORMULA, 'consistency': e['consistency'],
              'confidence': 'medium' if abs(e['consistency'] - 1) <= 0.1 else 'low'}
        db(f"""update products set d_cm = {e['d_est']},
                  dims_evidence = coalesce(dims_evidence,'{{}}'::jsonb) || jsonb_build_object('d', {q(json.dumps(ev, ensure_ascii=False))}::jsonb),
                  dims_source = coalesce(dims_source,'') || ' mesh:1'
                where shop_mid={it['mid']} and external_id={q(it['eid'])} and d_cm is null""")
        done += 1
    print(f'записано глубин: {done}, пропущено (нет glb/масштаб не сходится): {skipped}')
    return 0


def report() -> None:
    r = db("select count(*) filter (where dims_evidence->'d'->>'source'='mesh_ratio'), count(*) filter (where cat_role='диван' and in_stock and d_cm is null) from products")[0]
    print(f'глубин из меша в каталоге: {r[0]}; диванов in_stock без глубины: {r[1]}')


if __name__ == '__main__':
    if '--calibrate' in sys.argv:
        sys.exit(calibrate())
    if '--apply' in sys.argv:
        lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0
        sys.exit(apply(lim))
    report()
