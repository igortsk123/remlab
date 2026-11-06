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
        json.dump({'sku': sku, 'role': 'комод' if i == 3 else 'пуф', 'input': {'sha': f's{i}', 'dims_cm': {'w': 50, 'd': 30}}},
                  open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        skus.append(sku)
    return skus


def glob_glb(src: str, key: str) -> str:
    import glob
    return glob.glob(os.path.join(src, key, '*', 'model.glb'))[0]


def run(src: str, out: str, **env) -> tuple[int, str]:
    # TOPVIEW_PUBLISHED='' — «на проде ничего не опубликовано», без сети (тест может задать свой файл)
    e = dict(os.environ, TOPVIEW_SRC=src, TOPVIEW_OUT=out, TOPVIEW_BUDGET_S='600', TOPVIEW_PUBLISHED='')
    e.update(env)
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

        print('только решённые: yaw нерешённого не меняется, cabinet_front не перебивает (T-20261105-56)')
        sys.path.insert(0, os.path.join(HERE, '..'))
        import orient_policy as OP

        def sha(k):
            g = glob_glb(src, k)
            return hashlib.sha256(open(g, 'rb').read()).hexdigest()[:16]
        pub = os.path.join(tmp, 'published.json')
        json.dump({keys[2]: {'yaw': 270.0, 'orient': 'orient-v1:auto_resolved:orienter+vlm_agree'}},
                  open(pub, 'w', encoding='utf-8'))
        json.dump({f'{skus[1]}|{sha1}|orient-v1': ['auto_resolved', 'orienter+vlm_agree', 270.0, 'md5c'],
                   f'{skus[2]}|{sha(keys[2])}|orient-v1': ['vlm_pending', 'awaiting_vlm', 90.0, 'p1'],
                   f'{skus[4]}|{sha(keys[4])}|orient-v1': ['review_pending', 'vlm_disagree', 180.0, 'r1'],
                   f'{skus[3]}|{sha(keys[3])}|orient-v1': ['auto_resolved', 'orienter+vlm_agree', 90.0, 'c1']},
                  open(idx, 'w', encoding='utf-8'), ensure_ascii=False)
        # прежняя запись комода — перебивка фасадом (180) без подписи: legacy-исключения больше нет
        m6[keys[3]].update({'yaw': 180.0, 'orient': 'orient-v1:cabinet_depth'})
        m6[keys[3]].pop('orient_sig', None)
        json.dump(m6, open(os.path.join(out, 'topview.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        rc, log = run(src, out, TOPVIEW_ORIENT_INDEX=idx, TOPVIEW_PUBLISHED=pub)
        m7 = json.load(open(os.path.join(out, 'topview.json')))
        e2, e4, e3 = m7[keys[2]], m7[keys[4]], m7[keys[3]]
        check(rc == 0 and e2['yaw'] == 270.0 and e2['orient'] == 'unresolved:vlm_pending' and e2['status'] == 'vlm_pending',
              f"vlm_pending: опубликованный поворот 270, не 90 из решения ({e2.get('yaw')}, {e2.get('orient')})")
        check(e4['yaw'] == 0.0 and e4['orient'] == 'unresolved:review_pending' and e4['status'] == 'review_pending',
              f"review_pending, на проде нет: прежний поворот прошлого манифеста 0, не 180 ({e4.get('yaw')})")
        check(e3['yaw'] == 90.0 and 'cabinet' not in e3['orient'] and e3['status'] == 'auto_resolved',
              f"комод: yaw решения 90, cabinet_front не перебивает, старая запись cabinet_depth пересчитана ({e3.get('yaw')}, {e3.get('orient')})")
        check('cabinet_front' not in open(os.path.join(HERE, 'topview_render.py'), encoding='utf-8').read().split('"""', 2)[2]
              .replace('`cabinet_front`', ''), 'в коде вида сверху нет вызова cabinet_front')
        check(all(OP.YAW_POLICY in m7[k]['orient_sig'] and m7[k]['status'] in m7[k]['orient_sig'] for k in keys),
              'подпись кэша = версия правила + статус')

        print('смена правила поворота инвалидирует кэш')
        m7[keys[1]].update({'yaw': 0.0, 'orient': 'старое-правило',
                            'orient_sig': m7[keys[1]]['orient_sig'].replace(OP.YAW_POLICY, 'yaw-p1')})
        json.dump(m7, open(os.path.join(out, 'topview.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        rc, log = run(src, out, TOPVIEW_ORIENT_INDEX=idx, TOPVIEW_PUBLISHED=pub)
        m8 = json.load(open(os.path.join(out, 'topview.json')))
        check(rc == 0 and m8[keys[1]]['yaw'] == 270.0 and m8[keys[1]]['orient'] != 'старое-правило'
              and new_count(log) == 1,
              f"подпись прежней версии правила — запись пересчитана и перерисована ({m8[keys[1]].get('yaw')}, новых {new_count(log)})")
        rc, log = run(src, out, TOPVIEW_ORIENT_INDEX=idx, TOPVIEW_PUBLISHED=pub)
        check(rc == 0 and new_count(log) == 0, f'та же версия — из кэша (новых {new_count(log)})')

        print('публикация orient.json: только решённые, прод нерешённым не затирается')
        import publish_merge as PM
        prod = {keys[2]: {'yaw': 270.0, 'orient': 'x'}, keys[4]: {'yaw': 90.0, 'orient': 'orient-v1:cabinet_depth'},
                keys[1]: {'yaw': 0.0, 'orient': 'human:orient-review:cur'}, keys[3]: {'yaw': 180.0, 'orient': 'orient-v1:cabinet_depth'}}
        merged, held = PM.merge(prod, m8, only_resolved=True)
        check(merged[keys[2]] == prod[keys[2]] and merged[keys[4]] == prod[keys[4]],
              'vlm_pending/review_pending — прод-значение без изменений')
        check(keys[0] not in merged and keys[5] not in merged, 'без решения — в прод не добавляется')
        check(merged[keys[3]]['yaw'] == 90.0 and merged[keys[3]]['status'] == 'auto_resolved',
              'решённый комод заменяет прежний cabinet_depth, со status')
        check(merged[keys[1]] == prod[keys[1]], 'ручное решение прода автоматическим не затирается')
        check(held == 5, f'не пошло по фильтру: 5 ({held})')
        merged_all, _ = PM.merge(prod, m8)
        check(merged_all[keys[2]]['yaw'] == 270.0 and keys[0] in merged_all, 'без флага — прежнее слияние (mesh-index)')
        bs = open(os.path.join(HERE, 'batch_show.py'), encoding='utf-8').read()
        step = [ln for ln in bs.splitlines() if "'ориент-паблиш'" in ln]
        check(len(step) == 1 and '--only-resolved' in step[0], 'шаг «ориент-паблиш» публикует с --only-resolved')

        print('симметричные: случайный yaw БД нигде не всплывает (ведущий 06.11)')
        ix = json.load(open(idx, encoding='utf-8'))
        ix[f'{skus[0]}|{sha(keys[0])}|orient-v1'] = ['auto_resolved', 'symmetric_by_role', 90.0, 's0']
        ix[f'{skus[5]}|{sha(keys[5])}|orient-v1'] = ['auto_resolved', 'symmetric_by_role:upright', 90.0, 's5']
        json.dump(ix, open(idx, 'w', encoding='utf-8'), ensure_ascii=False)
        pubd = json.load(open(pub, encoding='utf-8'))
        pubd[keys[0]] = {'yaw': 270.0, 'orient': 'orient-v1:symmetric:sync'}
        json.dump(pubd, open(pub, 'w', encoding='utf-8'))
        rc, log = run(src, out, TOPVIEW_ORIENT_INDEX=idx, TOPVIEW_PUBLISHED=pub)
        m9 = json.load(open(os.path.join(out, 'topview.json')))
        s0, s5 = m9[keys[0]], m9[keys[5]]
        check(rc == 0 and s0['yaw'] == 270.0 and 'symmetric:kept' in s0['orient'],
              f"симметричный с прод-значением: манифест держит прод 270, не 90 БД ({s0.get('yaw')}, {s0.get('orient')})")
        check(s5['yaw'] == 0.0 and 'symmetric:zero' in s5['orient'],
              f"новый симметричный: манифест 0, не 90 БД ({s5.get('yaw')}, {s5.get('orient')})")
        prod9 = {**prod, keys[0]: pubd[keys[0]]}
        merged9, _ = PM.merge(prod9, m9, only_resolved=True)
        check(merged9[keys[0]] == prod9[keys[0]], 'симметричный с прод-значением — прод не меняется')
        check(merged9[keys[5]]['yaw'] == 0.0 and 'symmetric:zero' in merged9[keys[5]]['orient']
              and merged9[keys[5]]['status'] == 'auto_resolved', 'новый симметричный в прод: yaw 0, symmetric:zero, status')
        forced = {**m9, keys[5]: {**s5, 'yaw': 90.0, 'orient': 'orient-v1:auto_resolved:symmetric_by_role'}}
        check(PM.merge({}, forced, only_resolved=True)[0][keys[5]]['yaw'] == 0.0,
              'даже если в манифест попал 90 — в прод уходит 0')
        check(all(float(v['yaw']) != 90.0 for k, v in merged9.items() if k in (keys[0], keys[5]))
              and all(float(m9[k]['yaw']) != 90.0 for k in (keys[0], keys[5])), 'yaw 90 из БД — ни в манифесте, ни в проде')
        check(not OP.yaw_sure(merged9[keys[5]]), 'серверный кадр: симметричный не «уверенный» → 0, как прежде')

        print('серверный 3D-кадр: «уверенный» по status, cabinet_* — нет')
        dr = open(os.path.join(HERE, '..', 'draft_render.py'), encoding='utf-8').read()
        check("'cabinet_'" not in dr and 'sure = _yaw_sure(oinfo)' in dr, 'draft_render: sure = orient_policy.yaw_sure')
        check(not OP.yaw_sure({'yaw': 180, 'orient': 'orient-v1:review_pending:cabinet_conflict', 'status': 'review_pending'})
              and not OP.yaw_sure({'yaw': 180, 'orient': 'orient-v1:cabinet_depth'})
              and OP.yaw_sure(merged[keys[3]]), 'cabinet_conflict/cabinet_depth не уверенные, решённый — уверенный')

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
