#!/usr/bin/env python3
"""Как предмет попадает в кадр — и что для него значит «готов».

ЗАЧЕМ. Правило «сеты только из товаров с мешами» невыполнимо буквально: мягкий декор мешей не
получает НИКОГДА (плед ложится на диван вклейкой, штора и ковёр варпятся по перспективе). Пока
готовность мерилась одним `mesh_ready`, такие слоты вечно числились непокрытыми, и покрытие
резерва врало вниз — а гейт «сеты только с готовыми» на этом основании остановил бы сборку.

Правильный контракт (критика Codex 29.08): **у каждого предмета есть готовое представление,
соответствующее ЕГО способу отрисовки.** Стратегия выводится из роли, требования — из стратегии.

  mesh   — объёмное, юзер крутит его в планировщике: нужен принятый меш ТЕКУЩЕГО фото
           плюс решённая ориентация;
  cutout — мелочь на поверхности, вклеивается силуэтом: нужна вырезка с вердиктом `ok`;
  flat   — плоское и мягкое, варпится по перспективе: нужны живое фото и габариты.

Роль, которой в таблице нет, считается `mesh`: строже безопаснее, чем тихо пропустить объёмный
предмет без модели.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'salad'))   # preprocess.ASSESSOR_VERSION живёт там

# ЕДИНСТВЕННЫЙ КАНОН СТРАТЕГИЙ — `rules/asset-strategies.json` (владелец 01.09: свет и вазы
# входят в сеты, меши им нужны). Здесь только ОТОБРАЖЕНИЕ канона в термины рендера; свои
# списки ролей были второй истиной и держали люстры/вазы в cutout, из-за чего планировщик
# заданий не выбрал бы их никогда (разбор Codex 01.09).
CUTOUT = {'плед', 'покрывало', 'шторы', 'подушка', 'часы', 'полка'}   # для обратной совместимости
FLAT = {'ковёр', 'ковер', 'картина', 'зеркало'}
_MAP = {'hunyuan3d': 'mesh', 'procedural_plane': 'flat', 'cutout': 'cutout',
        'parametric_soft': 'cutout'}


def strategy(role: str | None) -> str:
    import asset_strategy as _AS
    return _MAP.get(_AS.strategy(role), 'mesh')


def base_role(slot: str) -> str:
    """Слот «кресло 3» → роль «кресло»; «стол обеденный» НЕ резать."""
    parts = slot.split(' ')
    return slot if not parts[-1].isdigit() else ' '.join(parts[:-1])


_CACHE: dict[str, bool] | None = None


def _load() -> dict[str, bool]:
    """SKU → готов ли по своей стратегии."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    out: dict[str, bool] = {}
    try:
        from mesh_queue import db, q
        from preprocess import ASSESSOR_VERSION
        # mesh: принятая ревизия текущего фото + решённая ориентация той же ревизии
        from mesh_ready import mesh_ready_raw
        mesh_ok = mesh_ready_raw()
        # cutout: вырезка текущего фото с вердиктом ok
        cut_ok = {r[0] for r in db(
            "select c.sku from product_photo_current c "
            "join photo_assessment a on a.source_sha = c.source_sha "
            f" and a.assessor_version = {q(ASSESSOR_VERSION)} "
            "where a.verdict = 'ok'") if r and r[0]}
        # flat: живое фото и известные габариты — фото проверяет `img_alive`, габариты каталог
        flat_ok = {r[0] for r in db(
            "select p.shop_mid||':'||p.external_id from products p "
            "where p.image_url is not null and p.in_stock and p.status='active' "
            "  and coalesce(p.w_cm, 0) > 0") if r and r[0]}
        roles = {r[0]: r[1] for r in db(
            "select shop_mid||':'||external_id, cat_role from products "
            "where cat_role is not null") if len(r) == 2}
    except Exception as e:  # noqa: BLE001 — без БД предикат молчит, но НЕ молча (Codex P0-3):
        # тихий провал здесь делал ВСЕ ассеты неготовыми, и резерв/метрики врали нулями.
        print(f'[render_strategy] предикат не загрузился: {type(e).__name__}: {str(e)[:120]}',
              flush=True)
        _CACHE = {}
        return _CACHE
    for sku, role in roles.items():
        st = strategy(role)
        out[sku] = (sku in mesh_ok if st == 'mesh'
                    else sku in cut_ok if st == 'cutout'
                    else sku in flat_ok)
    _CACHE = out
    return out


def asset_ready(sku: str, role: str | None = None) -> bool:
    """Готов ли предмет к показу ПО СВОЕЙ стратегии. Единая точка истины покрытия."""
    return _load().get(sku, False)


def report() -> None:
    import collections
    from mesh_queue import db
    roles = {r[0]: r[1] for r in db(
        "select shop_mid||':'||external_id, cat_role from products where cat_role is not null")
        if len(r) == 2}
    ready = _load()
    by = collections.defaultdict(lambda: [0, 0])
    for sku, role in roles.items():
        b = by[strategy(role)]
        b[0] += 1
        b[1] += bool(ready.get(sku))
    print(f"{'стратегия':10}{'товаров':>10}{'готовых':>10}{'доля':>8}")
    for st, (n, ok) in sorted(by.items()):
        print(f'{st:10}{n:10}{ok:10}{100 * ok / max(n, 1):7.1f}%')


if __name__ == '__main__':
    report()
