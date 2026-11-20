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
sys.path.insert(0, os.path.join(HERE, 'salad'))

import mesh_photo as MP  # noqa: E402 — сторож размера вырезки (ADR-0452)
import asset_strategy as AS  # noqa: E402 — канон стратегий ассета: сторож только для ролей с генерацией меша

POLICY_VERSION = 'p2'

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
    # СТОРОЖ РАЗМЕРА (ADR-0452, решение владельца TG 1864: «маленькие фото в меш не пропускать»): порог — `rules/mesh-photo.json`,
    # null = выключен. Стоит ПОСЛЕ прочих вердиктов: у коллажа и брака маски своя причина, размер их не перекрывает.
    # Только роли, которым ГЕНЕРИРУЕТСЯ меш (`hunyuan3d` канона): зеркало — плоскость, подушка/плед — вырезка; их текстуру размер вырезки не лишает
    # допуска (иначе `render_strategy.cut_ok` скрыл бы их из сцен). Роль неизвестна (пусто) — не судим.
    if role and AS.strategy(role) == 'hunyuan3d':
        fit, why = MP.check_size(ph.get('object_wh'))
        if not fit:
            return MP.STATUS, why
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
        # Источник текущего фото — `product_photo_current`, а не `mesh_demand`: спрос мешей уже,
        # чем пул отбора, и через него часть товаров была невидима. Вердикт НЕ берём из таблицы,
        # а считаем из измерений текущей политикой: иначе смена порогов оставит старые решения
        # (критика Codex 29.08).
        from preprocess import ASSESSOR_VERSION
        rows = _db("select c.sku, p.cat_role, a.metrics "
                   "  from product_photo_current c "
                   "  join products p on p.shop_mid||':'||p.external_id = c.sku "
                   "  join photo_assessment a on a.source_sha = c.source_sha "
                   f"   and a.assessor_version = '{ASSESSOR_VERSION}' "
                   " where c.source_sha is not null")
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


def reverdict_plan(rows: list) -> list:
    """rows [(source_sha, assessor_version, role, stored_verdict, metrics_json)] → [(source_sha, assessor_version, новый вердикт)].
    Двигаем ТОЛЬКО границу `ok` ↔ `photo_too_small` (область сторожа размера, ADR-0452): прочие вердикты не трогаем — они вынесены при вырезке.
    Чистая функция."""
    out = []
    for sha, ver, role, stored, raw in rows:
        if stored not in ('ok', MP.STATUS):
            continue
        try:
            m = json.loads(raw) if raw else {}
        except Exception:  # noqa: BLE001
            continue
        new = verdict_from_metrics(role, m)[0]
        if new in ('ok', MP.STATUS) and new != stored:
            out.append((sha, ver, new))
    return out


def reverdict() -> dict:
    """Привести ХРАНИМЫЙ `photo_assessment.verdict` к текущему порогу сторожа (его читают очередь мешей, экспорт, рендер, воронка: «ok» — единый
    допуск). Смена порога не требует заново резать фото: вердикт пересчитывается из сохранённых измерений. Идемпотентно. → счётчик {'ok→…': n}."""
    try:
        from preprocess import ASSESSOR_VERSION
    except Exception:  # noqa: BLE001 — вне образа зависимостей нет (как в mesh_queue)
        ASSESSOR_VERSION = os.environ.get('ASSESSOR_VERSION', 'a1')
    rows = _db("select a.source_sha, a.assessor_version, coalesce(max(p.cat_role), ''), a.verdict, a.metrics::text "
               "  from photo_assessment a "
               "  left join product_photo_current c on c.source_sha = a.source_sha "
               "  left join products p on p.shop_mid||':'||p.external_id = c.sku "
               f" where a.assessor_version = '{ASSESSOR_VERSION}' and a.verdict in ('ok', '{MP.STATUS}') "
               " group by a.source_sha, a.assessor_version, a.verdict, a.metrics::text")
    plan = reverdict_plan([r for r in rows if len(r) == 5])
    for sha, ver, new in plan:
        _db(f"update photo_assessment set verdict = '{new}' where source_sha = '{sha}' and assessor_version = '{ver}'")
    n_off = sum(1 for _, _, v in plan if v == MP.STATUS)
    print(f'[photo_fit] вердикты по порогу сторожа: отсечено новых {n_off}, вернулось в ok {len(plan) - n_off}', flush=True)
    return {'to_too_small': n_off, 'back_to_ok': len(plan) - n_off}


def shadow_verdict(role: str, metrics: dict | None, passport: dict | None, results: dict) -> tuple[str, str | None]:
    """ТЕНЬ паспорта (план mesh-type-passports-01, фаза 1): вердикт, который БЫ вынес паспорт. НИЧЕГО не блокирует — его пишет только `passport_shadow`.
    Порядок: (1) физический размер/коллаж — прежний `verdict_from_metrics` по измерениям ноды (если они есть; проход по тёплой части их не имеет — там размер
    уже вынесен в `photo_assessment`); (2) блокирующие метки сторожей паспорта (`blocking_verdicts` — у К1 `headboard_loss`); (3) мягкие метки (К3) — подпись,
    не вердикт. `results` = {имя сторожа: (вердикт, подтип)}. Чистая функция (существующие `verdict_from_metrics`/`reverdict*` не тронуты)."""
    if metrics:
        v, why = verdict_from_metrics(role, metrics)
        if v != 'ok':
            return v, why
    guards = {g['name']: g for g in ((passport or {}).get('cutout') or {}).get('guards') or ()}
    for name, (gv, _sub) in results.items():
        g = guards.get(name)
        if g and g.get('blocking') and gv in g.get('blocking_verdicts', ()):
            return gv, f'сторож {name}'
    for name, (gv, _sub) in results.items():
        if gv == 'ambiguous':      # не совместилось с исходником: НЕ «годно» — молча в ok не кладём
            return 'ambiguous', f'сторож {name}: не совместилось'
    return 'ok', None


def shadow_reverdict_plan(rows: list, reg: dict | None = None) -> list:
    """rows [(source_sha, роль, версия_замера, metrics_json, хранимый_вердикт)] → [(source_sha, роль, версия_замера, новый_вердикт)] по ТЕКУЩИМ порогам паспорта
    из СОХРАНЁННЫХ чисел, без пикселей (порог площади/ширины/hb_back меняется перевердиктом; пиксельный ΔE — новая версия замера, не здесь).
    Трогаем только вердикты, выносимые сторожами (ok/ambiguous/блокирующие): размер/коллаж в тени не пересчитать — их метрик в строке нет. Чистая функция."""
    import cutout_guards as CG
    import mesh_type_passports as MTP
    reg = reg or MTP.load()
    out = []
    for sha, role, mv, raw, stored in rows:
        p = reg['types'].get(role)
        g = next((x for x in ((p or {}).get('cutout') or {}).get('guards') or () if x['measurement_version'] == mv), None)
        if not g:
            continue
        own = {'ok', 'ambiguous', *g.get('blocking_verdicts', ())}
        if stored not in own:
            continue
        try:
            m = json.loads(raw) if raw else {}
        except Exception:  # noqa: BLE001
            continue
        gv, sub = CG.verdict(g['name'], m, g['thresholds'])
        new = shadow_verdict(role, None, p, {g['name']: (gv, sub)})[0]
        if new != stored:
            out.append((sha, role, mv, new))
    return out


def shadow_digest_targets(reg: dict | None = None) -> list:
    """[(роль, версия замера, ТЕКУЩИЙ хеш паспорта)] по всем сторожам реестра — какой штамп `policy_digest` должен стоять у строк тени после перевердикта. Чистая функция."""
    import mesh_type_passports as MTP
    reg = reg or MTP.load()
    return [(t, g['measurement_version'], MTP.digest_of(p)) for t, p in sorted(reg['types'].items()) for g in p['cutout']['guards']]


def shadow_reverdict() -> dict:
    """Привести `passport_shadow.shadow_verdict` к текущим порогам паспорта (пишет ТОЛЬКО в passport_shadow). Идемпотентно. → счётчик {'старый→новый': n}."""
    from collections import Counter
    rows = _db("select source_sha, normalized_role, measurement_version, metrics::text, shadow_verdict from passport_shadow where status = 'done' and metrics is not null")
    stored = {(r[0], r[1], r[2]): r[4] for r in rows if len(r) == 5}
    plan = shadow_reverdict_plan([r for r in rows if len(r) == 5])
    cnt = Counter()
    for sha, role, mv, new in plan:
        _db(f"update passport_shadow set shadow_verdict = '{new}', updated = now() where source_sha = '{sha}' and normalized_role = '{role}' and measurement_version = '{mv}'")
        cnt[f'{stored[(sha, role, mv)]}→{new}'] += 1
    # строки приведены к ТЕКУЩИМ порогам — штамп хеша паспорта тоже текущий (иначе `observe_gate` считал бы их устаревшими: фильтр по policy_digest)
    for role, mv, dg in shadow_digest_targets():
        _db(f"update passport_shadow set policy_digest = '{dg}', updated = now() where normalized_role = '{role}' and measurement_version = '{mv}' "
            f"and status = 'done' and metrics is not null and policy_digest <> '{dg}'")
    print(f'[photo_fit] тень паспортов: перевердикт {sum(cnt.values())} {dict(cnt)}', flush=True)
    return dict(cnt)


def photo_fit(sku: str) -> str:
    """ok | collage | tiny_object | photo_too_small | bad_cutout | unknown."""
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
    for k in ('ok', 'collage', 'tiny_object', MP.STATUS, 'bad_cutout'):
        print(f'  {k:12} {c.get(k, 0):6}  ({100 * c.get(k, 0) / max(total, 1):.1f}%)')
    unassessed = _db("select count(*) from mesh_demand where status='wanted' "
                     "and source_sha is not null and source_sha not in "
                     "(select source_sha from photo_assessment)")
    print(f'  ждут оценки {unassessed[0][0]}')
    # СЧЁТЧИК ВХОДА МЕШЕЙ (ADR-0452): сколько отсечено сторожем размера и при каком пороге; сбои гибридной маски ДОЛЖНЫ быть видны
    thr = MP.load_rules()
    print(f"  сторож размера: порог {thr['min_cut_side_px'] or 'выключен'} px ({thr['measure']}), отсечено {c.get(MP.STATUS, 0)}")
    try:
        hy = _db("select count(*) from photo_assessment where metrics ? 'hybrid_error'")[0][0]
        print(f'  сбоев гибридной маски (hybrid_error в измерениях): {hy}')
    except Exception as e:  # noqa: BLE001 — нет БД: счётчик пропускаем, но не молча
        print(f'  счётчик hybrid_error не получен ({type(e).__name__})')


if __name__ == '__main__':
    report()
