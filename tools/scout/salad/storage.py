"""Выгрузка результата в S3-совместимое хранилище (Cloudflare R2) — атомарно.

Почему не «просто положить файлы». Очередь Salad ретраит задания, прерывание ноды считается
неуспешной попыткой, и порядок загрузки нескольких файлов ничем не гарантирован. Если писать
GLB и карты как попало, в хранилище появятся частичные комплекты, которые выглядят как
результат: приёмка увидит GLB без roughness-карты и запишет товар в брак, хотя виновата
оборванная закачка.

Схема: всё пишем во ВРЕМЕННЫЙ префикс → проверяем, что комплект полон и файлы ненулевые →
переносим в постоянный → и только последним публикуем `complete.json`. Повторная попытка
сначала смотрит `complete.json`: он есть — работа уже сделана, GPU не тратим.
"""
import json
import os

import boto3
from botocore.config import Config

BUCKET = os.environ.get('S3_BUCKET', 'remlab-meshes')
_S3 = None

# Комплект ассета. Отсутствие любого из обязательных = задание НЕ выполнено.
REQUIRED = ('model.glb', 'manifest.json')
OPTIONAL = ('albedo.png', 'orm.png', 'normal.png', 'shape.glb', 'input.png')


def s3():
    global _S3
    if _S3 is None:
        _S3 = boto3.client(
            's3',
            endpoint_url=os.environ['S3_ENDPOINT'],
            aws_access_key_id=os.environ['S3_ACCESS_KEY'],
            aws_secret_access_key=os.environ['S3_SECRET_KEY'],
            config=Config(retries={'max_attempts': 5, 'mode': 'standard'},
                          signature_version='s3v4'),
            region_name=os.environ.get('S3_REGION', 'auto'))
    return _S3


def already_done(prefix: str) -> dict | None:
    """Готовый результат обнаруживается по `complete.json` — маркеру, который пишется последним."""
    try:
        obj = s3().get_object(Bucket=BUCKET, Key=f'{prefix}/complete.json')
        return json.loads(obj['Body'].read())
    except Exception:  # noqa: BLE001 — нет объекта или нет доступа: считаем, что не сделано
        return None


def _put(key: str, path: str) -> int:
    size = os.path.getsize(path)
    if size == 0:
        raise ValueError(f'пустой файл: {path}')
    with open(path, 'rb') as f:
        s3().put_object(Bucket=BUCKET, Key=key, Body=f)
    return size


def publish(prefix: str, files: dict, complete: dict) -> dict:
    """files: {имя в хранилище: локальный путь}. Возвращает карту размеров."""
    missing = [n for n in REQUIRED if n not in files]
    if missing:
        raise ValueError(f'неполный комплект, не выгружаем: нет {missing}')

    tmp = f'{prefix}/.staging'
    sizes = {}
    for name, path in files.items():
        sizes[name] = _put(f'{tmp}/{name}', path)

    # Перенос из временного в постоянный: копия на стороне хранилища, без повторной заливки
    for name in files:
        s3().copy_object(Bucket=BUCKET, Key=f'{prefix}/{name}',
                         CopySource={'Bucket': BUCKET, 'Key': f'{tmp}/{name}'})
    for name in files:
        try:
            s3().delete_object(Bucket=BUCKET, Key=f'{tmp}/{name}')
        except Exception:  # noqa: BLE001 — мусор во временном префиксе не ломает результат
            pass

    # МАРКЕР ГОТОВНОСТИ — СТРОГО ПОСЛЕДНИМ
    body = json.dumps({**complete, 'files': sizes}, ensure_ascii=False).encode()
    s3().put_object(Bucket=BUCKET, Key=f'{prefix}/complete.json', Body=body)
    return sizes
