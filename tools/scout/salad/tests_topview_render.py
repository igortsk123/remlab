#!/usr/bin/env python3
"""Вид сверху: пачка доходит до манифеста, адресный прогон не стирает чужие записи, фронт корпусных считается
(T-20261105-36). Настоящий `topview_render.py` на 6 маленьких мешах-коробках во временной папке (TOPVIEW_SRC/OUT),
без сети; ориентация читается из dev-БД (docker) — у выдуманных SKU её нет, берётся 0.

05.11 (волна 2 спальни): пул с `max_tasks_per_child=4` на Python 3.14 зависал на первой замене воркера — 8 моделей
за 22 с, дальше стоял до таймаута, манифест не писался; адресный прогон 49 SKU без обрыва переписал весь манифест
(236 КБ → 11 КБ); `cabinet_front.py --front-by-depth` с 04.09 падал NameError (точка входа стояла выше функции).

Запуск: ~/venvs/scout/bin/python tests_topview_render.py
"""
import ast
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(('  ✓ ' if cond else '  ✗ ') + what, flush=True)
    if not cond:
        FAILS.append(what)


def make_meshes(src: str, n: int) -> list[str]:
    import trimesh
    skus = []
    for i in range(n):
        sku = f'999001:{1000 + i}'
        d = os.path.join(src, sku.replace(':', '_'), f'h{i:04d}')
        os.makedirs(d)
        # вытянутая коробка (не «квадратная»: иначе вид сверху помечает upright_unsure — нам не важно, но ближе к мебели)
        m = trimesh.creation.box(extents=(0.5 + 0.05 * i, 0.4, 0.3))
        m.export(os.path.join(d, 'model.glb'))
        json.dump({'sku': sku, 'role': 'пуф', 'input': {'sha': f's{i}', 'dims_cm': {'w': 50, 'd': 30}}},
                  open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        skus.append(sku)
    return skus


def run(src: str, out: str, **env) -> tuple[int, str]:
    e = dict(os.environ, TOPVIEW_SRC=src, TOPVIEW_OUT=out, TOPVIEW_BUDGET_S='600', **env)
    r = subprocess.run([PY, os.path.join(HERE, 'topview_render.py')], capture_output=True, text=True,
                       timeout=240, env=e)
    return r.returncode, r.stdout + r.stderr


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, 'src'), os.path.join(tmp, 'out')
        skus = make_meshes(src, 6)
        keys = [s.replace(':', '_') for s in skus]

        print('пачка больше смены воркера (6 моделей, 2 процесса, смена каждые 2)')
        try:
            rc, log = run(src, out, TOPVIEW_WORKERS='2', TOPVIEW_TASKS_PER_CHILD='2', TOPVIEW_NEW_CAP='0')
        except subprocess.TimeoutExpired:
            rc, log = -1, 'ТАЙМАУТ 240 с — пул завис'
        check(rc == 0, f'проход завершился сам (rc={rc}) {log[-200:] if rc else ""}')
        man = json.load(open(os.path.join(out, 'topview.json'))) if os.path.exists(os.path.join(out, 'topview.json')) else {}
        check(all(k in man for k in keys), f'все 6 — в манифесте ({len(man)})')
        check(all(os.path.exists(os.path.join(out, f'{k}.png')) and os.path.exists(os.path.join(out, f'{k}.front.png'))
                  for k in keys), 'у всех 6 есть вид сверху и спереди')
        check('отрендерено 6 из 6' in log, 'счётчик «отрендерено 6 из 6»')
        check(not os.path.exists(os.path.join(out, 'topview.json.tmp')), 'манифест записан целиком (нет .tmp)')

        print('адресный прогон дополняет, а не переписывает')
        man['чужой_sku'] = {'png': 'чужой_sku.png', 'yaw': 90.0, 'orient': 'manual'}
        json.dump(man, open(os.path.join(out, 'topview.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        rc, log = run(src, out, TOPVIEW_ONLY=skus[0], TOPVIEW_FORCE='1')
        man2 = json.load(open(os.path.join(out, 'topview.json')))
        check(rc == 0 and 'отрендерено 1 из 1' in log, f'адресный прогон рендерит только свой SKU (rc={rc})')
        check(man2.get('чужой_sku', {}).get('orient') == 'manual', 'чужая запись цела')
        check(all(k in man2 for k in keys), f'остальные свои тоже целы ({len(man2)})')

        print('полный обход каталога по-прежнему пересобирает манифест (уходят записи мешей, которых больше нет)')
        rc, log = run(src, out)
        man3 = json.load(open(os.path.join(out, 'topview.json')))
        check(rc == 0 and 'чужой_sku' not in man3 and all(k in man3 for k in keys),
              f'полный обход: 6 своих, без чужой ({len(man3)})')

        print('ориентация — решение каскада для ИМЕННО этого GLB, кэш помнит решение (T-20261105-36/3)')
        import hashlib
        glb1 = os.path.join(src, keys[1], 'h0001', 'model.glb')
        sha1 = hashlib.sha256(open(glb1, 'rb').read()).hexdigest()[:16]
        idx = os.path.join(tmp, 'orient-index.json')

        def put_index(yaw_exact, md5):
            # у того же SKU есть и ДРУГАЯ ревизия (другой GLB) — её поворот брать нельзя, даже если она «новее»
            json.dump({f'{skus[1]}|{sha1}|orient-v1': ['auto_resolved', 'точный', yaw_exact, md5],
                       f'{skus[1]}|deadbeefdeadbeef|orient-v1': ['auto_resolved', 'чужой', 180.0, 'zzz']},
                      open(idx, 'w', encoding='utf-8'), ensure_ascii=False)

        def new_count(log):
            m = [ln for ln in log.splitlines() if ln.startswith('TOPVIEW_NEW ')]
            return int(m[-1].split()[1]) if m else -1

        put_index(90.0, 'md5a')
        rc, log = run(src, out, TOPVIEW_ORIENT_INDEX=idx)
        m4 = json.load(open(os.path.join(out, 'topview.json')))
        check(rc == 0 and m4[keys[1]]['yaw'] == 90.0 and sha1 in m4[keys[1]].get('orient_sig', ''),
              f"поворот из решения своего GLB: 90, не 180 чужой ревизии ({m4[keys[1]].get('yaw')})")
        check(new_count(log) == 1, f'перерисован только он — поворот сменился с 0 (новых {new_count(log)})')
        put_index(270.0, 'md5c')
        rc, log = run(src, out, TOPVIEW_ORIENT_INDEX=idx)
        m5 = json.load(open(os.path.join(out, 'topview.json')))
        check(rc == 0 and m5[keys[1]]['yaw'] == 270.0 and new_count(log) == 1,
              f"решение пересчитано → без TOPVIEW_FORCE новый поворот и рисунок ({m5[keys[1]].get('yaw')}, новых {new_count(log)})")
        rc, log = run(src, out, TOPVIEW_ORIENT_INDEX=idx)
        check(rc == 0 and new_count(log) == 0, f'то же решение — из кэша (новых {new_count(log)})')
        for v in m5.values():
            v.pop('orient_sig', None)
        json.dump(m5, open(os.path.join(out, 'topview.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        rc, log = run(src, out, TOPVIEW_ORIENT_INDEX=idx)
        m6 = json.load(open(os.path.join(out, 'topview.json')))
        check(rc == 0 and new_count(log) == 0 and all('orient_sig' in m6[k] for k in keys),
              f'старые записи без подписи — без массовой перерисовки, подпись проставлена (новых {new_count(log)})')

        print('фронт корпусных по глубине (cabinet_front --front-by-depth)')
        glb = os.path.join(src, keys[5], 'h0005', 'model.glb')
        r = subprocess.run([PY, os.path.join(HERE, 'cabinet_front.py'), '--front-by-depth', glb],
                           capture_output=True, text=True, timeout=120)
        ok = r.returncode == 0
        try:
            yaw, why = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001 — сам факт сбоя и есть провал проверки
            ok, yaw, why = False, None, r.stderr[-160:]
        check(ok and why in ('cabinet_depth', 'cabinet_unsure', 'cabinet_squarish'),
              f'вызов отрабатывает и отдаёт [yaw, источник] ({yaw}, {why})')
        tree = ast.parse(open(os.path.join(HERE, 'cabinet_front.py'), encoding='utf-8').read())
        mains = [i for i, n in enumerate(tree.body) if isinstance(n, ast.If) and '__main__' in ast.unparse(n.test)]
        later_defs = [n.name for n in tree.body[(mains[-1] + 1 if mains else 0):]
                      if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        check(bool(mains) and not later_defs, f'точка входа — в конце модуля (объявлений после неё: {later_defs})')

    print('стенд вида сверху: ' + ('ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПРОВАЛЫ {len(FAILS)}: {FAILS}'))
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
