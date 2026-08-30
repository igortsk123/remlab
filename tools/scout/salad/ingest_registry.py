#!/usr/bin/env python3
"""Регистрация мешей пилота в asset_revisions (P0 из передачи соседней сессии, 30.08).

Меши лежали файлами и были невидимы реестру: mesh_ready, резерв и автозамена их не видели.
Ключ ревизии — sku|source_sha|v1 (source_sha = hash исходного фото из манифеста): контракт
соседей сам отбраковывает меши от устаревших фото — каталог перешёл на HD, и пилотные
450px-меши честно останутся «от старого фото» для боевой воронки, годясь для оценки качества.
"""
import glob
import hashlib
import json
import os
import subprocess

SRC = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1']


def q(v):
    if v is None:
        return 'null'
    return "'" + str(v).replace("'", "''") + "'"


def main() -> None:
    n = 0
    for mp in sorted(glob.glob(os.path.join(SRC, '*/*/manifest.json'))):
        d = os.path.dirname(mp)
        man = json.load(open(mp, encoding='utf-8'))
        sku = man['sku']
        src_sha = (man.get('input') or {}).get('input_hash') or 'unknown'
        glb = os.path.join(d, 'model.glb')
        glb_sha = None
        if os.path.exists(glb):
            h = hashlib.sha256()
            with open(glb, 'rb') as f:
                for ch in iter(lambda: f.read(1 << 20), b''):
                    h.update(ch)
            glb_sha = h.hexdigest()[:16]
        rk = f'{sku}|{src_sha}|v1'
        status = 'generated' if glb_sha else (man.get('gpu') or {}).get('gate') or 'failed'
        sql = (f"insert into asset_revisions (revision_key, sku, glb_sha, status, origin, manifest) "
               f"values ({q(rk)}, {q(sku)}, {q(glb_sha)}, {q(status)}, 'salad-pilot', "
               f"{q(json.dumps(man, ensure_ascii=False))}::jsonb) "
               f"on conflict (revision_key) do update set glb_sha=excluded.glb_sha, "
               f"status=excluded.status, manifest=excluded.manifest;")
        r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
        if r.returncode == 0:
            n += 1
        else:
            print(f'  сбой {sku}: {r.stderr[:120]}')
    print(f'в реестр записано ревизий: {n}')


if __name__ == '__main__':
    main()
