#!/usr/bin/env python3
"""Здоров ли приёмник мешей — ДО того, как отдать GPU-время нодам.

ЗАЧЕМ (04.09). Приёмник (`receiver.py`, прод) отвечает 507 «нет места» только на PUT — то есть
когда меш УЖЕ посчитан и оплачен. В ночь на 04.09 так сгорели 104 задания: диск сервера забили
старые образы докера, ноды считали и роняли отправку, сторож погасил пул через 50 минут. Утром я
проверил приёмник ПУСТЫМ файлом и получил 404 — «ок» — снял запрет, и пул сжёг ещё 385
нодо-минут. Диагноз дала только настоящая загрузка 15 МБ. Отсюда два правила этого модуля:
  1) `check()` читает `GET /health` приёмника (без токена: free_gb / dir_gb / max_dir_gb) и
     судит С ЗАПАСОМ — лестница порогов: purge снимает срок хранения при free<8 / dir>6,
     здесь отказываем при free<5+2 / dir>max−1, приёмник даёт 507 при free<5 / dir>8;
  2) `canary()` делает то, что делает нода: авторизованный PUT ~1 МБ в staging и DELETE.
     Проверяет Caddy, TLS, токен и запись целиком — ровно то, что поймало бы 507 утром.

Кто зовёт: `ssh_run.run()` перед раздачей (оба), супервизор `ssh_run` раз в POLL_S (`check`),
`money_guard` раз в тик (`check`). Оповещение — с дросселем: одна авария = одно сообщение в час.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SINK_URL = os.environ.get('MESH_SINK_URL', 'https://remont-lab.online/mesh-sink').rstrip('/')
HEALTH_URL = os.environ.get('MESH_SINK_HEALTH_URL', SINK_URL + '/health')
MARGIN_GB = float(os.environ.get('MESH_SINK_MARGIN_GB', '2'))
MIN_FREE_GB = float(os.environ.get('MESH_MIN_FREE_GB', '5'))      # порог самого приёмника
ALERT_STAMP = os.path.expanduser('~/scout-scenes/.sink-alert-at')
ALERT_EVERY_S = float(os.environ.get('MESH_SINK_ALERT_EVERY_S', '3600'))
UA = 'remlab-mesh/1.0'


def _get(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b'{}')


def check() -> dict:
    """{'ok', 'why', 'free_gb', 'dir_gb', 'max_dir_gb'}. Недоступен — ok=False: ноды идут тем же
    адресом, раздавать им работу нельзя."""
    last = ''
    for attempt in (1, 2):
        try:
            h = _get(HEALTH_URL)
            free, d, mx = float(h.get('free_gb', 0)), float(h.get('dir_gb', 0)), float(h.get('max_dir_gb', 8))
            # /ready (если приёмник его уже умеет) сам говорит «нет»; /health всегда ok:true
            if h.get('ok') is False:
                return {'ok': False, 'why': f'приёмник сам отказывает: {h.get("detail") or h}',
                        'free_gb': free, 'dir_gb': d, 'max_dir_gb': mx}
            if free < MIN_FREE_GB + MARGIN_GB:
                return {'ok': False, 'why': f'на сервере свободно {free:.1f} ГБ (< {MIN_FREE_GB + MARGIN_GB:.0f})',
                        'free_gb': free, 'dir_gb': d, 'max_dir_gb': mx}
            if d > mx - 1:
                return {'ok': False, 'why': f'каталог приёмника {d:.1f} ГБ (предел {mx:.0f}) — нужен drain',
                        'free_gb': free, 'dir_gb': d, 'max_dir_gb': mx}
            return {'ok': True, 'why': '', 'free_gb': free, 'dir_gb': d, 'max_dir_gb': mx}
        except Exception as e:  # noqa: BLE001 — сеть/таймаут: вторая попытка, потом «недоступен»
            last = f'{type(e).__name__}: {str(e)[:80]}'
            if attempt == 1:
                time.sleep(5)
    return {'ok': False, 'why': f'приёмник недоступен ({last})', 'free_gb': 0, 'dir_gb': 0, 'max_dir_gb': 0}


def sink_token() -> str:
    """Токен приёмника: из окружения или из переменных первой группы Salad (там он и живёт)."""
    tok = os.environ.get('MESH_SINK_TOKEN')
    if tok:
        return tok
    key = os.environ.get('SALAD_API_KEY', '')
    grp = os.environ.get('SALAD_GROUP', '').split(',')[0].strip()
    if not key or not grp:
        return ''
    try:
        req = urllib.request.Request(
            f'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers/{grp}',
            headers={'Salad-Api-Key': key, 'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            env = (json.loads(r.read()).get('container') or {}).get('environment_variables') or {}
        return env.get('MESH_SINK_TOKEN', '')
    except Exception:  # noqa: BLE001
        return ''


def canary(size_mb: float = 1.0) -> dict:
    """PUT ~1 МБ в staging/_canary/<метка>/probe.bin и DELETE. {'ok', 'why', 'sec'}."""
    tok = sink_token()
    if not tok:
        return {'ok': False, 'why': 'нет токена приёмника (MESH_SINK_TOKEN / переменные группы)', 'sec': 0}
    mark = f'_canary/{int(time.time())}'
    body = os.urandom(int(size_mb * 1024 * 1024))
    t0 = time.time()
    try:
        req = urllib.request.Request(f'{SINK_URL}/staging/{mark}/probe.bin', data=body, method='PUT',
                                     headers={'Authorization': f'Bearer {tok}', 'User-Agent': UA,
                                              'Content-Type': 'application/octet-stream'})
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
    except urllib.error.HTTPError as e:
        return {'ok': False, 'why': f'PUT {size_mb:.0f} МБ → HTTP {e.code} {e.read()[:120]!r}', 'sec': time.time() - t0}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'why': f'PUT {size_mb:.0f} МБ → {type(e).__name__}: {str(e)[:80]}', 'sec': time.time() - t0}
    sec = time.time() - t0
    try:   # не удалилось — не страшно: `.staging` старше 6 ч уберёт receiver_purge
        req = urllib.request.Request(f'{SINK_URL}/{mark}', method='DELETE',
                                     headers={'Authorization': f'Bearer {tok}', 'User-Agent': UA})
        urllib.request.urlopen(req, timeout=30).read()
    except Exception:  # noqa: BLE001
        pass
    return {'ok': True, 'why': '', 'sec': sec}


def alert_throttled(text: str) -> bool:
    """Одно сообщение в ALERT_EVERY_S — авария одна, а проверяющих трое (run, супервизор, сторож)."""
    try:
        last = float(open(ALERT_STAMP).read().strip() or 0)
    except Exception:  # noqa: BLE001
        last = 0.0
    if time.time() - last < ALERT_EVERY_S:
        return False
    try:
        open(ALERT_STAMP, 'w').write(str(time.time()))
        subprocess.run(['bash', os.path.join(HERE, '..', 'alert.sh'), text], timeout=30,
                       capture_output=True, check=False)
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == '__main__':
    h = check()
    print('health:', h)
    if '--canary' in os.sys.argv:
        print('canary:', canary())
