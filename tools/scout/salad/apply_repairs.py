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

def main() -> None:
    fixed = 0
    for mp in sorted(glob.glob(os.path.join(SRC, '*/*/manifest.json'))):
        d = os.path.dirname(mp)
        glb = os.path.join(d, 'model.glb')
        if not os.path.exists(glb):
            continue
        role = (json.load(open(mp, encoding='utf-8')) or {}).get('role')
        before = os.path.getsize(glb)
        P.cut_base_slab(glb, role)
        P.cut_alien_debris(glb)
        if os.path.getsize(glb) != before:
            fixed += 1
            print(f'  починен: {os.path.basename(os.path.dirname(d))} ({role})')
    print(f'ремонт: изменено {fixed}')

if __name__ == '__main__':
    main()
