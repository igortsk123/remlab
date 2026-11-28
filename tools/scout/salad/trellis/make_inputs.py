#!/usr/bin/env python3
"""ВХОДЫ ФОРМЫ (T-20261118-91; с T-20261127-175/9 — на ЕДИНОМ МОДУЛЕ ВЫРЕЗКИ): вырезка товара `salad/cutout_one.py` (полная BiRefNet на процессоре с закреплённой ревизией весов →
`chain_shape`-цепочка: гибрид, связность, дыры, щели, студийный белый фон, вычитатель, мягкий край → шаг «главный предмет у стульев» (только роль «стул»)).
Шаг «хвосты у пола» из цепочки УБРАН (срезал настоящие ножки, решение Fable 27.11): здесь он только считается — `info['attached_prune_would']`, маску не меняет.
ФОТО: вход формы строится по фото ВЫСОКОГО разрешения — адрес `img_hd` первым, затем обычный `img`, затем адрес из набора (замечание Fable 27.11 к 9.1–9.3: смена названа явно).
Раньше здесь шла СТАРАЯ цепочка `preprocess._cut_chain` и своя копия `cpu_cutout` без ревизии весов; перенос из `t178-forms-1122/make_cut_v2.py` (образец «последнего» способа).

ПРОИСХОЖДЕНИЕ. Рядом с вырезкой пишется метка (`salad/cutout_origin.py`): способ и версия цепочки, набор шагов, источник маски и версия весов, версия кода, sha256 фото, sha256
содержимого вырезки, дата — в `inputs.json` (поле `origin`) И текстовым блоком `remlab.origin` внутри самого PNG. `trellis_trial.py` без актуальной метки платный запуск не начинает.

ЗАЧЕМ ОДИН ВХОД. Сравнение моделей честно только на ОДНОЙ и той же вырезке: отдаём её и TRELLIS.2, и Hunyuan 2.1 для пары. Хеш файла (`input_png_sha256`) и адрес фото пишутся в
`inputs.json` — в отчёте пробы он обязан быть.

Отказ товара (вход НЕ пишется, в `inputs.json` — `error`): нет адреса фото, сбой гибридной маски (гибрид обязателен — срезанное с фото в меше не появится), коллаж/негодная маска,
вырезка мельче правила размера (`mesh_photo.check_size`), исключение.

  ~/venvs/scout/bin/python make_inputs.py --out ~/remlab-logs/mesh-models-1118/trellis/inputs 112923:13224664101879413845 [...]
  (тяжёлое — под `tools/ops/heavy-slot.sh`; сеть — только фото магазина, ключей не читает; потоки — THREADS, по умолчанию 12)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.dirname(HERE)
sys.path.insert(0, SALAD)
sys.path.insert(0, os.path.dirname(SALAD))        # tools/scout — catalog_media, mesh_queue, mesh_photo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('skus', nargs='*', help='mid:eid')
    ap.add_argument('--out', required=True)
    ap.add_argument('--role', default=None)
    ap.add_argument('--set', help='JSON набора (select_set30.py): список {sku, role, name, hard}; роль берётся ПО ТОВАРУ — как у боевого конвейера')
    a = ap.parse_args()
    import catalog_media as CM
    import cutout_one as CO1
    import cutout_origin as CO
    import mesh_photo as MP
    import preprocess as PRE
    rules = MP.load_rules()
    os.makedirs(a.out, exist_ok=True)
    meta = {c['sku']: c for c in json.load(open(a.set, encoding='utf-8'))} if a.set else {}
    skus = a.skus or list(meta)
    jp = os.path.join(a.out, 'inputs.json')
    prev = json.load(open(jp, encoding='utf-8')) if os.path.exists(jp) else {}      # возобновление: готовые вырезки с АКТУАЛЬНОЙ меткой не пересчитываем
    res = {}
    for sku in skus:
        mid, eid = sku.split(':', 1)
        role = meta.get(sku, {}).get('role') or a.role
        name = sku.replace(':', '_')
        png = os.path.join(a.out, name + '.rgba.png')
        p = prev.get(sku)
        if p and p.get('input_png_sha256') and os.path.exists(png) and CO.check_png(png, p) == []:
            res[sku] = {**p, 'name': meta.get(sku, {}).get('name') or p.get('name'), 'hard': meta.get(sku, {}).get('hard', p.get('hard'))}
            print(f'{sku}: уже есть (метка актуальна), хеш {p["input_png_sha256"][:16]} — пропуск', flush=True)
            continue
        m = CM.media(mid, eid) or {}
        url = m.get('img_hd') or m.get('img') or meta.get(sku, {}).get('image_url')        # кровати спальни — не в products: адрес фото берём из набора
        if not url:
            print(f'!! {sku}: адреса фото нет — пропуск', flush=True)
            res[sku] = {'error': 'no_image_url'}
            continue
        try:
            raw = PRE.fetch(url)
            shape, cut, info, origin = CO1.make_input(raw, role)
        except Exception as e:  # noqa: BLE001 — один плохой товар не должен класть набор из 30
            print(f'!! {sku}: вырезка упала — {type(e).__name__}: {str(e)[:120]}', flush=True)
            res[sku] = {'error': f'{type(e).__name__}: {str(e)[:120]}', 'image_url': url}
            continue
        he = MP.hybrid_error(info)
        good, why = MP.check_size(list(cut.size), rules)
        refused = (f'сторож размера: {why}' if not good else f'сбой гибридной маски: {he}' if he
                   else f'маска не годна: {info.get("reason")}' if info.get('verdict') == 'bad' else None)
        if refused:
            print(f'!! {sku}: {refused} — вход не пишем', flush=True)
            cut.save(os.path.join(a.out, f'{name}.cut-preview.png'))          # обрезанную копию — чтобы видно причину
            res[sku] = {'error': refused, 'image_url': url, 'role': role}
            continue
        data = CO.png_bytes(shape, origin)                                    # PNG с меткой `remlab.origin` внутри
        sha = hashlib.sha256(data).hexdigest()
        open(png, 'wb').write(data)
        cut.save(os.path.join(a.out, f'{name}.cut-preview.png'))
        res[sku] = {'role': role, 'name': meta.get(sku, {}).get('name'), 'hard': meta.get(sku, {}).get('hard'), 'image_url': url, 'input_png_sha256': sha,
                    'input_hash_generator': origin['photo_sha256'][:16], 'size': list(shape.size), 'origin': origin,
                    'mask': {k: info.get(k) for k in ('verdict', 'reason') if k in info}}
        print(f'{sku}: {shape.size} sha256 {sha[:16]} маска {res[sku]["mask"]} цепочка {origin["chain_version"]} шаги {origin["steps"]}', flush=True)
    json.dump(res, open(os.path.join(a.out, 'inputs.json'), 'w'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
