"""ЦВЕТ РЕНДЕРА КАК В ЖИВОЙ 3D (T-20261117-23): подкраска товара (`sku.tint`) доходит до записи предмета экспорта; пресет — тон и небо как у живой сцены.
    python tools/scout/tests/test_render_tint.py        # без Blender и сети
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'cycles_probe'))
import export_scene as ES  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


check('подкраска: три множителя в пределах 0,2–3 принимаются как есть', ES.tint_of({'tint': [0.826, 0.729, 0.679]}) == [0.826, 0.729, 0.679])
check('подкраска: целые числа и граничные значения', ES.tint_of({'tint': [1, 3, 0.2]}) == [1.0, 3.0, 0.2])
check('подкраска: нет поля, нет товара — нет подкраски', ES.tint_of({}) is None and ES.tint_of(None) is None)
check('подкраска: чужие данные отвергаются (длина, пределы, не числа, логические)', all(ES.tint_of({'tint': t}) is None for t in (
    [1, 1], [1, 1, 1, 1], [0.1, 1, 1], [1, 4, 1], ['1', 1, 1], [True, 1, 1], 'x', {'r': 1}, [None, 1, 1])))
item = ES.payload_of({'variants': [{'room_id': 'r', 'style': 's', 'id': 'v', 'cams': [], 'items': [{'role': 'шкаф', 'x': 1, 'y': 1, 'w': 100, 'd': 50, 'h': 200,
                                                                                      'sku': {'sid': 'a', 'tint': [0.8, 0.7, 0.6], 'swatch': '#ccc3bc'}}]}],
                      'rooms_geo': {'r': {}}, 'room': {}}, 0)['items'][0]
check('данные для сцены: tint товара не теряется по дороге', item.get('tint') == [0.8, 0.7, 0.6] and item.get('swatch') == '#ccc3bc')

pr = json.load(open(os.path.join(HERE, '..', 'cycles_probe', 'render-preset.json'), encoding='utf-8'))
fl = pr['flags']
check('пресет: тон Khronos PBR Neutral, как у живой 3D (`viewer.ts`)', fl[fl.index('--transform') + 1] == 'Khronos PBR Neutral')
check('пресет: экспозиция −0,15 EV (= 0,9 живой сцены), насыщенность неба 0,4', fl[fl.index('--exposure') + 1] == '-0.15' and fl[fl.index('--sky-sat') + 1] == '0.4')
check('пресет: заполняющий свет белый 6500 К, лампы 1 Вт (стена не теплеет от света сильнее живой)', fl[fl.index('--fill-k') + 1] == '6500' and fl[fl.index('--lamps') + 1] == '1')
print('итог:', 'чисто' if not fails else f'{len(fails)} провал(ов): {fails}')
sys.exit(1 if fails else 0)
