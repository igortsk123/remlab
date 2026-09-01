#!/usr/bin/env python3
"""Прогон калибровки фронта по скачанным мешам пилота → orientation_state (upsert).

Фронт нужен виду сверху (план topview-from-mesh): спрайт из меша обязан смотреть
«перед» в согласованную сторону, иначе GPT и планировщик получат развёрнутые предметы.
"""
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from PIL import Image  # noqa: E402

import mesh_orient as MO  # noqa: E402

SRC = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')


def psql(q: str) -> str:
    r = subprocess.run(['docker', 'exec', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
                        '-t', '-A', '-c', q], capture_output=True, text=True)
    return r.stdout.strip()


def main() -> None:
    done = skipped = failed = 0
    for mp in sorted(glob.glob(os.path.join(SRC, '*/*/manifest.json'))):
        d = os.path.dirname(mp)
        glb = os.path.join(d, 'model.glb')     # только оригинал (ремонт отменён 01.09)
        cut = os.path.join(d, 'cutout.png')
        if not (os.path.exists(glb) and os.path.exists(cut)):
            continue
        man = json.load(open(mp, encoding='utf-8'))
        key = f"{man['sku']}|{(man.get('input') or {}).get('sha') or man.get('source_sha') or ''}|v1"
        st = psql(f"SELECT status FROM orientation_state WHERE revision_key='{key}'")
        if st and st != 'pending':
            skipped += 1
            continue
        try:
            res = MO.calibrate(glb, Image.open(cut))
        except Exception as e:  # noqa: BLE001 — один битый меш не valит прогон
            print(f'  сбой {man["sku"]}: {str(e)[:80]}')
            failed += 1
            continue
        payload = json.dumps(res, ensure_ascii=False).replace("'", "''")
        psql("INSERT INTO orientation_state (revision_key, sku, status, resolution) "
             f"VALUES ('{key}', '{man['sku']}', '{res.get('status', 'pending')}', '{payload}') "
             "ON CONFLICT (revision_key) DO UPDATE SET status=EXCLUDED.status, "
             "resolution=EXCLUDED.resolution, updated=now()")
        done += 1
        print(f"  {man['sku']}: {res.get('status')} yaw={res.get('yaw')}")
    print(f'калибровано: {done} | уже было: {skipped} | сбоев: {failed}')


if __name__ == '__main__':
    main()
