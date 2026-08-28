#!/usr/bin/env python3
"""Единый предикат «у товара есть годный меш» + shadow-отчёт покрытия сетов (ADR-0131).

Правило владельца: сеты собираются только из товаров с мешами — вводится ЭТАПНО (q25):
  MESH_GATE_PHASE=off      (сейчас) — предикат никого не режет;
  MESH_GATE_PHASE=shadow   — только отчёт покрытия (этот файл, шаг в refresh_daily);
  MESH_GATE_PHASE=hard_new — новые сеты не публикуются без мешей (гейт в подборе);
  MESH_GATE_PHASE=rolling / full — по решению владельца после цифр coverage.
Один и тот же предикат обязан использоваться и первичной сборкой, и лечением слотов —
fail-closed в hard-фазах (сейчас первичная сборка идёт мимо _slot_ok, q25).

  ~/venvs/scout/bin/python mesh_ready.py --coverage   # shadow-отчёт по sets3.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mesh_queue import MESH_EXCLUDE, db  # noqa: E402

_CACHE: dict[str, bool] | None = None


def _load() -> dict[str, bool]:
    """SKU → готов ли: принятая ревизия ТЕКУЩЕГО фото (Salad, не legacy) + решённая ориентация.

    Сверка с `mesh_demand.source_sha` обязательна. Без неё меш, сделанный по СТАРОЙ картинке,
    продолжает считаться готовым после того, как магазин заменил фото, — и «заменитель с готовым
    мешом» оказывается мешом другого на вид товара. Ключ ревизии — `sku|source_sha|pipeline`,
    поэтому сверяем среднюю часть: `split_part(revision_key, '|', 2)`.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    rows = db(
        "select r.sku from asset_revisions r "
        "join mesh_demand d on d.sku = r.sku "
        "join orientation_state o on o.revision_key = r.revision_key "
        "where r.status='accepted' and r.origin <> 'legacy-local' "
        "  and d.source_sha is not null "
        "  and split_part(r.revision_key, '|', 2) = d.source_sha "
        "  and o.status in ('auto_resolved','human_resolved') "
        "  and coalesce(o.resolution->>'unusable','') <> 'true' "
        "group by r.sku")
    # Ориентация сверяется по ТОЙ ЖЕ revision_key, а не «есть ли у SKU хоть какая-то решённая»:
    # иначе вердикт для старой ревизии подтверждал бы новую, которую никто не смотрел.
    _CACHE = {r[0]: True for r in rows if r and r[0]}
    return _CACHE


def mesh_ready(sku: str) -> bool:
    """Готов = принятый меш И решённая ориентация. Единственная точка истины предиката."""
    return _load().get(sku, False)


def gate_active() -> bool:
    return os.environ.get('MESH_GATE_PHASE', 'off') in ('hard_new', 'rolling', 'full')


def coverage() -> None:
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    full, part_rows, role_tot, role_ok = 0, [], {}, {}
    for n, s in enumerate(sets, 1):
        items = {slot: v for slot, v in (s.get('items') or {}).items()
                 if (slot.split(' ')[0] if slot.split(' ')[-1].isdigit() else slot)
                 not in MESH_EXCLUDE}          # мягкому декору и плоскому меш не нужен
        skus = {f"{v.get('mid')}:{v.get('eid')}" for v in items.values()
                if v and v.get('mid') is not None}
        ok = {p for p in skus if mesh_ready(p)}
        if skus and ok == skus:
            full += 1
        part_rows.append((n, len(ok), len(skus)))
        for slot, v in items.items():
            if not v or v.get('mid') is None:
                continue
            role = slot.split(' ')[0] if slot.split(' ')[-1].isdigit() else slot
            role_tot[role] = role_tot.get(role, 0) + 1
            if mesh_ready(f"{v['mid']}:{v['eid']}"):
                role_ok[role] = role_ok.get(role, 0) + 1
    print(f'[mesh-coverage] сетов полностью с мешами: {full}/{len(sets)}', flush=True)
    for role in sorted(role_tot, key=lambda r: -role_tot[r]):
        print(f'  {role:16s} {role_ok.get(role, 0)}/{role_tot[role]}', flush=True)


if __name__ == '__main__':
    if '--coverage' in sys.argv:
        coverage()
    else:
        print(__doc__)
