#!/usr/bin/env python3
"""ГОТОВНОСТЬ ПРЕДМЕТОВ БАНКА КОМНАТЫ ИЗ ПРИВЯЗКИ `offer_asset_binding` (room-bank-01 этап В, T-20261106-70; Codex § 3 п.4:
«для room_catalog — offer_asset_binding, products.mesh_status недостаточен»).

ЗАЧЕМ. Гостиная судит «товар готов к показу» по полям products (`bank_ready.classify`). Мебель спальни живёт в room_catalog,
её канон меша — привязка. Правило ОДНО с витриной: `room_bindings.usable` (сторож варианта спальни T-20261105-51/3 зовёт его же):
  предмет солвера (кровать, тумбы, шкаф, комод… — `demo_bedroom.SOLVER_ROLES`, те же роли, что проверяет витрина) годен, когда
  привязка `ready` (и модель выложена) ИЛИ `blocked` только по развороту (`orientation_*`, режим orient — по умолчанию),
  модель сцены (представитель, `room_bindings.mesh_rep`) = модель привязки и она в индексе прода без карантина
  (`room_bindings.prod_index`). Режим strict — флагом правил `rooms.bedroom.mesh_gate`.
  Прочие роли (лампа, ковёр, шторы, плед) витрина моделью не проверяет — здесь они готовы; их собственные требования (фото,
  ссылка, наличие) — strict этапа Г.
Отказ привязки → тип ожидания `bank_ready` (`wait_asset`) с причиной и need: нет меша — 'mesh' (в спрос мешей), брак/паспорт —
'review', не выложена/нет в индексе — 'publish'. Привязка не читается — у всех предметов солвера «unbound» (ячейки ждут, а не
продвигаются с заглушками).

  python3 room_ready.py --selftest
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import room_bindings as RB  # noqa: E402

GATED_ROLES = None          # демо_bedroom.SOLVER_ROLES — лениво (один список с витриной)


def gated_roles() -> tuple:
    global GATED_ROLES
    if GATED_ROLES is None:
        import demo_bedroom as DB
        GATED_ROLES = tuple(DB.SOLVER_ROLES)
    return GATED_ROLES


def base_role(role: str) -> str:
    parts = (role or '').split(' ')
    return ' '.join(parts[:-1]) if len(parts) > 1 and parts[-1].isdigit() else role


class Facts:
    """Факты готовности комнаты: строки привязки, причина «не читается», индекс прода, карта представителей, режим."""

    def __init__(self, rows: dict | None, why: str, idx: set, rep: dict, mode: str = 'orient'):
        if mode not in RB.MESH_GATE_MODES:
            raise ValueError(f'rooms.<комната>.mesh_gate={mode!r}? можно {", ".join(RB.MESH_GATE_MODES)}')
        self.rows, self.why, self.idx, self.rep_map, self.mode = rows or {}, why, idx, rep, mode

    def rep(self, sku: str) -> str:
        """Представитель семейства (для журнала ожидания, как `bank_ready.Facts.rep`)."""
        return (self.rows.get(sku) or {}).get('representative_offer_id') or sku

    def asset(self, sku: str) -> dict:
        import catalog_items as CI
        return CI.bound_asset({}, self.rows.get(sku), self.why)

    @property
    def mesh_ok(self) -> set:
        """Товары с годной моделью по правилу витрины (как `bank_ready.Facts.mesh_ok`) — метрика ночи `bank_pending`
        («доделано за ночь»; этап Ж: без поля шаг ожидания комнаты падал на записи)."""
        if not hasattr(self, '_mesh_ok'):
            self._mesh_ok = {s for s in self.rows if not RB.usable(self.asset(s), self.msid(s), self.idx, self.mode)[0]}
        return self._mesh_ok

    def msid(self, sku: str) -> str | None:
        """Модель сцены = модель привязки (`room_bindings.scene_msid`, T-20261106-77/4); представитель — только явной привязкой
        (`via_family`), иначе None (T-20261107-25/5)."""
        return RB.scene_msid(self.rows.get(sku), sku.replace(':', '_', 1), self.rep_map)


def load_facts(mode: str | None = None, fetch=None, idx: set | None = None, rep: dict | None = None,
               demo_data: str | None = None) -> Facts:
    """Привязка — одним запросом (`room_bindings.load_db`), индекс прода и представители — те же функции, что у витрины.
    Прод не ответил — модели вчерашнего демо (`demo_data`), как у витрины."""
    import catalog_items as CI
    rows, why = RB.load_db(fetch or CI.fetch)
    if why:
        print(f'WARN:room_ready: привязка не читается ({why}) — у предметов комнаты моделей нет', flush=True)
    if idx is None:
        idx = RB.prod_index(lambda: RB.demo_msids(demo_data) if demo_data else set())
    return Facts(rows, why, idx, RB.mesh_rep() if rep is None else rep, mode or 'orient')


def classify(role: str, sku: str, item: dict | None, F: Facts) -> tuple[str, str | None, str | None]:
    """→ (тип, причина, need) — как `bank_ready.classify`: 'ready' или тип ожидания (`wait_asset`)."""
    if base_role(role) not in gated_roles():
        return 'ready', None, None
    a = F.asset(sku)
    why, _note = RB.usable(a, F.msid(sku), F.idx, F.mode)
    if not why:
        return 'ready', None, None
    if why == RB.QUARANTINED:                 # карантин модели — на разбор (переделка/решение), не выкладка (T-20261107-05/3)
        return 'wait_asset', why, 'review'
    if a['mesh_status'] == 'none':
        return 'wait_asset', why, 'mesh'
    if a['mesh_status'] == 'blocked':
        return 'wait_asset', why, 'review'
    if why in ('модель не выложена', 'нет в индексе прода'):
        return 'wait_asset', why, 'publish'
    return 'wait_asset', why, None


def note(sku: str, F: Facts) -> str:
    """Нерешённый разворот у годного предмета (режим orient) — причина, иначе ''."""
    return RB.usable(F.asset(sku), F.msid(sku), F.idx, F.mode)[1]


# ---------------------------------------------------------------- селфтест
def _row(status, mesh_id='5_r', published=False, reasons=(), rep=None):
    return {'status': status, 'asset_id': 'a:' + 'f' * 64, 'mesh_id': mesh_id, 'local_path': '/x/model.glb',
            'representative_offer_id': rep, 'via_family': bool(rep), 'generation_key': 'g', 'revision_key': 'r',
            'source_sha': 's', 'orientation': None, 'passport': None, 'local_3d': True, 'solver': True, 'appearance': True,
            'published_3d': published, 'reasons': list(reasons), 'warnings': [], 'snapshot_id': 'snap' * 4}


def _selftest() -> int:
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    rows = {'1:a': _row('ready', '1_a', True), '2:b': _row('blocked', '2_b', reasons=['orientation_review_pending']),
            '3:c': _row('blocked', '3_c', reasons=['rep:orientation_missing']), '4:d': _row('blocked', '4_d',
                                                                                         reasons=['passport_mismatch']),
            '6:f': _row('ready', '6_f', False), '7:g': _row('ready', '5_r', True, rep='5:r'), '8:h': _row('ready', '8_h', True),
            '9:i': _row('blocked', '9_i', reasons=['orientation_missing', 'photo_stale'])}
    idx = {'1_a', '2_b', '3_c', '4_d', '6_f', '5_r', '9_i'}
    F = Facts(rows, '', idx, {'7_g': '5_r'})
    S = Facts(rows, '', idx, {'7_g': '5_r'}, 'strict')
    c = lambda sku, role='кровать', FF=F: classify(role, sku, None, FF)  # noqa: E731
    ok('ready + выложена + в индексе — готов', c('1:a') == ('ready', None, None))
    ok('orient: blocked только по развороту (свой и представителя) — готов, заметка в журнал',
       c('2:b')[0] == 'ready' and c('3:c')[0] == 'ready' and note('2:b', F) == 'orientation_review_pending')
    ok('strict: тот же разворот — ждёт (review)', c('2:b', FF=S) == ('wait_asset', 'привязка blocked: orientation_review_pending',
                                                                     'review'))
    ok('blocked не только по развороту — ждёт в обоих режимах', c('9:i')[0] == 'wait_asset' and c('4:d')[2] == 'review')
    ok('ready, но не выложена — ждёт публикации', c('6:f') == ('wait_asset', 'модель не выложена', 'publish'))
    ok('представитель: сцена грузит 5_r = модель привязки — готов', c('7:g') == ('ready', None, None))
    ok('нет в индексе прода — ждёт публикации', c('8:h') == ('wait_asset', 'нет в индексе прода', 'publish'))
    # карантин модели (T-20261107-05/3): причина «карантин модели», разбор (review), не выкладка — и по привязке, и по индексу
    qi = RB.ProdIndex(idx - {'8_h'})
    qi.quarantined = frozenset({'8_h'})
    QF = Facts(dict(rows, **{'q:1': _row('blocked', 'q_1', reasons=['mesh_quarantine:cut']),
                             'q:2': _row('blocked', '5_r', reasons=['rep:mesh_quarantine:reject'], rep='5:r')}),
               '', qi, {'q_2': '5_r'})
    want = ('wait_asset', RB.QUARANTINED, 'review')
    ok('карантин по привязке (свой и представителя) — «карантин модели», review', classify('кровать', 'q:1', None, QF) == want
       and classify('кровать', 'q:2', None, QF) == want)
    ok('привязка ещё «ready», а индекс прода вычел карантин — тоже «карантин модели», не «нет в индексе» (выкладку не зовёт)',
       classify('кровать', '8:h', None, QF) == want and c('8:h')[2] == 'publish')
    ok('товара нет в привязке — ждёт меш (спрос мешей)', c('0:z')[2] == 'mesh' and c('0:z')[0] == 'wait_asset')
    ok('модель сцены = модель привязки, представитель семьи её не перебивает (T-20261106-77/4)',
       Facts(rows, '', idx, {'1_a': '9_9'}).msid('1:a') == '1_a' and c('1:a', FF=Facts(rows, '', idx, {'1_a': '9_9'}))[0] == 'ready')
    ok('записи привязки нет, а семья есть — модели нет (представителя молча не берём, T-25/5); без семьи — свой артикул',
       Facts(rows, '', idx, {'0_z': '9_9'}).msid('0:z') is None and Facts(rows, '', idx, {}).msid('0:z') == '0_z')
    ok('у записи нет модели, а семья есть — модели нет; сторож называет причину',
       Facts({'1:a': _row('ready', None, True)}, '', idx, {'1_a': '9_9'}).msid('1:a') is None
       and classify('кровать', '1:a', None, Facts({'1:a': _row('ready', None, True)}, '', idx, {'1_a': '9_9'}))[1]
       .startswith('модели сцены нет'))
    ok('лампа, ковёр, шторы — моделью не проверяются (как у витрины)', all(c('0:z', r)[0] == 'ready' for r in ('лампа', 'ковёр', 'шторы')))
    ok('пронумерованный экземпляр «тумба прикроватная 2» — проверяется как тумба', c('0:z', 'тумба прикроватная 2')[0] == 'wait_asset')
    U = Facts(None, 'binding_missing', idx, {})
    ok('привязка не читается — предметы солвера ждут (unbound), не «готовы»', classify('шкаф', '1:a', None, U)[1]
       == 'привязка unbound: binding_missing')
    try:
        Facts(rows, '', idx, {}, '0')
        ok('режим 0 у банка запрещён', False)
    except ValueError:
        ok('режим 0 у банка запрещён (выключать сторож можно только витрине)', True)
    ok('представитель для журнала ожидания', F.rep('7:g') == '5:r' and F.rep('1:a') == '1:a')
    # общий индекс: запасной список и карантин
    import io
    import contextlib
    import urllib.request
    keep = urllib.request.urlopen
    try:
        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError('нет сети'))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            got = RB.prod_index(lambda: {'x', 'y'}, quarantine=lambda: {'y'})
        ok('prod_index: прод не ответил — запасной список, карантин вычтен, WARN', got == {'x'} and 'WARN:mesh_index' in buf.getvalue())
    finally:
        urllib.request.urlopen = keep
    ok('mesh_rep: строки БД → карта; нет БД — {}', RB.mesh_rep(lambda q: [['1_a', '5_r'], ['2_b', None]]) == {'1_a': '5_r'}
       and RB.mesh_rep(lambda q: (_ for _ in ()).throw(RuntimeError('нет'))) == {})
    print(f'room_ready: ошибок {bad}')
    return bad


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(1 if _selftest() else 0)
    print(__doc__)
