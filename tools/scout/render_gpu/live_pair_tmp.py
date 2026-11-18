"""ОДНОРАЗОВАЯ живая проверка T-24/2 (не коммитить): on → ждём «прогрелась» → пара через SaladGpuExecutor ×2 → off.
Сообщения контроллера сухо (RENDER_MACHINE_DRY). Деньги: ≈ прогрев + 2 пары на 4090 ($0,33/ч), потолок скрипта — 25 мин работы."""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
os.environ['RENDER_MACHINE_DRY'] = '1'
os.environ['RENDER_EXECUTOR'] = 'salad-gpu'
PY = os.path.expanduser('~/venvs/scout/bin/python')
RM = os.path.join(HERE, 'render_machine.py')


def rm(*a):
    r = subprocess.run([PY, RM, *a], capture_output=True, text=True, timeout=600)
    out = (r.stdout.strip() or r.stderr.strip())
    print(time.strftime('%H:%M:%S', time.gmtime()), 'rm', ' '.join(a), '→', out[:260], flush=True)
    return out


def main():
    import render_exec as RE
    import render_snapshot as RS
    data = json.load(open(os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json'), encoding='utf-8'))
    out_root = os.path.expanduser('~/remlab-logs/t24-1117/live')
    os.makedirs(out_root, exist_ok=True)
    t0 = time.time()
    print('=== on', flush=True)
    rm('on', '--by', 'live-t24-2')
    warm = False
    try:
        while time.time() - t0 < 900:
            rm('tick')
            s = rm('status', '--json')
            try:
                st = json.loads(s)
            except ValueError:
                st = {}
            if st.get('warm') or st.get('ready') or 'прогрелась' in rm('status'):
                warm = True
                break
            time.sleep(30)
        print('=== прогрелась:', warm, 'за', round(time.time() - t0), 'с', flush=True)
        if not warm:
            return 1
        ex = RE.make_executor({'RENDER_EXECUTOR': 'salad-gpu'})
        for n, vid in enumerate(('set1', 'set1'), 1):
            snap = RS.canonicalize(data, {'v': 1, 'variant_id': vid}, 'demo')
            stages = []
            out = os.path.join(out_root, f'pair{n}-{int(time.time())}')
            t1 = time.time()
            try:
                meta = ex.render(snap, out, lambda st, *_: stages.append((st, round(time.time() - t1, 1))))
                print(f'=== пара {n} ({vid}): {round(time.time() - t1, 1)} с, стадии {stages}', flush=True)
                print(json.dumps(meta, ensure_ascii=False)[:900], flush=True)
            except Exception as e:  # noqa: BLE001
                print(f'=== пара {n} ОШИБКА {type(e).__name__}: {e} code={getattr(e, "code", None)} стадии {stages}', flush=True)
                return 2
        return 0
    finally:
        print('=== off', flush=True)
        rm('off', '--by', 'live-t24-2')
        rm('status')


if __name__ == '__main__':
    sys.exit(main())
