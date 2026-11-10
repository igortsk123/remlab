#!/usr/bin/env python3
"""ПЕРЕСБОРКА ГОТОВЫХ ТУРОВ «КАК ЕСТЬ» — команда оператора (план agent-trial-08; T-20261110-05).

Зачем: тур собирается один раз, правки сборщика и страницы (имена товаров, вкладка плана с дверями, порядок комнат) на готовые туры
не попадают. Команда пересобирает данные страницы на ТЕКУЩЕМ коде (`tools/scout/trial_reissue.py`) из сохранённого результата и
последней версии — без нового разбора плана и без нового подбора мебели, 0 $ — и публикует новую версию; сервер закрепляет за туром
текущую витрину (`lib/trial/repo-reissue.ts`). Идёт мимо очереди воркера: сборка — секунды, ответ по каждому туру сразу.
По каждому туру — строка: опубликован (версия, витрина) / пропущен (идёт пересборка агента, срок вышел…) / отказ сборщика (тур прежний).
Что осталось прежним (мебель и исходы комнат) — в строке и в `report.json` папки прогона.

  python tools/floorplan/reissue.py --job <id> [--job <id> …]   # эти туры
  python tools/floorplan/reissue.py --days 7                    # все готовые туры младше 7 дней
  … --dry-run                                                   # собрать и показать, не публиковать
Окружение — как у воркера (`worker.py`): TRIAL_API_URL, TRIAL_WORKER_TOKEN, TRIAL_WORK_DIR (папка прогона — `<она>/reissue/<время>`).
Код выхода: 0 — всё опубликовано или пропущено штатно, 1 — хотя бы один тур не пересобран из-за сбоя или отказа.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import worker as wk  # noqa: E402
from conveyor import BUNDLE_MAX_BYTES, child_failure  # noqa: E402

READ_MAX = 24 * 1024 * 1024                  # ответ «исходник»: результат (≤ 2 МБ) + версия (≤ 8 МБ), экранированная в JSON
SKIP = ('busy', 'expired', 'not_ready', 'not_found', 'no_bundle')   # пропуски: тур не трогаем, пересборка не сбоила
WHY = {'busy': 'идёт пересборка агента', 'expired': 'срок тура вышел', 'not_ready': 'тур ещё не готов', 'not_found': 'тура нет',
       'no_bundle': 'файла версии данных нет на сервере — пересобирать не из чего', 'stale': 'версия сменилась, пока собирали'}
ROOMS = ('kept_furniture', 'kept_outcome', 'no_source', 'renamed_rooms')


def build(cfg: wk.Cfg, jid: str, d: Path, result: dict, old: str, cmd: list | None = None) -> tuple[int, dict, Path]:
    """Сборка «как есть» отдельным процессом. → (код выхода, отчёт/отказ сборщика, путь к новой версии)."""
    d.mkdir(parents=True, exist_ok=True)
    res_p, old_p, new_p, log_p = d / 'result.json', d / 'bundle-old.json', d / 'bundle-new.json', d / 'reissue.log'
    res_p.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    old_p.write_bytes(old.encode('utf-8'))                         # точные байты прежней версии — для разбора
    cmd = (cmd or [cfg.python, str(HERE.parent / 'scout' / 'trial_reissue.py')]) + [jid, str(res_p), str(old_p), '--out', str(new_p)]
    with open(log_p, 'wb') as out:
        try:
            rc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, cwd=str(HERE.parent.parent), timeout=cfg.bundle_timeout_s,
                                env={**os.environ, 'PYTHONUNBUFFERED': '1'}).returncode
        except subprocess.TimeoutExpired:
            return -1, {'why': f'timeout {cfg.bundle_timeout_s:g} s'}, new_p
    lines = [x for x in log_p.read_text(encoding='utf-8', errors='replace').splitlines() if x.strip()]
    try:
        last = json.loads(lines[-1]) if lines else {}
    except ValueError:
        last = {}
    if rc not in (0, 2):
        last = {'why': child_failure('trial_reissue', rc, log_p)}
    return rc, last, new_p


def one(api: wk.Api, cfg: wk.Cfg, jid: str, run_dir: Path, dry: bool, cmd: list | None = None) -> dict:
    """Один тур: исходник → сборка → публикация. → строка отчёта {id, status, …}."""
    st, src = api.call('GET', f'/api/trial/worker/reissue/{jid}', read_max=READ_MAX)
    if st != 200 or not isinstance(src, dict) or not src.get('ok'):
        why = (src or {}).get('error') if isinstance(src, dict) else None
        return {'id': jid, 'status': 'skipped' if why in SKIP else 'failed', 'why': why or f'http {st}'}
    base = int(src['version'])
    result = src['result']
    if src.get('edits'):                     # правки комнат агента — поверх копии результата, как у пересборок (`conveyor.Rebuild.overlay`)
        import room_edits
        result = room_edits.apply(result, src['edits'])[0]
    if src.get('openingEdits'):              # окна и двери агента — после комнат (`opening_edits.apply`, T-20261110-39)
        import opening_edits
        result = opening_edits.apply(result, src['openingEdits'])[0]
    rc, rep, new_p = build(cfg, jid, run_dir / jid, result, src['bundle'], cmd)
    if rc == 2:
        return {'id': jid, 'status': 'refused', 'why': rep.get('refusal'), 'detail': rep.get('detail'), 'from': base}
    if rc != 0 or not new_p.exists():
        return {'id': jid, 'status': 'failed', 'why': rep.get('why') or f'rc={rc}', 'from': base}
    data = new_p.read_bytes()
    if len(data) > BUNDLE_MAX_BYTES:
        return {'id': jid, 'status': 'failed', 'why': 'bundle_too_large', 'from': base}
    row = {'id': jid, 'from': base, 'same_bytes': data == src['bundle'].encode('utf-8'), **{k: rep.get(k) for k in ROOMS}}
    if dry:
        return {**row, 'status': 'built'}
    st, r = api.call('POST', f'/api/trial/worker/reissue/{jid}',
                     {'baseVersion': base, 'bundle': data.decode('utf-8'), 'sha256': hashlib.sha256(data).hexdigest()})
    if st == 200 and isinstance(r, dict) and r.get('ok'):
        return {**row, 'status': 'published', 'version': r.get('version'), 'repeated': r.get('repeated'), 'release': r.get('release'),
                'previous': r.get('previous')}
    why = (r or {}).get('error') if isinstance(r, dict) else None
    return {**row, 'status': 'skipped' if why in SKIP + ('stale',) else 'failed', 'why': why or f'http {st}'}


def line(r: dict) -> str:
    """Строка оператору по-русски: что вышло и что осталось прежним."""
    s = r['status']
    if s == 'published':
        rel = 'витрина НЕ закреплена (release_pin_failed)' if r.get('release') == 'failed' else f"витрина {str(r.get('release'))[:12]}"
        ver = f"v{r['from']} → v{r['version']}" + (' (данные те же, обновлена только витрина)' if r.get('repeated') else '')
        kept = ', '.join(r.get('kept_furniture') or []) or '—'
        tail = f"; без источника мебели (отказ с текстом): {', '.join(r['no_source'])}" if r.get('no_source') else ''
        return f"{r['id']}: опубликован {ver}, {rel}; мебель прежняя в комнатах: {kept}{tail}"
    if s == 'built':
        return f"{r['id']}: собран (без публикации), мебель прежняя в: {', '.join(r.get('kept_furniture') or []) or '—'}" + \
            (' · байты те же' if r.get('same_bytes') else '')
    if s == 'skipped':
        return f"{r['id']}: пропущен — {r['why']}: {WHY.get(r['why'], '?')} (тур не тронут)"
    if s == 'refused':
        return f"{r['id']}: отказ сборщика {r['why']} — тур остался прежним ({str(r.get('detail') or '')[:120]})"
    return f"{r['id']}: сбой — {r['why']} (тур остался прежним)"


def main(argv=None, api: wk.Api | None = None, cfg: wk.Cfg | None = None, cmd: list | None = None) -> int:
    ap = argparse.ArgumentParser(description='Пересборка готовых туров «как есть» (оператор)')
    ap.add_argument('--job', action='append', default=[], help='id тура (можно несколько раз)')
    ap.add_argument('--days', type=int, help='все готовые туры младше N дней')
    ap.add_argument('--dry-run', action='store_true', help='собрать, не публиковать')
    a = ap.parse_args(argv)
    cfg = cfg or wk.Cfg.from_env()
    if not cfg.token:
        print('нет TRIAL_WORKER_TOKEN', file=sys.stderr)
        return 2
    if not a.job and not a.days:
        ap.error('нужен --job или --days')
    api = api or wk.Api(cfg)
    ids = list(dict.fromkeys(x for x in a.job if wk.TOKEN_RE.match(x)))
    if a.days:
        st, got = api.call('GET', f'/api/trial/worker/reissue?days={int(a.days)}')
        if st != 200 or not isinstance(got, dict):
            print(f'список туров: http {st} {got}', file=sys.stderr)
            return 1
        ids += [j['id'] for j in got.get('jobs') or [] if j['id'] not in ids]
    run_dir = cfg.base / 'reissue' / time.strftime('%Y%m%d-%H%M%S')
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for jid in ids:
        try:
            r = one(api, cfg, jid, run_dir, a.dry_run, cmd)
        except wk.NetError as e:
            r = {'id': jid, 'status': 'failed', 'why': str(e)[:300]}
        rows.append(r)
        print(line(r), flush=True)
    (run_dir / 'report.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    n = {s: sum(1 for r in rows if r['status'] == s) for s in ('published', 'built', 'skipped', 'refused', 'failed')}
    print(f"итого туров {len(rows)}: " + ', '.join(f'{k} {v}' for k, v in n.items() if v) + f' · отчёт {run_dir / "report.json"}')
    return 1 if n['refused'] or n['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
