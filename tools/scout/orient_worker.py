#!/usr/bin/env python3
"""Каскад ориентации мешей (ADR-0131, план mesh-queue-orientation).

Порядок на меш: (1) 3d-orienter+flipper (отдельный venv, subprocess) → точная матрица
«сырой→канон» Кабшем + уверенность; (2) наш `mesh_front` на КАНОНИЗИРОВАННОМ меше — авторитет
фронта сидячих (замер 28.08: канонический фронт = MR-yaw 180); (3) правило симметрии по
роли/подтипу; (4) VLM qwen3-vl — только ПРЕДЛАГАЕТ (признаковый промпт, один кадр); согласен
с orienter → второй свидетель, авто; противоречит → человеку. Авто-разворот от VLM ЗАПРЕЩЁН
(q24). Спорное → review_pending (страница /lab/mesh-review, человек финален).

Вердикт — resolution: raw_to_canonical quaternion (det=+1, w≥0) + версии методов + evidence.
GLB не перезаписывается. Легаси-совместимость: front_yaw выводится из кватерниона.

  ~/venvs/scout/bin/python orient_worker.py --run [--limit N] [--vlm]
  ~/venvs/scout/bin/python orient_worker.py --report
Один воркер на машину (flock); тяжёлое — под nice.
"""
import fcntl
import glob
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
RES_DIR = os.path.join(SCENE_DIR, 'orientation', 'v1')
ORIENTER_PY = os.path.expanduser('~/venvs/orienter/bin/python')
CONTRACT = 'orient-v1'          # версия контракта каскада; смена = пересчёт
FRONT_CANON_YAW = 180           # фронт канона в нашей MR-конвенции (замер 28.08)

from mesh_front import NONDIRECTIONAL, SEAT_ROLES, infer_seat_front  # noqa: E402
from mesh_queue import DIRECTED, db, q  # noqa: E402


def directed_role(role: str, name: str = '', subtype: str = '') -> bool:
    if role in DIRECTED or role in SEAT_ROLES:
        t = f'{name} {subtype}'.lower()
        if role in ('пуф', 'банкетка'):
            return 'спинк' in t     # без спинки — симметрична (q25: подтип, не роль)
        return True
    return False


def front_yaw_from_R(R: list[list[float]]) -> tuple[int, float]:
    """Легаси front_yaw из матрицы: raw_front = Rᵀ·f_canon; f_canon = ry(180)·Z = (0,0,-1).
    Наклон — ХУДШИЙ из двух: перед от горизонтали И верх от вертикали. Проверка только
    переда пропускала крен «на бок» (комоды владельца 28.08): перед горизонтален, а
    предмет лежит."""
    fx = -R[2][0]; fy = -R[2][1]; fz = -R[2][2]       # Rᵀ @ (0,0,-1)
    yaw = round(math.degrees(math.atan2(fx, fz))) % 360
    t_front = abs(math.degrees(math.asin(max(-1.0, min(1.0, fy)))))
    t_up = math.degrees(math.acos(max(-1.0, min(1.0, R[1][1]))))   # up_raw·ŷ = R[1][1]
    return yaw, round(max(t_front, t_up), 1)


def sku_from_path(p: str) -> str | None:
    m = re.match(r'(\d+)_(\d+)', os.path.basename(p))
    return f'{m.group(1)}:{m.group(2)}' if m else None


def role_of(sku: str | None) -> tuple[str, str, str]:
    if sku:
        rows = db(f"select role, coalesce(name,''), '' from mesh_demand where sku={q(sku)}")
        if rows and len(rows[0]) >= 2:
            return rows[0][0], rows[0][1], ''
        rows = db(f"""select coalesce(cat_role,'?'), coalesce(name,''), ''
                       from products where shop_mid||':'||external_id={q(sku)}""")
        if rows and len(rows[0]) >= 2:
            return rows[0][0], rows[0][1], ''
    return '?', '', ''


def canonical_parts(glb: str, R: list[list[float]]):
    """Канонизированный меш как parts для mesh_front/рендера: применяем R и грузим заново."""
    import numpy as np
    import trimesh

    from mesh_render import load_parts
    tm = trimesh.load(glb, force='mesh')
    T = np.eye(4); T[:3, :3] = np.asarray(R)
    tm.apply_transform(T)
    fd, tmp = tempfile.mkstemp(suffix='.obj')
    os.close(fd)
    tm.export(tmp)
    try:
        return load_parts(tmp)
    finally:
        os.unlink(tmp)


# Признаки сторон для VLM — по ролям (протокол бенча 28.08: описывать ПРИЗНАКИ, не просить сравнивать)
ROLE_HINTS = {
    'стул': 'обеденный стул. СПЕРЕДИ: видно сиденье-подушку, спинка ЗА ним. СЗАДИ: только спинка во весь рост',
    'кресло': 'кресло. СПЕРЕДИ: сиденье и подлокотники раскрыты к зрителю. СЗАДИ: глухая спинка',
    'диван': 'диван. СПЕРЕДИ: сиденье и подушки. СЗАДИ: глухая спинка',
    'банкетка': 'банкетка. СПЕРЕДИ: сиденье, спинка за ним. СЗАДИ: спинка закрывает сиденье',
    'тв-тумба': 'ТВ-тумба. СПЕРЕДИ: дверцы, ящики, полки. СЗАДИ: глухая стенка',
    'комод': 'комод. СПЕРЕДИ: ящики с ручками. СЗАДИ: глухая стенка',
    'стеллаж': 'стеллаж. СПЕРЕДИ: открытые полки. СЗАДИ: задняя стенка',
    'стенка': 'мебельная стенка. СПЕРЕДИ: фасады и ниша под ТВ. СЗАДИ: глухая стенка',
    'витрина': 'витрина. СПЕРЕДИ: стеклянные дверцы. СЗАДИ: глухая стенка',
    'камин': 'камин/биокамин. СПЕРЕДИ: очаг (топка). СЗАДИ: глухой корпус',
}


def vlm_side(parts, role: str) -> tuple[str | None, float]:
    """Один кадр канонического фронта → «перед|зад» с уверенностью. Только предлагает."""
    import urllib.request

    from PIL import Image

    import draft_render as DR
    from mesh_render import render
    img = render(parts, float(FRONT_CANON_YAW), 10.0, size=(420, 420))
    bg = Image.new('RGB', img.size, (255, 255, 255))
    bg.paste(img, (0, 0), img)
    prompt = (f'На изображении {ROLE_HINTS.get(role, role)}. Какой стороной предмет повёрнут '
              'к зрителю? Ответь строго JSON: {"side": "перед"|"зад", "confidence": 0..1}')
    body = {'model': 'alibaba/qwen3-vl-instruct', 'max_tokens': 60,
            'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': DR._b64(bg, 85)}}]}]}
    req = urllib.request.Request(DR.CHAT_URL, json.dumps(body).encode(),
                                 {'Authorization': 'Bearer ' + DR.gw_key(),
                                  'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = json.loads(r.read())['choices'][0]['message']['content'] or ''
        m = re.search(r'\{.*\}', txt, re.S)
        d = json.loads(m.group(0))
        return str(d.get('side', '')).lower() or None, float(d.get('confidence', 0))
    except Exception as e:  # noqa: BLE001 — VLM недоступен: остаёмся на vlm_pending
        print(f'  vlm: {str(e)[:80]}', flush=True)
        return None, 0.0


def decide(sku: str, glb: str, inf: dict, use_vlm: bool) -> dict:
    """Каскад для одного меша → resolution dict (status + evidence)."""
    role, name, subtype = role_of(sku)
    yaw, tilt = front_yaw_from_R(inf['R'])
    res = {'contract': CONTRACT, 'sku': sku, 'glb': os.path.basename(glb),
           'glb_sha': hashlib.sha256(open(glb, 'rb').read()).hexdigest(),
           'raw_to_canonical_quat_wxyz': inf['quat_wxyz'], 'R': inf['R'],
           'canonical_axes': {'front': 'MR-yaw 180', 'up': '+Y'},
           'legacy_front_yaw': yaw, 'up_tilt_deg': tilt, 'role': role,
           'versions': {'orienter': 'cscarv/3d-orienter@main', 'front': 2,
                        'vlm': 'alibaba/qwen3-vl-instruct'},
           'evidence': {'orienter': {'flip_prob': inf['flip_prob'],
                                     'pset_size': inf['pset_size']}}}
    if not directed_role(role, name, subtype):
        res.update(status='auto_resolved', source='symmetric_by_role',
                   equivalence=NONDIRECTIONAL.get(role, [0, 90, 180, 270]))
        return res
    if tilt > 15:
        # Orienter завалил «верх» (владелец 28.08: комоды на спине). Генераторы отдают мебель
        # СТОЙМЯ — up из сырого GLB надёжнее нейросети. Её наклон отбрасываем целиком: меш
        # остаётся стоять, а перед решают следующие слои (сиденье/VLM) уже на сыром меше.
        res['evidence']['orienter']['up_rejected'] = True
        inf = dict(inf, R=[[1, 0, 0], [0, 1, 0], [0, 0, 1]], quat_wxyz=[1.0, 0.0, 0.0, 0.0])
        res['raw_to_canonical_quat_wxyz'] = inf['quat_wxyz']
        res['legacy_front_yaw'], res['up_tilt_deg'] = 180, 0.0

    parts = canonical_parts(glb, inf['R'])
    if role in SEAT_ROLES:
        seat = infer_seat_front(parts, role, has_back=directed_role(role, name, subtype))
        res['evidence']['seat'] = {k: seat.get(k) for k in ('front_yaw', 'status', 'margin')}
        if seat.get('status') == 'confident':
            if seat.get('front_yaw') == FRONT_CANON_YAW:
                res.update(status='auto_resolved', source='orienter+seat_agree')
            else:
                res.update(status='review_pending', source='seat_conflict')
            return res
    # корпусные и сидячие без уверенного сиденья → VLM-свидетель
    if not use_vlm:
        res.update(status='vlm_pending', source='awaiting_vlm')
        return res
    side, conf = vlm_side(parts, role)
    res['evidence']['vlm'] = {'side': side, 'confidence': conf}
    if side == 'перед' and conf >= 0.7 and inf['flip_prob'] >= 0.5:
        res.update(status='auto_resolved', source='orienter+vlm_agree')
    else:
        res.update(status='review_pending',
                   source='vlm_disagree' if side == 'зад' else 'vlm_unsure')
    return res


_SHA_CACHE = os.path.expanduser('~/scout-scenes/orientation/sha-cache.json')


def _sha16(path: str) -> str:
    """sha16 файла с кэшем по (mtime, size): шаг заново читал ВСЕ модели (>1 ГБ на круг)
    и не укладывался в таймаут конвейера — «ориентация: СБОЙ Terminated» (01.09)."""
    try:
        st = os.stat(path)
        key = f'{path}'
        cache = _sha16.cache
        if cache is None:
            cache = {}
            if os.path.exists(_SHA_CACHE):
                try:
                    cache = json.load(open(_SHA_CACHE, encoding='utf-8'))
                except Exception:  # noqa: BLE001
                    cache = {}
            _sha16.cache = cache
        hit = cache.get(key)
        if hit and hit[0] == int(st.st_mtime) and hit[1] == st.st_size:
            return hit[2]
        sha = hashlib.sha256(open(path, 'rb').read()).hexdigest()[:16]
        cache[key] = [int(st.st_mtime), st.st_size, sha]
        _sha16.dirty = True
        return sha
    except Exception:  # noqa: BLE001
        return hashlib.sha256(open(path, 'rb').read()).hexdigest()[:16]


_sha16.cache = None
_sha16.dirty = False


def _sha_flush() -> None:
    if _sha16.dirty and _sha16.cache is not None:
        os.makedirs(os.path.dirname(_SHA_CACHE), exist_ok=True)
        json.dump(_sha16.cache, open(_SHA_CACHE, 'w', encoding='utf-8'))
        _sha16.dirty = False


def pending_meshes(limit: int) -> list[tuple[str, str, str]]:
    """(rev_key, sku, glb) без записи в orientation_state по текущему контракту."""
    out = []
    have = {r[0] for r in db('select revision_key from orientation_state') if r and r[0]}
    for glb in sorted(glob.glob(os.path.join(SCENE_DIR, 'meshes', '*.glb'))
                      + glob.glob(os.path.join(SCENE_DIR, 'salad-assets', '*', 'model.glb'))
                      # пилот Hunyuan (план orient-v2): sku на два уровня выше model.glb
                      + glob.glob(os.path.join(SCENE_DIR, 'meshes-hunyuan', 'meshes',
                                               'hunyuan21', 'v2', '*', '*', 'model.glb'))):
        sku = (sku_from_path(glb) or sku_from_path(os.path.basename(os.path.dirname(glb)))
               or sku_from_path(os.path.basename(os.path.dirname(os.path.dirname(glb)))) or '?')
        sha = _sha16(glb)
        rk = f'{sku}|{sha}|{CONTRACT}'
        if rk not in have:
            out.append((rk, sku, glb))
        if len(out) >= limit:
            break
    _sha_flush()
    return out


def run(limit: int, use_vlm: bool) -> None:
    os.makedirs(RES_DIR, exist_ok=True)
    lock = open(os.path.join(SCENE_DIR, 'orientation', 'worker.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('[orient] другой воркер уже работает — выходим', flush=True)
        return
    todo = pending_meshes(limit)
    if not todo:
        print('[orient] нечего делать', flush=True)
        return
    lst = os.path.join(RES_DIR, '_batch.txt')
    open(lst, 'w').write('\n'.join(g for _, _, g in todo))
    outp = os.path.join(RES_DIR, '_batch.json')
    r = subprocess.run(['nice', '-n', '15', ORIENTER_PY,
                        os.path.join(HERE, 'orient_infer.py'), '--list', lst, '--out', outp],
                       capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        print('[orient] infer упал:', r.stderr[-300:], flush=True)
        return
    inf_all = json.load(open(outp))
    done = {}
    for rk, sku, glb in todo:
        inf = inf_all.get(glb) or {}
        if 'error' in inf or 'R' not in inf:
            res = {'contract': CONTRACT, 'sku': sku, 'status': 'review_pending',
                   'source': 'infer_error', 'error': inf.get('error', 'нет результата')}
        else:
            try:
                res = decide(sku, glb, inf, use_vlm)
            except Exception as e:  # noqa: BLE001 — один меш не валит пакет
                res = {'contract': CONTRACT, 'sku': sku, 'status': 'review_pending',
                       'source': 'cascade_error', 'error': str(e)[:200]}
        fp = os.path.join(RES_DIR, rk.replace(':', '_').replace('|', '__') + '.json')
        json.dump(res, open(fp + '.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(fp + '.tmp', fp)
        db(f"""insert into orientation_state (revision_key, sku, status, resolution)
               values ({q(rk)}, {q(sku)}, {q(res['status'])},
                       {q(json.dumps(res, ensure_ascii=False))}::jsonb)
               on conflict (revision_key) do update
                 set status=excluded.status, resolution=excluded.resolution, updated=now()""")
        done[res['status']] = done.get(res['status'], 0) + 1
        print(f"  {os.path.basename(glb)}: {res['status']} ({res.get('source', '')})", flush=True)
    print(f'[orient] итог: {done}', flush=True)


def report() -> None:
    rows = db("""select status, coalesce(resolution->>'source','?'), count(*)
                   from orientation_state group by 1,2 order by 3 desc""")
    for st, src, n in rows:
        print(f'{st:16s} {src:22s} {n}')


if __name__ == '__main__':
    if '--run' in sys.argv:
        lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 100
        run(lim, '--vlm' in sys.argv)
    elif '--report' in sys.argv:
        report()
    else:
        print(__doc__)
