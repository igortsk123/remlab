#!/usr/bin/env python3
"""Убирает зависимость Hunyuan 2.1 от Blender (`bpy`). Запускается ОДИН РАЗ при сборке образа.

ПОЧЕМУ ЭТО ВООБЩЕ НУЖНО. В `requirements.txt` апстрима стоит `bpy==4.0`, но этой версии на
PyPI больше нет: у 4.0.0 ноль файлов, и ни одна версия сейчас не даёт колесо под Python 3.10
(проверено 28.08.2026). Официальный `docker/Dockerfile` Tencent сегодня падает на этом же
месте — дело не в нашей сборке.

ЧТО ОТ BLENDER РЕАЛЬНО ТРЕБУЕТСЯ. На нашем пути `bpy` используется в одной функции —
`convert_obj_to_glb`: импортировать OBJ, сгладить нормали, экспортировать GLB. Остальное в
`mesh_utils.py` (запись OBJ, MTL, карты) — чистый numpy/cv2. При этом в том же репозитории
уже лежит `hy3dpaint/convert_utils.py` с `create_glb_with_pbr_materials` на trimesh +
pygltflib, и она делает БОЛЬШЕ: явно цепляет albedo/metallic/roughness/normal как PBR-карты
glTF. Для нашей задачи это и нужно — ради разделённых карт всё и затевалось.

ЧЕМ ОТЛИЧАЕТСЯ РЕЗУЛЬТАТ. Blender по пути делал сглаживание по углу 60° и слияние вершин;
trimesh — нет. Нормали могут выйти чуть жёстче на скруглениях. Это проверяется на пилоте
(поле `converter` в манифесте ассета), а не принимается на веру.

Патч идемпотентен: повторный запуск ничего не меняет.
"""
import os
import re
import sys

HY = os.environ.get('HY_ROOT', '/opt/hunyuan')
MESH_UTILS = os.path.join(HY, 'hy3dpaint/DifferentiableRenderer/mesh_utils.py')
REQS = os.path.join(HY, 'requirements.txt')
MARK = '# --- remlab: bpy-free convert_obj_to_glb ---'

OVERRIDE = '''

''' + MARK + '''
# Переопределение НИЖЕ исходного: последнее определение в модуле побеждает, поэтому патч не
# трогает тело апстримной функции и переживает обновление всего остального файла.
def convert_obj_to_glb(obj_path, glb_path, shade_type="SMOOTH",
                       auto_smooth_angle=60, merge_vertices=False):
    """OBJ → GLB без Blender, с PBR-картами.

    Карты ищем по соглашению, которым их пишет `save_obj_mesh` в этом же модуле:
    `<база>.jpg` (albedo), `<база>_metallic.jpg`, `<база>_roughness.jpg`, `<база>_normal.jpg`.
    Отсутствие необязательной карты — не ошибка: у части товаров генератор её не отдаёт.
    """
    import os as _os
    import sys as _sys
    _hy = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..')
    if _hy not in _sys.path:
        _sys.path.insert(0, _hy)
    try:
        from convert_utils import create_glb_with_pbr_materials
    except Exception:
        create_glb_with_pbr_materials = None

    base = _os.path.splitext(obj_path)[0]
    maps = {}
    for key, suffix in (('albedo', ''), ('metallic', '_metallic'),
                        ('roughness', '_roughness'), ('normal', '_normal')):
        for ext in ('.jpg', '.png'):
            p = f'{base}{suffix}{ext}'
            if _os.path.exists(p):
                maps[key] = p
                break

    if create_glb_with_pbr_materials is not None and 'albedo' in maps:
        try:
            create_glb_with_pbr_materials(obj_path, maps, glb_path)
            return True
        except Exception as e:  # noqa: BLE001
            print(f'convert_utils не смог, падаю на trimesh: {e}', flush=True)

    # Последний рубеж: без PBR, но с геометрией и базовой текстурой. Молча возвращать False
    # нельзя — вызывающий код примет это за «файл готов» и оставит пустой результат.
    try:
        import trimesh
        trimesh.load(obj_path, force='mesh').export(glb_path)
        return _os.path.exists(glb_path) and _os.path.getsize(glb_path) > 0
    except Exception as e:  # noqa: BLE001
        print(f'конвертация OBJ→GLB провалилась: {e}', flush=True)
        return False
'''


def patch_requirements() -> bool:
    """Строку bpy убираем ДО pip install — иначе установка падает целиком."""
    if not os.path.exists(REQS):
        return False
    src = open(REQS, encoding='utf-8').read()
    out = '\n'.join(l for l in src.splitlines() if not re.match(r'^\s*bpy\s*[=<>]', l))
    if out != src:
        open(REQS, 'w', encoding='utf-8').write(out + '\n')
        return True
    return False


def patch_mesh_utils() -> bool:
    src = open(MESH_UTILS, encoding='utf-8').read()
    if MARK in src:
        return False
    # Импорт делаем необязательным: остальные функции модуля от Blender не зависят,
    # и падать на импорте из-за одной неиспользуемой ветки бессмысленно.
    src = re.sub(r'^import bpy\s*$',
                 'try:\n    import bpy\nexcept Exception:  # remlab: Blender не ставится, '
                 'см. patch_bpy.py\n    bpy = None',
                 src, count=1, flags=re.M)
    open(MESH_UTILS, 'w', encoding='utf-8').write(src + OVERRIDE)
    return True


def main() -> None:
    r = patch_requirements()
    m = patch_mesh_utils()
    print(f'requirements: {"bpy убран" if r else "уже без bpy"}; '
          f'mesh_utils: {"пропатчен" if m else "уже пропатчен"}')
    if 'import bpy' not in open(MESH_UTILS, encoding='utf-8').read():
        sys.exit('ОШИБКА: не нашёл импорт bpy — файл апстрима изменился, патч надо пересмотреть')


if __name__ == '__main__':
    main()
