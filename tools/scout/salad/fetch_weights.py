"""Догрузка весов при старте, если образ собран без них (BAKE_WEIGHTS=0).

Нужна ровно тогда, когда образ пришлось делать лёгким. Скачивание идёт уже на тарифицируемой
ноде, поэтому время замеряется и попадает в /health — иначе «дешёвая» схема с лёгким образом
может незаметно оказаться дороже тяжёлой, и сравнить их будет нечем.

Скачиваем ОДИН РАЗ на контейнер: маркер `.ready` рядом с весами. Рестарт процесса в живом
контейнере повторной закачки не вызывает; смена ноды — вызывает, и это ровно та цена, которую
мы и меряем.
"""
import os
import time

WEIGHTS = os.environ.get('WEIGHTS_DIR', '/opt/weights')
READY = os.path.join(WEIGHTS, '.ready')


def ensure() -> dict:
    if os.path.exists(READY):
        return {'downloaded': False, 'seconds': 0.0}
    if not os.path.exists(os.path.join(WEIGHTS, '.lazy')):
        return {'downloaded': False, 'seconds': 0.0}      # веса вшиты в образ

    from huggingface_hub import snapshot_download
    t0 = time.time()
    snapshot_download('tencent/Hunyuan3D-2.1',
                      local_dir=os.path.join(WEIGHTS, 'hunyuan3d-2.1'),
                      allow_patterns=['hunyuan3d-dit-v2-1/*', 'hunyuan3d-paintpbr-v2-1/*'],
                      max_workers=8)
    snapshot_download('ZhengPeng7/BiRefNet',
                      local_dir=os.path.join(WEIGHTS, 'birefnet'), max_workers=8)
    took = round(time.time() - t0, 1)
    with open(READY, 'w', encoding='utf-8') as f:
        f.write(str(took))
    return {'downloaded': True, 'seconds': took}
