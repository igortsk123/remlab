#!/usr/bin/env python3
"""ЦЕНА МЕША ПО ГРУППАМ — за скользящие сутки (план mesh-15, владелец 21.10: «меш не дороже 1,5 рубля»).

ЗАЧЕМ. Цену меша портит не тариф, а сбои и простой: 3090 до ~13.10 давала 1,0–1,8 ₽, после — 2,1–3,1 ₽ при тех же $ в
час (`domain/mesh-pool-ops.md` § 5), A5000 — 0,78–0,80 ₽. Общий сторож денег ловит только «платим и ничего не выдаём»;
группа, которая выдаёт, но втрое дороже, жила неделями. Здесь — одна цифра на группу: деньги / новые меши.

  деньги группы  = рабочие нодо-минуты из переписи пула (`mesh-pool-census.jsonl`, строка на тик сторожа, поле `running`)
                   × тариф группы (`rules/salad-groups.json` → `prices_usd_h`) × курс `usd_rub` оттуда же;
  новые меши     = первый ok каждого job_id (хвост `prefix`), попавший в окно; повторы готовых — не меши (урок 523);
  правило        = `price_ceiling` в том же файле: потолок, окно, «судить после N рабочих нодо-часов группы».

Мало данных (меньше judge_after_node_h рабочих нодо-часов группы в окне, сумма по машинам) — не судим: цена на 3–5 мешах —
шум («рубль двадцать / рубль семьдесят», владелец 21.10), судим по средней за длинный отрезок. Отработала столько и 0 мешей —
дорого. Быстрый случай «платим и ничего не выдаём» ловят прежние правила сторожа денег, этот суд их не заменяет.
Модуль ничего не гасит — только считает; гасит `money_guard.py`, показывает `pipeline_map.py`.

  ~/venvs/scout/bin/python mesh_price.py [--at <unix>]   # ₽ за меш по группам за сутки до `at` (по умолчанию — сейчас)
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import salad_groups as SG  # noqa: E402

CENSUS = os.path.join(HERE, '..', 'mesh-pool-census.jsonl')
JOURNAL = os.path.join(HERE, '..', 'mesh-run-progress.jsonl')
TICK_S = float(os.environ.get('MESH_GUARD_TICK_S', '300'))   # шаг переписи = тик сторожа денег


def _rows_since(path: str, since: float) -> list[dict]:
    """Строки jsonl с `at` ≥ since. Перепись — десятки МБ: читаем с хвоста кусками, пока не дошли до строки старше окна."""
    try:
        f = open(path, 'rb')
    except FileNotFoundError:
        return []
    with f:
        size, chunk = f.seek(0, 2), 1 << 18
        while True:
            start = max(0, size - chunk)
            f.seek(start)
            lines = f.read().split(b'\n')
            if start:
                lines = lines[1:]                     # первая строка куска — обрезок
            first = None
            for ln in lines:
                try:
                    first = json.loads(ln)
                    break
                except ValueError:
                    continue
            if start == 0 or (first and float(first.get('at') or 0) < since):
                break
            chunk *= 4
    out = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if float(r.get('at') or 0) >= since:
            out.append(r)
    return out


def spend_node_min(since: float, until: float, census: str = CENSUS, tick_s: float = TICK_S) -> dict[str, float]:
    """Рабочие нодо-минуты по группам за [since, until] — так же, как книга расходов сторожа: `running` × тик. Строку,
    пришедшую раньше чем через полтика после учтённой (финальная точка переписи при гашении), не считаем дважды."""
    out: dict[str, float] = {}
    last: dict[str, float] = {}
    for r in sorted(_rows_since(census, since), key=lambda r: float(r.get('at') or 0)):
        at, g = float(r.get('at') or 0), str(r.get('group') or '')
        if at > until or not g:
            continue
        if at - last.get(g, -1e18) < tick_s / 2:
            continue
        last[g] = at
        run = r.get('running') or 0
        if run > 0:
            out[g] = out.get(g, 0.0) + run * tick_s / 60.0
    return out


def new_meshes(since: float, until: float, journal: str = JOURNAL) -> dict[str, int]:
    """Новые готовые меши по группам за [since, until]: первый ok каждого job_id (хвост `prefix`; без него — sku+seed).
    Тот же job_id второй раз — оплаченный повтор, не меш (урок 523, `money_guard.repeats`)."""
    first: dict[str, dict] = {}
    try:
        with open(journal, encoding='utf-8') as f:
            for line in f:
                if '"ok"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get('status') != 'ok':
                    continue
                j = str(r.get('prefix') or '').rsplit('/', 1)[-1] or f'{r.get("sku")}#{r.get("seed")}'
                if j not in first or float(r.get('at') or 0) < float(first[j].get('at') or 0):
                    first[j] = r
    except FileNotFoundError:
        return {}
    out: dict[str, int] = {}
    for r in first.values():
        if since <= float(r.get('at') or 0) <= until:
            g = str(r.get('group') or '?')
            out[g] = out.get(g, 0) + 1
    return out


def verdict(node_min: float, usd_h: float | None, usd_rub: float, meshes: int, rule: dict) -> dict:
    """Суд одной группы. Чистая функция: state — 'дорого' | 'дёшево' | 'мало данных' | 'нет тарифа' | 'нет правила'."""
    ceil = float(rule.get('rub_per_mesh') or 0)
    if not ceil:
        return {'state': 'нет правила', 'rub': None, 'per_mesh': None, 'meshes': meshes}
    if not usd_h:
        return {'state': 'нет тарифа', 'rub': None, 'per_mesh': None, 'meshes': meshes}
    rub = node_min / 60.0 * usd_h * usd_rub
    per = rub / meshes if meshes else None
    if node_min / 60.0 < float(rule.get('judge_after_node_h') or 4):
        state = 'мало данных'
    else:
        state = 'дорого' if per is None or per > ceil else 'дёшево'
    return {'state': state, 'rub': round(rub, 2), 'per_mesh': None if per is None else round(per, 2), 'meshes': meshes,
            'ceil': ceil}


def by_group(groups: list[str] | None = None, now: float | None = None, floor: dict | None = None,
             census: str = CENSUS, journal: str = JOURNAL) -> dict[str, dict]:
    """₽ за меш по группам за окно правила (по умолчанию 24 ч) до `now`. `floor` — {группа: unix}: окно группы не раньше
    этой отметки (после снятия запрета цены судим заново, а не по тем же суткам, за которые погасили). Без `groups` —
    все группы, что тратили или делали меши в окне."""
    now = now or time.time()
    rule = SG.price_ceiling()
    window = float(rule.get('window_h') or 24) * 3600
    since = now - window
    spend = spend_node_min(since, now, census)
    made = new_meshes(since, now, journal)
    for g, t in (floor or {}).items():                    # у кого окно короче — пересчитать отдельно
        if float(t) > since:
            spend[g] = spend_node_min(float(t), now, census).get(g, 0.0)
            made[g] = new_meshes(float(t), now, journal).get(g, 0)
    gs = groups if groups is not None else sorted(set(spend) | set(made))
    rate = SG.usd_rub()
    out = {g: dict(verdict(spend.get(g, 0.0), SG.price(g), rate, made.get(g, 0), rule),
                   node_min=round(spend.get(g, 0.0), 1)) for g in gs}
    # СУД ПО ПОЛНЫМ ЧАСАМ РАБОТЫ (владелец 23.10, T-20261022-10/4: «стату считай по полным 8 часам работы»): `judge_after_h` —
    # не судить, пока окно группы (от `floor`: первый тик, гашение или снятие запрета) короче стольких часов по часам на стене.
    # Нодо-часы набираются за минуты при 20–30 машинах, а ночь, текучка и прогрев видны только на длинном отрезке
    after_h = float(rule.get('judge_after_h') or 0)
    for g, v in out.items():
        start = max(since, float((floor or {}).get(g, since)))
        if after_h and (now - start) / 3600 < after_h and v['state'] in ('дорого', 'дёшево'):
            v['state'], v['judge_in_h'] = 'мало данных', round(after_h - (now - start) / 3600, 1)
    return out


def summary(res: dict[str, dict]) -> str:
    """«mesh-low-8 0,80 ₽ (24 ₽ / 30 мешей)» по группам — для пульса и журнала."""
    parts = []
    for g, v in res.items():
        if v['rub'] is None:
            parts.append(f'{g} — {v["state"]}')
            continue
        per = f'{v["per_mesh"]:.2f} ₽' if v['per_mesh'] is not None else '∞ ₽'
        parts.append(f'{g} {per} ({v["rub"]:.0f} ₽ / {v["meshes"]} меш.){"" if v["state"] == "дёшево" else " — " + v["state"]}')
    return '; '.join(parts) or 'нет данных'


if __name__ == '__main__':
    at = float(sys.argv[sys.argv.index('--at') + 1]) if '--at' in sys.argv else None
    r = by_group(now=at)
    print(f'₽ за меш по группам за {float(SG.price_ceiling().get("window_h") or 24):.0f} ч: {summary(r)}')
    print(json.dumps(r, ensure_ascii=False))
