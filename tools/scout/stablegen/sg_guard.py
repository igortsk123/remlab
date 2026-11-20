"""СТОРОЖ ПОКРЫТИЯ ТЕКСТУРЫ для крашеных моделей StableGen (T-20261120-152/1; план painted-to-rt-01, предпосылка (г)).

Что делает. Берёт `painted.glb` прогона (или `model.glb` записи склада), камеры — ИЗ ДАННЫХ ПРОГОНА (`sg_cams.rig_for_run`: записанные позы `cameras.json`, иначе восстановленные по `status.json`),
считает `tex_coverage.process(rig=…)` — доли unseen / grazing / unpainted среди наружных текселей и швы — и выносит решение `keep / repaint / reject` по ОДНОМУ словарю порогов `tex_coverage.THRESHOLDS`
(тот же, что у MV-Adapter; своих чисел здесь нет). Для записи склада решение переводится в поле `guard` манифеста: keep → `pass` (значение из канона `painted_source.guard_pass`), repaint/reject — как есть.
`pass` один из ДВУХ условий победы крашеной у Hunyuan (второе — «принято владельцем», `rules/painted-accepted.json`): сторож показывает только, что краска легла по всей поверхности.

  ~/venvs/scout/bin/python sg_guard.py table ПАПКА_ПРОГОНА… [--out ДИР]      таблица SKU → решение и доли (прогон: <папка>/blender/painted.glb)
  Позы: записанные (cameras.json у новых прогонов / `--cams ПАПКА` — снятые `sg_cams.py extract` из session.blend) → иначе восстановленные по status.json; `--reconstruct` — только восстановленные.
  ~/venvs/scout/bin/python sg_guard.py store ЗАПИСЬ_СКЛАДА… [--out ДИР]      то же + записать `guard` и отчёт в manifest.json записи (sg_store.set_guard)
Папка прогона с 'blender' внутри берётся как есть; `--glob 'шаблон'` — найти прогоны по шаблону. Платного нет, процессор; тяжёлое (весь набор) — под `tools/ops/heavy-slot.sh --prio 0`."""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'salad', 'trellis'))
sys.path.insert(0, os.path.join(HERE, '..'))

VERDICT_GUARD = {'keep': None, 'repaint': 'repaint', 'reject': 'reject'}      # keep → guard_pass из канона (None = подставить)


def glb_of(d: str) -> str:
    for p in (os.path.join(d, 'blender', 'painted.glb'), os.path.join(d, 'model.glb')):
        if os.path.isfile(p):
            return p
    raise FileNotFoundError(f'{d}: нет blender/painted.glb и model.glb')


def sku_of(d: str) -> str:
    """SKU `mid:eid` — из манифеста записи склада, иначе из имени папки прогона (`<mid>_<eid>@…`)."""
    try:
        return json.load(open(os.path.join(d, 'manifest.json'), encoding='utf-8'))['sku']
    except (OSError, ValueError, KeyError):
        return os.path.basename(d.rstrip('/')).partition('@')[0].replace('_', ':', 1)


def guard_value(verdict: str, cfg: dict | None = None) -> str:
    """Решение сторожа → значение поля `guard` манифеста: keep → `guard_pass` канона, остальное — своё слово."""
    if cfg is None:
        import sg_store
        cfg = sg_store.painted_cfg()
    return cfg['guard_pass'] if verdict == 'keep' else VERDICT_GUARD[verdict]


def guard_dir(d: str, out_dir: str | None = None, thresholds: dict | None = None, grid: int = 2048, view_res: int = 768, cams_dir: str | None = None, reconstruct_only: bool = False) -> dict:
    """Одна папка (прогон или запись склада) → результат `tex_coverage.process` + `sku`, `run`. Камер нет → ValueError (в таблицу как «нет камер»)."""
    import sg_cams
    import tex_coverage as TC
    glb = glb_of(d)

    def rig(geoms):
        import numpy as np
        V = np.concatenate([g['V'] for g in geoms])
        doc = sg_cams.rig_for_run(d, ((V.min(axis=0) + V.max(axis=0)) / 2.0).tolist(), cams_dir, reconstruct_only)
        return (sg_cams.rig_glb(doc), doc['source']) if doc else (None, None)

    out_dir = out_dir or d
    res = TC.process(glb, out_dir, grid=grid, view_res=view_res, thresholds=thresholds, write_glb=False, rig=rig)
    res['sku'], res['run'] = sku_of(d), os.path.basename(d.rstrip('/'))
    return res


COLS = ['sku', 'run', 'verdict', 'cameras', 'faces', 'outer_share_tex', 'unseen_outer', 'grazing_outer', 'unpainted_outer', 'unseen_all', 'grazing_all', 'unpainted_all', 'seam_tex', 'why', 'time_s']


def row_of(r: dict) -> dict:
    if 'error' in r:
        return {'sku': r['sku'], 'run': r['run'], 'verdict': 'ошибка', 'why': r['error']}
    ot, t = r['outer_tex'], r['tex']
    return {'sku': r['sku'], 'run': r['run'], 'verdict': r['verdict'], 'cameras': r['cameras']['source'], 'faces': r['faces'], 'outer_share_tex': r['outer_share_tex_pct'],
            'unseen_outer': ot['unseen_pct'], 'grazing_outer': ot['grazing_pct'], 'unpainted_outer': ot['unpainted_pct'],
            'unseen_all': t['unseen_pct'], 'grazing_all': t['grazing_pct'], 'unpainted_all': t['unpainted_pct'],
            'seam_tex': (r.get('seam') or {}).get('seam_tex_pct'), 'why': '; '.join(r['verdict_why']), 'time_s': r['time_s']['all']}


def write_table(out_dir: str, results: list) -> tuple:
    """Таблица набора: `guard-table.csv/.md/.json`. Счётчик решений и ошибок — в конце .md (счётчик отказов обязателен)."""
    os.makedirs(out_dir, exist_ok=True)
    rows = [row_of(r) for r in results]
    p_csv, p_md, p_json = (os.path.join(out_dir, f'guard-table.{e}') for e in ('csv', 'md', 'json'))
    with open(p_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ('' if r.get(k) is None else r.get(k)) for k in COLS})
    counts: dict = {}
    for r in rows:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    json.dump({'verdicts': counts, 'rows': rows}, open(p_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    f1 = lambda v: '—' if v is None or v == '' else (f'{v:.1f}' if isinstance(v, float) else str(v))  # noqa: E731
    L = ['# Сторож покрытия текстуры — крашеные модели StableGen', '',
         'Доли — % текселей среди НАРУЖНЫХ (видимых снаружи хотя бы с одного из 26 направлений); «все» — по всем текселям карты. unseen — ни одна из камер прогона не видит, '
         'grazing — видят только вскользь, unpainted — «фон» (чёрный/белый). Камеры — из данных прогона (`recorded` — записанные, `reconstructed` — восстановленные по status.json). Пороги — `tex_coverage.THRESHOLDS`.', '',
         '| SKU | прогон | решение | камеры | граней | наружных % | unseen | grazing | unpainted | unseen (все) | grazing (все) | unpainted (все) | швы % | почему |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        L.append(f"| `{r['sku']}` | `{r['run'][:40]}` | **{r['verdict']}** | {r.get('cameras') or '—'} | {f1(r.get('faces'))} | {f1(r.get('outer_share_tex'))} | {f1(r.get('unseen_outer'))} | {f1(r.get('grazing_outer'))} | "
                 f"{f1(r.get('unpainted_outer'))} | {f1(r.get('unseen_all'))} | {f1(r.get('grazing_all'))} | {f1(r.get('unpainted_all'))} | {f1(r.get('seam_tex'))} | {r.get('why') or ''} |")
    L += ['', 'Итого: ' + ', '.join(f'{k} — {v}' for k, v in sorted(counts.items())) + f' (всего {len(rows)})']
    open(p_md, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    return p_csv, p_md, p_json


def run_set(dirs: list, out_dir: str, write_guard: bool = False, thresholds: dict | None = None, cams_dir: str | None = None, reconstruct_only: bool = False) -> list:
    """Прогнать набор. Ошибка одной папки — строка «ошибка» в таблице и код 1 в конце, остальные идут. write_guard — записать итог в manifest.json записей склада."""
    results = []
    for d in dirs:
        t0 = time.time()
        try:
            r = guard_dir(d, os.path.join(out_dir, 'json'), thresholds, cams_dir=cams_dir, reconstruct_only=reconstruct_only)
            if write_guard:
                import sg_store
                g = guard_value(r['verdict'])
                sg_store.set_guard(d, g, {'verdict': r['verdict'], 'why': r['verdict_why'], 'cameras': r['cameras'], 'outer_tex': r['outer_tex'], 'tex': r['tex'],
                                          'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
            print(f"{r['sku']} {r['run'][:34]}: {r['verdict']} · камеры {r['cameras']['source']} · unseen {r['outer_tex']['unseen_pct']} % grazing {r['outer_tex']['grazing_pct']} % "
                  f"unpainted {r['outer_tex']['unpainted_pct']} % · {time.time() - t0:.0f} с", flush=True)
        except Exception as e:  # noqa: BLE001 — счётчик отказов обязателен: ошибка в таблицу, не молчание
            r = {'sku': sku_of(d), 'run': os.path.basename(d.rstrip('/')), 'error': f'{type(e).__name__}: {str(e)[:160]}'}
            print(f"{r['sku']} {r['run'][:34]}: ОШИБКА {r['error']}", flush=True)
        results.append(r)
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Сторож покрытия текстуры крашеных моделей StableGen: камеры из данных прогона')
    ap.add_argument('mode', choices=['table', 'store'])
    ap.add_argument('dirs', nargs='*')
    ap.add_argument('--glob', default='', help='шаблон папок прогонов (в кавычках)')
    ap.add_argument('--out', default='')
    ap.add_argument('--cams', default='', help='папка с позами, снятыми из session.blend (<имя прогона>.json): записанные позы без правки папок прогонов')
    ap.add_argument('--reconstruct', action='store_true', help='записанные позы игнорировать — только восстановленные (сравнение с записанными)')
    ap.add_argument('--thresholds', default='', help='JSON с порогами вместо tex_coverage.THRESHOLDS')
    a = ap.parse_args(argv)
    dirs = list(a.dirs)
    if a.glob:
        dirs += sorted(glob.glob(os.path.expanduser(a.glob)))
    dirs = [d for d in dirs if os.path.isdir(d)]
    if not dirs:
        ap.error('нет папок: укажи прогоны/записи склада или --glob')
    th = json.load(open(a.thresholds, encoding='utf-8')) if a.thresholds else None
    out = a.out or os.path.join(os.getcwd(), 'sg-guard-out')
    results = run_set(dirs, out, write_guard=(a.mode == 'store'), thresholds=th, cams_dir=os.path.expanduser(a.cams) or None, reconstruct_only=a.reconstruct)
    print('\n'.join(write_table(out, results)))
    return 1 if any('error' in r for r in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
