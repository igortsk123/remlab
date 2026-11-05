#!/usr/bin/env python3
"""Вид сверху из меша → лёгкий PNG-спрайт для планировщика (план topview-from-mesh).

GLB в браузер не грузим: страница остаётся мгновенной, механика — как со спрайтами
(поворот картинкой). Фронт: решение каскада orient-v1 ИМЕННО для этого GLB (`orientation_state`, ключ
`sku|sha16|orient-v1`) — берётся только скаляр legacy_front_yaw, снэпнутый к 90°, матрица R НЕ применяется
(рендер — сырой меш под этим yaw); у комода/тв-тумбы/тумбы его перебивает фасад (`cabinet_front`); решения
для этого GLB нет — фолбэк на пилотный калибратор (`yaw_for`, иначе 0). Рендер ортографический, сверху,
текстура + мягкий свет, прозрачный фон; supersample ×2 и downscale — против зубцов.
"""
import glob
import json
import os
import time
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

# TOPVIEW_SRC / TOPVIEW_OUT — только для стенда (tests_topview_render.py), боевой путь их не задаёт
SRC = os.environ.get('TOPVIEW_SRC') or os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
OUT = os.environ.get('TOPVIEW_OUT') or os.path.expanduser('~/scout-scenes/mesh-topview')
SHA_CACHE_PATH = os.path.join(OUT, '.sha16-cache.json')
PX = 420          # длинная сторона итогового спрайта


ORIENT_CONTRACT = 'orient-v1'


def orient_index() -> dict:
    """Все решения боевого каскада одним запросом: revision_key → (status, source, legacy_front_yaw, md5 решения).
    Ключ `sku|sha16 GLB|orient-v1` (как пишет `orient_worker.pending_meshes`) — решение берём ТОЧНО для этого GLB.
    Прежнее «последнее по артикулу» (Codex T-36/2): у 318 SKU 375 ревизий наклонной ветки, пересчёт старой ревизии
    делал её «последней» и её поворот ложился на другой GLB. md5 решения — для кэша: решение сменилось → перерисовать."""
    if os.environ.get('TOPVIEW_ORIENT_INDEX'):      # стенд (tests_topview_render.py): готовый индекс из файла
        return {k: tuple(v) for k, v in json.load(open(os.environ['TOPVIEW_ORIENT_INDEX'], encoding='utf-8')).items()}
    r = subprocess.run(['docker', 'exec', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-t', '-A',
                        '-F', '\x1f', '-c',
                        "SELECT revision_key, status, coalesce(resolution->>'source',''), "
                        "coalesce(resolution->>'legacy_front_yaw',''), md5(coalesce(resolution::text,'')) "
                        f"FROM orientation_state WHERE revision_key LIKE '%|{ORIENT_CONTRACT}'"],
                       capture_output=True, text=True, timeout=300)
    out = {}
    for ln in r.stdout.splitlines():
        p = ln.split('\x1f')
        if len(p) == 5 and p[3] != '':
            out[p[0]] = (p[1], p[2], float(p[3]), p[4])
    return out


_SHA_CACHE: dict = {}


def glb_sha16(glb: str) -> str:
    """sha16 файла (тот же, что в ключе ревизии `orient_worker`) с кэшем по (mtime, size) в OUT — без него круг читал
    бы каждый GLB целиком (>1 ГБ). Свой кэш, а не `orientation/sha-cache.json`: стенд не пишет в боевые файлы."""
    import hashlib
    st = os.stat(glb)
    hit = _SHA_CACHE.get(glb)
    if hit and hit[0] == int(st.st_mtime) and hit[1] == st.st_size:
        return hit[2]
    sha = hashlib.sha256(open(glb, 'rb').read()).hexdigest()[:16]
    _SHA_CACHE[glb] = [int(st.st_mtime), st.st_size, sha]
    return sha


def orient_for(sku: str, glb: str, index: dict) -> tuple[str, tuple | None]:
    """(revision_key, решение каскада для ИМЕННО этого GLB или None)."""
    rk = f'{sku}|{glb_sha16(glb)}|{ORIENT_CONTRACT}'
    return rk, index.get(rk)


def orient_sig(rk: str, dec: tuple | None) -> str:
    """Подпись решения для кэша вида сверху: GLB + md5 решения каскада."""
    return f"{rk}|{dec[3] if dec else 'none'}"


def yaw_for(key: str) -> tuple[float, str]:
    r = subprocess.run(['docker', 'exec', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
                        '-t', '-A', '-c',
                        f"SELECT status, resolution FROM orientation_state WHERE revision_key='{key}'"],
                       capture_output=True, text=True).stdout.strip()
    if not r or '|' not in r:
        return 0.0, 'unknown'
    st, res = r.split('|', 1)
    try:
        yaw = float(json.loads(res).get('yaw') or 0)
    except Exception:  # noqa: BLE001
        yaw = 0.0
    return (yaw if st == 'confident' else 0.0), st


def photo_upright_flip(glb: str, cutout_png: str, R=None) -> bool:
    """«Верх» по фото: профиль ширины маски фото (сверху вниз) против профиля меша по
    высоте в двух гипотезах — как есть и перевёрнут. Возвращает True, если перевёрнутая
    заметно лучше. Нужен, когда каскад отверг свой up-детектор (ваза/лампа 99272: identity).
    """
    import numpy as np
    import trimesh
    from PIL import Image
    try:
        cut = np.asarray(Image.open(cutout_png).convert('RGBA'))[..., 3] > 100
        rows = cut.sum(axis=1).astype(float)
        nz = np.where(rows > 0)[0]
        if len(nz) < 10:
            return False
        prof_photo = rows[nz[0]:nz[-1] + 1]
        B = 24
        idx = (np.linspace(0, len(prof_photo) - 1, B)).astype(int)
        prof_photo = prof_photo[idx]
        m = trimesh.load(glb, force='mesh')
        V = np.asarray(m.vertices, np.float32)
        if R is not None:
            V = V @ np.asarray(R, np.float32).T
        lo, hi = V[:, 1].min(), V[:, 1].max()
        ys = (V[:, 1] - lo) / max(hi - lo, 1e-6)
        prof_mesh = np.zeros(B)
        for i in range(B):
            sel = (ys >= i / B) & (ys < (i + 1) / B)
            if sel.sum() >= 6:
                prof_mesh[i] = np.ptp(V[sel][:, 0]) + np.ptp(V[sel][:, 2])
        prof_mesh = prof_mesh[::-1]                     # фото идёт сверху вниз
        def corr(a, b):
            a = (a - a.mean()) / (a.std() + 1e-6)
            b = (b - b.mean()) / (b.std() + 1e-6)
            return float((a * b).mean())
        c_asis = corr(prof_photo, prof_mesh)
        c_flip = corr(prof_photo, prof_mesh[::-1])
        return c_flip > c_asis + 0.10
    except Exception:  # noqa: BLE001 — проверка не должна ронять рендер
        return False


UP_HYPS = {                       # какая ось меша на самом деле «вверх» (пуф лежал на боку)
    'I':    [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    'X180': [[1, 0, 0], [0, -1, 0], [0, 0, -1]],
    'X90':  [[1, 0, 0], [0, 0, -1], [0, 1, 0]],
    'X-90': [[1, 0, 0], [0, 0, 1], [0, -1, 0]],
    'Z90':  [[0, -1, 0], [1, 0, 0], [0, 0, 1]],
    'Z-90': [[0, 1, 0], [-1, 0, 0], [0, 0, 1]],
}


def photo_upright_hyp(glb: str, cutout_png: str, dims: dict | None, R=None) -> str:
    """Выбор «верха» из 6 гипотез: корреляция профиля ширины с фото + соответствие
    пропорций паспорту (h/w различает лежащий пуф). Возвращает ключ UP_HYPS."""
    import numpy as np
    import trimesh
    from PIL import Image
    try:
        cut = np.asarray(Image.open(cutout_png).convert('RGBA'))[..., 3] > 100
        rows = cut.sum(axis=1).astype(float)
        nz = np.where(rows > 0)[0]
        if len(nz) < 10:
            return 'I'
        B = 24
        idx = (np.linspace(nz[0], nz[-1], B)).astype(int)
        prof_photo = rows[idx]
        m = trimesh.load(glb, force='mesh')
        V0 = np.asarray(m.vertices, np.float32)
        if R is not None:
            V0 = V0 @ np.asarray(R, np.float32).T
        d0 = dims or {}
        w, dd, h = d0.get('w'), d0.get('d'), d0.get('h')
        want_hw = (float(h) / float(max(w, dd or w))) if (h and w) else None
        def corr(a, b):
            a = (a - a.mean()) / (a.std() + 1e-6)
            b = (b - b.mean()) / (b.std() + 1e-6)
            return float((a * b).mean())
        best, best_score = 'I', -9
        for name, Rh in UP_HYPS.items():
            V = V0 @ np.asarray(Rh, np.float32).T
            lo, hi = V[:, 1].min(), V[:, 1].max()
            ys = (V[:, 1] - lo) / max(hi - lo, 1e-6)
            prof = np.zeros(B)
            for i in range(B):
                sel = (ys >= i / B) & (ys < (i + 1) / B)
                if sel.sum() >= 6:
                    prof[i] = np.ptp(V[sel][:, 0]) + np.ptp(V[sel][:, 2])
            score = corr(prof_photo, prof[::-1])
            if want_hw is not None:
                got_hw = float((hi - lo) / max(np.ptp(V[:, 0]), np.ptp(V[:, 2]), 1e-6))
                score += 0.5 * max(0.0, 1.0 - abs(got_hw - want_hw) / max(want_hw, 0.2))
            bonus = 0.06 if name == 'I' else 0.0       # гистерезис: не дёргать без нужды
            if score + bonus > best_score:
                best, best_score = name, score + bonus
        # куб/неразличимо (пуф 45³): гипотезы не разделяются — честно «не определено»
        ext = [float(np.ptp(V0[:, i])) for i in range(3)]
        cubish = max(ext) / max(min(ext), 1e-6) < 1.10
        return (best, not cubish)
    except Exception:  # noqa: BLE001
        return ('I', False)


def render_front(glb: str, yaw_deg: float, out_png: str) -> None:
    """Взгляд СПЕРЕДИ по вердикту фронта (владелец 31.08: «фронт не показал») —
    камера чуть сверху (pitch 15°), чтобы читалась форма."""
    import mesh_render as MR
    import numpy as np
    from PIL import Image
    img = MR.render(MR.load_parts(glb), yaw_deg=yaw_deg, pitch_deg=15.0, size=(700, 700))
    a = np.asarray(img)
    ys, xs = np.where(a[..., 3] > 8)
    if len(ys):
        img = img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    w, h = img.size
    k = 320 / max(w, h)
    img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    img.save(out_png)


def render_top(glb: str, yaw_deg: float, out_png: str, R=None, flip=False) -> None:
    """Честный попиксельный рендер (z-buffer + UV) из mesh_render — камера строго сверху.
    Прежний центроидный сэмплинг давал «кляксы» цвета (владелец 31.08)."""
    import mesh_render as MR
    import numpy as np
    from PIL import Image
    parts = MR.load_parts(glb)
    if R is not None:
        Rm = np.asarray(R, np.float32)
        for m in parts:
            m.vertices = np.asarray(m.vertices, np.float32) @ Rm.T
        yaw_deg = 180.0                      # канон фронта боевого контура (MR-yaw 180)
    if flip and flip != 'I':
        Fx = np.asarray(UP_HYPS[flip], np.float32)
        for m in parts:
            m.vertices = np.asarray(m.vertices, np.float32) @ Fx.T
    img = MR.render(parts, yaw_deg=yaw_deg, pitch_deg=90.0, size=(900, 900))
    a = np.asarray(img)
    ys, xs = np.where(a[..., 3] > 8)
    if len(ys):
        img = img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    w, h = img.size
    k = PX / max(w, h)
    img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    img.save(out_png)


def _render_pair(job) -> str:
    """Одна модель для пула процессов: вид сверху + вид спереди."""
    glb, yaw, png, fpng, sku = job
    render_top(glb, yaw, png)
    render_front(glb, yaw, fpng)
    return sku


def render_pool(todo: list, workers: int, per_child: int, deadline: float) -> tuple[int, int, list, bool]:
    """Рендер пачки: НОВЫЙ пул на каждые workers × per_child моделей → (готово, поставлено, сбойные sku, обрыв по бюджету).

    Память: воркер копит +100 МБ на меш (trimesh, урок 391), поэтому живёт не дольше per_child моделей.
    Раньше это делал `ProcessPoolExecutor(max_tasks_per_child=…)`, но на Python 3.14 пул ЗАВИСАЕТ на первой замене
    воркера (T-20261105-36: воспроизводится на пустых заданиях, при fork/forkserver/spawn) — 05.11 волна 2 спальни:
    8 моделей за 22 с, дальше стоял до таймаута шага, манифест не писался. Свежий пул на пачку даёт ту же границу
    памяти без замены воркеров. Бюджет проверяем перед каждой пачкой."""
    import concurrent.futures as _cf
    chunk = max(1, workers * per_child)
    done_ok, submitted, failed, stopped = 0, 0, [], False
    for i in range(0, len(todo), chunk):
        if time.time() > deadline:
            stopped = True
            break
        part = todo[i:i + chunk]
        with _cf.ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_render_pair, job): job[4] for job in part}
            submitted += len(part)
            for f in _cf.as_completed(futs):
                try:
                    f.result()
                    done_ok += 1
                except Exception as e:  # noqa: BLE001 — битый меш не валит остальные
                    print(f'  сбой {futs[f]}: {str(e)[:80]}', flush=True)
                    failed.append(futs[f])
    return done_ok, submitted, failed, stopped


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    manifest = {}
    n = 0
    # АДРЕСНЫЙ ПРОГОН (01.09): TOPVIEW_ONLY="mid_eid mid_eid …" рендерит только
    # перечисленные SKU. Нужен, когда витрина ждёт вид сверху для конкретных предметов,
    # а обычный обход идёт по всему каталогу с бюджетом времени и до них не доходит.
    only = {x.strip().replace(':', '_') for x in
            os.environ.get('TOPVIEW_ONLY', '').replace(',', ' ').split() if x.strip()}
    if only:
        print(f'адресный прогон: {len(only)} SKU', flush=True)
    skip = int(os.environ.get('TOPVIEW_SKIP', 0))
    lim = int(os.environ.get('TOPVIEW_LIMIT', 0)) or None
    # ПРЕДЕЛ НОВЫХ МЕШЕЙ НА ПРОЦЕСС (04.09). Память растёт от НОВЫХ мешей (анализ + рендер), а
    # не от просмотренных: готовые берутся из кэша за копейки. Прежние `skip/limit` считали
    # просмотренные, поэтому 120 новых в одном процессе давали ~10 ГБ (trimesh +100 МБ/меш,
    # урок 391) и earlyoom, а проходы со сдвигом заново начинались с нуля при каждом запуске —
    # хвост каталога до рендера не доживал. Теперь: проход смотрит ВСЁ, берёт не больше
    # TOPVIEW_NEW_CAP новых, выходит; обёртка в batch_show повторяет, пока есть новые.
    new_cap = int(os.environ.get('TOPVIEW_NEW_CAP', 20))
    # БЮДЖЕТ ВРЕМЕНИ (31.08: шаг конвейера убивало по таймауту 45 мин на растущем пилоте —
    # «топ-вью: СБОЙ Terminated», манифест не записывался и работа цикла пропадала).
    # Рендер попиксельный ~30с/модель, кэш по mtime — за несколько циклов догоняем всё.
    budget = float(os.environ.get('TOPVIEW_BUDGET_S', 1800))
    t0 = time.time()
    # КЭШ ГОТОВЫХ ЗАПИСЕЙ (31.08, второй «СБОЙ Terminated»): цикл заново грузил геометрию и
    # считал карты глубины для КАЖДОЙ модели, даже с готовым png — на ~170 моделях лимит
    # шага выгорал ещё до рендера. Готовая пара png+запись берётся из прошлого манифеста.
    prev_man = {}
    try:
        _mp = os.path.join(OUT, 'topview.json')
        if os.path.exists(_mp):
            prev_man = json.load(open(_mp, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        prev_man = {}
    try:
        if os.path.exists(SHA_CACHE_PATH):
            _SHA_CACHE.update(json.load(open(SHA_CACHE_PATH, encoding='utf-8')))
    except Exception:  # noqa: BLE001 — кэш необязателен, пересчитаем
        pass
    index = orient_index()
    print(f'решений каскада ({ORIENT_CONTRACT}): {len(index)}', flush=True)
    stopped_early = False
    todo: list = []
    seen_i = 0
    for mp in sorted(glob.glob(os.path.join(SRC, '*/*/manifest.json'))):
        d = os.path.dirname(mp)
        glb = os.path.join(d, 'model.glb')     # только оригинал (ремонт отменён 01.09)
        if not os.path.exists(glb) or os.path.exists(os.path.join(d, 'owner_reject.json')):
            continue
        man = json.load(open(mp, encoding='utf-8'))
        sku = man['sku'].replace(':', '_')
        if only and sku not in only:
            continue
        if sku in manifest:                          # свежайший каталог уже обработан
            continue
        # канон стратегий: ковры и прочие не-hunyuan виду сверху из МЕША не подлежат —
        # их фото и есть вид сверху (владелец 31.08), спрайт берётся из фото плоскостью
        import asset_strategy as AS
        if AS.strategy(man.get('role')) != 'hunyuan3d':
            continue
        seen_i += 1
        if seen_i <= skip or (lim and seen_i > skip + lim):
            continue
        # БЮДЖЕТ ПРОВЕРЯЕМ В НАЧАЛЕ ЦИКЛА, а не только у рендера: анализ (загрузка меша +
        # карты глубины для фасада) сам по себе тяжёлый, и шаг успевали убить снаружи
        # раньше, чем он печатал хоть строку
        if time.time() - t0 > budget:
            stopped_early = True
            print(f'бюджет {budget:.0f}с исчерпан на анализе — остальное в следующем цикле',
                  flush=True)
            break
        if seen_i % 20 == 0:
            print(f'  ...просмотрено {seen_i}, к рендеру {len(todo)}, {time.time() - t0:.0f}с',
                  flush=True)
        png_c = os.path.join(OUT, f'{sku}.png')
        rk, dec = orient_for(man['sku'], glb, index)
        sig = orient_sig(rk, dec)
        dec_yaw = float(round(dec[2] / 90.0) * 90 % 360) if dec else None
        prev = prev_man.get(sku) or {}
        # КЭШ = свежий png И то же решение каскада (Codex T-36/2: по одному mtime пересчитанное решение не доходило до
        # вида сверху без TOPVIEW_FORCE). Записи до подписи (без orient_sig) — переход без массовой перерисовки:
        # годны, если фронт корпусных взят по фасаду (решение каскада им не важно) или поворот совпадает с решением.
        legacy_ok = ('orient_sig' not in prev and prev.get('yaw') is not None
                     and (str(prev.get('orient', '')).startswith('orient-v1:cabinet_')
                          or (dec_yaw is not None and float(prev['yaw']) == dec_yaw)))
        if (os.environ.get('TOPVIEW_FORCE') != '1' and prev
                and (prev.get('orient_sig') == sig or legacy_ok)
                and os.path.exists(png_c) and os.path.getmtime(png_c) >= os.path.getmtime(glb)):
            manifest[sku] = {**prev, 'orient_sig': sig}   # готово с прошлого цикла — не пересчитываем
            n += 1
            continue
        key = f"{man['sku']}|{(man.get('input') or {}).get('sha') or man.get('source_sha') or ''}|v1"
        if dec is not None:
            # ТОЛЬКО снэпнутый скаляр legacy_front_yaw, матрица R каскада здесь НЕ применяется (владелец 31.08:
            # полный R давал наклоны и «фронт под углом», авто-переворот портил здоровые диваны)
            yaw = dec_yaw
            st = f'{ORIENT_CONTRACT}:{dec[0]}:{dec[1]}'
        else:
            yaw, st = yaw_for(key)
        png = os.path.join(OUT, f'{sku}.png')
        fpng = os.path.join(OUT, f'{sku}.front.png')
        VESSEL = {'ваза', 'кашпо', 'лампа', 'люстра', 'торшер'}
        base_role = (man.get('role') or '').split()[0] if man.get('role') else ''
        ext_ok = True
        try:
            # ДОЧЕРНИЙ ПРОЦЕСС, не `trimesh.load` здесь (04.09): trimesh на плотных Hunyuan-мешах
            # не отдаёт память — +100 МБ на каждый меш в родителе, к сотому — 10 ГБ и earlyoom
            # (урок 391; образец — `mesh_dims.extents`). Дочерний процесс умирает — память возвращается.
            import subprocess as _sp
            _r = _sp.run([sys.executable, '-c',
                          'import sys,json,numpy as np,trimesh;m=trimesh.load(sys.argv[1],force="mesh");'
                          'V=np.asarray(m.vertices);print(json.dumps([float(np.ptp(V[:,k])) for k in range(3)]))',
                          glb], capture_output=True, text=True, timeout=300)
            _e = json.loads(_r.stdout.strip()) if _r.returncode == 0 and _r.stdout.strip() else None
            if _e:
                ext_ok = max(_e) / max(min(_e), 1e-6) >= 1.10
        except Exception:  # noqa: BLE001
            pass
        if base_role in VESSEL or not ext_ok:
            st += ':upright_unsure'
        # корпусная мебель: фронт по деталям фасада (ручки/филёнки) — владелец 31.08
        # «реальная проблема с тв-тумбами и комодами»; сильнее вердикта каскада
        if base_role in {'комод', 'тв-тумба', 'тумба'}:
            try:
                # тоже дочерним процессом — второй полный load меша + карты глубины (04.09)
                import subprocess as _sp
                _r = _sp.run([sys.executable, os.path.join(HERE, 'cabinet_front.py'),
                              '--front-by-depth', glb], capture_output=True, text=True, timeout=300)
                if _r.returncode != 0:
                    raise RuntimeError((_r.stderr or '')[-120:])
                cyaw, csrc = json.loads(_r.stdout.strip().splitlines()[-1])
                if cyaw is not None:
                    yaw = cyaw
                    st = f'orient-v1:{csrc}'
                else:
                    st += ':cabinet_unsure'
            except Exception as _e:  # noqa: BLE001
                print(f'  cabinet_front пропущен {sku}: {str(_e)[:60]}')
        try:
            # кэш: рендер заново, если png отсутствует/старее меша или TOPVIEW_FORCE=1
            # …и если сменился поворот: png рисуется под yaw, свежий по mtime png со старым поворотом — ложь
            need = (os.environ.get('TOPVIEW_FORCE') == '1'
                    or not os.path.exists(png)
                    or os.path.getmtime(png) < os.path.getmtime(glb)
                    or prev.get('yaw') is None or float(prev['yaw']) != float(yaw))
            if need:
                # РЕНДЕР КОПИМ И ГОНИМ ПАРАЛЛЕЛЬНО (владелец 31.08 «не проще ли на ноду
                # Salad?» — замер показал: узкое место не мощность, а один занятый поток
                # из 12; ~6с/модель × 200 = 20 мин в один поток против ~2 мин на пуле)
                todo.append((glb, yaw, png, fpng, sku))
                if new_cap and len(todo) >= new_cap:
                    stopped_early = True
                    print(f'предел {new_cap} новых мешей на процесс — остальное следующим проходом',
                          flush=True)
                    dims = (man.get('input') or {}).get('dims_cm') or {}
                    manifest[sku] = {'png': f'{sku}.png', 'yaw': yaw, 'orient': st, 'orient_sig': sig,
                                     'role': man.get('role'), 'w': dims.get('w'), 'd': dims.get('d')}
                    n += 1
                    break
        except Exception as e:  # noqa: BLE001 — один битый меш не валит страницу
            print(f'  сбой {sku}: {str(e)[:80]}')
            continue
        dims = (man.get('input') or {}).get('dims_cm') or {}
        manifest[sku] = {'png': f'{sku}.png', 'yaw': yaw, 'orient': st, 'orient_sig': sig,
                         'role': man.get('role'), 'w': dims.get('w'), 'd': dims.get('d')}
        n += 1
    if todo:
        # ПАМЯТЬ, А НЕ ЯДРА (01.09): 10 процессов рендера на 8 ГБ машины съедали память, и
        # шаг убивало через ~70с («топ-вью: СБОЙ» посреди прогресса). Урезали до 4 — и в
        # 07:13 шаг УБИЛО СНОВА на 8.86 ГБ (earlyoom), то есть 4 всё ещё много: параллельные
        # рендеры форкаются от уже нагруженного родителя. Держим 2 и оставляем запас
        # конвейеру, который работает параллельно.
        # 04.09: на 11 ГБ dev-VM держим ОДИН процесс рендера (Codex №8) и меняем его каждые
        # TOPVIEW_TASKS_PER_CHILD задач — воркер, живущий всю пачку, копит те же +100 МБ/меш.
        # 05.11: «меняем» = новый пул на пачку (render_pool), не max_tasks_per_child — тот зависает на 3.14.
        workers = int(os.environ.get('TOPVIEW_WORKERS', 0)) or 1
        per_child = int(os.environ.get('TOPVIEW_TASKS_PER_CHILD', 0)) or 4
        print(f'рендер: {len(todo)} моделей на {workers} процессах (смена каждые {per_child})', flush=True)
        done_ok, submitted, failed, cut = render_pool(todo, workers, per_child, t0 + budget)
        for sku_j in failed:
            manifest.pop(sku_j, None)
        stopped_early = stopped_early or cut
        if stopped_early:
            print(f'бюджет {budget:.0f}с исчерпан — остальное в следующем цикле', flush=True)
        print(f'отрендерено {done_ok} из {submitted}', flush=True)
        for job in todo[submitted:]:      # не поставленные в очередь — не в манифест
            manifest.pop(job[4], None)
    mpth = os.path.join(OUT, 'topview.json')
    # частичный прогон ДОПОЛНЯЕТ манифест, а не затирает: skip/limit, выход по бюджету и АДРЕСНЫЙ прогон
    # (TOPVIEW_ONLY видит только свои SKU — 05.11 адресный прогон 49 SKU без обрыва переписал весь манифест,
    # 236 КБ → 11 КБ, T-20261105-36). Целиком переписывает только полный обход каталога.
    if os.path.exists(mpth) and (only or skip or lim or stopped_early):
        base = json.load(open(mpth, encoding='utf-8'))
        base.update(manifest)
        manifest = base
    tmp_m = mpth + '.tmp'
    with open(tmp_m, 'w', encoding='utf-8') as fh:   # целиком или никак: читатели (сборка демо) не видят полфайла
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    os.replace(tmp_m, mpth)
    try:
        tmp_s = SHA_CACHE_PATH + '.tmp'
        json.dump(_SHA_CACHE, open(tmp_s, 'w', encoding='utf-8'))
        os.replace(tmp_s, SHA_CACHE_PATH)
    except OSError as e:
        print(f'  кэш sha16 не записан: {e}', flush=True)
    print(f'видов сверху: {n}{" (частично, бюджет)" if stopped_early else ""} → {OUT}')
    print(f'TOPVIEW_NEW {len(todo)}', flush=True)     # сколько НОВЫХ взял этот проход — читает обёртка


if __name__ == '__main__':
    main()
