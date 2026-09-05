#!/usr/bin/env python3
"""Партии моделей для ручной приёмки (/lab/mesh-audit): заливка на прод и удаление КОПИЙ.

ПРАВИЛА (решение владельца 05.09 + разбор Codex):
  * исходники на DEV не удаляются НИКОГДА — здесь нет ни одной операции удаления над
    ~/scout-scenes/**; локальная сборка партии — жёсткие ссылки в ~/.cache, и только она чистится;
  * на проде удаляется только каталог ВНУТРИ фиксированного корня releases/, с именем-токеном
    (16 hex) и собственным manifest.json — путь собирается из проверенного токена, не из строки API;
  * порядок «залить → проверить → переключить → выждать → удалить прежнюю»: обрыв связи оставляет
    прежнюю партию активной, открытая вкладка владельца не остаётся без моделей;
  * место: свободно − партия − запас ≥ 7 ГБ (порог приёмника конвейера на том же диске: 5 + 2).

Состав партии берётся С ПРОДА (страницы партии через API) — порядок карточек хранится там.

  ~/venvs/scout/bin/python mesh_audit_publish.py --token <hex16> --batch N   # залить партию
  ~/venvs/scout/bin/python mesh_audit_publish.py --cleanup                   # удалить отслужившие
  python3 mesh_audit_publish.py --selftest
"""
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SSH = ['ssh', '-p', '22222', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', 'root@89.167.127.0']
REMOTE_ROOT = '/opt/remlab/test/mesh-audit/releases'
STAGE_ROOT = os.path.expanduser('~/.cache/mesh-audit-stage')
LOCK = os.path.expanduser('~/scout-scenes/mesh-audit/publish.lock')
TOKEN_RE = re.compile(r'^[0-9a-f]{16}$')
MIN_FREE_GB = 7.0        # sink_health: MIN_FREE_GB 5 + MARGIN_GB 2
RESERVE_GB = 0.5
GRACE_S = 600            # прежняя партия живёт ещё 10 минут после переключения
PAGES_PER_BATCH = 10     # = lib/mesh-audit/rules.ts (BATCH_SIZE / PAGE_SIZE)
CHUNK = 20               # файлов на один вызов rsync → отчёт о прогрессе после каждого


# ---------------------------------------------------------------- чистые правила (selftest)

def token_ok(token: str) -> bool:
    return bool(TOKEN_RE.match(token or ''))


def remote_dir(token: str, staging: bool = False) -> str:
    """Единственный способ получить путь для удаления/переименования: из ПРОВЕРЕННОГО токена."""
    if not token_ok(token):
        raise ValueError(f'плохой токен партии: {token!r}')
    return f'{REMOTE_ROOT}/{token}' + ('.staging' if staging else '')


def deletable(path: str) -> bool:
    """Удалять можно только `<корень>/<hex16>` или `<корень>/<hex16>.staging` — ничего выше и рядом."""
    if not path.startswith(REMOTE_ROOT + '/'):
        return False
    tail = path[len(REMOTE_ROOT) + 1:]
    return bool(re.match(r'^[0-9a-f]{16}(\.staging)?$', tail))


def enough_space(free_gb: float, batch_gb: float) -> bool:
    return free_gb - batch_gb - RESERVE_GB >= MIN_FREE_GB


def manifest_ok(expected: dict, actual: dict) -> list[str]:
    """Расхождения ожидаемого манифеста (что залили) с фактическим (что лежит на проде)."""
    bad = []
    for rel, meta in expected.items():
        got = actual.get(rel)
        if not got:
            bad.append(f'нет файла {rel}')
        elif got.get('bytes') != meta['bytes'] or got.get('sha') != meta['sha']:
            bad.append(f'{rel}: размер/хеш не совпал')
    return bad


# ---------------------------------------------------------------- прод API

def _api(method: str, path: str, body: dict | None = None) -> dict:
    from mesh_audit_sync import api
    return api(method, path, body)


def report(token: str, **patch) -> None:
    try:
        _api('PATCH', '/api/lab/mesh-audit/batch', {'token': token, **patch})
    except Exception as e:  # noqa: BLE001 — отчёт о прогрессе не должен ронять заливку
        print(f'  отчёт партии не дошёл: {type(e).__name__}', flush=True)


def batch_items(batch: int) -> list[dict]:
    items = []
    for page in range((batch - 1) * PAGES_PER_BATCH + 1, batch * PAGES_PER_BATCH + 1):
        r = _api('GET', f'/api/lab/mesh-audit/items?page={page}')
        if r.get('page') != page:
            break                      # страниц меньше — партия неполная (последняя)
        items.extend(r.get('items', []))
    return items


# ---------------------------------------------------------------- прод: ssh

def ssh(cmd: str, timeout: int = 120) -> str:
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f'ssh: {r.stderr.strip()[:200]}')
    return r.stdout


def remote_free_gb() -> float:
    return int(ssh('df -B1 --output=avail /opt/remlab | tail -1').strip()) / 2 ** 30


def remote_rm(path: str) -> None:
    if not deletable(path):
        raise ValueError(f'ОТКАЗ: путь вне корня партий — {path}')
    ssh(f'rm -rf -- {path}')


# ---------------------------------------------------------------- заливка

def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''):
            h.update(ch)
    return h.hexdigest()


def stage(token: str, items: list[dict]) -> tuple[str, dict]:
    """Локальная сборка партии ЖЁСТКИМИ ССЫЛКАМИ (тот же раздел): ни копий, ни касания оригиналов."""
    from mesh_queue import db
    root = os.path.join(STAGE_ROOT, token)
    shutil.rmtree(root, ignore_errors=True)    # только наш кэш сборки
    os.makedirs(root, exist_ok=True)
    keys = {it['generationKey'] for it in items}
    lit = ','.join("'" + k.replace("'", "''") + "'" for k in keys) or "''"
    paths = {r[0]: r[1] for r in db(f"select generation_key, path from mesh_generations where generation_key in ({lit})")
             if len(r) == 2}
    manifest = {}
    for it in items:
        src = os.path.join(paths.get(it['generationKey'], ''), 'model.glb')
        if not os.path.exists(src):
            print(f'  нет модели для {it["sku"]} ({it["generationKey"]}) — пропуск', flush=True)
            continue
        dst = os.path.join(root, it['modelPath'])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.link(src, dst)
        manifest[it['modelPath']] = {'bytes': os.path.getsize(src), 'sha': _sha(src)}
    json.dump(manifest, open(os.path.join(root, 'manifest.json'), 'w'), indent=1)
    return root, manifest


def upload(token: str, root: str, manifest: dict) -> None:
    dst = remote_dir(token, staging=True)
    ssh(f'mkdir -p {dst}')
    rels = sorted(manifest)
    for i in range(0, len(rels), CHUNK):
        lst = '\n'.join(rels[i:i + CHUNK]) + '\nmanifest.json\n'
        r = subprocess.run(['rsync', '-a', '--files-from=-', '-e', 'ssh -p 22222 -o BatchMode=yes',
                            root + '/', 'root@89.167.127.0:' + dst + '/'],
                           input=lst, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            raise RuntimeError(f'rsync: {r.stderr.strip()[-200:]}')
        report(token, status='uploading', filesDone=min(i + CHUNK, len(rels)), filesTotal=len(rels))


def verify(token: str, manifest: dict) -> None:
    dst = remote_dir(token, staging=True)
    out = ssh(f'cd {dst} && find . -type f -name model.glb -printf "%P\\t%s\\n" | while IFS=$\'\\t\' read -r p s; '
              f'do printf "%s\\t%s\\t%s\\n" "$p" "$s" "$(sha256sum -- "$p" | cut -d" " -f1)"; done', timeout=900)
    actual = {}
    for ln in out.splitlines():
        p, s, h = ln.split('\t')
        actual[p] = {'bytes': int(s), 'sha': h}
    bad = manifest_ok(manifest, actual)
    if bad:
        raise RuntimeError('проверка партии: ' + '; '.join(bad[:5]))


def publish(token: str, batch: int) -> int:
    """Любой сбой ДО заливки (прод отвечает 502 во время деплоя, нет модели, нет места) тоже
    обязан стать `failed` на проде — иначе партия зависает в `requested`/`uploading`, а владелец
    не понимает, почему кнопка молчит. После `failed` кнопку можно нажать снова."""
    if not token_ok(token):
        raise SystemExit(f'плохой токен: {token!r}')
    try:
        return _publish(token, batch)
    except Exception as e:  # noqa: BLE001 — отчёт важнее трассы; трасса всё равно в логе
        report(token, status='failed', error=f'{type(e).__name__}: {str(e)[:160]}')
        raise


def _publish(token: str, batch: int) -> int:
    items = batch_items(batch)
    if not items:
        report(token, status='failed', error='в партии нет карточек')
        return 1
    root, manifest = stage(token, items)
    batch_gb = sum(m['bytes'] for m in manifest.values()) / 2 ** 30
    free = remote_free_gb()
    if not enough_space(free, batch_gb):
        report(token, status='failed', error=f'на проде свободно {free:.1f} ГБ, партия {batch_gb:.1f} ГБ — порог 7 ГБ')
        shutil.rmtree(root, ignore_errors=True)
        return 1
    report(token, status='uploading', filesTotal=len(manifest), filesDone=0, bytesTotal=int(batch_gb * 2 ** 30))
    try:
        upload(token, root, manifest)
        report(token, status='verifying')
        verify(token, manifest)
        ssh(f'mv -T -- {remote_dir(token, staging=True)} {remote_dir(token)}')
        # состав партии по sku: страница решает «есть 3D» по нему, а не по номеру страницы
        skus = [it['sku'] for it in items if it['modelPath'] in manifest]
        report(token, status='active', filesDone=len(manifest), filesTotal=len(manifest), skus=skus)
        print(f'партия {batch} активна: {len(manifest)} моделей, {batch_gb:.2f} ГБ, токен {token}', flush=True)
        return 0
    except Exception as e:  # noqa: BLE001 — любая ошибка: прежняя партия остаётся активной
        report(token, status='failed', error=f'{type(e).__name__}: {str(e)[:160]}')
        print(f'партия {batch} НЕ опубликована: {e}', flush=True)
        return 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def cleanup() -> None:
    """Удалить прежнюю партию после grace и брошенные staging-каталоги старше суток."""
    st = _api('GET', '/api/lab/mesh-audit/batch')
    ret, act = st.get('retiring'), st.get('active')
    if ret and act and act.get('activatedAt'):
        t = time.mktime(time.strptime(act['activatedAt'][:19], '%Y-%m-%dT%H:%M:%S'))
        if time.time() - t >= GRACE_S and token_ok(ret['token']):
            remote_rm(remote_dir(ret['token']))
            report(ret['token'], status='removed')
            print(f'прежняя партия {ret["batch"]} ({ret["token"]}) удалена с прода', flush=True)
    for name in ssh(f'find {REMOTE_ROOT} -maxdepth 1 -mindepth 1 -type d -name "*.staging" -mmin +1440 -printf "%f\\n" 2>/dev/null || true').split():
        p = f'{REMOTE_ROOT}/{name}'
        if deletable(p):
            remote_rm(p)
            print(f'брошенный staging удалён: {name}', flush=True)


def _selftest() -> int:
    bad = 0
    if not token_ok('0123456789abcdef') or token_ok('0123456789ABCDEF') or token_ok('../etc') or token_ok(''):
        bad += 1; print('  FAIL token_ok')
    for p, want in ((f'{REMOTE_ROOT}/0123456789abcdef', True), (f'{REMOTE_ROOT}/0123456789abcdef.staging', True),
                    (REMOTE_ROOT, False), (f'{REMOTE_ROOT}/', False), (f'{REMOTE_ROOT}/../posters', False),
                    ('/opt/remlab/test/mesh-audit/posters', False), (f'{REMOTE_ROOT}/0123456789abcdef/x', False),
                    ('/home/pakar/scout-scenes/meshes-hunyuan', False)):
        if deletable(p) != want:
            bad += 1; print(f'  FAIL deletable {p}: ожидалось {want}')
    try:
        remote_dir('x/../..')
        bad += 1; print('  FAIL remote_dir принял плохой токен')
    except ValueError:
        pass
    # 9.0 − 1.5 − 0.5 = ровно 7 → ещё можно; 8.9 → уже нет
    if enough_space(17.0, 1.5) is not True or enough_space(9.0, 1.5) is not True or enough_space(8.9, 1.5) is not False:
        bad += 1; print('  FAIL enough_space')
    exp = {'a/model.glb': {'bytes': 10, 'sha': 'x'}, 'b/model.glb': {'bytes': 5, 'sha': 'y'}}
    if manifest_ok(exp, {'a/model.glb': {'bytes': 10, 'sha': 'x'}, 'b/model.glb': {'bytes': 5, 'sha': 'y'}}):
        bad += 1; print('  FAIL manifest_ok: ложная тревога')
    if len(manifest_ok(exp, {'a/model.glb': {'bytes': 10, 'sha': 'z'}})) != 2:
        bad += 1; print('  FAIL manifest_ok: не поймал расхождения')
    print(f'mesh_audit_publish selftest: случаев 13, ошибок {bad}')
    return 1 if bad else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    lock = open(LOCK, 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('публикатор уже работает', flush=True)
        return 75
    if '--cleanup' in sys.argv:
        cleanup()
        return 0
    token = sys.argv[sys.argv.index('--token') + 1]
    batch = int(sys.argv[sys.argv.index('--batch') + 1])
    return publish(token, batch)


if __name__ == '__main__':
    sys.exit(main())
