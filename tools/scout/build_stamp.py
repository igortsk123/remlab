"""МЕТКА СБОРКИ ДАННЫХ (T-20261112-92): одно поле `build` в данных /demo (`flat215_demo.py`) и тура (`trial_bundle.py`,
`trial_reissue.py`) — «<git>.<правила>». Страница его не читает; по нему проверка «демо = туры» (`tools/ops/tour-reissue.sh`)
видит, что тур и витрина собраны одними правилами сборщика.

  git     — короткий хеш HEAD копии, из которой собрано (справка: коммиты одной памяти его двигают, сравнивать не по нему);
  правила — sha256 ВХОДОВ СБОРКИ ВИТРИНЫ `DEMO_INPUTS` (ниже): файлы правил, которые читает `flat215_demo.py` и то, что он
            импортирует и запускает, и папки целиком (`room-templates/`, `profiles/` — все файлы с подпапками) — путь от корня
            репо + содержимое, в порядке пути.
  История: до T-20261112-121 (conveyor-guards-01 шаг 5) — только верхний уровень rules/ (правка шаблона комнаты метку не
  двигала); шаг 5 — вся rules/** (13.11 новый `rules/tour-auto-photos.json`, влитый во время сборки, сорвал выкладку /demo без
  причины — витрина его не читает); T-121/2 — только входы сборки. Новый файл в rules/** вне списка метку НЕ двигает.
Сбой git — `nogit`, правил нет — `norules`: метка не валит сборку.

СПИСОК ВХОДОВ — ОДИН, ЗДЕСЬ. Сторож — `tools/ops/build_inputs.py` (CI и prepush через `conveyor_check.py`): обходит код сборки и
краснеет, если тот называет правило вне списка; на ходу `watch_rules()` (зовёт `flat215_demo.py`) пишет `WARN:build_inputs:`,
если сборка открыла правило вне списка, и строку «прочитано K из N входов» — по ней лишнее из списка можно убрать с доказательством.

ПУБЛИКАТОР СВЕРЯЕТ (шаг 5): `publish_demo.sh` зовёт `build_stamp.py --check-data <сборка>/demo-data.json` и не выкладывает сборку,
у которой нет метки или правила метки ≠ правилам копии, из которой публикуют (собрано по другим правилам — пересобрать
`flat215_demo.py`). Самопроверка — `python tools/scout/build_stamp.py --selftest`.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RULE_DIRS = ('services/planner-solver/rules', 'tools/scout/rules')
_P, _S = 'services/planner-solver/rules/', 'tools/scout/rules/'
# ВХОДЫ СБОРКИ ВИТРИНЫ (T-121/2): что называет код `flat215_demo.py` и его импортов/запусков (`python tools/ops/build_inputs.py
# --list` — кто какое). Папка с `/` на конце — все её .json с подпапками. Новое правило, которое сборка читает, — сюда, иначе CI
# красный; правило, которое сборка не читает (автофото тура, деньги, диск), — не сюда: его правка выкладку не держит.
DEMO_INPUTS = (
    _P + 'bedroom.json', _P + 'hall.json', _P + 'occupancy.json', _P + 'templates.json', _P + 'weights.json', _P + 'zones.json',
    _P + 'room-templates/',
    _S + 'asset-strategies.json', _S + 'bank-candidate.json', _S + 'bedroom-roles.json', _S + 'catalog-bindings.json',
    _S + 'catalog-bindings.schema.json', _S + 'catalog-item.schema.json', _S + 'demo-layout.json', _S + 'demo-swap.json',
    _S + 'dev-tmp.json', _S + 'hall-roles.json', _S + 'improve-rooms.json', _S + 'mesh-asset-decisions.json',
    _S + 'mesh-color-guard.json', _S + 'mesh-pinned.json', _S + 'mesh-priority.json', _S + 'mesh-quarantine.json',
    _S + 'mesh-queue-demo.json', _S + 'openai_prices.json', _S + 'photo-set-roles.json', _S + 'practice_priors.json', _S + 'quiz.json',
    _S + 'room-mesh-want.json', _S + 'room-profile.schema.json', _S + 'style-axes.json', _S + 'style-color-policy.json',
    _S + 'profiles/',
)


def rule_files(root: str = ROOT, inputs=DEMO_INPUTS) -> list[str]:
    """→ файлы входов от корня, по порядку пути (одна копия правил — один порядок на любой машине); нет файла — пропуск
    (его ловит `build_inputs.py`)."""
    out = set()
    for i in inputs:
        p = os.path.join(root, i)
        if i.endswith('/'):
            for dp, _dn, fn in os.walk(p):
                out.update(os.path.relpath(os.path.join(dp, f), root).replace(os.sep, '/') for f in fn if f.endswith('.json'))
        elif os.path.isfile(p):
            out.add(i)
    return sorted(out)


def rules_hash(root: str = ROOT, inputs=DEMO_INPUTS) -> str:
    h, n = hashlib.sha256(), 0
    for rel in rule_files(root, inputs):
        with open(os.path.join(root, rel), 'rb') as f:
            h.update(rel.encode('utf-8') + b'\0' + f.read() + b'\0')
        n += 1
    return h.hexdigest()[:10] if n else 'norules'


def git_head(root: str = ROOT) -> str:
    try:
        r = subprocess.run(['git', '-C', root, 'rev-parse', '--short=10', 'HEAD'], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else 'nogit'
    except (OSError, subprocess.TimeoutExpired):
        return 'nogit'


def stamp(root: str = ROOT) -> str:
    """→ «<git>.<правила>»."""
    return f'{git_head(root)}.{rules_hash(root)}'


def rules_of(build: str | None) -> str:
    """Часть «правила» метки (то, что сравнивает проверка); нет метки — ''."""
    return str(build or '').rsplit('.', 1)[-1] if build and '.' in str(build) else ''


def check_data(path: str, root: str = ROOT) -> str:
    """Сборка `path` (demo-data.json) собрана по правилам копии `root`? → '' (да) или причина отказа."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return f'данные сборки не прочитаны ({type(e).__name__}: {path})'
    got = rules_of(data.get('build') if isinstance(data, dict) else None)
    if not got:
        return f'у сборки нет метки правил (`build` в {path}) — собрана до T-92 или не flat215_demo.py'
    want = rules_hash(root)
    if got != want:
        return f'сборка собрана по другим правилам: метка {got}, правила этой копии {want}'
    return ''


# ------------------------------------------------------------------ на ходу: какие правила сборка открыла (T-121/2)
_OPENED: set[str] = set()
_WATCH: list[str] = []


def watch_rules(root: str = ROOT) -> None:
    """Слушать открытия файлов процесса (sys.addaudithook): всё под RULE_DIRS копии `root` — в `_OPENED`. Сбой — молча мимо."""
    if _WATCH:
        return
    base = os.path.abspath(root)
    dirs = tuple(os.path.join(base, d) + os.sep for d in RULE_DIRS)

    def hook(event, args):
        if event != 'open' or not args:
            return
        try:
            p = args[0]
            if isinstance(p, int):
                return
            p = os.path.abspath(os.fsdecode(p))
            if p.startswith(dirs) and p.endswith('.json'):
                _OPENED.add(os.path.relpath(p, base).replace(os.sep, '/'))
        except Exception:  # noqa: BLE001 — сторож не валит сборку
            pass

    sys.addaudithook(hook)
    _WATCH.append(base)


def watch_report(root: str | None = None, inputs=DEMO_INPUTS) -> list[str]:
    """→ строки для журнала: правила вне входов, которые сборка открыла (WARN), и «прочитано K из N входов»."""
    if not _WATCH:
        return []
    root = root or _WATCH[0]
    listed = set(rule_files(root, inputs))
    extra = sorted(_OPENED - listed)
    out = [f'WARN:build_inputs: сборка прочла правило вне build_stamp.DEMO_INPUTS — {p}: его правка метку не сдвинет; добавить '
           f'во входы' for p in extra]
    unread = sorted(listed - _OPENED)
    out.append(f'build_inputs: прочитано {len(listed & _OPENED)} из {len(listed)} входов; не прочитаны в этом процессе '
               f'(могли читать запущенные скрипты): {", ".join(p.rsplit("/", 1)[-1] for p in unread) or "—"}')
    return out


def _selftest() -> int:
    import tempfile
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
    remlab_tmp.use('build_stamp-selftest')
    bad = []

    def ok(c, m):
        print(('OK  ' if c else 'BAD ') + m)
        if not c:
            bad.append(m)

    with tempfile.TemporaryDirectory(prefix='build-stamp-') as d:
        def put(rel, text):
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(text)

        inp = (_P + 'occupancy.json', _P + 'room-templates/', _S + 'demo-swap.json', _S + 'profiles/')
        ok(rules_hash(d, inp) == 'norules', 'нет правил — norules')
        put(_P + 'occupancy.json', '{"a": 1}')
        put(_S + 'demo-swap.json', '{"b": 1}')
        h0 = rules_hash(d, inp)
        put(_S + 'tour-auto-photos.json', '{"новое": 1}')
        put(_P + 'severity.json', '{}')
        ok(rules_hash(d, inp) == h0, 'новый посторонний файл в rules/ (автофото тура, 13.11) — метка та же')
        put(_S + 'demo-swap.json', '{"b": 2}')
        h1 = rules_hash(d, inp)
        ok(h1 != h0, 'правка правила из списка — метка другая')
        put(_P + 'room-templates/living.json', '{"w": 1}')
        h2 = rules_hash(d, inp)
        ok(h2 != h1 and _P + 'room-templates/living.json' in rule_files(d, inp), 'шаблон комнаты из подпапки — входит')
        put(_P + 'room-templates/living.json', '{"w": 2}')
        ok(rules_hash(d, inp) != h2, 'правка шаблона комнаты — метка другая')
        h3 = rules_hash(d, inp)
        put(_S + 'profiles/x/deep.json', '{}')
        ok(rules_hash(d, inp) != h3, 'файл на любой глубине папки-входа — в метке')
        put(_S + 'profiles/notes.md', 'не правило')
        ok(_S + 'profiles/notes.md' not in rule_files(d, inp), 'не-json в метку не идёт')
        ok(rule_files(d, inp) == sorted(rule_files(d, inp)), 'порядок — по пути')
        ok(rules_hash(d, inp + (_S + 'нет-такого.json',)) == rules_hash(d, inp), 'вход без файла — не валит метку (ловит build_inputs)')
        put('out/good.json', json.dumps({'build': f'abc.{rules_hash(d)}'}))
        put('out/stale.json', json.dumps({'build': 'abc.0123456789'}))
        put('out/nostamp.json', json.dumps({'v': 1}))
        put('out/broken.json', '{')
        ok(check_data(os.path.join(d, 'out/good.json'), d) == '', 'сборка по этим правилам — пропуск')
        ok('другим правилам' in check_data(os.path.join(d, 'out/stale.json'), d), 'другие правила — отказ')
        ok('нет метки' in check_data(os.path.join(d, 'out/nostamp.json'), d), 'нет метки — отказ')
        ok('не прочитаны' in check_data(os.path.join(d, 'out/broken.json'), d), 'битый файл — отказ')
        ok('не прочитаны' in check_data(os.path.join(d, 'out/none.json'), d), 'нет файла — отказ')
        # на ходу: открытое правило вне списка — WARN, из списка — «прочитано»
        watch_rules(d)
        with open(os.path.join(d, _S + 'demo-swap.json'), encoding='utf-8') as f:
            f.read()
        with open(os.path.join(d, _S + 'tour-auto-photos.json'), encoding='utf-8') as f:
            f.read()
        rep = watch_report(d, inp)
        ok(any('WARN:build_inputs' in s and 'tour-auto-photos.json' in s for s in rep), 'сборка открыла правило вне списка — WARN')
        ok(any(s.startswith('build_inputs: прочитано 1 из') for s in rep) and not any('demo-swap' in s and 'WARN' in s for s in rep),
           'правило из списка — «прочитано», без WARN')
    ok(any('/room-templates/' in p for p in rule_files()), 'в репо шаблоны комнат входят в метку')
    ok(not any('tour-auto-photos' in p for p in rule_files()), 'в репо правило автофото тура в метку не входит')
    print('итог:', 'OK' if not bad else f'FAIL ({len(bad)})')
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ['--selftest']:
        return _selftest()
    if len(argv) == 2 and argv[0] == '--check-data':
        why = check_data(argv[1])
        if why:
            print(f'отказ: {why}. Пересоберите витрину (`tools/scout/flat215_demo.py`) из этой копии и публикуйте снова.')
            return 1
        print(f'метка правил сборки сверена: {rules_hash()}')
        return 0
    if not argv:
        print(stamp())
        return 0
    print('ключи: --check-data <demo-data.json> | --selftest | (без ключей — метка этой копии)', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
