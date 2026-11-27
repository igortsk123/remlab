#!/usr/bin/env python3
"""T-99/12 шаг 2 (Fable 19 §3): образец библиотеки выбирается ПО РИСУНКУ фото (три числа «паспорта рисунка»: ясность линий, длина штриха, доля крупного — `pattern_passport.py`),
а не по тону: тон красит Ш4а, из образца берётся только светлое-тёмное (узор нулевого среднего). Раньше `library_bin` брал ближайший по тону → гладкий образец с ясностью 0,42 против 0,79 на фото.
Один образец на материал товара: части с одним материалом карточки (поле роли) берут образец по паспорту самой крупной части, которую фото видит в лоб; у частей без паспорта — тот же образец.
Выкл (`rules.pattern_pick.enabled=false`, по умолчанию) — этот модуль не вызывается, путь «по тону» байт в байт как раньше. ID товаров в коде нет."""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..', '..'))
if SCOUT not in sys.path:
    sys.path.insert(0, SCOUT)

_LIB_PASS: dict = {}


def _pp():
    import pattern_passport as PP
    return PP


def library_passports(ppc: float, classes: list, tile_fallback_cm: float) -> dict:
    """Паспорт каждого образца класса из `classes` (семейство «дерево») при масштабе кадра ppc (px/см): образец ужимается/растягивается до физического размера плитки. {имя: паспорт + 'sigma'}."""
    import cv2
    import part_grain as PG
    import top_prior as TP
    PP = _pp()
    R = PP.load_rules()
    key = (round(float(ppc), 2), tuple(sorted(classes)), float(tile_fallback_cm))
    if key in _LIB_PASS:
        return _LIB_PASS[key]
    lib = PG._library(TP.load_rules())
    out = {}
    for name, v in lib['items'].items():
        if v.get('family', 'wood') != 'wood' or v.get('pattern_class', 'straight') not in classes:
            continue
        pat, std = PG.pattern_of_bin(name, v.get('grain_axis'))
        tile = float((v.get('tile_cm') or [0])[0] or tile_fallback_cm)
        n = max(64, int(round(tile * ppc)))
        im = cv2.resize(np.asarray(pat, np.float32) + 50.0, (n, n), interpolation=cv2.INTER_AREA if n < pat.shape[0] else cv2.INTER_CUBIC)
        pp = PP.passport(im, np.ones((n, n), bool), ppc, None, R)
        if pp is not None:
            out[name] = dict(pp, sigma=round(float(std), 3))
    _LIB_PASS[key] = out
    return out


def group_passports(L_frame, valid, ids, cos_f, face_group, roles, face_ny, ppc: float, L_nosh=None, cos_min: float = 0.3) -> dict:
    """Паспорт рисунка фото по группам на кадре 04 (как `group_photo_sigma`): верх (роль top) — грани вверх (|n_y|>0.8), остальные — грани к камере (cos ≥ cos_min).
    Доля крупного — по фото без теней (`L_nosh`, этап 05), если оно есть. {id группы: паспорт | None}."""
    PP = _pp()
    R = PP.load_rules()
    nF = len(face_group)
    fid = np.clip(ids, 0, nF - 1)
    gpix = np.where(valid & (ids >= 0), np.asarray(face_group)[fid], -1)
    out = {}
    for g, role in enumerate(roles):
        m = gpix == g
        m = m & (np.abs(np.asarray(face_ny)[fid]) > 0.8) if role == 'top' else m & (cos_f >= cos_min)
        pp = PP.passport(L_frame, m, ppc, None, R) if m.any() else None
        if pp is not None and L_nosh is not None:
            pd_ = PP.passport(L_nosh, m, ppc, pp['angle'], R)
            if pd_ is not None:
                pp = dict(pp, coarse=pd_['coarse'], coarse_with_shadows=pp['coarse'])
        out[g] = pp
    return out


def material_key(p: dict, rules: dict) -> str:
    """Ключ материала части по полю карточки её роли (как в wood_always); нет роли/поля — своя группа (общего материала не утверждаем)."""
    import part_grain_measure as PGM
    pm = rules.get('pattern_measure')
    if not pm:
        import part_grain as PG
        pm = PG.load_rules()['pattern_measure']
    prm = dict(rules, pattern_measure=pm)
    role, _src = PGM.part_role(p, prm)
    rf = PGM.role_field(p.get('card'), role, prm)
    if rf['status'] != 'ok' or not rf['text']:
        return 'group:%s' % p['id']
    import re
    return ' '.join(sorted(re.findall(r'[а-яёa-z]+', rf['text'].lower())))


def pick(parts: list, passports: dict, rules: dict, ppc: float) -> dict:
    """{id части: {'bin', 'dist', 'source': 'own'|'material', 'from': id части-образца паспорта, 'passport': паспорт фото, 'sample': паспорт образца, 'key'}}.
    Образец — ближайший по расстоянию паспортов (rules/pattern-passport.json pick.weights) среди образцов класса из rules.pattern_pick.classes; образец, которому не хватает σ до σ фото
    при amp_max, штрафуется (чтобы сильный рисунок фото не упирался в потолок). Частям без паспорта — образец той же группы материала (нет паспортов у материала — части не в ответе → путь по тону)."""
    PP = _pp()
    R = PP.load_rules()
    cfg = rules['pattern_pick']
    lib = library_passports(ppc, list(cfg['classes']), float(cfg.get('tile_fallback_cm', 40.0)))
    if not lib:
        return {}
    keys = {p['id']: material_key(p, rules) for p in parts}
    by_key: dict = {}
    for p in parts:
        by_key.setdefault(keys[p['id']], []).append(p)
    res = {}
    for k, ps in by_key.items():
        seen = [p for p in ps if passports.get(p['id'])]
        if not seen:
            continue
        rep = max(seen, key=lambda p: passports[p['id']]['n_px'])
        ph = passports[rep['id']]
        sg = rep.get('photo_sigma')
        best = None
        for name, sp in lib.items():
            d = PP.distance(sp, ph, R)
            if sg and sp['sigma'] > 0:
                need = float(sg) / sp['sigma']
                if need > float(rules['amp_max']):
                    d += float(cfg.get('amp_penalty', 1.0)) * float(np.log(need / float(rules['amp_max'])))
            if best is None or d < best[0]:
                best = (d, name)
        for p in ps:
            own = passports.get(p['id']) is not None
            res[p['id']] = {'bin': best[1], 'dist': round(float(best[0]), 3), 'source': 'own' if own and p['id'] == rep['id'] else 'material', 'from': rep['id'], 'key': k,
                            'passport': {x: ph[x] for x in ('clarity', 'stroke_cm', 'coarse')}, 'sample': {x: lib[best[1]][x] for x in ('clarity', 'stroke_cm', 'coarse')}}
    return res
