"""Куда нода складывает результат. Два сменных приёмника, воркер о разнице не знает.

`STORAGE_BACKEND=http` — НАШ сервер (умолчание для пилота). Нода одноразовая, её диск умирает
вместе с ней, поэтому результат уходит сразу. 500 моделей ≈ 2 ГБ — на exit-fi помещается, и
лишний аккаунт заводить незачем.
`STORAGE_BACKEND=s3` — S3-совместимое (Cloudflare R2 и т.п.). Понадобится на полном пуле:
11 631 модель ≈ 47 ГБ, а на exit-fi свободно 23 ГБ и рядом живёт боевая VPN-нода.

Почему не «просто положить файлы» — в обоих случаях. Очередь ретраит задания, прерывание
ноды считается неуспешной попыткой, порядок загрузки нескольких файлов не гарантирован. Если
писать как попало, появятся частичные комплекты, которые выглядят как результат: приёмка
увидит GLB без roughness-карты и запишет товар в брак, хотя виновата оборванная закачка.

Схема одна для обоих приёмников: пишем во ВРЕМЕННОЕ место → проверяем, что комплект полон и
файлы ненулевые → переносим → и только последним публикуем `complete.json`. Повторная попытка
сначала смотрит `complete.json`: он есть — работа сделана, GPU не тратим.
"""
import json
import os
import urllib.error
import urllib.request

BACKEND = os.environ.get('STORAGE_BACKEND', 'http')

# Комплект ассета. Отсутствие любого из обязательных = задание НЕ выполнено.
REQUIRED = ('model.glb', 'manifest.json')
OPTIONAL = ('albedo.png', 'orm.png', 'normal.png', 'shape.glb', 'input.png')


def _check(files: dict) -> None:
    missing = [n for n in REQUIRED if n not in files]
    if missing:
        raise ValueError(f'неполный комплект, не выгружаем: нет {missing}')
    for name, path in files.items():
        if os.path.getsize(path) == 0:
            raise ValueError(f'пустой файл: {name}')


# ---------------------------------------------------------------- наш сервер (HTTP)

def _http_req(method: str, path: str, body: bytes | None = None,
              ctype: str = 'application/octet-stream', timeout: int = 300):
    base = os.environ['MESH_SINK_URL'].rstrip('/')
    req = urllib.request.Request(f'{base}{path}', data=body, method=method, headers={
        'Authorization': f"Bearer {os.environ['MESH_SINK_TOKEN']}",
        'Content-Type': ctype})
    return urllib.request.urlopen(req, timeout=timeout)


def _http_done(prefix: str) -> dict | None:
    try:
        with _http_req('GET', f'/complete/{prefix}', timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:  # noqa: BLE001 — приёмник недоступен: считаем, что не сделано, и пробуем
        return None


def _http_publish(prefix: str, files: dict, complete: dict) -> dict:
    sizes = {}
    for name, path in files.items():
        with open(path, 'rb') as f:
            data = f.read()
        # Файлы уходят во ВРЕМЕННОЕ имя на стороне приёмника; он сам переносит их в
        # постоянное только по сигналу /complete — так оборванная закачка не оставляет
        # полуфабрикат, который выглядит готовым.
        with _http_req('PUT', f'/staging/{prefix}/{name}', data) as r:
            r.read()
        sizes[name] = len(data)
    body = json.dumps({**complete, 'files': sizes}, ensure_ascii=False).encode()
    with _http_req('POST', f'/complete/{prefix}', body, 'application/json') as r:
        r.read()
    return sizes


# ---------------------------------------------------------------- S3-совместимое

_S3 = None
BUCKET = os.environ.get('S3_BUCKET', 'remlab-meshes')


def s3():
    global _S3
    if _S3 is None:
        import boto3
        from botocore.config import Config
        _S3 = boto3.client(
            's3',
            endpoint_url=os.environ['S3_ENDPOINT'],
            aws_access_key_id=os.environ['S3_ACCESS_KEY'],
            aws_secret_access_key=os.environ['S3_SECRET_KEY'],
            config=Config(retries={'max_attempts': 5, 'mode': 'standard'},
                          signature_version='s3v4'),
            region_name=os.environ.get('S3_REGION', 'auto'))
    return _S3


def _s3_done(prefix: str) -> dict | None:
    try:
        return json.loads(s3().get_object(Bucket=BUCKET,
                                          Key=f'{prefix}/complete.json')['Body'].read())
    except Exception:  # noqa: BLE001 — нет объекта или нет доступа: считаем, что не сделано
        return None


def _s3_publish(prefix: str, files: dict, complete: dict) -> dict:
    tmp, sizes = f'{prefix}/.staging', {}
    for name, path in files.items():
        with open(path, 'rb') as f:
            s3().put_object(Bucket=BUCKET, Key=f'{tmp}/{name}', Body=f)
        sizes[name] = os.path.getsize(path)
    for name in files:                       # копия на стороне хранилища, без повторной заливки
        s3().copy_object(Bucket=BUCKET, Key=f'{prefix}/{name}',
                         CopySource={'Bucket': BUCKET, 'Key': f'{tmp}/{name}'})
    for name in files:
        try:
            s3().delete_object(Bucket=BUCKET, Key=f'{tmp}/{name}')
        except Exception:  # noqa: BLE001 — мусор во временном префиксе не ломает результат
            pass
    body = json.dumps({**complete, 'files': sizes}, ensure_ascii=False).encode()
    s3().put_object(Bucket=BUCKET, Key=f'{prefix}/complete.json', Body=body)
    return sizes


# ---------------------------------------------------------------- общий вход

def already_done(prefix: str) -> dict | None:
    """Готовый результат обнаруживается по маркеру, который пишется последним."""
    return _http_done(prefix) if BACKEND == 'http' else _s3_done(prefix)


def publish(prefix: str, files: dict, complete: dict) -> dict:
    """files: {имя в хранилище: локальный путь}. Возвращает карту размеров."""
    _check(files)
    return (_http_publish if BACKEND == 'http' else _s3_publish)(prefix, files, complete)
