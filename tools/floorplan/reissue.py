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

«ПЕРЕЧИТАТЬ ПЛАНИРОВКУ» (план trial-reparse-01; T-20261111-02) — `--reparse`: исходный лист тура заново через текущий разбор (кэш VLM,
0 $), мебель заново, ОДНА версия с новым `result` — только если сторож регресса чист (`regress.guard_*`) или разница одобрена:
  … --reparse --dry-run [--sheets f.tsv] [--out папка]          # на DEV как на проде (`conveyor.Reparse`), без постановки:
                                                                # таблица «комната: было → стало» и вердикт сторожа по каждому туру
  … --reparse [--approve f.tsv]                                 # боевой: по одной пересборке на воркер, ждёт исход каждой
`--sheets` — TSV «id тура, лист, [файл текста объявления|-]»: лист для пробного прогона (сервер отдаёт лист только воркеру под арендой).
`--approve` — TSV «id тура, ключ находки, [почему]»: адресное одобрение конкретной разницы (`<TRIAL_WORK_DIR>/reparse-approve/<id>.json`,
его читает воркер); ключи — из таблицы пробного прогона. Пробный прогон дособирает мебель и при находках сторожа (чтобы «стало» было
видно до одобрения); боевой при неодобренной разнице разбора останавливается до мебели. Из worktree — данные мебели основной копии
(их нет в git): TRIAL_SETS=<копия>/tools/scout/sets3.json, TRIAL_BEDROOM_SETS=<копия>/tools/scout/sets-bedroom.json,
BEDROOM_STYLE_SCORES=<копия>/tools/scout/style-scores-bedroom.json (без банка спален все спальни — `refused/no_products`).
Одобрение пропускает тур, только если одобрены ВСЕ его находки (`regress.verdict`), и «изм.», и «БЛОК».
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
                                # срок стадии — подбор ракурсов кладёт себя в него (T-20261111-23, `trial_bundle.cams_budget`)
                                env={**os.environ, 'PYTHONUNBUFFERED': '1', 'TRIAL_STAGE_TIMEOUT_S': f'{cfg.bundle_timeout_s:g}'}).returncode
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


# ───────────────────────── «перечитать планировку» ─────────────────────────
VERDICT = {'same': 'чисто — прочитано то же самое', 'clean': 'чисто — разницы нет', 'approved': 'чисто — разница одобрена',
           'block': 'блок', 'change': 'улучшение/изменение — нужна приёмка'}


def read_tsv(path: str | None) -> dict:
    """TSV → {id тура: [поля…]}, `#` — комментарий."""
    out: dict = {}
    if path:
        for ln in Path(path).expanduser().read_text(encoding='utf-8').splitlines():
            f = [x.strip() for x in ln.split('\t')]
            if ln.strip() and not ln.startswith('#') and len(f) >= 2:
                out.setdefault(f[0], []).append(f[1:])
    return out


def approvals(cfg: wk.Cfg, path: str | None, write: bool) -> dict:
    """Одобрения: файл `--approve` (по туру — ключи находок) поверх уже записанных в `<base>/reparse-approve/`; `write` — записать для
    воркера (боевой проход)."""
    d = cfg.base / 'reparse-approve'
    got = {}
    for f in d.glob('*.json') if d.is_dir() else []:
        try:
            got[f.stem] = list(json.loads(f.read_text(encoding='utf-8')).get('keys') or [])
        except (OSError, ValueError):
            pass
    for jid, rows in read_tsv(path).items():
        got[jid] = list(dict.fromkeys(r[0] for r in rows))
        if write:
            d.mkdir(parents=True, exist_ok=True)
            (d / f'{jid}.json').write_text(json.dumps({'keys': got[jid], 'why': {r[0]: (r[1] if len(r) > 1 else '') for r in rows},
                                                       'at': time.strftime('%Y-%m-%d %H:%M:%S')}, ensure_ascii=False, indent=1))
    return got


def reparse_source(api: wk.Api, jid: str) -> tuple[dict | None, str | None]:
    """Исходник тура: ручка «перечитать» (`/reparse/<id>`: + текст объявления и снятые комнаты); на сервере без неё — перевыпуска."""
    for path in (f'/api/trial/worker/reparse/{jid}', f'/api/trial/worker/reissue/{jid}'):
        st, src = api.call('GET', path, read_max=READ_MAX)
        if st == 200 and isinstance(src, dict) and src.get('ok'):
            return src, None
        why = (src or {}).get('error') if isinstance(src, dict) else None
        if why in SKIP:
            return None, why
    return None, f'http {st}'


def consented(bundle: str) -> list[str]:
    """Снятые агентом комнаты по самой странице (флаг `approx_consent` у комнаты версии) — когда сервер их не отдаёт."""
    b = json.loads(bundle)
    return [x['id'] for p in (b.get('trial') or {}).get('panels') or [] for x in p.get('rooms') or []
            if 'approx_consent' in (x.get('flags') or [])]


def reparse_dry(api: wk.Api, cfg: wk.Cfg, jid: str, run_dir: Path, sheet: list | None, approved: list) -> dict:
    """Пробный прогон одного тура: `conveyor.Reparse` целиком на DEV (лист — локальный, отправка — в файл) → строка отчёта + таблица."""
    import shutil
    import threading
    from types import SimpleNamespace
    import conveyor
    import regress
    src, why = reparse_source(api, jid)
    if src is None:
        return {'id': jid, 'status': 'skipped' if why in SKIP else 'failed', 'why': why}
    if not sheet:
        return {'id': jid, 'status': 'failed', 'why': 'нет листа в --sheets'}
    path = Path(sheet[0]).expanduser()
    mime = regress.MIME.get(path.suffix.lower(), 'image/png')
    text = src['listingText'] if 'listingText' in src else \
        (Path(sheet[1]).expanduser().read_text(encoding='utf-8') if len(sheet) > 1 and sheet[1] not in ('', '-') else '')
    rel = src['released'] if 'released' in src else consented(src['bundle'])
    wd = run_dir / jid
    wd.mkdir(parents=True, exist_ok=True)
    res_p = wd / 'result-old.json'
    res_p.write_text(json.dumps(src['result'], ensure_ascii=False), encoding='utf-8')
    (wd / 'bundle-old.json').write_bytes(src['bundle'].encode('utf-8'))

    class Dry(conveyor.Reparse):
        def source(self):
            inp = self.wd / 'plan' / ('input' + self.ext)
            inp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, inp)
            return inp

        def send(self, tag, data):
            (self.wd / f'bundle-new-{tag}.json').write_bytes(data)
            self.last, self.outcome = json.loads(data), 'published'
            return True

        def judge(self, page):
            # пробный прогон дособирает тур и при находках: вердикт — по `findings` (ниже), а «стало» с мебелью нужно ведущему,
            # чтобы одобрить разницу по ключам; на проде (`conveyor.Reparse.judge`) «изменение» останавливает сборку до мебели
            super().judge(page)
            return None

    w = wk.Worker(cfg, api)
    lease = {'id': f'dry{jid[:19]}', 'attempt': 1, 'leaseToken': 'dry-run-no-lease'}
    cv = Dry(w, lease, wd, SimpleNamespace(lost=threading.Event()), res_p, jid, rel, text, mime, wk.EXT[mime], src['bundle'],
             edits=src.get('edits') or [], opening_edits=src.get('openingEdits') or [], approved=approved)
    t0 = time.time()
    end = cv.rebuild()
    row = {'id': jid, 'from': int(src['version']), 'end': end, 'sec': round(time.time() - t0), 'text_len': len(text), 'released': rel,
           'edits': len(src.get('edits') or []), 'opening_edits': len(src.get('openingEdits') or []), 'detail': cv.detail}
    if cv.pc is None:
        return {**row, 'status': 'failed', 'why': end.split(':', 1)[-1]}
    same = end == 'published' and cv.new_result is None
    v = 'same' if same else regress.verdict(cv.findings, approved)[0] if end in ('published', 'failed:regress') else None
    page = json.loads(cv.cur_bytes) if cv.cur_bytes else None
    if same:
        page = json.loads(src['bundle'])
    row.update(status='built' if v else 'failed', verdict=v, why=None if v else end.split(':', 1)[-1],
               findings=cv.findings, rows=regress.table_rows(src['result'], cv.new_result or src['result'], cv.pc, json.loads(src['bundle']), page),
               map=cv.map)
    return row


def _side(x: dict | None) -> str:
    if not x:
        return '—'
    g = '' if x.get('goods') is None else f", товаров {x['goods']}"
    return f"{x['name'] or x['id']} [{x['kind']}] {x['area']} м², дв {x['doors']}, ок {x['windows']}, {x.get('state') or '—'}{g}"


def reparse_lines(r: dict) -> list[str]:
    """Тур → строки отчёта: вердикт, затем «комната: было → стало» и находки."""
    if r['status'] != 'built':
        return [f"{r['id']}: {'пропущен' if r['status'] == 'skipped' else 'СБОЙ'} — {r.get('why')}" +
                (f"\n    {r['detail']}" if r.get('detail') else '')]
    out = [f"{r['id']} (v{r['from']}, {r['sec']} с, текст {r['text_len']} зн., правок {r['edits']}+{r['opening_edits']}): "
           f"{VERDICT[r['verdict']]}"]
    for x in r['rows']:
        mark = '' if x['now'] and x['was'] else ' ◀'
        out.append(f"    {x['panel']}: {_side(x['was'])} → {_side(x['now'])}{' · ' + x['why'] if x.get('why') else ''}{mark}")
    for f in r['findings']:
        out.append(f"    {'БЛОК' if f['level'] == 'block' else 'изм.'} {f['text']}  [{f['key']}]")
    return out


def reparse_live(api: wk.Api, cfg: wk.Cfg, jid: str, run_dir: Path, wait_s: float = 3600.0) -> dict:
    """Боевой: копия прежнего (откат) → постановка → ждать исход пересборки (`GET /reparse?id=`)."""
    src, why = reparse_source(api, jid)
    if src is None:
        return {'id': jid, 'status': 'skipped' if why in SKIP else 'failed', 'why': why}
    d = run_dir / jid
    d.mkdir(parents=True, exist_ok=True)
    (d / 'before.json').write_text(json.dumps({'version': src['version'], 'result': src['result']}, ensure_ascii=False), encoding='utf-8')
    (d / 'bundle-before.json').write_bytes(src['bundle'].encode('utf-8'))
    st, r = api.call('POST', '/api/trial/worker/reparse', {'jobId': jid, 'requestId': f"reparse-{time.strftime('%Y%m%d%H%M%S')}-{jid[:6]}"})
    if st != 202 or not isinstance(r, dict):
        why = (r or {}).get('error') if isinstance(r, dict) else None
        return {'id': jid, 'status': 'skipped' if why in SKIP else 'failed', 'why': why or f'http {st}'}
    rid, t0 = r['rebuild']['id'], time.time()
    while time.time() - t0 < wait_s:
        time.sleep(15)
        st, s = api.call('GET', f'/api/trial/worker/reparse?id={rid}')
        if st == 200 and isinstance(s, dict) and s.get('status') in ('done', 'failed'):
            return {'id': jid, 'status': 'published' if s['status'] == 'done' else 'failed', 'from': src['version'],
                    'version': s.get('version'), 'why': s.get('error'), 'detail': s.get('detail'), 'rebuild': rid}
    return {'id': jid, 'status': 'failed', 'why': f'не дождался {wait_s:g} с (пересборка {rid} идёт)', 'rebuild': rid}


def missing_banks(env=os.environ) -> list[str]:
    """Банки мебели, без которых пробная сборка отказывает всем комнатам (`refused/no_products`) и сторож даёт ЛОЖНЫЙ блок
    (T-20261111-02/2: из worktree их нет — они вне git). → «переменная=путь» отсутствующих."""
    scout = HERE.parent / 'scout'
    want = (('TRIAL_SETS', 'sets3.json'), ('TRIAL_BEDROOM_SETS', 'sets-bedroom.json'),
            ('BEDROOM_STYLE_SCORES', 'style-scores-bedroom.json'))
    return [f'{k}={p}' for k, n in want for p in [env.get(k) or str(scout / n)] if not Path(p).is_file()]


def reparse_main(a, api: wk.Api, cfg: wk.Cfg, ids: list) -> int:
    if a.dry_run and cfg.furnish and (miss := missing_banks()):
        print('нет банков мебели — пробный прогон дал бы ложные блоки (комнаты без товаров): ' + ', '.join(miss) +
              ' · из worktree укажите файлы основной копии', file=sys.stderr)
        return 2
    run_dir = Path(a.out).expanduser() if a.out else cfg.base / 'reparse' / time.strftime('%Y%m%d-%H%M%S')
    run_dir.mkdir(parents=True, exist_ok=True)
    appr = approvals(cfg, a.approve, write=not a.dry_run)
    if a.dry_run:                                # пробный прогон пишет сцены в свою папку, живые `~/scout-scenes/trial/<id>` не трогает
        import dataclasses
        cfg = dataclasses.replace(cfg, scenes_root=run_dir / 'scenes')
    sheets = read_tsv(a.sheets)
    rows, lines = [], []
    for jid in ids:
        try:
            r = reparse_dry(api, cfg, jid, run_dir, (sheets.get(jid) or [None])[0], appr.get(jid, [])) if a.dry_run else \
                reparse_live(api, cfg, jid, run_dir)
        except wk.NetError as e:
            r = {'id': jid, 'status': 'failed', 'why': str(e)[:300]}
        rows.append(r)
        ls = reparse_lines(r) if a.dry_run else [f"{jid}: {r['status']} {r.get('why') or ''} v{r.get('from')} → v{r.get('version')}"
                                                  + (f"\n    {r['detail']}" if r.get('detail') else '')]
        lines += ls
        print('\n'.join(ls), flush=True)
    (run_dir / 'report.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    tally: dict = {}
    for r in rows:
        k = VERDICT.get(r.get('verdict')) or (f"сбой: {r.get('why')}" if r['status'] == 'failed' else r['status'])
        tally[k] = tally.get(k, 0) + 1
    tail = f"итого туров {len(rows)}: " + ', '.join(f'{k} — {v}' for k, v in tally.items()) + f' · отчёт {run_dir}'
    (run_dir / 'table.txt').write_text('\n'.join(lines + ['', tail]) + '\n', encoding='utf-8')
    print(tail)
    return 0 if all(r.get('verdict') in ('same', 'clean', 'approved') or r['status'] in ('published', 'skipped') for r in rows) else 1


def main(argv=None, api: wk.Api | None = None, cfg: wk.Cfg | None = None, cmd: list | None = None) -> int:
    ap = argparse.ArgumentParser(description='Пересборка готовых туров «как есть» (оператор)')
    ap.add_argument('--job', action='append', default=[], help='id тура (можно несколько раз)')
    ap.add_argument('--days', type=int, help='все готовые туры младше N дней')
    ap.add_argument('--dry-run', action='store_true', help='собрать, не публиковать')
    ap.add_argument('--reparse', action='store_true', help='перечитать планировку (новый разбор листа), а не пересборка «как есть»')
    ap.add_argument('--sheets', help='--reparse --dry-run: TSV «id, лист, [текст объявления|-]»')
    ap.add_argument('--approve', help='--reparse: TSV «id, ключ находки, [почему]» — одобренная ведущим разница')
    ap.add_argument('--out', help='папка прогона (по умолчанию <TRIAL_WORK_DIR>/reparse|reissue/<время>)')
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
    if a.reparse:
        return reparse_main(a, api, cfg, ids)
    run_dir = Path(a.out).expanduser() if a.out else cfg.base / 'reissue' / time.strftime('%Y%m%d-%H%M%S')
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
