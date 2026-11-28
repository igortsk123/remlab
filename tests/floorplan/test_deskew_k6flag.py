"""Изменения rab-4 (97e303407: отсев линий страницы DESKEW_PAGE, запасной проход DESKEW_FALLBACK, запрет доворота у «перспективы» DESKEW_PERSP_VETO) — под СВОЙ флаг
FP_CLEAN_DESKEW_K6 (T-171/k6-porog5; правило «каждая перемена — под своим выключателем»). По умолчанию ВЫКЛ, FP_INPUT_ALL=1 его не включает.

Без OCR и сети (идёт в CI). Золото `golden_deskew_base.json` — результат input_step.run при FP_INPUT_ALL=1 на коде ДО 97e303407 (390acfbc8) на 7 синтетических листах
(ops, угол, размер, steps с матрицами; побайтно по листу сверено вне теста: sha256 совпал с кодом ветки при выкл флаге).
  • все свои флаги выкл + FP_INPUT_ALL=1 → ops, угол, размер, steps как на базе;
  • −контроль: флаг принудительно ВКЛ → результат другой (тонкий план с чёрной полосой доворачивается, лист-трапеция — нет), тест на золото красный."""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(0, str(ROOT / 'tests' / 'floorplan'))
import cleanup as cl  # noqa: E402
import input_step as ins  # noqa: E402
import test_cleanup as TC  # noqa: E402
import test_deskew as TD  # noqa: E402
import test_k6_continuation as K  # noqa: E402

GOLD = json.loads((ROOT / 'tests' / 'floorplan' / 'golden_deskew_base.json').read_text(encoding='utf-8'))


def _pil(img):
    from PIL import Image
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def _thin_with_bar(deg):
    img = K.rotate_like_td(K.thin_grid(), deg)
    cv2.line(img, (0, 40), (img.shape[1] - 1, 40), (0, 0, 0), 14)
    return img


def _keystone(deg):
    rot, _ = TD.rotated(deg)
    h, w = rot.shape[:2]
    src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    dst = np.float32([[w * 0.18, 0], [w * 0.82, 0], [w - 1, h - 1], [0, h - 1]])
    return cv2.warpPerspective(rot, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=(255, 255, 255))


CASES = {
    'rot+10': lambda: TD.rotated(10.0)[0], 'rot-10': lambda: TD.rotated(-10.0)[0], 'rot+4': lambda: TD.rotated(4.0)[0],
    'rot+2': lambda: TD.rotated(2.0)[0], 'rot0': lambda: TC.plan(3, fill=False),
    'thin20_bar': lambda: _thin_with_bar(20.0), 'keystone6': lambda: _keystone(6.0),
}


def _clear(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith('FP_'):
            monkeypatch.delenv(k, raising=False)


def _same_as_gold(name, r):
    g = GOLD[name]
    if r['ops'] != g['ops'] or r['deskew_deg'] != g['deskew_deg'] or list(r['sheet'].size) != g['size'] or len(r['steps']) != len(g['steps']):
        return False
    for a, b in zip(r['steps'], g['steps']):
        if a['op'] != b['op'] or ('H' in a) != ('H' in b):
            return False
        if 'H' in a and not np.allclose(np.array(a['H']), np.array(b['H']), atol=1e-4):
            return False
    return True


def test_flag_is_own_and_off(monkeypatch):
    _clear(monkeypatch)
    assert not cl.flag_deskew_k6() and not ins.flags_from_env()['deskew_k6']
    monkeypatch.setenv('FP_INPUT_ALL', '1')
    f = ins.flags_from_env()
    assert f['deskew'] and not f['deskew_k6']                                              # FP_INPUT_ALL=1 свой флаг НЕ включает
    assert cl.DESKEW_PAGE is False and cl.DESKEW_FALLBACK is False                         # умолчания main_angle — как до 97e303407
    monkeypatch.setenv('FP_CLEAN_DESKEW_K6', '1')
    assert ins.flags_from_env()['deskew_k6'] and cl.flag_deskew_k6()


@pytest.mark.parametrize('name', sorted(CASES))
def test_all_flags_off_with_input_all_is_as_before_97e303407(monkeypatch, name):
    _clear(monkeypatch)
    monkeypatch.setenv('FP_INPUT_ALL', '1')
    flags = ins.flags_from_env()
    assert not flags['deskew_k6'] and not flags['deskew_min5'] and not flags['deskew_guard'] and not flags['quarter_after']
    r = ins.run(_pil(CASES[name]()), flags, scorer=None)
    assert _same_as_gold(name, r), (name, r['ops'], r['deskew_deg'], GOLD[name]['ops'], GOLD[name]['deskew_deg'])


def test_control_flag_on_changes_result_so_golden_goes_red(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv('FP_INPUT_ALL', '1')
    flags = {**ins.flags_from_env(), 'deskew_k6': True}                                    # −контроль: флаг принудительно ВКЛ
    red = [n for n in CASES if not _same_as_gold(n, ins.run(_pil(CASES[n]()), dict(flags), scorer=None))]
    assert 'thin20_bar' in red and 'keystone6' in red, red                                 # золото краснеет именно там, где флаг что-то меняет
    assert 'rot+10' not in red and 'rot0' not in red                                       # обычный поворот и прямой лист флаг не трогает
