"""T-20261112-64: причины «в цене, нет в 3D» (`priced_vs_3d.reason`), ₽ недостающего (`missing_rub`), итоги (`summarize`) и роли
набора банка, которых нет на странице (`bank_not_exported`, `why_absent`). Без сети, node и данных витрины."""
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import priced_vs_3d as P  # noqa: E402


def row(**kw):
    r = {'src': 'decor', 'role': 'ваза', 'price': 1000, 'qty': 1, 'slots': 1, 'shown': 0, 'has_msid': True, 'dims_ok': True}
    r.update(kw)
    return r


def test_reason_by_kind():
    assert P.reason(row(shown=1)) is None                                          # в 3D — не нарушение
    assert P.reason(row(role='подушка', soft=True, has_msid=False)) == P.SOFT       # мягкое: список-только
    assert P.reason(row(role='лампа', list_only=True)) == P.LIST_ONLY
    assert P.reason(row(unplaced=True)) == P.NO_SUPPORT                             # ваза без опоры
    assert P.reason(row(role='картина', wall_art=True, unplaced=True, has_msid=False)) == P.EXTRA_ART
    assert P.reason(row(src='item', role='кресло', has_msid=False)) == P.NO_MESH
    assert P.reason(row(src='item', role='кресло', dims_ok=False)) == P.NO_DIMS
    # ковёр без модели — плита с фото, не «нет меша»; не показан по другой причине — «другое»
    assert P.reason(row(src='item', role='ковёр', has_msid=False, rug=True)) == P.OTHER
    assert P.reason(row(src='item', role='стул', slots=4, shown=2, qty=2, pack=2, qty_shown=1)) == P.PARTIAL


def test_missing_rub_and_summary():
    assert P.missing_rub(row(src='item', price=500, qty=2, qty_shown=1)) == 500     # упаковка стульев: одна из двух не в 3D
    facts = {'/x/demo-data.json': {'variants': [
        {'id': 'set1', 'room_id': 'living', 'style': 'сканди', 'error': '', 'rows': [
            row(role='подушка', soft=True, price=2000), row(role='подушка 2', soft=True, price=3000),
            row(role='ваза', shown=1), row(role='лампа', list_only=True, price=700)]}]}}
    s = P.summarize(facts, 'demo')
    assert (s['priced_rows'], s['priced_rub'], s['missing_n'], s['missing_rub']) == (4, 6700, 3, 5700)
    assert s['by_role']['подушка'] == {'n': 2, 'rub': 5000.0}                      # «подушка 2» — та же роль
    assert list(s['by_reason']) == [P.SOFT, P.LIST_ONLY]                           # по убыванию ₽
    assert s['by_room']['living']['n'] == 3


def test_bank_roles_absent_from_page():
    demo = {'variants': [{'id': 'set2', 'items': [{'role': 'диван', 'sku': {'sid': '1_1'}}],
                          'decor': [{'role': 'ваза', 'sku': {'sid': '1_9'}}], 'dims_unknown': [{'role': 'комод'}]},
                         {'id': 'bedroom-1-scandi', 'items': []}]}
    bank = [{'items': {}}, {'items': {'диван': {'mid': 1, 'eid': 5, 'name': 'Диван другой'},   # товар сменился, роль есть — не строка
                                      'люстра': {'mid': 1, 'eid': 6, 'name': 'Люстра', 'price': 900},
                                      'кресло 2': {'mid': 1, 'eid': 7, 'name': 'Кресло'},
                                      'комод': {'mid': 1, 'eid': 8, 'name': 'Комод'},
                                      'свеча': {'mid': 1, 'eid': 3, 'name': 'Свеча'}}}]
    got = {b['role']: b['why'] for b in P.bank_not_exported(demo, bank, ({'диван', 'кресло', 'комод'}, {'ваза', 'свеча'}))}
    assert got == {'люстра': 'нет в экспорте: роль не выгружается', 'кресло 2': 'раскладка не поставила (роль сцены)',
                   'комод': 'dims_unknown: нет размера — не в сцене', 'свеча': 'декор без товара на странице'}


def test_export_roles_read_from_source(tmp_path):
    src = tmp_path / 'fd.py'
    src.write_text("SHOW_ROLES = ('диван', 'диван 2',\n  'стул')\nDECOR_ROLES = {'ваза', 'часы'}\n", encoding='utf-8')
    assert P.export_roles(str(src)) == ({'диван', 'стул'}, {'ваза', 'часы'})
