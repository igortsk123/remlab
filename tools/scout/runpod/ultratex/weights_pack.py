#!/usr/bin/env python3
"""Веса внутрь образа слоями по 2–5 ГиБ (T-178/1, 21.11; владелец TG 1143: «веса внутрь и всё как у мешей — конвейер»).

ЗАЧЕМ: DiT FLUX.2-klein-base-9B — ОДИН файл 18 ГБ; слой образа такого размера плохо качается и не докачивается. Здесь файл режется ПО ТЕНЗОРАМ на валидные
safetensors-куски ≤ MAX_SHARD (ничего не пересчитывается: байты тензоров те же). Каждый кусок — свой слой образа (`RUN … weights_pack.py shard K`), без второй копии на диске сборщика.
КАК: заголовок safetensors (8 байт длины + JSON) читается Range-запросом; кусок K собирается из Range-запросов только своих тензоров; токен HF — только из секрета сборки
(`RUN --mount=type=secret,id=hf_token`), в слой не попадает. В конце каждого куска — sha256 и число тензоров в `shards/manifest.json` (дописывается каждым шагом).
ВОРКЕР: `load_sharded(dir)` собирает словарь тензоров из кусков; проверка — набор имён, форма и dtype совпадают с заголовком исходного файла (хранится в манифесте).

  python weights_pack.py plan   --url URL --token-env HF_TOKEN [--max-gb 4]          # печатает группы (без записи)
  python weights_pack.py shard  --url URL --token-env HF_TOKEN --out DIR --k K [--max-gb 4]
  python weights_pack.py verify --out DIR                                            # без сети: куски целы, набор тензоров = заголовку исходника
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request

MAX_SHARD = 4 * 2 ** 30
CHUNK = 64 * 2 ** 20
MANIFEST = 'manifest.json'
SHARDS_JSON = 'shards.json'                                      # признак «каталог кусков» для load_sharded


# ---------------------------------------------------------------- чтение диапазонов (HTTP Range, токен только на первый хоп — CDN его не любит)
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class HttpRange:
    def __init__(self, url: str, token: str = ''):
        self.url, self.token = url, token

    def _open(self, url: str, start: int, end: int, auth: bool, depth: int = 0):
        headers = {'Range': f'bytes={start}-{end - 1}', 'User-Agent': 'weights-pack/1'}
        if auth and self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            return opener.open(urllib.request.Request(url, headers=headers), timeout=120)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and depth < 5:
                loc = urllib.parse.urljoin(url, e.headers['Location'])
                same = urllib.parse.urlparse(loc).netloc == urllib.parse.urlparse(url).netloc
                return self._open(loc, start, end, auth and same, depth + 1)
            raise

    def read(self, start: int, end: int):
        """Байты [start, end) кусками ≤ CHUNK; обрыв — повтор с места обрыва (до 6 раз на кусок)."""
        pos = start
        while pos < end:
            stop = min(pos + CHUNK, end)
            for attempt in range(6):
                try:
                    with self._open(self.url, pos, stop, True) as r:
                        data = r.read()
                    if len(data) != stop - pos:
                        raise OSError(f'получено {len(data)} из {stop - pos}')
                    break
                except (OSError, http.client.HTTPException):
                    if attempt == 5:
                        raise
            yield data
            pos = stop

    def read_all(self, start: int, end: int) -> bytes:
        return b''.join(self.read(start, end))


# ---------------------------------------------------------------- заголовок и разбиение
def read_header(src) -> tuple[dict, int]:
    """→ (заголовок без __metadata__, смещение начала данных в файле)."""
    n = struct.unpack('<Q', src.read_all(0, 8))[0]
    if n <= 0 or n > 100 * 2 ** 20:
        raise ValueError(f'длина заголовка safetensors {n} — это не safetensors')
    head = json.loads(src.read_all(8, 8 + n))
    head.pop('__metadata__', None)
    return head, 8 + n


def plan_groups(header: dict, max_bytes: int = MAX_SHARD) -> list[list[str]]:
    """Группы имён тензоров в порядке расположения в файле; куски ≤ max_bytes (тензор больше — свой кусок). Порядок и состав детерминированы."""
    items = sorted(header.items(), key=lambda kv: kv[1]['data_offsets'][0])
    groups, cur, size = [], [], 0
    for name, info in items:
        a, b = info['data_offsets']
        if cur and size + (b - a) > max_bytes:
            groups.append(cur)
            cur, size = [], 0
        cur.append(name)
        size += b - a
    if cur:
        groups.append(cur)
    return groups


def write_shard(src, header: dict, data_start: int, names: list[str], out_path: str) -> dict:
    """Собирает safetensors-кусок из тензоров `names`; данные идут потоком (память ≈ CHUNK). → {file, bytes, sha256, tensors}."""
    new, off = {}, 0
    for n in names:
        a, b = header[n]['data_offsets']
        new[n] = {'dtype': header[n]['dtype'], 'shape': header[n]['shape'], 'data_offsets': [off, off + (b - a)]}
        off += b - a
    hj = json.dumps(new, separators=(',', ':')).encode()
    hj += b' ' * ((8 - len(hj) % 8) % 8)                           # выравнивание данных по 8 байт, как у safetensors
    h = hashlib.sha256()
    tmp = out_path + '.part'
    with open(tmp, 'wb') as f:
        for blob in (struct.pack('<Q', len(hj)), hj):
            f.write(blob)
            h.update(blob)
        for n in names:
            a, b = header[n]['data_offsets']
            for data in src.read(data_start + a, data_start + b):
                f.write(data)
                h.update(data)
    os.replace(tmp, out_path)
    return {'file': os.path.basename(out_path), 'bytes': os.path.getsize(out_path), 'sha256': h.hexdigest(), 'tensors': len(names)}


def _manifest_path(out: str) -> str:
    return os.path.join(out, MANIFEST)


def shard_step(src, out: str, k: int, max_bytes: int = MAX_SHARD) -> dict:
    """Шаг K сборки образа: заголовок исходника → куски группы K → строка в manifest.json (+ shards.json — признак каталога)."""
    header, data_start = read_header(src)
    groups = plan_groups(header, max_bytes)
    if not 0 <= k < len(groups):
        raise IndexError(f'кусок {k}: всего {len(groups)}')
    os.makedirs(out, exist_ok=True)
    row = write_shard(src, header, data_start, groups[k], os.path.join(out, f'shard-{k:02d}.safetensors'))
    man = json.load(open(_manifest_path(out))) if os.path.isfile(_manifest_path(out)) else {'shards': {}}
    man['total_shards'] = len(groups)
    man['source_tensors'] = {n: {'dtype': i['dtype'], 'shape': i['shape']} for n, i in header.items()}
    man['shards'][str(k)] = row
    json.dump(man, open(_manifest_path(out), 'w'))
    open(os.path.join(out, SHARDS_JSON), 'w').write('{"format": "safetensors-shards-v1"}')
    return row


# ---------------------------------------------------------------- проверка и загрузка
def verify_dir(out: str, deep: bool = True) -> dict:
    """Без сети: все куски на месте, размеры/sha256 как в манифесте, набор тензоров, формы и dtype равны заголовку исходника. Нарушение — ValueError."""
    man = json.load(open(_manifest_path(out)))
    total = man['total_shards']
    if sorted(man['shards']) != [str(i) for i in range(total)]:
        raise ValueError(f'в манифесте куски {sorted(man["shards"])}, ждали 0..{total - 1}')
    seen = {}
    for k in range(total):
        row = man['shards'][str(k)]
        path = os.path.join(out, row['file'])
        if os.path.getsize(path) != row['bytes']:
            raise ValueError(f'{row["file"]}: размер {os.path.getsize(path)} ≠ {row["bytes"]}')
        if deep:
            h = hashlib.sha256()
            with open(path, 'rb') as f:
                for blob in iter(lambda: f.read(CHUNK), b''):
                    h.update(blob)
            if h.hexdigest() != row['sha256']:
                raise ValueError(f'{row["file"]}: sha256 не совпал')
        with open(path, 'rb') as f:
            n = struct.unpack('<Q', f.read(8))[0]
            head = json.loads(f.read(n))
        head.pop('__metadata__', None)
        end = max((i['data_offsets'][1] for i in head.values()), default=0)
        if os.path.getsize(path) != 8 + n + end:
            raise ValueError(f'{row["file"]}: хвост данных не сходится с заголовком')
        for name, i in head.items():
            if name in seen:
                raise ValueError(f'тензор {name} в двух кусках')
            seen[name] = {'dtype': i['dtype'], 'shape': i['shape']}
    if seen != man['source_tensors']:
        miss = sorted(set(man['source_tensors']) - set(seen))[:5]
        raise ValueError(f'набор/формы тензоров ≠ исходнику (нет: {miss})')
    return {'shards': total, 'tensors': len(seen), 'bytes': sum(r['bytes'] for r in man['shards'].values())}


def is_sharded_dir(path: str) -> bool:
    return os.path.isdir(path) and os.path.isfile(os.path.join(path, SHARDS_JSON))


def load_sharded(path: str, device: str = 'cpu') -> dict:
    """Словарь тензоров из кусков (как `safetensors.torch.load_file` для одного файла). Состав сверяется с манифестом; лишнее/недостающее — RuntimeError."""
    from safetensors.torch import load_file
    man = json.load(open(_manifest_path(path)))
    sd = {}
    for k in range(man['total_shards']):
        part = load_file(os.path.join(path, man['shards'][str(k)]['file']), device=device)
        dup = set(part) & set(sd)
        if dup:
            raise RuntimeError(f'тензоры в двух кусках: {sorted(dup)[:3]}')
        sd.update(part)
    if set(sd) != set(man['source_tensors']):
        raise RuntimeError('набор тензоров из кусков ≠ исходному файлу (образ собран неверно)')
    return sd


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['plan', 'shard', 'verify'])
    ap.add_argument('--url')
    ap.add_argument('--token-env', default='')
    ap.add_argument('--token-file', default='')
    ap.add_argument('--out')
    ap.add_argument('--k', type=int, default=0)
    ap.add_argument('--max-gb', type=float, default=MAX_SHARD / 2 ** 30)
    ap.add_argument('--shallow', action='store_true')
    ap.add_argument('--expect-shards', type=int, default=0, help='verify/plan: ожидаемое число кусков (иначе — ошибка, сборка падает до платного прогона)')
    a = ap.parse_args(argv)
    maxb = int(a.max_gb * 2 ** 30)
    if a.cmd == 'verify':
        info = verify_dir(a.out, deep=not a.shallow)
        if a.expect_shards and info['shards'] != a.expect_shards:
            raise SystemExit(f'кусков {info["shards"]}, ждали {a.expect_shards}')
        print(json.dumps(info))
        return 0
    token = os.environ.get(a.token_env, '') if a.token_env else ''
    if a.token_file and os.path.isfile(a.token_file):
        token = open(a.token_file).read().strip()
    src = HttpRange(a.url, token)
    if a.cmd == 'plan':
        header, _ = read_header(src)
        groups = plan_groups(header, maxb)
        for i, g in enumerate(groups):
            print(i, len(g), round(sum(header[n]['data_offsets'][1] - header[n]['data_offsets'][0] for n in g) / 2 ** 30, 3), 'ГиБ')
        if a.expect_shards and len(groups) != a.expect_shards:
            raise SystemExit(f'кусков {len(groups)}, ждали {a.expect_shards}: поправь число RUN-шагов в Dockerfile')
        return 0
    print(json.dumps(shard_step(src, a.out, a.k, maxb)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
