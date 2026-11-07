#!/usr/bin/env python3
"""СВЯЗКА НОЧИ БАНКА ПО `run_id` (план room-bank-01 этап А, критика Codex 06.11 `_intake/codex/room-bank-2026-11-06-answer.md` § 4–5).

ЗАЧЕМ. Цепочка `bank_prepare` → `bank_pending --night` → `bank_promote` → `bank_refresh` шла подряд без связи: promote судил ЛЮБОЙ
лежащий кандидат (`sets3.next.json` вчерашний, если сборка этой ночи упала), а писатель проверял только возраст manifest. Теперь у
ночи один номер `run_id`: prepare кладёт его в отчёт и в паспорт кандидата (`<кандидат>.run.json`: номер + sha256 байт файла),
pending — в своё состояние, promote — в manifest; каждый следующий шаг принимает только СВОЙ номер и только тот самый файл
кандидата (по sha), иначе — отказ строкой `ERROR:` и `DIGEST:` (ночной дайджест её собирает). Вручную — `--run-id` явно.

Паспорт — отдельным файлом, а не полем в кандидате: кандидат — список сетов, его читают сборщик, демо, тесты солвера.

  python3 bank_run.py --selftest
"""
import hashlib
import json
import os
import sys
import time


class ChainError(Exception):
    """Шаг цепочки не своей ночи / не тот кандидат: `rc` — код шага, текст — для ERROR и дайджеста."""

    def __init__(self, msg: str, rc: int = 1):
        super().__init__(msg)
        self.rc = rc


def new_run_id(kind: str = 'manual') -> str:
    return f"{kind}-{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"


def arg(argv: list) -> str | None:
    """`--run-id X` из командной строки (нет — None; пустое значение — тоже None)."""
    if '--run-id' not in argv:
        return None
    i = argv.index('--run-id') + 1
    return argv[i] if i < len(argv) and argv[i] and not argv[i].startswith('--') else None


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def passport_path(cand: str) -> str:
    return (cand[:-5] if cand.endswith('.json') else cand) + '.run.json'


def _atomic_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def attest(cand: str, run_id: str) -> str:
    """Паспорт кандидата: номер ночи и sha байт файла, каким его оставил prepare. Возвращает sha."""
    h = sha(open(cand, 'rb').read())
    _atomic_json(passport_path(cand), {'run_id': run_id, 'candidate_sha': h, 'at': time.strftime('%Y-%m-%dT%H:%M:%S')})
    return h


def refuse(step: str, msg: str, rc: int = 1) -> int:
    """Отказ шага цепочки: строка ошибки шага и строка в утренний дайджест."""
    print(f'ERROR:{step}: {msg}', flush=True)
    print(f'DIGEST:банк: {step} отказал — {msg}', flush=True)
    return rc


def need(run_id: str | None) -> str:
    if not run_id:
        raise ChainError('нужен --run-id (номер ночи из отчёта bank_prepare; вручную — тот, что напечатал bank_prepare)', 2)
    return run_id


def load_report(report: str, run_id: str) -> dict:
    """Отчёт bank_prepare именно этой ночи."""
    try:
        rep = json.load(open(report, encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ChainError(f'отчёта bank_prepare {report} нет или не читается ({type(e).__name__})')
    if rep.get('run_id') != run_id:
        raise ChainError(f"отчёт bank_prepare не этой ночи (run_id {rep.get('run_id')} ≠ {run_id})")
    return rep


def candidate(rep: dict, run_id: str, cand_path: str | None = None) -> tuple[bytes, str]:
    """Байты кандидата этой ночи (одно чтение — дальше судят ровно их) и их sha. Проверки: prepare довёл кандидат до суда,
    путь тот же, sha файла = sha в отчёте = sha в паспорте, номер паспорта — этой ночи."""
    if not rep.get('pending_due'):
        raise ChainError('кандидат этой ночи не прошёл bank_prepare (нет pending_due)')
    path = cand_path or rep.get('candidate')
    if not path:
        raise ChainError('в отчёте bank_prepare нет пути кандидата')
    if rep.get('candidate') and os.path.realpath(rep['candidate']) != os.path.realpath(path):
        raise ChainError(f"кандидат {path} — не тот, что собрал bank_prepare ({rep['candidate']})")
    try:
        raw = open(path, 'rb').read()
    except OSError as e:
        raise ChainError(f'кандидата {path} нет ({type(e).__name__})')
    h = sha(raw)
    if h != rep.get('candidate_sha'):
        raise ChainError('файл кандидата изменился после bank_prepare (sha другой)')
    try:
        pp = json.load(open(passport_path(path), encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ChainError(f'паспорта кандидата {passport_path(path)} нет ({type(e).__name__})')
    if pp.get('run_id') != run_id or pp.get('candidate_sha') != h:
        raise ChainError(f"паспорт кандидата не этой ночи (run_id {pp.get('run_id')}, sha "
                         f"{'тот' if pp.get('candidate_sha') == h else 'другой'})")
    return raw, h


def _selftest() -> int:
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
    remlab_tmp.use('bank_run-selftest')
    import contextlib
    import io
    import tempfile
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1

    def err(fn):
        try:
            fn()
        except ChainError as e:
            return str(e), e.rc
        return None, None
    with tempfile.TemporaryDirectory(prefix='bank-run-') as td:
        cand, rp = os.path.join(td, 'sets3.next.json'), os.path.join(td, 'bank-prepare.json')
        open(cand, 'w').write('[{"a": 1}]')
        h = attest(cand, 'R1')
        _atomic_json(rp, {'run_id': 'R1', 'candidate': cand, 'candidate_sha': h, 'pending_due': True})
        raw, h2 = candidate(load_report(rp, 'R1'), 'R1', cand)
        ok('своя ночь: байты и sha кандидата отдаются', raw == b'[{"a": 1}]' and h2 == h)
        ok('паспорт рядом с кандидатом', passport_path(cand) == os.path.join(td, 'sets3.next.run.json'))
        m, rc = err(lambda: load_report(rp, 'R2'))
        ok('чужой run_id отчёта — отказ', m and 'не этой ночи' in m and rc == 1, m)
        m, _ = err(lambda: load_report(os.path.join(td, 'нет.json'), 'R1'))
        ok('отчёта нет — отказ', m and 'нет или не читается' in m, m)
        m, rc = err(lambda: need(None))
        ok('без --run-id — отказ кодом 2', m and '--run-id' in m and rc == 2, m)
        open(cand, 'w').write('[{"a": 2}]')                  # устаревший/подменённый кандидат
        m, _ = err(lambda: candidate(load_report(rp, 'R1'), 'R1', cand))
        ok('кандидат изменился после prepare — отказ', m and 'изменился' in m, m)
        h3 = attest(cand, 'R0')                                # кандидат вчерашней ночи с её паспортом
        _atomic_json(rp, {'run_id': 'R1', 'candidate': cand, 'candidate_sha': h3, 'pending_due': True})
        m, _ = err(lambda: candidate(load_report(rp, 'R1'), 'R1', cand))
        ok('паспорт кандидата другой ночи — отказ', m and 'паспорт кандидата не этой ночи' in m, m)
        _atomic_json(rp, {'run_id': 'R1', 'candidate': cand, 'candidate_sha': h3})
        m, _ = err(lambda: candidate(load_report(rp, 'R1'), 'R1', cand))
        ok('без pending_due — отказ', m and 'pending_due' in m, m)
        _atomic_json(rp, {'run_id': 'R1', 'candidate': '/другой/sets3.next.json', 'candidate_sha': h3, 'pending_due': True})
        m, _ = err(lambda: candidate(load_report(rp, 'R1'), 'R1', cand))
        ok('другой путь кандидата — отказ', m and 'не тот' in m, m)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = refuse('bank_promote', 'тест')
    ok('отказ: ERROR и DIGEST строкой', rc == 1 and 'ERROR:bank_promote: тест' in buf.getvalue()
       and 'DIGEST:банк: bank_promote отказал — тест' in buf.getvalue(), buf.getvalue())
    ok('--run-id из argv', arg(['x', '--run-id', 'R9']) == 'R9' and arg(['--run-id']) is None and arg(['--run-id', '--x']) is None
       and arg([]) is None)
    ok('номер ночи: вид-дата-pid', new_run_id('night').startswith('night-') and new_run_id().count('-') == 2)
    print(f'bank_run selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)
