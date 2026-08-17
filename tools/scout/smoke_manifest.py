#!/usr/bin/env python3
"""Манифест быстрого смоука (ускорение 17.08, Codex п.Б): детерминированное подмножество сцен —
покрытие room_mode × контур × проёмы (по 1–2 на класс), семантические ветки, все сертифицированные
MEDIA_MISSING, сцены из замечаний владельца. Отдельно perf-smoke — 3 самые тяжёлые (по duration_s
из последнего полного отчёта). Смоук — ОБРАТНАЯ СВЯЗЬ, не гейт закрытия пакета: полный экзамен
(272) — перед коммитом и ночью по cron.

  smoke_manifest.py            # печатает состав и пишет smoke-manifest.json / perf-manifest.json
"""
from __future__ import annotations

import collections
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

# сцены владельца (галерея №N → id): открытые замечания + по одному репро на закрытый класс бага
OWNER_SCENES = ['set1-bay', 'set8-base', 'set9-pylons', 'set10-base', 'set16-base', 'set28-base',
                'set26-base', 'set30-base', 'set31-bay', 'set91-base', 'set92-base', 'set95-base',
                'set14-base', 'set57-pylons', 'set87-pylons']
# семантические ветки (угловой диван, пара по сторонам, U, два дивана, compact+quiet, инсталляция,
# камин, столовая остров/край, окно-вейвер) — сцены, где эти ветки наблюдались в экзаменах
SEMANTIC_SCENES = ['set102-base', 'set106-base', 'set111-pylons', 'set119-base', 'set67-base',
                   'set74-long', 'set99-base', 'set126-base', 'set25-bay', 'set47-base', 'set39-base',
                   'set18-long', 'set122-base', 'set80-r23', 'set13-bay', 'set36-base']
MEDIA_MISSING = ['set21-mirL', 'set21-mirR', 'set80-L']
PERF_FALLBACK = ['set102-base', 'set105-pylons', 'set120-base']


def _cls(s, sets):
    m2 = sets[s['set'] - 1]['m2']
    mode = 'small' if m2 < 20 else ('trans' if m2 < 25 else ('large' if m2 < 40 else 'xl'))
    suf = s['id'].split('-', 1)[1] if '-' in s['id'] else 'base'
    return (mode, re.sub(r'\d+', '', suf), 'custom' if s.get('openings') else 'std')


def build() -> tuple[list[str], list[str]]:
    scenes = json.load(open(os.path.join(HERE, 'acceptance-scenes.json'), encoding='utf-8'))
    sets = json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8'))
    ids = {s['id'] for s in scenes}
    by = collections.defaultdict(list)
    for s in scenes:
        by[_cls(s, sets)].append(s['id'])
    chosen: list[str] = []
    for k in sorted(by):                       # покрытие: 1 сцена на класс (детерминированно — первая),
        chosen.append(by[k][0])                # для базовых классов (base/long) — вторая тоже
        if k[1] in ('base', 'long') and k[0] in ('small', 'trans') and len(by[k]) > 1:
            chosen.append(by[k][len(by[k]) // 2])      # вторая — только в дешёвых режимах (XL по 5–8 мин)
    for x in SEMANTIC_SCENES + MEDIA_MISSING + OWNER_SCENES:
        if x in ids and x not in chosen:
            chosen.append(x)
    # perf: по duration_s из последнего полного отчёта, иначе fallback
    perf = []
    rep = os.path.join(HERE, 'acceptance-report-zoned.jsonl')
    try:
        durs = []
        for line in open(rep, encoding='utf-8'):
            r = json.loads(line)
            if r.get('duration_s'):
                durs.append((r['duration_s'], r['scene']))
        perf = [s for _, s in sorted(durs, reverse=True)[:3]]
    except Exception:
        pass
    if not perf:
        perf = [x for x in PERF_FALLBACK if x in ids]
    chosen = [c for c in chosen if c not in perf]  # тяжёлые — не в смоуке (Codex: 7–9 мин ломают «≈5 мин»)
    json.dump(chosen, open(os.path.join(HERE, 'smoke-manifest.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    json.dump(perf, open(os.path.join(HERE, 'perf-manifest.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    return chosen, perf


if __name__ == '__main__':
    ch, pf = build()
    print(f'smoke: {len(ch)} сцен → smoke-manifest.json; perf: {pf} → perf-manifest.json')
    print(', '.join(ch))
