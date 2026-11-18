"""ПРОБА T-20261117-02: сборка сцены в Blender и рендер Cycles на ПРОЦЕССОРЕ (0 ₽). Запуск — внутри Blender:

  ~/opt/blender-4.5.9/blender -b -P render_cycles.py -- --scene-dir <папка выгрузки сцены> --cam C1 --out <png> [--samples 160] [--pct 100]

Вход — выгрузка `export_scene.py` (те же меши/текстуры/камеры, что у серверного кадра T-61). Комната: пол/стены/потолок — плиты
(свет не протекает в углах), проёмы — по `cuts`; небо Nishita + солнце сквозь окно + мягкий заполняющий свет.
"""
import argparse
import json
import math
import os
import sys
import time

T_START = time.time()
import bpy
import numpy as np
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--scene-dir', required=True)
ap.add_argument('--cam', default='C1', help='ракурс или список через запятую (C1,C2) — тогда все кадры в ОДНОМ процессе Blender, в --out шаблон {cam}')
ap.add_argument('--device', default='cpu', choices=['cpu', 'auto', 'optix', 'cuda'], help='cpu (по умолчанию) | auto (OptiX → CUDA → CPU) | optix | cuda; GPU недоступен при optix/cuda — ошибка')
ap.add_argument('--out', required=True)
ap.add_argument('--jpeg-quality', type=int, default=0, help='>0 — кадры JPEG этого качества (T-24/11: с машины уходит JPEG, не PNG; имя в --out должно кончаться на .jpg); 0 — PNG как раньше')
ap.add_argument('--also-png', default='', help='ТОЛЬКО ДЛЯ ПРИЁМКИ: вместе с JPEG положить и PNG из того же результата (шаблон с {cam}) — сравнить ΔE кодировщика; в бою не задаётся')
ap.add_argument('--mask-out', default='', help='после кадра — маска поверхностей тем же ракурсом: пол красный, нейтральная стена зелёная, акцентная синяя, остальное чёрное (замер яркости, T-20261117-23/2)')
ap.add_argument('--samples', type=int, default=160)
ap.add_argument('--pct', type=int, default=100)
ap.add_argument('--mask-scale', type=float, default=1.0, help='маска поверхностей (--mask-out) в долях размера кадра: 0.25 — четверть (быстрее и в десятки раз меньше файл); 1 — как кадр')
ap.add_argument('--threads', type=int, default=8)
ap.add_argument('--persistent', type=int, default=0, help='1 — render.use_persistent_data: между кадрами одного процесса не пересобирать BVH и текстуры (проба T-22; по умолчанию как раньше)')
ap.add_argument('--sun', type=float, default=4.0)
ap.add_argument('--sky', type=float, default=1.0)
ap.add_argument('--sky-sat', type=float, default=1.0, help='насыщенность света неба Nishita (1 — как есть; меньше — голубизна белых стен и постели слабее)')
ap.add_argument('--sun-angle', type=float, default=1.5, help='угловой размер солнца, ° (мягкость края тени; Codex: 3–5)')
ap.add_argument('--fill', type=float, default=60.0)
ap.add_argument('--fill-k', type=float, default=5500.0, help='цвет заполняющего света, К (6500 — белый, как полусфера живой 3D)')
ap.add_argument('--view', type=float, default=1.2)
ap.add_argument('--exposure', type=float, default=0.0)
ap.add_argument('--lite-tex', type=int, default=0, help='>0: уменьшить текстуры до этой стороны (замер облегчённой версии)')
ap.add_argument('--demo-glb', default='', help='GLB декора из сцены /demo (demo_scene_dump.mjs)')
ap.add_argument('--demo-nodes', default='', help='demo_nodes_uuids.json рядом с GLB')
ap.add_argument('--plant-wmax', type=float, default=0.5, help='предел ширины растения-кандидата, м (с --plant-swap)')
ap.add_argument('--plant-swap', default='', help='GLB растения-кандидата (`plant_candidates.py`): ставится вместо растений декора /demo (T-20261117-21)')
ap.add_argument('--plant-slot', default='plant:', help='подстрока слота заменяемых растений (`plant:кашпо`, `plant:decor:ваза`)')
ap.add_argument('--plant-on', default='', help='роль предмета (`тв-тумба`): поставить растение-кандидата СВЕРХУ на него, у его края (доля по длинной стороне — `--plant-on-frac`)')
ap.add_argument('--plant-on-frac', type=float, default=0.22, help='где на верхней плоскости (0 — край, 0.5 — середина)')
ap.add_argument('--plant-n', type=int, default=1, help='сколько растений (слотов по порядку) заменить')
ap.add_argument('--plant-h', type=float, default=0.0, help='высота подставляемого растения, см (0 — как у прежнего)')
ap.add_argument('--chandelier', type=float, default=60.0, help='мощность света люстры, Вт (0 — без света)')
ap.add_argument('--hdri', default='', help='HDRI неба (Poly Haven, CC0): свет и портал вместо Nishita')
ap.add_argument('--hdri-strength', type=float, default=1.0)
ap.add_argument('--portal', type=int, default=0, help='1: световой портал в проёме окна')
ap.add_argument('--transform', default='AgX', help='view transform: AgX | Filmic | Standard (сетка настроек, T-20261117-06/1)')
ap.add_argument('--look', default='AgX - Medium High Contrast', help='look (подбирается по имени; нет такого — без look)')
ap.add_argument('--cam-h', type=float, default=0.0, help='>0: высота глаза камеры, м (по умолчанию — как у ракурса)')
ap.add_argument('--cam-auto', type=int, default=0, help='1: ракурс с окном (глаз в дальнем углу, взгляд горизонтальный) вместо C1/C2')
ap.add_argument('--orig', action='append', default=[], help='РОЛЬ:путь.glb (можно несколько раз) — заменить runtime-меш этой роли оригиналом (проба обивки)')
ap.add_argument('--soft-min-z', type=float, default=0.12, help='мягкая мебель: ниже этой высоты от пола (м) — ножки, без ворса/плетения')
ap.add_argument('--soft-rough', type=float, default=-1.0, help='>=0: шероховатость ткани мягкой мебели (вместо карты меша; ножки остаются по карте)')
ap.add_argument('--orig-rough', type=float, default=-1.0, help='>=0: шероховатость оригинала (число; иначе — как в файле)')
ap.add_argument('--sheen', type=float, default=0.0, help='>0: Sheen Weight мягкой мебели и текстиля (ткань, не кожа)')
ap.add_argument('--sheen-rough', type=float, default=0.5)
ap.add_argument('--fabric', default='', help='путь к карте нормалей ткани (CC0): мелкий рельеф плетения поверх мягкой мебели (проба)')
ap.add_argument('--fabric-k', type=float, default=0.6)
ap.add_argument('--fabric-tile', type=float, default=12.0, help='физический размер одного повтора карты ткани, см')
ap.add_argument('--rug-erode', type=float, default=0.0, help='доля ширины ковра: срезать светлую кайму по краю выреза (0 — как раньше)')
ap.add_argument('--sheer', type=float, default=1.0, help='<1: непрозрачность штор (тюль), чтобы окно не закрывалось «молоком»')
ap.add_argument('--normal-k', type=float, default=0.7, help='сила карты нормалей отделки (у three — 0.7; больше — виден рельеф штукатурки и досок)')
ap.add_argument('--eye', default='', help='x,y глаза, м (оси Blender: y = −план_y); с --aim задаёт ракурс')
ap.add_argument('--aim', default='', help='x,y точки, куда смотрит камера, м (оси Blender)')
ap.add_argument('--level', type=int, default=0, help='1: горизонтальный взгляд ракурса (вертикали прямые), наклон — через --shift-y')
ap.add_argument('--lens', type=float, default=0.0, help='>0: объектив, мм на полный кадр (28–35); 0 — угол ракурса')
ap.add_argument('--pitch', type=float, default=None, help='наклон взгляда вниз от горизонта, градусы (поверх --level 1; общий параметр позы)')
ap.add_argument('--pose-mode', default='b', choices=['b', 'demo'], help="поза /demo: b — вариант «Б» (глаз 1,35, горизонтально, сдвиг вниз); demo — как в витрине")
ap.add_argument('--pose-shift', type=float, default=0.15, help='«Б»: сдвиг объектива вниз, доли высоты кадра (Codex: ≤ 0,15)')
ap.add_argument('--floor-min', type=float, default=0.35, help='«Б»: доля пола в кадре, ниже которой глаз опускается до --eye-low')
ap.add_argument('--eye-low', type=float, default=1.2, help='«Б»: низкий глаз, м')
ap.add_argument('--floor-keep', type=float, default=0.7, help='«Б»: при подъёме кадра пол не ниже этой доли от --floor-min')
ap.add_argument('--brick-var', type=float, default=0.16, help='разнотон кирпичей: размах яркости ± (доля), насыщенность — половина')
ap.add_argument('--brick-hue', type=float, default=0.015, help='разнотон кирпичей: сдвиг оттенка ± (доля круга)')
ap.add_argument('--brick-patch', type=float, default=0.10, help='медленные пятна яркости по стене ± (доля)')
ap.add_argument('--brick-bump', type=float, default=0.9, help='рельеф кладки по карте высоты: сила bump (0 — выкл)')
ap.add_argument('--brick-dist', type=float, default=0.012, help='рельеф кладки: глубина шва, м')
ap.add_argument('--brick-ao', type=float, default=0.75, help='затенение скана множителем на цвет (0 — выкл)')
ap.add_argument('--art-guard', type=int, default=1, help='сторож картин: картина без текстуры или белая и почти однотонная (σ яркости центра < --art-sigma) — ошибка кадра с именем товара, кадр не сдаётся')
ap.add_argument('--art-allow-blank', action='store_true', help='сторож картин: не падать, только предупредить (пока белые картины не заменены в данных витрины)')
ap.add_argument('--live-cam', default='', help='камера живой 3D: live_cam.json из `demo_scene_dump.mjs livecam=…` (положение, взгляд, угол как на странице); позу «Б» и подгонки не применяет')
ap.add_argument('--live-scale', type=float, default=2.0, help='--live-cam: во сколько раз кадр больше холста страницы (375×667 → 750×1334)')
ap.add_argument('--near', type=float, default=1.5, help='«Б»: предмет ближе этого расстояния от камеры (глаз → точка предмета) — передний план, м; ваза на столике C2 — ~1,4 м')
ap.add_argument('--occl', type=float, default=0.10, help='«Б»: доля НИЖНЕЙ половины кадра, закрытая передним планом, выше которой камера отодвигается назад')
ap.add_argument('--back-max', type=float, default=1.5, help='«Б»: на сколько метров камера может уйти назад (и не ближе 0,3 м к стене)')
ap.add_argument('--shift-y', type=float, default=None, help='сдвиг объектива по вертикали (доли ширины кадра); нет — как у ракурса')
ap.add_argument('--lamps', type=float, default=0.0, help='>0: мощность точечного света у каждого торшера и настольной лампы, Вт (0 — лампы не светят, как в данных)')
ap.add_argument('--lamp-k', type=float, default=0.0, help='>0: цветовая температура ламп, К (люстра и заполняющий свет); 0 — как было')
ap.add_argument('--export', default='', help='scene-export.json (lib/viewer3d/scene-export.ts): стены и пол — карты, тайл и тонировка оттуда')
ap.add_argument('--public', default='', help='папка public/ репо (карты материалов); по умолчанию — public/ этой копии')
ap.add_argument('--real', type=int, default=0, help='(устарел, не действует: фактура — только из --export)')
ap.add_argument('--dof', type=float, default=0.0, help='>0: диафрагма f/N, лёгкая глубина резкости (фокус — середина мебели)')
ap.add_argument('--smooth-deg', type=float, default=50.0, help='угол сглаживания нормалей мебели, ° (0 — без сглаживания, плоские грани)')
ap.add_argument('--denoise', type=int, default=1, help='0 — без шумоподавления OIDN (разбор причины артефактов)')
ap.add_argument('--mr', type=int, default=1, help='1: у мебели своя карта шероховатости/металла меша (как есть), иначе таблица ROUGH')
ap.add_argument('--qa', type=int, default=1, help='сторож кадров (render-qa-gate-01, frame_qa.py): до рендера — оплачиваемые позиции против выгрузки и сцены; после — маска предметов каждого кадра, отчёт `<кадр>.qa.json`; только отчёт, кадр не блокирует (шаг 5 не включён)')
ap.add_argument('--qa-inject', default='', help='проверка сторожа: art_nomap[:слот],art_white[:слот],curtain_remove,hide_item:слот,camera (через запятую)')
a = ap.parse_args(argv)
if a.orig and (a.lamp_k == 2800.0 or a.sheen == 0.4 or (a.fabric and a.fabric_tile == 12.0)):
    # прежние очереди пробы (круг 1: оранжевый свет; sheen 0,4 и плетение без маски ножек) заменены новым набором — не тратим на них ядра
    print('пропуск: устаревший вариант пробы обивки')
    sys.exit(0)

M = json.load(open(os.path.join(a.scene_dir, 'scene.json'), encoding='utf-8'))
W, D, H = M['W'], M['D'], M['H']
CORNER, THICK = 10.0, 12.0


def b(x, y, z):
    """сцена (см) → Blender (м)."""
    return (x / 100.0, -z / 100.0, y / 100.0)


def hexrgb(h):
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


def srgb2lin(c):
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
cy = sc.cycles


def pick_device(want):
    """Устройство рендера: `cpu` — как было; `auto` — OptiX → CUDA → CPU; `optix`/`cuda` — только это, нет — ошибка (не молчаливый CPU).
    Фактическое устройство печатается строками DEVICE_* и возвращается — по нему оператор судит, что рендер пошёл на GPU."""
    if want == 'cpu':
        cy.device = 'CPU'
        return 'CPU'
    prefs = bpy.context.preferences.addons['cycles'].preferences
    order = ['OPTIX', 'CUDA'] if want == 'auto' else [want.upper()]
    for kind in order:
        try:
            prefs.compute_device_type = kind
            prefs.refresh_devices() if hasattr(prefs, 'refresh_devices') else None
        except (TypeError, ValueError) as e:
            print(f'DEVICE_SKIP {kind}: {e}', flush=True)
            continue
        devs = [d for d in prefs.get_devices_for_type(kind) if d.type == kind]
        for d in prefs.devices:
            d.use = d.type == kind              # процессор не берём: смесь CPU+GPU замедляет кадр и мешает замеру
        print(f'DEVICE_LIST {kind}: ' + ', '.join(f'{d.name}' for d in devs), flush=True)
        if devs:
            cy.device = 'GPU'
            for d in devs:
                d.use = True
            print(f'DEVICE_USED {kind} ({devs[0].name})', flush=True)
            return f'{kind}:{devs[0].name}'
    if want != 'auto':
        raise SystemExit(f'DEVICE_FAIL: устройство {want} недоступно (ни одного {want.upper()}-устройства) — рендер не запущен')
    print('DEVICE_USED CPU (GPU не найден, запасной путь)', flush=True)
    cy.device = 'CPU'
    return 'CPU'


DEVICE_USED = pick_device(a.device)
if a.device != 'cpu' and cy.device == 'GPU':
    try:
        cy.denoising_use_gpu = True             # OIDN на видеокарте
    except AttributeError:
        pass
cy.samples = a.samples
cy.use_adaptive_sampling = True
cy.adaptive_threshold = 0.01
cy.use_denoising = bool(a.denoise)
cy.denoiser = 'OPENIMAGEDENOISE'
cy.max_bounces = 8
cy.diffuse_bounces = 5
cy.glossy_bounces = 4
cy.transmission_bounces = 4
cy.sample_clamp_indirect = 10.0
cy.caustics_reflective = False
cy.caustics_refractive = False
sc.render.threads_mode = 'FIXED'
sc.render.threads = a.threads
sc.render.use_persistent_data = bool(a.persistent)
sc.view_settings.view_transform = a.transform
# look: имя точное, затем без префикса «AgX - » / «Filmic - » (в разных версиях Blender пишется по-разному); нет — без look
_short = a.look.split(' - ', 1)[-1]
for _look in (a.look, _short, a.transform + ' - ' + _short):
    try:
        sc.view_settings.look = _look
        break
    except TypeError:
        continue
print('view', sc.view_settings.view_transform, '| look', sc.view_settings.look)
sc.view_settings.exposure = a.exposure
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_depth = '8'
if a.jpeg_quality > 0:
    sc.render.image_settings.file_format = 'JPEG'          # кодирует сам Blender (в образе машины нет Pillow); тот же вид-трансформ и dither, что у PNG
    sc.render.image_settings.quality = max(1, min(100, a.jpeg_quality))
    sc.render.image_settings.color_mode = 'RGB'


def make_obj(name, verts, faces, uvs=None, mat=None, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(map(float, v)) for v in verts], [], [tuple(map(int, f)) for f in faces])
    me.update()
    if uvs is not None:
        uv = me.uv_layers.new(name='UV')
        loops = np.array([l.vertex_index for l in me.loops], np.int64)
        uv.data.foreach_set('uv', np.asarray(uvs, np.float32)[loops].ravel())
    if mat is not None:
        me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    sc.collection.objects.link(ob)
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
        try:
            me.shade_smooth_by_angle = None
        except Exception:
            pass
    return ob


def smooth_by_angle(ob, deg=45):
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(deg))
    except Exception:
        bpy.ops.object.shade_smooth()
    ob.select_set(False)


def principled(name, rgb=None, tex=None, rough=0.6, spec=0.5, metallic=0.0, tex_lite=0, mr=None, tint=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes['Principled BSDF']
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metallic
    try:
        bsdf.inputs['Specular IOR Level'].default_value = spec
    except KeyError:
        pass
    if tex:
        node = nt.nodes.new('ShaderNodeTexImage')
        img = bpy.data.images.load(os.path.join(a.scene_dir, tex), check_existing=True)
        if tex_lite and max(img.size) > tex_lite:
            img.scale(tex_lite, tex_lite)
        node.image = img
        node.interpolation = 'Cubic'
        if tint:
            # ПОДКРАСКА ПОД ТОВАР (T-20261117-23): карта × множитель товара в ЛИНЕЙНОМ пространстве — как живая 3D (`meshes.ts:placeMesh`: color × tint)
            mx = nt.nodes.new('ShaderNodeMix')
            mx.data_type = 'RGBA'
            mx.blend_type = 'MULTIPLY'
            mx.inputs['Factor'].default_value = 1.0
            mx.inputs['B'].default_value = (*tint, 1.0)
            nt.links.new(node.outputs['Color'], mx.inputs['A'])
            nt.links.new(mx.outputs['Result'], bsdf.inputs['Base Color'])
        else:
            nt.links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
        if mr:
            # glTF: шероховатость — канал G, металл — B (множитель в файле = 1) — карта самого меша, ничего не придумываем
            n2 = nt.nodes.new('ShaderNodeTexImage')
            im2 = bpy.data.images.load(os.path.join(a.scene_dir, mr), check_existing=True)
            im2.colorspace_settings.name = 'Non-Color'
            n2.image = im2
            sep = nt.nodes.new('ShaderNodeSeparateColor')
            nt.links.new(n2.outputs['Color'], sep.inputs['Color'])
            nt.links.new(sep.outputs['Green'], bsdf.inputs['Roughness'])
            nt.links.new(sep.outputs['Blue'], bsdf.inputs['Metallic'])
    else:
        lin = srgb2lin(rgb)
        if tint:
            lin = [c * t for c, t in zip(lin, tint)]
        bsdf.inputs['Base Color'].default_value = (*lin, 1.0)
    return m


def kelvin_rgb(k):
    """Цвет чёрного тела 1000–6500 К → линейный RGB лампы (приближение Таннера Хеллмана, sRGB → линейный)."""
    t = max(1000.0, min(6500.0, k)) / 100.0
    r = 1.0 if t <= 66 else min(1.0, 1.292936 * (t - 60) ** -0.1332047)
    g = (0.390082 * math.log(t) - 0.631841) if t <= 66 else 1.129891 * (t - 60) ** -0.0755148
    bl = 1.0 if t >= 66 else (0.0 if t <= 19 else 0.543207 * math.log(t - 10) - 1.196254)
    return tuple(srgb2lin([max(0.0, min(1.0, x)) for x in (r, g, bl)]))


def camera_only(ob):
    ob.visible_diffuse = ob.visible_glossy = ob.visible_transmission = ob.visible_shadow = ob.visible_volume_scatter = False


ROUGH = {'диван': 0.9, 'кресло': 0.9, 'стул': 0.75, 'кровать': 0.9, 'пуф': 0.9, 'банкетка': 0.9, 'кашпо': 0.8, 'ваза': 0.35, 'торшер': 0.45}

# ---------------- комната (плиты — свет не протекает) ----------------
wall_mat = principled('wall', hexrgb(M['finish']['wall']['colorHex']), rough=0.92, spec=0.2)
ceil_mat = principled('ceiling', hexrgb(M['finish']['ceiling']['colorHex']), rough=0.95, spec=0.1)

# СТЕНЫ И ПОЛ — только из описания сцены (`scene-export.json`, render-3d-01 шаг 0): карты, физический размер повтора (`tileCm`) и тонировка
# посчитаны браузерным кодом (`lib/viewer3d/scene-export.ts`, `finish-passport.ts:tintHex`) — своих правил (доски, штукатурка) здесь нет.
# Нет описания — ровный цвет паспорта из `scene.json`.
EXP = json.load(open(a.export, encoding='utf-8')) if a.export else None
PUB = a.public or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'public')
_room0 = EXP['rooms'][0] if EXP else None


def finish_material(name, surf):
    """Материал поверхности по записи экспорта: карта цвета × tintHex, нормали (как три: сила 0.7), шероховатость карты × roughness."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes['Principled BSDF']
    bsdf.inputs['Roughness'].default_value = surf['roughness']
    bsdf.inputs['Metallic'].default_value = surf['metalness']
    try:
        bsdf.inputs['Specular IOR Level'].default_value = 0.35
    except KeyError:
        pass
    maps = surf['maps']
    if not maps.get('color'):
        bsdf.inputs['Base Color'].default_value = (*srgb2lin(hexrgb(surf['colorHex'])), 1.0)
        return m
    tc = nt.nodes.new('ShaderNodeTexCoord')
    mp = nt.nodes.new('ShaderNodeMapping')
    # метры → повторы: один повтор карты = tileCm сантиметров (то же, что `materials.ts:tiled` в браузере)
    # стена: вертикаль (Z) — вторая сторона тайла, обе горизонтали — первая (кирпичный тайл 210×105 не квадратный); пол и штукатурка — как были
    if name.startswith('wall'):
        mp.inputs['Scale'].default_value = (100.0 / surf['tileCm'][0], 100.0 / surf['tileCm'][0], 100.0 / surf['tileCm'][1])
    else:
        mp.inputs['Scale'].default_value = (100.0 / surf['tileCm'][0], 100.0 / surf['tileCm'][1], 100.0 / surf['tileCm'][0])
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])

    def tex(key, srgb):
        n = nt.nodes.new('ShaderNodeTexImage')
        img = bpy.data.images.load(os.path.join(PUB, maps[key].lstrip('/')), check_existing=True)
        img.colorspace_settings.name = 'sRGB' if srgb else 'Non-Color'
        n.image = img
        n.interpolation = 'Cubic'
        n.projection = 'BOX'              # пол и стены без развёртки: плоская проекция по оси нормали
        n.projection_blend = 0.0
        nt.links.new(mp.outputs['Vector'], n.inputs['Vector'])
        return n
    col = tex('color', True)
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MULTIPLY'
    mix.inputs['Factor'].default_value = 1.0
    nt.links.new(col.outputs['Color'], mix.inputs['A'])
    mix.inputs['B'].default_value = (*srgb2lin(hexrgb(surf['tintHex'])), 1.0)
    base_out = mix.outputs['Result']
    if maps.get('ao') and a.brick_ao > 0:
        # затенение скана (швы глубже, края кирпича светлее) — множителем на цвет
        am = nt.nodes.new('ShaderNodeMix')
        am.data_type = 'RGBA'
        am.blend_type = 'MULTIPLY'
        am.inputs['Factor'].default_value = a.brick_ao
        nt.links.new(base_out, am.inputs['A'])
        nt.links.new(tex('ao', False).outputs['Color'], am.inputs['B'])
        base_out = am.outputs['Result']
    if maps.get('variation') and a.brick_var > 0:
        # РАЗНОТОН ПО КИРПИЧАМ: номер кирпича из карты (0 — шов) + случайное смещение на каждый повтор тайла (без повтора узора по стене) →
        # случайное число 0..1 на кирпич → сдвиг яркости, насыщенности и оттенка; плюс медленные пятна по стене
        idn = tex('variation', False)
        idn.interpolation = 'Closest'
        idn_v = nt.nodes.new('ShaderNodeSeparateColor')
        nt.links.new(idn.outputs['Color'], idn_v.inputs['Color'])
        fl = nt.nodes.new('ShaderNodeVectorMath')
        fl.operation = 'FLOOR'
        nt.links.new(mp.outputs['Vector'], fl.inputs[0])
        wn = nt.nodes.new('ShaderNodeTexWhiteNoise')
        wn.noise_dimensions = '3D'
        nt.links.new(fl.outputs['Vector'], wn.inputs['Vector'])
        add = nt.nodes.new('ShaderNodeMath')
        add.operation = 'ADD'
        nt.links.new(idn_v.outputs['Red'], add.inputs[0])
        nt.links.new(wn.outputs['Value'], add.inputs[1])
        fr = nt.nodes.new('ShaderNodeMath')
        fr.operation = 'FRACT'
        nt.links.new(add.outputs['Value'], fr.inputs[0])
        isb = nt.nodes.new('ShaderNodeMath')            # 1 на кирпиче, 0 на шве
        isb.operation = 'GREATER_THAN'
        isb.inputs[1].default_value = 0.05
        nt.links.new(idn_v.outputs['Red'], isb.inputs[0])
        cen = nt.nodes.new('ShaderNodeMath')            # -1..1
        cen.operation = 'MULTIPLY_ADD'
        cen.inputs[1].default_value = 2.0
        cen.inputs[2].default_value = -1.0
        nt.links.new(fr.outputs['Value'], cen.inputs[0])
        sgn = nt.nodes.new('ShaderNodeMath')
        sgn.operation = 'MULTIPLY'
        nt.links.new(cen.outputs['Value'], sgn.inputs[0])
        nt.links.new(isb.outputs['Value'], sgn.inputs[1])
        ntex = nt.nodes.new('ShaderNodeTexNoise')       # медленные пятна: ~1,2 м, без привязки к кирпичу
        ntex.inputs['Scale'].default_value = 0.9
        ntex.inputs['Detail'].default_value = 2.0
        nt.links.new(tc.outputs['Object'], ntex.inputs['Vector'])
        pat = nt.nodes.new('ShaderNodeMath')
        pat.operation = 'MULTIPLY_ADD'
        pat.inputs[1].default_value = 2.0 * a.brick_patch
        pat.inputs[2].default_value = -a.brick_patch
        nt.links.new(ntex.outputs['Fac'], pat.inputs[0])
        hs = nt.nodes.new('ShaderNodeHueSaturation')
        hs.inputs['Fac'].default_value = 1.0
        # оттенок: 0.5 ± brick_hue · k; насыщенность: 1 ± 0.5·brick_var · k; яркость: 1 ± brick_var · k + пятна
        hue = nt.nodes.new('ShaderNodeMath')
        hue.operation = 'MULTIPLY_ADD'
        hue.inputs[1].default_value = a.brick_hue
        hue.inputs[2].default_value = 0.5
        nt.links.new(sgn.outputs['Value'], hue.inputs[0])
        nt.links.new(hue.outputs['Value'], hs.inputs['Hue'])
        sat = nt.nodes.new('ShaderNodeMath')
        sat.operation = 'MULTIPLY_ADD'
        sat.inputs[1].default_value = 0.5 * a.brick_var
        sat.inputs[2].default_value = 1.0
        nt.links.new(sgn.outputs['Value'], sat.inputs[0])
        nt.links.new(sat.outputs['Value'], hs.inputs['Saturation'])
        val = nt.nodes.new('ShaderNodeMath')
        val.operation = 'MULTIPLY_ADD'
        val.inputs[1].default_value = a.brick_var
        val.inputs[2].default_value = 1.0
        nt.links.new(sgn.outputs['Value'], val.inputs[0])
        val2 = nt.nodes.new('ShaderNodeMath')
        val2.operation = 'ADD'
        nt.links.new(val.outputs['Value'], val2.inputs[0])
        nt.links.new(pat.outputs['Value'], val2.inputs[1])
        nt.links.new(val2.outputs['Value'], hs.inputs['Value'])
        nt.links.new(base_out, hs.inputs['Color'])
        base_out = hs.outputs['Color']
    nt.links.new(base_out, bsdf.inputs['Base Color'])
    nrm_out = None
    if maps.get('normal'):
        nm = nt.nodes.new('ShaderNodeNormalMap')
        nm.inputs['Strength'].default_value = a.normal_k
        nt.links.new(tex('normal', False).outputs['Color'], nm.inputs['Color'])
        nrm_out = nm.outputs['Normal']
    if maps.get('height') and a.brick_bump > 0:
        # рельеф кладки по карте высоты: швы утоплены и ловят свет у окна (bump, без смещения геометрии)
        bp = nt.nodes.new('ShaderNodeBump')
        bp.inputs['Strength'].default_value = a.brick_bump
        bp.inputs['Distance'].default_value = a.brick_dist
        nt.links.new(tex('height', False).outputs['Color'], bp.inputs['Height'])
        if nrm_out is not None:
            nt.links.new(nrm_out, bp.inputs['Normal'])
        nrm_out = bp.outputs['Normal']
    if nrm_out is not None:
        nt.links.new(nrm_out, bsdf.inputs['Normal'])
    if maps.get('roughness'):
        sep = nt.nodes.new('ShaderNodeSeparateColor')
        nt.links.new(tex('roughness', False).outputs['Color'], sep.inputs['Color'])
        mul = nt.nodes.new('ShaderNodeMath')
        mul.operation = 'MULTIPLY'
        mul.inputs[1].default_value = surf['roughness']
        nt.links.new(sep.outputs['Green'], mul.inputs[0])
        nt.links.new(mul.outputs['Value'], bsdf.inputs['Roughness'])
    return m


accent_mat, accent_side = None, None
if EXP:
    wall_mat = finish_material('wall', _room0['wall'])
    if _room0.get('accent'):
        # акцентная стена (T-20261117-16: лофт — кирпич): материал и сторона из описания сцены, свои правила здесь не нужны
        accent_mat = finish_material('wall_accent', _room0['accent']['surface'])
        accent_side = _room0['accent']['side']
        print('акцентная стена:', accent_side, _room0['accent']['surface'].get('id'))

def slab(name, x0, x1, y0, y1, z0, z1, mat):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return make_obj(name, v, f, mat=mat, smooth=False)


# пол — плита вниз; материал — из описания сцены (карты, тайл, тонировка), иначе ровный цвет паспорта
fm = finish_material('floor', _room0['floor']) if EXP else principled('floor', hexrgb(M['finish']['floor']['colorHex']), rough=0.6, spec=0.3)
slab('floor', -CORNER / 100, (W + CORNER) / 100, -(D + CORNER) / 100, CORNER / 100, -THICK / 100, 0.0, fm)
slab('ceiling', -CORNER / 100, (W + CORNER) / 100, -(D + CORNER) / 100, CORNER / 100, H / 100, (H + THICK) / 100, ceil_mat)

# стены по правилам сервера (`planner/scene.py`: wall_rects, _wall_quad) + плита наружу
FR = {'south': ((0, 0), (1, 0), (0, 1)), 'north': ((W, D), (-1, 0), (0, -1)),
      'west': ((0, D), (0, -1), (1, 0)), 'east': ((W, 0), (0, 1), (-1, 0))}


def wall_rects(length, height, cuts):
    out, cursor = [], 0.0
    for u0, u1, bottom, top in sorted(cuts):
        u0, u1 = max(0.0, min(length, u0)), max(0.0, min(length, u1))
        if u1 <= u0:
            continue
        if u0 > cursor:
            out.append((cursor, u0, 0.0, height))
        if bottom > 0:
            out.append((u0, u1, 0.0, min(bottom, height)))
        if top < height:
            out.append((u0, u1, top, height))
        cursor = max(cursor, u1)
    if cursor < length:
        out.append((cursor, length, 0.0, height))
    return [r for r in out if r[1] - r[0] > 0.5 and r[3] - r[2] > 0.5]


for wall, ((ox, oz), (dx, dz), (nx, nz)) in FR.items():
    length = W if wall in ('north', 'south') else D
    cl = [(c['u0'], c['u1'], c['bottom'], c['top']) for c in M['cuts'].get(wall, [])]
    for k, (u0, u1, v0, v1) in enumerate(wall_rects(length, H, cl)):
        u0 = u0 - CORNER if u0 <= 0 else u0
        u1 = u1 + CORNER if u1 >= length else u1
        pts = []
        for back in (0.0, THICK):
            bx, bz = ox - nx * back, oz - nz * back
            for (u, v) in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
                pts.append(b(bx + dx * u, v, bz + dz * u))
        f = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
        # ориентация граней не важна для Cycles (двусторонние), нормали — по сглаживанию отключены
        make_obj(f'wall_{wall}_{k}', pts, f, mat=accent_mat if (accent_mat is not None and wall == accent_side) else wall_mat, smooth=False)
    # за дверным проёмом — «коридор» (приглушённый светлый), чтобы дыра не читалась небом
    for c in M['cuts'].get(wall, []):
        if c['kind'] in ('window', 'balcony'):
            continue
        back = 90.0
        bx, bz = ox - nx * back, oz - nz * back
        pts = [b(bx + dx * u, v, bz + dz * u) for (u, v) in ((c['u0'] - 60, 0), (c['u1'] + 60, 0), (c['u1'] + 60, c['top'] + 40), (c['u0'] - 60, c['top'] + 40))]
        hall = bpy.data.materials.new('hall')
        hall.use_nodes = True
        hb = hall.node_tree.nodes['Principled BSDF']
        hb.inputs['Base Color'].default_value = (*srgb2lin((0.62, 0.6, 0.57)), 1)
        hb.inputs['Emission Color'].default_value = (*srgb2lin((0.62, 0.6, 0.57)), 1)
        hb.inputs['Emission Strength'].default_value = 0.5
        ho = make_obj('hall', pts, [(0, 1, 2, 3)], mat=hall, smooth=False)
        camera_only(ho)

# вид из окна (как у браузера и серверного кадра): картинка на плоскости за стеной, видна ТОЛЬКО камере — свет и тень не трогает
for k, bdv in enumerate(M.get('backdrops', [])):
    bd = bdv['bd']
    (ox, oz), (dx, dz), (nx, nz) = FR[bdv['wall']]
    bx, bz = ox - nx * bd['back'], oz - nz * bd['back']
    pts = [b(bx + dx * u, v, bz + dz * u) for (u, v) in ((bd['u0'], bd['bottom']), (bd['u1'], bd['bottom']), (bd['u1'], bd['top']), (bd['u0'], bd['top']))]
    uvr = bd['uv']
    uvs = [(uvr['u0'], uvr['v0']), (uvr['u1'], uvr['v0']), (uvr['u1'], uvr['v1']), (uvr['u0'], uvr['v1'])]
    vm = bpy.data.materials.new('view')
    vm.use_nodes = True
    n = vm.node_tree
    bsdf = n.nodes['Principled BSDF']
    ti = n.nodes.new('ShaderNodeTexImage')
    ti.image = bpy.data.images.load(os.path.join(a.scene_dir, bdv['tex']))
    n.links.new(ti.outputs['Color'], bsdf.inputs['Emission Color'])
    bsdf.inputs['Base Color'].default_value = (0, 0, 0, 1)
    bsdf.inputs['Emission Strength'].default_value = a.view
    vo = make_obj('view', pts, [(0, 1, 2, 3)], uvs=uvs, mat=vm, smooth=False)
    camera_only(vo)

# ---------------- проба обивки (T-20261117-06/1, владелец TG 1341: «диван как кожа») ----------------
SOFT = ('диван', 'кресло', 'пуф', 'банкетка', 'кровать')


def swap_original(rt_ob, rt_v, path):
    """Заменяет runtime-меш (лёгкий, без карты шероховатости/металла) оригиналом из каталога (`.glb` с metallicRoughness). Оригинал ставится в ту же
    рамку: четыре поворота вокруг вертикали (по 90°), выбирается тот, чьё облако вершин ближе к runtime-мешу; масштаб — по ящику габаритов
    по осям. Форма и цвет товара те же, меняется только то, что в runtime-копии потеряно (чёткость текстуры, карта шероховатости)."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in set(bpy.data.objects) - before if o.type == 'MESH']
    mws = {o: o.matrix_world.copy() for o in new}
    P = np.concatenate([np.array([tuple(mws[o] @ v.co) for v in o.data.vertices]) for o in new])
    rc, oc = (rt_v.min(0) + rt_v.max(0)) / 2, (P.min(0) + P.max(0)) / 2
    rd = rt_v.max(0) - rt_v.min(0)
    rng = np.random.default_rng(1)
    A_ = rt_v[rng.choice(len(rt_v), min(1200, len(rt_v)), replace=False)] - rc
    B_ = P[rng.choice(len(P), min(1200, len(P)), replace=False)] - oc
    best = None
    for k in range(4):
        c_, s_ = math.cos(math.pi / 2 * k), math.sin(math.pi / 2 * k)
        R = np.array([[c_, -s_, 0.0], [s_, c_, 0.0], [0.0, 0.0, 1.0]])
        Q = (P - oc) @ R.T
        qd = Q.max(0) - Q.min(0)
        S = rd / qd
        Bq = ((B_ @ R.T) * S)
        d = np.sqrt(((A_[:, None, :] - Bq[None, :, :]) ** 2).sum(-1))
        score = float(d.min(1).mean() + d.min(0).mean())
        if best is None or score < best[0]:
            best = (score, k, R, S, qd)
    _, k, R, S, qd = best
    print(f'оригинал {os.path.basename(path)}: поворот {90 * k}°, масштаб по осям {np.round(S, 3).tolist()}, расстояние облаков {best[0]:.4f} м')
    T = Matrix.Translation(Vector(rc)) @ Matrix.Diagonal(Vector((*S, 1.0))) @ Matrix(R.tolist()).to_4x4() @ Matrix.Translation(Vector(-oc))
    for o in new:
        mw = mws[o]
        o.parent = None
        o.data.transform(T @ mw)
        o.matrix_world = Matrix.Identity(4)
        o.visible_shadow = True
    bpy.data.objects.remove(rt_ob, do_unlink=True)
    return new


def soft_tweaks(mat, fabric=None):
    """Sheen (ворс/ткань: рассеянный блик по краям) и мелкий рельеф плетения поверх материала меша — цвет и форма не меняются."""
    nt = mat.node_tree
    bs = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bs is None:
        return
    # У меша один материал на всё: деревянные ножки получили бы тот же ворс и плетение. Грубая маска по геометрии — высота от пола
    # (координата Object = мир, вершины запечены): ниже `soft_min_z` м — ножки (маска 0), выше `soft_min_z + 0.06` — ткань (маска 1).
    mtc = nt.nodes.new('ShaderNodeTexCoord')
    msep = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(mtc.outputs['Object'], msep.inputs['Vector'])
    mrng = nt.nodes.new('ShaderNodeMapRange')
    mrng.inputs['From Min'].default_value = a.soft_min_z
    mrng.inputs['From Max'].default_value = a.soft_min_z + 0.06
    nt.links.new(msep.outputs['Z'], mrng.inputs['Value'])
    mask = mrng.outputs['Result']
    if a.sheen > 0:
        sw = nt.nodes.new('ShaderNodeMath')
        sw.operation = 'MULTIPLY'
        sw.inputs[1].default_value = a.sheen
        nt.links.new(mask, sw.inputs[0])
        nt.links.new(sw.outputs['Value'], bs.inputs['Sheen Weight'])
        bs.inputs['Sheen Roughness'].default_value = a.sheen_rough
        bs.inputs['Sheen Tint'].default_value = (1.0, 1.0, 1.0, 1.0)
    if a.soft_rough >= 0:
        # шероховатость ткани — число (стартовое значение Codex), ножки — как в карте меша
        rl = next((l for l in nt.links if l.to_socket == bs.inputs['Roughness']), None)
        mx = nt.nodes.new('ShaderNodeMix')
        mx.data_type = 'FLOAT'
        mx.inputs[3].default_value = a.soft_rough            # B
        if rl is not None:
            nt.links.new(rl.from_socket, mx.inputs[2])      # A — прежнее
        else:
            mx.inputs[2].default_value = bs.inputs['Roughness'].default_value
        nt.links.new(mask, mx.inputs[0])
        nt.links.new(mx.outputs[1], bs.inputs['Roughness'])
    if fabric and not bs.inputs['Normal'].is_linked:
        tc = nt.nodes.new('ShaderNodeTexCoord')
        mp = nt.nodes.new('ShaderNodeMapping')
        sc_ = 100.0 / a.fabric_tile
        mp.inputs['Scale'].default_value = (sc_, sc_, sc_)
        nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])
        tn = nt.nodes.new('ShaderNodeTexImage')
        im = bpy.data.images.load(fabric, check_existing=True)
        im.colorspace_settings.name = 'Non-Color'
        tn.image = im
        tn.interpolation = 'Cubic'
        tn.projection = 'BOX'
        tn.projection_blend = 0.2
        nt.links.new(mp.outputs['Vector'], tn.inputs['Vector'])
        nm = nt.nodes.new('ShaderNodeNormalMap')
        km = nt.nodes.new('ShaderNodeMath')
        km.operation = 'MULTIPLY'
        km.inputs[1].default_value = a.fabric_k
        nt.links.new(mask, km.inputs[0])
        nt.links.new(km.outputs['Value'], nm.inputs['Strength'])
        nt.links.new(tn.outputs['Color'], nm.inputs['Color'])
        nt.links.new(nm.outputs['Normal'], bs.inputs['Normal'])


# ---------------- предметы (меши с текстурами) ----------------
mat_cache = {}
ROLE_OBJ = {}
for o in M['objs']:
    z = np.load(os.path.join(a.scene_dir, o['file']))
    role = o['role'].split(' ')[0]
    if o['tex']:
        mr_ = o.get('mr') if a.mr else None
        tint_ = tuple(o['tint']) if o.get('tint') else None
        key = ('t', o['tex'], role, mr_, tint_)
        if key not in mat_cache:
            mat_cache[key] = principled('m_' + os.path.basename(o['tex']), tex=o['tex'], rough=ROUGH.get(role, 0.55), tex_lite=a.lite_tex, mr=mr_, tint=tint_)
        mat = mat_cache[key]
    else:
        rgb = tuple(c / 255.0 for c in o['rgb'])
        tint_ = tuple(o['tint']) if o.get('tint') else None
        key = ('c', rgb, role, tint_)
        if key not in mat_cache:
            rough = 0.3 if role == 'тв' else 0.6
            mat_cache[key] = principled('c_' + o['role'], rgb, rough=rough, tint=tint_)
        mat = mat_cache[key]
    vv = z['v']
    if o['n_faces'] == 12 and not o['tex']:
        # простые коробки (рама окна, плинтус, карниз) касаются друг друга совпадающими гранями — в Cycles в углах чёрные пятна самотени;
        # растягиваем каждую на доли миллиметра по-разному, чтобы грани не лежали в одной плоскости
        k_ = int(o['file'][1:4])
        vv = vv.mean(axis=0) + (vv - vv.mean(axis=0)) * (1.0 + 0.0006 * (1 + k_ % 4))
    ob = make_obj(o['file'], vv, z['f'], uvs=z['uv'] if 'uv' in z.files else None, mat=mat, smooth=False)
    ROLE_OBJ.setdefault(o['role'], ob)
    if o['tex'] and a.smooth_deg > 0:
        smooth_by_angle(ob, a.smooth_deg)
    _orig = dict(s.split(':', 1) for s in a.orig)
    _swapped = bool(role in _orig and o['tex'])
    if _swapped:
        _new = swap_original(ob, vv, _orig[role])
        ob = _new[0]
        for _o in _new:
            for _m in _o.data.materials:
                if _m and _m.use_nodes:
                    _b = next((n for n in _m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                    if _b is not None and a.orig_rough >= 0:
                        _b.inputs['Roughness'].default_value = a.orig_rough
    if role in SOFT and (a.sheen > 0 or a.fabric):
        for _o in (_new if _swapped else [ob]):
            for _m in _o.data.materials:
                if _m and _m.use_nodes:
                    soft_tweaks(_m, a.fabric)
    if a.lamps > 0 and role in ('торшер', 'лампа'):
        # «мёртвая лампа» (владелец, TG 1319): у светильника в данных нет источника — ставим точечный свет у плафона; плафон не отбрасывает тень,
        # иначе замкнутая оболочка закроет свет. Только лампы; сама модель (геометрия, текстура) не меняется.
        _p = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        _zt, _zb = max(p.z for p in _p), min(p.z for p in _p)
        _lm = bpy.data.lights.new('lamp_' + role, 'POINT')
        _lm.energy = a.lamps
        _lm.shadow_soft_size = 0.06
        _lm.color = kelvin_rgb(a.lamp_k or 2700)
        _lo = bpy.data.objects.new('lamp_' + role, _lm)
        sc.collection.objects.link(_lo)
        _lo.location = (sum(p.x for p in _p) / 8, sum(p.y for p in _p) / 8, _zt - 0.18 * (_zt - _zb) if role == 'торшер' else _zt - 0.25 * (_zt - _zb))
        ob.visible_shadow = False

def rug_silhouette(msk):
    """Силуэт ковра (T-20261118-03/3): фон — только то, что СВЯЗАНО с краем кадра фото; светлые блики и пятна ВНУТРИ ковра — это ковёр.
    Иначе эрозия `--rug-erode` съедала по 10 px вокруг каждой внутренней «дырки» (≈ 3 % площади светлого ковра) и крошила ковёр на клочья
    (боевой пресет, любой светлый ковёр), а светлые участки рисунка были прозрачными. Только numpy (в Blender нет scipy)."""
    bgm = ~msk
    reach = np.zeros_like(bgm)
    reach[0, :], reach[-1, :], reach[:, 0], reach[:, -1] = bgm[0, :], bgm[-1, :], bgm[:, 0], bgm[:, -1]
    for _ in range(sum(msk.shape)):                 # рост от края до устойчивости (не больше полупериметра)
        g = reach.copy()
        g[1:] |= reach[:-1]
        g[:-1] |= reach[1:]
        g[:, 1:] |= reach[:, :-1]
        g[:, :-1] |= reach[:, 1:]
        g &= bgm
        if (g == reach).all():
            break
        reach = g
    return ~reach


# ковёр: фото сверху с вырезом по цвету фона (как `_paste_rug`)
for k, r in enumerate(M['rugs']):
    img = bpy.data.images.load(os.path.join(a.scene_dir, r['tex']))
    Wi, Hi = img.size
    px = np.array(img.pixels[:], np.float32).reshape(Hi, Wi, 4)[::-1]    # сверху вниз
    rgb = px[..., :3]
    corn = np.concatenate([rgb[:6, :6].reshape(-1, 3), rgb[:6, -6:].reshape(-1, 3), rgb[-6:, :6].reshape(-1, 3), rgb[-6:, -6:].reshape(-1, 3)])
    bg = np.median(corn, axis=0)
    dist = np.linalg.norm(rgb - bg, axis=2) * 255.0
    msk = dist > 22
    if msk.mean() < 0.30:
        msk[:] = True
    msk = rug_silhouette(msk)
    # светлая кайма по краю ковра (подложка/полутон фото на границе выреза) — съедаем краевые пиксели маски: `--rug-erode` = доля ширины ковра
    _ys0, _xs0 = np.where(msk)
    for _ in range(int(round(a.rug_erode * (_xs0.max() - _xs0.min() + 1)))):
        _m = msk.copy()
        _m[1:] &= msk[:-1]
        _m[:-1] &= msk[1:]
        _m[:, 1:] &= msk[:, :-1]
        _m[:, :-1] &= msk[:, 1:]
        msk = _m
    ys, xs = np.where(msk)
    bx0, bx1, by0, by1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
    mimg = bpy.data.images.new('rugmask', Wi, Hi)
    mm = np.zeros((Hi, Wi, 4), np.float32)
    mm[..., :3] = msk[..., None]
    mm[..., 3] = 1
    mimg.pixels = mm[::-1].ravel()
    hw, hd = r['w'] / 2, r['d'] / 2
    ang = math.radians(r['rot'])
    ca, sa = math.cos(ang), math.sin(ang)
    corners, uvs = [], []
    rot90 = (bw >= bh) != (r['w'] >= r['d'])
    for dx_, dz_, u, v in ((-hw, -hd, 0, 0), (hw, -hd, 1, 0), (hw, hd, 1, 1), (-hw, hd, 0, 1)):
        corners.append(b(r['x'] + dx_ * ca + dz_ * sa, 0.8, r['y'] - dx_ * sa + dz_ * ca))
        ua, va = (v, 1.0 - u) if rot90 else (u, v)
        uvs.append(((bx0 + ua * bw) / Wi, 1.0 - (by0 + va * bh) / Hi))
    rm = bpy.data.materials.new('rug')
    rm.use_nodes = True
    n = rm.node_tree
    bsdf = n.nodes['Principled BSDF']
    t1 = n.nodes.new('ShaderNodeTexImage')
    t1.image = img
    t2 = n.nodes.new('ShaderNodeTexImage')
    t2.image = mimg
    t2.interpolation = 'Closest'
    n.links.new(t1.outputs['Color'], bsdf.inputs['Base Color'])
    n.links.new(t2.outputs['Color'], bsdf.inputs['Alpha'])
    bsdf.inputs['Roughness'].default_value = 0.95
    make_obj(f'rug{k}', corners, [(0, 3, 2, 1)], uvs=uvs, mat=rm, smooth=False)

# ---------------- декор из сцены /demo (шторы, карниз, картины, люстра, подушки) ----------------
# Файл делает `demo_scene_dump.mjs` тем же движком и тем же расчётом мест, что живая сцена /demo: здесь только вставка в Blender
# (оси glTF → Blender импортёр переводит так же, как `b()`: (x, y, z) → (x, −z, y)) и свет люстры.
if a.demo_glb:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=a.demo_glb)
    info = {n['uuid']: n for n in json.load(open(a.demo_nodes, encoding='utf-8'))}
    chand, art_nodes = [], []
    for ob in set(bpy.data.objects) - before:
        if ob.type != 'MESH':
            continue
        uu = ob.name.split('__')[-1].split('.')[0]
        slot = (info.get(uu) or {}).get('slot', '')
        for m in ob.data.materials:
            if m and m.use_nodes:
                bs_ = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                if bs_ is not None and 'люстр' not in slot:
                    bs_.inputs['Roughness'].default_value = max(bs_.inputs['Roughness'].default_value, 0.8 if 'textile' in slot else 0.5)
        if a.sheen > 0 and slot.startswith('textile'):
            for m in ob.data.materials:
                if m and m.use_nodes:
                    soft_tweaks(m)
        if a.sheer < 1.0 and 'штор' in slot:
            # тюль: в /demo штора — сплошная ткань; на кадре сквозь неё должно быть видно окно (на фото-образце шторы раздвинуты). Только вид кадра, меш не меняется.
            for m in ob.data.materials:
                bs2_ = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if m and m.use_nodes else None
                if bs2_ is not None and not bs2_.inputs['Alpha'].is_linked:
                    bs2_.inputs['Alpha'].default_value = a.sheer
        if slot.startswith('картина'):
            art_nodes.append((slot, ob))
        if 'люстр' in slot:
            chand.append(ob)
        if slot.startswith('textile:подушка') or slot.startswith('textile:плед') or 'люстр' in slot:   # плед — тоже сглаженный (граненый брусок читался как доска)
            smooth_by_angle(ob, 50)
    if art_nodes and a.art_guard:
        # СТОРОЖ КАРТИН (T-20261117-16/2, владелец TG 1567/1568: «картины пустые белые»): текстура есть и это не белое поле — иначе кадр не сдаём
        _titles = {}
        try:
            _si = json.load(open(os.path.join(os.path.dirname(os.path.abspath(a.demo_nodes)), 'scene_info.json'), encoding='utf-8'))
            _titles = {x['slotId']: x.get('title') for x in _si.get('slots', [])}
        except Exception:
            pass
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
        import wall_art as _WA                       # то же правило, что при отборе в набор (`wall_art.has_content`, данные — `data/flat3d/wall-art.json:art_content`)
        _R = _WA.rules()
        _bad = []
        for _slot in sorted(set(x[0] for x in art_nodes)):
            # у картины несколько мешей (рама, полотно): текстура — у полотна; нет ни одной — ошибка
            _imgs = [n.image for _s, _ob in art_nodes if _s == _slot for m in _ob.data.materials if m and m.use_nodes
                     for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image]
            if not _imgs:
                _bad.append((_slot, 'нет текстуры'))
                continue
            _img = max(_imgs, key=lambda im: im.size[0] * im.size[1])
            _w, _h = _img.size
            _px = np.empty(_w * _h * 4, np.float32)
            _img.pixels.foreach_get(_px)
            _px = _px.reshape(_h, _w, 4)[:, :, :3]
            _m = _WA.canvas_metrics(_px * 255.0, _R)                 # та же мера, что при отборе (центр + вся площадь, T-20261118-03/2)
            if not _WA.has_content(_m, _R):
                _bad.append((_slot, f"нет рисунка (белое/тон-в-тон), цвет {_m['chroma']:.0f}, яркость {_m['luma']:.0f}, рисунок {(_m['ink_d'] >= _R['art_content']['ink_delta']).mean() * 100:.1f} % площади"))
        for _slot, _why in _bad:
            print('СТОРОЖ КАРТИН:', _slot, '·', _titles.get(_slot) or '?', '·', _why)
        if _bad and not a.art_allow_blank:
            raise SystemExit('ошибка кадра: ' + '; '.join(f"{(_titles.get(s_) or s_)} ({w_})" for s_, w_ in _bad))
    if a.plant_swap:
        # ЗАМЕНА РАСТЕНИЯ ДЛЯ ПРИМЕРКИ (T-20261117-21): у узлов `plant:<слот>` (в `demo_nodes_uuids.json` — `plant: true`) берём общий габарит,
        # убираем их и ставим на то же место (центр основания, низ) модель кандидата (`plant_candidates.py`, Y вверх, низ в нуле) той же высоты
        # (`--plant-h` см — иначе высота прежнего). Меняется ТОЛЬКО растение, комната, свет и ракурс те же — кадры «было / стало» сравнимы.
        groups = {}
        for ob in set(bpy.data.objects) - before:
            if ob.type == 'MESH' and (info.get(ob.name.split('__')[-1].split('.')[0]) or {}).get('plant'):
                slot_ = info[ob.name.split('__')[-1].split('.')[0]].get('slot', '')
                if a.plant_slot in slot_:
                    groups.setdefault(slot_, []).append(ob)
        if a.plant_on and a.plant_on in ROLE_OBJ:
            # растение СВЕРХУ на предмете (тумба): точка у края длинной стороны верхней плоскости, низ — на верхней плоскости
            _bp = [ROLE_OBJ[a.plant_on].matrix_world @ Vector(c) for c in ROLE_OBJ[a.plant_on].bound_box]
            _bx0, _bx1 = min(p.x for p in _bp), max(p.x for p in _bp)
            _by0, _by1 = min(p.y for p in _bp), max(p.y for p in _bp)
            _top = max(p.z for p in _bp)
            _fr = a.plant_on_frac
            if (_bx1 - _bx0) >= (_by1 - _by0):
                _cx, _cy = _bx0 + (_bx1 - _bx0) * _fr, (_by0 + _by1) / 2
            else:
                _cx, _cy = (_bx0 + _bx1) / 2, _by0 + (_by1 - _by0) * _fr
            groups = {'on:' + a.plant_on: []}
            _on_box = (_cx, _cx, _cy, _cy, _top, _top + max(a.plant_h, 20) / 100.0)
        for slot_, obs in sorted(groups.items())[:a.plant_n]:
            if slot_.startswith('on:'):
                x0, x1, y0, y1, z0, z1 = _on_box
            else:
                pts = [ob.matrix_world @ Vector(c) for ob in obs for c in ob.bound_box]
                x0, x1 = min(p.x for p in pts), max(p.x for p in pts)
                y0, y1 = min(p.y for p in pts), max(p.y for p in pts)
                z0, z1 = min(p.z for p in pts), max(p.z for p in pts)
            for ob in obs:
                bpy.data.objects.remove(ob, do_unlink=True)
            pre = set(bpy.data.objects)
            bpy.ops.import_scene.gltf(filepath=a.plant_swap)
            new = [o for o in set(bpy.data.objects) - pre]
            bpy.context.view_layer.update()   # без этого matrix_world новых узлов ещё единичная — размеры считались по сырым осям (Y вверх)
            meshes = [o for o in new if o.type == 'MESH']
            npts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
            hh = max(p.z for p in npts) - min(p.z for p in npts)
            tgt = (a.plant_h / 100.0) if a.plant_h > 0 else (z1 - z0)
            k = tgt / max(hh, 1e-6)
            ww = max(max(p.x for p in npts) - min(p.x for p in npts), max(p.y for p in npts) - min(p.y for p in npts), 1e-6)
            k = min(k, a.plant_wmax / ww)   # розетка (низкая и широкая) не раздувается до высоты прежнего растения
            for o in new:
                if o.parent is None:
                    o.scale = (o.scale.x * k, o.scale.y * k, o.scale.z * k)   # у узла сырого GLB уже есть масштаб квантования (≈2e-5): умножаем, не заменяем
                    o.location = ((x0 + x1) / 2, (y0 + y1) / 2, z0)
            bpy.context.view_layer.update()
            # точная посадка по фактическим границам после масштаба: центр основания на место прежнего, низ — на его низ
            npts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
            sx = (x0 + x1) / 2 - (min(p.x for p in npts) + max(p.x for p in npts)) / 2
            sy = (y0 + y1) / 2 - (min(p.y for p in npts) + max(p.y for p in npts)) / 2
            sz = z0 - min(p.z for p in npts)
            for o in new:
                if o.parent is None:
                    o.location = (o.location.x + sx, o.location.y + sy, o.location.z + sz)
            bpy.context.view_layer.update()
            print(f'PLANT_SWAP {slot_}: высота {tgt * 100:.0f} см, место ({(x0 + x1) / 2:.2f}, {(y0 + y1) / 2:.2f}, {z0:.2f}), масштаб {k:.2f}')
    if chand and a.chandelier > 0:
        pts = [ob.matrix_world @ Vector(c) for ob in chand for c in ob.bound_box]
        cx = sum(p.x for p in pts) / len(pts)
        cy_ = sum(p.y for p in pts) / len(pts)
        zc = (min(p.z for p in pts) + max(p.z for p in pts)) / 2
        lamp = bpy.data.lights.new('chandelier', 'POINT')
        lamp.energy = a.chandelier
        lamp.shadow_soft_size = 0.12
        lamp.color = kelvin_rgb(a.lamp_k) if a.lamp_k > 0 else (1.0, 0.86, 0.66)
        lo = bpy.data.objects.new('chandelier', lamp)
        sc.collection.objects.link(lo)
        lo.location = (cx, cy_, zc)
        print('люстра: свет в', lo.location, 'Вт', a.chandelier)

# ---------------- камера ----------------
def setup_camera(cam_name):
    """Ракурс `cam_name` целиком (поза, правила позы «Б», объектив) — глобальные cd/cam/co/right/up/fwd/pose_b обновляются."""
    global cd, pose_b, cam, co, right, up, fwd, rot, mat4, _wins
    cd = dict(next(c for c in M['cams'] if c['name'] == cam_name))
    _wins = [o['wall'] for o in M['openings'] if o['kind'] in ('window', 'balcony')]
    pose_b = False   # правила позы «Б» включаются только для позы витрины (ветка else ниже)
    if a.live_cam:
        # КАМЕРА ЖИВОЙ 3D КАК НА СТРАНИЦЕ (владелец TG 1504/1505): положение, взгляд и угол — из `live_cam.json` (`demo_scene_dump.mjs livecam=…`: тот же
        # движок и те же вызовы, что у /demo). Оси: три (x, высота, план_y, метры) → Blender (x, −план_y, высота). Без позы «Б» и подгонок.
        _lc = json.load(open(a.live_cam, encoding='utf-8'))
        _cv = lambda v: Vector((v[0], -v[2], v[1]))
        _lf, _lu = _cv(_lc['dir']).normalized(), _cv(_lc['up']).normalized()
        _lr = _lf.cross(_lu).normalized()
        _asp = _lc['w'] / _lc['h']
        cd.update({'eye': list(_cv(_lc['pos'])), 'fwd': list(_lf), 'up': list(_lu), 'right': list(_lr),
                   'fov': math.degrees(2 * math.atan(math.tan(math.radians(_lc['vfov']) / 2) * _asp)), 'shift_y': 0.0,
                   'w': int(round(_lc['w'] * a.live_scale)), 'h': int(round(_lc['h'] * a.live_scale))})
        print('камера живой 3D:', [round(x, 3) for x in cd['eye']], 'взгляд', [round(x, 3) for x in cd['fwd']], 'угол по горизонтали', round(cd['fov'], 1), 'кадр', cd['w'], 'x', cd['h'])
    elif a.eye and a.aim:
        # явный ракурс (метры, оси Blender: x вправо, y = −план_y): глаз и точка, куда смотрим; взгляд горизонтальный
        _e = [float(t) for t in a.eye.split(',')]
        _t = [float(t) for t in a.aim.split(",")]
        _eye = Vector((_e[0], _e[1], a.cam_h or 1.35))
        _f = Vector((_t[0] - _e[0], _t[1] - _e[1], 0.0))
        _f.normalize()
        cd.update({'eye': list(_eye), 'fwd': list(_f), 'up': [0.0, 0.0, 1.0], 'right': [_f.y, -_f.x, 0.0]})
    elif a.cam_auto and _wins[:1] in (['west'], ['east']):
        # ракурс С ОКНОМ для сравнения с фото (Codex 17.11): глаз в дальнем от окна углу, взгляд горизонтальный (вертикали прямые) в сторону окна и
        # глубины комнаты; объектив — `--lens` (мм, полный кадр). Только проба сетки настроек: общие позы /demo — отдельная задача (шаг 5 плана).
        _x_far = W / 100.0 - 0.4 if _wins[0] == 'west' else 0.4
        _eye = Vector((_x_far, -0.4, a.cam_h or 1.4))
        _tgt = Vector((W / 100.0 * (0.3 if _wins[0] == 'west' else 0.7), -D / 100.0 * 0.85, _eye.z))
        _f = (_tgt - _eye)
        _f.z = 0.0
        _f.normalize()
        cd.update({'eye': list(_eye), 'fwd': list(_f), 'up': [0.0, 0.0, 1.0], 'right': [_f.y, -_f.x, 0.0]})
    else:
        # поза /demo по умолчанию — вариант «Б» (владелец TG 1423; Codex 17.11 п.1): глаз 1,35 м, взгляд горизонтальный (вертикали прямые),
        # пол добирает сдвиг объектива вниз 0,15 доли высоты; правила долей — ниже (низкий глаз при малом поле пола, чистый передний план).
        # `--pose-mode demo` — старое поведение (поза витрины как есть).
        pose_b = a.pose_mode == 'b' and not a.eye
        _h = a.cam_h if a.cam_h > 0 else (1.35 if pose_b else 0.0)
        if _h > 0:
            cd['eye'] = [cd['eye'][0], cd['eye'][1], _h]
        if a.level or pose_b:
            # взгляд горизонтальный (вертикали стен прямые, Codex): наклон ракурса вниз заменяет сдвиг объектива `--shift-y`
            _f = Vector(cd['fwd'])
            _f.z = 0.0
            _f.normalize()
            cd.update({'fwd': list(_f), 'up': [0.0, 0.0, 1.0], 'right': [_f.y, -_f.x, 0.0]})
    if a.pitch is not None:
        # наклон взгляда вниз на `--pitch` градусов от ГОРИЗОНТА (нужен `--level 1`; вертикали при этом сходятся — в отличие от `--shift-y`)
        _f = Vector(cd['fwd'])
        _f.z = 0.0
        _f.normalize()
        _t = math.radians(a.pitch)
        _fw = _f * math.cos(_t) + Vector((0.0, 0.0, -math.sin(_t)))
        _up = Vector((0.0, 0.0, 1.0)) * math.cos(_t) + _f * math.sin(_t)
        cd.update({'fwd': list(_fw), 'up': list(_up)})
    cd['fov'] = math.degrees(2 * math.atan(18.0 / a.lens)) if a.lens > 0 else cd['fov']
    if a.shift_y is not None:
        cd['shift_y'] = a.shift_y
    elif pose_b:
        cd['shift_y'] = -a.pose_shift
    cam = bpy.data.cameras.new('cam')
    cam.sensor_fit = 'HORIZONTAL'
    cam.lens_unit = 'FOV'
    cam.angle = math.radians(cd['fov'])
    cam.shift_y = cd['shift_y'] * cd['h'] / cd['w']   # у кадра сервера минус — картинка вверх; у Blender так же (проверено по кадру T-61)
    cam.clip_start = 0.06    # как NEAR_CM=5 см серверного кадра: то, что вплотную к объективу, не рисуется
    cam.clip_end = 100.0
    co = bpy.data.objects.new('cam', cam)
    sc.collection.objects.link(co)
    right, up, fwd = (Vector(cd[k]).normalized() for k in ('right', 'up', 'fwd'))
    rot = np.array([[right.x, up.x, -fwd.x], [right.y, up.y, -fwd.y], [right.z, up.z, -fwd.z]])
    from mathutils import Matrix
    mat4 = Matrix.Identity(4)
    for i in range(3):
        for j in range(3):
            mat4[i][j] = rot[i, j]
    mat4.translation = Vector(cd['eye'])
    co.matrix_world = mat4
    sc.camera = co
    sc.render.resolution_x, sc.render.resolution_y = cd['w'], cd['h']
    sc.render.resolution_percentage = a.pct
    print('det камеры', float(np.linalg.det(rot)))

    # ---------------- правила позы «Б» (T-20261117-12/2, владелец TG 1423): доля пола и чистый передний план ----------------
    def frame_probe(eye):
        """Сетка лучей по кадру из `eye`: доля пола (ковёр — пол) и доля кадра, закрытая предметом ближе `--near` м. Общий расчёт для любой комнаты."""
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        T = math.tan(math.radians(cd['fov']) / 2)
        ratio = cd['h'] / cd['w']
        nx_, ny_ = 48, 36
        floor_n = near_n = 0
        for j in range(ny_):
            v = (j + 0.5) / ny_
            for i in range(nx_):
                u = (i + 0.5) / nx_
                dc = Vector(((2 * u - 1) * T, (1 - 2 * v) * T * ratio + cam.shift_y * 2 * T, -1.0)).normalized()
                d = right * dc.x + up * dc.y + fwd * (-dc.z)
                if d.z < -1e-6:      # зона пола: куда луч упал бы на пол комнаты, если бы мебели не было (стена — выше, потолок — не в счёт)
                    t_ = -eye[2] / d.z
                    px_, py_ = eye[0] + d.x * t_, eye[1] + d.y * t_
                    if 0.0 <= px_ <= W / 100.0 and -D / 100.0 <= py_ <= 0.0:
                        floor_n += 1
                hit, loc, nrm, _idx, ob, _m = sc.ray_cast(dg, Vector(eye), d, distance=100.0)
                if not hit:
                    continue
                if nrm.z > 0.85 and loc.z < 0.05:
                    continue
                dims = sorted(ob.dimensions)
                if dims[2] > 2.0 and dims[0] < 0.3:      # стена, потолок, штора во всю стену — оболочка, не предмет
                    continue
                if v >= 0.5 and (loc - Vector(eye)).length < a.near:      # нижняя половина кадра закрыта предметом ближе `--near` м
                    near_n += 1
        return floor_n / (nx_ * ny_), near_n / (nx_ * ny_ / 2)


    def set_eye(eye):
        cd['eye'] = list(eye)
        m_ = co.matrix_world.copy()
        m_.translation = Vector(eye)
        co.matrix_world = m_


    if pose_b:
        _eye = Vector(cd['eye'])
        fl, nr = frame_probe(_eye)
        log = f'поза Б: глаз {_eye.z:.2f} м, пол {fl * 100:.0f} %, передний план (нижняя половина кадра, ближе {a.near} м) {nr * 100:.0f} %'
        if fl < a.floor_min and _eye.z > a.eye_low + 1e-6:
            eye_hi, fl_hi, nr_hi = _eye.z, fl, nr
            _eye.z = a.eye_low
            set_eye(_eye)
            fl, nr = frame_probe(_eye)
            log += f' → глаз {a.eye_low} м: пол {fl * 100:.0f} %, передний план {nr * 100:.0f} %'
            if nr > a.occl and nr > nr_hi:
                # низкий глаз закрывает кадр предметом сильнее (спинка кровати, столик), а пол до порога всё равно не дотянул — чистый кадр важнее
                _eye.z = eye_hi
                set_eye(_eye)
                fl, nr = fl_hi, nr_hi
                log += f' → низкий глаз закрывает кадр сильнее ({nr * 100:.0f} % при {eye_hi} м), оставлен {eye_hi} м'
        if nr > a.occl:
            fh = Vector((fwd.x, fwd.y, 0.0)).normalized()
            back = -fh
            hit, loc, _n, _i, _o, _m = sc.ray_cast(bpy.context.evaluated_depsgraph_get(), _eye, back, distance=a.back_max + 0.5)
            tmax = a.back_max if not hit else max(0.0, min(a.back_max, (loc - _eye).length - 0.3))
            best = (nr, 0.0)
            t = 0.0
            while t < tmax - 1e-6:
                t = min(tmax, t + 0.1)
                e2 = _eye + back * t
                fl2, nr2 = frame_probe(e2)
                if nr2 < best[0]:
                    best = (nr2, t)
                if nr2 <= a.occl:
                    break
            if best[1] > 0:
                set_eye(_eye + back * best[1])
                fl, nr = frame_probe(Vector(cd['eye']))
                log += f' → камера назад на {best[1]:.1f} м (предел {tmax:.1f} м): пол {fl * 100:.0f} %, передний план {nr * 100:.0f} %'
            else:
                log += f' → отодвинуть некуда (предел {tmax:.1f} м)'
            if nr > a.occl:
                # назад некуда или не помогло — поднять кадр (сдвиг объектива вверх шагом 0,05, до горизонта), пока пол не ниже порога долей
                sh0 = cam.shift_y
                best_s = (nr, sh0)
                k_ = 0
                while cd['shift_y'] + 0.05 * (k_ + 1) <= 1e-9:
                    k_ += 1
                    cam.shift_y = (cd['shift_y'] + 0.05 * k_) * cd['h'] / cd['w']
                    fl2, nr2 = frame_probe(Vector(cd['eye']))
                    log += f' [сдвиг {cd["shift_y"] + 0.05 * k_:.2f}: пол {fl2 * 100:.0f} %, пл. {nr2 * 100:.0f} %]'
                    if fl2 < a.floor_min * a.floor_keep:        # пол не должен пропасть: доля порога долей, параметр
                        break
                    if nr2 < best_s[0]:
                        best_s = (nr2, cam.shift_y)
                    if nr2 <= a.occl:
                        break
                cam.shift_y = best_s[1]
                if best_s[1] != sh0:
                    cd['shift_y'] = best_s[1] * cd['w'] / cd['h']
                    fl, nr = frame_probe(Vector(cd['eye']))
                    log += f' → кадр поднят: сдвиг {cd["shift_y"]:.2f}, пол {fl * 100:.0f} %, передний план {nr * 100:.0f} %'
                else:
                    cam.shift_y = sh0
        print(log)



# ---------------- свет ----------------
world = bpy.data.worlds.new('w')
sc.world = world
world.use_nodes = True
wn = world.node_tree
bgn = wn.nodes['Background']
win = next((o['wall'] for o in M['openings'] if o['kind'] in ('window', 'balcony')), 'west')
(_, _), (_, _), (nx, nz) = FR[win]
inward = Vector((nx, -nz, 0.0))               # внутрь комнаты, мир Blender
if a.hdri:
    # настоящее небо (HDRI Poly Haven, CC0): солнце HDRI поворачиваем в сторону окна — свет и цвет неба берутся из него, Sun-лампа не нужна
    himg = bpy.data.images.load(a.hdri)
    hw_, hh_ = himg.size
    hpx = np.array(himg.pixels[:], np.float32).reshape(hh_, hw_, 4)
    lum = hpx[..., 0] * 0.2126 + hpx[..., 1] * 0.7152 + hpx[..., 2] * 0.0722
    row, col = np.unravel_index(int(np.argmax(lum)), lum.shape)
    phi = ((col + 0.5) / hw_ - 0.5) * 2 * math.pi                # u → азимут в системе Blender (dir.x = −cos φ, dir.y = sin φ)
    elev_h = ((row + 0.5) / hh_ - 0.5) * math.pi
    az_h = math.pi - phi
    az_t = math.atan2(-inward.y, -inward.x)                       # к солнцу — наружу через окно
    envn = wn.nodes.new('ShaderNodeTexEnvironment')
    envn.image = himg
    mp = wn.nodes.new('ShaderNodeMapping')
    mp.inputs['Rotation'].default_value = (0, 0, az_h - az_t)
    tcn = wn.nodes.new('ShaderNodeTexCoord')
    wn.links.new(tcn.outputs['Generated'], mp.inputs['Vector'])
    wn.links.new(mp.outputs['Vector'], envn.inputs['Vector'])
    wn.links.new(envn.outputs['Color'], bgn.inputs['Color'])
    bgn.inputs['Strength'].default_value = a.hdri_strength
    print(f'HDRI солнце: высота {math.degrees(elev_h):.1f}°, яркость {lum.max():.0f}, поворот {math.degrees(az_h - az_t):.0f}°')
    el = elev_h
else:
    sky = wn.nodes.new('ShaderNodeTexSky')
    for _t in ('NISHITA', 'MULTIPLE_SCATTERING'):       # в Blender 5.x тип переименован
        try:
            sky.sky_type = _t
            break
        except TypeError:
            continue
    sky.sun_disc = False
    sky.sun_elevation = math.radians(38)
    sky.air_density = 1.0
    if hasattr(sky, 'dust_density'):
        sky.dust_density = 1.2
    if a.sky_sat != 1.0:
        hs = wn.nodes.new('ShaderNodeHueSaturation')
        hs.inputs['Saturation'].default_value = a.sky_sat
        wn.links.new(sky.outputs['Color'], hs.inputs['Color'])
        wn.links.new(hs.outputs['Color'], bgn.inputs['Color'])
    else:
        wn.links.new(sky.outputs['Color'], bgn.inputs['Color'])
    bgn.inputs['Strength'].default_value = a.sky
    el = math.radians(38)
tr = Vector((inward.x * math.cos(el), inward.y * math.cos(el), -math.sin(el)))   # куда идёт свет
if a.sun > 0:
    sun = bpy.data.lights.new('sun', 'SUN')
    sun.energy = a.sun
    sun.angle = math.radians(a.sun_angle)
    sun.color = (1.0, 0.98, 0.95)
    so = bpy.data.objects.new('sun', sun)
    sc.collection.objects.link(so)
    so.rotation_euler = tr.to_track_quat('-Z', 'Y').to_euler()

if a.portal:
    # световой портал в проёме окна: не источник, а подсказка Cycles, откуда небо заходит в комнату (меньше шума при том же времени)
    wc = next((c for c in M['cuts'].get(win, []) if c['kind'] in ('window', 'balcony')), None)
    if wc is not None:
        (ox, oz), (dx, dz), _n = FR[win]
        uc, vc = (wc['u0'] + wc['u1']) / 2, (wc['bottom'] + wc['top']) / 2
        pl = bpy.data.lights.new('portal', 'AREA')
        pl.shape = 'RECTANGLE'
        pl.size, pl.size_y = (wc['u1'] - wc['u0']) / 100.0, (wc['top'] - wc['bottom']) / 100.0
        try:
            pl.cycles.is_portal = True
        except AttributeError:
            print('портал: нет свойства is_portal в этой версии')
        po = bpy.data.objects.new('portal', pl)
        sc.collection.objects.link(po)
        po.location = b(ox + dx * uc, vc, oz + dz * uc)
        po.rotation_euler = inward.to_track_quat('-Z', 'Y').to_euler()

fill = bpy.data.lights.new('fill', 'AREA')
fill.shape = 'RECTANGLE'
fill.size, fill.size_y = 1.6, 1.6
fill.energy = a.fill
fill.color = kelvin_rgb(a.fill_k) if a.lamp_k > 0 else (1.0, 0.97, 0.92)    # заполнение — отражённый дневной свет, не тёплая лампа (в сетке 17.11 при 4200 К весь кадр был оранжевым)
fo = bpy.data.objects.new('fill', fill)
sc.collection.objects.link(fo)
fo.location = (W / 200.0, -D / 200.0, (H - 6) / 100.0)
fo.rotation_euler = (0, 0, 0)
fo.visible_camera = False

def dof_current():
    if a.dof > 0:
        # лёгкая глубина резкости: фокус — середина мебели (предметы с текстурой), диафрагма f/N
        ps = [ob.matrix_world @ Vector(c) for ob in bpy.data.objects if ob.type == 'MESH' and ob.name.startswith('m') and ob.name.endswith('.npz')
              and ob.data.materials and ob.data.materials[0] and ob.data.materials[0].name.startswith('m_') for c in ob.bound_box]
        if ps:
            ctr = sum(ps, Vector()) / len(ps)
            cam.dof.use_dof = True
            cam.dof.focus_distance = (ctr - Vector(cd['eye'])).length
            cam.dof.aperture_fstop = a.dof
            print(f'DoF f/{a.dof}, фокус {cam.dof.focus_distance:.2f} м')


CAMS = [c.strip() for c in a.cam.split(',') if c.strip()]
if len(CAMS) > 1 and '{cam}' not in a.out:
    raise SystemExit('несколько ракурсов: в --out нужен шаблон {cam}, например /x/frame-{cam}.png')
print(f'SCENE_BUILD_SEC {time.time() - T_START:.1f}', flush=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_qa
QA = frame_qa.Guard(a, M, bool(a.qa and a.demo_nodes and a.export))
QA.scene_ready(bpy, np)
for _i, _cn in enumerate(CAMS):
    setup_camera(_cn)
    QA.camera_ready(bpy, co, _cn)
    dof_current()
    _out = a.out.replace('{cam}', _cn)
    os.makedirs(os.path.dirname(os.path.abspath(_out)), exist_ok=True)
    sc.render.filepath = _out
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    if a.also_png:                                   # PNG из «Render Result» (приёмка JPEG); сторож — после, он берёт хеш уже записанного кадра
        _ff = sc.render.image_settings.file_format
        sc.render.image_settings.file_format = 'PNG'
        bpy.data.images['Render Result'].save_render(a.also_png.replace('{cam}', _cn), scene=sc)
        sc.render.image_settings.file_format = _ff
    QA.frame_done(bpy, co, _cn, _out)
    print(f'RENDER_SEC {time.time() - t0:.1f} cam {_cn} frame {_i + 1}/{len(CAMS)} samples {a.samples} pct {a.pct} device {DEVICE_USED} threads {a.threads}', flush=True)

if a.mask_out and len(CAMS) > 1 and '{cam}' not in a.mask_out:
    raise SystemExit('несколько ракурсов: в --mask-out нужен шаблон {cam}')
if a.mask_out:
    _t_mask = time.time()
    # МАСКА ПОВЕРХНОСТЕЙ (после всех обычных кадров, один раз меняем сцену; на каждый ракурс свой файл — шаблон {cam} в --mask-out): каждая поверхность — плоский эмиссионный цвет по имени материала (`floor`, `wall`, `wall_accent`), остальное чёрное; без света, неба, шума
    def _flat(name, rgb):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        nt_ = m.node_tree
        for n_ in list(nt_.nodes):
            nt_.nodes.remove(n_)
        em = nt_.nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = (*rgb, 1.0)
        em.inputs['Strength'].default_value = 1.0
        out_ = nt_.nodes.new('ShaderNodeOutputMaterial')
        nt_.links.new(em.outputs['Emission'], out_.inputs['Surface'])
        return m
    _cat = {'floor': _flat('mk_floor', (1, 0, 0)), 'wall_accent': _flat('mk_accent', (0, 0, 1)), 'wall': _flat('mk_wall', (0, 1, 0))}
    _black = _flat('mk_black', (0, 0, 0))
    for ob_ in bpy.data.objects:
        if ob_.type != 'MESH':
            continue
        for i_, m_ in enumerate(list(ob_.data.materials)):
            nm_ = (m_.name if m_ else '')
            key_ = 'wall_accent' if nm_.startswith('wall_accent') else 'floor' if nm_.startswith('floor') else 'wall' if nm_.startswith('wall') else None
            ob_.data.materials[i_] = _cat[key_] if key_ else _black
    for l_ in list(bpy.data.lights):
        bpy.data.lights.remove(l_)
    wn.nodes.clear() if hasattr(wn.nodes, 'clear') else None
    sc.view_settings.view_transform = 'Standard'
    try:
        sc.view_settings.look = 'None'
    except TypeError:
        pass
    sc.view_settings.exposure = 0.0
    cy.samples = 1
    cy.use_adaptive_sampling = False
    cy.use_denoising = False
    if a.mask_scale != 1.0:
        sc.render.resolution_percentage = max(1, int(round(a.pct * a.mask_scale)))
    for _cn in CAMS:
        setup_camera(_cn)
        _mo = a.mask_out.replace('{cam}', _cn)
        os.makedirs(os.path.dirname(os.path.abspath(_mo)), exist_ok=True)
        sc.render.filepath = _mo
        bpy.ops.render.render(write_still=True)
        print('МАСКА', _cn, _mo, flush=True)
    print(f'MASK_SEC {time.time() - _t_mask:.1f} cams {len(CAMS)}', flush=True)       # цена маски: смена материалов + 1 выборка на ракурс

QA.finish(bpy, np)
