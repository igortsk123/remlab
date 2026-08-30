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
import threading
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
# Режим ноды: mask_only — только оценка фото (/assess), Hunyuan в VRAM не поднимается.
# Определение ПОТЕРЯЛОСЬ при слиянии 29.08: поток прогрева умирал на NameError между двумя
# try, молча — нода вечно `warm=false` при живом порте. Отсюда же правило ниже: тело прогрева
# обёрнуто целиком, а warm ставится в finally.
MASK_ONLY = os.environ.get('MASK_ONLY', '0') == '1'
STATE = {'warm': False, 'done': 0, 'failed': 0, 'skipped': 0, 'gpu_seconds': 0.0}


@app.get('/health')
def health():
    """ЖИВ ли процесс — всегда 200. Прогрет ли — в теле, поле `warm`.

    Раньше здесь отдавался 503 до конца прогрева, и это стоило нам ноды: у проверки
    готовности Salad бюджет ограничен (задержка максимум 1200с), а старт занимает ~35 минут
    (только веса качаются 32). Проверка исчерпывала лимит отказов раньше, чем воркер
    прогревался, и инстанс НАВСЕГДА помечался неготовым при живом и здоровом сервисе —
    шлюз отдавал 503 наружу (поймано 28.08).

    Гейт перенесён туда, где он и должен быть: задания отклоняет `/generate`, а отправщик
    их штатно повторяет. Раздачей всё равно управляем мы, а не платформа.
    """
    return {'ok': True, 'uptime_s': round(time.time() - STARTED), **STATE}


@app.on_event('startup')
def start_warmup():
    """Прогрев уходит в ФОНОВЫЙ поток — иначе сервер не слушает порт.

    Обработчик запуска выполняется ДО того, как uvicorn начнёт принимать соединения. Пока в
    нём качались веса (32 минуты), порт 8000 не отвечал никому: платформа видела инстанс
    неготовым, шлюз отдавал 503 наружу, нода тарифицировалась и не работала (поймано на живой
    ноде 29.08: `/opt/weights` рос, процесс жил, а localhost:8000 давал connection refused).
    Перенос гейта в `/generate` тут не помогал — отвечать было нечему.

    Теперь порт слушается сразу: `/health` честно говорит `warm=false`, `/generate` отдаёт
    503, отправщик ждёт. Платформа считает ноду живой, и она попадает в балансировку.
    """
    threading.Thread(target=warmup, daemon=True).start()


def warmup():
    """Один прогревочный прогон на синтетической картинке: компиляция ядер и загрузка весов
    не должны попасть в замер первого настоящего задания.

    ВСЁ тело — в одном try, warm ставится в finally. Урок 29.08: одна строка между двумя
    try (NameError на потерянном имени) убила поток молча, и нода вечно осталась «греющейся»
    при живом порте. Теперь любой сбой прогрева виден в warmup_error, а нода всё равно
    открывается: настоящие задания упадут ГРОМКО и покажут причину, это лучше вечного 503.
    """
    try:
        import fetch_weights
        STATE['weights'] = fetch_weights.ensure()   # пусто, если веса вшиты в образ
        STATE['mode'] = 'mask_only' if MASK_ONLY else 'generate'
        if MASK_ONLY:
            # Прогрев генератора здесь был бы прямым вредом: он поднял бы Hunyuan в VRAM ради
            # режима, в котором тот не нужен, и съел бы весь смысл дешёвого прохода.
            return
        t0 = time.time()
        # RGBA, а не RGB: контракт входа — альфа И ЕСТЬ маска товара. На сером RGB форма
        # возвращает None, и прогрев падает — компиляцию ядер оплатило бы первое задание.
        img = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
        from PIL import ImageDraw
        ImageDraw.Draw(img).ellipse((128, 128, 384, 384), fill=(200, 180, 160, 255))
        with tempfile.TemporaryDirectory() as d:
            P.generate(img, d, seed=0, params={'num_inference_steps': 5,
                                               'octree_resolution': 128})
        STATE['warmup_s'] = round(time.time() - t0, 1)
    except Exception:  # noqa: BLE001 — причина в warmup_error, нода всё равно открывается
        STATE['warmup_error'] = traceback.format_exc()[-800:]
    finally:
        STATE['warm'] = True


@app.post('/assess')
def assess(job: dict):
    """Оценка пригодности фото: вырезка, измерения, вердикт. Меш не генерируется.

    Отдаём измерения ЦЕЛИКОМ, а не только вердикт: пороги пригодности ещё калибруются по ролям,
    и при их смене не хочется заново считать маски всему пулу.
    """
    if not job.get('image_url'):
        raise HTTPException(status_code=400, detail='нет image_url')
    t0 = time.time()
    try:
        input_hash, info = PRE.assess(job['image_url'])
    except Exception as e:  # noqa: BLE001 — мёртвое фото не должно ронять ноду
        return {'sku': job.get('sku'), 'status': 'input_failed', 'error': str(e)[:300]}
    STATE['assessed'] = STATE.get('assessed', 0) + 1
    return {'sku': job.get('sku'), 'status': 'assessed', 'source_sha': input_hash,
            'assessor_version': PRE.ASSESSOR_VERSION, 'metrics': info,
            'secs': round(time.time() - t0, 2)}


@app.post('/generate')
def generate(job: dict):
    if not STATE['warm']:
        # 503 именно здесь: отправщик повторяет 5xx, а нода тем временем догревается.
        raise HTTPException(status_code=503, detail='прогрев не закончен')
    sku = job.get('sku')
    if not sku or not job.get('image_url'):
        raise HTTPException(status_code=400, detail='нет sku или image_url')
    # СТРАХОВКА КАНОНА (Codex q27): воркер пересчитывает стратегию сам и отклоняет чужое
    # ДО вырезки и GPU — новый источник заданий не сможет обойти реестр.
    try:
        import asset_strategy as AS
        if AS.strategy(job.get('role')) != 'hunyuan3d':
            return {'sku': sku, 'status': 'not_generator_eligible',
                    'strategy': AS.strategy(job.get('role')),
                    'policy_version': AS.policy_version()}
    except Exception:  # noqa: BLE001 — нет реестра в образе: работаем, фильтр у отправителя
        pass
    seed = int(job.get('seed', 0))
    params = job.get('params') or {}
    t0 = time.time()

    try:
        # Роль из задания включает точечные правки цепочки (ковёр — рост маски,
        # ваза/кашпо/статуэтка — силуэт вместо прозрачности). Без неё нода режет «вообще»,
        # и результат разойдётся с тем, что мы проверили на дев-машине.
        shape_img, paint_img, cut_rgba, input_hash, mask_info = PRE.prepare(
            job['image_url'], role=job.get('role'))
    except P.FlatShape as e:
        # Форма — доска: покраска НЕ запускалась, оплачена только дешёвая стадия формы.
        # Лечится другим seed (внешняя волна), дважды доска → фото без глубины, товар на замену.
        STATE['flat_shape'] = STATE.get('flat_shape', 0) + 1
        return {'sku': sku, 'status': 'flat_shape', 'error': str(e)[:200]}
    except PRE.BadCutout as e:
        # Отдельный статус: это не сбой ноды и не мёртвое фото, а брак ВЫРЕЗКИ. Такие товары
        # надо видеть списком — они лечатся другой вырезкой, а не повтором генерации.
        STATE['bad_cutout'] = STATE.get('bad_cutout', 0) + 1
        return {'sku': sku, 'status': 'bad_cutout', 'error': str(e)[:300]}
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
        # PNG держит альфу — именно она и есть маска товара для генератора (ADR-0133).
        shape_img.save(os.path.join(work, 'input.png'))          # что видит стадия формы
        cut_rgba.save(os.path.join(work, 'cutout.png'))          # вырезка с альфой — на просмотр
        params['_dims'] = job.get('dims_cm') or {}
        params['_square_role'] = job.get('role') in ('кашпо', 'ваза', 'торшер', 'лампа', 'пуф')
        res = P.generate(shape_img, work, seed=seed, params=params, paint_image=paint_img,
                         role=job.get('role'))

        files = {'model.glb': res['glb']}
        for name in ('albedo.png', 'orm.png', 'normal.png', 'shape.glb', 'cutout.png'):
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
