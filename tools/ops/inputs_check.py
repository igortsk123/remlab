#!/usr/bin/env python3
"""ВХОДЫ НАБОРОВ ТОВАРОВ: копии вне ~/remlab-logs + проверка «пути существуют, sha совпадает» (T-20261125-75/2, правило (4) разбора T-75).

ЗАЧЕМ. 24.11 в 05:23 кто-то руками перенёс папку ~/remlab-logs/t94-1119 на HDD — и вход комода 112923_13224664101879413845 (`…hd.rgba.png`) пропал из
37 списков прогонов; товар выпал из кругов «на 29» (р.3, р.5). Входы набора не должны жить в папках логов, которые переносят, чистят и прореживают.

ЧТО ЭТО. `~/remlab-inputs/<набор>/` — КОПИИ (не ссылки): photo/<sku>.hd.rgba.png (то, что круг получает как @in/photo.png), card/<sku>.card.json (карточка 07),
glb/<sku>-hd.glb (форма из этапа 02), other/… (другие версии того же входа, строкой «другая версия»), и MANIFEST.tsv: sku, kind, file, sha256, source, note.
Папку `~/remlab-inputs` не трогают ни `logs_archive.py` (отказ, `protected`), ни `--prune-hdd`, ни автоочистка, ни рабочие.

КОМАНДЫ (правила — tools/scout/rules/input-sets.json; сухо/читающая по умолчанию):
  python3 tools/ops/inputs_check.py                 # проверить все наборы: каждая строка MANIFEST — файл есть (копия, не ссылка), sha256 тот же; в наборе `expect` товаров,
                                                    # у каждого photo+card+glb; ПО СПИСКАМ ПРОГОНОВ круга (`lists`): все пути входов (glb, photo, pose_run, extra_in.*) существуют,
                                                    # а glb/photo.png/card.json имеют тот же sha, что копия («гонит другую версию» — ❗). Код 0 — чисто, 1 — есть ❗, 2 — не разобрать правила.
  python3 tools/ops/inputs_check.py --set set29     # один набор
  python3 tools/ops/inputs_check.py --json          # машинно
  python3 tools/ops/inputs_check.py --build set29   # СОЗДАТЬ копии из списков `lists` (+ `also` — другие версии) и MANIFEST.tsv. Ничего не перезаписывает: файл на месте с другим sha — ❗ отказ,
                                                    # тот же sha — оставляет; MANIFEST уже есть — ДОПИСЫВАЕТ строки новых файлов (существующие строки не меняет, другой sha у строки — ❗).
СПИСКИ СТРОК КРУГА И «ДО» (T-20261125-75/4): `copy_lists` — списки `inputs-q*.json` круга копируются в `<набор>/lists/<круг>/` (loop5.json `shard_inputs_glob` смотрит туда, а не в ~/remlab-logs);
`copy_base` — файлы «до» (06-visible, 07-fill, 08-material) каждого товара копируются в `<набор>/base/<шард>/<товар>/…` (loop5.json `base_root` смотрит туда). Всё — строками MANIFEST (kind list / base),
sha проверяется; `lists` правила — это КОПИИ (по ним проверка путей); список копии не закреплён в MANIFEST — ❗; у товара нет файла из `copy_base.need` — ❗.
ПОЗА (T-20261125-75/5): `copy_pose` — из `pose_run` каждого товара списка копируются только файлы камеры этапа 4, что читает круг (`files`), в `<набор>/pose/<товар>/…` (kind pose); loop5.load_rows
подставляет `pose_run` на эту копию (списки не меняются); у товара нет файла из `copy_pose.need` — ❗.
Новый круг: добавить его список в `copy_lists` (и `lists`) правила (иначе проверка его не видит). Правила — в json, не в коде; env: INPUTS_CHECK_RULES (другой файл правил), INPUTS_ROOT (другой корень — тесты).
Без чтения секретов, без сети, без платного."""
from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
RULES_PATH = os.path.join(ROOT, 'tools', 'scout', 'rules', 'input-sets.json')
KINDS = ('photo', 'card', 'glb')            # основные входы: по одному на товар
HEADER = ['sku', 'kind', 'file', 'sha256', 'source', 'note']
DEST = {'photo': 'photo/{sku}.hd.rgba.png', 'card': 'card/{sku}.card.json', 'glb': 'glb/{sku}-hd.glb'}


def rules() -> dict:
    p = os.environ.get('INPUTS_CHECK_RULES') or RULES_PATH
    with open(p, encoding='utf-8') as f:
        r = json.load(f)
    r['root'] = os.path.expanduser(os.environ.get('INPUTS_ROOT') or r.get('root') or '~/remlab-inputs')
    r.setdefault('sets', {})
    return r


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _x(p: str) -> str:
    return os.path.expanduser(p)


def read_manifest(path: str) -> tuple[list, list]:
    """(строки-словари, ❗ разбора)."""
    rows, bad = [], []
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.read().split('\n')
    except OSError as e:
        return [], [f'нет MANIFEST {path}: {e.strerror}']
    if not lines or lines[0].split('\t') != HEADER:
        return [], [f'MANIFEST {path}: первая строка должна быть «{chr(9).join(HEADER)}»']
    for i, ln in enumerate(lines[1:], 2):
        if not ln.strip():
            continue
        c = ln.split('\t')
        if len(c) != len(HEADER):
            bad.append(f'MANIFEST строка {i}: {len(c)} колонок вместо {len(HEADER)}')
            continue
        rows.append(dict(zip(HEADER, c)))
    return rows, bad


def list_entries(globs: list) -> tuple[dict, list]:
    """{sku: [(файл списка, запись)]}, ❗ (шаблон без файлов / не разобрать)."""
    out, bad = {}, []
    for pat in globs:
        fs = sorted(glob.glob(_x(pat)))
        if not fs:
            bad.append(f'список не найден: {pat}')
        for f in fs:
            try:
                d = json.load(open(f, encoding='utf-8'))
            except (OSError, ValueError) as e:
                bad.append(f'список {f}: не разобрать ({e})')
                continue
            if not isinstance(d, dict):
                bad.append(f'список {f}: не словарь {{sku: запись}}')
                continue
            for sku, v in d.items():
                if isinstance(v, dict):
                    out.setdefault(sku, []).append((f, v))
    return out, bad


def entry_paths(v: dict) -> list:
    """[(метка, путь, вид для sha | None)] — все пути-входы записи списка прогона."""
    ei = v.get('extra_in') or {}
    res = []
    if v.get('glb'):
        res.append(('glb', v['glb'], 'glb'))
    if v.get('photo'):
        res.append(('photo', v['photo'], None))                 # копия кадра в папке прогона — только «есть»
    if v.get('pose_run'):
        res.append(('pose_run', v['pose_run'], None))
    for name, p in ei.items():
        kind = 'photo' if name == 'photo.png' else 'card' if name == 'card.json' else None
        res.append((f'extra_in.{name}', p, kind))
    return res


def check_set(name: str, cfg: dict, root: str) -> tuple[list, dict]:
    """(❗-строки, статистика)."""
    probs = []
    sdir = os.path.join(root, name)
    mpath = os.path.join(root, cfg.get('manifest') or f'{name}/MANIFEST.tsv')
    rows, bad = read_manifest(mpath)
    probs += bad
    main = {}                                                   # sku -> kind -> sha
    other = {}                                                  # sku -> sha -> note
    nfiles = 0
    for r in rows:
        f = os.path.normpath(os.path.join(sdir, r['file']))
        if not (f == sdir or f.startswith(sdir + os.sep)):
            probs.append(f'{r["sku"]} {r["kind"]}: файл {r["file"]} вне папки набора')
            continue
        nfiles += 1
        if os.path.islink(f):
            probs.append(f'{r["sku"]} {r["kind"]}: {r["file"]} — ссылка, а не копия')
            continue
        if not os.path.isfile(f):
            probs.append(f'{r["sku"]} {r["kind"]}: нет файла {r["file"]}')
            continue
        got = sha256(f)
        if got != r['sha256']:
            probs.append(f'{r["sku"]} {r["kind"]}: sha256 не совпал ({r["file"]}: {got[:12]}… вместо {r["sha256"][:12]}…)')
        if r['kind'] in KINDS:
            if r['kind'] in main.setdefault(r['sku'], {}):
                probs.append(f'{r["sku"]}: два основных {r["kind"]} в MANIFEST')
            main[r['sku']][r['kind']] = r['sha256']
        else:
            other.setdefault(r['sku'], {})[r['sha256']] = r.get('note') or r['kind']
    exp = cfg.get('expect')
    if rows and exp is not None and len(main) != int(exp):
        probs.append(f'в наборе {len(main)} товаров вместо {exp}')
    for sku, m in sorted(main.items()):
        miss = [k for k in KINDS if k not in m]
        if miss:
            probs.append(f'{sku}: нет в MANIFEST основных входов: {", ".join(miss)}')
    entries, bad = list_entries(cfg.get('lists') or [])
    probs += bad
    mfiles = {os.path.normpath(os.path.join(sdir, r['file'])) for r in rows}
    for pat in cfg.get('lists') or []:
        for f in sorted(glob.glob(_x(pat))):
            if os.path.normpath(f).startswith(sdir + os.sep) and os.path.normpath(f) not in mfiles:
                probs.append(f'список {os.path.relpath(f, sdir)} лежит в наборе, но его нет в MANIFEST (sha не закреплён)')
    for kind, key, what in (('base', 'copy_base', '«до»'), ('pose', 'copy_pose', 'позы')):
        need = (cfg.get(key) or {}).get('need') or []
        if rows and need:
            for sku in sorted(main):
                for rel in need:
                    if not any(r['kind'] == kind and r['sku'] == sku and r['file'].endswith(f'/{sku}/{rel}') for r in rows):
                        probs.append(f'{sku}: нет {what} {rel} в MANIFEST (kind {kind})')
    npaths = 0
    for sku, lst in sorted(entries.items()):
        if rows and sku not in main:
            probs.append(f'{sku}: есть в списке прогонов, но нет в наборе')
        for lf, v in lst:
            lrel = os.path.relpath(lf, _x('~/remlab-logs')) if lf.startswith(_x('~/remlab-logs')) else lf
            for label, p, kind in entry_paths(v):
                npaths += 1
                p = _x(p)
                if not os.path.exists(p):
                    probs.append(f'{sku} [{lrel}] {label}: пути нет — {p}' + (' (висячая ссылка)' if os.path.islink(p) else ''))
                    continue
                if kind and os.path.isfile(p) and sku in main and kind in main[sku]:
                    got = sha256(p)
                    if got != main[sku][kind]:
                        note = other.get(sku, {}).get(got)
                        probs.append(f'{sku} [{lrel}] {label}: гонит ДРУГУЮ версию {kind} ({got[:12]}… ≠ копия {main[sku][kind][:12]}…)' + (f' — это «{note}»' if note else ''))
    return probs, {'sku': len(main), 'files': nfiles, 'list_paths': npaths, 'lists_skus': len(entries)}


def build_set(name: str, cfg: dict, root: str) -> tuple[list, list]:
    """Копии из списков `lists` + `also`; MANIFEST — только если его нет. (❗, строки-сообщения). Ничего не перезаписывает."""
    probs, msgs = [], []
    sdir = os.path.join(root, name)
    mpath = os.path.join(root, cfg.get('manifest') or f'{name}/MANIFEST.tsv')
    cl = cfg.get('copy_lists') or []
    entries, bad = list_entries([c['src'] for c in cl] or cfg.get('lists') or [])      # источник входов — списки круга в логах (копии `lists` появятся после первой сборки)
    probs += bad
    plan = []                                                   # (sku, kind, dest-rel, source, note)
    for sku in sorted(entries):
        v = entries[sku][-1][1]                                 # последняя запись (списки отсортированы по имени) — что гнали в круге
        ei = v.get('extra_in') or {}
        src = {'photo': ei.get('photo.png'), 'card': ei.get('card.json'), 'glb': v.get('glb')}
        for k in KINDS:
            if not src[k]:
                probs.append(f'{sku}: в списке нет входа {k}')
                continue
            plan.append((sku, k, DEST[k].format(sku=sku), src[k], ''))
    for c in cl:
        for f in sorted(glob.glob(_x(c['src']))):
            plan.append(('*', 'list', f"{c['dest'].rstrip('/')}/{os.path.basename(f)}", f, c.get('note') or 'список строк круга (копия)'))
    cb = cfg.get('copy_base')
    if cb:
        root_b = next((_x(s) for s in cb['src'] if os.path.isdir(_x(s))), None)
        if not root_b:
            probs.append('«до»: ни одной папки из copy_base.src нет: ' + ', '.join(cb['src']))
        else:
            for sku in sorted(entries):
                got = set()
                for d in sorted(glob.glob(os.path.join(root_b, '*', sku))):
                    shard = os.path.basename(os.path.dirname(d))
                    for rel in cb['files']:
                        if os.path.isfile(os.path.join(d, rel)):
                            got.add(rel)
                            plan.append((sku, 'base', f"{cb['dest'].rstrip('/')}/{shard}/{sku}/{rel}", os.path.join(d, rel), f'до: {shard}'))
                for rel in cb.get('need') or []:
                    if rel not in got:
                        probs.append(f'{sku}: «до» {rel} нет в {root_b}')
    cp = cfg.get('copy_pose')
    if cp:
        for sku in sorted(entries):
            pr = _x(entries[sku][-1][1].get('pose_run') or '')
            if not os.path.isdir(pr):
                probs.append(f'{sku}: pose_run нет папкой — {pr or "(пусто)"}')
                continue
            got = set()
            for rel in cp['files']:
                if os.path.isfile(os.path.join(pr, rel)):
                    got.add(rel)
                    plan.append((sku, 'pose', f"{cp['dest'].rstrip('/')}/{sku}/{rel}", os.path.join(pr, rel), f'поза: {pr}'))
            for rel in cp.get('need') or []:
                if rel not in got:
                    probs.append(f'{sku}: поза {rel} нет в {pr}')
    for a in cfg.get('also') or []:
        plan.append((a['sku'], a.get('kind') or 'other', a['dest'], a['path'], a.get('note') or 'другая версия'))
    out_rows = []
    for sku, kind, rel, src, note in plan:
        s = _x(src)
        dest = os.path.join(sdir, rel)
        if not os.path.isfile(s):
            probs.append(f'{sku} {kind}: источника нет — {s}')
            continue
        want = sha256(s)
        if os.path.lexists(dest):
            if os.path.islink(dest) or not os.path.isfile(dest) or sha256(dest) != want:
                probs.append(f'{sku} {kind}: {rel} уже есть и отличается — не перезаписываю')
                continue
            msgs.append(f'  есть {rel}')
        else:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + '.part'
            shutil.copyfile(s, tmp)
            if sha256(tmp) != want:
                os.remove(tmp)
                probs.append(f'{sku} {kind}: копия не совпала по sha — удалена временная, повторить')
                continue
            os.replace(tmp, dest)
            msgs.append(f'  скопировано {rel} ({os.path.getsize(dest)} Б)')
        out_rows.append({'sku': sku, 'kind': kind, 'file': rel, 'sha256': want, 'source': s, 'note': note})
    if os.path.lexists(mpath):
        old, bad_m = read_manifest(mpath)
        probs += bad_m
        have = {r['file']: r for r in old}
        new = []
        for r in out_rows:
            o = have.get(r['file'])
            if o is None:
                new.append(r)
            elif o['sha256'] != r['sha256'] or o['sku'] != r['sku'] or o['kind'] != r['kind']:
                probs.append(f'{r["sku"]} {r["kind"]}: строка MANIFEST для {r["file"]} отличается — не переписываю')
        if new and not probs:
            with open(mpath, 'a', encoding='utf-8') as f:
                for r in sorted(new, key=lambda r: (r['sku'], r['kind'], r['file'])):
                    f.write('\t'.join(r[h] for h in HEADER) + '\n')
            msgs.append(f'MANIFEST дополнен: {mpath} (+{len(new)} строк; прежние не менялись)')
        elif new:
            msgs.append('MANIFEST не дополнен: есть ❗ выше — исправить и повторить --build')
        else:
            msgs.append(f'MANIFEST уже есть ({mpath}), новых файлов нет — не пишу; сверка: python3 tools/ops/inputs_check.py --set {name}')
    elif out_rows and not probs:
        os.makedirs(os.path.dirname(mpath), exist_ok=True)
        with open(mpath, 'w', encoding='utf-8') as f:
            f.write('\t'.join(HEADER) + '\n')
            for r in sorted(out_rows, key=lambda r: (r['sku'], r['kind'], r['file'])):
                f.write('\t'.join(r[h] for h in HEADER) + '\n')
        msgs.append(f'MANIFEST записан: {mpath} ({len(out_rows)} строк)')
    elif out_rows:
        msgs.append('MANIFEST не записан: есть ❗ выше — исправить и повторить --build')
    return probs, msgs


class InputsError(Exception):
    """Вход набора не прочитать (нет набора/MANIFEST/файла) — строитель списка круга останавливается, а не берёт путь из ~/remlab-logs."""


def set_inputs(name: str) -> dict:
    """{sku: {'photo': путь, 'card': путь, 'glb': путь}} — ОСНОВНЫЕ входы набора из MANIFEST (абсолютные пути копий в ~/remlab-inputs).
    Для строителей списков круга (loop5.py, make_inputs_07.py): новые круги на 29 берут входы ОТСЮДА, а не из папок логов (T-20261125-75/3).
    Нет набора в правилах / MANIFEST / файла копии — InputsError (тихого отката на логи нет: из-за него 24.11 вход комода пропал из кругов)."""
    try:
        r = rules()
    except (OSError, ValueError) as e:
        raise InputsError(f'правила наборов не прочитать: {e}')
    if name not in r['sets']:
        raise InputsError(f'набор {name!r} не описан в {RULES_PATH}')
    cfg = r['sets'][name]
    sdir = os.path.join(r['root'], name)
    rows, bad = read_manifest(os.path.join(r['root'], cfg.get('manifest') or f'{name}/MANIFEST.tsv'))
    if bad or not rows:
        raise InputsError(f'набор {name}: ' + ('; '.join(bad) or 'MANIFEST пуст') + ' — python3 tools/ops/inputs_check.py --build ' + name)
    out: dict = {}
    for row in rows:
        if row['kind'] not in KINDS:
            continue
        f = os.path.normpath(os.path.join(sdir, row['file']))
        if not (f.startswith(sdir + os.sep) and os.path.isfile(f)):
            raise InputsError(f'набор {name}: нет файла входа {row["sku"]} {row["kind"]}: {f} — python3 tools/ops/inputs_check.py --set {name}')
        out.setdefault(row['sku'], {})[row['kind']] = f
    return out


def set_pose(name: str) -> dict:
    """{sku: папка позы} — копии `pose_run` в наборе (`<набор>/pose/<товар>`), если у набора есть `copy_pose`; нет — {} (подмены нет).
    Нет файла из `copy_pose.need` у товара из MANIFEST — InputsError (тихого отката на ~/remlab-logs нет)."""
    try:
        r = rules()
    except (OSError, ValueError) as e:
        raise InputsError(f'правила наборов не прочитать: {e}')
    cfg = r['sets'].get(name) or {}
    cp = cfg.get('copy_pose')
    if not cp:
        return {}
    sdir = os.path.join(r['root'], name)
    rows, bad = read_manifest(os.path.join(r['root'], cfg.get('manifest') or f'{name}/MANIFEST.tsv'))
    if bad or not rows:
        raise InputsError(f'набор {name}: ' + ('; '.join(bad) or 'MANIFEST пуст'))
    out: dict = {}
    for row in rows:
        if row['kind'] == 'pose':
            out[row['sku']] = os.path.join(sdir, cp['dest'].rstrip('/'), row['sku'])
    for sku, d in out.items():
        miss = [rel for rel in cp.get('need') or [] if not os.path.isfile(os.path.join(d, rel))]
        if miss:
            raise InputsError(f'набор {name}: у {sku} нет позы {", ".join(miss)} в {d} — python3 tools/ops/inputs_check.py --set {name}')
    return out


def set_photo_dirs() -> list:
    """Папки `<набор>/photo` (файлы `<sku>.hd.rgba.png`) всех наборов из правил — первыми в поиске фото входа 07 (make_inputs_07.py)."""
    try:
        r = rules()
    except (OSError, ValueError):
        return []
    return [d for d in (os.path.join(r['root'], n, 'photo') for n in r['sets']) if os.path.isdir(d)]


def main(argv: list) -> int:
    try:
        r = rules()
    except (OSError, ValueError) as e:
        print(f'❗ правила не прочитать: {e}', file=sys.stderr)
        return 2
    names = list(r['sets'])
    if '--set' in argv and argv.index('--set') + 1 < len(argv):
        names = [argv[argv.index('--set') + 1]]
    if '--build' in argv and argv.index('--build') + 1 < len(argv):
        names = [argv[argv.index('--build') + 1]]
    unknown = [n for n in names if n not in r['sets']]
    if unknown or not names:
        print(f'❗ нет набора в правилах: {", ".join(unknown) or "(пусто)"}', file=sys.stderr)
        return 2
    rc = 0
    res = {}
    for n in names:
        cfg = r['sets'][n]
        if '--build' in argv:
            probs, msgs = build_set(n, cfg, r['root'])
            print(f'набор {n}: копии в {os.path.join(r["root"], n)}')
            for m in msgs:
                print(m)
            for p in probs:
                print(f'  ❗ {p}')
            rc = rc or (1 if probs else 0)
            continue
        probs, st = check_set(n, cfg, r['root'])
        res[n] = {'problems': probs, **st}
        if '--json' not in argv:
            print(f'набор {n}: {st["sku"]} товаров, {st["files"]} файлов в MANIFEST, {st["list_paths"]} путей по {st["lists_skus"]} записям списков прогонов — ' + (f'❗ {len(probs)}' if probs else 'чисто'))
            for p in probs:
                print(f'  ❗ {p}')
        rc = rc or (1 if probs else 0)
    if '--json' in argv:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
