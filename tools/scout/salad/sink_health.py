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

ОДНА МЕРА ДЛЯ ВОРОТ И ЧИСТКИ (20.10, mesh-12). 17.10 ворота закрылись на «каталоге 7.1 ГБ», а
чистка в это же время насчитала у себя 0.6 ГБ комплектов (`du` по каталогам) — и «тесно» не
включила: две меры одного каталога разошлись на 5.6 ГБ, и пул простоял до стоп-файла. Теперь мера
одна — `measure()`: числа самого приёмника из /health, те же, по которым он отвечает 507. Пороги
лестницы — тоже здесь, и «тесно» (`tight`) всегда строго раньше ворот (`verdict`):
  dir:  тесно > max−2  →  ворота > max−1  →  507 приёмника > max;
  free: тесно < 5+2+1  →  ворота < 5+2    →  507 приёмника < 5.
Чистка, супервизор и сторож приёмника берут пороги отсюда, своих копий у них нет.
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
# Ступени лестницы, ГБ: ворота закрываются за GATE_BELOW до 507, «тесно» — ещё за TIGHT_BELOW до ворот.
# Нулевой зазор — та же мина, что 17.10 (чистка спохватывается, когда раздача уже стоит), поэтому
# недопустимая настройка роняет импорт, а не тихо выравнивает пороги.
GATE_BELOW_GB = float(os.environ.get('MESH_SINK_GATE_BELOW_GB', '1'))
TIGHT_BELOW_GB = float(os.environ.get('MESH_SINK_TIGHT_BELOW_GB', '1'))
if GATE_BELOW_GB < 0 or TIGHT_BELOW_GB <= 0:
    raise ValueError(f'лестница приёмника без зазора: ворота {GATE_BELOW_GB}, тесно {TIGHT_BELOW_GB}')
ALERT_STAMP = os.path.expanduser('~/scout-scenes/.sink-alert-at')
ALERT_EVERY_S = float(os.environ.get('MESH_SINK_ALERT_EVERY_S', '3600'))
UA = 'remlab-mesh/1.0'


def _get(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b'{}')


def gate_dir_gb(mx: float) -> float:
    """Каталог больше этого — ворота закрыты, задания не раздаём."""
    return mx - GATE_BELOW_GB


def tight_dir_gb(mx: float) -> float:
    """Каталог больше этого — «тесно»: чистка не ждёт срока хранения, супервизор зовёт уборку."""
    return gate_dir_gb(mx) - TIGHT_BELOW_GB


def gate_free_gb() -> float:
    return MIN_FREE_GB + MARGIN_GB


def tight_free_gb() -> float:
    return gate_free_gb() + TIGHT_BELOW_GB


def measure() -> dict:
    """ОДНА МЕРА приёмника: {'free_gb', 'dir_gb', 'max_dir_gb', 'refuses'} из его /health.
    Исключение — приёмник не ответил (решает вызывающий: ворота — «закрыто», чистка — пропуск)."""
    h = _get(HEALTH_URL)
    return {'free_gb': float(h.get('free_gb', 0)), 'dir_gb': float(h.get('dir_gb', 0)),
            'max_dir_gb': float(h.get('max_dir_gb', 8)),
            # /ready (если приёмник его уже умеет) сам говорит «нет»; /health всегда ok:true
            'refuses': (h.get('detail') or str(h)) if h.get('ok') is False else ''}


def verdict(m: dict) -> dict:
    """Ворота по мере `measure()`: {'ok', 'why', 'free_gb', 'dir_gb', 'max_dir_gb'}."""
    free, d, mx = m['free_gb'], m['dir_gb'], m['max_dir_gb']
    nums = {'free_gb': free, 'dir_gb': d, 'max_dir_gb': mx}
    if m.get('refuses'):
        return {'ok': False, 'why': f'приёмник сам отказывает: {m["refuses"]}', **nums}
    if free < gate_free_gb():
        return {'ok': False, 'why': f'на сервере свободно {free:.1f} ГБ (< {gate_free_gb():.0f})', **nums}
    if d > gate_dir_gb(mx):
        return {'ok': False, 'why': f'каталог приёмника {d:.1f} ГБ (предел {mx:.0f}) — нужен drain', **nums}
    return {'ok': True, 'why': '', **nums}


def tight(m: dict) -> str:
    """«Тесно» по той же мере, что ворота, и строго раньше них. Пусто — не тесно, иначе причина."""
    if m['free_gb'] < tight_free_gb():
        return f'свободно {m["free_gb"]:.1f} ГБ (< {tight_free_gb():.0f})'
    if m['dir_gb'] > tight_dir_gb(m['max_dir_gb']):
        return f'каталог {m["dir_gb"]:.1f} ГБ (> {tight_dir_gb(m["max_dir_gb"]):.0f}, ворота на {gate_dir_gb(m["max_dir_gb"]):.0f})'
    return ''


def check() -> dict:
    """{'ok', 'why', 'free_gb', 'dir_gb', 'max_dir_gb', 'tight'}. Недоступен — ok=False: ноды идут
    тем же адресом, раздавать им работу нельзя."""
    last = ''
    for attempt in (1, 2):
        try:
            m = measure()
            return {**verdict(m), 'tight': tight(m)}
        except Exception as e:  # noqa: BLE001 — сеть/таймаут: вторая попытка, потом «недоступен»
            last = f'{type(e).__name__}: {str(e)[:80]}'
            if attempt == 1:
                time.sleep(5)
    return {'ok': False, 'why': f'приёмник недоступен ({last})', 'free_gb': 0, 'dir_gb': 0, 'max_dir_gb': 0,
            'tight': ''}


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
    # УДАЛЯТЬ НАДО ПО `/prefix/...` (04.09). Раньше слали DELETE на `/{mark}`, а приёмник
    # принимает удаление только с этим префиксом (`receiver.do_DELETE`) — отвечал 404, ошибка
    # глушилась, и КАЖДАЯ канарейка оставляла на транзите ~1 МБ. Хуже, чем мусор: байты уже
    # учтены счётчиком приёмника и без его же DELETE никогда не вычитались.
    try:
        req = urllib.request.Request(f'{SINK_URL}/prefix/{mark}', method='DELETE',
                                     headers={'Authorization': f'Bearer {tok}', 'User-Agent': UA})
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:  # noqa: BLE001 — не удалилось: скажем вслух, молчать здесь дорого
        print(f'канарейка: не убрала за собой {mark} ({type(e).__name__}: {str(e)[:60]})')
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
