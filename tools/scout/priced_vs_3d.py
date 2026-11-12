#!/usr/bin/env python3
"""«В цене, но без места в 3D» — отчёт-наблюдение по /demo и турам /try (T-20261112-64, план living-full-01 Т1 шаг 2; совет Codex
`_intake/codex/2026-11-12-living-passport-carriers-answer.md` § 7 «Этап 2»: selected/priced − rendered, НЕ гейт). Только чтение.

ЗАЧЕМ. Правило владельца: ни одного товара «в комплекте и в цене, но без места в 3D». Отчёт даёт честную цифру «сколько и чего»
на живых данных — от неё меряем, что гостиная по новому паспорту дошла до нуля.

КАК СЧИТАЕМ. Правду о 3D знает только код сцены страницы (браузер), поэтому факты собирает TS-помощник
`priced_vs_3d_scene.ts` ТЕМ ЖЕ кодом: мост `fromDemoVariant` → `resolveScene` (`unplaced`) → `planObjects` (что рисуется); цена — правило
страницы `index.html:productsOf` (подробно — в шапке помощника). Помощник собирается esbuild из корня репо и идёт под node. Здесь —
причина по каждой строке (`reason`), итоги по ролям, причинам и комнатам. Отдельный раздел — «в наборе банка, но не на странице»
(`tools/scout/sets3.json` → вариант `set{n}` = набор n, как `flat215_demo.build`): это НЕ в цене страницы, только справка
(люстра, роли вне `SHOW_ROLES`/`DECOR_ROLES`, `dims_unknown`).

  ~/venvs/scout/bin/python priced_vs_3d.py OUTDIR [--demo demo-data.json] [--tours DIR_С_bundle.json] [--fetch-tours]
--fetch-tours: последние `bundle-<N>.json` 16 туров с тома прода (ssh, только чтение) → OUTDIR/tours/<id>.json.
Итог: OUTDIR/report.md + report.json.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
NODE_MODULES = os.environ.get('REMLAB_NODE_MODULES', '/home/pakar/igor/remlab/node_modules')
DEMO = os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
# живой банк (`bank_paths.LIVE`) — файл сборки, не в git: в worktree его нет — тогда основная копия репо
BANK = os.environ.get('SETS_BANK') or next((p for p in (os.path.join(HERE, 'sets3.json'), '/home/pakar/igor/remlab/tools/scout/sets3.json')
                                             if os.path.exists(p)), os.path.join(HERE, 'sets3.json'))
SRV, PORT = os.environ.get('MESH_SRV', 'root@89.167.127.0'), os.environ.get('MESH_SSH_PORT', '22222')
TRIAL_VOL = '/var/lib/docker/volumes/remlab_remlab-trial/_data'

# причины — в порядке проверки; подпись покупателю не нужна, это отчёт для нас
SOFT = 'список-только: мягкое (soft_roles)'
LIST_ONLY = 'список-только: list_only'
EXTRA_ART = 'лишняя картина: нет места на стене (unplaced)'
NO_SUPPORT = 'unplaced: нет опоры'
NO_MESH = 'нет меша'
NO_DIMS = 'нет габаритов'
PARTIAL = 'часть мест не в 3D'
OTHER = 'другое'


def base_role(role: str | None) -> str:
    return re.sub(r'\s+\d+$', '', str(role or '')).strip()


def reason(r: dict) -> str | None:
    """Причина «в цене, нет в 3D» строки фактов помощника; None — строка в 3D целиком."""
    if r.get('shown', 0) >= r.get('slots', 1):
        return None
    if r.get('src') == 'decor':
        if r.get('soft'):
            return SOFT
        if r.get('list_only'):
            return LIST_ONLY
        if r.get('unplaced'):
            return EXTRA_ART if r.get('wall_art') else NO_SUPPORT
    elif r.get('unplaced'):
        return EXTRA_ART if r.get('wall_plane') else NO_SUPPORT
    if r.get('shown', 0) > 0:
        return PARTIAL
    if not r.get('dims_ok'):
        return NO_DIMS
    if not r.get('has_msid') and not r.get('rug') and not r.get('wall_plane') and not r.get('wall_art'):
        return NO_MESH
    return OTHER


def missing_rub(r: dict) -> float:
    """₽ строки, которых нет в 3D: цена × (купить − купить за показанные места); декор — по штуке."""
    return float(r.get('price') or 0) * max(0, int(r.get('qty') or 1) - int(r.get('qty_shown') or 0))


def summarize(facts: dict, scope: str) -> dict:
    """facts — вывод помощника {файл: {variants: [...]}} → строки нарушений и итоги (роль, причина, комната)."""
    rows, by_role, by_reason, by_room = [], {}, {}, {}
    priced_n, priced_rub, variants = 0, 0.0, 0
    errors = []
    for f, d in facts.items():
        src = os.path.basename(f).replace('.json', '') if scope == 'tours' else 'demo'
        for v in d.get('variants') or []:
            variants += 1
            if v.get('error'):
                errors.append({'file': src, 'variant': v.get('id'), 'error': v['error']})
            for r in v.get('rows') or []:
                priced_n += 1
                priced_rub += float(r.get('price') or 0) * int(r.get('qty') or 1)
                why = reason(r)
                if not why:
                    continue
                rub = missing_rub(r)
                row = {'where': src, 'variant': v.get('id'), 'room': v.get('room_id'), 'style': v.get('style'),
                       'role': r.get('role'), 'name': r.get('name'), 'sid': r.get('sid'), 'rub': rub, 'reason': why}
                rows.append(row)
                for acc, k in ((by_role, base_role(r.get('role'))), (by_reason, why), (by_room, str(v.get('room_id')))):
                    a = acc.setdefault(k, {'n': 0, 'rub': 0.0})
                    a['n'] += 1
                    a['rub'] += rub
    order = lambda acc: dict(sorted(acc.items(), key=lambda kv: (-kv[1]['rub'], -kv[1]['n'])))  # noqa: E731
    return {'scope': scope, 'variants': variants, 'priced_rows': priced_n, 'priced_rub': round(priced_rub),
            'missing_n': len(rows), 'missing_rub': round(sum(x['rub'] for x in rows)),
            'by_role': order(by_role), 'by_reason': order(by_reason), 'by_room': order(by_room), 'rows': rows, 'errors': errors}


def export_roles(src: str | None = None) -> tuple[set, set]:
    """`SHOW_ROLES` и `DECOR_ROLES` экспорта демо — ЧТЕНИЕМ текста `flat215_demo.py`, не импортом (импорт модуля тянет окружение
    сборки витрины). Базовые роли (без номера)."""
    txt = open(src or os.path.join(HERE, 'flat215_demo.py'), encoding='utf-8').read()
    def grab(name: str) -> set:
        m = re.search(rf'^{name}\s*=\s*[({{](.*?)[)}}]', txt, re.S | re.M)
        return {base_role(x) for x in re.findall(r"'([^']+)'", m.group(1))} if m else set()
    return grab('SHOW_ROLES'), grab('DECOR_ROLES')


def why_absent(role: str, show: set, decor: set, unknown: set) -> str:
    """Почему роли набора нет на странице: размер не указан / раскладка не поставила / экспорт роль не берёт."""
    if role in unknown:
        return 'dims_unknown: нет размера — не в сцене'
    b = base_role(role)
    if b in show:
        return 'раскладка не поставила (роль сцены)'
    if b in decor:
        return 'декор без товара на странице'
    return 'нет в экспорте: роль не выгружается'


def bank_not_exported(demo: dict, bank: list, roles: tuple[set, set] | None = None) -> list:
    """Вариант `set{n}` ← набор банка n (`flat215_demo.build`): РОЛИ набора с товаром, которых на странице нет ни в предметах, ни в
    декоре (люстра, настольная лампа, банкетка…). Сверка по роли, не по sid: банк пересобирается каждую ночь и товары в нём меняются
    (12.11: у вариантов совпало 21–54 % sid), а состав ролей — то, что экспорт пропускает по правилу. `overlap` — доля sid страницы,
    найденных в наборе, для справки."""
    show, dec = roles or export_roles()
    out = []
    for v in demo.get('variants') or []:
        m = re.fullmatch(r'set(\d+)', str(v.get('id') or ''))
        if not m or int(m.group(1)) > len(bank):
            continue
        items = bank[int(m.group(1)) - 1].get('items') or {}
        entries = (v.get('items') or []) + (v.get('decor') or [])
        page = {str((x.get('sku') or {}).get('sid') or '').replace('_', ':', 1) for x in entries} - {''}
        page_roles = {str(x.get('role') or '') for x in entries}
        mine = {}
        for role, p in items.items():
            if isinstance(p, dict) and p.get('name'):
                mine[role] = (f"{p.get('mid')}:{p.get('eid')}", p)
        overlap = len(page & {s for s, _ in mine.values()}) / max(1, len(page))
        unknown = {x.get('role') for x in v.get('dims_unknown') or []}
        for role, (sid, p) in mine.items():
            if role in page_roles:
                continue
            out.append({'variant': v['id'], 'style': v.get('style'), 'role': role, 'name': p.get('name'), 'sid': sid,
                        'price': p.get('price'), 'why': why_absent(role, show, dec, unknown),
                        'overlap': round(overlap, 2)})
    return out


def scene_facts(paths: list, out_dir: str) -> dict:
    """Собрать помощник (esbuild, `@/` — tsconfig репо) и прогнать node по файлам данных."""
    build = os.path.join(out_dir, 'build')
    os.makedirs(build, exist_ok=True)
    mjs = os.path.join(build, 'scene.mjs')
    env = dict(os.environ, NODE_PATH=NODE_MODULES)
    subprocess.run([os.path.join(NODE_MODULES, '.bin', 'esbuild'), os.path.join(HERE, 'priced_vs_3d_scene.ts'), '--bundle',
                    '--platform=node', '--format=esm', '--log-level=warning', f'--outfile={mjs}'], cwd=REPO, env=env, check=True)
    res = subprocess.run(['node', mjs, *paths], capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def fetch_tours(dst: str) -> list:
    """Последние bundle-<N>.json каждого задания тома пробы (ssh, только чтение) → dst/<id>.json."""
    os.makedirs(dst, exist_ok=True)
    ls = subprocess.run(['ssh', '-p', PORT, '-o', 'BatchMode=yes', SRV, f'cd {TRIAL_VOL} && ls -1 */bundle-*.json'],
                        capture_output=True, text=True, check=True).stdout.split()
    last = {}
    for p in ls:
        m = re.fullmatch(r'([^/]+)/bundle-(\d+)\.json', p)
        if m and int(m.group(2)) >= last.get(m.group(1), (0, ''))[0]:
            last[m.group(1)] = (int(m.group(2)), p)
    got = []
    for job, (_, p) in sorted(last.items()):
        body = subprocess.run(['ssh', '-p', PORT, '-o', 'BatchMode=yes', SRV, f'cat {TRIAL_VOL}/{p}'],
                              capture_output=True, check=True).stdout
        path = os.path.join(dst, f'{job}.json')
        with open(path, 'wb') as fh:
            fh.write(body)
        got.append(path)
    return got


def table(acc: dict, head: str) -> str:
    s = f'| {head} | раз | ₽ |\n|---|---|---|\n'
    return s + ''.join(f"| {k} | {a['n']} | {round(a['rub']):,} |\n".replace(',', ' ') for k, a in acc.items())


def render_md(demo: dict, tours: dict, bank: list, meta: dict) -> str:
    L = [f"# В цене, но без места в 3D — {meta['at']}", '',
         f"Источник: /demo `{meta['demo']}`; туры — {meta['tours_n']} файлов данных (`{meta['tours']}`). Правило цены и 3D — шапка "
         '`tools/scout/priced_vs_3d_scene.ts`; причины — `tools/scout/priced_vs_3d.py:reason`. Расстановка — исходная (как открыл покупатель); '
         'правки покупателя (передвинул столик) могут добавить «ваза без опоры» — в отчёт не входят.', '']
    for s in (demo, tours):
        L += [f"## {'/demo' if s['scope'] == 'demo' else 'Туры /try'}",
              f"Вариантов {s['variants']}; строк в цене {s['priced_rows']} на {s['priced_rub']:,} ₽; **в цене без 3D — {s['missing_n']} строк на "
              f"{s['missing_rub']:,} ₽**.".replace(',', ' '), '']
        if s['missing_n']:
            L += ['### По ролям', table(s['by_role'], 'роль'), '### По причинам', table(s['by_reason'], 'причина'),
                  '### По комнатам', table(s['by_room'], 'комната'), '### Все строки',
                  '| где | вариант | роль | товар | ₽ | причина |', '|---|---|---|---|---|---|']
            L += [f"| {r['where']} | {r['variant']} | {r['role']} | {r['name']} | {round(r['rub'])} | {r['reason']} |" for r in s['rows']]
            L.append('')
        if s['errors']:
            L += ['Сбои сцены:', *[f"- {e['file']} {e['variant']}: {e['error']}" for e in s['errors']], '']
    L += ['## Справка: в наборе банка, но не на странице (НЕ в цене страницы)',
          'Вариант `set{n}` ← набор n `sets3.json`, сверка по РОЛИ (товары банка меняются каждую ночь); товар и ₽ — текущие банка. '
          '`overlap` — доля sid страницы, найденных в наборе, для справки.', '',
          '| вариант | роль | товар (банк сейчас) | ₽ | почему | overlap |', '|---|---|---|---|---|---|']
    L += [f"| {b['variant']} | {b['role']} | {b['name']} | {b['price']} | {b['why']} | {b['overlap']} |" for b in bank]
    return '\n'.join(L) + '\n'


def main(argv: list) -> int:
    out = argv[1]
    os.makedirs(out, exist_ok=True)
    arg = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d  # noqa: E731
    demo_path = arg('--demo', DEMO)
    tours_dir = arg('--tours', os.path.join(out, 'tours'))
    tours = fetch_tours(tours_dir) if '--fetch-tours' in argv else sorted(glob.glob(os.path.join(tours_dir, '*.json')))
    facts_demo = scene_facts([demo_path], out)
    facts_tours = scene_facts(tours, out) if tours else {}
    demo = summarize(facts_demo, 'demo')
    tour = summarize(facts_tours, 'tours')
    bank = bank_not_exported(json.load(open(demo_path, encoding='utf-8')), json.load(open(BANK, encoding='utf-8')))
    meta = {'at': subprocess.run(['date', '-u', '+%Y-%m-%d %H:%M UTC'], capture_output=True, text=True).stdout.strip(),
            'demo': demo_path, 'tours': tours_dir, 'tours_n': len(tours)}
    json.dump({'meta': meta, 'demo': demo, 'tours': tour, 'bank_not_exported': bank,
               'facts': {'demo': facts_demo, 'tours': facts_tours}},
              open(os.path.join(out, 'report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    with open(os.path.join(out, 'report.md'), 'w', encoding='utf-8') as fh:
        fh.write(render_md(demo, tour, bank, meta))
    print(f"/demo: в цене без 3D {demo['missing_n']} строк, {demo['missing_rub']} ₽ из {demo['priced_rub']} ₽; "
          f"туры ({len(tours)}): {tour['missing_n']} строк, {tour['missing_rub']} ₽; банк не на странице: {len(bank)}")
    print('отчёт', os.path.join(out, 'report.md'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
