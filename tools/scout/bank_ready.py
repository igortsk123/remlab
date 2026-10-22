#!/usr/bin/env python3
"""ГОТОВНОСТЬ ТОВАРА К ПОКАЗУ В БАНКЕ `bank_display_ready` и ТИП ОЖИДАНИЯ (conv-14 шаг 2.1, разбор Codex 22.10).

ЗАЧЕМ ОТДЕЛЬНО ОТ `render_strategy.asset_ready`. Глобальный предикат меряет то, что нужно рендеру (вырезка мягкого — маска
с вердиктом ok), и берёт стратегию из `cat_role` базы, игнорируя переданную роль (`render_strategy.py:95/113`). Для банка это
неверно: подушки/шторы/пледы в показе не вклеиваются (`flat215_demo.py:38/78`, `lib/configurator/fromDemo.ts:191/255`,
`draft_render.py:60/3181`), а вырезок мягкого 0 из 1542 (`refresh_daily.sh:331` CUTOUT_DAILY_MAX=0) — по старому правилу ни
одна ячейка не стала бы готовой никогда. Глобальный предикат НЕ меняем; здесь — стратегия по ПЕРЕДАННОЙ роли слота.

ГОТОВ К ПОКАЗУ (общая часть для всех): товар в каталоге и доступен (`catalog_media.state == available`), ссылка кандидата =
текущая партнёрская, фото живое по `img_alive.alive_now` (витрина мёртвое фото превращает в пустоту, `flat215_demo.py:1206`).
Плюс по стратегии: `cutout` — ничего больше (ни маски, ни габаритов); `flat` — ковёр обе стороны, прочее — ширина; `mesh` —
гейт геометрии и готовый меш товара или представителя семейства.

ГЕЙТ ГЕОМЕТРИИ (меш-роль, ДО «меш готов»: `/flat` без высоты предмет отбрасывает — `fromDemo.ts:191`): `h > 0`, горизонталь
`w|dia`, и `d` для некруглых (`render_strategy.square_roles`) — контракт постановки `mesh_required` (`mesh_bind.py:91/101`).
ТРАНСФОРМЕР (`диван|кресло`: «-кровать», «Раскладная конструкция=Да», «Раскладной/Раскладывается=да», механизм трансформации)
без доказанных собранных размеров — `wait_catalog`: у Орматек «Ширина×Длина» — спальное место (диван 200×150, кресло d=200).
Доказано — отдельные поля спального/разложенного/габаритного размера в карточке (тогда основные — собранные) или размеры
`dims_source` scrape|manual. Правило по признакам, не список SKU.

ТИПЫ (что делать с неготовым): `wait_asset` — ждём представление (need=mesh — спрос мешей; need=review — меш в карантине,
ждёт решения); `wait_catalog` — дыра данных каталога (высота, глубина, обогащение, фото, ссылка, наличие не проверено);
`redo` — владелец велел переделать меш (своя очередь переделок, `mesh_rework_requests`); `blocked_policy` — товар заменить
(ушёл, `replace_needed`/`reject` журнала `mesh_decisions`, генерация failed_terminal) → чёрный список и пересборка ячейки;
`legacy_unknown` — `rejected` без происхождения: не продвигать, не тратить, разовая триаж-очередь.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TYPES = ('wait_asset', 'wait_catalog', 'redo', 'blocked_policy', 'legacy_unknown')
# худшее определяет статус ячейки: блок важнее ожидания (Codex § 4 — ячейка с блоком всё равно в спросе по остальным)
SEVERITY = {'blocked_policy': 5, 'legacy_unknown': 4, 'redo': 3, 'wait_catalog': 2, 'wait_asset': 1}
RUGS = ('ковёр', 'ковер')


def base_role(slot: str) -> str:
    parts = slot.split(' ')
    return ' '.join(parts[:-1]) if parts[-1].isdigit() else slot


class Facts:
    """Подменяемые в тестах факты. `prod[sku]` = {'role','status','eligible','has_h','rep','w','d','h','dia','tr','proven'};
    `media(sku)` → запись `catalog_media` или None; `alive(url)` → bool; `mesh_ok` — готовые меши; `failed` — failed_terminal;
    `decisions` — {sku: {'decision', …}} журнала; `with_gen` — SKU с поколением на DEV; `strategy(role)`; `square` — роли d = w."""

    def __init__(self, prod, failed, strategy, media=None, alive=None, mesh_ok=(), decisions=None, with_gen=(), square=(),
                 ready=None):
        self.prod, self.failed, self.strategy = prod, set(failed), strategy
        self.media = media or (lambda sku: None)
        self.alive = alive or (lambda url: bool(url))
        self.mesh_ok, self.decisions, self.with_gen, self.square = set(mesh_ok), decisions or {}, set(with_gen), set(square)
        if ready is not None:                        # старый вход шага 2: «готов» как функция — для тестов
            self.mesh_ok |= {s for s in prod if ready(s)}

    def rep(self, sku: str) -> str:
        return (self.prod.get(sku) or {}).get('rep') or sku


def geometry(role: str, p: dict, square) -> str | None:
    """Причина, по которой меш-роли нельзя показать/заказать по габаритам; None — габариты достаточны."""
    if not (p.get('h') or 0) > 0:
        return 'нет высоты (h_cm)'
    if not (p.get('w') or p.get('dia')):
        return 'нет горизонтали (w или диаметр)'
    if not (p.get('d') or p.get('dia') or role in square):
        return 'нет глубины (не круглое и не квадратное)'
    if p.get('tr') and not p.get('proven'):
        return 'трансформер: собранные размеры не доказаны (в карточке, вероятно, спальное место)'
    return None


def classify(role: str, sku: str, item: dict | None, F: Facts) -> tuple[str, str | None, str | None]:
    """→ (тип, причина, need). Тип — 'ready' или один из TYPES; need — 'mesh' (спрос мешей), 'review' или None.
    `item` — позиция кандидата (для сверки ссылки); None — переоценка чёрного списка вне кандидата."""
    b = base_role(role)
    st = F.strategy(b)
    p = F.prod.get(sku)
    if not p:
        return 'blocked_policy', 'нет в каталоге', None
    m = F.media(sku)
    if not m or m.get('state') == 'gone':
        return 'blocked_policy', 'товар ушёл из продажи', None
    if m.get('state') != 'available':
        return 'wait_catalog', 'наличие не проверено (магазин в карантине)', None
    if item is not None and (not item.get('url') or item.get('url') != m.get('url')):
        return 'wait_catalog', 'ссылка кандидата не текущая партнёрская', None
    if not F.alive(m.get('img')):
        return 'wait_catalog', 'фото товара не живое', None
    rep = F.rep(sku)
    dec = (F.decisions.get(sku) or F.decisions.get(rep) or {}).get('decision')
    if dec in ('replace_needed', 'reject'):
        return 'blocked_policy', f'решение по мешу: {dec}', None
    if st == 'cutout':
        return 'ready', None, None
    if st == 'flat':
        if b in RUGS:
            return ('ready', None, None) if (p.get('w') or 0) > 0 and (p.get('d') or 0) > 0 \
                else ('wait_catalog', 'ковёр: нужны обе стороны', None)
        return ('ready', None, None) if (p.get('w') or 0) > 0 else ('wait_catalog', 'нет ширины', None)
    geo = geometry(b, p, F.square)
    if geo:
        return 'wait_catalog', geo, None
    if sku in F.mesh_ok or rep in F.mesh_ok:
        return 'ready', None, None
    if dec == 'redo':
        return 'redo', 'владелец: переделать меш (очередь переделок)', None
    rp = F.prod.get(rep) or p
    if rp.get('status') == 'rejected':
        if rep not in F.with_gen and sku not in F.with_gen:
            return 'legacy_unknown', 'меш rejected без происхождения (нет решения и поколения) — в триаж', None
        return 'legacy_unknown', 'меш rejected без решения в журнале — в триаж', None
    if rp.get('status') == 'quarantine':
        return 'wait_asset', 'меш в карантине — ждёт решения', 'review'
    if rep in F.failed:
        return 'blocked_policy', 'генерация failed_terminal', None
    if not rp.get('eligible'):
        return 'wait_catalog', 'не мешепригоден (mesh_required=false: обогащение, фото или габариты)', None
    return 'wait_asset', 'нет меша', 'mesh'


# ——— факты из базы ———

TRANSFORMER_SQL = (
    "(p.cat_role in ('диван','кресло') and (p.name ~* 'кроват' or p.params->>'Раскладная конструкция' = 'Да' "
    " or p.params->>'Раскладной' ~* '^да' or p.params->>'Раскладывается' ~* '^да' "
    " or coalesce(p.params->>'Механизм трансформации','') !~* '^(|нет|без механизма|отсутствует)$'))")
PROVEN_SQL = (
    "(coalesce(p.dims_source,'') ~ '(scrape|manual)' or exists (select 1 from jsonb_object_keys("
    " case when jsonb_typeof(p.params)='object' then p.params else '{}'::jsonb end) k where k ~* '(спальн|разложенн|габаритн)'))")


def load_prod() -> dict:
    from mesh_queue import db
    prod = {}
    for r in db("select p.shop_mid||':'||p.external_id, coalesce(p.cat_role,''), coalesce(p.mesh_status,'none'), "
                "coalesce(p.mesh_required,false)::text, coalesce(p.mesh_family_rep, p.shop_mid||':'||p.external_id), "
                "coalesce(p.w_cm,0), coalesce(p.d_cm,0), coalesce(p.h_cm,0), coalesce(p.dia_cm,0), "
                f"{TRANSFORMER_SQL}::text, {PROVEN_SQL}::text from products p"):
        if len(r) == 11:
            num = lambda v: float(v) or None  # noqa: E731
            prod[r[0]] = {'role': r[1], 'status': r[2], 'eligible': r[3] == 'true', 'rep': r[4], 'w': num(r[5]),
                          'd': num(r[6]), 'h': num(r[7]), 'dia': num(r[8]), 'has_h': num(r[7]) is not None,
                          'tr': r[9] == 'true', 'proven': r[10] == 'true'}
    return prod


def load_facts() -> Facts:
    from mesh_queue import db
    import catalog_media as CM
    import img_alive as IA
    import mesh_decisions as MD
    import render_strategy as RS
    from mesh_ready import mesh_ready_raw
    failed = {r[0] for r in db("select distinct sku from mesh_jobs where status = 'failed_terminal'") if r and r[0]}
    gens = {r[0] for r in db("select distinct sku from mesh_generations") if r and r[0]}
    media = lambda sku: CM.media(*sku.split(':', 1))  # noqa: E731
    return Facts(load_prod(), failed, RS.strategy, media=media, alive=IA.alive_now, mesh_ok=mesh_ready_raw(),
                 decisions=MD.load(), with_gen=gens, square=RS.square_roles())


def _selftest() -> int:
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    P = lambda role, **k: {'role': role, 'status': 'none', 'eligible': True, 'rep': None, 'w': 100, 'd': 50, 'h': 80,  # noqa: E731
                           'dia': None, 'tr': False, 'proven': False, **k}
    prod = {'s:pil': P('подушка', w=None, d=None, h=None), 's:pil2': P('подушка'), 's:rug': P('ковёр', d=None),
            's:rug2': P('ковёр', h=None), 's:sofa': P('диван'), 's:sofa2': P('диван', h=None), 's:pot': P('кашпо', d=None),
            's:bra': P('бра', d=None), 's:bed': P('диван', tr=True), 's:bed2': P('диван', tr=True, proven=True),
            's:tubo': P('кашпо', status='rejected'), 's:leg': P('витрина', status='rejected'),
            's:redo': P('кресло', status='rejected'), 's:q': P('кресло', status='quarantine'),
            's:fail': P('кресло'), 's:ne': P('кресло', eligible=False), 's:v2': P('диван', rep='s:sofa')}
    M = {s: {'state': 'available', 'url': f'u/{s}', 'img': f'i/{s}'} for s in prod}
    M['s:pil2'] = {'state': 'gone', 'url': 'u', 'img': 'i'}
    strat = lambda r: 'cutout' if r == 'подушка' else 'flat' if r == 'ковёр' else 'mesh'  # noqa: E731
    F = Facts(prod, failed={'s:fail'}, strategy=strat, media=M.get, alive=lambda u: u != 'i/s:dead',
              mesh_ok={'s:sofa', 's:sofa2', 's:bed'}, decisions={'s:tubo': {'decision': 'replace_needed'},
                                                                 's:redo': {'decision': 'redo'}},
              with_gen={'s:redo'}, square={'кашпо'})
    it = lambda s: {'url': f'u/{s}'}  # noqa: E731
    c = lambda role, s, item='same': classify(role, s, it(s) if item == 'same' else item, F)[:2]  # noqa: E731
    ok('подушка без маски и габаритов, живое фото и текущая ссылка — готова', c('подушка 2', 's:pil')[0] == 'ready')
    ok('подушка ушла из продажи — blocked_policy', c('подушка', 's:pil2')[0] == 'blocked_policy')
    M['s:pil']['img'] = 'i/s:dead'
    ok('подушка с мёртвым фото — wait_catalog', c('подушка', 's:pil')[0] == 'wait_catalog')
    M['s:pil']['img'] = 'i/s:pil'
    ok('ссылка кандидата не текущая — wait_catalog', c('подушка', 's:pil', {'url': 'old'})[0] == 'wait_catalog')
    ok('ковёр без второй стороны — wait_catalog; с обеими — готов (высота не нужна)',
       c('ковёр', 's:rug')[0] == 'wait_catalog' and c('ковёр', 's:rug2')[0] == 'ready')
    ok('роль — переданная, не из базы: «подушка» в слоте ковра судится как ковёр',
       classify('ковёр', 's:pil', it('s:pil'), F)[0] == 'wait_catalog')
    ok('меш готов, но нет высоты — wait_catalog (гейт геометрии раньше готовности)',
       c('диван', 's:sofa2') == ('wait_catalog', 'нет высоты (h_cm)'))
    ok('кашпо (квадратное) без глубины — проходит гейт; бра без глубины — wait_catalog',
       c('кашпо', 's:pot')[0] == 'wait_asset' and c('бра', 's:bra')[0] == 'wait_catalog')
    ok('трансформер без доказанных собранных размеров — wait_catalog даже с готовым мешем; доказано — по мешу',
       c('диван', 's:bed')[0] == 'wait_catalog' and 'трансформер' in c('диван', 's:bed')[1] and c('диван', 's:bed2')[0] == 'wait_asset')
    ok('Tubo — replace_needed журнала → blocked_policy', c('кашпо', 's:tubo') == ('blocked_policy', 'решение по мешу: replace_needed'))
    ok('rejected без решения и поколения — legacy_unknown', c('витрина', 's:leg')[0] == 'legacy_unknown')
    ok('владелец велел переделать — redo, не спрос мешей', classify('кресло', 's:redo', it('s:redo'), F)[::2] == ('redo', None))
    ok('карантин — wait_asset/review; failed_terminal — blocked; mesh_required=false — wait_catalog',
       classify('кресло', 's:q', it('s:q'), F)[::2] == ('wait_asset', 'review') and c('кресло', 's:fail')[0] == 'blocked_policy'
       and c('кресло', 's:ne')[0] == 'wait_catalog')
    ok('цвет той же модели — готов по мешу представителя', c('диван', 's:v2')[0] == 'ready')
    ok('обычный меш-товар без меша — wait_asset/mesh (спрос)', classify('кресло', 's:fail', None,
       Facts(prod, set(), strat, media=M.get))[::2] == ('wait_asset', 'mesh'))
    ok('вне кандидата (item=None) ссылку не сверяем', classify('подушка', 's:pil', None, F)[0] == 'ready')
    print(f'bank_ready selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else print(__doc__) or 0)
