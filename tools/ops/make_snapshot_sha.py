#!/usr/bin/env python3
"""tools/ops/make_snapshot_sha.py — снимок кода Этажей ИЗ РЕПО ПО SHA (канон по вердикту Fable 28.11; билдер 1213 — snimok_rezerv.py, rab-9; в репо оформил rab-8).
Рядом: make_snapshot_sha_pravki.py (таблица правок путей, байт-в-байт snimok_pravki.py) и make_snapshot_sha_base.tsv — ЯВНЫЙ список файлов НЕ из репо
(путь в снимке · источник · путь источника · sha256): билдер берёт ровно их, у каждого сверяет sha256 (изменился — ОТКАЗ), посторонние файлы базовых папок игнорирует.
Список пересоздаёт только `--zapisat-spisok <файл.tsv>` (ревью — по git diff). Условия Fable 28.11: а) явный список, б) MANIFEST: строка на файл не из репо, в) тест детерминизма (tools/ops/tests/test_make_snapshot_sha.py).

Сборка ЖИВОГО СНИМКА кода Этажей, версия 2 (T-171/paket-zhivoe, rab-9, 28.11; решение директора+Fable, zadachi/snimok-paket-v2.md).

  python -I tools/ops/make_snapshot_sha.py <SHA> <новая-папка> [--repo ~/igor/remlab] [--base-2234 <папка>] [--base-2105 <папка>] [--list <tsv>] [--bez-pravok]
  python -I tools/ops/make_snapshot_sha.py --zapisat-spisok <новый.tsv> [--base-2234 …] [--base-2105 …]      # пересоздать список файлов не из репо

СОСТАВ (раскладка — как у снимка 2234, плоская: раннер берёт `--snap <папка>`, `import storozh` из корня, `floorplan/` рядом с overlay_status):
  • из `git archive <SHA>` репо: storozh.py, storozh_rules.json, ru_eval.py, ext.py (из tools/floorplan/etazhi/) и floorplan/{input_step,cleanup,apartment_cut}.py
    (из tools/floorplan/; ключ --floorplan 2234 берёт эти три из 2234 — они в репо ушли вперёд: входной шаг 4c отличается от проверенного экзаменом);
  • run_sb100.py — из снимка 20261127-2105 (причина в шапке: verdict из сторожа + overlay в guard — нужен пакету);
  • ВСЁ ОСТАЛЬНОЕ — из снимка 2234 побайтно, кроме замены пути папки снимка в .py/.sh/.mjs (как делал make_snapshot.py: путь старой папки → путь новой);
  • служебные файлы пишутся заново: FLOORPLAN-SHA.txt, KAK-ZAPUSKAT.md, SHA256SUMS (по копиям), SNIMOK.md (шапка: sha256 ВСЕХ файлов и источник каждого);
    не берутся: __pycache__, _selfcheck/, SELFCHECK.txt, SHA256SUMS-ORIGINALY (следы прежних прогонов/сборок).
Только чтение источников; пишет только в НОВУЮ папку (отказ: уже есть и не пуста; внутри ustroystvo/, внутри любого существующего снимка voronka/versii/). $0.
Код возврата: 0 собрано · 1 отказ с причиной."""
import argparse
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))      # python -I не добавляет папку скрипта
import make_snapshot_sha_pravki as snimok_pravki  # noqa: E402

W = os.path.expanduser('~/remlab-logs/etazhi-walls')
HERE = os.path.dirname(os.path.abspath(__file__))
SRC_TAGS = ('2234', '2234-sluzh', '2105', 'vneshniy')
TEXT_EXT = ('.py', '.sh', '.mjs')
SERVICE = {'FLOORPLAN-SHA.txt', 'KAK-ZAPUSKAT.md', 'SHA256SUMS', 'SHA256SUMS-ORIGINALY', 'SELFCHECK.txt', 'FAILED-SELFCHECK'}
SKIP_DIRS = {'__pycache__', '_selfcheck'}
REPO_MAP = [                                   # (путь в репо, путь в снимке)
    ('tools/floorplan/etazhi/storozh.py', 'storozh.py'),
    ('tools/floorplan/etazhi/storozh_rules.json', 'storozh_rules.json'),
    ('tools/floorplan/etazhi/ru_eval.py', 'ru_eval.py'),
    ('tools/floorplan/etazhi/ext.py', 'ext.py'),
]
FLOORPLAN_MAP = [('tools/floorplan/%s' % n, 'floorplan/%s' % n) for n in ('input_step.py', 'cleanup.py', 'apartment_cut.py',
                                                                          'quarter_turn.py', 'deskew_min.json')]      # резерв 74: cleanup читает deskew_min.json при импорте, input_step импортирует quarter_turn — оба рядом в плоском floorplan/
REASON_2105 = 'verdict из сторожа + overlay в guard — нужен пакету'


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def git(repo, *args, binary=False):
    p = subprocess.run(['git', '-C', repo] + list(args), capture_output=True, stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        raise RuntimeError('git %s: %s' % (' '.join(args[:2]), p.stderr.decode('utf-8', 'replace').strip()[:200]))
    return p.stdout if binary else p.stdout.decode('utf-8', 'replace').strip()


def repo_files(repo, sha, paths, skip_links=None):
    raw = git(repo, 'archive', sha, *paths, binary=True)
    out = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        for m in tf.getmembers():
            if m.isdir():
                continue
            if m.issym() and skip_links is not None and not m.name.startswith('/') and '..' not in m.name.split('/'):
                skip_links.append('%s -> %s' % (m.name, m.linkname))      # символьная ссылка — не копируем, перечисляем в шапке
                continue
            if not m.isreg() or m.name.startswith('/') or '..' in m.name.split('/'):
                raise RuntimeError('недопустимый элемент архива: %s' % m.name)
            out[m.name] = (tf.extractfile(m).read(), m.mode & 0o777)
    return out


def walk(base):
    out = []
    for dp, dn, fn in os.walk(base):
        dn[:] = sorted(d for d in dn if d not in SKIP_DIRS)
        for f in sorted(fn):
            rel = os.path.relpath(os.path.join(dp, f), base)
            if f.endswith('.pyc') or rel in SERVICE or f in SERVICE:
                continue
            out.append(rel)
    return out


CHAIN_ROOTS = ['clean_all', 'overlay_status', 'vetka_fit', 'storozh', 'ru_eval', 'vetka_a_eval', 'vetka_a_run', 'vetka_a_12', 'vetka_a_12d', 'nc_eval', 'vetka_a_cmp_bd',
               'fp_cmp', 'run_sb100', 'reader_v2', 'reader_v2b', 'opus_agent', 'ext', 'oblomki_feat', 'words_on_sheet', 'llm_gateway', 'input_step', 'cleanup', 'apartment_cut', 'ink_layers']


def import_closure(plan, roots):
    """статическое замыкание импортов (в т.ч. внутри функций) от корней цепочки по файлам СНИМКА (plan: путь → (байты, …)); → {модуль: путь в снимке}"""
    import ast
    search = ['', 'nc-models', 'tools/scout', 'tools/floorplan', 'tools/floorplan/etazhi', 'floorplan']

    def find(m):
        for d in search:
            for c in ((d + '/' if d else '') + m + '.py', (d + '/' if d else '') + m + '/__init__.py'):
                if c in plan:
                    return c
        return None
    seen, q = {}, list(roots)
    while q:
        m = q.pop()
        if m in seen:
            continue
        p = find(m)
        seen[m] = p
        if not p:
            continue
        try:
            t = ast.parse(plan[p][0].decode('utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for n in ast.walk(t):
            if isinstance(n, ast.Import):
                q.extend(a.name.split('.')[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                q.append(n.module.split('.')[0])
    return {m: p for m, p in seen.items() if p}


def sha_f(p):
    with open(p, 'rb') as f:
        return sha_b(f.read())


def load_list(path):
    """список файлов НЕ из репо: строки «путь в снимке TAB источник TAB путь источника TAB sha256»; # — комментарий"""
    rows = []
    with open(path, encoding='utf-8') as f:
        for ln in f.read().split('\n'):
            if not ln.strip() or ln.startswith('#'):
                continue
            c = ln.split('\t')
            if len(c) != 4 or c[1] not in SRC_TAGS or len(c[3]) != 64:
                raise RuntimeError('список %s: плохая строка «%s»' % (path, ln[:80]))
            rows.append(tuple(c))
    paths = [r[0] for r in rows]
    if len(set(paths)) != len(paths):
        raise RuntimeError('список %s: путь в снимке повторяется' % path)
    return rows


def resolve(tag, src, b34, b05):
    if tag in ('2234', '2234-sluzh'):
        return os.path.join(b34, src)
    if tag == '2105':
        return os.path.join(b05, src)
    return os.path.expanduser(src)


def take_base(rows, b34, b05, dest, plan):
    """берёт ровно файлы списка; sha256 источника не совпал / файла нет — RuntimeError. → (KAK-ZAPUSKAT.md базы 2234 в байтах, [(путь, источник, путь источника, sha256)])"""
    kak, notrepo = None, []
    for dst, tag, src, h in rows:
        p = resolve(tag, src, b34, b05)
        if not os.path.isfile(p):
            raise RuntimeError('нет файла списка: %s (нужен в снимок как %s)' % (p, dst))
        data = open(p, 'rb').read()
        if sha_b(data) != h:
            raise RuntimeError('файл изменился с момента записи списка: %s (sha256 %s, в списке %s) — пересоздать список `--zapisat-spisok` и показать diff' % (p, sha_b(data)[:12], h[:12]))
        if tag == '2234-sluzh':
            kak = data
            continue
        n = 0
        if tag in ('2234', '2105') and dst.endswith(TEXT_EXT):
            base = b34 if tag == '2234' else b05
            txt = data.decode('utf-8')
            n = txt.count(base)
            data = txt.replace(base, dest).encode('utf-8')
        label = {'2234': '2234', '2105': '20261127-2105: ' + REASON_2105}.get(tag, 'внешний: ' + p)
        plan[dst] = (data, os.stat(p).st_mode & 0o777, label, n)
        notrepo.append((dst, tag, p, h))
    if kak is None:
        raise RuntimeError('в списке нет строки KAK-ZAPUSKAT.md (источник 2234-sluzh)')
    return kak, notrepo


def zapisat_spisok(b34, b05, out):
    """пересоздать список: файлы базы 2234 (кроме приходящих из репо), run_sb100.py из 2105, внешние из snimok_pravki.externals(); sha256 — на момент записи"""
    repo_dest = {d for _, d in REPO_MAP + FLOORPLAN_MAP}
    home = os.path.expanduser('~')
    rows = []
    for rel in walk(b34):
        if rel in repo_dest or rel == 'run_sb100.py':
            continue
        rows.append((rel, '2234', rel, sha_f(os.path.join(b34, rel))))
    rows.append(('KAK-ZAPUSKAT.md', '2234-sluzh', 'KAK-ZAPUSKAT.md', sha_f(os.path.join(b34, 'KAK-ZAPUSKAT.md'))))
    rows.append(('run_sb100.py', '2105', 'run_sb100.py', sha_f(os.path.join(b05, 'run_sb100.py'))))
    for src_abs, rel in snimok_pravki.externals():
        src = '~' + src_abs[len(home):] if src_abs.startswith(home + '/') else src_abs
        rows.append((rel, 'vneshniy', src, sha_f(src_abs)))
    rows.sort()
    with open(out, 'w', encoding='utf-8') as f:
        f.write('# Файлы снимка НЕ из репо (явный список; make_snapshot_sha.py берёт ровно их). Колонки через TAB: путь в снимке · источник (2234 | 2234-sluzh | 2105 | vneshniy) · путь источника '
                '(2234/2105 — внутри базовой папки; vneshniy — абсолютный, ~ = домашняя) · sha256 источника ДО правки пути.\n')
        f.write('# Пересоздаёт только `make_snapshot_sha.py --zapisat-spisok`; изменение — ревью по git diff.\n')
        for r in rows:
            f.write('\t'.join(r) + '\n')
    print('СПИСОК ЗАПИСАН · %s · %d строк (2234 %d, 2105 1, внешних %d, служебный 1)' % (out, len(rows), sum(1 for r in rows if r[1] == '2234'), sum(1 for r in rows if r[1] == 'vneshniy')))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('sha', nargs='?')
    ap.add_argument('dest', nargs='?')
    ap.add_argument('--list', default=os.path.join(HERE, 'make_snapshot_sha_base.tsv'), help='явный список файлов не из репо (tsv)')
    ap.add_argument('--bez-pravok', action='store_true', help='ТОЛЬКО автотест: не применять правки путей (снимок не для боя, помечается в MANIFEST)')
    ap.add_argument('--zapisat-spisok', metavar='TSV', help='пересоздать список файлов не из репо и выйти')
    ap.add_argument('--repo', default=os.path.expanduser('~/igor/remlab'))
    ap.add_argument('--base-2234', default=W + '/voronka/versii/20261126-2234')
    ap.add_argument('--base-2105', default=W + '/voronka/versii/20261127-2105')
    ap.add_argument('--floorplan', choices=['repo'], default='repo', help='floorplan/ — из репо (решение директора)')
    a = ap.parse_args()
    if a.zapisat_spisok:
        return zapisat_spisok(os.path.abspath(os.path.expanduser(a.base_2234)), os.path.abspath(os.path.expanduser(a.base_2105)), os.path.abspath(os.path.expanduser(a.zapisat_spisok)))
    if not a.sha or not a.dest:
        ap.error('нужны <SHA> и <новая-папка> (или --zapisat-spisok)')

    dest = os.path.abspath(os.path.expanduser(a.dest))
    b34, b05 = os.path.abspath(os.path.expanduser(a.base_2234)), os.path.abspath(os.path.expanduser(a.base_2105))
    vers = os.path.join(W, 'voronka', 'versii') + '/'
    if (dest + '/').startswith(W + '/ustroystvo/'):
        print('ОТКАЗ · живая папка ustroystvo/ не трогается (%s)' % dest)
        return 1
    for b in (b34, b05):
        if (dest + '/').startswith(b + '/'):
            print('ОТКАЗ · папка назначения внутри существующего снимка %s' % b)
            return 1
    if (dest + '/').startswith(vers) and os.path.exists(dest):
        print('ОТКАЗ · существующий снимок voronka/versii/ не перезаписывается: %s' % dest)
        return 1
    if os.path.exists(dest) and (not os.path.isdir(dest) or os.listdir(dest)):
        print('ОТКАЗ · папка назначения уже есть и не пуста: %s (снимок — только в новую папку)' % dest)
        return 1
    for b in (b34, b05):
        if not os.path.isdir(b):
            print('ОТКАЗ · нет базового снимка %s' % b)
            return 1
    try:
        full = git(a.repo, 'rev-parse', '--verify', a.sha + '^{commit}')
    except RuntimeError as e:
        print('ОТКАЗ · SHA не коммит репо %s: %s' % (a.repo, e))
        return 1
    if len(a.sha) < 7:
        print('ОТКАЗ · SHA слишком короткий: %s' % a.sha)
        return 1
    rmap = REPO_MAP + (FLOORPLAN_MAP if a.floorplan == 'repo' else [])
    try:
        rf = repo_files(a.repo, full, [p for p, _ in rmap])
    except RuntimeError as e:
        print('ОТКАЗ · %s' % e)
        return 1
    miss = [p for p, _ in rmap if p not in rf]
    if miss:
        print('ОТКАЗ · в репо на %s нет файлов: %s' % (full[:9], ', '.join(miss)))
        return 1
    name = os.path.basename(dest.rstrip('/'))
    # --- план состава: (путь в снимке) → (байты, режим, источник, сколько раз заменён путь)
    plan = {}
    repo_dest = {d: p for p, d in rmap}
    try:
        rows = load_list(a.list)
        kak, notrepo = take_base(rows, b34, b05, dest, plan)
    except RuntimeError as e:
        print('ОТКАЗ · %s' % e)
        return 1
    over = sorted(set(plan) & set(repo_dest))
    if over:
        print('ОТКАЗ · файлы списка совпадают с приходящими из репо: %s' % ', '.join(over[:5]))
        return 1
    for rp, d in rmap:
        plan[d] = (rf[rp][0], rf[rp][1] or 0o644, 'репо %s:%s' % (full, rp), 0)
    # --- целиком из репо: tools/floorplan и tools/scout (байт-в-байт) — их берут nc_eval/ink_layers/vetka_a_run (решение директора ❓13)
    links = []
    try:
        for rp, (data, mode) in repo_files(a.repo, full, ['tools/floorplan', 'tools/scout', 'tools/ops/run_card.py', 'tools/ops/run_manifest.py'], skip_links=links).items():
            if rp in plan:
                print('ОТКАЗ · путь %s есть и в репо, и в списке файлов не из репо' % rp)
                return 1
            plan[rp] = (data, mode or 0o644, 'репо %s:%s' % (full, rp), 0)
    except RuntimeError as e:
        print('ОТКАЗ · %s' % e)
        return 1
    # --- внешние файлы (nc-models, раннер t176, planwalk) — уже взяты по списку (take_base)
    # --- правки путей (всё исполняемое — из снимка); исходный sha запоминаем
    pravki_log = []
    for rel in sorted([] if a.bez_pravok else snimok_pravki.PRAVKI):
        if rel not in plan:
            print('ОТКАЗ · правка для %s, а файла в составе снимка нет' % rel)
            return 1
        data, mode, src, nrep = plan[rel]
        try:
            new = snimok_pravki.apply(rel, data.decode('utf-8'), dest).encode('utf-8')
        except snimok_pravki.PravkaError as e:
            print('ОТКАЗ · правка пути не применилась: %s' % e)
            return 1
        pravki_log.append((rel, len(snimok_pravki.PRAVKI[rel]), sha_b(data), sha_b(new), src))
        plan[rel] = (new, mode, src + ' + правка пути', nrep)
    # --- запись
    os.makedirs(dest, exist_ok=True)
    for rel, (data, mode, _, _) in sorted(plan.items()):
        p = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(data)
        os.chmod(p, mode or 0o644)
    sums = [(sha_b(plan[r][0]), r) for r in sorted(plan)]
    bad = [r for h, r in sums if sha_b(open(os.path.join(dest, r), 'rb').read()) != h]
    if bad:
        print('ОТКАЗ · записанное на диск не совпало с планом: %s' % ', '.join(bad[:5]))
        return 1
    fp_rows = [(rp, d) for rp, d in FLOORPLAN_MAP]
    with open(os.path.join(dest, 'FLOORPLAN-SHA.txt'), 'w', encoding='utf-8') as f:
        f.write('репозиторий %s\nSHA %s\nфайлы floorplan/ — %s\n' % (a.repo, full, 'из репо на этом SHA' if a.floorplan == 'repo' else 'из снимка 2234 (не из репо)'))
        for rp, d in fp_rows:
            f.write('%s  %s\n' % (sha_b(plan[d][0]), rp))
    k34 = kak.decode('utf-8').replace(b34, dest)
    with open(os.path.join(dest, 'KAK-ZAPUSKAT.md'), 'w', encoding='utf-8') as f:
        f.write('# Снимок кода %s (собран из репо %s + база 2234) — состав и источник каждого файла: SNIMOK.md\n'
                'Ниже — инструкция запуска из снимка 2234 с путями этого снимка (текст прежний).\n\n%s' % (name, full[:9], k34))
    import json as _json
    rules = _json.loads(plan['storozh_rules.json'][0].decode('utf-8'))
    sw = []
    for k, v in rules.items():
        if isinstance(v, dict):
            if 'enabled' in v:
                sw.append((k, v['enabled']))
            for k2, v2 in v.items():
                if isinstance(v2, dict) and 'enabled' in v2:
                    sw.append(('%s.%s' % (k, k2), v2['enabled']))
        elif k not in ('_why',) and isinstance(v, (bool, str)):
            sw.append((k, v))
    mf = ['# MANIFEST снимка %s — что ВКЛЮЧЕНО и на каком коде (резерв 74, итоговая проверка; rab-9, 28.11)' % name,
          '- из репо по SHA %s (git archive; билдер make_snapshot.sha.py; storozh.py, ru_eval.py, ext.py, floorplan/, tools/floorplan, tools/scout, tools/ops/run_card.py, run_manifest.py — из репо; остальное — база 2234 / 2105 / внешние копии, см. SNIMOK.md)' % full,
          '- код: репо %s, SHA **%s** (origin/main на момент сборки; sha256 каждого файла — SNIMOK.md и SHA256SUMS)' % (a.repo, full),
          '- принятый набор сторожа (выключатели `storozh_rules.json` корня снимка; значения — как в репо, кроме строки «правки» ниже):']
    mf += ['  - `%s` = %s' % (k, str(v).lower() if isinstance(v, bool) else v) for k, v in sw]
    mf += ['- правки КОПИИ правил корня снимка (по решению задания; в репо файл прежний): `area_flag.enabled` false → **true**, `area_flag.module_dir` ".." → "tools/floorplan" (модуль внутри снимка). '
           'Флажок площади — отдельная строка справки «Пл» (k6, влит 0f1548d17); на исход листа и на звонки НЕ влияет; граница 0,2216532258064516, числа сверяет сам сторож (json ↔ модуль).',
           '- вход листа: `floorplan/{input_step,cleanup,apartment_cut,quarter_turn}.py` + `deskew_min.json` (порог доворота 5,0°) — код ЕСТЬ, флаги в самом снимке НЕ заданы (все FP_* по умолчанию выкл). '
           'Доворот ≥ 5° и четверть включает отдельный подготовительный шаг резерва (`~/remlab-logs/t171-rezerv74/dovorot_podgotovka.py`) переменными FP_CLEAN_DESKEW/_GUARD/_MIN5/_K6, FP_CLEAN_QUARTER/_AFTER; раннер экзамена input_step сам не зовёт.',
           '- Б-3: **ждёт оценки** на ~50 стенах — НЕ включён (строй без Б-3; включение — только после решения, отдельным снимком).',
           '- дверь правилом (T-171, ветка feat/t171-dver-pravilo, 91e895783): **не входит** (закрыта директором, в этом коде её нет).',
           '- не входит и не менялось: `ustroystvo/` (живое), `ZHIVOY`, прежние снимки (20261128-0400 и ранее).']
    if a.bez_pravok:
        mf.append('- БЕЗ ПРАВОК ПУТЕЙ (--bez-pravok, только автотест): снимок не для боя')
    mf.append('')
    mf.append('## Файлы НЕ из репо (%d): путь в снимке · источник · путь источника · sha256 источника до правки пути. Список — %s (sha256 %s)' % (
        len(notrepo), os.path.basename(a.list), sha_f(a.list)))
    mf += ['- %s · %s · %s · %s' % r for r in sorted(notrepo)]
    with open(os.path.join(dest, 'MANIFEST.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(mf) + '\n')
    service = ['FLOORPLAN-SHA.txt', 'KAK-ZAPUSKAT.md', 'MANIFEST.md']
    svc_sums = [(sha_b(open(os.path.join(dest, s), 'rb').read()), s) for s in service]
    allsums = sorted(sums + svc_sums, key=lambda x: x[1])
    with open(os.path.join(dest, 'SHA256SUMS'), 'w', encoding='utf-8') as f:
        f.write(''.join('%s  %s\n' % (h, r) for h, r in allsums))
    try:
        branches = git(a.repo, 'branch', '-r', '--contains', full).replace('\n', ' ').strip()
    except RuntimeError:
        branches = ''
    subj = git(a.repo, 'log', '-1', '--format=%s', full)
    repl = sorted((r, v[3]) for r, v in plan.items() if v[3])
    n_src = {}
    for v in plan.values():
        k = v[2].split(':')[0].split(' ')[0]
        n_src[k] = n_src.get(k, 0) + 1
    with open(os.path.join(dest, 'SNIMOK.md'), 'w', encoding='utf-8') as f:
        f.write('# Снимок кода Этажей v2 — %s\n\n' % name)
        f.write('- СНИМОК КОДА: %s (%d файлов + служебных 3; база воронки — снимок 2234; из репо %d, из 2105 %d, из 2234 %d, внешних копий %d; правок путей в %d файлах)\n' % (
            name, len(plan), n_src.get('репо', 0), n_src.get('20261127-2105', 0), n_src.get('2234', 0), n_src.get('внешний', 0), len(pravki_log)))
        f.write('- из репо по SHA %s · «%s»\n' % (full, subj[:160]))
        f.write('- в ветках origin: %s\n' % (branches or 'НИ В ОДНОЙ (не запушен)'))
        f.write('- база 2234: %s\n- база 20261127-2105: %s (взят только run_sb100.py — %s)\n' % (b34, b05, REASON_2105))
        f.write('- floorplan/: %s\n' % ('из репо на SHA (в репо ушёл вперёд от 2234 — вход 4c отличается!)' if a.floorplan == 'repo' else 'из 2234'))
        f.write('- собран: %s UTC (= Лондон зимой) · репо %s · живое ustroystvo/, 2234, 20261127-2105 не тронуты (только чтение)\n' % (
            time.strftime('%Y-%m-%d %H:%M', time.gmtime()), a.repo))
        f.write('- путь папки заменён (старая папка снимка → эта) в %d файлах: %s\n' % (
            len(repl), '; '.join('%s ×%d' % (r, n) for r, n in repl) or '—'))
        f.write('- символьные ссылки репо (не копируются, не исполняются цепочкой): %s\n' % ('; '.join(links) or 'нет'))
        f.write('- не взято: __pycache__, _selfcheck/, SELFCHECK.txt, SHA256SUMS-ORIGINALY (следы прежних сборок); из 2105 — все файлы кроме run_sb100.py\n')
        f.write('- формат строки: sha256  путь  |  источник\n')
        f.write('- ИСПОЛНЯЕМЫЕ файлы снимка — строки ниже (хешируются снимочные копии); читаемое МИМО снимка — отдельный раздел «ВНЕ СНИМКА» в конце\n\n')
        for h, r in allsums:
            src = plan[r][2] if r in plan else 'служебный: сгенерирован сборкой'
            f.write('%s  %s  |  %s\n' % (h, r, src))
        f.write('\n## ПРАВКИ ПУТЕЙ в копиях (всё исполняемое — из снимка, запасного пути наружу нет; только пути, логика не меняется) — таблица в snimok_pravki.py\n')
        f.write('Формат: файл · число правок · sha256 источника ДО правки → sha256 в снимке ПОСЛЕ · откуда\n')
        for rel, n, h0, h1, srcp in pravki_log:
            f.write('- %s · %d · %s → %s · %s\n' % (rel, n, h0, h1, srcp))
        home = os.path.expanduser('~')
        # --- выбор версий (решения директора ❓14–❓16): всё считается по файлам снимка
        import difflib
        import re as _re
        ag_repo = plan.get('tools/floorplan/opus_agent.py', (None,))[0]
        ag_t176 = home + '/remlab-logs/t176/ekz/floorplan/opus_agent.py'
        try:
            ag_b = open(ag_t176, 'rb').read()
        except OSError:
            ag_b = None
        if ag_b and ag_repo:
            ud = [x for x in difflib.unified_diff(ag_b.decode('utf-8').splitlines(), ag_repo.decode('utf-8').splitlines(), lineterm='', n=0) if x[:1] in '+-' and x[:3] not in ('+++', '---')]
            nd = '%d строк отличий (+%d репо / −%d t176)' % (len(ud), sum(1 for x in ud if x[0] == '+'), sum(1 for x in ud if x[0] == '-'))
        else:
            nd = 'сравнить не удалось'
        f.write('\n## ВЫБОР ВЕРСИЙ (решения директора ❓14–❓16, 28.11)\n')
        f.write('- ❓14 opus_agent.py: В СНИМКЕ — версия репо (`tools/floorplan/opus_agent.py`, sha256 %s); раннер запускать с `--agent-dir <эта папка>/tools/floorplan`. '
                't176-копия экзамена %s (%s): %s. Раскладка (rab-9, OTCHET.md «СНИМОК v2»): все отличия — страж недели/лимит (допуск `OPUS_AGENT_WEEK_ALLOW`, потолок `OPUS_AGENT_WEEK_HARD`, журнал допуска); '
                'запрос, вызов модели и разбор ответа — побайтно те же. Без этих двух переменных окружения — поведение прежнее.\n' % (
                    sha_b(ag_repo) if ag_repo else 'НЕТ', sha_b(ag_b) if ag_b else 'НЕТ', ag_t176, nd))
        fpn, dflt, sets = set(), {}, []
        for p in ('floorplan/input_step.py', 'floorplan/cleanup.py', 'floorplan/apartment_cut.py', 'tools/floorplan/quarter_turn.py'):
            if p in plan:
                txt = plan[p][0].decode('utf-8', 'replace')
                fpn.update(_re.findall(r"'(FP_[A-Z_]+)'", txt))
                for mm in _re.finditer(r"environ\.get\([^,()]+,\s*'([^']*)'\)", txt):
                    dflt[mm.group(1)] = dflt.get(mm.group(1), 0) + 1
        for p, v in sorted(plan.items()):
            if p.startswith(('tools/', 'floorplan/', 'planwalk-src/')) or not p.endswith(('.py', '.sh')):
                continue
            for i, ln in enumerate(v[0].decode('utf-8', 'replace').splitlines(), 1):
                if 'FP_' in ln and not ln.lstrip().startswith('#') and ('environ' in ln or 'export' in ln):
                    sets.append('%s:%d' % (p, i))
        ov = plan.get('overlay_status.py')
        runcall = next((ln.strip() for ln in ov[0].decode('utf-8').splitlines() if 'input_step.run(' in ln and not ln.lstrip().startswith('#')), 'не найден') if ov else 'нет'
        f.write('- ❓15 floorplan/ (вход 4c) — из репо. Флаги шагов (чтение `os.environ.get(<флаг>, <умолчание>)`): %s; найденные умолчания: %s — %s. '
                'ВАЖНО: `FP_INPUT_ALL=1` включает все шаги кроме quarter, в том числе новый deskew. Цепочка раннера задаёт FP_* в: %s. '
                'Вызов входа в overlay_status: `%s` — deskew/quarter в нём не заданы → ВЫКЛ. Новое в репо против 2234 (deskew, quarter, шаги в steps) под этими выключателями; без флага вход побайтно как у 2234 (сверка на листах — OTCHET.md).\n' % (
                    ', '.join(sorted(fpn)) or 'не найдены', ', '.join('«%s»×%d' % kv for kv in sorted(dflt.items())) or 'нет',
                    'все выкл' if set(dflt) <= {'0'} else 'ЕСТЬ умолчание ≠ 0 — проверить!', '; '.join(sets) or 'нигде (кроме floorplan/)', runcall[:200]))
        clo = import_closure(plan, CHAIN_ROOTS)
        sm = sorted(m for m, p in clo.items() if p.startswith('tools/scout/'))
        oh = [p for m, p in sorted(clo.items()) if any('occupancy' in x and not x.lstrip().startswith('#') for x in plan[p][0].decode('utf-8', 'replace').splitlines())]
        f.write('- ❓16 tools/scout/occupancy.json (симлинк репо → ../../services/planner-solver/rules/occupancy.json): замыкание импортов цепочки — %d модулей, из tools/scout %d (%s); '
                'упоминаний occupancy в них: %d%s → %s.\n' % (
                    len(clo), len(sm), ' '.join(sm), len(oh), (' (' + ', '.join(oh) + ')') if oh else '',
                    'НЕ ЧИТАЕТСЯ цепочкой (статический разбор; динамических импортов не ловит)' if not oh else 'ЧИТАЕТСЯ — файл надо положить целью, а не ссылкой'))
        st_fp = plan.get('tools/floorplan/etazhi/storozh.py', (None,))[0]
        st_root = plan.get('storozh.py', (None,))[0]
        f.write('\n## ПЕРЕМЕНЫ FLOORPLAN БЕЗ ФЛАГА (поимённо; решение Fable 28.11 ~03:45) и сверки сборки\n')
        f.write('- 1) `tools/floorplan/input_step.py` (и копия `floorplan/input_step.py`): `run()` возвращает 2 лишних ключа в ответе — `deskew_deg`, `quarter_k` — на КАЖДОМ листе, флаг не нужен (пиксели, ops, steps, cut — как у 2234: сверка 8 листов, OTCHET.md).\n')
        f.write('- 2) `FP_INPUT_ALL=1` теперь включает и новый шаг deskew (раньше — rect/bg/grid/lines/layers/cut) — только при этом флаге; раннер его не ставит, вход 4c в overlay_status задаёт флаги явно (только lines). В окружении живого `FP_INPUT_ALL` НЕ ставить.\n')
        f.write('- сверка storozh.py: `tools/floorplan/etazhi/storozh.py` sha256 %s (ожидалось 91f4a2f2… — %s); `storozh.py` в корне снимка (тот же файл с правкой пути на эту папку) %s\n' % (
            sha_b(st_fp) if st_fp else 'НЕТ', 'СОВПАДАЕТ' if st_fp and sha_b(st_fp).startswith('91f4a2f2') else 'НЕ СОВПАДАЕТ — СТОП', sha_b(st_root)[:12] if st_root else 'НЕТ'))
        f.write('- ❓16 «occupancy.json не читается цепочкой» верно только пока в снимке нет путей наружу: сборка не пишет sys.path/запасных путей на живые папки (правки путей — таблица ПРАВКИ ПУТЕЙ), '
                'проверка `import_test.py` (все модули цепочки лежат внутри снимка) и −контроль (импорт модуля, которого в снимке нет → ModuleNotFoundError, не молчаливое чтение из живой папки) — результат в OTCHET.md.\n')
        f.write('\n## ВНЕ СНИМКА — читается МИМО снимка (НЕ воспроизводится этим снимком; sha256 на момент сборки)\n')
        f.write('Честная пометка: код ниже снимок не фиксирует — изменится файл/данные, изменится поведение прогона.\n')
        node = home + '/.nvm/versions/node/v22.23.3/bin/node'
        try:
            f.write('- node22: %s · sha256 бинарника %s\n' % (node, sha_b(open(node, 'rb').read())))
        except OSError:
            f.write('- node22: НЕТ ФАЙЛА %s\n' % node)
        f.write('- данные (вне снимка по замыслу): voronka/run, voronka/vlm, voronka/vlm2, nc-models/ru/out, nc-models/vetka-a, ru-plans, floorplan-bench, floorplan/gold репо — пути в коде живые\n')
        f.write('- ключи и .env: tools/scout/env_keys.py читает .env/ACCESS из репо и окружения (вне снимка; сами ключи не хешируются и не копируются)\n')
        f.write('- venv (planner / scout / nc-models) и пакеты в них (shapely, rapidocr, PIL, cv2, numpy…) — версии не фиксируются снимком\n')
        f.write('- не правилось сознательно: storozh.py `U = W + "/ustroystvo"` — папка вывода CLI `storozh run/selftest`, раннер её не использует (импортирует S.* функции)\n')
    print('СОБРАНО · %s · %d файлов (+служебных 3) · SHA %s · из репо %d / 2105 %d / 2234 %d · %s' % (
        dest, len(plan), full[:9], n_src.get('репо', 0), n_src.get('20261127-2105', 0), n_src.get('2234', 0),
        'в origin: ' + branches if branches else 'НЕ в origin (не запушен)'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
