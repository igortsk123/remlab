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

  ~/venvs/scout/bin/python orient_worker.py --run [--limit N] [--vlm] [--recheck-roles]
  ~/venvs/scout/bin/python orient_worker.py --report
  ~/venvs/scout/bin/python orient_worker.py --dry-roles   # сколько «симметричных по роли» устарело и цена VLM
--recheck-roles: в пачку идут и решения «симметрична по роли», принятые при ПРЕЖНЕЙ политике ролей, если роль
теперь направленная или была неизвестна (отпечаток `role_policy()`; Codex T-36/3). Без флага не берутся: пересчёт
платный по VLM, включается явно (ведущий — по цифре сухого прогона).
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
import asset_strategy as AS  # noqa: E402 — канон переда роли и подсказок VLM


def directed_role(role: str, name: str = '', subtype: str = '') -> bool:
    """Направленность — из данных (`asset_strategy.front`, T-20261106-78): роль без записи с мешем — направленная (раньше —
    «симметрична по роли» без проверки). Банкетка и пуф — по признаку спинки (q25: подтип, не роль). `DIRECTED` — та же
    карта плюс роли профилей комнат; член `DIRECTED` направлен всегда (тест подменяет его)."""
    if role in DIRECTED:
        return True
    return AS.is_directed(role, name, subtype)


MANIFEST_ROLE_RULE = 1   # 05.11 (T-36/2): роль '?'/пустая → из manifest.json меша; смена правила роли → +1


def role_policy() -> str:
    """Отпечаток политики ролей: какие роли направленные и как роль находится. Ключ ревизии (`…|orient-v1`) его не
    содержит, поэтому решение «симметрична по роли» несёт отпечаток в себе: сменился DIRECTED / SEAT_ROLES / правило
    роли — такие решения видны как устаревшие (`stale_by_role_policy`), не нужно поднимать контракт всем мешам."""
    blob = json.dumps([sorted(DIRECTED), sorted(SEAT_ROLES), MANIFEST_ROLE_RULE], ensure_ascii=False)
    return 'roles-' + hashlib.sha1(blob.encode()).hexdigest()[:8]


def stale_by_role_policy(status: str, res: dict) -> bool:
    """Решение «симметрична по роли» принято при другой политике ролей, а роль теперь направленная (или была
    неизвестна — её теперь может дать manifest). Решения человека не трогаем никогда."""
    if str(status or '').startswith('human') or status == 'unusable':
        return False
    if (res or {}).get('source') != 'symmetric_by_role' or res.get('role_policy') == role_policy():
        return False
    role = (res.get('role') or '').strip()
    return role in ('', '?') or directed_role(role)


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


# Сырой меш стоймя и передом к камере фото → канон (фронт = MR-yaw 180): поворот на 180° вокруг +Y.
RAW_UPRIGHT_R = [[-1, 0, 0], [0, 1, 0], [0, 0, -1]]
RAW_UPRIGHT_QUAT = [0.0, 0.0, 1.0, 0.0]          # wxyz, det=+1, w ≥ 0


def role_from_manifest(glb: str, name: str = '') -> tuple[str, str]:
    """Роль меша из его manifest.json, когда SKU нет ни в mesh_demand, ни в products (T-20261105-36/2: спальня onb-10
    шла заданиями из файлов, карточек в БД нет — роль «?» уводила кровати и тумбы в «симметричные»)."""
    try:
        man = json.load(open(os.path.join(os.path.dirname(glb), 'manifest.json'), encoding='utf-8'))
        return (man.get('role') or '?'), (name or man.get('name') or '')
    except (OSError, ValueError):
        return '?', name


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


# Признаки сторон для VLM — по ролям: канон `front_hints` в `rules/asset-strategies.json` (T-20261106-78; был ROLE_HINTS)
def vlm_side(parts, role: str) -> tuple[str | None, float]:
    """Один кадр канонического фронта → «перед|зад» с уверенностью. Только предлагает."""
    import urllib.request

    from PIL import Image

    import draft_render as DR
    from mesh_render import render
    img = render(parts, float(FRONT_CANON_YAW), 10.0, size=(420, 420))
    bg = Image.new('RGB', img.size, (255, 255, 255))
    bg.paste(img, (0, 0), img)
    prompt = (f'На изображении {AS.front_hint(role)}. Какой стороной предмет повёрнут '
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
    if not (role or '').strip() or role == '?':          # NULL/пустая роль в mesh_demand — тоже «нет роли» (Codex T-36/2)
        role, name = role_from_manifest(glb, name)
    yaw, tilt = front_yaw_from_R(inf['R'])
    res = {'contract': CONTRACT, 'sku': sku, 'glb': os.path.basename(glb),
           'glb_sha': hashlib.sha256(open(glb, 'rb').read()).hexdigest(),
           'raw_to_canonical_quat_wxyz': inf['quat_wxyz'], 'R': inf['R'],
           'canonical_axes': {'front': 'MR-yaw 180', 'up': '+Y'},
           'legacy_front_yaw': yaw, 'up_tilt_deg': tilt, 'role': role,
           'versions': {'orienter': 'cscarv/3d-orienter@main', 'front': 2,
                        'vlm': 'alibaba/qwen3-vl-instruct'},
           'role_policy': role_policy(),
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
        # ПЕРЕД — ТОЖЕ ИЗ СЫРОГО (T-20261105-36/2): меш по фото смотрит на камеру фото = MR-yaw 0 (у сидячих с
        # уверенным сиденьем так 95–98 %: диваны 561/576, кресла 369/375, стулья 269/282). Канон «фронт = MR-yaw 180»
        # значит R = поворот на 180° вокруг вертикали, а не единичная: прежняя единичная ставила перед на зад сырого
        # меша — VLM у таких комодов в 49 из 67 сказал «зад», у тв-тумб 29 из 52.
        res['evidence']['orienter']['up_rejected'] = True
        inf = dict(inf, R=RAW_UPRIGHT_R, quat_wxyz=RAW_UPRIGHT_QUAT)
        res['R'] = inf['R']
        res['raw_to_canonical_quat_wxyz'] = inf['quat_wxyz']
        res['legacy_front_yaw'], res['up_tilt_deg'] = front_yaw_from_R(inf['R'])

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


def state_index() -> tuple[set, set]:
    """(все revision_key, устаревшие по политике ролей) — одним запросом."""
    rows = db("select revision_key, status, coalesce(resolution->>'source',''), coalesce(resolution->>'role',''), "
              "coalesce(resolution->>'role_policy','') from orientation_state")
    have = {r[0] for r in rows if r and r[0]}
    stale = {r[0] for r in rows if len(r) >= 5 and stale_by_role_policy(
        r[1], {'source': r[2], 'role': r[3], 'role_policy': r[4]})}
    return have, stale


def all_meshes() -> list[str]:
    return sorted(glob.glob(os.path.join(SCENE_DIR, 'meshes', '*.glb'))
                  + glob.glob(os.path.join(SCENE_DIR, 'salad-assets', '*', 'model.glb'))
                  # пилот Hunyuan (план orient-v2): sku на два уровня выше model.glb
                  + glob.glob(os.path.join(SCENE_DIR, 'meshes-hunyuan', 'meshes', 'hunyuan21', 'v2', '*', '*',
                                           'model.glb')))


def sku_of_glb(glb: str) -> str:
    return (sku_from_path(glb) or sku_from_path(os.path.basename(os.path.dirname(glb)))
            or sku_from_path(os.path.basename(os.path.dirname(os.path.dirname(glb)))) or '?')


def pending_meshes(limit: int, recheck_roles: bool = False) -> list[tuple[str, str, str]]:
    """(rev_key, sku, glb) без записи в orientation_state по текущему контракту; с recheck_roles — ещё и решения
    «симметрична по роли», устаревшие по политике ролей (`stale_by_role_policy`)."""
    out = []
    have, stale = state_index()
    for glb in all_meshes():
        sku = sku_of_glb(glb)
        sha = _sha16(glb)
        rk = f'{sku}|{sha}|{CONTRACT}'
        if rk not in have or (recheck_roles and rk in stale):
            out.append((rk, sku, glb))
        if len(out) >= limit:
            break
    _sha_flush()
    return out


VLM_TOKENS_IN = 420 * 420 // (28 * 28) + 120    # один кадр 420² (патчи 28 px у qwen-vl) + текст промпта
VLM_TOKENS_OUT = 60                               # max_tokens запроса vlm_side


def dry_roles() -> dict:
    """Сухой прогон --recheck-roles: какие устаревшие решения есть на диске, какая роль у них станет и сколько
    вызовов VLM это даст (верхняя граница: сидячим VLM нужен, только если сиденье не уверено). Ничего не пишет."""
    _, stale = state_index()
    by_role: dict = {}
    for glb in all_meshes():
        sku = sku_of_glb(glb)
        rk = f'{sku}|{_sha16(glb)}|{CONTRACT}'
        if rk not in stale:
            continue
        role, name, subtype = role_of(sku)
        if not (role or '').strip() or role == '?':
            role, name = role_from_manifest(glb, name)
        d = directed_role(role, name, subtype)
        c = by_role.setdefault(role, {'meshes': 0, 'directed': 0, 'vlm_max': 0, 'seat_first': 0})
        c['meshes'] += 1
        if d:
            c['directed'] += 1
            c['vlm_max'] += 1
            c['seat_first'] += role in SEAT_ROLES
    tot = {k: sum(c[k] for c in by_role.values()) for k in ('meshes', 'directed', 'vlm_max', 'seat_first')}
    out = {'role_policy': role_policy(), 'stale_in_db': len(stale), 'by_role': by_role, 'total': tot,
           'vlm_tokens_in': tot['vlm_max'] * VLM_TOKENS_IN, 'vlm_tokens_out': tot['vlm_max'] * VLM_TOKENS_OUT}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def run(limit: int, use_vlm: bool, recheck_roles: bool = False) -> None:
    os.makedirs(RES_DIR, exist_ok=True)
    lock = open(os.path.join(SCENE_DIR, 'orientation', 'worker.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('[orient] другой воркер уже работает — выходим', flush=True)
        return
    todo = pending_meshes(limit, recheck_roles)
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
        run(lim, '--vlm' in sys.argv, '--recheck-roles' in sys.argv)
    elif '--dry-roles' in sys.argv:
        dry_roles()
    elif '--report' in sys.argv:
        report()
    else:
        print(__doc__)
