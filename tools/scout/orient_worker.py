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
  ~/venvs/scout/bin/python orient_worker.py --dry-roles   # сколько решений устарело по ролям и цена VLM
  ~/venvs/scout/bin/python orient_worker.py --shadow DIR [--limit N] [--vlm]   # перерешить устаревшие В ПАПКУ, без БД
  ~/venvs/scout/bin/python orient_worker.py --bed-guard [--apply] [--out F.json]   # сторож изголовья всех кроватей (без --apply — сухо)
Кровати (T-20261110-20/3): до VLM — свидетель изголовья по геометрии (`bed_headboard`, `apply_headboard`): уверен — решено
(согласие или доворот матрицы), стоит боком без ясного торца — `review_pending`/`headboard_sideways` (блок в привязке).
--recheck-roles: в пачку идут и решения, устаревшие по ролям (`stale_by_role`): (а) «симметрична по роли», принятое при
ПРЕЖНЕЙ политике ролей, если роль теперь направленная или была неизвестна (отпечаток `role_policy()`; Codex T-36/3);
(б) СМЕНА РОЛИ в каталоге — роль решения ≠ текущей (`current_role`), в любую сторону: симметричная → направленная,
направленная → симметричная (пуф, решённый «как диван» до T-53), направленная → другая (T-20261105-56/5). Решения
человека и `unusable` — никогда. Ночной `refresh_daily.sh` идёт с флагом (T-20261105-56/6); устаревшие — в общей
квоте `--limit` вместе с новыми.
Сторож поворота (`yaw_guard`, T-20261105-56/6): авто-решение направленного, которое МЕНЯЕТ уже опубликованный yaw этого же
меша (прод `orient.json`, тот же sha16), пишется `review_pending` (источник `yaw_change_guard`) — на прод молча не уходит.
Деньги VLM (T-20261105-56/7): каждый ответ — в общий журнал `openai-spend.jsonl` (`openai_budget.log_spend`, цена шлюза в
`rules/openai_prices.json`); перед пачкой — дневной лимит `openai_budget.allow`, не влезает — пачка без VLM (vlm_pending).
--shadow DIR: только устаревшие по ролям (без новых мешей), решения — файлами в DIR и `DIR/index-overlay.json`
(формат индекса `topview_render.orient_index` → `TOPVIEW_ORIENT_INDEX`); в БД и `orientation/v1` не пишет.
Один воркер на машину (flock); тяжёлое — под nice.
"""
import fcntl
import gc
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
from openai_budget import allow, log_spend, price_of  # noqa: E402 — учёт и дневной лимит платных вызовов (T-56/7)
import bed_headboard as HB  # noqa: E402 — изголовье кровати по геометрии (T-20261110-20/3)

VLM_MODEL = 'alibaba/qwen3-vl-instruct'   # через шлюз Vercel; цена — rules/openai_prices.json
# Кровати: перед/зад VLM видит, а разворот на 90° — нет (отвечает «перед» почти всегда): Лория/Кейла 120 стояли боком
# с `orienter+vlm_agree`. Свидетель — изголовье по геометрии (`bed_headboard`), до VLM (T-20261110-20/3)
BED_ROLES = ('кровать',)


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


def _known(role) -> str:
    """Роль или '' — пустая и «?» значат «роль неизвестна»."""
    r = (role or '').strip()
    return '' if r == '?' else r


def role_changed(status: str, res: dict, cur_role: str | None) -> bool:
    """Роль, по которой решал каскад (`resolution.role`), ≠ текущей роли товара — решение устарело в ЛЮБУЮ сторону
    (T-20261105-56/5): пуф, решённый «как диван» до правила названий T-53, держит поворот направленного предмета.
    Обе роли должны быть известны (роль «?» — забота `stale_by_role_policy`); человек и `unusable` — никогда. После
    перерешения `decide` пишет текущую роль — по кругу не гоняется."""
    if str(status or '').startswith('human') or status == 'unusable':
        return False
    old, cur = _known((res or {}).get('role')), _known(cur_role)
    return bool(old and cur and old != cur)


def stale_by_role(status: str, res: dict, cur_role: str | None) -> bool:
    """Одно правило «решение устарело по ролям»: прежняя политика ролей ИЛИ смена роли товара."""
    return stale_by_role_policy(status, res) or role_changed(status, res, cur_role)


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


# Каталожная роль, которая НЕ считается известной: пусто/NULL (в каталоге это «без роли»), «?», «другое».
CAT_ROLE_UNKNOWN = frozenset({'', '?', 'другое', 'без роли'})


def cat_role_known(role) -> bool:
    return str(role or '').strip() not in CAT_ROLE_UNKNOWN


# Узкая роль → общая, которую она уточняет (T-20261107-10/2): один SKU в двух комнатах (68 шкафов-купе divan.ru — «шкаф» в
# спальне и «шкаф-купе» в прихожей) берёт узкую — у неё точнее перед и подсказка VLM («раздвижные двери», не «дверцы»).
ROLE_NARROWER = {'шкаф-купе': 'шкаф'}


def pick_room_role(rows) -> tuple[str, str] | None:
    """Роль SKU по строкам `room_catalog` (спальня, прихожая; [(роль, имя)]) → (роль, имя) или None (T-20261107-10/2,
    Codex 07.11). Одна известная роль — она. Несколько: общая, уточнённая присутствующей узкой (`ROLE_NARROWER`), уходит;
    из оставшихся направленная главнее ненаправленной; дальше — первая по алфавиту (детерминированно, не по порядку
    комнат в JSON). Чистая функция."""
    rs: dict = {}
    for role, name in rows or ():
        if cat_role_known(role):
            rs.setdefault(role.strip(), name or '')
    if not rs:
        return None
    cand = [r for r in rs if not any(ROLE_NARROWER.get(o) == r for o in rs)] or list(rs)
    cand = [r for r in cand if directed_role(r, rs[r])] or cand
    r = sorted(cand)[0]
    return r, rs[r]


def pick_role(cat: tuple | None, demand: tuple | None, room: tuple | None = None) -> tuple[str, str, str]:
    """Порядок ролей. (0) Роль КОМНАТЫ (`room_catalog`, `pick_room_role`; T-20261107-10/2, Codex 07.11) главнее всего:
    каталог гостиной (`products.cat_role`) знает товар прихожей по своей роли — банкетку как «пуф» (симметричный
    [0,90,180,270] вместо «по спинке»), консоль как «комод», шкаф-купе как «шкаф». (1) Известная роль каталога
    (`products.cat_role`) главнее `mesh_demand` (T-20261105-56/5 правки) — там роль замораживается при постановке задания
    и отстаёт от каталога (пуф «Красавчик» оставался диваном). Каталог не знает роли (`CAT_ROLE_UNKNOWN`) → `mesh_demand`,
    затем что есть в каталоге, иначе «?» (дальше — манифест). cat/demand/room — (роль, имя) или None."""
    if room and cat_role_known(room[0]):
        return room[0], room[1] or (cat[1] if cat else '') or (demand[1] if demand else ''), ''
    if cat and cat_role_known(cat[0]):
        return cat[0], cat[1] or (demand[1] if demand else ''), ''
    if demand:
        return demand[0], demand[1], ''
    if cat:
        return (cat[0] or '?'), cat[1], ''
    return '?', '', ''


def role_of(sku: str | None) -> tuple[str, str, str]:
    if not sku:
        return '?', '', ''
    room = pick_room_role([(r[0], r[1]) for r in db(f"""select role, coalesce(name,'') from room_catalog
                                                       where shop_mid||':'||external_id={q(sku)}""") or [] if len(r) >= 2])
    if room:
        return pick_role(None, None, room)
    rows = db(f"""select coalesce(cat_role,''), coalesce(name,''), ''
                   from products where shop_mid||':'||external_id={q(sku)}""")
    cat = (rows[0][0], rows[0][1]) if rows and len(rows[0]) >= 2 else None
    if cat and cat_role_known(cat[0]):
        return pick_role(cat, None)
    rows = db(f"select role, coalesce(name,''), '' from mesh_demand where sku={q(sku)}")
    demand = (rows[0][0], rows[0][1]) if rows and len(rows[0]) >= 2 else None
    return pick_role(cat, demand)


def role_index(skus) -> dict:
    """`role_of` для многих SKU тремя запросами на пачку (тот же порядок: `pick_room_role` → `pick_role`) — `pending_meshes` смотрит
    тысячи ревизий, по запросу на каждую выходило бы по 2 вызова psql на меш. SKU без строк — нет в словаре."""
    skus = sorted({s for s in skus if s and s != '?'})
    cat: dict = {}
    dem: dict = {}
    rooms: dict = {}
    for i in range(0, len(skus), 500):
        inl = ','.join(q(s) for s in skus[i:i + 500])
        for r in db(f"""select shop_mid||':'||external_id, coalesce(cat_role,''), coalesce(name,'')
                          from products where shop_mid||':'||external_id in ({inl})""") or []:
            if len(r) >= 3:
                cat[r[0]] = (r[1], r[2])
        for r in db(f"select sku, role, coalesce(name,'') from mesh_demand where sku in ({inl})") or []:
            if len(r) >= 3:
                dem[r[0]] = (r[1], r[2])
        for r in db(f"""select shop_mid||':'||external_id, role, coalesce(name,'') from room_catalog
                          where shop_mid||':'||external_id in ({inl})""") or []:
            if len(r) >= 3:
                rooms.setdefault(r[0], []).append((r[1], r[2]))
    room = {s: pick_room_role(v) for s, v in rooms.items()}
    return {s: pick_role(cat.get(s), dem.get(s), room.get(s)) for s in set(cat) | set(dem) | set(room)}


def current_role(sku: str | None, glb: str, roles: dict | None = None) -> tuple[str, str, str]:
    """Текущая роль меша — та, по которой решает `decide`: `role_of` (или готовый `role_index`), пустая/«?» — из
    manifest.json меша (T-36/2)."""
    role, name, subtype = (roles.get(sku) or ('?', '', '')) if roles is not None else role_of(sku)
    if not (role or '').strip() or role == '?':
        role, name = role_from_manifest(glb, name)
    return role, name, subtype


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
    body = {'model': VLM_MODEL, 'max_tokens': VLM_TOKENS_OUT,
            'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': DR._b64(bg, 85)}}]}]}
    req = urllib.request.Request(DR.CHAT_URL, json.dumps(body).encode(),
                                 {'Authorization': 'Bearer ' + DR.gw_key(),
                                  'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read())
        # учёт — тем же журналом, что у остальных платных вызовов (дневной лимит `openai_budget` его видит; T-56/7)
        log_spend(VLM_MODEL, out.get('usage'), 1, f'orient vlm {role}')
        txt = out['choices'][0]['message']['content'] or ''
        m = re.search(r'\{.*\}', txt, re.S)
        d = json.loads(m.group(0))
        return str(d.get('side', '')).lower() or None, float(d.get('confidence', 0))
    except Exception as e:  # noqa: BLE001 — VLM недоступен: остаёмся на vlm_pending
        print(f'  vlm: {str(e)[:80]}', flush=True)
        return None, 0.0


def decide(sku: str, glb: str, inf: dict, use_vlm: bool) -> dict:
    """Каскад для одного меша → resolution dict (status + evidence)."""
    role, name, subtype = current_role(sku, glb)       # NULL/пустая/«?» — из manifest (Codex T-36/2)
    yaw, tilt = front_yaw_from_R(inf['R'])
    res = {'contract': CONTRACT, 'sku': sku, 'glb': os.path.basename(glb),
           'glb_sha': hashlib.sha256(open(glb, 'rb').read()).hexdigest(),
           'raw_to_canonical_quat_wxyz': inf['quat_wxyz'], 'R': inf['R'],
           'canonical_axes': {'front': 'MR-yaw 180', 'up': '+Y'},
           'legacy_front_yaw': yaw, 'up_tilt_deg': tilt, 'role': role,
           'versions': {'orienter': 'cscarv/3d-orienter@main', 'front': 2,
                        'vlm': VLM_MODEL},
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

    if role in BED_ROLES:
        out = apply_headboard(res, headboard_witness(res, glb, inf['R']))
        if out is not None:
            return out
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


def headboard_witness(res: dict, glb: str, R) -> dict:
    """Изголовье по геометрии в каноне решения `R` → вердикт `bed_headboard`; кратко — в evidence.headboard. Рядом — боковая
    спинка (`infer_side_back`, T-20261112-31: угловая модель — только в угол спинкой к стене), `hb['side_back']`."""
    V = HB.canonical_vertices(glb, R)
    hb = HB.infer_headboard(V)
    hb['side_back'] = HB.side_back_brief(HB.infer_side_back(V, hb))
    res.setdefault('evidence', {})['headboard'] = {k: hb.get(k) for k in ('status', 'head_side', 'fix_deg', 'margin', 'xz', 'version',
                                                                          'side_back')}
    return hb


MISMATCH_SOURCES = ('headboard_sideways', 'headboard_flip')   # в привязке — `orientation_mismatch` (жёсткий блок)


def fix_corroborated(hb: dict) -> bool:
    """Доворот изголовья подтверждён ВТОРЫМ признаком — формой: рама вытянута поперёк канона (длинная сторона по X, а у
    кровати она должна идти от изголовья к изножью, по Z), значит поворот на 90° виден и без высот. Разворот на 180° форма
    не подтверждает."""
    return hb.get('status') == 'confident' and hb.get('fix_deg') in (90, 270) and float(hb.get('xz') or 0) > HB.SQUARE[1]


def apply_headboard(res: dict, hb: dict) -> dict | None:
    """Решение кровати по изголовью → новое решение или None (свидетель не уверен — каскад идёт дальше, к VLM).
      confident, поправка 0 → `auto_resolved`, `orienter+headboard_agree`;
      confident, поправка 90/180/270 → матрица каскада доворачивается вокруг вертикали (R' = ry·R: изголовье к +Z канона),
             кватернион и legacy_front_yaw пересчитаны тем же `front_yaw_from_R` → `auto_resolved`, `headboard_fix`; прежнее —
             в evidence.headboard.prev;
      sideways (вытянута поперёк канона, торцы не различить) → `review_pending`, `headboard_sideways`: привязка даёт
             `orientation_mismatch` — жёсткий блок (`room_bindings.orient_only` его не пускает), человек — на /lab/mesh-review."""
    st = hb.get('status')
    if st == 'confident':
        if not hb['fix_deg']:
            return {**res, 'status': 'auto_resolved', 'source': 'orienter+headboard_agree'}
        if not fix_corroborated(hb):
            # разворот без второго признака (180° или почти квадратная рама): по одной высоте торца прод не трогаем —
            # высокое изножье дало бы уверенный ложный разворот (второе мнение Codex, T-20/3). Предложение — в evidence
            return {**res, 'status': 'review_pending', 'source': 'headboard_flip'}
        prev = {'yaw': res.get('legacy_front_yaw'), 'status': res.get('status'), 'source': res.get('source')}
        R = HB.rotate_R(res['R'], hb['fix_deg'])
        out = {**res, 'R': R, 'raw_to_canonical_quat_wxyz': HB.quat_wxyz(R), 'status': 'auto_resolved', 'source': 'headboard_fix'}
        out['legacy_front_yaw'], out['up_tilt_deg'] = front_yaw_from_R(R)
        out['evidence'] = {**res.get('evidence', {}), 'headboard': {**res['evidence']['headboard'], 'prev': prev}}
        return out
    if st == 'sideways':
        return {**res, 'status': 'review_pending', 'source': 'headboard_sideways'}
    return None


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
        tmp = f'{_SHA_CACHE}.{os.getpid()}.tmp'       # целиком или никак: тень и боевой воркер пишут один кэш
        json.dump(_sha16.cache, open(tmp, 'w', encoding='utf-8'))
        os.replace(tmp, _SHA_CACHE)
        _sha16.dirty = False


def state_index() -> tuple[set, set, dict]:
    """(все revision_key, устаревшие по политике ролей, rk → (статус, решение-кратко)) — одним запросом. Смену роли
    товара здесь не судим: текущая роль бывает только из manifest меша, его путь знает `pending_meshes`."""
    rows = db("select revision_key, status, coalesce(resolution->>'source',''), coalesce(resolution->>'role',''), "
              "coalesce(resolution->>'role_policy',''), coalesce(resolution->>'legacy_front_yaw','') "
              "from orientation_state")
    have = {r[0] for r in rows if r and r[0]}
    meta = {r[0]: (r[1], {'source': r[2], 'role': r[3], 'role_policy': r[4],
                          'legacy_front_yaw': r[5] if len(r) >= 6 else ''}) for r in rows if len(r) >= 5}
    stale = {rk for rk, (st, res) in meta.items() if stale_by_role_policy(st, res)}
    return have, stale, meta


def stale_meshes(meta: dict | None = None) -> list[tuple[str, str, str, str, str]]:
    """Ревизии на диске, устаревшие по ролям: (rk, sku, glb, причина `policy|role`, текущая роль). Роль решения
    сравнивается с текущей (`current_role` по `role_index` + manifest) — одно правило `stale_by_role`."""
    if meta is None:
        meta = state_index()[2]
    found = []
    for glb in all_meshes():
        sku = sku_of_glb(glb)
        rk = f'{sku}|{_sha16(glb)}|{CONTRACT}'
        if rk in meta:
            found.append((rk, sku, glb))
    roles = role_index(s for _, s, _ in found)
    out = []
    for rk, sku, glb in found:
        st, res = meta[rk]
        cur = current_role(sku, glb, roles)[0]
        if stale_by_role_policy(st, res):
            out.append((rk, sku, glb, 'policy', cur))
        elif role_changed(st, res, cur):
            out.append((rk, sku, glb, 'role', cur))
    _sha_flush()
    return out


def all_meshes() -> list[str]:
    return sorted(glob.glob(os.path.join(SCENE_DIR, 'meshes', '*.glb'))
                  + glob.glob(os.path.join(SCENE_DIR, 'salad-assets', '*', 'model.glb'))
                  # пилот Hunyuan (план orient-v2): sku на два уровня выше model.glb
                  + glob.glob(os.path.join(SCENE_DIR, 'meshes-hunyuan', 'meshes', 'hunyuan21', 'v2', '*', '*',
                                           'model.glb')))


def sku_of_glb(glb: str) -> str:
    return (sku_from_path(glb) or sku_from_path(os.path.basename(os.path.dirname(glb)))
            or sku_from_path(os.path.basename(os.path.dirname(os.path.dirname(glb)))) or '?')


def pending_meshes(limit: int, recheck_roles: bool = False, stale_only: bool = False) -> list[tuple[str, str, str]]:
    """(rev_key, sku, glb) без записи в orientation_state по текущему контракту; с recheck_roles — ещё и решения,
    устаревшие по ролям (`stale_by_role`: прежняя политика ролей или смена роли товара в любую сторону); stale_only —
    только устаревшие (тень `--shadow`)."""
    have, _, meta = state_index()
    stale = {rk for rk, *_ in stale_meshes(meta)} if (recheck_roles or stale_only) else set()
    out = []
    for glb in all_meshes():
        sku = sku_of_glb(glb)
        sha = _sha16(glb)
        rk = f'{sku}|{sha}|{CONTRACT}'
        if rk in stale or (not stale_only and rk not in have):
            out.append((rk, sku, glb))
        if len(out) >= limit:
            break
    _sha_flush()
    return out


VLM_TOKENS_IN = 420 * 420 // (28 * 28) + 120    # один кадр 420² (патчи 28 px у qwen-vl) + текст промпта
VLM_TOKENS_OUT = 60                               # max_tokens запроса vlm_side


def dry_roles() -> dict:
    """Сухой прогон --recheck-roles: какие устаревшие решения есть на диске, какая роль у них станет и сколько
    вызовов VLM это даст (верхняя граница: сидячим VLM нужен, только если сиденье не уверено), и смены ролей
    «было → стало». Ничего не пишет."""
    _, stale_pol, meta = state_index()
    by_role: dict = {}
    moves: dict = {}
    found = stale_meshes(meta)
    names = role_index(s for _, s, _, _, _ in found)
    for rk, sku, glb, why, role in found:
        _, name, subtype = current_role(sku, glb, names)
        d = directed_role(role, name, subtype)
        c = by_role.setdefault(role, {'meshes': 0, 'directed': 0, 'vlm_max': 0, 'seat_first': 0})
        c['meshes'] += 1
        if d:
            c['directed'] += 1
            c['vlm_max'] += 1
            c['seat_first'] += role in SEAT_ROLES
        if why == 'role':
            old = meta[rk][1].get('role')
            k = f"{old} → {role} ({'направл' if directed_role(old) else 'симм'} → {'направл' if d else 'симм'})"
            moves[k] = moves.get(k, 0) + 1
    tot = {k: sum(c[k] for c in by_role.values()) for k in ('meshes', 'directed', 'vlm_max', 'seat_first')}
    out = {'role_policy': role_policy(), 'stale_policy_in_db': len(stale_pol),
           'role_changed_on_disk': sum(1 for f in found if f[3] == 'role'),
           'role_moves': dict(sorted(moves.items(), key=lambda kv: -kv[1])), 'by_role': by_role, 'total': tot,
           'vlm_tokens_in': tot['vlm_max'] * VLM_TOKENS_IN, 'vlm_tokens_out': tot['vlm_max'] * VLM_TOKENS_OUT,
           'vlm_usd': price_of(VLM_MODEL, tot['vlm_max'] * VLM_TOKENS_IN, tot['vlm_max'] * VLM_TOKENS_OUT)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def overlay_row(res: dict) -> list:
    """Строка индекса решений в формате `topview_render.orient_index` (статус, источник, legacy_front_yaw, отпечаток
    решения, роль). Отпечаток — sha1 JSON (не md5 jsonb из БД): нужен лишь для подписи кэша вида сверху."""
    blob = json.dumps(res, ensure_ascii=False, sort_keys=True)
    return [res.get('status'), res.get('source', ''), float(res.get('legacy_front_yaw') or 0),
            'shadow-' + hashlib.sha1(blob.encode()).hexdigest()[:16], res.get('role') or '']


PUBLISHED_URL = 'https://remont-lab.online/test/mesh-pilot10/orient.json'


def published_orient() -> dict | None:
    """Прод `orient.json` для сторожа поворота. ORIENT_PUBLISHED=<файл> — тест/стенд (пустая строка — «прод пуст»).
    Сеть недоступна — None: тогда сторож сравнивает с прежним решением в БД."""
    p = os.environ.get('ORIENT_PUBLISHED')
    if p is not None:
        return json.load(open(p, encoding='utf-8')) if p else {}
    import urllib.request
    try:
        return json.loads(urllib.request.urlopen(PUBLISHED_URL, timeout=30).read())
    except Exception as e:  # noqa: BLE001
        print(f'[orient] прод orient.json не прочитан ({type(e).__name__}) — сторож поворота по прежнему решению БД',
              flush=True)
        return None


def snap_yaw(y) -> float:
    """Поворот так, как его берёт вид сверху у решённого направленного (`topview_render`: снэп к 90°)."""
    return float(round(float(y or 0) / 90.0) * 90 % 360)


def yaw_guard(res: dict, rk: str, published: dict | None, old: tuple | None) -> dict:
    """Сторож ночного пути (T-20261105-56/6): авто-решение уходит на прод (`publish_merge --only-resolved`) само,
    поэтому направленному авто-решению, которое МЕНЯЕТ уже опубликованный поворот этого же меша, решённым быть нельзя —
    `review_pending` (источник `yaw_change_guard`, кандидат в `guard`), прод держит прежний поворот (нерешённое не
    публикуется), человек смотрит лист. Авто — только если yaw тот же или записи этого меша на проде нет.
    Опубликованная запись «этого же меша» — `orient_sig` прода с тем же sha16 (у старых записей без подписи — считаем
    тем же: безопаснее спросить). Прод не прочитан (None) — сравнение с прежним решённым решением в БД (`old` из
    `state_index`). Симметричные не трогаем: их прод-поворот `orient_policy.publishable` и так не затирает."""
    if res.get('status') != 'auto_resolved' or 'symmetric' in str(res.get('source') or ''):
        return res
    # кровать, довёрнутая изголовьем по геометрии с подтверждением формой (`apply_headboard` → `headboard_fix`), — не догадка
    # VLM: сторож ловит тихие смены от слабого свидетеля, а эта смена и есть исправление опубликованного брака (Лория/Кейла
    # 120 боком, T-20261110-20/3). Согласие изголовья (`orienter+headboard_agree`) сторожа не минует
    if res.get('source') == 'headboard_fix' and fix_corroborated((res.get('evidence') or {}).get('headboard') or {}):
        return res
    sku_, sha16 = rk.split('|')[0].replace(':', '_'), rk.split('|')[1]
    new = snap_yaw(res.get('legacy_front_yaw'))
    ref = None
    if published is not None:
        pub = published.get(sku_) or {}
        sig = str(pub.get('orient_sig') or '').split('|')
        if pub.get('yaw') is not None and (len(sig) < 3 or sig[1] == sha16):
            ref = ('прод', snap_yaw(pub['yaw']))
    elif old and old[0] in ('auto_resolved', 'human_resolved') and str(old[1].get('legacy_front_yaw') or '') != '':
        ref = ('прежнее решение БД', snap_yaw(old[1]['legacy_front_yaw']))
    if ref is None or ref[1] == new:
        return res
    return {**res, 'status': 'review_pending', 'source': 'yaw_change_guard',
            'guard': {'was_source': res.get('source'), 'new_yaw': new, 'ref_yaw': ref[1], 'ref': ref[0],
                      'task': 'T-20261105-56/6'}}


def store(rk: str, sku: str, res: dict, res_dir: str = RES_DIR, to_db: bool = True) -> None:
    """Решение — файлом в `res_dir` и (боевой путь) строкой `orientation_state` (ключ revision_key)."""
    fp = os.path.join(res_dir, rk.replace(':', '_').replace('|', '__') + '.json')
    json.dump(res, open(fp + '.tmp', 'w'), ensure_ascii=False, indent=1)
    os.replace(fp + '.tmp', fp)
    if to_db:
        db(f"""insert into orientation_state (revision_key, sku, status, resolution)
               values ({q(rk)}, {q(sku)}, {q(res['status'])},
                       {q(json.dumps(res, ensure_ascii=False))}::jsonb)
               on conflict (revision_key) do update
                 set status=excluded.status, resolution=excluded.resolution, updated=now()""")


BED_GUARD_CACHE = os.path.join(SCENE_DIR, 'orientation', 'bed-guard-cache.json')


def bed_rows() -> list:
    """Решения кроватей контракта orient-v1 с путём к модели (поколение того же sha16) → [(rk, sku, status, resolution, glb)]."""
    out = []
    for rk, sku, st, txt, path in db(
            "select o.revision_key, o.sku, o.status, o.resolution::text, coalesce(g.path, '-') from orientation_state o "
            "left join lateral (select path from mesh_generations g where g.sku = o.sku "
            "  and g.glb_sha = left(o.resolution->>'glb_sha', 16) limit 1) g on true "
            f"where o.resolution->>'role' in ({', '.join(q(r) for r in BED_ROLES)}) "
            f"and coalesce(o.resolution->>'contract', split_part(o.revision_key, '|', 3)) = {q(CONTRACT)} order by o.sku"):
        glb = os.path.join(path, 'model.glb') if os.path.isdir(path) else path
        out.append((rk, sku, st, json.loads(txt), glb))
    return out


def bed_verdict(st: str, res: dict, hb: dict) -> tuple[str, dict | None]:
    """Что сторож делает с решением кровати → (действие, новое решение | None).
    Решение человека не трогаем никогда (расхождение — в отчёт, `human_conflict`); `unusable` — тоже."""
    if st == 'human_resolved' or res.get('unusable'):
        bad = hb.get('status') == 'sideways' or (hb.get('status') == 'confident' and hb['fix_deg'])
        return ('human_conflict' if bad else 'ok'), None
    new = apply_headboard(res, hb)
    if new is None:
        return 'unsure', None                                  # свидетель не уверен — решение каскада остаётся
    if new['source'] == 'headboard_fix':
        return 'fixed', new
    if new['source'] in MISMATCH_SOURCES:
        return ('blocked', new) if not (st == 'review_pending' and res.get('source') == new['source']) else ('ok', None)
    if st == 'auto_resolved':
        return 'ok', None
    # согласен: нерешённое «VLM не уверен» решено геометрией; прочие причины разбора (сторож поворота, смена роли…) — не наши
    return ('promoted', new) if st == 'review_pending' and res.get('source') == 'vlm_unsure' else ('agree_kept', None)


def bed_guard(apply: bool, out: str | None = None) -> list:
    """СТОРОЖ ИЗГОЛОВЬЯ (T-20261110-20/3) по ВСЕМ решениям кроватей: изголовье по геометрии в каноне решения против решения.
    Разошлось уверенно — решение доворачивается (`headboard_fix`), стоит боком без ясного торца — `headboard_sideways`
    (блок `orientation_mismatch`), нерешённое с уверенным согласием — `orienter+headboard_agree`. Пишет тем же путём, что
    каскад (`store`: файл + `orientation_state`), только с `apply`; дальше обычный путь: вид сверху и `publish_merge
    --only-resolved` → прод `orient.json`, ночная привязка `room_bindings --build`. Решения человека не трогает.
    Кэш по отпечатку решения и версии свидетеля — меш, проверенный тем же решением, заново не грузится."""
    try:
        cache = json.load(open(BED_GUARD_CACHE, encoding='utf-8'))
    except (OSError, ValueError):
        cache = {}
    rows, n = [], {}
    published, meta = published_orient(), state_index()[2]     # тот же сторож поворота, что у каскада (`run`)
    for rk, sku, st, res, glb in bed_rows():
        sig = hashlib.sha1(json.dumps(res, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16] + f'|hb{HB.VERSION}.{HB.SIDE_VERSION}'
        rec = {'rk': rk, 'sku': sku, 'was': {'status': st, 'source': res.get('source'), 'yaw': res.get('legacy_front_yaw')}}
        if cache.get(rk, {}).get('sig') == sig:
            rec.update(action='cached', hb=cache[rk].get('hb'))
        elif 'R' not in res or not os.path.exists(glb):
            rec['action'] = 'no_mesh'
        else:
            work = json.loads(json.dumps(res))
            try:
                hb = headboard_witness(work, glb, res['R'])
            except Exception as e:  # noqa: BLE001 — одна модель не валит сторожа
                rec.update(action='error', error=str(e)[:200])
                hb = None
            if hb is not None:
                action, new = bed_verdict(st, work, hb)
                if new is not None and new['status'] == 'auto_resolved':
                    # смена опубликованного поворота без подтверждения — не на прод (подтверждённый доворот сторож пропускает)
                    guarded = yaw_guard(new, rk, published, meta.get(rk))
                    if guarded.get('source') == 'yaw_change_guard':
                        action, new = 'guarded', None
                rec.update(action=action, hb={k: hb.get(k) for k in ('status', 'head_side', 'fix_deg', 'margin', 'xz', 'side_back')})
                if new is not None:
                    rec['now'] = {'status': new['status'], 'source': new['source'], 'yaw': new.get('legacy_front_yaw')}
                    if apply:
                        store(rk, sku, new)
                if apply:                    # сухой прогон кэш не трогает (он общий с ночным путём)
                    cache[rk] = {'sig': sig if new is None else hashlib.sha1(json.dumps(new, sort_keys=True, ensure_ascii=False)
                                                                           .encode()).hexdigest()[:16] + f'|hb{HB.VERSION}.{HB.SIDE_VERSION}',
                                 'hb': rec['hb']}
        n[rec['action']] = n.get(rec['action'], 0) + 1
        rows.append(rec)
        gc.collect()
    if apply:
        os.makedirs(os.path.dirname(BED_GUARD_CACHE), exist_ok=True)
        json.dump(cache, open(BED_GUARD_CACHE + '.tmp', 'w', encoding='utf-8'), ensure_ascii=False)
        os.replace(BED_GUARD_CACHE + '.tmp', BED_GUARD_CACHE)
    if out:
        json.dump(rows, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for r in rows:
        if r['action'] in ('fixed', 'blocked', 'promoted', 'guarded', 'human_conflict', 'error'):
            print(f"  {r['sku']}: {r['action']} {r['was']} → {r.get('now')} {r.get('hb')}", flush=True)
    print(f"[bed-guard] {'запись' if apply else 'сухо'}: {n}", flush=True)
    return rows


def run(limit: int, use_vlm: bool, recheck_roles: bool = False, shadow: str | None = None) -> None:
    """Пачка каскада. `shadow` — папка тени: только устаревшие по ролям, результаты и `index-overlay.json` туда,
    БД и `orientation/v1` не трогаются (свой замок в папке тени — боевой воркер не блокируется)."""
    res_dir = shadow or RES_DIR
    os.makedirs(res_dir, exist_ok=True)
    lock = open(os.path.join(res_dir if shadow else os.path.join(SCENE_DIR, 'orientation'), 'worker.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('[orient] другой воркер уже работает — выходим', flush=True)
        return
    todo = pending_meshes(limit, recheck_roles, stale_only=bool(shadow))
    if not todo:
        print('[orient] нечего делать', flush=True)
        return
    lst = os.path.join(res_dir, '_batch.txt')
    open(lst, 'w').write('\n'.join(g for _, _, g in todo))
    outp = os.path.join(res_dir, '_batch.json')
    r = subprocess.run(['nice', '-n', '15', ORIENTER_PY,
                        os.path.join(HERE, 'orient_infer.py'), '--list', lst, '--out', outp],
                       capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        print('[orient] infer упал:', r.stderr[-300:], flush=True)
        return
    inf_all = json.load(open(outp))
    # дневной лимит ДО платных вызовов: верхняя граница — по запросу на меш; не влезает — без VLM (vlm_pending), не упасть
    if use_vlm and not allow(VLM_MODEL, len(todo), note=f'orient vlm ≤{len(todo)}'):
        use_vlm = False
    done, overlay = {}, {}
    published = published_orient()
    meta = state_index()[2]
    for rk, sku, glb in todo:
        inf = inf_all.get(glb) or {}
        if 'error' in inf or 'R' not in inf:
            res = {'contract': CONTRACT, 'sku': sku, 'status': 'review_pending',
                   'source': 'infer_error', 'error': inf.get('error', 'нет результата')}
        else:
            try:
                res = yaw_guard(decide(sku, glb, inf, use_vlm), rk, published, meta.get(rk))
            except Exception as e:  # noqa: BLE001 — один меш не валит пакет
                res = {'contract': CONTRACT, 'sku': sku, 'status': 'review_pending',
                       'source': 'cascade_error', 'error': str(e)[:200]}
        store(rk, sku, res, res_dir, to_db=not shadow)
        if shadow:
            overlay[rk] = overlay_row(res)
        done[res['status']] = done.get(res['status'], 0) + 1
        print(f"  {os.path.basename(glb)}: {res['status']} ({res.get('source', '')}) роль {res.get('role', '')}", flush=True)
        # Каскад одного меша (trimesh, рендер) оставляет циклы ссылок: без сборки процесс рос на 70–150 МБ за меш —
        # 3,5 ГБ к 38-му, тень 152 меша снял earlyoom на 6,5 ГБ; с gc.collect() пик 405 МБ на тех же мешах (T-56/6)
        gc.collect()
    if shadow:
        op = os.path.join(shadow, 'index-overlay.json')
        json.dump(overlay, open(op + '.tmp', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        os.replace(op + '.tmp', op)
        print(f'[orient] тень: {len(overlay)} решений → {op} (БД не тронута)', flush=True)
    print(f'[orient] итог: {done}', flush=True)


def report() -> None:
    rows = db("""select status, coalesce(resolution->>'source','?'), count(*)
                   from orientation_state group by 1,2 order by 3 desc""")
    for st, src, n in rows:
        print(f'{st:16s} {src:22s} {n}')


if __name__ == '__main__':
    if '--run' in sys.argv or '--shadow' in sys.argv:
        lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 100
        shd = sys.argv[sys.argv.index('--shadow') + 1] if '--shadow' in sys.argv else None
        run(lim, '--vlm' in sys.argv, '--recheck-roles' in sys.argv or bool(shd), shadow=shd)
    elif '--bed-guard' in sys.argv:
        bed_guard('--apply' in sys.argv, sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None)
    elif '--dry-roles' in sys.argv:
        dry_roles()
    elif '--report' in sys.argv:
        report()
    else:
        print(__doc__)
