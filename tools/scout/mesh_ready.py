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

from asset_strategy import non_mesh_roles  # noqa: E402
from mesh_queue import db  # noqa: E402

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
        # ОРИЕНТАЦИЯ — ТОГО ЖЕ ФИЗИЧЕСКОГО МЕША (05.09, план mesh-owner-audit). Ключи двух таблиц
        # несравнимы напрямую: средний сегмент у ревизии — хеш ФОТО, у ориентации — хеш МОДЕЛИ.
        # С 01.09 связывали по SKU — и перегон (новый seed) наследовал решённую ориентацию
        # старого меша, которую для него никто не считал. Честная связка уже была в
        # `mesh_dims.py`: `resolution->>'glb_sha'` (полный) против `asset_revisions.glb_sha`
        # (16 знаков); все auto/human_resolved строки его несут (1542/1542 на 05.09).
        "join orientation_state o on split_part(o.revision_key,'|',1) = r.sku "
        "  and left(o.resolution->>'glb_sha',16) = r.glb_sha "
        # ГОДЕН ПО УМОЛЧАНИЮ, ПОКА ВЛАДЕЛЕЦ НЕ СКАЗАЛ ОБРАТНОЕ (решение владельца 01.09: «те меши,
        # которые идут автоматом, пусть становятся проверенными, пока я не отмечу обратное»).
        # Прежнее условие требовало статус `accepted`, а его не проставлял НИКТО: на 01.09 в
        # `asset_revisions` 310 ревизий и ноль принятых — предикат готовности возвращал пустоту
        # для всего каталога, и подбор замены не отличал товар с мешом от товара без меша.
        # Теперь принимаем и `generated`; брак остаётся браком: `flat_shape`, `superseded` и
        # явный отказ владельца (`owner_reject`) сюда не попадают.
        "where r.status in ('accepted','generated') and r.origin <> 'legacy-local' "
        "  and d.source_sha is not null "
        # СРАВНИВАЕМ ПО ПРЕФИКСУ, А НЕ НА РАВЕНСТВО (01.09). В ключе ревизии хеш фото ОБРЕЗАН
        # до 16 знаков, в `mesh_demand.source_sha` он полный (64) — точное равенство не
        # выполнялось НИКОГДА, и предикат готовности возвращал пустоту для всех 405 ревизий.
        # Смысл проверки при этом верный и сохраняется: меш, сделанный по СТАРОМУ фото, годным
        # не считается — просто сверяем ту часть хеша, которая есть в обоих местах.
        "  and d.source_sha like split_part(r.revision_key, '|', 2) || '%' "
        "  and o.status in ('auto_resolved','human_resolved') "
        "  and coalesce(o.resolution->>'unusable','') <> 'true' "
        "group by r.sku")
    _CACHE = {r[0]: True for r in rows if r and r[0]}
    # ОДИН МЕШ НА МОДЕЛЬ (владелец 05.09): цветовой вариант готов, когда готов представитель
    # его семейства (`products.mesh_family_rep`, `mesh_family.py`) — своего меша у варианта нет.
    for r in db("select shop_mid||':'||external_id, mesh_family_rep from products "
                "where mesh_family_rep is not null and mesh_family_rep <> shop_mid||':'||external_id"):
        if len(r) == 2 and r[1] in _CACHE:
            _CACHE[r[0]] = True
    return _CACHE


def mesh_ready_raw() -> set:
    """Множество SKU с готовым мешом — нужно `render_strategy`, чтобы не дублировать запрос."""
    return set(_load())


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
                 not in non_mesh_roles()}      # мягкому декору и плоскому меш не нужен
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
