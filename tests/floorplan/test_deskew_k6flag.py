"""Изменения rab-4 (97e303407: отсев линий страницы DESKEW_PAGE, запасной проход DESKEW_FALLBACK, запрет доворота у «перспективы» DESKEW_PERSP_VETO) — под СВОЙ флаг
FP_CLEAN_DESKEW_K6 (T-171/k6-porog5; правило «каждая перемена — под своим выключателем»). По умолчанию ВЫКЛ, FP_INPUT_ALL=1 его не включает.

Без OCR и сети (идёт в CI). «Все свои флаги выкл + FP_INPUT_ALL=1 = как до 97e303407» проверяется ПРЯМЫМ сравнением в ОДНОМ процессе:
старая функция — копия кода 390acfbc8 (tests/floorplan/data/base390/*_base390.py, не править) против новой на 7 синтетических листах: ops, угол, размер, steps
(точное равенство, в т. ч. матрицы H), пиксели листа, cut. Золотого файла нет: числа, снятые на одной версии cv2, ломались на другой (cv2 5.0 против 5.1 — угол 10,0↔9,99), а код в одном
процессе на любой версии cv2 даёт у обеих функций одно и то же.
  • −контроль: флаг K6 принудительно ВКЛ → результат другой (тонкий план с чёрной полосой доворачивается, лист-трапеция — нет), прямое сравнение краснеет."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(0, str(ROOT / 'tests' / 'floorplan'))
sys.path.insert(0, str(ROOT / 'tests' / 'floorplan' / 'data' / 'base390'))
import cleanup as cl  # noqa: E402
import input_step as ins  # noqa: E402
import input_step_base390 as ins_old  # noqa: E402  (код 390acfbc8, не править)
import test_cleanup as TC  # noqa: E402
import test_deskew as TD  # noqa: E402
import test_k6_continuation as K  # noqa: E402


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


def _norm(x):
    """Приведение к сравнимому виду без округления: numpy → списки, числа как есть (точное равенство)."""
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_norm(v) for v in x]
    if isinstance(x, np.ndarray):
        return _norm(x.tolist())
    if isinstance(x, np.generic):
        return x.item()
    return x


def diff_old_new(old, new):
    """Расхождения результатов input_step.run старой и новой функции (пусто = точное равенство)."""
    out = []
    for k in ('ops', 'deskew_deg', 'quarter_k', 'steps', 'cut'):
        if _norm(old[k]) != _norm(new[k]):
            out.append(k)
    if old['sheet'].size != new['sheet'].size:
        out.append('size %s != %s' % (old['sheet'].size, new['sheet'].size))
    elif not np.array_equal(np.asarray(old['sheet']), np.asarray(new['sheet'])):
        out.append('pixels')
    return out


def run_both(name, monkeypatch, k6=False):
    """Старая (390acfbc8) и новая функции, один процесс, одни и те же вход и окружение, все свои флаги выкл (k6=True — только −контроль)."""
    _clear(monkeypatch)
    monkeypatch.setenv('FP_INPUT_ALL', '1')
    old = ins_old.run(_pil(CASES[name]()), ins_old.flags_from_env(), scorer=None)
    flags = ins.flags_from_env()
    assert not flags['deskew_k6'] and not flags['deskew_min5'] and not flags['deskew_guard'] and not flags['quarter_after']
    if k6:
        flags = {**flags, 'deskew_k6': True}                                               # −контроль: флаг принудительно ВКЛ
    new = ins.run(_pil(CASES[name]()), flags, scorer=None)
    return old, new


def test_flag_is_own_and_off(monkeypatch):
    _clear(monkeypatch)
    assert not cl.flag_deskew_k6() and not ins.flags_from_env()['deskew_k6']
    monkeypatch.setenv('FP_INPUT_ALL', '1')
    f = ins.flags_from_env()
    assert f['deskew'] and not f['deskew_k6']                                              # FP_INPUT_ALL=1 свой флаг НЕ включает
    assert cl.DESKEW_PAGE is False and cl.DESKEW_FALLBACK is False                         # умолчания main_angle — как до 97e303407
    monkeypatch.setenv('FP_CLEAN_DESKEW_K6', '1')
    assert ins.flags_from_env()['deskew_k6'] and cl.flag_deskew_k6()


def test_fixture_is_the_base_code():
    """Фикстура — настоящий старый код: модули разные, у новой функции есть то, чего нет у старой."""
    import cleanup_base390 as clo
    assert clo is not cl and ins_old is not ins
    assert not hasattr(clo, 'flag_deskew_k6') and hasattr(cl, 'flag_deskew_k6')
    assert 'deskew_k6' not in ins_old.ENV_OWN and 'deskew_k6' in ins.ENV_OWN


@pytest.mark.parametrize('name', sorted(CASES))
def test_all_flags_off_with_input_all_is_as_before_97e303407(monkeypatch, name):
    old, new = run_both(name, monkeypatch)
    assert diff_old_new(old, new) == [], (name, old['ops'], new['ops'], old['deskew_deg'], new['deskew_deg'])


def test_control_flag_on_changes_result_so_direct_comparison_goes_red(monkeypatch):
    red = [n for n in CASES if diff_old_new(*run_both(n, monkeypatch, k6=True))]
    assert 'thin20_bar' in red and 'keystone6' in red, red                                 # сравнение краснеет именно там, где флаг что-то меняет
    assert 'rot+10' not in red and 'rot0' not in red                                       # обычный поворот и прямой лист флаг не трогает
