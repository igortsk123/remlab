#!/usr/bin/env python3
"""Приёмник мешей на НАШЕЙ стороне: ноды Salad кладут результат сюда, минуя объектное хранилище.

Ставится на exit-fi (единственная машина проекта с публичным адресом). Дев-машина ноде
недоступна, поэтому сервер работает ТРАНЗИТОМ: принял → отдал по запросу → `drain.sh` утащил
на дев-машину и освободил место.

ПОЧЕМУ ЭТО НЕ ПРОСТО «PUT В ПАПКУ»:
  * exit-fi делит хост с боевой VPN-нодой, и забить ему диск нельзя. Отсюда жёсткий лимит
    `MAX_DIR_GB`: превышен — приёмник отвечает 507 и ноды получают честную ошибку вместо
    молчаливой потери результата.
  * оборванная закачка не должна выглядеть готовым результатом. Файлы падают в `.staging`,
    и только POST /complete переносит комплект в постоянное место, последним записывая
    `complete.json`.
  * повторное задание после прерывания ноды обязано узнать, что работа уже сделана, иначе
    GPU сожжётся второй раз. Отсюда GET /complete/<prefix>.

  Запуск:  MESH_SINK_TOKEN=... MESH_ROOT=/opt/remlab/meshes python3 receiver.py
"""
import json
import os
import shutil

from fastapi import FastAPI, HTTPException, Request, Response

ROOT = os.environ.get('MESH_ROOT', '/opt/remlab/meshes')
TOKEN = os.environ.get('MESH_SINK_TOKEN', '')
MAX_DIR_GB = float(os.environ.get('MESH_MAX_DIR_GB', '8'))     # потолок на каталог
MIN_FREE_GB = float(os.environ.get('MESH_MIN_FREE_GB', '5'))   # неприкосновенный запас диска
MAX_FILE_MB = float(os.environ.get('MESH_MAX_FILE_MB', '80'))

app = FastAPI()


def _auth(request: Request) -> None:
    if not TOKEN or request.headers.get('authorization') != f'Bearer {TOKEN}':
        raise HTTPException(status_code=401, detail='нет токена')


def _safe(prefix: str, name: str = '') -> str:
    """Путь строго внутри ROOT: префикс приходит снаружи, `..` в нём быть не должно."""
    p = os.path.normpath(os.path.join(ROOT, prefix, name))
    if not p.startswith(os.path.abspath(ROOT) + os.sep):
        raise HTTPException(status_code=400, detail='плохой путь')
    return p


def _dir_gb() -> float:
    total = 0
    for dirpath, _, files in os.walk(ROOT):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                continue
    return total / 2 ** 30


def _free_gb() -> float:
    st = os.statvfs(ROOT)
    return st.f_bavail * st.f_frsize / 2 ** 30


@app.get('/health')
def health():
    return {'ok': True, 'dir_gb': round(_dir_gb(), 2), 'free_gb': round(_free_gb(), 2),
            'max_dir_gb': MAX_DIR_GB}


@app.get('/complete/{prefix:path}')
def get_complete(prefix: str, request: Request):
    _auth(request)
    p = _safe(prefix, 'complete.json')
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail='не готово')
    return json.load(open(p, encoding='utf-8'))


@app.put('/staging/{prefix:path}/{name}')
async def put_file(prefix: str, name: str, request: Request):
    _auth(request)
    if os.sep in name or name.startswith('.'):
        raise HTTPException(status_code=400, detail='плохое имя файла')
    if _dir_gb() > MAX_DIR_GB or _free_gb() < MIN_FREE_GB:
        # 507 вместо тихого падения: нода увидит отказ, задание вернётся в очередь, а мы
        # поймём по логу, что пора запускать drain. Забить диск exit-fi нельзя — там VPN.
        raise HTTPException(status_code=507,
                            detail=f'нет места: каталог {_dir_gb():.1f} ГБ, '
                                   f'свободно {_free_gb():.1f} ГБ — запусти drain.sh')
    body = await request.body()
    if len(body) > MAX_FILE_MB * 2 ** 20:
        raise HTTPException(status_code=413, detail='файл слишком большой')
    if not body:
        raise HTTPException(status_code=400, detail='пустое тело')
    d = _safe(prefix, '.staging')
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, name + '.part')
    with open(tmp, 'wb') as f:
        f.write(body)
    os.replace(tmp, os.path.join(d, name))
    return {'ok': True, 'bytes': len(body)}


@app.post('/complete/{prefix:path}')
async def post_complete(prefix: str, request: Request):
    _auth(request)
    meta = json.loads(await request.body())
    staging = _safe(prefix, '.staging')
    dest = _safe(prefix)
    if not os.path.isdir(staging):
        raise HTTPException(status_code=400, detail='нет загруженных файлов')

    have = set(os.listdir(staging))
    need = set((meta.get('files') or {}).keys())
    if not need <= have:
        raise HTTPException(status_code=400, detail=f'не хватает файлов: {sorted(need - have)}')
    for name, size in (meta.get('files') or {}).items():
        actual = os.path.getsize(os.path.join(staging, name))
        if actual != size:
            raise HTTPException(status_code=400,
                                detail=f'{name}: пришло {actual}, заявлено {size}')

    for name in have:
        os.replace(os.path.join(staging, name), os.path.join(dest, name))
    shutil.rmtree(staging, ignore_errors=True)
    # МАРКЕР — СТРОГО ПОСЛЕДНИМ: до этой строки комплект «не существует» для повторных попыток
    with open(os.path.join(dest, 'complete.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)
    return {'ok': True, 'files': len(have)}


@app.get('/list')
def list_done(request: Request):
    """Что уже принято — для drain.sh и для учёта прогресса пилота."""
    _auth(request)
    out = []
    for dirpath, _, files in os.walk(ROOT):
        if 'complete.json' in files:
            out.append(os.path.relpath(dirpath, ROOT))
    return {'count': len(out), 'prefixes': sorted(out), 'dir_gb': round(_dir_gb(), 2)}


@app.delete('/prefix/{prefix:path}')
def drop(prefix: str, request: Request):
    """Удаление ПОСЛЕ откачки на дев-машину. Транзит не должен копить."""
    _auth(request)
    p = _safe(prefix)
    if not os.path.isdir(p):
        raise HTTPException(status_code=404, detail='нет такого')
    shutil.rmtree(p, ignore_errors=True)
    return Response(status_code=204)


if __name__ == '__main__':
    import uvicorn
    os.makedirs(ROOT, exist_ok=True)
    if not TOKEN:
        raise SystemExit('нет MESH_SINK_TOKEN — приёмник без токена не поднимаю')
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('MESH_SINK_PORT', 877)))
