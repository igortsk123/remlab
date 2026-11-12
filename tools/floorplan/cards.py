#!/usr/bin/env python3
"""ГОТОВЫЕ СНИМКИ КАРТОЧЕК КОМНАТ ТУРА (T-20261112-29, владелец: «почему когда захожу — сначала план-схема, потом 3D-фото»).

Карточка комнаты тура показывала схему плана, пока страница покупателя сама не снимет кадр 3D (`index.html:trHomeShot`, ~5 с на
телефоне при каждом заходе). Теперь кадр снимается один раз на DEV после публикации версии — ТОЙ ЖЕ функцией на ТОЙ ЖЕ странице тура
(`tools/scout/trial_cards.mjs`, Playwright, телефонный режим) — и уходит на прод (`POST /api/trial/worker/cards`). Сервер кладёт карту
«ключ расстановки → файл» прямо в HTML страницы (`lib/trial/tour-page.ts:injectTour`): карточка с картинкой с первого кадра, новой
версии данных не нужно, открытая страница не перезагружается. Правленая агентом расстановка — другой ключ: страница снимет сама, как раньше.

Кто зовёт: конвейер после итоговой версии (`conveyor.Conveyor._finish`, и «Обустроить» тоже) и перевыпуск (`reissue.one`) — `spawn`:
отдельный процесс в своей временной службе (`systemd-run --user`, свой потолок памяти и ядер, не в 2 ядрах воркера), воркер не ждёт.
Тяжёлое (браузер с программным 3D) — под общей очередью `tools/ops/heavy-slot.sh`. Не вышло — тур как был (страница снимет сама).

  python tools/floorplan/cards.py --job <id> [--job <id> …]   # снять и отправить (окружение воркера: TRIAL_API_URL, TRIAL_WORKER_TOKEN)
  … --dry-run [--out папка]                                   # снять, не отправлять (кадры — в папку прогона)
Код выхода: 0 — все туры с кадрами (или снимать нечего), 1 — хоть один не снят / не принят.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

KEY_RE = re.compile(r'^[a-z0-9-]{1,40}\|[A-Za-z0-9_.-]{1,80}\|[A-Za-z0-9_-]{1,80}$')   # = contracts/trial-cards.ts:CARD_KEY_RE
CARD_MAX_BYTES = 400 * 1024                                                            # = CARD_MAX_BYTES
PER_POST = 8                                                                           # = CARDS_PER_POST
RENDER_TIMEOUT_S = 600            # сам браузер: 17 вариантов ≈ 77 с на 4 ядрах (замер T-29); очередь heavy-slot — отдельно
SLOT_WAIT_S = 1800
SLOT_PRIO = 1                     # как стадии пробы (`conveyor.SLOT_PRIO_TRIAL`)


def tour_url(api_url: str, jid: str) -> str:
    return f'{api_url.rstrip("/")}/try/{jid}/tour/'


def render_cmd(url: str, out: Path) -> list:
    node = shutil.which('node') or '/usr/local/bin/node'
    return [str(ROOT / 'tools' / 'ops' / 'heavy-slot.sh'), 'trial-cards', '--min-gb', '2', '--cores', '4', '--prio', str(SLOT_PRIO),
            '--timeout', str(SLOT_WAIT_S), '--', node, str(ROOT / 'tools' / 'scout' / 'trial_cards.mjs'), url, str(out),
            '--timeout', str(RENDER_TIMEOUT_S)]


def parse_cards(res: dict) -> list[dict]:
    """Выход снимальщика → годные кадры {key, jpg(base64)}: ключ по формату сервера, JPEG не больше потолка. Прочее отбрасывается."""
    out = []
    for c in (res or {}).get('cards') or []:
        if not isinstance(c, dict) or not isinstance(c.get('jpg'), str) or not KEY_RE.match(str(c.get('key') or '')):
            continue
        try:
            raw = base64.b64decode(c['jpg'], validate=True)
        except (ValueError, TypeError):
            continue
        if 100 <= len(raw) <= CARD_MAX_BYTES and raw[:3] == b'\xff\xd8\xff':
            out.append({'key': c['key'], 'jpg': c['jpg']})
    return out


def upload(call, jid: str, cards: list[dict]) -> tuple[int, str | None]:
    """Кадры на прод порциями по PER_POST. `call(method, path, body)` → (статус, JSON). → (принято кадров, ошибка или None)."""
    sent = 0
    for i in range(0, len(cards), PER_POST):
        part = cards[i:i + PER_POST]
        st, r = call('POST', '/api/trial/worker/cards', {'id': jid, 'cards': part})
        if st != 200 or not isinstance(r, dict) or not r.get('ok'):
            return sent, f'http {st} {(r or {}).get("error") if isinstance(r, dict) else ""}'.strip()
        sent += len(part)
    return sent, None


def make(jid: str, api_url: str, run_dir: Path, call=None, dry: bool = False, cmd=None, runner=subprocess.run) -> dict:
    """Один тур: снять кадры страницы тура → отправить. → строка отчёта."""
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f'{jid}.json'
    t0 = time.time()
    try:
        rc = runner(cmd or render_cmd(tour_url(api_url, jid), out), cwd=str(ROOT), timeout=SLOT_WAIT_S + RENDER_TIMEOUT_S + 60).returncode
    except subprocess.TimeoutExpired:
        return {'id': jid, 'status': 'failed', 'why': 'timeout'}
    try:
        res = json.loads(out.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        res = {}
    cards = parse_cards(res)
    errs = [c for c in res.get('cards') or [] if isinstance(c, dict) and c.get('err')]
    row = {'id': jid, 'rc': rc, 'render_s': round(time.time() - t0, 1), 'cards': len(cards), 'errors': len(errs),
           **({'error': res.get('error')} if res.get('error') else {})}
    if rc not in (0,) and not cards:
        return {**row, 'status': 'failed', 'why': res.get('error') or f'rc={rc}'}
    if not cards:
        return {**row, 'status': 'empty'}
    if dry:
        return {**row, 'status': 'rendered'}
    sent, err = upload(call, jid, cards)
    out.write_text(json.dumps({**res, 'cards': [{k: v for k, v in c.items() if k != 'jpg'} for c in res.get('cards') or []]}),
                   encoding='utf-8')                     # кадры приняты — в журнале остаётся только сводка
    return {**row, 'sent': sent, 'status': 'sent' if not err else 'failed', **({'why': err} if err else {})}


PASS_ENV = ('TRIAL_API_URL', 'TRIAL_WORKER_TOKEN', 'TRIAL_WORK_DIR', 'PATH', 'TMPDIR', 'PLAYWRIGHT_BROWSERS_PATH', 'HOME')


def spawn(jid: str, log_dir: Path, python: str = sys.executable, runner=subprocess.run, log=print, env=os.environ) -> bool:
    """Снять и отправить кадры тура В ФОНЕ: временная служба `systemd-run --user` со своим потолком (вне 2 ядер и 2 ГБ воркера),
    токен и адрес — из окружения вызывающего (`-E` не пишет значение в командную строку). → True — служба запущена."""
    log_dir.mkdir(parents=True, exist_ok=True)
    unit = f'remlab-cards-{re.sub(r"[^A-Za-z0-9_-]", "", jid)[:24]}-{int(time.time())}'
    lf = log_dir / f'{jid}.log'
    # TMPDIR — браузеру нужен диск, не /tmp с квотой; передаём только то, что задано у вызывающего
    envs = [x for n in PASS_ENV if n in env for x in ('-E', n)]
    cmd = ['systemd-run', '--user', '--collect', '--quiet', f'--unit={unit}', '--nice=15',
           '-p', 'MemoryMax=1536M', '-p', 'CPUQuota=400%', '-p', f'StandardOutput=append:{lf}', '-p', f'StandardError=append:{lf}',
           f'--working-directory={ROOT}', *envs, '--', python, str(HERE / 'cards.py'), '--job', jid]
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f'cards {jid}: фон не запущен — {type(e).__name__}: {e}')
        return False
    if r.returncode != 0:
        log(f'cards {jid}: фон не запущен — systemd-run rc={r.returncode} {(r.stderr or "").strip()[:200]}')
        return False
    log(f'cards {jid}: снимки карточек — в фоне ({unit}, журнал {lf})')
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Готовые снимки карточек комнат тура')
    ap.add_argument('--job', action='append', default=[], help='id тура (можно несколько раз)')
    ap.add_argument('--dry-run', action='store_true', help='снять, не отправлять')
    ap.add_argument('--out', help='папка прогона (по умолчанию <TRIAL_WORK_DIR>/cards/<время>)')
    a = ap.parse_args(argv)
    if not a.job:
        ap.error('нужен --job')
    import worker as wk
    cfg = wk.Cfg.from_env()
    if not a.dry_run and not cfg.token:
        print('нет TRIAL_WORKER_TOKEN — отправлять нечем (или --dry-run)', file=sys.stderr)
        return 2
    api = wk.Api(cfg)
    run_dir = Path(a.out).expanduser() if a.out else cfg.base / 'cards' / time.strftime('%Y%m%d-%H%M%S')

    def call(method, path, body):
        try:
            return api.call(method, path, body)
        except wk.NetError as e:
            return None, {'error': str(e)[:200]}
    rows = [make(j, cfg.url, run_dir, call, a.dry_run) for j in a.job]
    for r in rows:
        print(json.dumps(r, ensure_ascii=False), flush=True)
    return 0 if all(r['status'] in ('sent', 'rendered', 'empty') for r in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
