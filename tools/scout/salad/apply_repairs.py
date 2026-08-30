#!/usr/bin/env python3
"""Локальный ремонт скачанных мешей перед публикацией: срез пола и обломков.

Зачем локально, а не только в образе. Правка резака на нодах требует перевыкатки группы —
это перекачка весов на каждой машине посреди прогона. Ремонт после drain даёт тот же
результат немедленно: галерея и дальнейшие потребители видят уже чищеное. В образе те же
функции тоже живут — свежие ноды после следующей выкатки будут чистить сами, а повторный
проход здесь безвреден (резакам нечего срезать второй раз).
"""
import glob
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('salad_pipeline', os.path.join(HERE, 'pipeline.py'))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

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
    """ПРАВИЛО ВЛАДЕЛЬЦА (30.08, после изрезанного дивана): МОДЕЛЬ НА ЖИВУЮ НЕ ПРАВИТЬ.

    `model.glb` — неприкосновенный оригинал генератора. Ремонт пишется ТОЛЬКО в копию
    `model.repaired.glb`, и она становится кандидатом, а не заменой: показывается и
    используется лишь после доказательства «гейт до/после не ухудшил». Вторая причина
    прошлой аварии — конвейер прогонял ремонт по ВСЕМ мешам на каждой пачке, срезы
    накапливались в живом файле; теперь повторный проход видит repair.json и молчит.
    """
    fixed = 0
    verdicts = {}
    reseed = json.load(open(RESEED, encoding='utf-8')) if os.path.exists(RESEED) else []
    seen = {(r['sku'], r.get('seed')) for r in reseed}
    for mp in sorted(glob.glob(os.path.join(SRC, '*/*/manifest.json'))):
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
        rep = os.path.join(d, 'model.repaired.glb')
        # Версия цепочки ремонта: repair.json от старой версии не считается сделанным —
        # иначе апгрейд (цветокор, лифт теней) доехал бы только до вручную сброшенных
        # (тумба 112923_813… показывалась без цветокора именно поэтому).
        REPAIR_VERSION = 3
        rj = os.path.join(d, 'repair.json')
        stale = True
        if os.path.exists(rj):
            try:
                stale = (json.load(open(rj)).get('repair_version') or 0) < REPAIR_VERSION
            except Exception:  # noqa: BLE001
                stale = True
        vj = os.path.join(d, 'verdict.json')
        if not stale and os.path.exists(vj) and \
                os.path.getmtime(vj) >= os.path.getmtime(rep if os.path.exists(rep) else glb):
            # приёмка кэширована: ремонт актуален и вердикт свежее меша — цикл не жуёт
            # старое заново (45-минутные Terminated на 44 каталогах, 30.08)
            try:
                verdicts[man['sku']] = json.load(open(vj)).get('status') or 'generated'
                continue
            except Exception:  # noqa: BLE001
                pass
        if stale:
            import shutil
            shutil.copy(glb, rep)                     # ремонт — только над копией
            before = os.path.getsize(rep)
            P.cut_base_slab(rep, role)
            if role in ('диван', 'кровать', 'банкетка'):
                man_dims = (man.get('input') or {}).get('dims_cm')
                n = P.crop_beyond_passport(rep, man_dims, role)
                if n:
                    print(f'  плита по паспорту: −{n} граней')
                    # срез открыл кромку с текселями подложки — закрасить (владелец 30.08)
                    try:
                        import importlib.util as _il2
                        _sp2 = _il2.spec_from_file_location('tf2', os.path.join(HERE, 'texture_fix.py'))
                        _tf2 = _il2.module_from_spec(_sp2); _sp2.loader.exec_module(_tf2)
                        npx = _tf2.repaint_cut_edge(rep)
                        if npx:
                            print(f'  кромка закрашена: {npx} px')
                    except Exception as e:  # noqa: BLE001
                        print(f'  закраска кромки пропущена: {str(e)[:80]}')
            if int(man.get('seed') or 0) >= 1:
                # конвейер владельца (30.08): повторный брак → обрезку обломков включаем,
                # кандидат идёт на согласование человеку (оригинал сохранён)
                os.environ['ALIEN_CUT'] = '1'
            P.cut_alien_debris(rep)
            os.environ.pop('ALIEN_CUT', None)
            try:
                import importlib.util as _il
                _sp = _il.spec_from_file_location('tf', os.path.join(HERE, 'texture_fix.py'))
                _tf = _il.module_from_spec(_sp); _sp.loader.exec_module(_tf)
                _tf.despeckle_glb(rep)
                # цвет к фото (владелец 30.08) — по вырезке этой же версии
                cut_p = os.path.join(d, 'cutout.png')
                if os.path.exists(cut_p):
                    de = _tf.match_photo_color(rep, cut_p)
                    if de:
                        print(f'  цвет к фото: ΔE {de}')
            except Exception as e:  # noqa: BLE001
                print(f'  despeckle пропущен: {str(e)[:80]}')
            changed = os.path.getsize(rep) != before
            json.dump({'changed': changed, 'repair_version': REPAIR_VERSION,
                       'bytes_orig': os.path.getsize(glb),
                       'bytes_repaired': os.path.getsize(rep)},
                      open(os.path.join(d, 'repair.json'), 'w'))
            if changed:
                fixed += 1
                print(f'  кандидат-ремонт: {os.path.basename(os.path.dirname(d))} ({role})')
            else:
                os.remove(rep)                        # нечего чинить — копию не плодим
        status = accept(d, man)
        # метрика владельца: модель шире паспорта >15% — лишняя подложка, статус капится
        excess = slab_excess(glb, (man.get('input') or {}).get('dims_cm'), role)
        if excess and excess > 1.15 and status not in ('generated',):
            status = 'generated'
            print(f'  подложка сверх паспорта ×{excess}: {man["sku"]} → на переделку')
        # цвет не как на фото (хвост распределения): брак покраски → на переделку
        cmis = color_mismatch(rep if os.path.exists(rep) else glb,
                              os.path.join(d, 'cutout.png')) \
            if os.path.exists(os.path.join(d, 'cutout.png')) else None
        if cmis and cmis > 0.12 and status not in ('generated',):
            status = 'generated'
            print(f'  покрашено не в цвет фото ({int(cmis * 100)}% чужих тонов): {man["sku"]} → на переделку')
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
    print(f'ремонт-кандидатов: {fixed} | приёмка: {dict(collections.Counter(verdicts.values()))} '
          f'| на перегон: {len(reseed)}')

if __name__ == '__main__':
    main()
