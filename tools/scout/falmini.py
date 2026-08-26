#!/usr/bin/env python3
"""МИНИМАЛЬНЫЙ КЛИЕНТ fal — только то, что нужно сервису чернового рендера (26.08).

Вынесено из `viz_base.py`: тот тянет за собой весь инструментарий витрины (`steps`, эмбеддинги,
маски), и контейнер сервиса пришлось бы собирать из половины репозитория. Здесь три функции:
ключ, отправка задания с ретраями на транзиентное и картинка → data-URI.
"""
import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))


def fal_key() -> str:
    k = os.environ.get('FAL_KEY')
    if k:
        return k
    # свой .env первым (А4): зависимость от чужих проектов ломается при их переезде
    for p in (os.path.join(HERE, '.env'), '/home/pakar/mltest/.env', os.path.join(HERE, '../../.env')):
        try:
            for line in open(p):
                m = re.match(r'FAL_KEY=(.+)', line.strip())
                if m:
                    return m.group(1).strip().strip('"')
        except OSError:
            continue
    raise SystemExit('нет FAL_KEY — см. .memory_bank/_secrets/ACCESS.md')


def uri_from_image(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def fal_run(model: str, payload: dict, key: str, timeout: int = 300) -> dict:
    # 3 попытки на транзиентное (5xx/сеть/таймаут ожидания); 4xx (не тот набор полей) и FAILED
    # (детерминированный отказ модели) не ретраим — это не «мигнуло», а ошибка (А4).
    last = None
    for attempt in range(3):
        try:
            return _fal_once(model, payload, key, timeout)
        except _FalTransient as e:
            last = e
            if attempt < 2:
                print(f'  fal транзиент ({e}) — ретрай {attempt + 2}/3 через 15 с', flush=True)
                time.sleep(15)
    raise SystemExit(f'fal: 3 попытки исчерпаны ({last})')


class _FalTransient(Exception):
    pass


def _fal_once(model: str, payload: dict, key: str, timeout: int) -> dict:
    req = urllib.request.Request(
        f'https://queue.fal.run/{model}',
        data=json.dumps(payload).encode(),
        headers={'Authorization': f'Key {key}', 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            job = json.loads(r.read())
    except urllib.error.HTTPError as e:      # 422 = не тот набор полей: показываем схему ошибки
        if e.code >= 500:
            raise _FalTransient(f'submit {e.code}') from e
        raise SystemExit(f'fal {e.code}: {e.read().decode()[:600]}')
    except (urllib.error.URLError, TimeoutError) as e:
        raise _FalTransient(f'submit сеть: {str(e)[:80]}') from e
    status_url = job.get('status_url') or job.get('response_url')
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        sreq = urllib.request.Request(status_url, headers={'Authorization': f'Key {key}'})
        try:
            with urllib.request.urlopen(sreq, timeout=60) as r:
                st = json.loads(r.read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue                          # разовый сбой опроса — просто спросим ещё раз
        if st.get('status') == 'COMPLETED':
            time.sleep(1)
            rreq = urllib.request.Request(job['response_url'], headers={'Authorization': f'Key {key}'})
            try:
                with urllib.request.urlopen(rreq, timeout=60) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code >= 500:
                    raise _FalTransient(f'результат {e.code}') from e
                raise SystemExit(f'fal результат {e.code}: {e.read().decode()[:500]}')
        if st.get('status') in ('FAILED', 'ERROR'):
            raise SystemExit(f'fal: {json.dumps(st)[:400]}')
    raise _FalTransient('таймаут ожидания результата')
