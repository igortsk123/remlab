"""Сторож «в цене — значит в 3D» (`tools/scout/priced_vs_3d.py --guard`, T-20261113-23, П1.62; владелец TG 1619/1623).

Синтетическая гостиная тем же кодом сцены, что у страницы (помощник `priced_vs_3d_scene.ts` → мост → решатель → что рисуется):
  • диван, столик, комод и лампа на комоде — всё в цене и в 3D: проходит. Лампа на комоде — место `carrier:` (13.11 помощник искал
    её среди ваз `decor:` и писал 27 ложных строк «в цене без 3D» по турам);
  • ПОДЛОЖЕННАЯ строка: та же лампа, но комода нет — лампа в цене без опоры → код 1, ОТКАЗ и DIGEST:!;
  • товар «только в списке» — отказ и в гостиной, и в спальне (`REPORT_ONLY_KINDS` пуст после T-22);
  • ядро гостиной (директор 13.11): вариант без столика или без тумбы/стенки ТВ — отказ «ядро: нет в 3D»; пустой вариант (отказ
    комнаты) и спальня ядро гостиной не проверяют;
  • тур (`--vs`): строка была и в прежней версии — не держим; новая — отказ;
  • сам сторож не сработал (нет пакетов node) — WARN и DIGEST:!, выкладку не держит.
Нужны node и пакеты репо (`node_modules`): в CI — job gate после `pnpm install`.
    python3 tools/scout/tests/test_priced_3d_guard.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, '..', 'priced_vs_3d.py')
sys.path.insert(0, os.path.join(HERE, '..'))
import priced_vs_3d as PV  # noqa: E402

BAD = []


def ok(cond, msg, extra=''):
    print(('OK   ' if cond else 'FAIL ') + msg + (f' — {extra}' if extra and not cond else ''), flush=True)
    if not cond:
        BAD.append(msg)


SOFA = {'role': 'диван', 'x': 200, 'y': 305, 'rot': 180, 'w': 200, 'd': 90, 'h': 80, 'sku': {'name': 'Диван', 'price': 50000, 'msid': 's_1'}}
TABLE = {'role': 'столик', 'x': 150, 'y': 180, 'rot': 0, 'w': 80, 'd': 50, 'h': 45, 'sku': {'name': 'Столик', 'price': 9000, 'msid': 't_1'}}
DRESSER = {'role': 'комод', 'x': 60, 'y': 120, 'rot': 90, 'w': 120, 'd': 45, 'h': 80, 'sku': {'name': 'Комод', 'price': 20000, 'msid': 'c_1'}}
TV = {'role': 'тв-тумба', 'x': 250, 'y': 25, 'rot': 0, 'w': 160, 'd': 40, 'h': 50, 'sku': {'name': 'Тумба ТВ', 'price': 15000, 'msid': 'tv_1'}}
FIT = {'edge_inset_min_cm': 8, 'edge_inset_over_half_base_cm': 3, 'max_share_of_top': 0.2}
LAMP = {'role': 'лампа', 'strategy': 'carrier_surface',
        'place': {'x': 60, 'y': 120, 'bottom_cm': 80, 'slot_instance_id': 'light.lamp#0', 'parent_slot_instance_id': 'light.dresser#0',
                  'anchor': {'kind': 'item_surface', 'surface': 'top'}, 'local': {'dx': 0, 'dy': 0},
                  'carrier': {'role': 'комод', 'ordinal': 0}, 'fit': FIT},
        'sku': {'name': 'Лампа настольная', 'price': 4000, 'msid': 'lp_1', 'w': 25, 'd': 25, 'h': 50}}
LISTED = {'role': 'ваза', 'list_only': True, 'sku': {'name': 'Ваза только в списке', 'price': 1500}}


def data(items, decor, room_id='living'):
    return {'room': {'w': 400, 'd': 350, 'title': 'Комната', 'height_cm': 270, 'openings': []},
            'variants': [{'id': 'v1', 'room_id': room_id, 'style': 'сканди', 'items': items, 'decor': decor}]}


def run(path, *extra, env=None):
    return subprocess.run([sys.executable, TOOL, '--guard', path, *extra], capture_output=True, text=True, timeout=120,
                          env={**os.environ, **(env or {})})


def main() -> int:
    # чистая логика: вид комнаты и деление строк на «блок» и «только отчёт»
    ok(PV.room_kind('bedroom-2') == 'bedroom' and PV.room_kind('living') == 'living' and PV.room_kind(None) == 'living',
       'вид комнаты — id без номера')
    with tempfile.TemporaryDirectory(prefix='priced3d-test-', dir=os.environ.get('REMLAB_TMP') or None) as td:
        def put(name, obj):
            p = os.path.join(td, name)
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(obj, f, ensure_ascii=False)
            return p
        good = put('good.json', data([SOFA, TABLE, TV, DRESSER], [LAMP]))
        r = run(good)
        ok(r.returncode == 0 and 'priced_3d: OK' in r.stdout,
           'гостиная: диван, столик, тумба ТВ, комод, лампа на комоде — всё в 3D, проходит', r.stdout + r.stderr[-300:])
        # ПОДЛОЖЕННАЯ СТРОКА: комода нет — лампа в цене без опоры
        nocarrier = put('nocarrier.json', data([SOFA, TABLE, TV], [LAMP]))
        r = run(nocarrier)
        ok(r.returncode == 1 and 'ОТКАЗ:priced_3d' in r.stdout and 'DIGEST:!' in r.stdout and 'Лампа настольная' in r.stdout
           and 'нет опоры' in r.stdout, 'лампа без комода — в цене без 3D: код 1, ОТКАЗ, строка в сводку, причина «нет опоры»',
           r.stdout + r.stderr[-300:])
        listed = put('listed.json', data([SOFA, TABLE, TV, DRESSER], [LAMP, LISTED]))
        r = run(listed)
        ok(r.returncode == 1 and 'list_only' in r.stdout, 'гостиная: товар «только в списке» — отказ', r.stdout)
        # ЯДРО (директор 13.11): вариант гостиной без столика / без носителя ТВ не выкладывается — даже если всё в цене есть в 3D
        notable = put('notable.json', data([SOFA, TV, DRESSER], [LAMP]))
        r = run(notable)
        ok(r.returncode == 1 and 'гостиная без ядра (диван, столик, носитель ТВ) — 1' in r.stdout and 'в цене без места' not in r.stdout
           and 'столик «ядро» — ядро: нет в 3D' in r.stdout,
           'гостиная без столика — отказ «ядро: нет в 3D»', r.stdout + r.stderr[-300:])
        notv = put('notv.json', data([SOFA, TABLE, DRESSER], [LAMP]))
        r = run(notv)
        ok(r.returncode == 1 and 'носитель ТВ «ядро»' in r.stdout, 'гостиная без тумбы и стенки ТВ — отказ «носитель ТВ»', r.stdout)
        empty = put('empty.json', data([], []))
        r = run(empty)
        ok(r.returncode == 0 and 'priced_3d: OK' in r.stdout, 'пустой вариант (отказ комнаты) ядро не проверяет', r.stdout)
        bed_core = put('bed_core.json', data([DRESSER], [LAMP], room_id='bedroom-1'))
        r = run(bed_core)
        ok(r.returncode == 0 and 'ядро' not in r.stdout, 'спальня: ядро гостиной не требуется', r.stdout)
        r = run(notable, '--vs', good)
        ok(r.returncode == 1 and 'столик' in r.stdout, 'тур: столик пропал против прежней версии — отказ', r.stdout)
        r = run(notable, '--vs', notable)
        ok(r.returncode == 0, 'тур: без столика было и раньше — перевыпуск не держим', r.stdout)
        bed = put('bed.json', data([SOFA, TABLE, DRESSER], [LAMP, LISTED], room_id='bedroom-1'))
        r = run(bed)
        ok(PV.REPORT_ONLY_KINDS == () and r.returncode == 1 and 'ОТКАЗ:priced_3d' in r.stdout and 'list_only' in r.stdout
           and 'только отчёт' not in r.stdout, 'спальня: товар «только в списке» — отказ, как в гостиной (после T-22)', r.stdout)
        r = run(nocarrier, '--vs', nocarrier)
        ok(r.returncode == 0, 'тур: та же строка была в прежней версии — перевыпуск не держим', r.stdout)
        r = run(nocarrier, '--vs', good)
        ok(r.returncode == 1 and 'ОТКАЗ:priced_3d' in r.stdout, 'тур: новая строка против прежней версии — отказ', r.stdout)
        g = PV.guard(nocarrier, good)
        ok(not g['ok'] and len(g['block']) == 1 and g['block'][0]['role'] == 'лампа', 'guard(): одна новая строка — лампа', g)
        r = run(good, env={'REMLAB_NODE_MODULES': os.path.join(td, 'нет-пакетов')})
        ok(r.returncode == 0 and 'WARN:priced_3d: сторож «в цене — в 3D» не сработал' in r.stdout and 'DIGEST:!' in r.stdout,
           'сторож не сработал — WARN и строка в сводку, выкладку не держит', r.stdout + r.stderr[-300:])
    print('итог:', 'OK' if not BAD else f'FAIL ({len(BAD)})')
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
