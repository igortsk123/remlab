#!/usr/bin/env python3
"""Пригоден ли снимок товара для меша и для сета — единый предикат.

РАЗДЕЛЕНИЕ, РАДИ КОТОРОГО ЭТО ОТДЕЛЬНЫЙ ФАЙЛ. Нода считает ИЗМЕРЕНИЯ (`salad/preprocess.assess`)
и кладёт их в `photo_assessment` целиком. Здесь живёт ПОЛИТИКА — какие числа считать негодными.
Так смена порогов не требует заново гонять маски всему пулу: пересчитывается только вердикт.

ПРО РАЗРЕШЕНИЕ — И ПРО ОТВЕРГНУТУЮ ГИПОТЕЗУ. Ворота по абсолютной ширине кадра бессмысленны:
в фиде Гдеслона ВСЕ фото 450 px, такой гейт выкосил бы каталог целиком. Ожидалось, что различать
будет доля кадра, занятая товаром (на баннере он мелкий). **Замер 28.08 на 36 товарах эту гипотезу
не подтвердил:** у нормальных карточек длинная сторона товара занимает 0.38–1.00 кадра (медиана
0.74), у двух пойманных коллажей — 0.56 и 0.82, то есть ровно внутри нормы. Размер коллажи не
выдаёт; выдаёт их только детектор баннера по маске.

Поэтому `tiny_object` оставлен НЕ как гейт качества, а как страховка от вырожденного случая
(товар-миниатюра в углу рекламного щита): порог поставлен ниже всего наблюдавшегося диапазона.
Настоящий потолок качества — 450 px исходника, он одинаков для всех и воротами быть не может;
лечится только доступом к оригиналам магазинов, а не отбраковкой.

ПОЛИТИКА НЕИЗВЕСТНОГО. `unknown` (замера ещё не было) не равно «годно». В новые сеты и в любые
ЗАМЕНЫ неизвестное не пускаем — иначе просьба владельца «чтобы коллажи не проходили в сеты»
не выполняется по построению. Уже опубликованные сеты живут по старому правилу, пока их фото
не оценены (grandfathering), иначе банк схлопнется в один вечер.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

POLICY_VERSION = 'p1'

# Пороги взяты ИЗ ЗАМЕРА, а не из головы, и намеренно ниже всего наблюдавшегося: на выборке 36
# минимум у живых карточек — длинная сторона 0.382 кадра и площадь 0.124. Всё, что ниже этих
# ворот, — уже не «мелковато», а вырожденный кадр. Ложных срабатываний на выборке: ноль.
# Мерим ДЛИННУЮ сторону: у торшера и стеллажа короткая мала по природе предмета, и порог по ней
# забраковал бы 78% каталога (проверено).
MIN_REL_SIDE = 0.25
MIN_OBJECT_SHARE = 0.05

PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

_CACHE: dict[str, str] | None = None


def verdict_from_metrics(role: str, metrics: dict) -> tuple[str, str | None]:
    """(вердикт, причина) по измерениям ноды. Чистая функция — её и тестируем."""
    if not metrics:
        return 'unknown', 'замера не было'
    col = (metrics.get('collage') or {})
    if col.get('verdict'):
        return 'collage', 'фото-коллаж: ' + ', '.join(col.get('why', [])[1:] or ['баннер'])
    if metrics.get('verdict') == 'bad':
        return 'bad_cutout', metrics.get('reason') or 'вырезка непригодна'
    ph = metrics.get('photo') or {}
    rel, share = ph.get('object_rel_side'), ph.get('object_share')
    if rel is not None and rel < MIN_REL_SIDE:
        return 'tiny_object', f'товар занимает {100 * rel:.0f}% длинной стороны кадра'
    if share is not None and share < MIN_OBJECT_SHARE:
        return 'tiny_object', f'товар занимает {100 * share:.1f}% площади кадра'
    return 'ok', None


def _db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, capture_output=True, text=True, input=sql)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def _load() -> dict[str, str]:
    """SKU → вердикт, по измерениям ТЕКУЩЕГО фото товара."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    out: dict[str, str] = {}
    try:
        rows = _db("select d.sku, d.role, a.metrics from mesh_demand d "
                   "join photo_assessment a on a.source_sha = d.source_sha "
                   "where d.source_sha is not null")
    except Exception:  # noqa: BLE001 — без БД предикат обязан молчать, а не врать «годно»
        _CACHE = {}
        return _CACHE
    for sku, role, raw in rows:
        try:
            m = json.loads(raw) if raw else {}
        except Exception:  # noqa: BLE001
            m = {}
        out[sku] = verdict_from_metrics(role, m)[0]
    _CACHE = out
    return out


def photo_fit(sku: str) -> str:
    """ok | collage | tiny_object | bad_cutout | unknown."""
    return _load().get(sku, 'unknown')


def fit_ok(sku: str, allow_unknown: bool = False) -> bool:
    """Годится ли товар. `allow_unknown` — только для уже опубликованных сетов (grandfathering);
    для новых сетов и для ЗАМЕН неизвестное годным не считается."""
    v = photo_fit(sku)
    return v == 'ok' or (allow_unknown and v == 'unknown')


def report() -> None:
    from collections import Counter
    c = Counter(_load().values())
    total = sum(c.values())
    print(f'оценено фото: {total} (политика {POLICY_VERSION})')
    for k in ('ok', 'collage', 'tiny_object', 'bad_cutout'):
        print(f'  {k:12} {c.get(k, 0):6}  ({100 * c.get(k, 0) / max(total, 1):.1f}%)')
    unassessed = _db("select count(*) from mesh_demand where status='wanted' "
                     "and source_sha is not null and source_sha not in "
                     "(select source_sha from photo_assessment)")
    print(f'  ждут оценки {unassessed[0][0]}')


if __name__ == '__main__':
    report()
