"""Сбор входа этапа 09 «проверка» (T-20261123-20/1, правка T-20261123-30): единая папка `<out>/<sku>/<этап>` с симлинками на готовые папки этапов.
Использование: plan09.py <inputs.json> <out> [--build] [--new ROOT ...] [--logs DIR]
  Без --build — только таблица покрытия (что где найдено). С --build — создаёт симлинки (существующие не трогает). Ничего не удаляет.
Источник раннего этапа (01/02/03/05, 04 из pose_run) — ПО ПРОИСХОЖДЕНИЮ ПАКЕТА: `inputs[sku].stage_src[<этап>]` (явно) → прогоны, из которых взяты форма/фото/поза пакета
(предки путей `glb`, `photo`, `pose_run`, `extra_in`: `<предок>/<sku>/<этап>`, `<предок>/*/<sku>/<этап>`; ближний предок первым) → приоритетные корни `OLD` (список проверенных прогонов) →
ТОЛЬКО если происхождения нет — запасной поиск по `<logs>/*/<sku>/<этап>`, `<logs>/*/*/<sku>/<этап>` (прошедший, самый свежий). Запасной поиск может взять этап от другой формы/камеры, поэтому каждый
такой этап помечен `how=search` в `<out>/<sku>/sources.json`, а этап 09 пишет в пометки «источник по поиску: …» (товар не «готов» без пометки). Этапы 06/07/seam/08 — ТОЛЬКО из перечисленных `--new` корней пакета.
Ничего не удаляет. ID товаров в коде нет."""
import glob
import json
import os
import sys

LOGS = '/home/pakar/remlab-logs'
OLD = {
    '01-trellis': [f'{LOGS}/t178-1121/prep', f'{LOGS}/t174-1121/after-run', f'{LOGS}/t183-1121/runs04', f'{LOGS}/e2eHD-batch-1121'],
    '02-prep': [f'{LOGS}/t178-1121/prep', f'{LOGS}/t174-1121/after-run', f'{LOGS}/t183-1121/runs04', f'{LOGS}/e2eHD-batch-1121'],
    '05-delight': [f'{LOGS}/t178-1121/prep', f'{LOGS}/t174-1121/after-run', f'{LOGS}/e2eHD-batch-1121'],
    '03-parts': [f'{LOGS}/t198-1122/parts-root', f'{LOGS}/t198-1122/parts-root-coarse', f'{LOGS}/e2eHD-batch-1121'],
}
NEW_STAGES = ('06-visible', '07-fill', '07-seam', '08-material')
SOURCES = 'sources.json'                                                       # <out>/<sku>/sources.json: откуда каждый этап (how: origin | list | package | search); читает paint_check
NEED = ['01-trellis', '02-prep', '03-parts', '04-camera', '05-delight', '06-visible', '07-fill', '08-material']


def has_check(d):
    return os.path.isfile(os.path.join(d, 'check.json'))


def _passed(d):
    try:
        return bool(json.load(open(os.path.join(d, 'check.json'), encoding='utf-8')).get('passed'))
    except (OSError, ValueError):
        return False


def origin_dirs(sku, stage, v, logs):
    """Папки этапа из прогонов, породивших вход пакета: предки путей glb/photo/pose_run/extra_in (ближний первым), внутри logs."""
    paths = [v.get('pose_run'), v.get('glb'), v.get('photo')] + list((v.get('extra_in') or {}).values())
    seen, out = set(), []
    lg = os.path.realpath(logs)
    for p in paths:
        if not p:
            continue
        rp = os.path.realpath(p)
        a = rp if os.path.isdir(rp) else os.path.dirname(rp)
        while a.startswith(lg + os.sep) and a != lg:
            if a not in seen:
                seen.add(a)
                out += [os.path.join(a, sku, stage)] + sorted(glob.glob(os.path.join(a, '*', sku, stage)))
            a = os.path.dirname(a)
    return out


def find_old(sku, stage, roots, logs, skip=(), v=None):
    """→ (папка | None, how): origin (из прогонов входа пакета / явный stage_src) | list (приоритетные корни) | search (запасной поиск — другая форма/камера возможны) | None."""
    v = v or {}
    ex = (v.get('stage_src') or {}).get(stage)
    if ex and has_check(ex):
        return ex, 'origin'
    skp = [os.path.realpath(x) for x in skip if x]
    for p in origin_dirs(sku, stage, v, logs):
        rp = os.path.realpath(p)
        if has_check(p) and not any(rp == x or rp.startswith(x + os.sep) for x in skp):
            return p, 'origin'
    for r in roots:
        p = os.path.join(r, sku, stage)
        if has_check(p):
            return p, 'list'
    cands = []
    for pat in (os.path.join(logs, '*', sku, stage), os.path.join(logs, '*', '*', sku, stage)):
        for p in glob.glob(pat):
            rp = os.path.realpath(p)
            if os.path.isdir(p) and has_check(p) and not any(rp == x or rp.startswith(x + os.sep) for x in skp):
                cands.append(p)
    if not cands:
        return None, None
    ok = [p for p in cands if _passed(p)]
    return max(ok or cands, key=lambda p: os.path.getmtime(os.path.join(p, 'check.json'))), 'search'


def collect(inputs, news, logs=LOGS, old=OLD, skip=()):
    """→ [(sku, {этап: папка}, {этап: how})]."""
    rows = []
    for sku, v in sorted(inputs.items()):
        found, how = {}, {}
        for st, roots in old.items():
            p, h = find_old(sku, st, roots, logs, skip, v)
            if p:
                found[st], how[st] = p, h
        pr = v.get('pose_run') or ''
        p = os.path.join(pr, '04-camera') if pr else ''
        if p and has_check(p):
            found['04-camera'], how['04-camera'] = p, 'origin'
        for st in NEW_STAGES:
            for r in news:
                p = os.path.join(r, sku, st)
                if os.path.isdir(p) and (has_check(p) or st in ('07-seam', '07-fill')):
                    found[st], how[st] = p, 'package'
                    break
        rows.append((sku, found, how))
    return rows


def link(rows, out):
    n = 0
    for sku, found, how in rows:
        if found:
            os.makedirs(os.path.join(out, sku), exist_ok=True)
            json.dump({'sources': {st: {'dir': p, 'how': how.get(st)} for st, p in found.items()}}, open(os.path.join(out, sku, SOURCES), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        for st, p in found.items():
            d = os.path.join(out, sku)
            os.makedirs(d, exist_ok=True)
            lk = os.path.join(d, st)
            if not os.path.lexists(lk):
                os.symlink(p, lk)
                n += 1
    return n


def news_of(new):
    news = []
    for n in new:                                                              # корень пакета: либо сам <root>/<sku>, либо папка шардов <root>/sh*/<sku>
        news += [os.path.join(n, d) for d in sorted(os.listdir(n)) if os.path.isdir(os.path.join(n, d)) and d.startswith('sh')] or [n]
    return news


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    inputs = json.load(open(a[0], encoding='utf-8'))
    out = a[1]
    build = '--build' in a
    new = [a[i + 1] for i, x in enumerate(a) if x == '--new']
    logs = next((a[i + 1] for i, x in enumerate(a) if x == '--logs'), LOGS)
    rows = collect(inputs, news_of(new), logs, OLD, skip=(os.path.realpath(out),))
    links = link(rows, out) if build else 0
    print('товар'.ljust(34), ' '.join(s[:2] for s in NEED))
    miss_all = {}
    for sku, f, hw in rows:
        print(sku.ljust(34), ' '.join((('✓ ' if hw.get(s) != 'search' else '≈ ') if s in f else '— ') for s in NEED))
        for s in NEED:
            if s not in f:
                miss_all.setdefault(s, []).append(sku)
    print({s: len(x) for s, x in miss_all.items()}, f'симлинков создано: {links}' if build else '(без --build)', '· «≈» — источник по поиску (не по происхождению пакета)')


if __name__ == '__main__':
    main()
