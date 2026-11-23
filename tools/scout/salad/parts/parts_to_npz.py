#!/usr/bin/env python3
"""Части PartLLM (этап 03, T-198/1) → вход этапа 07: `<корень частей>/<товар>/03-parts/parts.npz` (ключ `part`, int32, ОДИН массив на все грани GLB в порядке геометрий —
ровно то, что читает `tex_fill.parts_from_npz`) + `parts.json` (номер части → имя PartLLM, доля граней; роли — только через мост `rules/part-llm-roles.json` (T-217/2, `parts_names_roles`): `mode` dry — отчёт `roles-bridge.json`, parts.json как был; `on` — поля роли в parts.json). Выбор источника зон для 07 —
флаг `zones_from` в rules/paint-fill.json: `parts` (по умолчанию, при наличии годного parts.npz) | `panels` (только панели формы, как до T-198).
Здесь только то, что знает PartLLM-часть: перевод выхода воркера (`parts_trial.py`: faces.npy = метка части на грань в порядке граней входного glb) и проверка «число граней совпало».

  python parts_to_npz.py convert --items items.json --src <папка с <товар>/faces.npy> --out <корень частей> [--prompt-set fine]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.abspath(os.path.join(HERE, '..', '..', 'rules', 'paint-fill.json'))
CHECK_RULES = os.path.abspath(os.path.join(HERE, '..', '..', 'rules', 'part-llm-check.json'))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..')))
MODES = ('parts', 'panels')


def zones_mode(rules_path: str | None = None) -> str:
    """`zones_from` из rules/paint-fill.json; нет ключа — `parts`; чужое значение — ValueError (молча не угадываем)."""
    with open(rules_path or RULES, encoding='utf-8') as f:
        v = json.load(f).get('zones_from', 'parts')
    if v not in MODES:
        raise ValueError(f'rules/paint-fill.json: zones_from={v!r}, ожидалось одно из {MODES}')
    return v


def write_stage_check(out_dir: str, sku: str, res: dict, seconds: float | None = None, rules_path: str | None = None) -> dict:
    """`check.json` этапа 03-parts рядом с parts.npz (T-20261123-44): раньше путь PartLLM писал только parts.npz/parts.json, и этап 9 брал `check.json` старого прогона другой формы.
    Правило общее: этап без своего check.json = не пройден; отказ (нет faces.npy, не тот меш) тоже пишет check.json с passed=false и причиной. Пороги — rules/part-llm-check.json."""
    import paint_stage as ps
    with open(rules_path or CHECK_RULES, encoding='utf-8') as f:
        R = json.load(f)
    if not res.get('ok'):
        return ps.write_check(out_dir, '03-parts', sku, passed=False, reason=res.get('reason') or 'этап не отдал части', seconds=seconds, outputs=[], source='partllm', **({'n_faces': res['n_faces']} if 'n_faces' in res else {}))
    n, cover = res['n_parts'], round(1.0 - float(res['share_unlabeled']), 4)
    metrics = {'n_parts': {'value': n, 'threshold': f"{R['min_parts']}–{R['max_parts']}", 'op': 'in', 'ok': R['min_parts'] <= n <= R['max_parts']},
               'faces_with_part_share': {'value': cover, 'threshold': R['faces_with_part_min'], 'op': '>=', 'ok': cover >= R['faces_with_part_min']}}
    return ps.write_check(out_dir, '03-parts', sku, passed=None, metric={'name': 'n_parts', **metrics['n_parts']}, metrics=metrics, seconds=seconds, outputs=['parts.npz', 'parts.json'], source='partllm', n_faces=res.get('n_faces'))


def glb_face_count(path: str) -> int:
    """Число граней ВСЕХ геометрий GLB подряд (как считает `parts_from_npz`)."""
    import trimesh
    sc = trimesh.load(path, process=False)
    geoms = list(sc.geometry.values()) if hasattr(sc, 'geometry') else [sc]
    return int(sum(len(g.faces) for g in geoms))


def bridge_step(glb: str, lab, names: list, parts: list, doc: dict, out_dir: str, ctx: dict | None) -> dict | None:
    """Мост «название → роль» (T-217/2, `rules/part-llm-roles.json`, режим `mode`): роли по именам частей + геометрии → `roles-bridge.json` (отчёт, всегда при mode≠off и заданном `ctx`);
    при mode=on — ещё и поля роли в записи `parts` (parts.json). dry — parts.json не меняется. ctx: {product_role, channels, channel_classes, cam_az}; нет ctx — шаг не выполняется (None).
    Сбой расчёта не роняет конвертер: {error} в отчёте, части остаются."""
    sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', '..', 'assets')))
    import parts_names_roles as PN
    rules = PN.load_rules()
    if PN.mode(rules) == 'off' or ctx is None:
        return None
    res = PN.run_glb(glb, lab, names, ctx.get('product_role'), set(ctx.get('channels') or []), ctx.get('channel_classes') or {}, ctx.get('cam_az'), rules)
    json.dump(res, open(os.path.join(out_dir, 'roles-bridge.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if res.get('mode') == 'on' and 'roles' in res:
        for p in parts:
            r = res['roles'].get(str(p['id']))
            if r:
                p.update({k: r[k] for k in PN.FIELDS})
        doc['roles'] = {k: v for k, v in res['summary'].items() if k in ('known_role_area_share', 'no_channel_area_share', 'unknown_reasons')}
    return {'mode': res.get('mode'), **({'error': res['error']} if 'error' in res else {'summary': res['summary']})}


def convert(src_dir: str, glb: str, out_dir: str, prompt_set: str = 'fine', roles_ctx: dict | None = None, sku: str | None = None) -> dict:
    """Один товар: `<src_dir>/faces.npy` (+ meta.json) → `<out_dir>/parts.npz`, `parts.json`. → {ok, reason, n_faces, n_parts, ...}. Число граней не совпало — файлов нет, ok=False.
    `roles_ctx` — тип/каналы/камера товара для моста ролей (`bridge_step`); без него роли не считаются (parts.json как до T-217).
    Всегда пишет `<out_dir>/check.json` (T-20261123-44): годный выход — по мерам rules/part-llm-check.json, отказ — passed=false с причиной. sku — имя товара (нет — имя папки над `03-parts`)."""
    import time
    t0 = time.time()
    res = _convert(src_dir, glb, out_dir, prompt_set, roles_ctx)
    sku = sku or os.path.basename(os.path.dirname(os.path.abspath(out_dir)))
    try:
        write_stage_check(out_dir, sku, res, time.time() - t0)
        res['check'] = 'check.json записан'
    except Exception as e:  # noqa: BLE001 — запись check не должна ронять перевод частей, но и молчать нельзя
        res['check'] = f'check.json НЕ записан: {type(e).__name__}: {str(e)[:100]}'
    return res


def _convert(src_dir: str, glb: str, out_dir: str, prompt_set: str, roles_ctx: dict | None) -> dict:
    import numpy as np
    fp = os.path.join(src_dir, 'faces.npy')
    if not os.path.isfile(fp):
        return {'ok': False, 'reason': 'нет faces.npy (PartLLM не отдал части)'}
    lab = np.load(fp).astype(np.int64)
    n = glb_face_count(glb)
    if lab.shape != (n,):
        return {'ok': False, 'reason': f'меток {lab.shape[0] if lab.ndim else lab.size}, граней в GLB {n} — части другого меша', 'n_faces': n}
    names = []
    mp = os.path.join(src_dir, 'meta.json')
    if os.path.isfile(mp):
        names = (json.load(open(mp, encoding='utf-8')) or {}).get('names') or []
    ids, cnt = np.unique(lab[lab >= 0], return_counts=True)
    os.makedirs(out_dir, exist_ok=True)
    np.savez_compressed(os.path.join(out_dir, 'parts.npz'), part=lab.astype(np.int32))
    parts = [{'id': int(i), 'name': names[int(i)] if 0 <= int(i) < len(names) else '', 'face_share': round(float(c) / n, 4)} for i, c in zip(ids, cnt)]
    doc = {'source': 'partllm', 'prompt_set': prompt_set, 'n_faces': n, 'share_unlabeled': round(float((lab < 0).mean()), 4), 'parts': parts}
    bridge = bridge_step(glb, lab, names, parts, doc, out_dir, roles_ctx)                    # dry: только отчёт; on: поля роли в parts; до записи parts.json
    json.dump(doc, open(os.path.join(out_dir, 'parts.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return {'ok': True, 'reason': f'{len(parts)} частей', 'n_faces': n, 'n_parts': len(parts), 'share_unlabeled': doc['share_unlabeled'], **({'roles': bridge} if bridge else {})}


def pick_parts(parts_root: str, sku: str, face_glb: str, mode: str) -> tuple:
    """Что кладём в задание 07 по товару: (путь parts.npz | None, строка-причина). `panels` → None; `parts`: файл есть и граней столько же, сколько в `face_glb` → путь,
    иначе None + причина (07 не падает, идёт по панелям формы — отдельная строка в зонах, не молчком)."""
    if mode == 'panels':
        return None, 'zones_from=panels'
    npz = os.path.join(parts_root, sku, '03-parts', 'parts.npz')
    if not os.path.isfile(npz):
        return None, 'panels: нет parts.npz'
    import numpy as np
    n_lab = int(np.load(npz)['part'].shape[0])
    n = glb_face_count(face_glb)
    if n_lab != n:
        return None, f'panels: parts.npz граней {n_lab}, в GLB {n} — части другого меша'
    return npz, 'parts'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['convert'])
    ap.add_argument('--items', required=True, help='JSON [{"sid","path"}] — GLB формы (как у parts_trial)')
    ap.add_argument('--src', required=True, help='папка выхода parts_trial: <товар>/faces.npy')
    ap.add_argument('--out', required=True, help='корень частей: <товар>/03-parts/parts.npz')
    ap.add_argument('--prompt-set', default='fine')
    ap.add_argument('--roles-ctx', default='', help='JSON {товар: {product_role, channels: [..], channel_classes: {..}, cam_az}} — вход моста ролей (rules/part-llm-roles.json, mode); нет — роли не считаются')
    a = ap.parse_args()
    items = json.load(open(a.items, encoding='utf-8'))
    ctxs = json.load(open(a.roles_ctx, encoding='utf-8')) if a.roles_ctx else {}
    res, bad = {}, 0
    os.makedirs(a.out, exist_ok=True)
    for it in items:
        r = convert(os.path.join(a.src, str(it['sid'])), os.path.expanduser(it['path']), os.path.join(a.out, str(it['sid']), '03-parts'), a.prompt_set, ctxs.get(str(it['sid'])))
        res[str(it['sid'])] = r
        bad += 0 if r['ok'] else 1
        print(('ok  ' if r['ok'] else 'ОТКАЗ'), it['sid'], r['reason'])
    json.dump(res, open(os.path.join(a.out, 'convert-report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'итого: {len(items) - bad} из {len(items)}, отказов {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
