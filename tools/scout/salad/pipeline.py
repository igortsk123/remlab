"""Hunyuan3D 2.1: форма → выгрузка → PBR-текстура, с замером памяти и времени по стадиям.

ГЛАВНОЕ РЕШЕНИЕ — СТАДИЙНОСТЬ. Официальные требования 2.1: форма 10 ГБ VRAM, покраска 21 ГБ,
обе модели одновременно 29 ГБ. Публичные замеры «139 с на модель» получены на 24-гиговой
4090, где обе модели держат в памяти и система вынуждена выгружать веса в RAM.
Если выгружать форму ПЕРЕД покраской, пик равен 21 ГБ и укладывается в 24 ГБ без offload.
Это гипотеза, которую пилот обязан проверить измерением, поэтому режим переключаемый
(`STAGED=0/1`) и обе стадии инструментированы: без парного замера вывод сделать нельзя.

Времена и пики пишутся в манифест каждого ассета — из них потом считается не «цена за
генерацию», а цена за ГОДНЫЙ ассет с учётом всех попыток.
"""
import gc
import os
import time

import torch

STAGED = os.environ.get('STAGED', '1') == '1'
WEIGHTS = os.environ.get('WEIGHTS_DIR', '/opt/weights')
MODEL_PATH = os.path.join(WEIGHTS, 'hunyuan3d-2.1')

_SHAPE = None
_PAINT = None


def _peak_gb() -> float:
    return round(torch.cuda.max_memory_allocated() / 2 ** 30, 2)


def _free():
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()


HY_ROOT = os.environ.get('HY_ROOT', '/opt/hunyuan')


def _fix_torchvision():
    """Апстрим кладёт рядом `torchvision_fix` и просит применить его до импортов — иначе
    на свежих torchvision ломается загрузка их трансформов. Молча пропустить нельзя:
    падение будет далеко от причины."""
    try:
        from torchvision_fix import apply_fix
        apply_fix()
    except Exception:  # noqa: BLE001 — модуля нет: работаем как есть, как и в их demo.py
        pass


def shape_pipeline():
    """Импорты и вызовы — как в `demo.py` апстрима, не по догадке.

    `from_pretrained` принимает путь к КОРНЮ набора весов и сам находит подпапку
    `hunyuan3d-dit-v2-1`; передача subfolder вручную ломается на их загрузчике.
    """
    global _SHAPE
    if _SHAPE is None:
        _fix_torchvision()
        from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
        _SHAPE = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(MODEL_PATH)
    return _SHAPE


def paint_pipeline():
    """`textureGenPipeline` лежит в корне hy3dpaint и импортируется верхним уровнем
    (hy3dpaint в PYTHONPATH), а не как `hy3dpaint.textureGenPipeline`.

    Пути конфигов задаются явно и абсолютно: апстрим пишет их относительно корня
    репозитория, и при запуске из другого каталога пайплайн не находит ни ppbr-конфиг,
    ни чекпойнт RealESRGAN.
    """
    global _PAINT
    if _PAINT is None:
        from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline
        cfg = Hunyuan3DPaintConfig(int(os.environ.get('MAX_NUM_VIEW', 6)),
                                   int(os.environ.get('PAINT_RESOLUTION', 512)))
        cfg.realesrgan_ckpt_path = os.path.join(HY_ROOT, 'hy3dpaint/ckpt/RealESRGAN_x4plus.pth')
        cfg.multiview_cfg_path = os.path.join(HY_ROOT, 'hy3dpaint/cfgs/hunyuan-paint-pbr.yaml')
        cfg.custom_pipeline = os.path.join(HY_ROOT, 'hy3dpaint/hunyuanpaintpbr')
        _PAINT = Hunyuan3DPaintPipeline(cfg)
    return _PAINT


def _unload(name: str):
    """Выгрузка стадии. Без явного удаления ссылок и сборки мусора VRAM не возвращается —
    и весь смысл стадийности теряется."""
    global _SHAPE, _PAINT
    if name == 'shape':
        _SHAPE = None
    else:
        _PAINT = None
    _free()


# Роли, у которых у пола НЕ бывает родных горизонтальных плоскостей: тут плита — всегда
# артефакт. У стеллажей/тумб/кашпо плита неотличима от нижней полки или днища (пробный
# прогон 30.08 отрезал бы куски у двух товаров) — там резак выключен, брак ловит приёмка
# и лечит повтор с другим seed.
# ТОЛЬКО кресло/стул (Codex q26): у диванов/кроватей/банкеток бывают законные цоколи и
# коробчатые основания — там плиту не отличить, лечит перегон.
SLAB_ROLES = {'кресло', 'стул'}


class FlatShape(Exception):
    """Форма — плоская доска: покраску не запускаем, деньги на неё не тратим."""


class SlabSuspect(Exception):
    """Плита-«пол» у НЕсрезаемой роли (тумба/диван): покраску не тратим, решает перегон.

    Codex q28: у тумб плита в 3/3 генераций, автосрез запрещён (цоколь неотличим) —
    единственная экономия это не красить брак: paint — половина стоимости задания."""


def crop_beyond_passport(glb_path: str, dims: dict | None, role: str | None = None) -> int:
    """Нож по формуле владельца (30.08, финал): «скачок толщины со всех сторон — начало
    объекта». Всё, что ЦЕЛИКОМ вне контура тела — артефакт, режется на любой высоте
    (кольцо-обод плиты доходило до 0.76 высоты и выживало под порогом). Внутри контура не
    трогаем НИЧЕГО — дно родное (прошлая версия паспортной рамкой срезала 79% дна: рамка
    оказалась уже тела). Паспорт — только проверка масштаба, не нож.

    Контур: карта максимальных высот сверху (сэмплы по ГРАНЯМ — по вершинам дырявила тело),
    порог тело/плита из скачка профиля толщины, сглаживание гауссом.
    """
    d0 = dims or {}
    w, d, h = d0.get('w') or d0.get('dia'), d0.get('d') or d0.get('dia'), d0.get('h')
    try:
        import numpy as np
        import trimesh
        from scipy import ndimage as _ndi
        m = trimesh.load(glb_path, force='mesh')
        if m.faces is None or len(m.faces) < 500:
            return 0
        V, F = np.asarray(m.vertices), np.asarray(m.faces)
        lo, hi = V.min(axis=0), V.max(axis=0)
        ext = np.maximum(hi - lo, 1e-6)
        fv = V[F]
        # профиль толщины: есть ли вообще плита (переход ≥1.6х в нижних 20%)
        bins = 40
        ys = (V[:, 1] - lo[1]) / ext[1]
        prof = np.zeros(bins)
        for i in range(bins):
            sel = (ys >= i / bins) & (ys < (i + 1) / bins)
            if sel.sum() >= 8:
                p2 = V[sel]
                prof[i] = float((p2[:, 0].max() - p2[:, 0].min()) *
                                (p2[:, 2].max() - p2[:, 2].min()))
        band_frac = None
        for i in range(max(2, int(bins * 0.20))):
            a2, b2 = prof[i], prof[i + 1] if i + 1 < bins else 0
            if a2 > 0 and b2 > 0 and a2 / b2 >= 1.6:
                band_frac = (i + 1) / bins
                break
        if band_frac is None:
            return 0                                   # перехода нет — плиты нет, не режем
        # КОНТУР ТЕЛА — РАСТЕРИЗАЦИЕЙ ТРЕУГОЛЬНИКОВ (не сэмплами: у крупных плоских
        # граней точек мало, маска дырявела и нож резал тело — упало 78%→36% дна).
        # Растеризуем в маску все грани, чей верх выше порога тело/плита.
        G = 256
        thr = lo[1] + min(max(2.0 * band_frac, 0.10), 0.20) * ext[1]
        high = fv[:, :, 1].max(axis=1) > thr
        body = np.zeros((G, G), bool)
        tx = (fv[high][:, :, 0] - lo[0]) / ext[0] * (G - 1)
        tz = (fv[high][:, :, 2] - lo[2]) / ext[2] * (G - 1)
        for t2x, t2z in zip(tx, tz):
            x0, x1 = int(t2x.min()), int(np.ceil(t2x.max()))
            z0, z1 = int(t2z.min()), int(np.ceil(t2z.max()))
            if x1 - x0 <= 1 and z1 - z0 <= 1:
                body[max(0, x0):x1 + 1, max(0, z0):z1 + 1] = True
                continue
            gx, gz = np.meshgrid(np.arange(x0, x1 + 1), np.arange(z0, z1 + 1), indexing='ij')
            # барицентрический тест принадлежности точки треугольнику
            x2, z2 = gx + 0.5, gz + 0.5
            d1 = (t2x[1] - t2x[0]) * (z2 - t2z[0]) - (t2z[1] - t2z[0]) * (x2 - t2x[0])
            d2 = (t2x[2] - t2x[1]) * (z2 - t2z[1]) - (t2z[2] - t2z[1]) * (x2 - t2x[1])
            d3 = (t2x[0] - t2x[2]) * (z2 - t2z[2]) - (t2z[0] - t2z[2]) * (x2 - t2x[2])
            inside = ((d1 >= 0) & (d2 >= 0) & (d3 >= 0)) | ((d1 <= 0) & (d2 <= 0) & (d3 <= 0))
            xs, zs = np.clip(gx[inside], 0, G - 1), np.clip(gz[inside], 0, G - 1)
            body[xs, zs] = True
        from scipy import ndimage as _ndi
        body = _ndi.binary_fill_holes(_ndi.binary_closing(body, np.ones((3, 3))))
        body = _ndi.binary_dilation(body, np.ones((2, 2)))
        if body.mean() < 0.08:
            return 0
        vgx = np.clip(((fv[:, :, 0] - lo[0]) / ext[0] * (G - 1)).astype(int), 0, G - 1)
        vgz = np.clip(((fv[:, :, 2] - lo[2]) / ext[2] * (G - 1)).astype(int), 0, G - 1)
        vin = body[vgx, vgz]
        drop = ~vin.any(axis=1)                        # целиком вне контура — на любой высоте
        if drop.any() and not drop.all():
            m.update_faces(~drop)
            m.remove_unreferenced_vertices()
            m.export(glb_path)
            return int(drop.sum())
        return 0
    except Exception:  # noqa: BLE001 — ремонт не должен ронять задание
        return 0


def slab_suspect(glb_path: str) -> str | None:
    """Плита-АРТЕФАКТ на shape.glb: отдельный нижний компонент, ВЫХОДЯЩИЙ ЗА ГАБАРИТ тела.

    Разделитель дал владелец (30.08), и он же спас от массового ложного гейта: у тумбы
    «плита» — это аккуратное ДНО и лежит ВНУТРИ габарита корпуса (3/3 тумбы годные!);
    артефакт у дивана ТОРЧИТ за границы. Меряем выступ компонента за footprint остальной
    геометрии по X/Z: выступает заметно хотя бы с двух сторон — подозрение. Только диагноз.
    """
    try:
        import numpy as np
        import trimesh
        m = trimesh.load(glb_path, force='mesh')
        if m.faces is None or len(m.faces) < 500:
            return None
        labels = trimesh.graph.connected_component_labels(m.face_adjacency,
                                                          node_count=len(m.faces))
        if labels.max() == 0:
            return None
        V, F = np.asarray(m.vertices), np.asarray(m.faces)
        lo, hi = V.min(axis=0), V.max(axis=0)
        ext = np.maximum(hi - lo, 1e-6)
        for lab in np.unique(labels):
            sel = labels == lab
            if sel.all():
                continue
            pts = V[F[sel].ravel()]
            b0, b1 = pts.min(axis=0), pts.max(axis=0)
            fr = (b1 - b0) / ext
            thin_low = fr[1] < 0.06 and (b0[1] - lo[1]) / ext[1] < 0.07
            if not (thin_low and fr[0] > 0.6 and fr[2] > 0.6):
                continue
            rest = V[F[~sel].ravel()]
            r0, r1 = rest.min(axis=0), rest.max(axis=0)
            over = [max(0.0, float(r0[a] - b0[a])) / ext[a] for a in (0, 2)] +                    [max(0.0, float(b1[a] - r1[a])) / ext[a] for a in (0, 2)]
            sides = sum(1 for o in over if o > 0.025)
            if sides >= 2:
                return (f'плита торчит за габарит: выступы '
                        f'{[round(o, 3) for o in over]}, граней {int(sel.sum())}')
        return None
    except Exception:  # noqa: BLE001
        return None


def cut_alien_debris(glb_path: str) -> None:
    """Срезает галлюцинации-обломки: кусок не в палитре товара, висящий у пола.

    Диван 114667 (владелец 30.08): вырезка чистая, а у ножек белый мятый ком от генератора.
    Уроки первой версии фильтра: (1) у texture-визуала нет цветов вершин — их надо ЗАПЕЧЬ
    из текстуры по UV (`visual.to_color()`); (2) меш раздроблен на сотни кусков, «крупнейшее
    тело» — не палитра: доминанту берём по ВСЕЙ поверхности, взвешенно по площади граней;
    (3) ком бывает до ~7% граней — порог размера 8%, отбор делает цвет.
    Обломок = кусок ≤8% граней, целиком в нижних 40% высоты, цвет дальше 90 от доминанты.
    Тёмные ножки при тёмном корпусе — в палитре; белая мебель — доминанта белая, фильтр молчит.
    """
    import numpy as np
    import trimesh
    try:
        sc = trimesh.load(glb_path)
        mesh = sc.to_mesh() if hasattr(sc, 'to_mesh') else sc
        if mesh.faces is None or len(mesh.faces) < 1000:
            return
        vis = getattr(mesh, 'visual', None)
        if vis is None or getattr(vis, 'kind', None) != 'texture':
            return
        colored = vis.to_color()                     # запечь текстуру в цвета вершин по UV
        vc = np.asarray(colored.vertex_colors)[:, :3].astype(np.float32)
        V, F = np.asarray(mesh.vertices), np.asarray(mesh.faces)
        labels = trimesh.graph.connected_component_labels(mesh.face_adjacency,
                                                          node_count=len(F))
        if labels.max() == 0:
            return
        area = np.asarray(mesh.area_faces, np.float64)
        fcol = vc[F].mean(axis=1)                    # цвет грани = среднее по её вершинам
        dominant = (fcol * area[:, None]).sum(axis=0) / max(area.sum(), 1e-9)
        lo, hi = V.min(axis=0), V.max(axis=0)
        up = 1                                        # GLB: вверх — Y
        drop = np.zeros(len(F), bool)
        import collections
        counts = collections.Counter(labels.tolist())
        main_lab = counts.most_common(1)[0][0]
        for lab, cnt in counts.items():
            if lab == main_lab or cnt / len(F) > 0.08:
                continue
            sel = labels == lab
            pts = V[F[sel].ravel()]
            low = (pts[:, up].max() - lo[up]) / max(hi[up] - lo[up], 1e-6) < 0.40
            col = (fcol[sel] * area[sel, None]).sum(axis=0) / max(area[sel].sum(), 1e-9)
            alien = float(np.linalg.norm(col - dominant)) > 90
            if low and alien:
                drop |= sel
        if drop.any() and not drop.all():
            if os.environ.get('ALIEN_CUT', '0') == '1':
                mesh.update_faces(~drop)
                mesh.remove_unreferenced_vertices()
                mesh.export(glb_path)
                print(f'срезаны обломки не в палитре: {int(drop.sum())} граней', flush=True)
            else:
                # Codex q26: признаки пока небезопасны (доля граней ≠ площадь, зона ловит
                # ножки, одна доминанта врёт на двухцветном) — до размеченного бенча только
                # ПОМЕТКА; лечит перегон другим seed.
                open(glb_path + '.alien_suspect', 'w').write(str(int(drop.sum())))
                print(f'обломок-подозрение: {int(drop.sum())} граней (пометка, не срез)', flush=True)
    except Exception as e:  # noqa: BLE001 — ремонт не должен ронять задание
        print(f'cut_alien_debris пропущен: {type(e).__name__} {str(e)[:80]}', flush=True)


def cut_base_slab(glb_path: str, role: str | None = None) -> None:
    """Срезает «пол», который генератор дорисовывает под предметом.

    Пилот 29.08, кресло 112923: плита на всю ширину. Геометрия после конвертации слита в
    один меш → режем по связным компонентам граней (метки связности, не `split` — тот висит
    на плотных мешах, урок 28.08). ОСЬ «ВВЕРХ» НЕ УГАДЫВАЕМ: в GLB это обычно Y, у рендеров
    бывает Z — первый вариант резака искал плиту в XY и не нашёл её вовсе (проверено на том
    самом кресле). Теперь примеряем каждую ось: плита — тонкая (<5%) вдоль оси, лежит на её
    краю (<2%) и накрывает ≥80% по двум другим. Сомнительное не трогаем.
    """
    import numpy as np
    import trimesh
    if role is not None and role not in SLAB_ROLES:
        return
    try:
        m = trimesh.load(glb_path, force='mesh')
        if m.faces is None or not len(m.faces):
            return
        labels = trimesh.graph.connected_component_labels(m.face_adjacency,
                                                          node_count=len(m.faces))
        if labels.max() == 0:
            return
        V, F = np.asarray(m.vertices), np.asarray(m.faces)
        lo, hi = V.min(axis=0), V.max(axis=0)
        ext = np.maximum(hi - lo, 1e-6)
        drop = np.zeros(len(F), bool)
        up = 1                       # каноническая ось GLB — Y; перебор осей срезал бы
        others = [0, 2]              # заднюю/боковую панель как «пол» (Codex q26)
        for lab in np.unique(labels):
            sel = labels == lab
            if sel.all():
                continue
            pts = V[F[sel].ravel()]
            b0, b1 = pts.min(axis=0), pts.max(axis=0)
            frac = (b1 - b0) / ext
            thin = frac[up] < 0.05
            at_edge = (b0[up] - lo[up]) / ext[up] < 0.07   # плита о двух слоях: верхний чуть выше
            wide = frac[others[0]] > 0.8 and frac[others[1]] > 0.8
            if thin and at_edge and wide:
                drop |= sel
        # второй проход: крошка от плиты — мелкие компоненты, ЦЕЛИКОМ лежащие в нижних 6%
        # (ножки не задевает: их компонент тянется вверх и в зону целиком не попадает)
        if drop.any():
            zone = lo[up] + 0.06 * ext[up]
            for lab in np.unique(labels):
                sel = labels == lab
                if sel.all() or drop[sel].all():
                    continue
                pts = V[F[sel].ravel()]
                if pts[:, up].max() < zone and (pts[:, up].min() - lo[up]) / ext[up] < 0.04:
                    span_frac = (pts.max(axis=0) - pts.min(axis=0)) / ext
                    if span_frac[others[0]] < 0.5 and span_frac[others[1]] < 0.5:
                        drop |= sel
        if drop.any() and not drop.all():
            m.update_faces(~drop)
            m.remove_unreferenced_vertices()
            m.export(glb_path)
            print(f'срезан дорисованный пол: {int(drop.sum())} граней', flush=True)
    except Exception as e:  # noqa: BLE001 — ремонт не должен ронять задание
        print(f'cut_base_slab пропущен: {type(e).__name__} {str(e)[:80]}', flush=True)


def generate(image, out_dir: str, seed: int = 0, params: dict | None = None,
             paint_image=None, role: str | None = None) -> dict:
    """Одно задание: картинка → GLB с PBR-картами. Возвращает пути, времена и пики памяти.

    `image` — RGBA на полном холсте: альфа и есть маска товара, `ImageProcessorV2` сам кропает
    её по bbox и добавляет поле. `paint_image` — та же вырезка, но уже кропнутая: покраска вход
    не центрирует, только ужимает до 512, и без кропа половина её разрешения уходит на пустоту.
    """
    p = {'octree_resolution': 380, 'num_inference_steps': 50, 'guidance_scale': 5.0}
    p.update(params or {})
    os.makedirs(out_dir, exist_ok=True)
    timings, peaks = {}, {}
    generator = torch.Generator(device='cuda').manual_seed(seed)

    _free()
    t0 = time.time()
    extra = {}
    if p.get('mc_level') is not None:
        extra['mc_level'] = float(p['mc_level'])      # A/B q28: изоуровень marching cubes
    mesh = shape_pipeline()(
        image=image, generator=generator,
        octree_resolution=p['octree_resolution'],
        num_inference_steps=p['num_inference_steps'],
        guidance_scale=p['guidance_scale'], **extra)[0]
    timings['shape'] = round(time.time() - t0, 1)
    peaks['shape_gb'] = _peak_gb()

    raw_glb = os.path.join(out_dir, 'shape.glb')
    mesh.export(raw_glb)
    import shutil
    shutil.copy(raw_glb, os.path.join(out_dir, 'shape.generated.glb'))  # бэкап ДО ножей
    # РЕМОНТ И ГЕЙТЫ ДО ПОКРАСКИ (Codex q26): плита режется на форме — краска ляжет на
    # чистую геометрию, а брак формы не тратит paint-стадию (это половина времени задания).
    cut_base_slab(raw_glb, role)
    # ТОЛЬКО диваны/кровати (владелец 30.08: тумбы годные, их дно резак ЗАДЕВАЛ на тесте —
    # генератор строит корпус чуть шире паспорта, и кромка законного дна попадала «за габарит»)
    if role in ('диван', 'кровать', 'банкетка'):
        ncut = crop_beyond_passport(raw_glb, (params or {}).get('_dims'), role)
        if ncut:
            print(f'припол за паспортом срезан: {ncut} граней', flush=True)
    flat = flat_shape(raw_glb, params or {})
    if flat:
        raise FlatShape(flat)
    if role not in SLAB_ROLES and not ((params or {}).get('_dims') or {}).get('d'):
        # страховка только когда паспорта нет — с паспортом лишнее уже срезано по габариту
        sus = slab_suspect(raw_glb)
        if sus:
            raise SlabSuspect(sus)

    if STAGED:
        _unload('shape')          # ← ради этой строки вся конструкция и затевалась

    t1 = time.time()
    painted = paint_pipeline()(mesh_path=raw_glb, image_path=paint_image or image)
    timings['paint'] = round(time.time() - t1, 1)
    peaks['paint_gb'] = _peak_gb()

    t2 = time.time()
    final_glb = os.path.join(out_dir, 'model.glb')
    if isinstance(painted, str) and painted.lower().endswith('.obj'):
        # Покраска возвращает OBJ + mtl + карты РЯДОМ ОТДЕЛЬНЫМИ ФАЙЛАМИ. Переименовать его
        # в .glb — потерять материалы: первая десятка 29.08 уехала к нам геометрией без
        # текстур именно так. Конвертация обязана собрать САМОДОСТАТОЧНЫЙ GLB с PBR-картами —
        # это наш bpy-free convert_obj_to_glb (pygltflib, карты внутри base64).
        from DifferentiableRenderer.mesh_utils import convert_obj_to_glb
        ok = convert_obj_to_glb(painted, final_glb)
        if not ok or not os.path.exists(final_glb) or os.path.getsize(final_glb) == 0:
            raise RuntimeError('OBJ→GLB конвертация не удалась')
        cut_alien_debris(final_glb)   # только пометка suspect (автосрез под флагом)
    elif isinstance(painted, str):
        os.replace(painted, final_glb)
    else:
        painted.export(final_glb)
    timings['export'] = round(time.time() - t2, 1)
    timings['total'] = round(time.time() - t0, 1)

    if STAGED:
        _unload('paint')

    return {'glb': final_glb, 'shape_glb': raw_glb, 'timings': timings,
            'gpu': {'name': torch.cuda.get_device_name(0), 'staged': STAGED, **peaks}}
