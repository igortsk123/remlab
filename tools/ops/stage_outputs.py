"""ВЫХОД ЭТАПА БЕЗ ПОТРЕБИТЕЛЯ — проверка конвейера покраски (T-20261125-82, урок 25.11 «05-delight строился неделю, а читали сырое фото»; правило P-068
«урок — только с автопроверкой»). Часть `conveyor_check.py` (как build_inputs / docker_context / render_inputs): режим ПРЕДУПРЕЖДЕНИЕ (код выхода не меняет).

Описание конвейера — `tools/scout/rules/paint-run-all.json`: у каждого этапа `outputs` — файлы выхода (путь от папки товара, `05-delight/delight.rgba.png`) и КТО их читает.
Запись выхода — одно из двух:
  {"file": "05-delight/delight.rgba.png", "consumers": [{"stage": "06", "via": "dynamic", "key": "photo_vis"}]}
  {"file": "05-delight/frame.png", "report_only": "контрольный кадр этапа для человека"}   # либо "terminal": "итог конвейера, забирают вне run-all …"
Потребитель обязан быть НЕ ДО производителя по `order` и ПОДТВЕРЖДЁН по описанию/коду (описанию на слово не верим):
  via needs   — у потребителя в `needs`/`needs_tolerate` стоит папка производителя (только для check.json: гейт по статусу);
  via dynamic — `dynamic[key]` ссылается на файл (file_if_ok [папка, файл] / if_stage_ok {stage, file} / from_extra [папка, …]) и `{key}` стоит в argv шага потребителя;
  via argv    — путь файла (`07-fill/filled.glb`) стоит в argv шага потребителя;
  via alias   — `{alias}` (например prep_glb) стоит и в argv производителя, и в argv потребителя;
  via code    — скрипт из argv потребителя (`{root}/tools/…py`) существует и содержит `pattern` (по умолчанию имя файла); `code` — другой файл-доказательство
                (например правило, где этап перечислен), он обязан быть в репо, а скрипт потребителя — в его argv.
Находки (WARN):
  ORPHAN-OUTPUT <этап> <файл>: нет потребителя и не помечен terminal/report_only (с причиной);
  ORPHAN-OUTPUT <этап> <файл>: потребитель <этап> не подтверждён (…): заявлен, но в описании/коде его нет — «подключён на словах»;
  ORPHAN-OUTPUT <этап> <папка>: выходы папки не описаны (`outputs`).
Выход не гасится «исключением»: либо потребитель подтверждён, либо честная причина terminal/report_only, либо остаётся предупреждением.

    python3 tools/ops/stage_outputs.py                # предупреждения
    python3 tools/ops/stage_outputs.py --table        # таблица «этап → файл → кто читает → чем подтверждено» (md)
    python3 tools/ops/stage_outputs.py --selftest
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DEFAULT = os.path.abspath(os.path.join(HERE, '..', '..'))
RULES = 'tools/scout/rules/paint-run-all.json'


def load(root: str) -> dict:
    with open(os.path.join(root, RULES), encoding='utf-8') as f:
        return json.load(f)


def _argv_text(stage: dict) -> str:
    return '\n'.join(' '.join(str(x) for x in (st.get('argv') or [])) for st in stage.get('steps') or [])


def _read(root: str, rel: str):
    try:
        with open(os.path.join(root, rel), encoding='utf-8', errors='ignore') as f:
            return f.read()
    except OSError:
        return None


def _scripts(root: str, stage: dict) -> list:
    """Скрипты шагов этапа: токены argv вида `{root}/tools/…` с расширением кода."""
    out = []
    for st in stage.get('steps') or []:
        for tok in st.get('argv') or []:
            t = str(tok)
            if t.startswith('{root}/') and t.endswith(('.py', '.sh', '.mjs')):
                out.append(t[len('{root}/'):])
    return out


def evidence(root: str, rules: dict, prod: str, out: dict, cons: dict) -> tuple:
    """(подтверждён?, чем / почему нет)."""
    order, stages = rules.get('order') or [], rules.get('stages') or {}
    cid, via = str(cons.get('stage')), cons.get('via')
    if cid not in stages:
        return False, f'этапа {cid} нет в stages'
    if cid not in order or prod not in order or order.index(cid) <= order.index(prod):
        return False, f'этап {cid} не после {prod} по order'
    cst, pst = stages[cid], stages[prod]
    f = out['file']
    folder = f.split('/')[0]
    if via == 'needs':
        if not f.endswith('check.json'):
            return False, 'via needs годится только для check.json (гейт по статусу)'
        if folder in (cst.get('needs') or []) or folder in (cst.get('needs_tolerate') or {}):
            return True, f'needs этапа {cid} содержит {folder}'
        return False, f'{folder} нет в needs этапа {cid}'
    if via == 'dynamic':
        key = cons.get('key')
        d = (rules.get('dynamic') or {}).get(key) or {}
        ios = d.get('if_stage_ok') or {}
        ref = d.get('file_if_ok') or d.get('from_extra') or ([ios['stage'], ios['file']] if ios.get('stage') and ios.get('file') else None)
        hit = bool(ref) and ref[0] == folder and (len(ref) < 2 or ref[1] == f.split('/', 1)[-1] or d.get('from_extra'))
        if not hit:
            return False, f'dynamic.{key} не ссылается на {f}'
        if '{' + str(key) + '}' not in _argv_text(cst):
            return False, f'{{{key}}} нет в argv этапа {cid}'
        return True, f'dynamic.{key} → {{{key}}} в argv {cid}'
    if via == 'argv':
        if f in _argv_text(cst) or (f.endswith('/') and f.rstrip('/') in _argv_text(cst)):
            return True, f'«{f}» в argv {cid}'
        return False, f'«{f}» нет в argv этапа {cid}'
    if via == 'alias':
        a = '{' + str(cons.get('alias')) + '}'
        if a in _argv_text(pst) and a in _argv_text(cst):
            return True, f'{a} в argv {prod} и {cid}'
        return False, f'{a} не стоит в argv обоих этапов ({prod}, {cid})'
    if via == 'code':
        scripts = _scripts(root, cst)
        script = cons.get('script')
        if script and script not in scripts:
            return False, f'скрипта {script} нет в argv этапа {cid}'
        if not script and not scripts:
            return False, f'в argv этапа {cid} нет скриптов'
        proof = cons.get('code') or script
        pats = cons.get('pattern') or os.path.basename(f.rstrip('/'))
        pats = [pats] if isinstance(pats, str) else list(pats)
        for rel in ([proof] if proof else scripts):
            src = _read(root, rel)
            if src is None:
                return False, f'файла-доказательства {rel} нет в репо'
            if all(p in src for p in pats) or (not proof and any(p in src for p in pats)):
                return True, f'«{pats[0]}» найдено в {rel}'
        return False, f'«{pats[0]}» не найдено в ' + ', '.join([proof] if proof else scripts)
    return False, f'via «{via}» не поддерживается'


def analyse(root: str, rules: dict) -> list:
    """Строки таблицы: {stage, file, status: ok|terminal|report_only|orphan|unconfirmed|no-outputs, why, consumers: [(stage, via, ok, чем)]}."""
    rows = []
    for sid in rules.get('order') or []:
        st = (rules.get('stages') or {}).get(sid) or {}
        outs = st.get('outputs') or []
        covered = {o.get('file', '').split('/')[0] for o in outs}
        for folder in st.get('produces') or []:
            if folder not in covered:
                rows.append({'stage': sid, 'file': folder + '/', 'status': 'no-outputs', 'why': 'выходы папки не описаны (outputs)', 'consumers': []})
        for o in outs:
            row = {'stage': sid, 'file': o.get('file', ''), 'consumers': []}
            for key in ('terminal', 'report_only'):
                if key in o:
                    if str(o[key]).strip():
                        row.update(status=key, why=str(o[key]))
                    else:
                        row.update(status='orphan', why=f'{key} без причины')
                    break
            cons = o.get('consumers') or []
            for c in cons:
                ok, why = evidence(root, rules, sid, o, c)
                row['consumers'].append((str(c.get('stage')), c.get('via'), ok, why))
            if 'status' not in row:
                if not cons:
                    row.update(status='orphan', why='нет потребителя и не помечен terminal/report_only')
                elif all(c[2] for c in row['consumers']):
                    row.update(status='ok', why='')
                else:
                    row.update(status='unconfirmed', why='; '.join(f'{c[0]} ({c[1]}): {c[3]}' for c in row['consumers'] if not c[2]))
            rows.append(row)
    return rows


def check(root: str, rules: dict = None) -> list:
    """Предупреждения ORPHAN-OUTPUT (строки без префикса WARN)."""
    rows = analyse(root, rules or load(root))
    out = []
    for r in rows:
        if r['status'] in ('orphan', 'no-outputs'):
            out.append(f"ORPHAN-OUTPUT {r['stage']} {r['file']}: {r['why']}")
        elif r['status'] == 'unconfirmed':
            out.append(f"ORPHAN-OUTPUT {r['stage']} {r['file']}: потребитель не подтверждён — {r['why']}")
    return out


def summary(root: str, rules: dict = None) -> str:
    rows = analyse(root, rules or load(root))
    n = lambda s: sum(1 for r in rows if r['status'] == s)  # noqa: E731
    return (f"выходы этапов покраски: объявлено {len(rows)}, потребитель подтверждён {n('ok')}, terminal {n('terminal')}, report_only {n('report_only')}, "
            f"ORPHAN-OUTPUT {n('orphan') + n('no-outputs') + n('unconfirmed')} (предупреждение)")


def table(root: str, rules: dict = None) -> str:
    rows = analyse(root, rules or load(root))
    lines = ['| этап | файл | статус | кто читает → чем подтверждено |', '|---|---|---|---|']
    for r in rows:
        who = '; '.join(f"{c[0]} ({c[1]}) {'✔' if c[2] else '✘'} {c[3]}" for c in r['consumers']) or r['why']
        lines.append(f"| {r['stage']} | `{r['file']}` | {r['status']} | {who} |")
    return '\n'.join(lines)


def _selftest() -> int:
    import tempfile
    sys.path.insert(0, os.path.join(HERE, '..', 'scout'))
    import remlab_tmp
    remlab_tmp.use('stage_outputs_selftest')
    bad = 0

    def ok(c, name, extra=''):
        nonlocal bad
        print(('  ok  ' if c else '  FAIL ') + 'stage_outputs: ' + name + (f'  {extra}' if (extra and not c) else ''))
        bad += 0 if c else 1
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, 'tools/x'))
        open(os.path.join(d, 'tools/x/reader.py'), 'w').write("p = os.path.join(run, 'mask.png')\n")
        rules = {'order': ['a', 'b', 'c'], 'dynamic': {'pic': {'file_if_ok': ['a-out', 'pic.png'], 'fallback': 'photo'}},
                 'stages': {
                     'a': {'produces': ['a-out'], 'needs': [], 'steps': [{'argv': ['{py}', '{root}/tools/x/writer.py', '--out', '{glb_a}']}], 'outputs': [
                         {'file': 'a-out/pic.png', 'consumers': [{'stage': 'b', 'via': 'dynamic', 'key': 'pic'}]},
                         {'file': 'a-out/dangling.png', 'consumers': []},
                         {'file': 'a-out/frame.png', 'report_only': 'контрольный кадр'},
                         {'file': 'a-out/final.glb', 'terminal': 'итог, забирает публикация'},
                         {'file': 'a-out/nored.json', 'terminal': ' '},
                         {'file': 'a-out/mask.png', 'consumers': [{'stage': 'b', 'via': 'code', 'script': 'tools/x/reader.py'}]},
                         {'file': 'a-out/claimed.png', 'consumers': [{'stage': 'b', 'via': 'argv'}]},
                         {'file': 'a-out/back.png', 'consumers': [{'stage': 'a', 'via': 'argv'}]},
                         {'file': 'a-out/check.json', 'consumers': [{'stage': 'c', 'via': 'needs'}]},
                         {'file': 'a-out/half.png', 'consumers': [{'stage': 'b', 'via': 'code', 'script': 'tools/x/reader.py', 'pattern': 'mask.png'}, {'stage': 'c', 'via': 'argv'}]},
                         {'file': 'a-out/glb.glb', 'consumers': [{'stage': 'b', 'via': 'alias', 'alias': 'glb_a'}]}]},
                     'b': {'produces': ['b-out'], 'needs': [], 'steps': [{'argv': ['{py}', '{root}/tools/x/reader.py', '{pic}', '{glb_a}']}], 'outputs': []},
                     'c': {'produces': [], 'needs': ['a-out'], 'steps': [{'argv': ['{py}', 'z']}]}}}
        rows = {r['file']: r for r in analyse(d, rules)}
        ok(rows['a-out/pic.png']['status'] == 'ok', 'выход подан через dynamic и {pic} в argv — потребитель подтверждён')
        ok(rows['a-out/dangling.png']['status'] == 'orphan', 'выход без потребителя — ORPHAN-OUTPUT')
        ok(rows['a-out/frame.png']['status'] == 'report_only' and rows['a-out/final.glb']['status'] == 'terminal', 'report_only / terminal с причиной — не находка')
        ok(rows['a-out/nored.json']['status'] == 'orphan', 'terminal без причины — находка')
        ok(rows['a-out/mask.png']['status'] == 'ok', 'via code: имя файла найдено в скрипте из argv потребителя')
        ok(rows['a-out/claimed.png']['status'] == 'unconfirmed', 'потребитель заявлен, но пути нет в его argv — не подтверждён')
        ok(rows['a-out/back.png']['status'] == 'unconfirmed' and 'не после' in rows['a-out/back.png']['why'], 'потребитель не после производителя по order — не подтверждён')
        ok(rows['a-out/check.json']['status'] == 'ok', 'via needs: папка производителя в needs потребителя')
        ok(rows['a-out/glb.glb']['status'] == 'ok', 'via alias: {glb_a} в argv обоих этапов')
        ok(rows['b-out/']['status'] == 'no-outputs', 'папка produces без описанных выходов — находка')
        got = check(d, rules)
        ok(sum(1 for x in got if x.startswith('ORPHAN-OUTPUT')) == len(got) == 6, 'check(): ровно 6 предупреждений (dangling, nored, claimed, back, half, b-out)', str(got))
        ok(rows['a-out/half.png']['status'] == 'unconfirmed', 'два потребителя, один заявлен на словах — находка (подтверждённый другой её не гасит)')
        rules['stages']['a']['outputs'][1]['report_only'] = 'внутренний кэш'
        ok(not any('dangling' in x for x in check(d, rules)), 'после честной пометки report_only находка уходит (без исключений в коде)')
        open(os.path.join(d, 'tools/x/reader.py'), 'w').write('pass\n')
        ok({r['file']: r for r in analyse(d, rules)}['a-out/mask.png']['status'] == 'unconfirmed', 'скрипт больше не упоминает файл — via code больше не подтверждает')
        ok(summary(d, rules).startswith('выходы этапов покраски: объявлено'), 'summary строится')
    # случай урока 25.11 на РЕАЛЬНОМ описании: убрали подачу снятого фото в шаги 06 → выход 05 остаётся без потребителя
    import copy
    real = load(ROOT_DEFAULT)
    ok(not any('05-delight/delight.rgba.png' in x for x in check(ROOT_DEFAULT, real)), 'реальное описание: delight.rgba.png подан в 06 ({photo_vis}) — не находка')
    cut = copy.deepcopy(real)
    for st in cut['stages']['06']['steps']:
        st['argv'] = [a.replace('{photo_vis}', '{photo_cam}') for a in st['argv']]
    got = [x for x in check(ROOT_DEFAULT, cut) if '05-delight/delight.rgba.png' in x]
    ok(len(got) == 1 and 'не подтверждён' in got[0], '{photo_vis} убран из argv шагов 06 → delight.rgba.png: потребитель не подтверждён (ровно случай 05-delight)', str(got))
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    root = argv[argv.index('--root') + 1] if '--root' in argv else ROOT_DEFAULT
    if '--table' in argv:
        print(table(root))
        return 0
    for w in check(root):
        print('WARN ' + w)
    print(summary(root))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
