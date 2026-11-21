#!/usr/bin/env python3
"""Сторожа вырезки по паспорту типа — диспетчер и ПОЛИТИКА (план mesh-type-passports-01, фаза 1, тень).

Пиксели → числа делает `passport_measure.py` (замер); здесь — (1) закрытый диспетчер сторожей (имя вне списка → ошибка, fail-closed), (2) политика:
числа метрик + пороги паспорта → вердикт (чистые функции — их тестирует замороженная фикстура и `shadow_reverdict`: смена порога пересчитывается из сохранённых
чисел БЕЗ пикселей), (3) запуск сторожа в ДОЧЕРНЕМ ПРОЦЕССЕ с таймаутом (`run_guard_child`: поток убить нельзя, зависший сторож не держит ночную вырезку).

Пороги — только из паспорта (`thresholds` сторожа); пиксельные (`pixel_params`: ΔE потери, ошибка совмещения, срез кромки) входят в замер, их смена = новая
`measurement_version`; остальные применяются к сохранённым числам (перевердикт).

К1 `headboard_loss` (кровать): вердикты `ok` | `headboard_loss` | `ambiguous` (не совместилось с исходником) + подтип `hb_low` (hb_back < порога; НЕ вердикт).
К3 `pillow_plain` (подушка): мягкая метка `pattern_free` | `microtexture` | `pattern` | `unmeasured` — в блок не идёт, решает способ покраски в фазе 2.

  python tools/scout/cutout_guards.py --selftest
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# закрытые списки (дублируют схему загрузчика; расхождение ловит selftest)
GUARDS = ('headboard_loss', 'pillow_plain')
CHILD_CODES = ('ok', 'guard_timeout', 'decode_failed', 'guard_error')


# ------------------------------------------------------------------ политика (чистые функции над числами)
def policy_headboard_loss(m: dict, th: dict) -> tuple:
    """(вердикт, подтип) К1 по метрикам `passport_measure.k1_measure`."""
    if not m.get('registered'):
        return 'ambiguous', None
    hb = m.get('hb_back')
    sub = 'hb_low' if hb is not None and hb < th['hb_back_sub'] else None
    loss = any(c['area_share'] >= th['loss_area_share'] and c['width_share'] >= th['loss_width_share'] for c in m.get('comps') or ())
    return ('headboard_loss' if loss else 'ok'), sub


def policy_pillow_plain(m: dict, th: dict) -> tuple:
    """(мягкая метка, None) К3 по метрикам `passport_measure.k3_measure`."""
    if m.get('note') == 'tiny_inner' or 'p95_total' not in m:
        return 'unmeasured', None
    plain = m['p95_total'] < th['p95_max'] and m['cluster2'] < th['cluster2_max'] and m['boundary'] < th['boundary_max']
    if not plain:
        return 'pattern', None
    return ('microtexture' if m['p95_fine'] >= th['micro_fine_min'] else 'pattern_free'), None


POLICY = {'headboard_loss': policy_headboard_loss, 'pillow_plain': policy_pillow_plain}


def verdict(name: str, metrics: dict, thresholds: dict) -> tuple:
    """(вердикт, подтип) по имени сторожа. Имя вне закрытого списка — ValueError (fail-closed)."""
    if name not in POLICY:
        raise ValueError(f'сторож {name!r} вне списка {GUARDS}')
    return POLICY[name](metrics, thresholds)


# ------------------------------------------------------------------ замер (пиксели; импорт cv2 — внутри, чтобы политику читали и без него)
def measure(guard: dict, cut_rgba, src_rgb=None, object_xy=None) -> dict:
    """Метрики одного сторожа паспорта (`guard` — элемент `cutout.guards[]`). Пиксельные пороги берутся из его `thresholds`."""
    import passport_measure as PM
    name, th = guard['name'], guard['thresholds']
    if name == 'headboard_loss':
        if guard.get('needs_source') and src_rgb is None:
            raise ValueError('headboard_loss: нужен исходник')
        return PM.k1_measure(src_rgb, cut_rgba, object_xy, th['loss_de'], th['register_err_max'])
    if name == 'pillow_plain':
        return PM.k3_measure(cut_rgba, th['edge_erode'])
    raise ValueError(f'сторож {name!r} вне списка {GUARDS}')


def evaluate(role: str, cut_rgba, src_rgb=None, object_xy=None, reg: dict | None = None) -> list:
    """В процессе (для `cutout_redo chain --guards` — измерительный инструмент, в БД не пишет): по каждому сторожу паспорта роли
    [{guard, measurement_version, metrics, verdict, subtype}]. Роли без паспорта/сторожей — []."""
    import mesh_type_passports as MTP
    p = MTP.get(role, reg)
    out = []
    for g in ((p or {}).get('cutout') or {}).get('guards') or ():
        m = measure(g, cut_rgba, src_rgb, object_xy)
        v, sub = verdict(g['name'], m, g['thresholds'])
        out.append({'guard': g['name'], 'measurement_version': g['measurement_version'], 'metrics': m, 'verdict': v, 'subtype': sub})
    return out


# ------------------------------------------------------------------ дочерний процесс с таймаутом
def run_guard_child(guard: dict, cut_path: str, src_path: str | None, object_xy, timeout: float, cmd: list | None = None) -> tuple:
    """Сторож в ОТДЕЛЬНОМ процессе: → (код, метрики|None). Коды (закрытый список): ok | guard_timeout (процесс убит по `timeout`) | decode_failed (битый
    PNG/JPEG: терминально) | guard_error (любое другое падение сторожа: попытка). Не бросает. `cmd` — подмена команды (тест зависшего сторожа)."""
    job = {'guard': guard, 'cut_path': cut_path, 'src_path': src_path, 'object_xy': list(object_xy) if object_xy else None}
    try:
        r = subprocess.run(cmd or [sys.executable, os.path.abspath(__file__), '--child'], input=json.dumps(job), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 'guard_timeout', None
    except Exception:  # noqa: BLE001 — не запустился процесс: это сбой сторожа, не вырезки
        return 'guard_error', None
    if r.returncode == 3:
        return 'decode_failed', None
    if r.returncode != 0:
        return 'guard_error', None
    try:
        return 'ok', json.loads(r.stdout.strip().splitlines()[-1])['metrics']
    except Exception:  # noqa: BLE001
        return 'guard_error', None


def _child() -> int:
    """Тело дочернего процесса: задание JSON со stdin → одна строка JSON {"metrics": …} на stdout."""
    from PIL import Image, PngImagePlugin
    import numpy as np
    PngImagePlugin.MAX_TEXT_CHUNK = 256 * 1024 * 1024   # как в cutout_redo: огромный текстовый блок PNG не повод отказывать
    Image.MAX_IMAGE_PIXELS = None
    job = json.loads(sys.stdin.read())
    try:
        cut = np.asarray(Image.open(job['cut_path']).convert('RGBA'))
        src = np.asarray(Image.open(job['src_path']).convert('RGB')) if job.get('src_path') else None
    except Exception:  # noqa: BLE001 — битый файл
        return 3
    m = measure(job['guard'], cut, src, job.get('object_xy'))
    print(json.dumps({'metrics': m}, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ самотест
def _selftest() -> int:
    import tempfile
    import remlab_tmp
    remlab_tmp.use('cutout_guards')     # временное — на диске, с уборкой (test_tmp_hygiene)
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    import mesh_type_passports as MTP
    reg = MTP.load(force=True)
    k1 = reg['types']['кровать']['cutout']['guards'][0]
    k3 = reg['types']['подушка']['cutout']['guards'][0]
    ok('имена диспетчера = закрытый список схемы', tuple(POLICY) == GUARDS == MTP.GUARD_NAMES)
    ok('сторож вне списка → ValueError (fail-closed)', _raises(lambda: verdict('x', {}, {})))
    t1, t3 = k1['thresholds'], k3['thresholds']
    ok('К1: нет совмещения → ambiguous', verdict('headboard_loss', {'registered': False}, t1) == ('ambiguous', None))
    ok('К1: область ≥4 % и ширина ≥20 % → headboard_loss',
       verdict('headboard_loss', {'registered': True, 'hb_back': 0.4, 'comps': [{'area_share': 0.05, 'width_share': 0.3}]}, t1) == ('headboard_loss', None))
    ok('К1: область большая, но узкая (<20 % ширины) → ok',
       verdict('headboard_loss', {'registered': True, 'hb_back': 0.4, 'comps': [{'area_share': 0.09, 'width_share': 0.1}]}, t1)[0] == 'ok')
    ok('К1: подтип hb_low при hb_back < 0,25 — вердикт не меняет',
       verdict('headboard_loss', {'registered': True, 'hb_back': 0.2, 'comps': []}, t1) == ('ok', 'hb_low'))
    ok('К3: однотонная / микротекстура / рисунок / не измерена',
       verdict('pillow_plain', {'p95_total': 1, 'cluster2': 0, 'boundary': 0, 'p95_fine': 0.5}, t3)[0] == 'pattern_free'
       and verdict('pillow_plain', {'p95_total': 1, 'cluster2': 0, 'boundary': 0, 'p95_fine': 2.5}, t3)[0] == 'microtexture'
       and verdict('pillow_plain', {'p95_total': 9, 'cluster2': 0, 'boundary': 0, 'p95_fine': 0}, t3)[0] == 'pattern'
       and verdict('pillow_plain', {'note': 'tiny_inner'}, t3)[0] == 'unmeasured')
    # перевердикт по порогу — без пикселей: тот же набор чисел, порог p95 строже → другая метка
    m = {'p95_total': 3.0, 'cluster2': 0, 'boundary': 0, 'p95_fine': 0.5}
    ok('смена порога = перевердикт тех же чисел (без пикселей)',
       verdict('pillow_plain', m, t3)[0] == 'pattern_free' and verdict('pillow_plain', m, {**t3, 'p95_max': 2.0})[0] == 'pattern')
    # дочерний процесс на настоящих картинках и по таймауту
    try:
        import numpy as np
        from PIL import Image
        import cv2  # noqa: F401
    except ImportError as e:
        print(f'  - дочерний процесс: пропуск, нет {e.name} (в CI ставится)')
        print(f'cutout_guards selftest: ошибок {bad}')
        return 1 if bad else 0
    with tempfile.TemporaryDirectory() as td:
        h, w = 200, 200
        px = np.full((h, w, 3), (180, 60, 70), np.uint8)
        al = np.zeros((h + 16, w + 16), np.uint8)
        al[8:-8, 8:-8] = 255
        full = np.zeros((h + 16, w + 16, 4), np.uint8)
        full[8:-8, 8:-8, :3] = px
        full[:, :, 3] = al
        cp = os.path.join(td, 'cut.png')
        Image.fromarray(full, 'RGBA').save(cp)
        code, met = run_guard_child(k3, cp, None, None, 60)
        ok('дочерний процесс К3: ok, метрики равны замеру в процессе',
           code == 'ok' and met == measure(k3, np.asarray(Image.open(cp).convert('RGBA'))))
        bp = os.path.join(td, 'broken.png')
        open(bp, 'wb').write(b'not a png')
        ok('битый PNG → decode_failed', run_guard_child(k3, bp, None, None, 60)[0] == 'decode_failed')
        ok('нет файла → decode_failed', run_guard_child(k3, os.path.join(td, 'нет.png'), None, None, 60)[0] == 'decode_failed')
        ok('К1 без исходника → guard_error', run_guard_child(k1, cp, None, (8, 8), 60)[0] == 'guard_error')
        import time
        t0 = time.time()
        code, _ = run_guard_child(k3, cp, None, None, 0.5, cmd=[sys.executable, '-c', 'import time; time.sleep(60)'])
        ok('зависший сторож убит по таймауту (≈0,5 с), код guard_timeout', code == 'guard_timeout' and time.time() - t0 < 10)
        ok('evaluate: роль без сторожей → []', evaluate('комод', np.asarray(Image.open(cp).convert('RGBA')), None, None, reg) == [])
        ev = evaluate('подушка 2', np.asarray(Image.open(cp).convert('RGBA')), None, None, reg)
        ok('evaluate: подушка → один результат К3 с версией замера', len(ev) == 1 and ev[0]['measurement_version'] == 'k3.v1' and ev[0]['verdict'] == 'pattern_free')
    print(f'cutout_guards selftest: ошибок {bad}')
    return 1 if bad else 0


def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


if __name__ == '__main__':
    if '--child' in sys.argv:
        raise SystemExit(_child())
    if '--selftest' in sys.argv:
        raise SystemExit(_selftest())
    print(__doc__)
