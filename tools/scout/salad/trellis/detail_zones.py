#!/usr/bin/env python3
"""Зоны деталей и стекла/проёмов для 07 (T-20261123-47/4; правила R-DETAIL-EXCLUSIONS-07 и R-OPENINGS-ZONES-07; план `.memory_bank/plans/type-rules-code-01.md` § А).

ЗАЧЕМ. Паспорт типа (`paint.hidden_exclusions`, `paint.openings`) говорит, что НЕ переносить с лица на невидимое: ручки, рельеф дверей, пуговицы, подушки, стекло. Здесь — ЧИСТАЯ функция:
по текстуре в Lab, известным текселям, карте частей, ролям частей этапа 3, политике типа и карточке товара → маски зон (T×T bool по геометриям) и отчёт «зона | воздержание + причина».
Хуки 07 (выкинуть зону из статистики/пула/доноров и из переноса) — отдельный шаг поверх этого модуля. Известные фото-тексели зона НЕ перезаписывает: это только маска «деталь».

ИСТОЧНИКИ (в отчёте у каждой зоны — `source`):
  Z1 — роль части этапа 3 (handles → фурнитура фасада, facade → рельеф двери, роль канала стекла из карточки → стекло); сейчас приходит редко (перепись S0: handles/glass_mirror = 0);
  Z2/Z3 — по ТЕКСТУРЕ известного (фото): компактные пятна чужого тона (пуговицы, ручки) и часть другого тона (подушка); «параметры карточки» — стекло по парам (ключ, значение).
Пороги — `tools/scout/rules/detail-zones.json`; в коде нет чисел порогов и ID товаров. Нет данных → воздержание с кодом причины (не «нет зоны = всё хорошо»).
  import detail_zones as DZ
  r = DZ.detail_zones(lab, known, part_map, roles, policy, card, rules)   # → {'zones': {вид: [bool T×T]}, 'any': [bool T×T], 'report': {вид: {...}}}
  DZ.rule_entries(role, r)                                                  # → записи extra.rules[] (через rule_record.entry)
Запуск тестов: python tools/scout/salad/trellis/tests_detail_zones.py"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..', '..'))
RULES_PATH = os.path.join(ROOT, 'tools', 'scout', 'rules', 'detail-zones.json')
RULE_DETAIL = 'R-DETAIL-EXCLUSIONS-07'
RULE_OPEN = 'R-OPENINGS-ZONES-07'


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def glass_channels(card: dict | None, rules: dict) -> list:
    """Стекло по ПАРАМ карточки (не по слову во всём тексте): ключ «Материал …» со значением стекл*/зеркал* → канал материала (ножки, столешница, фасад…, `unknown` — канал не распознан);
    ключ «Наличие зеркал» — только при значении, не означающем «нет». → список каналов, [] — карточка стекла не называет."""
    g = rules['glass']
    out = []
    for k, v in (card or {}).items():
        key, val = str(k).lower(), str(v).lower()
        has = any(w in val for w in g['words'])
        if key.startswith(g['key_prefix'].lower()) and has:
            ch = next((c for w, c in g['channels'].items() if w in key), 'unknown')
            out.append(ch)
        elif any(key.startswith(p.lower()) for p in g['presence_keys']) and not any(n in val for n in g['negatives']) and val.strip():
            out.append('mirror')
    return sorted(set(out))


def _de(a, b) -> np.ndarray:
    return np.linalg.norm(np.asarray(a, np.float64) - np.asarray(b, np.float64), axis=-1)


def _blobs(mask: np.ndarray, area: int, c: dict) -> list:
    """Связные (8) пятна маски, прошедшие отбор по размеру (доля площади карты), плотности в рамке и вытянутости → [(метка-маска, h, w, fill)]."""
    from scipy import ndimage as ndi
    lab, n = ndi.label(mask, structure=np.ones((3, 3)))
    out = []
    if not n:
        return out
    sz = ndi.sum(mask, lab, range(1, n + 1))
    for i, sl in enumerate(ndi.find_objects(lab), start=1):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        s = float(sz[i - 1]) / area
        fill = float(sz[i - 1]) / float(h * w)
        asp = max(h, w) / float(min(h, w))
        if c['min_share'] <= s <= c['max_share'] and fill >= c['min_fill'] and asp <= c['max_aspect']:
            out.append((lab == i, asp, fill))
    return out


def _dark_peaks(L: np.ndarray, known_g: np.ndarray, c: dict) -> np.ndarray:
    """Точечные тёмные ямки на известном (пуговицы): локальные минимумы разности гауссианов яркости L (узкое минус широкое) глубже −dog_min и глубже ratio_min × локальной «ряби» (сглаженный |dog|, окно rough_sigma):
    на гладкой обивке ямка выделяется, на узоре/фактуре рябь высокая — ямка тонет. От края известного — отступ 1,5 широкого сглаживания. → bool-маска пиков (по одному тексельному пику на ямку)."""
    from scipy import ndimage as ndi
    s1, s2 = c['dog']
    inner = known_g & ndi.binary_erosion(known_g, iterations=int(round(s2 * 1.5)))
    dog = ndi.gaussian_filter(L, s1) - ndi.gaussian_filter(L, s2)
    rough = ndi.gaussian_filter(np.abs(dog), float(c['rough_sigma']))
    pk = inner & (dog == ndi.minimum_filter(dog, size=int(c['peak_size']))) & (dog <= -float(c['dog_min']))
    return pk & (-dog >= float(c['ratio_min']) * np.maximum(rough, 1e-3))


def _outliers(lab_g: np.ndarray, known_g: np.ndarray, part_g: np.ndarray, dE_min: float, sigma: float, min_known: int) -> np.ndarray:
    """Тексели известного, чей тон (Lab, лёгкое сглаживание `sigma`) дальше `dE_min` от медианы СВОЕЙ части; части с известным < min_known — не меряем."""
    from scipy import ndimage as ndi
    sm = np.stack([ndi.gaussian_filter(lab_g[..., i], sigma) for i in range(3)], -1) if sigma > 0 else lab_g
    out = np.zeros(known_g.shape, bool)
    for p in np.unique(part_g[known_g]):
        m = known_g & (part_g == p)
        if int(m.sum()) < min_known:
            continue
        out |= m & (_de(sm, np.median(lab_g[m], axis=0)) >= dE_min)
    return out


def detail_zones(lab: list, known: list, part_map: list, roles: dict, policy: dict, card: dict | None, rules: dict | None = None) -> dict:
    """lab — по геометриям (T,T,3) Lab текстуры 06; known — (T,T) bool фото-правда; part_map — (T,T) номер части в текселе (−1 вне развёртки); roles — {часть: роль этапа 3};
    policy — `mesh_type_passports.paint_policy(role)` (нужны `exclusions`, `openings`); card — карточка товара (плоский словарь параметров). Что просит паспорт — то и ищем: остальное не трогаем."""
    R = rules or load_rules()
    n = len(lab)
    want = list(policy.get('exclusions') or []) + [o for o in (policy.get('openings') or []) if o not in (policy.get('exclusions') or [])]
    zones = {k: [np.zeros(known[g].shape, bool) for g in range(n)] for k in want}
    rep = {k: {'status': 'abstain', 'source': None, 'texels': 0, 'share': 0.0, 'reason': None} for k in want}
    role_of = lambda p: roles.get(p, roles.get(str(p)))  # noqa: E731
    area = [int((np.asarray(part_map[g]) >= 0).sum()) or 1 for g in range(n)]
    total = float(sum(area))

    def put(kind, src, per_geom, note=None):
        t = sum(int(m.sum()) for m in per_geom)
        if t == 0:
            return False
        for g in range(n):
            zones[kind][g] |= per_geom[g]
        r = rep[kind]
        r.update(status='zone', source=(r['source'] + '+' + src) if r['source'] and src not in r['source'] else src, texels=sum(int(z.sum()) for z in zones[kind]),
                 share=round(sum(int(z.sum()) for z in zones[kind]) / total, 5))
        if note:
            r['note'] = note
        return True

    def role_zone(roles_want):
        return [np.isin(np.asarray(part_map[g]), [p for p in {int(x) for x in np.unique(part_map[g]) if x >= 0} if role_of(p) in roles_want]) for g in range(n)]

    # --- Z1: роли частей этапа 3
    if 'facade_hardware' in want:
        put('facade_hardware', 'Z1:роль handles', role_zone(R['roles']['facade_hardware']))
    if 'door_relief' in want:
        if not put('door_relief', 'Z1:роль facade', role_zone(R['roles']['door_relief'])):
            rep['door_relief']['reason'] = 'no_facade_part'
    # --- стекло: по ПАРАМ карточки (+ роль части канала); проёмы-«стекло» и исключение «glass» — одна зона
    gl_kinds = [k for k in ('glass',) if k in want]
    if gl_kinds:
        chans = glass_channels(card, R)
        if not chans:
            rep['glass']['reason'] = 'no_glass_source'
        else:
            wr = {r for ch in chans for r in R['glass']['channel_roles'].get(ch, [])}
            if not put('glass', 'params:' + ','.join(chans), role_zone(wr)):
                rep['glass']['reason'] = 'no_glass_part'
                rep['glass']['channels'] = chans
    # --- Z3: пятна чужого тона (пуговицы, ручки) на известном
    blobs_for = [k for k in ('buttons', 'facade_hardware') if k in want]
    if blobs_for:
        bc = R['blob']
        found = []
        for g in range(n):
            mk = _outliers(np.asarray(lab[g], np.float64), np.asarray(known[g], bool), np.asarray(part_map[g]), bc['dE_min'], bc['sigma'], bc['min_known'])
            for m, asp, fill in _blobs(mk, int(np.asarray(known[g]).size), bc):
                found.append((g, m, asp, fill))
        if 'buttons' in want:
            bt = R['buttons']
            pks = [_dark_peaks(np.asarray(lab[g], np.float64)[..., 0], np.asarray(known[g], bool), bt) for g in range(n)]
            k = sum(int(m.sum()) for m in pks)
            if bt['min_count'] <= k <= bt['max_count']:
                from scipy import ndimage as ndi
                put('buttons', 'Z3:тёмные точки (локальный контраст)', [ndi.binary_dilation(m, iterations=int(bt['dilate'])) for m in pks], note=f'точек {k}')
            else:
                rep['buttons']['reason'] = 'no_evidence' if k < bt['min_count'] else 'texture'
                rep['buttons']['note'] = f'точек {k}, нужно {bt["min_count"]}…{bt["max_count"]} (больше — узор/фактура, не пуговицы)'
        if 'facade_hardware' in want and rep['facade_hardware']['status'] != 'zone':
            hd = R['hardware']
            pg = [np.zeros(known[g].shape, bool) for g in range(n)]
            k = 0
            for g, m, asp, fill in found:
                if asp <= hd['max_aspect'] and fill >= hd['min_fill']:
                    pg[g] |= m
                    k += 1
            if k >= hd['min_count']:
                put('facade_hardware', 'Z3:пятна чужого тона', pg, note=f'пятен {k}')
            else:
                rep['facade_hardware']['reason'] = 'no_evidence'
    # --- Z2+тон: подушка — часть другого тона, не из служебных ролей, доля в пределах
    if 'pillows' in want and R['pillows'].get('enabled'):
        pc = R['pillows']
        cnt, med = {}, {}
        for g in range(n):
            pm, kk, lb = np.asarray(part_map[g]), np.asarray(known[g], bool), np.asarray(lab[g], np.float64)
            for p in {int(x) for x in np.unique(pm) if x >= 0}:
                m = pm == p
                cnt[p] = cnt.get(p, 0) + int(m.sum())
                km = m & kk
                if int(km.sum()) >= R['blob']['min_known']:
                    med.setdefault(p, []).append(lb[km])
        med = {p: np.median(np.concatenate(v), axis=0) for p, v in med.items()}
        body = [p for p in cnt if role_of(p) not in pc['roles_skip'] and p in med]
        cand = []
        if body:
            main = max(body, key=lambda p: cnt[p])
            for p in body:
                s = cnt[p] / total
                if p != main and pc['share'][0] <= s <= pc['share'][1] and float(_de(med[p], med[main])) >= pc['dE_min']:
                    cand.append(p)
        if cand:
            put('pillows', 'Z2:часть другого тона', [np.isin(np.asarray(part_map[g]), cand) for g in range(n)], note=f'частей {len(cand)}')
        else:
            rep['pillows']['reason'] = 'no_evidence'
    for k in want:                                                          # то, что не умеем: честное воздержание
        if rep[k]['status'] != 'zone' and rep[k]['reason'] is None:
            rep[k]['reason'] = 'not_implemented' if k in R['not_implemented'] else 'no_evidence'
    anyz = [np.zeros(known[g].shape, bool) for g in range(n)]
    for k in want:
        for g in range(n):
            anyz[g] |= zones[k][g]
    return {'zones': zones, 'any': anyz, 'report': rep, 'wanted': want}


def rule_entries(role: str | None, res: dict, extra_reason: str = '') -> list:
    """Записи extra.rules[] (формат `rule_record.entry`, одна функция на все этапы): R-DETAIL-EXCLUSIONS-07 — по исключениям паспорта, R-OPENINGS-ZONES-07 — по проёмам/стеклу.
    applied — найдена хоть одна зона; иначе воздержание с причинами по видам (no_evidence / no_glass_source / …)."""
    scout = os.path.join(ROOT, 'tools', 'scout')
    if scout not in sys.path:
        sys.path.insert(0, scout)
    import rule_record as RR  # noqa: PLC0415
    rep, out = res['report'], []
    R = load_rules()
    for rid, kinds in ((RULE_DETAIL, [k for k in res['wanted'] if k in R['exclusion_kinds']]), (RULE_OPEN, [k for k in res['wanted'] if k in R['opening_kinds']])):
        if not kinds:
            out.append(RR.entry(rid, role, False, 'паспорт типа не просит ' + ('исключений' if rid == RULE_DETAIL else 'проёмов/стекла')))
            continue
        got = [k for k in kinds if rep[k]['status'] == 'zone']
        if got:
            out.append(RR.entry(rid, role, True, '; '.join(f'{k}:{rep[k]["source"]}' for k in got)))
        else:
            out.append(RR.entry(rid, role, False, '; '.join(f'{k}:{rep[k]["reason"]}' for k in kinds)))
    return out
