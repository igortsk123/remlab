"""Разметка бинов библиотеки зерна (T-97/1 фаза 5): по каждому скану — числа узора, поле `grain_marks` в `data/flat3d/top-library/library.json` (items.<бин>.grain_marks).
Читает `part_grain.plan_wood_always` (выбор «спокойного»/«выраженного» запасного бина по числам, не по глазу); пороги — в rules/part-grain.json wood_always.calm_*.
  sigma_L        — σL узора бина (тот же узор, что кладётся на текстуру: `part_grain.pattern_of_bin` — бесшовный, ось по бину, нулевое среднее);
  low_freq       — доля низких частот: σ размытия (GaussianBlur σ=8 px) / σ узора — пятна, сучки (у ровного волокна мала);
  directionality — |Sobel по y| / |Sobel по x| (средние) — вытянутость волокна.
Запуск (venv с numpy, Pillow, opencv): python tools/scout/salad/trellis/part_grain_marks.py [--check]. Новый бин в библиотеке → запустить и закоммитить файл. --check: не пишет, код 1, если разметка в файле не совпадает с пересчётом.
Бины без файла узора пропускаются. Файл пишется как был (indent=1, ensure_ascii=False, без перевода строки в конце)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import part_grain as PG  # noqa: E402
import top_prior as TP  # noqa: E402


def marks_of(name: str, grain_axis: str | None) -> dict:
    import cv2
    pat, s = PG.pattern_of_bin(name, grain_axis)
    p32 = pat.astype(np.float32)
    low = float(cv2.GaussianBlur(p32, (0, 0), 8).std()) / max(s, 1e-6)
    an = float(np.mean(np.abs(cv2.Sobel(p32, cv2.CV_32F, 0, 1))) / max(np.mean(np.abs(cv2.Sobel(p32, cv2.CV_32F, 1, 0))), 1e-6))
    return {'sigma_L': round(s, 4), 'low_freq': round(low, 2), 'directionality': round(an, 2)}


def compute(lib: dict) -> dict:
    tp = TP.load_rules()
    out = {}
    for name, v in lib['items'].items():
        if os.path.exists(os.path.join(PG.ROOT, tp['library_pat'], name + '.jpg')):
            out[name] = marks_of(name, v.get('grain_axis'))
    return out


def main(argv: list | None = None) -> int:
    a = sys.argv[1:] if argv is None else argv
    path = os.path.join(PG.ROOT, TP.load_rules()['library'])
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    lib = json.loads(text)
    new = compute(lib)
    cur = {n: v.get('grain_marks') for n, v in lib['items'].items() if n in new}
    if '--check' in a:
        bad = [n for n in new if cur.get(n) != new[n]]
        print('grain_marks: %d бинов, расхождений %d%s' % (len(new), len(bad), (' — ' + ', '.join(bad[:5])) if bad else ''))
        return 1 if bad else 0
    for n, m in new.items():
        lib['items'][n]['grain_marks'] = m
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(lib, indent=1, ensure_ascii=False))
    print('grain_marks записаны: %d бинов' % len(new))
    return 0


if __name__ == '__main__':
    sys.exit(main())
