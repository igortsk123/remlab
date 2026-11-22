"""T-180/7: кадры приёмки формы — число файлов = товары × виды × света; виды и свет идут из ОДНОЙ таблицы в forms_render.py (в команде Blender нет своих копий)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import forms_render as FR  # noqa: E402


def test_views_one_source_and_roles():
    assert set(FR.VIEWS) <= set(FR.VIEW_DEFS) and set(FR.ACCEPT_VIEWS) <= set(FR.VIEW_DEFS) and set(FR.SEAT_VIEWS) <= set(FR.VIEW_DEFS)
    assert FR.VIEW_DEFS['az180'][0] == 180 and FR.VIEW_DEFS['az090'][0] == 90                          # строго сзади и строго сбоку
    assert 30 <= FR.VIEW_DEFS['top40'][1] <= 45                                                       # косой сверху 30–45°
    assert FR.accept_views('ваза') == FR.ACCEPT_VIEWS and FR.accept_views('') == FR.ACCEPT_VIEWS
    for r in ('диван', 'Кресло', 'стул', 'кушетка'):
        assert FR.accept_views(r) == FR.ACCEPT_VIEWS + FR.SEAT_VIEWS
    assert FR.accept_views('стол обеденный') == FR.ACCEPT_VIEWS and FR.accept_views('столик') == FR.ACCEPT_VIEWS     # «стул» ≠ «стол»


def test_files_count_equals_items_times_views(tmp_path):
    roles = {'a_1': 'ваза', 'b_2': 'диван', 'c_3': 'шкаф', 'd_4': 'кресло'}
    total = 0
    for sku, role in roles.items():
        views = FR.accept_views(role)
        names = FR.frame_names(views, FR.ACCEPT_LIGHTS)
        assert len(names) == len(set(names)) == len(views) * len(FR.ACCEPT_LIGHTS)
        assert FR.frames_of(str(tmp_path), sku, views, FR.ACCEPT_LIGHTS) == []                        # пока ничего нет
        d = tmp_path / sku
        d.mkdir()
        for n in names[:-1]:
            (d / n).write_bytes(b'p')
        assert FR.frames_of(str(tmp_path), sku, views, FR.ACCEPT_LIGHTS) == []                        # без последнего кадра товар не готов
        (d / names[-1]).write_bytes(b'p')
        assert [os.path.basename(x) for x in FR.frames_of(str(tmp_path), sku, views, FR.ACCEPT_LIGHTS)] == names
        total += len(names)
    files = sum(len(fs) for _, _, fs in os.walk(tmp_path))
    assert files == total == 10 + 12 + 10 + 12                                                         # 4 товара: 2 сидячих по 6 видов × 2 света, 2 прочих по 5 × 2


def test_render_cmd_takes_views_from_table():
    cmd = FR.render_cmd('/g.glb', '/o', FR.accept_views('диван'), FR.ACCEPT_LIGHTS, 16, 2)
    spec = cmd[cmd.index('--views') + 1].split(',')
    assert [s.split(':')[0] for s in spec] == list(FR.accept_views('диван'))
    assert all(tuple(float(x) for x in s.split(':')[1:]) == FR.VIEW_DEFS[s.split(':')[0]] for s in spec)
    assert cmd[cmd.index('--lights') + 1] == 'key,graze' and '--shade' not in cmd
    assert '--shade' in FR.render_cmd('/g.glb', '/o', FR.VIEWS, ('key',), 16, 2, 'recalc')
    assert os.path.isfile(FR.RENDER_STAND)                                                            # стенд лежит там, куда указывает команда
    page = FR.frame_names(FR.VIEWS)                                                                  # страница этапа (T-180/5) — прежние имена
    assert page == ['01_az000_clay.png', '02_az225_clay.png']
