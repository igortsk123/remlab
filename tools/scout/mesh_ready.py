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
  ~/venvs/scout/bin/python mesh_ready.py --shadow     # тень: прежний предикат против `product_photo_current` (T-20261118-04/22; пропало должно быть 0)

Откуда хеш ТЕКУЩЕГО фото — выключатель `rules/mesh-ready.json:photo_current` (по потребителю, `_why` у каждого поля).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from asset_strategy import non_mesh_roles  # noqa: E402
from mesh_queue import db, q  # noqa: E402

RULES = os.path.join(HERE, 'rules', 'mesh-ready.json')

# Кэш по РЕЖИМУ: False — прежний путь (хеш фото из `mesh_demand`), True — через `product_photo_current` (T-20261118-04/22).
_CACHE: dict[bool, dict[str, bool] | None] = {False: None, True: None}
_RULES: dict | None = None

REV_OK = "r.status in ('accepted','generated') and r.origin <> 'legacy-local'"


def rules() -> dict:
    """`rules/mesh-ready.json`; нет файла или он не читается — {} (все выключатели выключены, прежний путь)."""
    global _RULES
    if _RULES is None:
        try:
            _RULES = json.load(open(RULES, encoding='utf-8'))
        except (OSError, ValueError):
            _RULES = {}
    return _RULES


def photo_current_on(consumer: str | None = None) -> bool:
    """Считать готовность по `product_photo_current` (а не по строке спроса `mesh_demand`) для потребителя? Выключатель —
    `rules/mesh-ready.json:photo_current` (по потребителю: `bank_ready`, остальные — `others`); неизвестное/нет поля — False."""
    p = rules().get('photo_current') or {}
    return bool(p.get('bank_ready' if consumer == 'bank_ready' else 'others', False))


def revision_current_sql(sku_expr: str, sha_expr: str, pipeline: str | None = None) -> str:
    """Условие `exists (…)`: у товара есть ГОДНАЯ ревизия ТЕКУЩЕГО фото — не legacy, accepted|generated, хеш фото в ключе ревизии (16 знаков)
    — префикс текущего `sha_expr` (полного); `pipeline` — ещё и версия конвейера в ключе. Одно правило у готовности и у планировщика
    (Codex 18.11: планировщик сверял только `accepted` и полный хеш, ревизия «generated» его не гасила — меш с неразрешённой ориентацией
    ставили в генерацию повторно)."""
    pv = f" and split_part(r.revision_key,'|',3) = {q(pipeline)}" if pipeline else ''
    return ("exists (select 1 from asset_revisions r "
            f"where r.sku = {sku_expr} and {REV_OK} "
            f"and coalesce({sha_expr},'') <> '' and {sha_expr} like split_part(r.revision_key,'|',2) || '%'{pv})")


def ready_sql(photo_current: bool = False) -> str:
    """SQL готовности: SKU (представитель), у которого есть годная ревизия ТЕКУЩЕГО фото и решённая ориентация ЭТОГО ЖЕ glb.
    `photo_current=False` — прежний текст (хеш фото — `mesh_demand.source_sha`); `True` — хеш фото из `product_photo_current`
    (канон `photo_hash`, им же пользуется `mesh_bind.enforce_ready_invariant`): готовность не зависит от того, есть ли у товара
    строка изменяемой таблицы спроса (Codex 18.11: у меша, сделанного очередью demo/комнат, строки спроса не бывает)."""
    if photo_current:
        join_src, sha = "join product_photo_current c on c.sku = r.sku ", "c.source_sha"
        sha_ok = "  and coalesce(c.source_sha,'') <> '' "
    else:
        join_src, sha = "join mesh_demand d on d.sku = r.sku ", "d.source_sha"
        sha_ok = "  and d.source_sha is not null "
    return (
        "select r.sku from asset_revisions r "
        + join_src +
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
        f"where {REV_OK} "
        + sha_ok +
        # СРАВНИВАЕМ ПО ПРЕФИКСУ, А НЕ НА РАВЕНСТВО (01.09). В ключе ревизии хеш фото ОБРЕЗАН
        # до 16 знаков, в `mesh_demand.source_sha` он полный (64) — точное равенство не
        # выполнялось НИКОГДА, и предикат готовности возвращал пустоту для всех 405 ревизий.
        # Смысл проверки при этом верный и сохраняется: меш, сделанный по СТАРОМУ фото, годным
        # не считается — просто сверяем ту часть хеша, которая есть в обоих местах.
        f"  and {sha} like split_part(r.revision_key, '|', 2) || '%' "
        "  and o.status in ('auto_resolved','human_resolved') "
        "  and coalesce(o.resolution->>'unusable','') <> 'true' "
        "group by r.sku")


FAMILY_SQL = ("select shop_mid||':'||external_id, mesh_family_rep from products "
              "where mesh_family_rep is not null and mesh_family_rep <> shop_mid||':'||external_id")


def _load(photo_current: bool = False) -> dict[str, bool]:
    """SKU → готов ли: принятая ревизия ТЕКУЩЕГО фото (Salad, не legacy) + решённая ориентация.

    Сверка текущего фото обязательна. Без неё меш, сделанный по СТАРОЙ картинке,
    продолжает считаться готовым после того, как магазин заменил фото, — и «заменитель с готовым
    мешом» оказывается мешом другого на вид товара. Ключ ревизии — `sku|source_sha|pipeline`,
    поэтому сверяем среднюю часть: `split_part(revision_key, '|', 2)`. Хеш текущего фото — `mesh_demand.source_sha`
    (прежний путь) или `product_photo_current.source_sha` (`photo_current=True`, см. `ready_sql`).
    """
    if _CACHE[photo_current] is not None:
        return _CACHE[photo_current]
    rows = db(ready_sql(photo_current))
    out = {r[0]: True for r in rows if r and r[0]}
    # ОДИН МЕШ НА МОДЕЛЬ (владелец 05.09): цветовой вариант готов, когда готов представитель
    # его семейства (`products.mesh_family_rep`, `mesh_family.py`) — своего меша у варианта нет.
    # Фото представителя — потому что ревизия и `product_photo_current` лежат на самом представителе (`c.sku = r.sku`).
    for r in db(FAMILY_SQL):
        if len(r) == 2 and r[1] in out:
            out[r[0]] = True
    _CACHE[photo_current] = out
    return out


def mesh_ready_raw(consumer: str | None = None) -> set:
    """Множество SKU с готовым мешом — нужно `render_strategy`, чтобы не дублировать запрос. `consumer` — имя потребителя
    для выключателя `rules/mesh-ready.json:photo_current` (`bank_ready`; без имени — `others`)."""
    return set(_load(photo_current_on(consumer)))


def mesh_ready(sku: str, consumer: str | None = None) -> bool:
    """Готов = принятый меш И решённая ориентация. Единственная точка истины предиката."""
    return _load(photo_current_on(consumer)).get(sku, False)


def shadow() -> int:
    """Тень: старый предикат против нового (только чтение). Печатает, сколько SKU добавилось и пропало; пропало хоть одно — код 1."""
    old, new = set(_load(False)), set(_load(True))
    add, lost = new - old, old - new
    print(f'[mesh-ready shadow] прежний {len(old)} · через product_photo_current {len(new)} · добавилось {len(add)} · пропало {len(lost)}', flush=True)
    for s in sorted(lost)[:20]:
        print(f'  ПРОПАЛ {s}', flush=True)
    return 1 if lost else 0


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
    elif '--shadow' in sys.argv:
        sys.exit(shadow())
    else:
        print(__doc__)
