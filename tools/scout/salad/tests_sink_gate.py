#!/usr/bin/env python3
"""Ворота приёмника и чистка — одна мера с зазором (mesh-12, T-20261020-09). БЕЗ сети и Salad.

17.10 волна встала: ворота (`sink_health`) судили по счётчику приёмника — 7.1 ГБ, «не принимает»;
чистка (`receiver_purge`) — по `du` комплектов, 0.6 ГБ, «не тесно»; а 39 уже записанных комплектов
держало правило «нет в базе». Счётчик при этом врал на +5.6 ГБ (`receiver.py`). Стенд закрепляет:
  1) лестница одна и с зазором: тесно < ворота < 507 — и по каталогу, и по свободному месту;
  2) каталог МЕЖДУ порогами: ворота открыты, чистка удаляет, не дожидаясь срока хранения;
  3) каталог ВЫШЕ ворот: задания не раздаются (`ssh_run.sink_preflight`/`sink_poll`), уборка идёт;
  4) комплект с моделью удаляется по записи в реестре, а не по `mesh_status='ready'`;
     не записанный — остаётся, старше ORPHAN_H — `WARN:sink_unregistered`, удаляется только с --orphans;
  5) счётчик приёмника сходится с диском после 507, повторной выкладки и DELETE; врущий — пересчитывается.

Запуск: ~/venvs/scout/bin/python tests_sink_gate.py   (CI: python tools/scout/salad/tests_sink_gate.py)
"""
import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import receiver_purge as RP  # noqa: E402
import sink_health as SH  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(('  ✓ ' if cond else '  ✗ ') + what)
    if not cond:
        FAILS.append(what)


def meas(d: float, free: float = 11.8, mx: float = 8.0) -> dict:
    return {'free_gb': free, 'dir_gb': d, 'max_dir_gb': mx, 'refuses': ''}


def case_ladder() -> None:
    print('лестница порогов — одна и с зазором')
    for mx in (8.0, 20.0):
        check(SH.tight_dir_gb(mx) < SH.gate_dir_gb(mx) < mx,
              f'каталог (max {mx:.0f}): тесно {SH.tight_dir_gb(mx)} < ворота {SH.gate_dir_gb(mx)} < 507 на {mx}')
    check(SH.tight_free_gb() > SH.gate_free_gb() > SH.MIN_FREE_GB,
          f'свободно: тесно < {SH.tight_free_gb()} раньше ворот < {SH.gate_free_gb()} раньше 507 < {SH.MIN_FREE_GB}')
    # красное всегда «тесно»: иначе на закрытых воротах уборка не пошла бы
    for m in (meas(7.5), meas(3.0, free=6.0), meas(8.5)):
        check(not SH.verdict(m)['ok'] and bool(SH.tight(m)), f'красное {m["dir_gb"]}/{m["free_gb"]} ГБ — и тесно')
    bad = subprocess.run([sys.executable, '-c', 'import sink_health'], cwd=HERE, capture_output=True, text=True,
                         env={**os.environ, 'MESH_SINK_TIGHT_BELOW_GB': '0'})
    check(bad.returncode != 0 and 'без зазора' in bad.stderr, 'нулевой зазор «тесно» — импорт падает, а не молчит')
    for p in ('receiver_purge.py', 'ssh_run.py', 'sink_keeper.sh'):
        src = open(os.path.join(HERE, p), encoding='utf-8').read()
        check(not any(k in src for k in ('DIR_TIGHT_GB =', 'FREE_MIN_GB =', 'SINK_YELLOW_GB =', 'TRIGGER_GB=')),
              f'{p}: своей копии порога нет')


def kits(n: int, age_h: float, size: int = 15 << 20) -> list:
    return [(f'meshes/hunyuan21/v2/112923_{i}/job{i}', size, age_h) for i in range(n)]


def decide(sets, registered, m, **kw):
    return RP.decide(sets, registered, bool(SH.tight(m)),
                     local_bytes_of=kw.get('loc', lambda d: 15 << 20), model_in=kw.get('model', lambda d: True))


def case_between() -> None:
    print('каталог между порогами (6.5 из 8): ворота открыты, чистка удаляет')
    young = kits(5, age_h=1.0)
    reg = {d for d, _, _ in young}
    m = meas(6.5)
    check(SH.verdict(m)['ok'], 'ворота открыты на 6.5 ГБ')
    check(bool(SH.tight(m)), 'чистка видит «тесно» на 6.5 ГБ')
    purge, keep, _ = decide(young, reg, m)
    check(len(purge) == 5, f'молодые записанные комплекты удаляются без срока хранения ({len(purge)} из 5)')
    purge, keep, _ = decide(young, reg, meas(5.0))
    check(not purge and keep['молодые'] == 5, 'на 5 ГБ не тесно — кэш «уже сделано» держим')
    purge, _, _ = decide(young, reg, meas(2.0, free=7.5))
    check(len(purge) == 5, 'мало свободного (7.5 < 8) — тоже тесно, хотя каталог мал')


def case_above_gate() -> None:
    print('каталог выше ворот (7.1 из 8): задания не раздаются, уборка идёт')
    import ssh_run as S  # noqa: PLC0415
    m = meas(7.1)
    check(not SH.verdict(m)['ok'], 'ворота закрыты на 7.1 ГБ')
    real_get, real_alert, real_canary, real_thread = SH._get, SH.alert_throttled, SH.canary, S.threading.Thread
    calls = {'canary': 0, 'relief': 0}
    SH._get = lambda url, timeout=15: {'ok': True, 'dir_gb': 7.1, 'free_gb': 11.8, 'max_dir_gb': 8.0}
    SH.alert_throttled = lambda text: False
    SH.canary = lambda size_mb=1.0: calls.__setitem__('canary', calls['canary'] + 1) or {'ok': True, 'sec': 0}
    S.threading.Thread = lambda target, daemon=None: type(  # noqa: ARG005 — стенд уборку не запускает
        'T', (), {'start': lambda _s: calls.__setitem__('relief', calls['relief'] + 1)})()
    S._RELIEF.update(busy=False, at=0.0)
    try:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            first = S.sink_preflight()
            S._SINK.update(ok=True, at=0.0)
            polled = S.sink_poll(force=True)
        check(first is False and calls['canary'] == 0, 'перед раздачей: «не принимает», до канарейки не дошло')
        check('задания не раздаю' in out.getvalue(), 'в журнале — «задания не раздаю»')
        check(polled is False and S._SINK['ok'] is False, 'супервизор: воркеры ждут')
        check(calls['relief'] == 1, 'на красном супервизор сам запускает уборку (тесно ⊂ красное)')
    finally:
        SH._get, SH.alert_throttled, SH.canary, S.threading.Thread = real_get, real_alert, real_canary, real_thread
        S._RELIEF.update(busy=False, at=0.0)
        S._SINK.update(ok=True, at=0.0)


def case_incident_1710() -> None:
    print('повтор 17.10: счётчик 7.06 ГБ, комплектов 0.6 ГБ, все 39 записаны (stale/quarantine)')
    sets = kits(39, age_h=64.0, size=16 << 20)
    reg = {d for d, _, _ in sets}
    purge, keep, orph = decide(sets, reg, meas(7.06), loc=lambda d: 16 << 20)
    check(len(purge) == 39 and not orph, f'все 39 уходят — запись в реестре, а не метка ready ({len(purge)})')


def case_unregistered() -> None:
    print('комплект с моделью, но не в реестре')
    sets = kits(2, age_h=10.0) + [('meshes/hunyuan21/v2/99272_7/old', 15 << 20, 50.0)]
    purge, keep, orph = decide(sets, set(), meas(7.5))
    check(not purge and keep['нет в реестре'] == 3, 'даже при «тесно» не удаляется по умолчанию')
    check(orph == ['meshes/hunyuan21/v2/99272_7/old'], 'старше ORPHAN_H — в список «сбой записи»')
    purge, keep, _ = decide(kits(1, 99.0), set(), meas(7.5), model=lambda d: False)
    check(len(purge) == 1, 'без модели (диагностика) — хватает локальной копии, реестр не нужен')
    purge, keep, _ = decide(kits(1, 99.0), {kits(1, 99.0)[0][0]}, meas(7.5), loc=lambda d: 1)
    check(not purge and keep['объём меньше'] == 1, 'оборванная локальная копия — не удаляем')


def run_purge(argv: list, m: dict, real_gb: float, sets: list, registered: set) -> tuple:
    deleted: list = []
    stubs = {'remote_sets': lambda: sets, 'sweep_staging': lambda apply: 0, 'registered_dirs': lambda: registered,
             'remote_bytes': lambda: int(real_gb * 2 ** 30), 'local_bytes': lambda d: 1 << 30,
             'has_model': lambda d: True, 'sink_delete': lambda ds: deleted.extend(ds) or (len(ds), 0)}
    saved = {k: getattr(RP, k) for k in stubs}
    saved_measure, saved_argv = SH.measure, sys.argv
    for k, v in stubs.items():
        setattr(RP, k, v)
    SH.measure = lambda: m
    sys.argv = ['receiver_purge.py', *argv]
    try:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            RP.main()
    finally:
        for k, v in saved.items():
            setattr(RP, k, v)
        SH.measure, sys.argv = saved_measure, saved_argv
    return out.getvalue().strip().splitlines(), deleted


def case_purge_main() -> None:
    print('receiver_purge целиком: сухой режим, --apply, --orphans, сторож расхождения')
    reg_sets = kits(3, age_h=64.0)
    orphan = ('meshes/hunyuan21/v2/99272_9/orph', 15 << 20, 60.0)
    reg = {d for d, _, _ in reg_sets}
    lines, deleted = run_purge([], meas(6.31), 0.71, reg_sets + [orphan], reg)
    check(not deleted, 'без --apply ничего не удаляет')
    check(any('тесно' in ln for ln in lines), 'решение «тесно» взято из меры приёмника (6.31 > 6)')
    check(lines[-2].startswith('WARN:sink_counter_drift') or lines[-1].startswith('WARN:sink_counter_drift'),
          'счётчик 6.31 при 0.71 на диске — WARN:sink_counter_drift в хвосте вывода')
    check(any(ln.startswith('WARN:sink_unregistered') for ln in lines[-2:]), 'WARN:sink_unregistered в хвосте')
    _, deleted = run_purge(['--apply'], meas(6.31), 0.71, reg_sets + [orphan], reg)
    check(sorted(deleted) == sorted(reg), 'с --apply — только записанные в реестр')
    _, deleted = run_purge(['--apply', '--orphans'], meas(6.31), 0.71, reg_sets + [orphan], reg)
    check(orphan[0] in deleted and len(deleted) == 4, 'с --apply --orphans — и не записанные старше ORPHAN_H')
    lines, _ = run_purge([], meas(0.75), 0.71, reg_sets, reg)
    check(not any('WARN:sink_counter_drift' in ln for ln in lines), 'счётчик сходится с диском — тишина')


# ---------------------------------------------------------------- счётчик приёмника
def receiver_server(root: str):
    os.environ.update(MESH_ROOT=root, MESH_SINK_TOKEN='t', MESH_SIZE_RECOUNT_S='1e9')
    R = importlib.reload(sys.modules['receiver']) if 'receiver' in sys.modules else importlib.import_module('receiver')
    R.MIN_FREE_GB = 0.0                 # на DEV /tmp — tmpfs с квотой: свободное место стенда не мерим
    srv = ThreadingHTTPServer(('127.0.0.1', 0), R.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return R, srv, f'http://127.0.0.1:{srv.server_address[1]}'


def http(base: str, method: str, path: str, body: bytes | None = None) -> int:
    req = urllib.request.Request(base + path, data=body, method=method, headers={'Authorization': 'Bearer t'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def put_kit(base: str, prefix: str, files: dict) -> list:
    codes = [http(base, 'PUT', f'/staging/{prefix}/{n}', b) for n, b in files.items()]
    meta = json.dumps({'files': {n: len(b) for n, b in files.items()}}).encode()
    return codes + [http(base, 'POST', f'/complete/{prefix}', meta)]


def case_receiver_counter() -> None:
    print('счётчик приёмника сходится с диском')
    with tempfile.TemporaryDirectory() as root:
        R, srv, base = receiver_server(root)
        try:
            def same(what: str) -> None:
                counted, real = R._SIZE['bytes'], R._walk_bytes()
                check(counted == real, f'{what}: счётчик {counted} = диск {real}')
            R.dir_gb()
            put_kit(base, 'k/a', {'shape.glb': b'x' * 3000, 'manifest.json': b'{}'})
            same('комплект принят')
            put_kit(base, 'k/a', {'shape.glb': b'y' * 1000, 'model.glb': b'z' * 5000, 'manifest.json': b'{}'})
            same('повторная выкладка того же комплекта (полнее)')
            R.MAX_DIR_GB = (R._SIZE['bytes'] + 4000) / 2 ** 30   # первый файл войдёт, второй — 507
            codes = [http(base, 'PUT', '/staging/k/b/shape.glb', b's' * 3000),
                     http(base, 'PUT', '/staging/k/b/model.glb', b'm' * 3000)]
            check(codes == [200, 507], f'второй файл комплекта получил 507 ({codes})')
            same('после 507 посреди комплекта')
            R.MAX_DIR_GB = 8.0
            check(http(base, 'DELETE', '/prefix/k/a') == 204, 'DELETE комплекта')
            same('после DELETE')
            R._SIZE['bytes'] += 5 << 30                       # фантом, как 20.10
            R._SIZE['at'] = 0.0
            R.RECOUNT_S = 600.0
            check(abs(R.dir_gb() - R._walk_bytes() / 2 ** 30) < 1e-9, 'врущий счётчик пересчитан обходом')
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == '__main__':
    for case in (case_ladder, case_between, case_above_gate, case_incident_1710, case_unregistered,
                 case_purge_main, case_receiver_counter):
        case()
    if FAILS:
        print(f'\nПРОВАЛ: {len(FAILS)}')
        sys.exit(1)
    print('\nвсе проверки прошли')
