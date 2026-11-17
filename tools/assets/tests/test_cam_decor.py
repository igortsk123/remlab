#!/usr/bin/env python3
"""Растения в расчёте ракурса (T-20261117-21): числа `CAM_DECOR` в блоке CAMFIT (`tools/scout/flat215-demo/index.html`) — те же, что правила посадки
сцены (`data/flat3d/plants.json` → `fit`). Блок исполняется и в браузере, и в Node (`tools/flat3d/demo-cams.mjs`) без доступа к файлу данных,
поэтому числа продублированы в нём; этот тест не даёт им разойтись: сменили посадку растения — ракурсы считаются по прежнему размеру.

  кашпо на полу   ↔ `fit.green.floor`   (крона, высота от горла, пределы высоты, погружение)
  ваза со столиком ↔ `fit.dry.table`     (крона, высота от носителя, пределы высоты, погружение)
Запуск: python -m pytest tools/assets/tests/test_cam_decor.py -q"""
import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
HTML = os.path.join(ROOT, 'tools', 'scout', 'flat215-demo', 'index.html')
PLANTS = os.path.join(ROOT, 'data', 'flat3d', 'plants.json')


def _block():
    with open(HTML, encoding='utf-8') as f:
        s = f.read()
    a = s.index('const CAM_DECOR={')
    return s[a:s.index('};', a) + 2]


def _fit(text, key):
    """Объект `fit:{…}` после ключа `key:{` в тексте блока → словарь чисел."""
    a = text.index(key + ':{')
    m = re.search(r'fit:\{([^}]*)\}', text[a:])
    assert m, key
    return {k: float(v) for k, v in re.findall(r'(\w+):\s*(-?[0-9.]+)', m.group(1))}


def test_decor_numbers_match_plants_fit():
    with open(PLANTS, encoding='utf-8') as f:
        fit = json.load(f)['fit']
    block = _block()
    assert _fit(block, 'planter') == {k: float(v) for k, v in fit['green']['floor'].items() if k in
        ('crownOverThroat', 'heightOverThroat', 'minHeightCm', 'maxHeightCm', 'sinkCm')}
    assert _fit(block, 'vase') == {k: float(v) for k, v in fit['dry']['table'].items() if k in
        ('crownOverThroat', 'heightOverCarrier', 'minHeightCm', 'maxHeightCm', 'sinkCm')}


def test_decor_gate_and_roles_present():
    """Штраф перекрытия главного — в общем списке порогов кадра с весом; призрачный декор не покрывается и не входит в окна превью."""
    with open(HTML, encoding='utf-8') as f:
        s = f.read()
    assert "['decor',0.12]" in s and 'decor:2,' in s and 'CAM_BAD_W={' in s
    assert "['decorSelf',0.05]" in s and 'decorSelf:3' in s
    assert 's0.decorSelf=camDecorSelf(c,its)' in s
    # срез главного >15 % отдельным штрафом (keyCut15, T-21/2) убран: на лофте 22.10 он уводил второй вид в пустую стену, на /demo выбор не менял
    assert 's0.decor=camDecorOver(c,its)' in s
    assert 'L=L.map(camDecorAdd)' in s
    assert s.count('if(it.decor)return;') >= 1 and 'if(it.decor||!e||' in s


if __name__ == '__main__':
    test_decor_numbers_match_plants_fit()
    test_decor_gate_and_roles_present()
    print('ok')
