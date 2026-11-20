#!/usr/bin/env python3
"""ТОНКИЙ СЛОЙ КОДА БЕЗ ЛОКАЛЬНОЙ БАЗЫ (T-20261119-104): аналог `crane append` на чистом Python.

ЗАЧЕМ. `docker buildx build -f Dockerfile.code` на DEV тянет в кэш ВСЮ основу (~28 ГБ), а на pakardev свободно ~11 ГБ (проба 19.11:
за 40 с набралось 3,4 ГБ, сборку пришлось снять). Здесь основа не скачивается вообще: берём её манифест и конфиг из реестра, кладём ОДИН новый
слой (файлы кода в /app) и пишем новый манифест под новым тегом. Слои основы остаются те же — реестр их уже держит (тот же репозиторий).

Доступ — готовый `migrate_groups.ghcr_auth()` (тот же, что получает Salad); ключ не печатается и не пишется.

  ~/venvs/scout/bin/python image_append.py --base ghcr.io/igortsk123/mesh-hunyuan@sha256:<digest> --tag mask-<хеш> worker.py preprocess.py …
  ~/venvs/scout/bin/python image_append.py … --dry-run     # слой и конфиг собрать, в реестр не писать (печатает размеры и digest)

Печатает ссылку на новый образ `repo@sha256:<digest манифеста>` — её и передавать группе (`queue_setup.py --image`). Образ другой основы (docker-манифест
вместо OCI) поддержан: тип слоя берётся от основы. Многоплатформенный индекс не поддержан (наши образы — один amd64-манифест) — отказ с причиной.
"""
import argparse
import base64
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ACCEPT = ('application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, '
          'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json')
OCI_LAYER = 'application/vnd.oci.image.layer.v1.tar+gzip'
DOCKER_LAYER = 'application/vnd.docker.image.rootfs.diff.tar.gzip'


def sha(b: bytes) -> str:
    return 'sha256:' + hashlib.sha256(b).hexdigest()


def split_ref(ref: str) -> tuple[str, str, str]:
    """`ghcr.io/o/r@sha256:…` → (host, repo, reference)."""
    host, _, rest = ref.partition('/')
    if '@' in rest:
        repo, _, tail = rest.partition('@')
    else:
        repo, _, tail = rest.partition(':')
    return host, repo, tail


class Reg:
    def __init__(self, host: str, repo: str):
        self.host, self.repo, self.tok = host, repo, None

    def _token(self) -> str:
        import migrate_groups as MG
        b = MG.ghcr_auth()['basic']
        basic = base64.b64encode(f"{b['username']}:{b['password']}".encode()).decode()
        url = f'https://{self.host}/token?service={self.host}&scope=repository:{self.repo}:pull,push'
        r = urllib.request.urlopen(urllib.request.Request(url, headers={'Authorization': f'Basic {basic}'}), timeout=60)
        return json.loads(r.read())['token']

    def call(self, method: str, url: str, body: bytes | None = None, headers: dict | None = None, ok=(200, 201, 202, 204)):
        if not url.startswith('http'):
            url = f'https://{self.host}{url}'
        if self.tok is None:
            self.tok = self._token()
        h = {'Authorization': f'Bearer {self.tok}', **(headers or {})}
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, data=body, method=method, headers=h), timeout=600)
            return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            if e.code in ok:
                return e.code, e.read(), e.headers
            raise RuntimeError(f'{method} {url.split("?")[0]} → HTTP {e.code}: {e.read()[:200]!r}') from e

    def blob_exists(self, digest: str) -> bool:
        try:
            self.call('HEAD', f'/v2/{self.repo}/blobs/{digest}')
            return True
        except RuntimeError:
            return False

    def put_blob(self, data: bytes) -> str:
        d = sha(data)
        if self.blob_exists(d):
            return d
        _, _, h = self.call('POST', f'/v2/{self.repo}/blobs/uploads/', b'', {'Content-Length': '0'})
        loc = h['Location']
        sep = '&' if '?' in loc else '?'
        self.call('PUT', f'{loc}{sep}digest={d}', data, {'Content-Type': 'application/octet-stream', 'Content-Length': str(len(data))})
        return d


def make_layer(files: list[str], dest: str) -> tuple[bytes, str]:
    """(gzip-слой, diff_id): файлы кладутся в `dest` (без ведущего «/»), владелец root, права 0644, время — сейчас."""
    raw = io.BytesIO()
    now = int(time.time())
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.GNU_FORMAT) as t:
        for f in files:
            data = open(f, 'rb').read()
            ti = tarfile.TarInfo(name=f'{dest.strip("/")}/{os.path.basename(f)}')
            ti.size, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname, ti.mtime = len(data), 0o644, 0, 0, 'root', 'root', now
            t.addfile(ti, io.BytesIO(data))
    tar = raw.getvalue()
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode='wb', mtime=0, compresslevel=9) as g:
        g.write(tar)
    return gz.getvalue(), sha(tar)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--dest', default='/app')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('files', nargs='+')
    a = ap.parse_args()
    host, repo, ref = split_ref(a.base)
    reg = Reg(host, repo)
    _, mbytes, _ = reg.call('GET', f'/v2/{repo}/manifests/{ref}', headers={'Accept': ACCEPT})
    man = json.loads(mbytes)
    if 'layers' not in man:
        sys.exit(f'основа — не одиночный манифест ({man.get("mediaType")}): индекс платформ не поддержан')
    _, cbytes, _ = reg.call('GET', f'/v2/{repo}/blobs/{man["config"]["digest"]}')
    cfg = json.loads(cbytes)
    layer, diff_id = make_layer(a.files, a.dest)
    ltype = OCI_LAYER if 'oci' in (man.get('mediaType') or '') else DOCKER_LAYER
    cfg['rootfs']['diff_ids'].append(diff_id)
    cfg.setdefault('history', []).append({'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                          'created_by': 'image_append.py (T-20261119-104): ' + ' '.join(os.path.basename(f) for f in a.files)[:200]})
    cfg['created'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    cfg_bytes = json.dumps(cfg, separators=(',', ':')).encode()
    print(f'слой {len(layer)} байт, diff_id {diff_id[:19]}…, слоёв основы {len(man["layers"])}, конфиг {len(cfg_bytes)} байт', flush=True)
    if a.dry_run:
        print('dry-run: в реестр не пишу')
        return 0
    ld = reg.put_blob(layer)
    cd = reg.put_blob(cfg_bytes)
    new = {'schemaVersion': 2, 'mediaType': man.get('mediaType'),
           'config': {'mediaType': man['config']['mediaType'], 'digest': cd, 'size': len(cfg_bytes)},
           'layers': man['layers'] + [{'mediaType': ltype, 'digest': ld, 'size': len(layer)}]}
    nb = json.dumps(new, separators=(',', ':')).encode()
    reg.call('PUT', f'/v2/{repo}/manifests/{a.tag}', nb, {'Content-Type': new['mediaType']})
    print(f'{host}/{repo}@{sha(nb)}')
    print(f'тег {a.tag}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
