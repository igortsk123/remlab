#!/usr/bin/env python3
"""РЕПЕТИЦИЯ ЗАПИСИ БАНКА КОМНАТЫ В КОПИЮ С ОТКАТОМ ПО SHA (room-bank-01 этап Е «тень», T-20261107-04; ведущий 07.11 — вариант (а)).

ЗАЧЕМ. Писатель живого банка комнаты (`bank_refresh.write`) включается словом ведущего (`rooms.<комната>.write_enabled` + prepare
и promote), и первая же настоящая запись не должна быть первым запуском этого кода на настоящих данных. Каждую ночь, пока писатель
спальни выключен, здесь проходит НАСТОЯЩИЙ писатель — но в копию:
  1. живой банк и его журнал (запрет отката, журнал записей) копируются во временную папку (`TMPDIR` = REMLAB_TMP ночью);
     sha живого и список файлов папки поколений запоминаются; состояние живого должно быть определено (`bank_refresh.state`);
  2. решение — сухой вердикт сторожей этой ночи (`room_guards.verdict`: strict, модели, экзамен, связи, демо, доля ≤ 25 %);
     смешанный банк и manifest — тем же кодом, что подмена ночи (`room_bank_chain.build`, этап Ж): прежние ячейки на своих
     номерах, новые принятые — в хвост (запись вида `add`), живые вне матрицы профиля — пометка `retired`;
     сторожа подменили 0 — режим «механика»: 1 ячейка кандидата, отличная от живой, помечена «не судима» (только копия);
  3. manifest в формате `bank_promote` (номер ночи, sha живого и смешанного, отпечатки ячеек) → `bank_refresh.write` в копию:
     снимок-поколение → намерение → атомарная запись → журнал; проверка: состояние копии определено, sha «после» ≠ «до»,
     изменились ровно подменённые и снятые (retired) номера, новые — ровно хвост, идентичность (ячейка → номер, set_id) цела;
  4. откат `bank_refresh.rollback last` в копии → sha копии = sha живого «до» = sha по журналу копии; состояние определено;
  5. живой банк и папка его поколений не изменились (sha и список файлов), внешних записей 0: на время записи и отката сеть
     (сокеты) и запуск процессов закрыты — попытка считается и роняет репетицию; медиа комнаты писатель не синхронизирует.
Итог — строки `bank_rehearsal:` и одна `DIGEST:банк <комната> (репетиция): …`; сбой — `WARN:bank_rehearsal:` и код 0 (ночь
идёт). Отчёт — `~/scout-scenes/bank-<комната>-rehearsal.json` (последний) и строка в `…-rehearsal.jsonl` (история теней).
За флагом `rules/bank-candidate.json:rooms.<комната>.rehearse_enabled` (выключен — строка «выключено»). Живое не пишет никогда.

  ~/venvs/scout/bin/python bank_rehearsal.py --room bedroom [--candidate Ф] [--keep ПАПКА] [--live Ф --generations ПАПКА]
      --keep — копию не убирать, положить в ПАПКУ (новую) для разбора; --live/--generations — другой живой банк (только чтение)
  python3 tests/test_bank_rehearsal.py
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import room_bank_spec as RBS  # noqa: E402


class External(RuntimeError):
    """Попытка выйти наружу (сеть, процесс) во время записи или отката в копию."""


@contextlib.contextmanager
def sealed(hits: list):
    """Сеть и процессы закрыты: попытка — строка в `hits` и исключение (репетиция падает, наружу ничего не ушло)."""
    real_conn, real_popen = socket.socket.connect, subprocess.Popen.__init__

    def no_conn(self, addr, *a, **k):
        hits.append(f'сеть {addr}')
        raise External(f'сеть {addr}')

    def no_proc(self, args, *a, **k):
        hits.append(f'процесс {str(args)[:80]}')
        raise External(f'процесс {str(args)[:80]}')
    socket.socket.connect, subprocess.Popen.__init__ = no_conn, no_proc
    try:
        yield
    finally:
        socket.socket.connect, subprocess.Popen.__init__ = real_conn, real_popen


def tmp_root() -> str | None:
    """Папка временного на диске: REMLAB_TMP, иначе ~/remlab-scratch/tmp, если есть (`tools/ops/remlab-tmp.sh`); нет — None
    (системная). /tmp DEV — tmpfs с квотой: песочница репетиции падала там EDQUOT при ручном прогоне (T-20261107-04/4)."""
    for d in (os.environ.get('REMLAB_TMP'), os.path.expanduser('~/remlab-scratch/tmp')):
        if d and os.path.isdir(d):
            return d
    return None


def _sha_file(path: str) -> str | None:
    import bank_refresh as RF
    try:
        return RF.sha(open(path, 'rb').read())
    except FileNotFoundError:
        return None


def listing(d: str) -> dict:
    """Папка поколений живого: {имя: sha} — до и после репетиции должна быть та же."""
    if not os.path.isdir(d):
        return {}
    return {n: _sha_file(os.path.join(d, n)) for n in sorted(os.listdir(d)) if os.path.isfile(os.path.join(d, n))}


def sandbox_paths(sb: str, spec) -> dict:
    g = os.path.join(sb, 'generations')
    return {'live': os.path.join(sb, os.path.basename(spec.live)), 'lock': os.path.join(sb, 'exam.lock'),
            'manifest': os.path.join(sb, 'promote.json'), 'gen': g, 'journal': os.path.join(g, 'journal.jsonl'),
            'hold': os.path.join(g, 'hold.json'), 'intent': os.path.join(g, 'intent.json'), 'room': spec.room,
            'snap': spec.snap_prefix}


def choose(rep: dict, live: list, cand: list, key, retire: list = ()) -> tuple[list[str], str, list[str]]:
    """(ячейки в копию, режим, новые ячейки из них). Режим: «сторожа» — их подмены этой ночи (и новые ячейки в хвост, и снятие
    `retired`); «механика» — подмен 0, берём 1 ячейку кандидата, отличную от живой (не судима); «нечего» — кандидат по живым
    ячейкам равен живому и снимать нечего."""
    import room_guards as RG
    L = {key(s): s for s in live}
    take = list(rep.get('take') or [])
    new = [c for c in take if c not in L]
    if take or retire:
        return take, 'сторожа', new
    for s in cand:
        c = key(s)
        if c in L and RG.sig(L[c]) != RG.sig(s):
            return [c], 'механика', []
    return [], 'нечего', []


def manifest(room: str, run_id: str, live_raw: bytes, live: list, hybrid_path: str, hybrid: list, take: list, key,
             mode: str, fields: dict | None = None) -> dict:
    """manifest в формате подмены. `fields` — тело от `room_bank_chain.build` (режим «сторожа»); иначе — по `take` в живом."""
    import bank_pending as BP
    import bank_refresh as RF
    head = {'room': room, 'run_id': run_id, 'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'live_sha': RF.sha(live_raw),
            'hybrid': hybrid_path, 'hybrid_sha': _sha_file(hybrid_path), 'rehearsal': True, 'mode': mode}
    if fields is not None:
        return {**head, **fields}
    pos = {key(s): n for n, s in enumerate(live, 1)}
    return {**head, 'promoted': sorted(pos[c] for c in take), 'retired': [],
            'cells': [{'n': n, 'cell': c, 'candidate_hash': BP.candidate_hash(hybrid[n - 1]), 'decision': 'promote'}
                      for c, n in ((c, pos[c]) for c in take)]}


def _want(room: str) -> set:
    import room_identity as RI
    return {'|'.join(map(str, c)) for c in RI.expected(room)}


def rehearse(room: str, sb: str, *, live_path: str, gen_dir: str, verdict_fn, run_id: str, want_fn=_want) -> dict:
    """Репетиция в папке `sb` (пустая). → отчёт {'ok', 'mode', 'problems', 'external', …}. Живое только читает.
    want_fn(комната) — ключи ячеек матрицы профиля (кому `retired`); подменяемо в тестах."""
    import bank_pending as BP
    import bank_refresh as RF
    import room_bank_chain as RBC
    import room_guards as RG
    spec = RBS.for_room(room)
    RBS.bind(RF, spec, 'bank_refresh')
    key = RG.cell_key               # ключ ячейки сторожей (их `take`, `hybrid_of`); идентичность записи — `spec.cell` писателя
    out = {'room': room, 'run_id': run_id, 'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'ok': False, 'problems': [],
           'external': [], 'sandbox': sb}
    bad = out['problems']
    if not os.path.exists(live_path):
        out.update(ok=True, mode='нет живого', note='живого банка нет — репетировать нечего (поколение 0 кладёт bootstrap)')
        return out
    real = {'live': live_path, 'gen': gen_dir, 'journal': os.path.join(gen_dir, 'journal.jsonl'),
            'intent': os.path.join(gen_dir, 'intent.json'), 'room': room}
    before_sha, before_ls = _sha_file(live_path), listing(gen_dir)
    good, why = RF.state(real)
    if not good:
        bad.append(f'состояние живого не определено — {why}')
        return out
    P = sandbox_paths(sb, spec)
    os.makedirs(P['gen'])
    shutil.copyfile(live_path, P['live'])
    for n in ('journal.jsonl', 'hold.json'):
        if os.path.exists(os.path.join(gen_dir, n)):
            shutil.copyfile(os.path.join(gen_dir, n), os.path.join(P['gen'], n))
    raw = open(P['live'], 'rb').read()
    got = verdict_fn(room)
    if got is None:
        bad.append('сторожа не судили (кандидата нет)')
        return out
    rep, _, cand, live_v = got
    live = json.loads(raw)
    if live_v is not None and live_v != live:
        bad.append('живой банк сменился между копией и вердиктом сторожей')
        return out
    want = want_fn(room)
    # кандидат не годен целиком (fatal) — подмен нет, снятия нет: только «механика» (как до этапа Ж)
    take, mode, new = choose(rep, live, cand, key, [] if rep.get('fatal') else RG.retire_of(live, want))
    # new_cells — все новые ячейки кандидата (отчёт сторожей); принятые из них уйдут в хвост (`added`)
    out.update(mode=mode, take=take, new_cells=list(rep.get('new_cells') or new), guards_take=len(rep.get('take') or []),
               cap=rep.get('cap'))
    if mode == 'нечего':
        out.update(ok=True, note='кандидат по живым ячейкам равен живому — записывать нечего')
        return out
    if mode == 'сторожа':                   # тот же код, что подмена ночи: живые на своих номерах, новые в хвост, retired
        hybrid, fields = RBC.build(room, rep, live, cand, want, BP.candidate_hash)
    else:
        hybrid, fields = RG.hybrid_of(live, cand, set(take), [key(s) for s in live]), None
    hpath = os.path.join(sb, 'hybrid.json')
    with open(hpath, 'w', encoding='utf-8') as f:
        json.dump(hybrid, f, ensure_ascii=False, indent=1)
    man = manifest(room, run_id, raw, live, hpath, hybrid, take, key, mode, fields)
    out.update(retired=man.get('retired') or [], added=[n for n in man['promoted'] if n > len(live)])
    with open(P['manifest'], 'w', encoding='utf-8') as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    hits = out['external']
    try:
        with sealed(hits):
            rc_w = RF.write(P, {'write_enabled': True}, media_fn=None, run_id=run_id)
            after = _sha_file(P['live'])
            J = RF.journal(P)
            wrec = J[-1] if J and J[-1].get('kind') in RF.WRITES else None      # `add` — запись с новыми ячейками
            st_w = RF.state(P)
            rc_r = RF.rollback(P, 'last') if wrec else None
            back = _sha_file(P['live'])
            st_r = RF.state(P)
    except External as e:
        bad.append(f'внешняя запись при записи/откате: {e}')
        return out
    out.update(write_rc=rc_w, rollback_rc=rc_r, sha_before=before_sha, sha_after_write=after, sha_after_rollback=back,
               generation=(wrec or {}).get('gen'), promoted=man['promoted'])
    if rc_w != 0 or not wrec:
        bad.append(f'запись в копию не прошла (код {rc_w}, записи в журнале {"нет" if not wrec else "есть"})')
    else:
        if after == before_sha:
            bad.append('после записи sha не сменился')
        if wrec.get('live_sha_before') != before_sha or wrec.get('live_sha_after') != after:
            bad.append('журнал записи: sha «до»/«после» не те')
        if not st_w[0]:
            bad.append(f'после записи состояние копии не определено — {st_w[1]}')
        if rc_r != 0:
            bad.append(f'откат в копии не прошёл (код {rc_r})')
        if back != before_sha:
            bad.append(f'после отката копия ≠ живой «до» ({(back or "нет")[:12]} против {(before_sha or "нет")[:12]})')
        if not st_r[0]:
            bad.append(f'после отката состояние копии не определено — {st_r[1]}')
    changed, grown, ident = _changed(json.loads(raw), P, RF, spec.cell) if wrec else (None, None, [])
    n0 = len(json.loads(raw))
    expect = sorted([n for n in man['promoted'] if n <= n0] + list(man.get('retired') or []))
    if changed is not None and changed != expect:
        bad.append(f'изменились номера {changed[:8]}, а подменяли и снимали {expect[:8]}')
    if grown is not None and grown != out['added']:
        bad.append(f'в хвост добавлены номера {grown[:8]}, а новых ячеек {out["added"][:8]}')
    if wrec and wrec.get('kind') != ('add' if out['added'] else 'write'):
        bad.append(f"вид записи журнала {wrec.get('kind')}, а новых ячеек {len(out['added'])}")
    out['grown'] = grown
    if ident:
        bad.append('идентичность записанного банка: ' + '; '.join(ident)[:200])
    out['changed'] = changed
    if _sha_file(live_path) != before_sha:
        bad.append('ЖИВОЙ БАНК ИЗМЕНИЛСЯ во время репетиции')
    if listing(gen_dir) != before_ls:
        bad.append('ПАПКА ПОКОЛЕНИЙ ЖИВОГО изменилась во время репетиции')
    out['ok'] = not bad and not hits
    return out


def _changed(live: list, P: dict, RF, key) -> tuple[list[int] | None, list[int] | None, list[str]]:
    """(номера живого, которые запись поменяла; номера, добавленные в хвост; нарушения идентичности записанного против живого:
    прежние номера и id на месте, новые — со своим id). Записанный банк — снимок, который откат сделал перед собой (банк ПОСЛЕ
    записи)."""
    import gzip
    import set_identity as SID
    rb = next((r for r in reversed(RF.journal(P)) if r.get('kind') == 'rollback'), None)
    if not rb:
        return None, None, []
    wrote = json.loads(gzip.decompress(open(rb['snapshot'], 'rb').read()))
    strip = RF._strip
    return ([n for n, (a, b) in enumerate(zip(live, wrote), 1) if strip(a) != strip(b)],
            list(range(len(live) + 1, len(wrote) + 1)),
            SID.verify(wrote, live, cells=None, key=key, grow=True))


def digest(out: dict) -> str:
    ru = {'bedroom': 'спальня', 'hall': 'прихожая'}.get(out['room'], out['room'])
    ext = f"внешних записей {len(out.get('external') or [])}"
    if out.get('problems') or out.get('external'):
        return (f"DIGEST:банк {ru} (репетиция): СБОЙ — {'; '.join((out.get('problems') or []) + (out.get('external') or []))[:300]}; "
                f"живой не тронут; {ext}")
    if out.get('mode') in ('нет живого', 'нечего'):
        return f"DIGEST:банк {ru} (репетиция): {out.get('note')}; {ext}"
    how = ('механика: 1 ячейка, не судима' if out['mode'] == 'механика'
           else f"подмены сторожей этой ночи ({out.get('guards_take')}, предел {out.get('cap')})")
    return (f"DIGEST:банк {ru} (репетиция): запись в копию — подменено {len(out.get('promoted') or [])} ({how}), "
            f"sha {out['sha_before'][:12]} → {out['sha_after_write'][:12]}; откат по SHA — копия = живой "
            f"({out['sha_after_rollback'][:12]}); живой и его поколения не тронуты; {ext}"
            + (f"; из них новых ячеек в хвост {len(out['added'])} {out['added'][:12]}" if out.get('added') else '')
            + (f"; снято с витрины (retired) {len(out['retired'])}" if out.get('retired') else '')
            + (f"; новых ячеек ждут суда {len(out['new_cells']) - len(out.get('added') or [])}"
               if len(out.get('new_cells') or []) > len(out.get('added') or []) else ''))


def report_paths(room: str) -> tuple[str, str]:
    base = os.path.expanduser(os.environ.get(f'BANK_{room.upper()}_REHEARSAL') or f'~/scout-scenes/bank-{room}-rehearsal')
    return base + '.json', base + '.jsonl'


def save(out: dict) -> None:
    last, hist = report_paths(out['room'])
    os.makedirs(os.path.dirname(last), exist_ok=True)
    tmp = last + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, last)
    with open(hist, 'a', encoding='utf-8') as f:
        f.write(json.dumps({k: out.get(k) for k in ('at', 'run_id', 'ok', 'mode', 'take', 'promoted', 'changed', 'sha_before',
                                                     'sha_after_write', 'sha_after_rollback', 'problems', 'external')},
                           ensure_ascii=False, default=str) + '\n')


def main(argv: list) -> int:
    room, argv = RBS.room_arg(argv)
    if not room or room == RBS.LIVING:
        print('bank_rehearsal: нужен --room <комната> (гостиная — свой писатель, тень гостиной — отдельно)')
        return 2
    spec = RBS.for_room(room)
    if not spec.rules().get('rehearse_enabled'):
        print(f'bank_rehearsal: выключено (rules/bank-candidate.json:rooms.{room}.rehearse_enabled=false)', flush=True)
        return 0
    opt = lambda n: argv[argv.index(n) + 1] if n in argv and argv.index(n) + 1 < len(argv) else None  # noqa: E731
    cand, keep = opt('--candidate'), opt('--keep')
    live_path, gen_dir = opt('--live') or spec.live, opt('--generations') or spec.generations
    run_id = f"rehearsal-{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"

    def verdict_fn(r):
        import room_guards as RG
        return RG.verdict(r, cand, live_path)
    try:
        if keep:
            os.makedirs(keep)               # новая папка: существующую не трогаем
            out = rehearse(room, keep, live_path=live_path, gen_dir=gen_dir, verdict_fn=verdict_fn, run_id=run_id)
        else:
            with tempfile.TemporaryDirectory(prefix=f'bank-rehearsal-{room}-', dir=tmp_root()) as sb:
                out = rehearse(room, sb, live_path=live_path, gen_dir=gen_dir, verdict_fn=verdict_fn, run_id=run_id)
    except (Exception, SystemExit) as e:  # noqa: BLE001 — репетиция не прошла: ночь идёт, в сводке видно; SystemExit — модули
        # сторожей/сборщика выходят им на нехватке входа (нет style-scores-*.json): без него шаг ночи стал бы FAIL, а не WARN
        out = {'room': room, 'run_id': run_id, 'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'ok': False, 'external': [],
               'problems': [f'упала: {type(e).__name__}: {str(e)[:200]}']}
    try:
        save(out)
    except OSError as e:
        print(f'WARN:bank_rehearsal: отчёт не записан ({e})', flush=True)
    print(f"bank_rehearsal {room}: {'ок' if out.get('ok') else 'СБОЙ'} — режим {out.get('mode')}, подменено "
          f"{len(out.get('promoted') or [])} {out.get('take') or ''}; код записи {out.get('write_rc')}, отката "
          f"{out.get('rollback_rc')}; изменились номера {out.get('changed')}; внешних записей {len(out.get('external') or [])}"
          + (f"; копия — {keep}" if keep else ''), flush=True)
    for p in out.get('problems') or []:
        print(f'  ✗ {p}', flush=True)
    if not out.get('ok'):
        print(f"WARN:bank_rehearsal: {room}: {'; '.join(out.get('problems') or out.get('external') or ['не прошла'])[:200]} — "
              'живой не тронут', flush=True)
    print(digest(out), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
