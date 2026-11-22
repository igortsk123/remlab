"""Банк берёт название из каталога вместе с фото, ссылкой и размерами (T-20261119-07/5 п.1): магазин переименовал товар («Далти» → «Далти-П»),
а банк хранил прежнее — копии одного товара в туре и /demo расходились. Без базы: `catalog_media.media` подменён.
    ~/venvs/scout/bin/python tools/scout/tests/test_catalog_media_names.py"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import catalog_media as CM  # noqa: E402

bad = 0


def ok(name, cond):
    global bad
    print(('ok   ' if cond else 'FAIL ') + name)
    bad += 0 if cond else 1


def item(**kw):
    return {'mid': '112923', 'eid': '2281', 'name': 'Кровать Далти 160', 'img': 'img/a.jpg', 'url': 'https://s/x', 'shop': 'S',
            'w': 176, 'd': 224, 'h': 127, 'dia': None, **kw}


def media(name='Кровать Далти-П 160', state='available'):
    return {'state': state, 'name': name, 'img': 'img/a.jpg', 'url': 'https://s/x', 'shop': 'S', 'w': 176, 'd': 224, 'h': 127, 'dia': None}


real = CM.media
try:
    sets = [{'items': {'кровать': item(name_en='Dalti 160 bed')}}]
    CM.media = lambda mid, eid: media()
    st = CM.sync_sets(sets)
    it = sets[0]['items']['кровать']
    ok('переименование в каталоге → название банка обновлено', it['name'] == 'Кровать Далти-П 160' and st['fixed_name'] == 1)
    ok('залежавшийся name_en снят (пересчитывается по русскому при сборке)', 'name_en' not in it)
    st2 = CM.sync_sets(sets)
    ok('повтор: нечего менять', st2['fixed_name'] == 0 and sets[0]['items']['кровать']['name'] == 'Кровать Далти-П 160')
    same = [{'items': {'кровать': item(name_en='Dalti 160 bed')}}]
    CM.media = lambda mid, eid: media(name='Кровать Далти 160')
    st3 = CM.sync_sets(same)
    ok('название то же — name_en не трогаем', st3['fixed_name'] == 0 and same[0]['items']['кровать']['name_en'] == 'Dalti 160 bed')
    CM.media = lambda mid, eid: media(name='')
    keep = [{'items': {'кровать': item()}}]
    CM.sync_sets(keep)
    ok('в каталоге названия нет — банковское остаётся', keep[0]['items']['кровать']['name'] == 'Кровать Далти 160')
    CM.media = lambda mid, eid: media(state='gone')
    gone = [{'items': {'кровать': item()}}]
    st4 = CM.sync_sets(gone)
    ok('товар ушёл из продажи — название не трогаем, только метка', gone[0]['items']['кровать']['name'] == 'Кровать Далти 160'
       and gone[0]['items']['кровать'].get('_gone') and st4['fixed_name'] == 0)
    CM.media = lambda mid, eid: media(state='unknown', name='Другое')
    unk = [{'items': {'кровать': item()}}]
    CM.sync_sets(unk)
    ok('источник в карантине — название не трогаем', unk[0]['items']['кровать']['name'] == 'Кровать Далти 160')
    before = copy.deepcopy(sets)
    ok('вход не портится между вызовами', before == sets)
finally:
    CM.media = real
print('итог: ' + ('чисто' if not bad else f'FAIL ({bad})'))
sys.exit(1 if bad else 0)
