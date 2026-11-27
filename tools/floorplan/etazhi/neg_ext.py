#!/usr/bin/env python3
"""T-171/paket-ext · −контроль теста: в КОПИИ ext.py портится по одной строке — test_ext.py обязан упасть на каждой порче (иначе тест не ловит именно эту ошибку).
Рабочая папка (перезаписывается, ничего не удаляется) — аргумент 1; живой ext.py и репо не меняются.
Запуск: python -I neg_ext.py <рабочая_папка>   → «пропущено N» (0 = все порчи пойманы), код 1 если что-то пропущено."""
import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, 'ext.py'), encoding='utf-8').read()

# (что портим, старый кусок, новый кусок) — каждый кусок должен встречаться в ext.py ровно нужное число раз (проверяется)
MUT = [
    ('узкий допуск TOL_MIN+1 → TOL_MIN', "tol = vf.TOL_MIN + 1.0\n            frac_tol", "tol = vf.TOL_MIN\n            frac_tol"),
    ('полоса: половина толщины → четверть', "band = 0.5 * th * s + vf.TOL_MIN\n                narrow", "band = 0.25 * th * s + vf.TOL_MIN\n                narrow"),
    ('допуск листа 1,2 % → 0,1 %', "frac_tol = 0.012 * max(Hh, Ww)", "frac_tol = 0.001 * max(Hh, Ww)"),
    ('потолок яркости чернил 170 → 100', "GRAY_MAX = 170", "GRAY_MAX = 100"),
    ('бледная: порог rel < r → rel > r', "pale[r].append(best_rel < r)", "pale[r].append(best_rel > r)"),
    ('окно от `from`: правый край пропал', "out[op['wall']].append((off / Lu, (off + wd) / Lu))", "out[op['wall']].append((off / Lu, (off + 0 * wd) / Lu))"),
    ('окно: считаем и дверь (вид по умолчанию)', "WINDOW_TYPES = ('window',)", "WINDOW_TYPES = ('window', 'door')"),
    ('класс без окон: порог «на линии» 0,7 → 0,99', "'на линии' if nar_ex >= 0.7", "'на линии' if nar_ex >= 0.99"),
    ('класс без окон: порог «неполная» 0,35 → 0,05', "'неполная' if nar_ex >= 0.35", "'неполная' if nar_ex >= 0.05"),
    ('coverage: нет наложения не замечено', "    if not ov:\n        return SKIP, 'нет наложения (overlay.json не получен)'", "    if not ov:\n        ov = {'overlay_status': 'легло'}"),
    ('coverage: статус не «легло» не отсекается', "    if stt != 'легло':", "    if False:"),
    ('coverage: вход не «как есть» не отсекается', "    if ov.get('вход', 'как есть') != 'как есть':", "    if False:"),
    ('coverage: пропавший вход не даёт СТОП', "    if lost:\n        return STOP, '; '.join(lost)", "    if False:\n        return STOP, '; '.join(lost)"),
    ('coverage: нет fit.json не считается потерей', "    if not fit:\n        lost.append('нет fit.json')", "    if False:\n        lost.append('нет fit.json')"),
    ('with_ext_numbers: СТОП не поднимает ExtStop', "if kind == STOP and stop:", "if False:"),
    ('with_ext_numbers: «не применяется» без пометки', "st['ext2b'] = st['ext2c'] = 'не применяется: ' + why", "st['ext2b'] = st['ext2c'] = None"),
    ('with_ext_numbers: выкл. 2б/2в всё равно классифицирует', "if not (want_2b or want_2c):", "if False:"),
    ('перевёрнутая ось Y не учтена', "A[1], B[1] = -A[1], -B[1]", "pass"),
    ('поворот плана не применён', "if abs(fit.get('rot_deg') or 0.0) > 1e-9 and fit.get('rot_center_cm'):", "if False:"),
    ('размер картинки не сверяется с sheet_px', "if list(g.shape[::-1]) != list(fit.get('sheet_px') or []):", "if False:"),
    ('допуск «сошлось с walls.csv» 0,03 → 0,9', "SHEET_TOL = 0.03", "SHEET_TOL = 0.9"),
    ('отказ по SOFT_INK убран', "bad.append('SOFT_INK не включён')", "pass"),
    ('отказ по INK_PALE убран', "for nm in ('INK_PALE', 'INK_THICK'):", "for nm in ('INK_THICK',):"),
    ('нет входа: fit=None не ловится', "    if not fit:\n        return _fail(sid, 'нет входа')\n    try:\n        import cv2", "    try:\n        import cv2"),
    ('with_ext_numbers: не-ok числа тоже кладутся', "if e['статус'] == 'ok':\n            o['ext2b'] = e", "if True:\n            o['ext2b'] = e"),
    ('with_ext_numbers: правится исходное наложение', "    o = dict(ov or {})\n    if not (want_2b or want_2c):", "    o = ov if ov is not None else {}\n    if not (want_2b or want_2c):"),
    ('порядок вариантов: b раньше d', "for var in ('d', 'b'):\n            p, im", "for var in ('b', 'd'):\n            p, im"),
    ('applicable: «частично» тоже годится', "ov.get('overlay_status') == 'легло' and", "ov.get('overlay_status') in ('легло', 'частично') and"),
    ('current_hit: порог «на линии» перевёрнут', "line < wf['on_line_min']", "line > wf['on_line_min']"),
    ('длина_м без масштаба', "'длина_м': round(L / s / 100.0, 3), 'узко': round(narrow, 3)", "'длина_м': round(L / 100.0, 3), 'узко': round(narrow, 3)"),
    ('исключение не ловится (нет «сбой»)', "    except Exception as ex:      # noqa: BLE001  (лист не берём в 2б, причину пишем — как мерка)", "    except ZeroDivisionError as ex:"),
]


def main():
    work = os.path.abspath(sys.argv[1])
    os.makedirs(work, exist_ok=True)
    shutil.copy(os.path.join(HERE, 'test_ext.py'), os.path.join(work, 'test_ext.py'))
    shutil.copytree(os.path.join(HERE, 'fixtures'), os.path.join(work, 'fixtures'), dirs_exist_ok=True)
    missed, caught = [], 0
    # контроль без порчи: копия обязана пройти
    open(os.path.join(work, 'ext.py'), 'w', encoding='utf-8').write(SRC)
    r0 = subprocess.run([sys.executable, '-I', 'test_ext.py'], cwd=work, capture_output=True, text=True)
    print('без порчи: код %d (ожидается 0)' % r0.returncode)
    if r0.returncode != 0:
        print(r0.stdout[-600:])
        return 2
    for name, old, new in MUT:
        if SRC.count(old) != 1:
            print('ОШИБКА НАБОРА: «%s» — кусок встречается %d раз (нужно 1)' % (name, SRC.count(old)))
            missed.append(name)
            continue
        open(os.path.join(work, 'ext.py'), 'w', encoding='utf-8').write(SRC.replace(old, new))
        r = subprocess.run([sys.executable, '-I', 'test_ext.py'], cwd=work, capture_output=True, text=True)
        fails = [ln[5:80] for ln in r.stdout.splitlines() if ln.startswith('FAIL')]
        ok = r.returncode != 0
        print('%s %s%s' % ('поймано ' if ok else 'ПРОПУЩЕНО', name, '' if not ok else '  ← ' + (fails[0] if fails else r.stderr.strip().splitlines()[-1][:80] if r.stderr.strip() else 'код %d' % r.returncode)))
        caught += ok
        if not ok:
            missed.append(name)
    open(os.path.join(work, 'ext.py'), 'w', encoding='utf-8').write(SRC)
    print('порч %d, поймано %d, пропущено %d' % (len(MUT), caught, len(missed)))
    return 1 if missed else 0


if __name__ == '__main__':
    sys.exit(main())
