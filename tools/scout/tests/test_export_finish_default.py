"""ОТДЕЛКА ПО УМОЛЧАНИЮ В ВЫГРУЗКЕ СЦЕНЫ (T-20261118-03/9): у комнаты тура паспорта отделки нет, Blender падал на `M['finish']['wall']`.
Проверяем: набор совпадает со страницей (`lib/viewer3d/finish-passport.ts`), своё не трогается, пол с фактурой сохраняет `tex`. python tools/scout/tests/test_export_finish_default.py"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', 'cycles_probe')]
import export_scene as ES  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


ts = open(os.path.join(HERE, '..', '..', '..', 'lib', 'viewer3d', 'finish-passport.ts'), encoding='utf-8').read()
body = ts[ts.index('export const DEFAULT_FINISH'):]
body = body[:body.index('};')]
page = {m.group(1): {'id': m.group(2), 'colorHex': m.group(3)} for m in re.finditer(r'(\w+): \{ id: "([^"]+)", colorHex: "(#[0-9a-fA-F]{6})" \}', body)}
check('набор по умолчанию совпадает со страницей (`DEFAULT_FINISH`)', page == ES.DEFAULT_FINISH and len(page) == 4)
for empty in (None, {}, 'x', []):
    check(f'паспорта нет ({empty!r}) — все четыре поверхности по умолчанию', ES.with_default_finish(empty) == ES.DEFAULT_FINISH)
own = {'wall': {'id': 'paint-x', 'colorHex': '#112233'}, 'floor': {'colorHex': '#445566', 'tex': {'src': 'a.jpg'}}}
got = ES.with_default_finish(own)
check('свои поверхности не трогаем, недостающие — по умолчанию', got['wall'] == own['wall'] and got['floor'] == own['floor'] and got['ceiling'] == ES.DEFAULT_FINISH['ceiling'] and got['skirting'] == ES.DEFAULT_FINISH['skirting'])
check('фактура пола без цвета не теряется: цвет по умолчанию + `tex`', ES.with_default_finish({'floor': {'tex': {'src': 'b.jpg'}}})['floor'] == {**ES.DEFAULT_FINISH['floor'], 'tex': {'src': 'b.jpg'}})
check('вход не меняется', own['wall'] == {'id': 'paint-x', 'colorHex': '#112233'} and 'ceiling' not in own)
print('\nВСЕГО провалов:', len(fails))
sys.exit(1 if fails else 0)
