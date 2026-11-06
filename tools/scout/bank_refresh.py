#!/usr/bin/env python3
"""ЕДИНСТВЕННЫЙ ПИСАТЕЛЬ ЖИВОГО БАНКА `bank_refresh` (conv-14 шаг 4; разбор Codex 22.10 `_intake/codex/conv-14-bank-auto-2026-10-22-answer.md`
§ 2 «один писатель sets3.json», § 5 тесты).

ЗАЧЕМ. Живой банк `sets3.json` до сих пор правили пять шагов ночи по очереди (`sets_heal`, `sets_pairs`, `sets_contracts`, недельные
`sets_refresh`/`sets_pairs_w`, медиа `catalog_media --apply`) — каждый писал файл сам, без снимка и без отката. Подмена готовых
ячеек (`bank_promote`, шаг 3) только судит и строит смешанный банк; записать его должен ОДИН писатель: атомарно, со снимком
прежнего банка и откатом одной командой.

ПОРЯДОК (за флагом `rules/bank-candidate.json:write_enabled`; при false ночь идёт ровно как раньше — шаг в неё не вызывается):
  1. замок экзамена `exam.lock` — банк под бегущими воркерами не меняем (как прежние писатели);
  1б. незавершённая запись прошлого запуска (`bank-generations/intent.json`) — сперва восстановление (`recover`, ниже);
  2. manifest шага 3 (`~/scout-scenes/bank-promote.json`, env BANK_PROMOTE) и его смешанный банк `hybrid.json`:
     номер ночи `run_id` = `--run-id` (room-bank-01 этап А: чужой — отказ, код 1; без `--run-id` — код 2; строка в дайджест),
     manifest этой ночи (не старше `write_manifest_max_age_h`), без фатальной ошибки; живой банк не менялся после суждения
     (`live_sha`), смешанный — тот самый (`hybrid_sha`); идентичность (`set_identity.verify`: номер массива → ячейка, set_id);
     меняются ТОЛЬКО продвинутые ячейки (у нетронутых — лишь `bank_status`), их состав = судимый кандидат (`candidate_hash`);
     откаченная вручную ячейка с тем же кандидатом (`hold.json`) — отказ. Любое нарушение — ничего не пишем, код 1 (FAIL);
  3. медиа из каталога (`catalog_media.sync_sets`) — к рабочей копии, не к файлу: при включённом писателе ночной
     `bank_media` идёт сухим прогоном, а фото, ссылки и габариты в живой банк кладёт этот шаг;
  4. совпало с живым — запись не нужна (no-op: без снимка и без записи);
  5. снимок прежнего банка — поколение `bank-generations/sets3-<поколение>.json.gz` (байт в байт, атомарно) — затем
     НАМЕРЕНИЕ `bank-generations/intent.json` (поколение, снимок, sha живого до и sha, который будет после, готовая запись
     журнала; атомарно + fsync) — затем `set_identity.write_bank` (временный файл + fsync + rename): сбой до rename оставляет
     банк целым; после записи — проверка идентичности, расхождение — возврат снимка; журнал; намерение снимается последним;
  6. журнал `bank-generations/journal.jsonl` и строки дайджеста `DIGEST:` (ночной дайджест их собирает): снято / добавлено /
     ждёт меш / скрыто и с пробелом (`bank_status` из manifest — тем же писателем).
ВОССТАНОВЛЕНИЕ (`recover`, в начале записи и отката; вручную — `recover`): намерение есть →
  поколение уже в журнале — только снять намерение; живой = «до» — запись не случилась: в журнал `recover/abort`;
  живой = «после» — проверка идентичности против снимка: сошлась — доводка (запись журнала с `recovered`, запрет отката —
  как задумано), не сошлась — возврат снимка (`recover/restore`); живой — ни то ни другое (его менял кто-то ещё) — отказ, код 1,
  намерение остаётся, банк не трогаем: разбор руками, затем `recover --abandon` (намерение → журнал `recover/abandon`).
  Каждый исход — строка `DIGEST:`.
ОТКАТ `rollback <поколение|last>`: банк до записи этого поколения (и всех позже) — байт в байт из снимка, атомарно, только при той
же карте «номер → ячейка, set_id»; текущий банк сперва сам становится поколением (откат обратим); ячейки откаченных записей —
в `hold.json`: тот же кандидат не продвигается (`bank_promote`), новый кандидат ячейки снимает запрет сам.

  ~/venvs/scout/bin/python bank_refresh.py --run-id <номер>    # ночной шаг (флаг write_enabled; номер — из refresh_daily.sh)
  ~/venvs/scout/bin/python bank_refresh.py --run-id <номер> --force   # ручная запись при выключенном флаге
  ~/venvs/scout/bin/python bank_refresh.py recover [--abandon] # довести/откатить прерванную запись (намерение)
  ~/venvs/scout/bin/python bank_refresh.py list                # поколения
  ~/venvs/scout/bin/python bank_refresh.py rollback <поколение|last> [--force]   # --force — при exam.lock
  ~/venvs/scout/bin/python bank_refresh.py release [<ячейка>|all]                # снять запрет отката
  ~/venvs/scout/bin/python bank_refresh.py --enabled           # 1/0 — для refresh_daily.sh (ошибка чтения — 0)
  env BANK_PROMOTE (manifest), BANK_GENERATIONS (папка поколений)
  python3 bank_refresh.py --selftest
"""
import copy
import datetime
import gzip
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bank_run as RUN  # noqa: E402
import set_identity as SID  # noqa: E402
import room_bank_spec as RBS  # noqa: E402

# пути и флаг писателя — из спецификации комнаты (room-bank-01 этап Б); без `--room` — гостиная, ровно прежнее
SPEC = RBS.for_room(None)
RULES_PATH = SPEC.rules_path


def paths() -> dict:
    """Пути писателя комнаты; env — в момент вызова, как раньше. У гостиной — прежние 7 ключей, у другой комнаты ещё
    `room` и `snap` (`RoomBankSpec.refresh_paths`)."""
    return RBS.for_room(SPEC.room).refresh_paths()


def rules() -> dict:
    return SPEC.view(json.load(open(RULES_PATH, encoding='utf-8')))


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _strip(s: dict) -> dict:
    return {k: v for k, v in s.items() if k != 'bank_status'}


def _sku(it) -> str | None:
    return f"{it.get('mid')}:{it.get('eid')}" if isinstance(it, dict) and it.get('eid') else None


def _cand_hash(s: dict) -> str:
    import bank_pending as BP
    return BP.candidate_hash(s)


def _atomic(path: str, data: bytes) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def journal(P: dict) -> list[dict]:
    try:
        return [json.loads(x) for x in open(P['journal'], encoding='utf-8') if x.strip()]
    except FileNotFoundError:
        return []


def _journal_add(P: dict, rec: dict) -> None:
    with open(P['journal'], 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def _hold(P: dict) -> dict:
    try:
        return json.load(open(P['hold'], encoding='utf-8')).get('cells') or {}
    except FileNotFoundError:
        return {}


def _hold_save(P: dict, cells: dict) -> None:
    _atomic(P['hold'], json.dumps({'cells': cells}, ensure_ascii=False, indent=1).encode())


def snapshot(P: dict, raw: bytes) -> tuple[str, str]:
    """Поколение = снимок банка ДО записи, байт в байт (gzip: банк 2,2 МБ → ~0,2 МБ — хранить без чистки)."""
    os.makedirs(P['gen'], exist_ok=True)
    pre = P.get('snap', 'sets3')               # префикс снимка комнаты; у гостиной — прежний `sets3`
    base = time.strftime('%Y%m%d-%H%M%S')
    gen, i = base, 1
    while os.path.exists(os.path.join(P['gen'], f'{pre}-{gen}.json.gz')):
        i += 1
        gen = f'{base}-{i}'
    path = os.path.join(P['gen'], f'{pre}-{gen}.json.gz')
    _atomic(path, gzip.compress(raw, mtime=0))
    return gen, path


def _intent_save(P: dict, it: dict) -> None:
    """Намерение ДО замены живого файла: при сбое между rename и журналом следующий запуск знает, что и куда менялось."""
    os.makedirs(P['gen'], exist_ok=True)
    _atomic(P['intent'], json.dumps(it, ensure_ascii=False, indent=1).encode())


def _intent_load(P: dict) -> dict | None:
    try:
        return json.load(open(P['intent'], encoding='utf-8'))
    except FileNotFoundError:
        return None


def _intent_clear(P: dict, to: str | None = None) -> None:
    """Снять намерение: переименованием в журнальную папку (след остаётся, файл намерения освобождается)."""
    if os.path.exists(P['intent']):
        os.replace(P['intent'], to or P['intent'] + '.done')


def recover(P: dict, abandon: bool = False) -> int:
    """Незавершённая запись/откат прошлого запуска → снять, довести или вернуть снимок по sha. 0 — можно работать дальше."""
    it = _intent_load(P)
    if not it:
        if abandon:
            print('bank_refresh: незавершённой записи нет', flush=True)
        return 0
    if it['record']['kind'] in ('bootstrap', 'unbootstrap'):     # поколение 0 комнаты (`room_bootstrap`, T-20261106-70)
        import room_bootstrap as RBO
        return RBO.recover_intent(P, it, abandon)
    gen, rec, now = it['gen'], it['record'], time.strftime('%Y-%m-%dT%H:%M:%S')
    if any(r.get('gen') == gen and r.get('kind') == rec['kind'] for r in journal(P)):
        if it.get('hold') is not None:         # сбой между журналом и запретом отката — запрет дописать (идемпотентно)
            _hold_save(P, it['hold'])
        _intent_clear(P)
        print(f'bank_refresh: намерение {gen} уже в журнале — снято', flush=True)
        return 0
    raw = open(P['live'], 'rb').read()
    cur = sha(raw)
    base = {'gen': f'{gen}-recover', 'kind': 'recover', 'at': now, 'of': gen, 'of_kind': rec['kind'], 'live_sha': cur,
            'run_id': it.get('run_id')}
    if cur == it['live_sha_before']:
        _journal_add(P, {**base, 'action': 'abort'})
        _intent_clear(P)
        print(f'bank_refresh: прерванная запись {gen} не дошла до замены — банк прежний, намерение снято', flush=True)
        print(f'DIGEST:банк: прерванная запись {gen} не дошла до замены — банк прежний', flush=True)
        return 0
    if cur == it['live_sha_after']:
        snap = gzip.decompress(open(it['snapshot'], 'rb').read())
        bad = (['снимок повреждён'] if sha(snap) != it['live_sha_before']
               else SID.verify(json.loads(raw), json.loads(snap), cells=len(json.loads(snap))))
        if not bad:
            if it.get('hold') is not None:
                _hold_save(P, it['hold'])
            _journal_add(P, {**rec, 'recovered': now})
            _intent_clear(P)
            print(f'bank_refresh: прерванная запись {gen} доведена — банк уже новый, журнал дописан', flush=True)
            print(f'DIGEST:банк: прерванная запись {gen} доведена после сбоя (журнал дописан)', flush=True)
            return 0
        if sha(snap) == it['live_sha_before']:
            _atomic(P['live'], snap)
            _journal_add(P, {**base, 'action': 'restore', 'why': '; '.join(bad)})
            _intent_clear(P)
            print(f"ERROR:bank_refresh: прерванная запись {gen}: идентичность не сошлась ({'; '.join(bad)}) — возвращён снимок",
                  flush=True)
            print(f'DIGEST:банк: прерванная запись {gen} отменена — возвращён снимок', flush=True)
            return 1
    if abandon:
        _journal_add(P, {**base, 'action': 'abandon'})
        _intent_clear(P, os.path.join(P['gen'], f'intent-{gen}-abandoned.json'))
        print(f'bank_refresh: намерение {gen} снято вручную (живой банк оставлен как есть)', flush=True)
        return 0
    print(f"ERROR:bank_refresh: незавершённая запись {gen}: живой банк не равен ни «до», ни «после» (менял кто-то ещё) — "
          f"не трогаю; разбор руками, затем `bank_refresh.py recover --abandon` ({P['intent']})", flush=True)
    print(f'DIGEST:банк: писатель стоит — незавершённая запись {gen} и чужая правка живого банка, нужен разбор', flush=True)
    return 1


def summary(live: list, out: list, promoted: list, rows: dict) -> dict:
    """Снято / добавлено по позициям продвинутых ячеек, ожидание мешей, статусы нетронутых — для журнала и дайджеста."""
    removed, added = [], []
    for n in promoted:
        a = {r: _sku(it) for r, it in (live[n - 1].get('items') or {}).items() if _sku(it)}
        b = {r: _sku(it) for r, it in (out[n - 1].get('items') or {}).items() if _sku(it)}
        removed += [(n, r, s) for r, s in a.items() if b.get(r) != s]
        added += [(n, r, s) for r, s in b.items() if a.get(r) != s]
    wait = [r for r in rows.values() if r.get('decision') == 'wait']
    mesh = [r for r in wait if (r.get('mesh_missing') or 0) > 0]
    states: dict = {}
    for s in out:
        st = (s.get('bank_status') or {}).get('state')
        if st:
            states[st] = states.get(st, 0) + 1
    return {'promoted': list(promoted), 'removed': len(removed), 'added': len(added),
            'removed_roles': sorted({r for _, r, _ in removed}), 'wait_mesh_cells': len(mesh),
            'wait_mesh': sum(r.get('mesh_missing') or 0 for r in mesh), 'wait_other': len(wait) - len(mesh),
            'blocked': sum(1 for r in rows.values() if r.get('decision') == 'blocked'),
            'deferred': sum(1 for r in rows.values() if r.get('decision') == 'deferred'), 'states': states}


def digest_lines(d: dict, gen: str | None) -> list[str]:
    head = (f"DIGEST:банк (поколение {gen}): подменено ячеек {len(d['promoted'])} {d['promoted'][:12]}; снято товаров "
            f"{d['removed']}, добавлено {d['added']}" + (f" ({', '.join(d['removed_roles'][:6])})" if d['removed_roles'] else '')
            if gen else "DIGEST:банк: без изменений (подменено 0)")
    tail = (f"DIGEST:банк: ждёт меш ячеек {d['wait_mesh_cells']} (мешей недостаёт {d['wait_mesh']}), ждёт прочего "
            f"{d['wait_other']}, заблокировано {d['blocked']}, до следующей ночи {d['deferred']}; скрыто "
            f"{d['states'].get('hidden', 0)}, с пробелом {d['states'].get('degraded', 0)}")
    return [head, tail]


def _fail(msg: str) -> int:
    print(f'ERROR:bank_refresh: {msg} — банк не тронут', flush=True)
    return 1


def _skip(msg: str) -> int:
    print(f'WARN:bank_refresh: {msg} — банк не тронут', flush=True)
    return 0


def write(P: dict, R: dict, *, force: bool = False, media_fn=None, now: float | None = None, run_id: str | None = None) -> int:
    if not (R.get('write_enabled') or force):
        print(f'bank_refresh: выключено (rules/bank-candidate.json:{SPEC.flag_ref("write_enabled")}=false) — живой банк пишут прежние '
              'шаги', flush=True)
        return 0
    if os.path.exists(P['lock']):
        print('bank_refresh: exam.lock — идёт экзамен, запись отложена до следующей ночи', flush=True)
        print('DIGEST:банк: запись отложена — идёт экзамен (exam.lock)', flush=True)
        return 0
    if recover(P):
        return 1
    if not run_id:
        return RUN.refuse('bank_refresh', 'нужен --run-id (номер ночи manifest bank_promote) — банк не тронут', 2)
    try:
        man = json.load(open(P['manifest'], encoding='utf-8'))
    except FileNotFoundError:
        return RUN.refuse('bank_refresh', f"manifest {P['manifest']} нет (bank_promote этой ночи не судил) — банк не тронут")
    if man.get('room', RBS.LIVING) != P.get('room', RBS.LIVING):     # manifest гостиной поля `room` не несёт
        return RUN.refuse('bank_refresh', f"manifest комнаты {man.get('room', RBS.LIVING)}, а писатель — "
                          f"{P.get('room', RBS.LIVING)} — банк не тронут")
    if man.get('run_id') != run_id:
        return RUN.refuse('bank_refresh', f"manifest не этой ночи (run_id {man.get('run_id')} ≠ {run_id}) — банк не тронут")
    raw = open(P['live'], 'rb').read()
    live, lsha = json.loads(raw), sha(raw)
    rows = {r['n']: r for r in man.get('cells') or []}
    promoted = sorted(man.get('promoted') or [])
    J = [r for r in journal(P) if r.get('kind') == 'write']
    if J and J[-1].get('manifest_at') == man.get('at') and J[-1].get('hybrid_sha') == man.get('hybrid_sha') \
            and J[-1].get('live_sha_after') == lsha:
        print(f"bank_refresh: этот manifest уже записан (поколение {J[-1]['gen']}) — без изменений", flush=True)
        return 0
    if man.get('fatal'):
        return _skip(f"manifest с фатальной ошибкой: {man['fatal']}")
    if not man.get('hybrid'):
        return _skip('в manifest нет смешанного банка')
    age_h = ((time.time() if now is None else now)
             - datetime.datetime.strptime(man['at'], '%Y-%m-%dT%H:%M:%S').timestamp()) / 3600
    if age_h > float(R.get('write_manifest_max_age_h') or 12):
        return RUN.refuse('bank_refresh', f"manifest от {man['at']} — старше {R.get('write_manifest_max_age_h') or 12} ч "
                          "(суждения этой ночи нет) — банк не тронут")
    if man.get('live_sha') != lsha:
        return _fail('живой банк менялся после суждения bank_promote (live_sha другой)')
    try:
        hraw = open(man['hybrid'], 'rb').read()
    except FileNotFoundError:
        return _fail(f"смешанного банка {man['hybrid']} нет")
    if sha(hraw) != man.get('hybrid_sha'):
        return _fail('смешанный банк не тот, что судили (hybrid_sha другой)')
    hybrid = json.loads(hraw)
    ident = SID.verify(hybrid, live, cells=len(live))
    if ident:
        return _fail('идентичность смешанного против живого: ' + '; '.join(ident))
    worse = [n for n in range(1, len(live) + 1) if n not in promoted and _strip(hybrid[n - 1]) != _strip(live[n - 1])]
    if worse:
        return _fail(f'изменились не продвинутые ячейки: {worse[:5]}')
    drift = [n for n in promoted if n not in rows or _cand_hash(hybrid[n - 1]) != rows[n].get('candidate_hash')]
    if drift:
        return _fail(f'состав продвинутых не равен судимому кандидату: {drift[:5]}')
    hold = _hold(P)
    held = [n for n in promoted if (hold.get(rows[n]['cell']) or {}).get('candidate_hash') == rows[n]['candidate_hash']]
    if held:
        return _fail(f'продвигаются откаченные вручную ячейки {held[:5]} (hold.json)')
    out = copy.deepcopy(hybrid)
    mstat = media_fn(out) if media_fn else None
    d = summary(live, out, promoted, rows)
    if mstat:
        print('медиа из каталога: ' + ', '.join(f'{k} {v}' for k, v in mstat.items() if v), flush=True)
    if out == live:
        print('bank_refresh: смешанный банк совпадает с живым — запись не нужна', flush=True)
        for x in digest_lines(d, None):
            print(x, flush=True)
        return 0
    try:                                       # байты, которые запишет write_bank (тот же dump) — sha «после» для намерения
        target = json.dumps(SID.assign_ids(copy.deepcopy(out), live), ensure_ascii=False, indent=1).encode('utf-8')
    except SID.IdentityError as e:
        return _fail(f'идентичность записи: {e}')
    # запрет отката снимается сам, когда у ячейки новый кандидат
    keep = {k: v for k, v in hold.items()
            if not any(r['cell'] == k and r['candidate_hash'] != v['candidate_hash'] for r in rows.values())}
    gen, spath = snapshot(P, raw)
    rec = {'gen': gen, 'kind': 'write', 'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'snapshot': spath, 'run_id': run_id,
           'live_sha_before': lsha, 'live_sha_after': sha(target), 'manifest_at': man.get('at'),
           'hybrid_sha': man.get('hybrid_sha'), 'media': mstat,
           'promoted_cells': [{'n': n, 'cell': rows[n]['cell'], 'candidate_hash': rows[n]['candidate_hash']}
                              for n in promoted], **{k: v for k, v in d.items() if k != 'promoted'}}
    _intent_save(P, {'gen': gen, 'run_id': run_id, 'snapshot': spath, 'live_sha_before': lsha, 'live_sha_after': sha(target),
                     'hold': keep if keep != hold else None, 'record': rec})
    try:
        SID.write_bank(out, P['live'], P['live'])
    except Exception as e:                     # noqa: BLE001 — любой сбой до rename: банк прежний (атомарная запись)
        _intent_clear(P)
        return _fail(f'запись не удалась ({type(e).__name__}: {e}); снимок {spath}')
    nraw = open(P['live'], 'rb').read()
    new = json.loads(nraw)
    left = SID.verify(new, live, cells=len(live))
    if left or new != out or sha(nraw) != sha(target):
        _atomic(P['live'], raw)
        _intent_clear(P)
        return _fail('после записи идентичность не сошлась (' + ('; '.join(left) or 'содержимое') + ') — возвращён снимок')
    _journal_add(P, rec)
    if keep != hold:
        _hold_save(P, keep)
    _intent_clear(P)
    print(f'bank_refresh: записано поколение {gen} — подменено {len(promoted)}, снимок прежнего {spath}', flush=True)
    for x in digest_lines(d, gen):
        print(x, flush=True)
    return 0


def rollback(P: dict, gen: str, force: bool = False) -> int:
    if os.path.exists(P['lock']) and not force:
        print('ERROR:bank_refresh: exam.lock — идёт экзамен; откат с --force', flush=True)
        return 1
    if recover(P):                             # прерванная запись — сперва довести/вернуть, иначе «last» не тот
        return 1
    J = journal(P)
    writes = [i for i, r in enumerate(J) if r.get('kind') == 'write']
    if not writes:
        print('ERROR:bank_refresh: поколений записи нет — откатывать некуда', flush=True)
        return 1
    idx = writes[-1] if gen == 'last' else next((i for i in writes if J[i]['gen'] == gen), None)
    if idx is None:
        print(f'ERROR:bank_refresh: поколения {gen} нет (список — bank_refresh.py list)', flush=True)
        return 1
    rec = J[idx]
    snap = gzip.decompress(open(rec['snapshot'], 'rb').read())
    if sha(snap) != rec['live_sha_before']:
        return _fail(f"снимок {rec['snapshot']} повреждён (sha не тот)")
    raw = open(P['live'], 'rb').read()
    old, live = json.loads(snap), json.loads(raw)
    ident = SID.verify(old, live, cells=len(live))
    if ident:
        return _fail('карта «номер → ячейка, set_id» снимка не совпала с живой: ' + '; '.join(ident))
    if raw == snap:
        print(f"bank_refresh: живой банк уже равен снимку {rec['gen']} — без изменений", flush=True)
        return 0
    undone = [J[i] for i in writes if i >= idx]
    hold = _hold(P)
    for r in undone:
        for c in r.get('promoted_cells') or []:
            hold[c['cell']] = {'candidate_hash': c['candidate_hash'], 'gen': r['gen'], 'at': time.strftime('%Y-%m-%dT%H:%M:%S')}
    here, spath = snapshot(P, raw)
    jrec = {'gen': here, 'kind': 'rollback', 'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'snapshot': spath,
            'to': rec['gen'], 'undone': [r['gen'] for r in undone], 'live_sha_before': sha(raw),
            'live_sha_after': rec['live_sha_before']}
    _intent_save(P, {'gen': here, 'snapshot': spath, 'live_sha_before': sha(raw), 'live_sha_after': rec['live_sha_before'],
                     'hold': hold, 'record': jrec})
    _atomic(P['live'], snap)
    if sha(open(P['live'], 'rb').read()) != rec['live_sha_before']:
        _atomic(P['live'], raw)
        _intent_clear(P)
        return _fail('после отката банк не равен снимку — возвращён прежний')
    _hold_save(P, hold)
    _journal_add(P, jrec)
    _intent_clear(P)
    cells = sorted({c['cell'] for r in undone for c in r.get('promoted_cells') or []})
    print(f"bank_refresh: откат к банку до поколения {rec['gen']} (отменено записей {len(undone)}); текущий сохранён как "
          f"{here}; запрет продвижения того же кандидата: {len(cells)} ячеек", flush=True)
    print(f"DIGEST:банк: откат к банку до {rec['gen']} — вернулось ячеек {len(cells)}", flush=True)
    return 0


def release(P: dict, what: str) -> int:
    hold = _hold(P)
    keep = {} if what == 'all' else {k: v for k, v in hold.items() if k != what}
    _hold_save(P, keep)
    print(f'bank_refresh: запрет отката снят у {len(hold) - len(keep)} ячеек, осталось {len(keep)}', flush=True)
    return 0


def list_gens(P: dict) -> int:
    for r in journal(P):
        if r['kind'] == 'recover':
            print(f"{r['gen']}  recover   {r['at']}  {r.get('action')} — запись {r.get('of')} ({r.get('of_kind')})")
            continue
        if r['kind'] in ('bootstrap', 'unbootstrap'):        # поколение 0 комнаты (`room_bootstrap`)
            print(f"{r['gen']}  {r['kind']:8}  {r['at']}  " + (f"поколение 0, ячеек {r.get('cells')}" if r['kind'] == 'bootstrap'
                  else f"снято поколение 0 {r.get('undone')}") + f"  {r['snapshot']}")
            continue
        print(f"{r['gen']}  {r['kind']:8}  {r['at']}  " + (f"подменено {len(r.get('promoted_cells') or [])}, снято "
              f"{r.get('removed')}, добавлено {r.get('added')}" + (' (доведена после сбоя)' if r.get('recovered') else '')
              if r['kind'] == 'write' else f"к банку до {r.get('to')}") + f"  {r['snapshot']}")
    it = _intent_load(P)
    if it:
        print(f"НЕЗАВЕРШЁННАЯ запись {it['gen']} ({it['record']['kind']}) — `bank_refresh.py recover`")
    return 0


def _enabled() -> int:
    try:
        print('1' if rules().get('write_enabled') is True else '0')
    except Exception:                          # noqa: BLE001 — не прочли правила: ночь как прежде
        print('0')
    return 0


def _selftest() -> int:
    import tempfile
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    tmp = tempfile.TemporaryDirectory(prefix='bank-refresh-')
    td = tmp.name
    P = {'live': os.path.join(td, 'sets3.json'), 'lock': os.path.join(td, 'exam.lock'),
         'manifest': os.path.join(td, 'promote.json'), 'gen': os.path.join(td, 'gens'),
         'journal': os.path.join(td, 'gens', 'journal.jsonl'), 'hold': os.path.join(td, 'gens', 'hold.json'),
         'intent': os.path.join(td, 'gens', 'intent.json')}
    R = {'write_enabled': True, 'write_manifest_max_age_h': 12}
    styles = ('сканди', 'лофт', 'джапанди')
    live = [{'band': b, 'style': st, 'tier': 'эконом', 'm2': 15, 'set_id': f'id{i}', 'capsule': 'c', 'group': 'g',
             'items': {'диван': {'mid': 1, 'eid': f'd{i}', 'price': 100}, 'столик': {'mid': 1, 'eid': f't{i}', 'price': 10}}}
            for i, (b, st) in enumerate(((b, st) for b in ('14-16', '17-20') for st in styles), 1)]
    with open(P['live'], 'w', encoding='utf-8') as f:     # формат живого — как у прежних писателей (без отступов)
        json.dump(live, f, ensure_ascii=False)
    orig = open(P['live'], 'rb').read()

    def manifest(promote_ns, *, base=None, status=None, mut=None, at=None, fatal=None, run_id='N1'):
        base = base if base is not None else json.load(open(P['live'], encoding='utf-8'))
        h = copy.deepcopy(base)
        for s in h:
            s.pop('bank_status', None)
        for n in promote_ns:
            h[n - 1]['items']['диван'] = {'mid': 1, 'eid': f'D{n}', 'price': 120}
        for n, st in (status or {}).items():
            h[n - 1]['bank_status'] = {'state': st}
        if mut:
            mut(h)
        hp = os.path.join(td, 'hybrid.json')
        with open(hp, 'w', encoding='utf-8') as f:
            json.dump(h, f, ensure_ascii=False, indent=1)
        rows = [{'n': n, 'cell': '|'.join(SID.cell(s)), 'candidate_hash': _cand_hash(s),
                 'decision': 'promote' if n in promote_ns else 'wait', 'mesh_missing': 0 if n in promote_ns else n % 2}
                for n, s in enumerate(h, 1)]
        man = {'at': at or time.strftime('%Y-%m-%dT%H:%M:%S'), 'live_sha': sha(open(P['live'], 'rb').read()),
               'hybrid': hp, 'hybrid_sha': sha(open(hp, 'rb').read()), 'promoted': list(promote_ns), 'fatal': fatal, 'run_id': run_id,
               'cells': rows}
        json.dump(man, open(P['manifest'], 'w', encoding='utf-8'), ensure_ascii=False)
        return h

    def cur():
        return open(P['live'], 'rb').read()

    def ids():
        return [(SID.cell(s), s['set_id']) for s in json.loads(cur())]
    ids0 = ids()
    R_off = {'write_enabled': False}
    manifest([2], status={5: 'degraded'})
    ok('флаг выключен — банк не тронут', write(P, R_off) == 0 and cur() == orig)
    open(P['lock'], 'w').close()
    ok('exam.lock — запись отложена, банк не тронут', write(P, R, run_id='N1') == 0 and cur() == orig)
    os.replace(P['lock'], P['lock'] + '.off')
    class _CrashOS:                            # os писателя `set_identity.write_bank`: rename падает (сбой диска/процесса)
        def __getattr__(self, k):
            return getattr(os, k)

        @staticmethod
        def replace(a, b):
            raise OSError('сбой до rename')
    SID.os = _CrashOS()
    try:
        rc = write(P, R, run_id='N1')
    finally:
        SID.os = os
    ok('сбой до rename — код 1, банк байт в байт прежний, журнал пуст, намерение снято', rc == 1 and cur() == orig
       and journal(P) == [] and not os.path.exists(P['intent']))
    h = manifest([2], status={5: 'degraded'})
    rc = write(P, R, run_id='N1')
    J = journal(P)
    ok('запись: живой = смешанный банк (ячейка 2 из кандидата, статус ячейки 5 — тем же писателем)',
       rc == 0 and json.loads(cur()) == h and json.loads(cur())[4]['bank_status'] == {'state': 'degraded'})
    ok('неизменность номеров и set_id после записи', ids() == ids0)
    ok('снимок прежнего банка — байт в байт, поколение в журнале',
       len(J) == 1 and gzip.decompress(open(J[0]['snapshot'], 'rb').read()) == orig and J[0]['removed'] == 1
       and J[0]['added'] == 1, J)
    after1 = cur()
    ok('повторный запуск с тем же manifest — no-op (без записи и снимка)', write(P, R, run_id='N1') == 0 and cur() == after1
       and len(journal(P)) == 1)
    manifest([], status={5: 'degraded'})
    n_snap = len(os.listdir(P['gen']))
    ok('новое суждение без изменений — no-op (без снимка)', write(P, R, run_id='N1') == 0 and cur() == after1
       and len(os.listdir(P['gen'])) == n_snap and len(journal(P)) == 1)
    manifest([3])
    json.dump(json.loads(cur()), open(P['live'], 'w', encoding='utf-8'), ensure_ascii=False, indent=2)  # кто-то переписал
    changed = cur()
    ok('живой менялся после суждения — отказ (FAIL), банк не тронут', write(P, R, run_id='N1') == 1 and cur() == changed)
    _atomic(P['live'], after1)
    manifest([3], mut=lambda h: h[0]['items'].update({'столик': {'mid': 1, 'eid': 'X', 'price': 1}}))
    ok('смешанный меняет не продвинутую ячейку — отказ', write(P, R, run_id='N1') == 1 and cur() == after1)
    manifest([3], mut=lambda h: h.__setitem__(slice(0, 2), [h[1], h[0]]))
    ok('смешанный с переставленными номерами — отказ', write(P, R, run_id='N1') == 1 and cur() == after1)
    manifest([3], fatal='идентичность')
    ok('manifest с фатальной ошибкой — WARN, банк не тронут', write(P, R, run_id='N1') == 0 and cur() == after1)
    manifest([3], at='2026-01-01T00:00:00')
    ok('manifest старше предела — отказ (код 1), банк не тронут', write(P, R, run_id='N1') == 1 and cur() == after1)
    manifest([3])
    hp = json.load(open(P['manifest'], encoding='utf-8'))['hybrid']
    with open(hp, 'a', encoding='utf-8') as f:
        f.write(' ')
    ok('смешанный банк подменён после суждения (hybrid_sha) — отказ', write(P, R, run_id='N1') == 1 and cur() == after1)
    manifest([3])

    def media(sets):
        sets[0]['items']['диван']['img'] = 'new.jpg'
        return {'fixed_img': 1}
    ok('медиа из каталога — к рабочей копии, в банк тем же писателем', write(P, R, media_fn=media, run_id='N1') == 0
       and json.loads(cur())[0]['items']['диван']['img'] == 'new.jpg' and json.loads(cur())[2]['items']['диван']['eid'] == 'D3'
       and ids() == ids0 and len(journal(P)) == 2)
    after2 = cur()
    ok('откат последнего поколения — банк байт в байт как до него', rollback(P, 'last') == 0 and cur() == after1
       and ids() == ids0)
    hold = _hold(P)
    ok('откат: под запретом ровно ячейка 3 (её кандидат), журнал — запись rollback',
       {k: v['candidate_hash'] for k, v in hold.items()} == {'|'.join(SID.cell(json.loads(after2)[2])):
                                                             _cand_hash(json.loads(after2)[2])}
       and journal(P)[-1]['kind'] == 'rollback', hold)
    manifest([3])
    ok('тот же кандидат откаченной ячейки — писатель отказывает', write(P, R, run_id='N1') == 1 and cur() == after1)
    ok('откат обратим: текущий перед откатом сохранён поколением',
       gzip.decompress(open(journal(P)[-1]['snapshot'], 'rb').read()) == after2)
    ok('откат к первому поколению — банк как в самом начале', rollback(P, journal(P)[0]['gen']) == 0 and cur() == orig)
    bad_snap = copy.deepcopy(json.loads(orig))
    bad_snap[0]['set_id'], bad_snap[1]['set_id'] = bad_snap[1]['set_id'], bad_snap[0]['set_id']
    raw_bad = json.dumps(bad_snap, ensure_ascii=False).encode()
    gp = os.path.join(P['gen'], 'sets3-bad.json.gz')
    _atomic(gp, gzip.compress(raw_bad, mtime=0))
    _journal_add(P, {'gen': 'bad', 'kind': 'write', 'at': '', 'snapshot': gp, 'live_sha_before': sha(raw_bad),
                     'live_sha_after': sha(cur()), 'promoted_cells': []})
    before = cur()
    ok('откат к снимку с другой картой номеров — отказ, банк не тронут', rollback(P, 'bad') == 1 and cur() == before)
    ok('снять запрет — release all', release(P, 'all') == 0 and _hold(P) == {})
    d = summary(live, live, [], {1: {'decision': 'wait', 'mesh_missing': 3}, 2: {'decision': 'wait', 'mesh_missing': 0},
                                 3: {'decision': 'blocked'}})
    lines = digest_lines(d, None)
    ok('дайджест: ждёт меш / прочего / заблокировано — строками DIGEST:', all(x.startswith('DIGEST:') for x in lines)
       and 'ждёт меш ячеек 1 (мешей недостаёт 3), ждёт прочего 1, заблокировано 1' in lines[1], lines)
    _selftest_chain(P, R, manifest, cur, ok)         # ошибки считает тот же ok
    tmp.cleanup()
    print(f'bank_refresh selftest: ошибок {bad}')
    return 1 if bad else 0


class _Die(BaseException):
    """Смерть процесса в окне записи (не Exception: писатель её не ловит — как kill/обрыв питания)."""


def _selftest_chain(P, R, manifest, cur, ok) -> None:
    """Номер ночи и восстановление после падения в каждом окне записи (room-bank-01 этап А)."""
    import contextlib
    import io
    real_wb, g = SID.write_bank, globals()

    def run_q(fn, *a, **k):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                rc = fn(*a, **k)
            except _Die:
                rc = 'die'
        return rc, buf.getvalue()

    def once(name, before=False):
        """Подменить функцию модуля: первый вызов умирает (до вызова настоящей или после)."""
        real = g[name] if name in g else None
        state = {'n': 0}

        def f(*a, **k):
            state['n'] += 1
            if state['n'] == 1 and before:
                raise _Die(name)
            r = (real or real_wb)(*a, **k)
            if state['n'] == 1:
                raise _Die(name)
            return r
        return real, f
    base = cur()
    manifest([4], run_id='N1')
    rc, txt = run_q(write, P, R, run_id='N2')
    ok('чужой run_id manifest — отказ (код 1) строкой ERROR и DIGEST, банк не тронут',
       rc == 1 and cur() == base and 'manifest не этой ночи' in txt and 'DIGEST:банк: bank_refresh отказал' in txt, txt)
    rc, txt = run_q(write, P, R)
    ok('без --run-id — отказ (код 2), банк не тронут', rc == 2 and cur() == base and '--run-id' in txt, txt)
    mp = P['manifest']
    P['manifest'] = mp + '.нет'
    rc, txt = run_q(write, P, R, run_id='N1')
    P['manifest'] = mp
    ok('manifest нет — отказ (код 1), банк не тронут', rc == 1 and cur() == base, txt)
    manifest([4], at='2026-01-01T00:00:00', run_id='N1')
    rc, txt = run_q(write, P, R, run_id='N1')
    ok('устаревший manifest своей ночи (старше предела) — отказ строкой в дайджест, не пишем', rc == 1 and cur() == base
       and 'старше' in txt and 'DIGEST:банк: bank_refresh отказал' in txt, txt)

    # окно 1: снимок есть, намерения ещё нет
    manifest([4])
    J0 = len(journal(P))
    real, g['_intent_save'] = (g['_intent_save'], lambda *a: (_ for _ in ()).throw(_Die('intent')))
    rc, _ = run_q(write, P, R, run_id='N1')
    g['_intent_save'] = real
    ok('падение после снимка до намерения — банк прежний, журнал и намерение пусты', rc == 'die' and cur() == base
       and len(journal(P)) == J0 and not os.path.exists(P['intent']))
    rc, txt = run_q(write, P, R, run_id='N1')
    w1 = cur()
    ok('…следующий запуск пишет как обычно', rc == 0 and w1 != base and journal(P)[-1]['kind'] == 'write'
       and journal(P)[-1]['run_id'] == 'N1' and journal(P)[-1]['live_sha_after'] == sha(w1), txt)

    # окно 2: намерение записано, rename не случился
    manifest([5])
    J0 = len(journal(P))
    SID.write_bank = lambda *a, **k: (_ for _ in ()).throw(_Die('до rename'))
    rc, _ = run_q(write, P, R, run_id='N1')
    SID.write_bank = real_wb
    it = _intent_load(P)
    ok('падение после намерения до rename — банк прежний, намерение лежит', rc == 'die' and cur() == w1 and it
       and it['live_sha_before'] == sha(w1) and len(journal(P)) == J0)
    rc, txt = run_q(write, P, R, run_id='N1')
    J = journal(P)
    w2 = cur()
    ok('…старт: по sha «до» — запись не случилась (recover/abort в журнал), намерение снято, запись идёт заново',
       rc == 0 and J[J0]['kind'] == 'recover' and J[J0]['action'] == 'abort' and J[J0]['of'] == it['gen']
       and J[-1]['kind'] == 'write' and w2 != w1 and not os.path.exists(P['intent'])
       and 'не дошла до замены' in txt, (txt, J[J0:]))

    # окно 3: rename случился, журнал — нет (падение сразу после write_bank)
    manifest([6])
    J0 = len(journal(P))
    _, SID.write_bank = once('write_bank')
    rc, _ = run_q(write, P, R, run_id='N1')
    SID.write_bank = real_wb
    w3, it = cur(), _intent_load(P)
    ok('падение после rename до журнала — банк новый, журнала нет, намерение «после» = sha живого',
       rc == 'die' and w3 != w2 and len(journal(P)) == J0 and it and it['live_sha_after'] == sha(w3))
    rc, txt = run_q(recover, P)
    J = journal(P)
    ok('…восстановление по sha «после»: идентичность против снимка сошлась — доводка (запись журнала с recovered)',
       rc == 0 and cur() == w3 and len(J) == J0 + 1 and J[-1]['kind'] == 'write' and J[-1]['gen'] == it['gen']
       and J[-1].get('recovered') and not os.path.exists(P['intent']) and 'DIGEST:' in txt, (txt, J[-1:]))
    rc, txt = run_q(write, P, R, run_id='N1')
    ok('…тот же manifest после доводки — уже записан, no-op', rc == 0 and cur() == w3 and len(journal(P)) == J0 + 1, txt)

    # окно 4: падение внутри записи журнала (до строки) — то же восстановление
    manifest([1])
    J0 = len(journal(P))
    real, g['_journal_add'] = (g['_journal_add'], lambda *a: (_ for _ in ()).throw(_Die('журнал')))
    rc, _ = run_q(write, P, R, run_id='N1')
    g['_journal_add'] = real
    snaps = lambda: sorted(f for f in os.listdir(P['gen']) if f.startswith('sets3-'))  # noqa: E731
    w4, nsnap = cur(), snaps()
    rc2, txt = run_q(write, P, R, run_id='N1')
    J = journal(P)
    ok('падение до журнала → следующий запуск доводит запись (без второй записи и второго снимка поколения)',
       rc == 'die' and w4 != w3 and rc2 == 0 and cur() == w4 and len(J) == J0 + 1 and J[-1].get('recovered')
       and 'уже записан' in txt and snaps() == nsnap, (rc, rc2, txt))

    # окно 5: журнал есть, намерение не снято
    manifest([2])
    J0 = len(journal(P))
    real, g['_intent_clear'] = (g['_intent_clear'], lambda *a: (_ for _ in ()).throw(_Die('снять')))
    rc, _ = run_q(write, P, R, run_id='N1')
    g['_intent_clear'] = real
    w5 = cur()
    rc2, txt = run_q(recover, P)
    ok('падение после журнала до снятия намерения — старт снимает намерение, журнал без дубля',
       rc == 'die' and rc2 == 0 and len(journal(P)) == J0 + 1 and not os.path.exists(P['intent'])
       and 'уже в журнале' in txt, (rc, rc2, txt))

    # живой менял кто-то ещё после падения — отказ, намерение остаётся, банк не трогаем
    manifest([3])
    SID.write_bank = lambda *a, **k: (_ for _ in ()).throw(_Die('до rename'))
    run_q(write, P, R, run_id='N1')
    SID.write_bank = real_wb
    _atomic(P['live'], w5 + b' ')
    other = cur()
    rc, txt = run_q(write, P, R, run_id='N1')
    ok('после падения живой — ни «до», ни «после» — писатель стоит (код 1), банк и намерение не тронуты',
       rc == 1 and cur() == other and os.path.exists(P['intent']) and 'нужен разбор' in txt, txt)
    rc, txt = run_q(recover, P, abandon=True)
    ok('…recover --abandon: намерение → журнал abandon, живой как есть', rc == 0 and not os.path.exists(P['intent'])
       and journal(P)[-1]['action'] == 'abandon' and cur() == other, txt)
    _atomic(P['live'], w5)

    # «после» по sha, но идентичность против снимка не сошлась — возврат снимка
    snapl = json.loads(w5)
    snapl[0]['set_id'], snapl[1]['set_id'] = snapl[1]['set_id'], snapl[0]['set_id']
    sraw = json.dumps(snapl, ensure_ascii=False).encode()
    sp = os.path.join(P['gen'], 'sets3-synt.json.gz')
    _atomic(sp, gzip.compress(sraw, mtime=0))
    _intent_save(P, {'gen': 'synt', 'snapshot': sp, 'live_sha_before': sha(sraw), 'live_sha_after': sha(w5), 'hold': None,
                     'record': {'gen': 'synt', 'kind': 'write'}})
    rc, txt = run_q(recover, P)
    ok('«после» по sha, идентичность против снимка разошлась — возврат снимка, recover/restore в журнале',
       rc == 1 and cur() == sraw and journal(P)[-1]['action'] == 'restore' and not os.path.exists(P['intent']), txt)
    _atomic(P['live'], w5)

    # откат: падение между заменой и журналом — доводка отката
    J0 = len(journal(P))
    real, g['_hold_save'] = (g['_hold_save'], lambda *a: (_ for _ in ()).throw(_Die('hold')))
    rc, _ = run_q(rollback, P, 'last')
    g['_hold_save'] = real
    wr = cur()
    rc2, txt = run_q(recover, P)
    J = journal(P)
    ok('откат: падение после замены до журнала — доводка (запись rollback и запрет отката дописаны)',
       rc == 'die' and wr != w5 and rc2 == 0 and len(J) == J0 + 1 and J[-1]['kind'] == 'rollback'
       and J[-1].get('recovered') and _hold(P) and not os.path.exists(P['intent']), (rc, rc2, txt))
    release(P, 'all')


def main() -> int:
    a = sys.argv[1:]
    if '--selftest' in a:
        return _selftest()
    room, a = RBS.room_arg(a)
    if room:                                   # `--room X`: пути и флаг комнаты; `--enabled` без него — флаг гостиной (BANK_WRITE)
        RBS.bind(sys.modules[__name__], RBS.for_room(room), 'bank_refresh')
    if '--enabled' in a:
        return _enabled()
    P = paths()
    if a[:1] == ['list']:
        return list_gens(P)
    gate = SPEC.skeleton_gate('bank_refresh', rules(), 'write_enabled', '--force' in a) if SPEC.skeleton else None
    if gate is not None:                       # каркас комнаты: ни записи, ни отката, ни снятия запрета
        return gate
    if a[:1] == ['rollback']:
        if len(a) < 2:
            print('использование: bank_refresh.py rollback <поколение|last> [--force]')
            return 2
        return rollback(P, a[1], force='--force' in a)
    if a[:1] == ['release']:
        return release(P, a[1] if len(a) > 1 else 'all')
    if a[:1] == ['recover']:
        return recover(P, abandon='--abandon' in a)
    from catalog_media import sync_sets
    return write(P, rules(), force='--force' in a, media_fn=sync_sets, run_id=RUN.arg(a))


if __name__ == '__main__':
    sys.exit(main())

