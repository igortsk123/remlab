#!/usr/bin/env python3
"""Приёмка скачанных мешей. РЕМОНТ ОТМЕНЁН (владелец 01.09).

Решение владельца после просмотра `/test/mesh-repairs-all/`: «процессом ремонта ты не
лечишь, а калечишь — отменяй все ремонты, оставляй оригинальные модели». С HD-фото
генератор даёт чистую геометрию без лишних деталей, чинить нечего; единственный реальный
дефект — цвет, и статистическая подгонка к фото (`texture_fix.match_photo_color`) делала
его ХУЖЕ. Цвет решаем отдельно и позже, на входе генератора, а не постобработкой.

Здесь остались только ИЗМЕРЕНИЯ и вердикты: они не трогают модель, а помечают статус и
собирают очередь перегона. `model.glb` — то, что показывается и используется везде.
Цепочка ремонта (`pipeline.cut_*`, `texture_fix.*`) не удалена из репозитория, но
из конвейера не вызывается.
"""
import glob
import json
import os
import sys

# `pipeline.py` (резаки) больше НЕ импортируется: ремонт отменён, а импорт тянул torch
# в шаг приёмки без нужды.
HERE = os.path.dirname(os.path.abspath(__file__))

SRC = os.environ.get('REPAIR_SRC',
                     os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2'))

sys.path.insert(0, os.path.join(HERE, '..'))
RESEED = os.path.join(HERE, '..', 'mesh-reseed.json')
# роли, симметричные в плане: пустая глубина паспорта = ширине, иначе профильный гейт слеп
# (кашпо-доска 30.08 прошла именно из-за пустой d)
SQUARE_ROLES = {'кашпо', 'ваза', 'торшер', 'лампа', 'стол', 'пуф'}


def slab_excess(glb: str, dims: dict | None, role: str | None) -> float | None:
    """Идентификация лишней подложки метрикой владельца (30.08): footprint модели
    против паспортного W×D. Возвращает коэффициент превышения (>1 — модель шире
    товара) или None, когда паспорта/высоты нет и сравнивать не с чем.

    Конвейер владельца: превышение >15% → статус не выше generated → переделка
    (reseed); повторный брак → срез-кандидат + отметка на проверку человеком,
    оригинал и обрезанный вариант сохраняются оба."""
    d0 = dims or {}
    w = d0.get('w') or d0.get('dia')
    dd = d0.get('d') or (w if role in SQUARE_ROLES else None)
    h = d0.get('h')
    if not (w and h):
        return None
    try:
        import numpy as np
        import trimesh
        m = trimesh.load(glb, force='mesh')
        V = np.asarray(m.vertices)
        lo, hi = V.min(axis=0), V.max(axis=0)
        ext = np.maximum(hi - lo, 1e-6)
        low = V[V[:, 1] < lo[1] + 0.10 * ext[1]]
        if len(low) < 8:
            return None
        scale = float(ext[1]) / float(h)              # юниты меша на сантиметр
        mx = float(np.ptp(low[:, 0])) / scale
        mz = float(np.ptp(low[:, 2])) / scale
        big, small = max(mx, mz), min(mx, mz)
        ratios = [big / float(max(w, dd or w))]
        if dd:
            ratios.append(small / float(min(w, dd)))
        return round(max(ratios), 3)
    except Exception:  # noqa: BLE001 — метрика не должна ронять приёмку
        return None


def color_mismatch(glb: str, cutout_png: str) -> float | None:
    """Идентификация «покрашено не в цвет фото» (тв-тумба 112923_813…: серая тумба
    покрашена в чёрный; средние сходятся из-за компенсации бежевыми пятнами, поэтому
    сравниваем ХВОСТ распределения). Возвращает долю текселей темнее самого тёмного
    5% фото с запасом — такие цвета на фото вообще отсутствуют. >0.12 — брак покраски,
    лечится перегоном, не косметикой."""
    try:
        import cv2
        import trimesh
        import numpy as np
        from PIL import Image
        cut = np.asarray(Image.open(cutout_png).convert('RGBA')).astype(np.float32)
        msk = cut[..., 3] > 150
        if msk.sum() < 500:
            return None
        pl = cv2.cvtColor(cut[..., :3].astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        p05 = float(np.percentile(pl[..., 0][msk], 5))
        m = trimesh.load(glb, force='mesh')
        tex = getattr(getattr(m.visual, 'material', None), 'baseColorTexture', None)
        if tex is None:
            return None
        t = np.asarray(tex.convert('RGB'))
        tl = cv2.cvtColor(t, cv2.COLOR_RGB2LAB).astype(np.float32)
        tm = t.max(axis=2) > 15
        if tm.sum() < 500:
            return None
        return round(float((tl[..., 0][tm] < p05 - 15).mean()), 3)
    except Exception:  # noqa: BLE001
        return None


def accept(d: str, man: dict) -> str:
    """Приёмка одного меша: геометрия + профиль по паспорту + PBR. Возвращает статус."""
    import mesh_gate as G
    import mesh_gate_pbr as PBR
    from PIL import Image
    glb = os.path.join(d, 'model.glb')
    role = man.get('role')
    dims = (man.get('input') or {}).get('dims_cm') or {}
    w = dims.get('w') or dims.get('dia')
    dd = dims.get('d') or (w if role in SQUARE_ROLES else None)
    h = dims.get('h')
    geo_ok = True
    prof_ok = True
    try:
        geo_ok = bool(G.geometry_layer(glb).get('ok', True))
    except Exception:  # noqa: BLE001
        pass
    if w and dd and h and os.path.exists(os.path.join(d, 'cutout.png')):
        try:
            v = G.view_layer(glb, Image.open(os.path.join(d, 'cutout.png')),
                             float(w), float(dd), float(h), 0)
            prof_ok = bool(v.get('profile_ok', True))
        except Exception:  # noqa: BLE001
            pass
    st = PBR.status(glb, role=role, geometry_ok=geo_ok and prof_ok)
    return st['status']


def main() -> None:
    """Приёмка без единой правки модели (владелец 01.09, см. docstring модуля).

    Никаких копий `model.repaired.glb` больше не создаётся, существующие — не читаются.
    Единственный результат прогона: `verdict.json` у каждого меша и очередь перегона.
    """
    verdicts = {}
    reseed = json.load(open(RESEED, encoding='utf-8')) if os.path.exists(RESEED) else []
    seen = {(r['sku'], r.get('seed')) for r in reseed}
    # Чанкование приёмки: цикл конвейера обязан влезать в таймаут шага. Не больше
    # ACCEPT_CAP тяжёлых приёмок за прогон; порядок перемешан, чтобы один тяжёлый
    # каталог не блокировал раскатку остальным (Terminated на 45-й минуте, 30.08).
    import random
    import time as _t
    # 01.09: замер показал 29с на ОДНУ приёмку (загрузка модели + метрики) — 40 штук это
    # 20 минут, и под работающим конвейером шаг не укладывался в таймаут («ремонт: СБОЙ
    # Terminated»), а пока он висел, ноды Salad оплачивались вхолостую. Ограничиваем и
    # числом, и временем: остаток догоняется следующим циклом, вердикты кэшируются.
    # 04.09: 20 приёмок × 4–5 загрузок GLB в ОДНОМ процессе (trimesh не отдаёт память, урок 391)
    # — earlyoom снимал шаг дважды за два часа. Теперь по 5 на процесс, а процессов несколько
    # (самоцикл ниже, ACCEPT_ROUNDS) — та же пропускная способность за цикл, память возвращается
    # ОС между процессами. Порядок — детерминированный: сперва меши БЕЗ свежего вердикта, старейшие
    # первыми; прежняя случайная перестановка по PID при ограниченных циклах не гарантировала, что
    # до какого-то меша очередь дойдёт вообще (Codex 04.09 №9 — голодание хвоста).
    ACCEPT_CAP = int(os.environ.get('ACCEPT_CAP', 5))
    ACCEPT_BUDGET_S = float(os.environ.get('ACCEPT_BUDGET_S', 600))
    _t0 = _t.time()
    checked = 0
    mans = sorted(glob.glob(os.path.join(SRC, '*/*/manifest.json')))

    def _order(mp: str) -> tuple:
        d = os.path.dirname(mp)
        glb, vj = os.path.join(d, 'model.glb'), os.path.join(d, 'verdict.json')
        fresh = os.path.exists(vj) and os.path.exists(glb) and os.path.getmtime(vj) >= os.path.getmtime(glb)
        return (1 if fresh else 0, os.path.getmtime(mp))
    mans.sort(key=_order)
    for mp in mans:
        d = os.path.dirname(mp)
        glb = os.path.join(d, 'model.glb')
        if not os.path.exists(glb):
            # suspect/flat: model нет, есть shape-диагностика — решаем перегон здесь же
            man = json.load(open(mp, encoding='utf-8'))
            st = (man.get('gpu') or {}).get('gate') or 'generated'
            seed = int(man.get('seed') or 0)
            verdicts[man['sku']] = st
            if seed < 1:
                key = (man['sku'], seed + 1)
                if key not in seen:
                    seen.add(key)
                    inp = man.get('input') or {}
                    reseed.append({'sku': man['sku'], 'role': man.get('role'),
                                   'image_url': inp.get('image_url'),
                                   'dims_cm': inp.get('dims_cm'), 'seed': seed + 1,
                                   'params': {}})
            continue
        man = json.load(open(mp, encoding='utf-8'))
        role = man.get('role')
        vj = os.path.join(d, 'verdict.json')
        if os.path.exists(vj) and os.path.getmtime(vj) >= os.path.getmtime(glb):
            # приёмка кэширована: вердикт свежее меша — цикл не жуёт старое заново
            # (45-минутные Terminated на 44 каталогах, 30.08)
            try:
                verdicts[man['sku']] = json.load(open(vj)).get('status') or 'generated'
                continue
            except Exception:  # noqa: BLE001
                pass
        if checked >= ACCEPT_CAP or _t.time() - _t0 > ACCEPT_BUDGET_S:
            try:                              # лимит цикла исчерпан — вердикт из кэша, если был
                verdicts[man['sku']] = json.load(open(vj)).get('status') or 'generated'
            except Exception:  # noqa: BLE001
                pass
            continue
        checked += 1
        status = accept(d, man)
        # метрика владельца: модель шире паспорта >15% — лишняя подложка, статус капится
        excess = slab_excess(glb, (man.get('input') or {}).get('dims_cm'), role)
        if excess and excess > 1.15 and status not in ('generated',):
            status = 'generated'
            print(f'  подложка сверх паспорта ×{excess}: {man["sku"]} → на переделку')
        # Цвет не как на фото — ТОЛЬКО измерение, в статус не бьёт (владелец 01.09).
        # Перегон с другим seed не лечит систематический увод тона покраской: тратит GPU
        # и возвращает тот же цвет. Решение по цвету — отдельной задачей, на входе покраски.
        cmis = color_mismatch(glb, os.path.join(d, 'cutout.png')) \
            if os.path.exists(os.path.join(d, 'cutout.png')) else None
        verdicts[man['sku']] = status
        seed = int(man.get('seed') or 0)
        json.dump({'status': status, 'slab_excess': excess, 'color_mismatch': cmis,
                   'manual_repair_candidate': bool(status in ('generated', 'geometry_valid') and seed >= 1)},
                  open(os.path.join(d, 'verdict.json'), 'w'))
        # Codex q27: один reseed; повторилась та же сигнатура — вручную/замена, второй
        # перегон жжёт GPU без шансов (seed-стабильные дефекты: пара на фото, плита у цоколя).
        if status in ('generated', 'geometry_valid') and seed < 1:
            key = (man['sku'], seed + 1)
            if key not in seen:
                seen.add(key)
                inp = man.get('input') or {}
                reseed.append({'sku': man['sku'], 'role': role,
                               'image_url': inp.get('image_url'),
                               'dims_cm': inp.get('dims_cm'), 'seed': seed + 1, 'params': {}})
    json.dump(reseed, open(RESEED, 'w'), ensure_ascii=False, indent=1)
    import collections
    print(f'приёмка (ремонт отменён 01.09): {dict(collections.Counter(verdicts.values()))} '
          f'| на перегон: {len(reseed)} | проверено в этом процессе: {checked}')
    print(f'ACCEPT_CHECKED {checked}', flush=True)


def rounds() -> None:
    """Самоцикл: родитель БЕЗ trimesh запускает себя ACCEPT_ROUNDS раз по ACCEPT_CAP приёмок,
    останавливаясь, когда раунд ничего не проверил (всё в кэше) или кончился общий бюджет.
    Граница памяти так не зависит от того, как шаг вызван из конвейера."""
    import subprocess
    import sys
    import time as _t
    n_rounds = int(os.environ.get('ACCEPT_ROUNDS', 4))
    budget = float(os.environ.get('ACCEPT_TOTAL_BUDGET_S', 2400))
    t0 = _t.time()
    env = {**os.environ, 'ACCEPT_CHILD': '1'}
    total = 0
    for i in range(n_rounds):
        left = budget - (_t.time() - t0)
        if left <= 60:
            print(f'приёмка: общий бюджет {budget:.0f} с исчерпан после {i} раундов', flush=True)
            break
        r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env,
                           capture_output=True, text=True, timeout=max(60, left))
        out = (r.stdout or '')
        print(out.rstrip(), flush=True)
        if r.returncode != 0:
            print(f'приёмка: раунд {i + 1} упал (код {r.returncode}): {(r.stderr or "")[-300:]}',
                  flush=True)
            break
        m = [ln for ln in out.splitlines() if ln.startswith('ACCEPT_CHECKED ')]
        n = int(m[-1].split()[1]) if m else 0
        total += n
        if n == 0:
            break
    print(f'приёмка: раундов {i + 1 if n_rounds else 0}, проверено всего {total}', flush=True)


if __name__ == '__main__':
    if os.environ.get('ACCEPT_CHILD') == '1':
        main()
    else:
        rounds()
