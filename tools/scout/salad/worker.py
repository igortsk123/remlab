"""Воркер задания: HTTP-эндпоинт, который дёргает Job Queue SaladCloud.

Очередь Salad устроена так: контейнер поднимает порт, платформа кладёт задания в очередь и
сама разносит их по живым нодам с ретраями. Наше дело — отвечать на /health честно (иначе
битая нода продолжит получать задания) и делать задание идемпотентно (иначе ретрай после
прерывания сожжёт GPU второй раз на уже готовый товар).

Формат задания — строка из `mesh-pilot-sample.json`:
  {"sku","mid","eid","role","image_url","dims_cm",...,"seeds":[0]}
На каждый seed ставится ОТДЕЛЬНОЕ задание — так повтор на трёх seed не превращается в одно
длинное задание, которое прерывание убивает целиком.

  ОТЛАДКА ЛОКАЛЬНО (на арендованной карте):
    docker run --gpus all -p 8000:8000 --env-file .env remlab/mesh-hunyuan:cu121
    curl -X POST localhost:8000/generate -d @job.json -H 'Content-Type: application/json'
"""
import json
import os
import shutil
import tempfile
import time
import traceback

from fastapi import FastAPI, HTTPException
from PIL import Image

import manifest as M
import pipeline as P
import preprocess as PRE
import storage as S

app = FastAPI()
STARTED = time.time()
STATE = {'warm': False, 'done': 0, 'failed': 0, 'skipped': 0, 'gpu_seconds': 0.0}


@app.get('/health')
def health():
    """Пока модели не прогреты, нода жива, но задания брать рано — отдаём 503.

    Прогрев считается частью холодного старта и меряется отдельно: смешивать его с warm-
    инференсом в средних цифрах нельзя, иначе бенч карт покажет не то.
    """
    if not STATE['warm']:
        raise HTTPException(status_code=503, detail='прогрев')
    return {'ok': True, 'uptime_s': round(time.time() - STARTED), **STATE}


@app.on_event('startup')
def warmup():
    """Один прогревочный прогон на синтетической картинке: компиляция ядер и загрузка весов
    не должны попасть в замер первого настоящего задания."""
    try:
        import fetch_weights
        STATE['weights'] = fetch_weights.ensure()   # пусто, если веса вшиты в образ
    except Exception:  # noqa: BLE001 — причину видно в логе ноды
        STATE['weights_error'] = traceback.format_exc()[-500:]
    try:
        t0 = time.time()
        img = Image.new('RGB', (512, 512), (200, 200, 200))
        with tempfile.TemporaryDirectory() as d:
            P.generate(img, d, seed=0, params={'num_inference_steps': 5,
                                               'octree_resolution': 128})
        STATE['warmup_s'] = round(time.time() - t0, 1)
    except Exception:  # noqa: BLE001 — прогрев не удался: причину видно в логе ноды
        STATE['warmup_error'] = traceback.format_exc()[-800:]
    STATE['warm'] = True


@app.post('/generate')
def generate(job: dict):
    sku = job.get('sku')
    if not sku or not job.get('image_url'):
        raise HTTPException(status_code=400, detail='нет sku или image_url')
    seed = int(job.get('seed', 0))
    params = job.get('params') or {}
    t0 = time.time()

    try:
        image, input_hash, mask_info = PRE.prepare(job['image_url'])
    except Exception as e:  # noqa: BLE001 — мёртвое фото не должно ронять ноду
        STATE['failed'] += 1
        return {'sku': sku, 'status': 'input_failed', 'error': str(e)[:300]}

    jid = M.job_id(sku, input_hash, params, seed)
    prefix = M.prefix(sku, jid)

    done = S.already_done(prefix)
    if done:                       # ретрай после прерывания — работа уже сделана
        STATE['skipped'] += 1
        return {'sku': sku, 'status': 'cached', 'job_id': jid, 'prefix': prefix}

    work = tempfile.mkdtemp(prefix='mesh-')
    try:
        image.save(os.path.join(work, 'input.png'))
        res = P.generate(image, work, seed=seed, params=params)

        files = {'model.glb': res['glb']}
        for name in ('albedo.png', 'orm.png', 'normal.png', 'shape.glb'):
            p = os.path.join(work, name)
            if os.path.exists(p):
                files[name] = p
        files['input.png'] = os.path.join(work, 'input.png')

        man = M.asset_manifest({**job, 'seed': seed, 'params': params}, jid, input_hash,
                               res['timings'], res['gpu'])
        man['mask'] = mask_info      # отчёт вырезки в паспорт: по нему видно, сработал ли
                                     # гибрид и сколько тонких деталей он вернул
        mp = os.path.join(work, 'manifest.json')
        json.dump(man, open(mp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        files['manifest.json'] = mp

        sizes = S.publish(prefix, files, {'sku': sku, 'job_id': jid,
                                          'timings_s': res['timings'], 'gpu': res['gpu']})
        STATE['done'] += 1
        STATE['gpu_seconds'] += time.time() - t0
        return {'sku': sku, 'status': 'ok', 'job_id': jid, 'prefix': prefix,
                'timings_s': res['timings'], 'gpu': res['gpu'], 'sizes': sizes}
    except Exception as e:  # noqa: BLE001 — задание падает, нода живёт и берёт следующее
        STATE['failed'] += 1
        return {'sku': sku, 'status': 'failed', 'job_id': jid,
                'error': f'{type(e).__name__}: {str(e)[:300]}',
                'trace': traceback.format_exc()[-1200:]}
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 8000)), log_level='info')
