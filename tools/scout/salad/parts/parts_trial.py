#!/usr/bin/env python3
"""Проба моделей разметки частей на Salad (Ш5 / T-183, T-20261121-179): ОДНА группа = ОДНА нода (4090) = один образ (p3sam | partllm) = пакет мешей по одному заданию на меш.
Бесплатно без --apply (печатает тело группы и список). С --apply — платное (запускать ТОЛЬКО под heavy-slot --prio 2): создать группу → start → ждать running → ждать /health phase=ready →
меши по одному (POST /run, опрос /job, скачать faces.npy/meta.json/faces_class.npy) → стоп с проверкой. ПЕРВЫЙ меш проверяется сразу: число меток = числу граней glb И согласие соседних граней
(метки не «в другом порядке»: доля смежных граней с одной меткой ≥0,85 и заметно выше перемешанных) — иначе стоп. Потолок денег `--cap`, предел времени, сторож тишины: отсчёт от `started`/running
(instance.started=True ИЛИ state=running — что раньше), не от running (урок р.2 21.11). Остановка — всегда (finally), проверка 0 нод."""
import argparse
import base64
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# trellis_trial.py живёт в ветке trial/trellis2-fastwarm (в main его нет) — берём из её worktree, пока ветка не влита; PARTS_TT_DIR переопределяет
_TT = os.environ.get('PARTS_TT_DIR') or (os.path.join(HERE, '..', 'trellis') if os.path.exists(os.path.join(HERE, '..', 'trellis', 'trellis_trial.py')) else os.path.expanduser('~/remlab-logs/t179-1121/wt/tools/scout/salad/trellis'))
sys.path.insert(0, _TT)
import trellis_trial as TT  # noqa: E402  (CARD, READINESS, STARTUP_BAKED, Gateway, цена, cost_usd, say — пути salad/render_gpu он добавляет сам)

say = TT.say
MODELS = ('p3sam', 'partllm')


def build_body(name, image, tier, model, cpu, mem_mb, auth, pre=''):
    env = {'MODEL': model, 'HF_HOME': '/data/hf', 'OUT_DIR': '/data/out', 'PORT': str(TT.PORT), 'NVIDIA_DRIVER_CAPABILITIES': 'all',
           'DEPLOYMENT_EPOCH': f'20261121-{name}', 'IMAGE_NOTE': image.split('@')[-1][:19]}
    # код воркера едет в `command` (как у trellis_trial): образ не пересобирается; в образе лежит та же копия (/app/worker_parts.py) как запасная
    cmd, z = TT.worker_command(os.path.join(HERE, 'worker_parts.py'), python='python', pre=pre)
    env['TRIAL_WORKER_Z'] = z
    return {'name': name, 'display_name': name,
            'container': {'image': image, 'command': cmd, 'resources': {'cpu': cpu, 'memory': mem_mb, 'gpu_classes': [TT.CARD['class_id']], 'storage_amount': 40 * 2 ** 30, 'shm_size': 2048},
                          'priority': tier, 'environment_variables': env, 'image_caching': True, 'registry_authentication': auth},
            'autostart_policy': False, 'restart_policy': 'never', 'replicas': 1, 'priority': tier, 'country_codes': [],
            'networking': {'protocol': 'http', 'port': TT.PORT, 'auth': True, 'load_balancer': 'round_robin', 'single_connection_limit': False,
                           'client_request_timeout': 100000, 'server_response_timeout': 100000},
            'readiness_probe': TT.READINESS, 'startup_probe': TT.STARTUP_BAKED}


def check_faces(glb_path, faces_path):
    """БЕСПЛАТНО на нашей стороне: число меток = граней; согласие смежных граней против перемешанных меток (ловит «грани в другом порядке»)."""
    import numpy as np
    import trimesh
    f = np.load(faces_path)
    m = trimesh.load(glb_path, force='mesh', process=False)
    n = int(len(m.faces))
    r = {'n_faces_glb': n, 'n_labels': int(f.shape[0]), 'count_ok': bool(f.shape == (n,)), 'dtype': str(f.dtype)}
    if not r['count_ok']:
        return r
    mm = m.copy()
    mm.merge_vertices()
    adj = mm.face_adjacency
    a, b = f[adj[:, 0]], f[adj[:, 1]]
    ok = (a >= 0) & (b >= 0)
    agree = float((a[ok] == b[ok]).mean()) if ok.any() else 0.0
    rng = np.random.default_rng(0)
    g = rng.permutation(f)
    ga, gb = g[adj[:, 0]], g[adj[:, 1]]
    okg = (ga >= 0) & (gb >= 0)
    shuf = float((ga[okg] == gb[okg]).mean()) if okg.any() else 0.0
    r.update(adj_pairs=int(len(adj)), adj_agree=round(agree, 4), adj_agree_shuffled=round(shuf, 4), n_parts=int(len([x for x in np.unique(f) if x >= 0])),
             share_unlabeled=round(float((f < 0).mean()), 4), order_ok=bool(agree >= 0.85 and agree > shuf + 0.2))
    return r


_PULL = {}


def pull_guard(name: str, ins: list, n_done: int, limit: int, now: float) -> int:
    """Сторож медленной докачки образа (владелец TG 1069/1070; уроки 734/357): те же `batch_show.cull_verdict` / `_rate_per_min` и
    `node_health.take_cull_slot/reallocate`, что у пула мешей (логику не копируем). Одна нода: «работающих < 2 — не трогать» тут не применяем
    (иначе сторож бесполезен для пробы). Возвращает число сделанных пересадок за вызов."""
    import batch_show as BS
    import node_health as NH
    acts = 0
    for i in ins:
        iid, raw = i.get('id'), i.get('pulling_progress')
        if not iid or i.get('state') != 'downloading' or raw is None:
            continue
        prog = float(raw)
        h = _PULL.setdefault(iid, {'first': now, 'best': prog, 'moved': now, 'obs': [(now, prog)]})
        if prog < h['best'] - 0.10:
            h.update(first=now, best=prog, moved=now, obs=[(now, prog)])
        else:
            if prog > h['best'] + BS.STALL_MIN:
                h.update(best=prog, moved=now)
            h['obs'] = [(t, p) for t, p in h['obs'] + [(now, prog)] if now - t <= 900]
        why = BS.cull_verdict(now - h['first'], h['best'], now - h['moved'], BS._rate_per_min(h['obs']))
        if why and n_done + acts < limit:
            if NH.take_cull_slot():
                say(f'сторож докачки: нода {iid[:8]}: {why} — пересаживаю ({n_done + acts + 1}/{limit})')
                NH.reallocate(name, iid, f'медленная докачка образа: {why}')
                _PULL.pop(iid, None)
                acts += 1
            else:
                say(f'сторож докачки: {why}, но бюджет пересадок исчерпан')
    return acts



def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', required=True, choices=MODELS)
    ap.add_argument('--image', required=True, help='ghcr.io/igortsk123/mesh-parts-trial@sha256:…')
    ap.add_argument('--items', required=True, help='JSON [{"sid","path"}] — меши по порядку (первый проверяется сразу)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--tier', default='high', choices=['batch', 'low', 'medium', 'high'])
    ap.add_argument('--cpu', type=int, default=8)
    ap.add_argument('--mem-mb', type=int, default=32768)
    ap.add_argument('--cap', type=float, default=0.5, help='потолок денег на ОДНУ группу, $')
    ap.add_argument('--max-min', type=int, default=45, help='предел минут после running')
    ap.add_argument('--health-min', type=int, default=12, help='минут от started до первого ответа /health')
    ap.add_argument('--ready-min', type=int, default=25, help='минут от started до phase=ready')
    ap.add_argument('--job-timeout', type=int, default=15)
    ap.add_argument('--pre', default='', help='команда перед воркером (временная заплатка к образу, напр. pip install; в отчёт — отдельной строкой)')
    ap.add_argument('--max-realloc', type=int, default=3, help='сколько раз пересадить медленно качающую образ ноду (0 = не пересаживать); бюджет общий с пулом (node_health)')
    ap.add_argument('--stuck-min', type=float, default=4.0, help='шаг задания не меняется и GPU меньше 5 процентов дольше N мин → считаем зависшим, гасим')
    ap.add_argument('--max-meshes', type=int, default=0, help='после N отправленных прогонов новые не отправлять (0 = без ограничения); дождаться текущего и погасить')
    ap.add_argument('--stop-file', default='', help='если файл существует — новые прогоны не отправлять (текущий дожидаемся, потом гасим); сигнал фоновому процессу НЕ работает')
    ap.add_argument('--variants', default='', help='JSON-файл [{"tag","params"}]: каждый меш прогоняется по всем вариантам подряд (меш за мешом); результаты в <out>/<tag>/<sid>/')
    ap.add_argument('--params', default='{}', help='JSON параметров модели (POST /run params)')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stop-only', action='store_true')
    a = ap.parse_args()
    import bench_run as BR
    import migrate_groups as MG
    name = f'trial-parts-{a.model}-{a.suffix}'
    MG.env_from_file()
    if a.stop_only:
        return 0 if BR.stop_and_verify(name) else 1
    items = json.load(open(a.items))
    VARS = json.load(open(a.variants)) if a.variants else []
    for it in items:
        if not os.path.isfile(os.path.expanduser(it['path'])):
            say('нет файла', it['path'])
            return 2
    price = TT.live_price_usd_h(MG, TT.CARD['class_name'], a.tier)
    src = 'живая'
    if price is None:
        price, src = TT.price_usd_h(a.tier), 'СНИМОК'
    body = build_body(name, a.image, a.tier, a.model, a.cpu, a.mem_mb, MG.ghcr_auth(), a.pre)
    say('группа', name, TT.CARD['class_name'], 'тариф', a.tier, 'цена $/ч', price, f'[{src}]', 'мешей', len(items), 'потолок $', a.cap)
    if not a.apply:
        b = json.loads(json.dumps(body))
        b['container'].pop('registry_authentication', None)
        print(json.dumps(b, ensure_ascii=False, indent=1))
        for it in items:
            print('  меш', it['sid'], it['path'])
        return 0
    if price is None:
        say('цены нет — стоп')
        return 2
    code, d = MG.api('')
    live = [g['name'] for g in d.get('items', []) if (g.get('current_state') or {}).get('status') not in ('stopped', 'failed', None)
            and not g['name'].startswith(('mesh-', 'render-', 'trial-'))]
    if live:
        say(f'живые чужие группы {live} — стоп')
        return 2
    if MG.api(f'/{name}')[0] == 200:
        say(f'группа {name} уже есть — другая --suffix')
        return 2
    code, resp = MG.api('', 'POST', body)
    say('POST создание', code, str(resp)[:200] if code >= 300 else 'ok')
    if code >= 300:
        return 1
    os.makedirs(a.out, exist_ok=True)
    summary = {'group': name, 'model': a.model, 'image': a.image, 'price_usd_h': price, 'cap_usd': a.cap, 'meshes': [], 'stopped_by': None, 'stop_verified': False}
    t_start = started_at = run_since = None
    try:
        for _ in range(480):
            _, st, _c = BR.group_state(name)
            if st == 'stopped':
                break
            time.sleep(5)
        t_start = time.time()
        say('start HTTP', MG.api(f'/{name}/start', 'POST')[0])
        gw = None
        ready = False
        todo = [{**it, 'tag': v.get('tag', ''), 'vparams': v.get('params', {})} for it in items for v in (VARS or [{}])]
        inflight = None
        n_sent = 0
        realloc_n = 0
        durs = []
        last_say = last_wait = 0.0
        first_done = False
        while True:
            t = time.time()
            _, st, cnt = BR.group_state(name)
            _, ins = BR.instances(name)
            i0 = ins[0] if ins else {}
            if run_since is None and ins and a.max_realloc:
                try:
                    realloc_n += pull_guard(name, ins, realloc_n, a.max_realloc, t)
                except Exception as e:  # noqa: BLE001 — сторож не должен ронять пробу
                    say('сторож докачки: сбой', type(e).__name__, str(e)[:100])
            if started_at is None and (i0.get('started') or i0.get('state') == 'running'):
                started_at = t
                summary['to_started_s'] = round(t - t_start, 1)
                say(f'started/running: t+{t - t_start:.0f} с от /start; поля экземпляра: {sorted(i0.keys())}')
            if run_since is None and i0.get('state') == 'running':
                run_since = t
                summary['to_running_s'] = round(t - t_start, 1)
            cost = TT.cost_usd((t - (run_since or t)), price)
            summary['cost_usd_est'] = round(cost, 3)
            if run_since is None and t - last_wait >= 120:
                last_wait = t
                say(f'ждём running: группа {st}, {cnt}, экземпляр {i0.get("state")}, образ {round((i0.get("pulling_progress") or 0) * 100)} %, {t - t_start:.0f} с от /start ($0 до running)')
            if cost >= a.cap:
                say(f'!! ПОТОЛОК ${a.cap}: ≈${cost:.2f} — гашу')
                summary['stopped_by'] = 'money'
                break
            if run_since is not None and t - run_since > a.max_min * 60:
                say(f'!! предел {a.max_min} мин — гашу')
                summary['stopped_by'] = 'time'
                break
            if run_since is None and t - t_start > 3600:
                say('!! час без running — гашу ($0)')
                summary['stopped_by'] = 'no_machine'
                break
            if gw is None and (run_since or started_at):
                dns = ((MG.api(f'/{name}')[1].get('networking') or {}).get('dns') or '')
                if dns:
                    gw = TT.Gateway(f'https://{dns}', os.environ['SALAD_API_KEY'])
                    say('шлюз получен')
            if gw is not None and not ready:
                c, h = gw.call('GET', '/health', timeout=20)
                silent = t - (started_at or t)
                if c == 200:
                    summary['health'] = h
                    if h.get('error') or h.get('phase') in ('load_failed', 'broken'):
                        say('!! загрузка модели упала:', h.get('error'), '— гашу')
                        summary['stopped_by'] = 'load_failed'
                        break
                    if h.get('phase') == 'ready':
                        ready = True
                        summary['to_ready_s'] = round(t - t_start, 1)
                        summary['load_s'] = h.get('load_s')
                        summary['gpu'] = h.get('gpu')
                        say(f'модель готова: t+{t - t_start:.0f} с от /start, загрузка весов {h.get("load_s")} с, gpu {h.get("gpu")}')
                    elif t - last_say >= 120:
                        last_say = t
                        say(f'прогрев: фаза {h.get("phase")}, {t - (started_at or t):.0f} с от started')
                elif started_at is not None and not summary.get('health') and silent > a.health_min * 60:
                    say(f'!! {a.health_min} мин от started /health молчит — гашу')
                    summary['stopped_by'] = 'no_health'
                    break
                if started_at is not None and not ready and silent > a.ready_min * 60:
                    say(f'!! {a.ready_min} мин от started модель не готова — гашу')
                    summary['stopped_by'] = 'not_ready'
                    break
            if ready:
                if inflight is None and todo:
                    why = None
                    sent = len(summary['meshes']) if isinstance(summary.get('meshes'), list) else 0
                    if a.max_meshes and n_sent >= a.max_meshes:
                        why = f'--max-meshes {a.max_meshes} достигнут'
                    elif a.stop_file and os.path.exists(os.path.expanduser(a.stop_file)):
                        why = f'есть файл-стоп {a.stop_file}'
                    elif run_since is not None and durs and t + sum(durs) / len(durs) * 1.05 > run_since + a.max_min * 60:
                        why = f'по средней длительности ({sum(durs) / len(durs):.0f} с) не успеет до предела {a.max_min} мин'
                    if why:
                        say('новые прогоны не отправляю:', why, '— гашу после текущих')
                        summary['stopped_by'] = summary.get('stopped_by') or 'planned'
                        todo = []
                        continue
                    n_sent += 1
                    it = todo.pop(0)
                    sid = it['sid']
                    tag = it.get('tag', '')
                    wsid = f'{sid}__{tag}' if tag else sid
                    glb = open(os.path.expanduser(it['path']), 'rb').read()
                    jid = f'{a.model}-{wsid}'
                    c, r = gw.call('POST', '/run', {'job_id': jid, 'items': [{'sid': wsid, 'glb_b64': base64.b64encode(glb).decode()}], 'params': {**json.loads(a.params), **it.get('vparams', {})}}, timeout=90)
                    inflight = {'sid': sid, 'tag': tag, 'wsid': wsid, 'job': jid, 'path': os.path.expanduser(it['path']), 'submitted': t, 'http': c}
                    say('меш', sid, tag or '-', '→ HTTP', c, f'{len(glb) / 1e6:.1f} МБ')
                    if c != 202:
                        inflight.update(status='failed', error=f'POST {c} {str(r)[:160]}')
                elif inflight is not None:
                    if inflight.get('status') != 'failed':
                        c, r = gw.call('GET', '/job/' + inflight['job'], timeout=30)
                        if c == 200 and r.get('state') != 'done':
                            pg0 = r.get('progress') or {}
                            key = (pg0.get('step'), pg0.get('since'))
                            gpu_idle = (pg0.get('gpu_util') or 0) < 5
                            if inflight.get('stuck_key') != key or not gpu_idle:
                                inflight['stuck_key'], inflight['stuck_since'] = key, t     # шаг сменился или GPU ожил — отсчёт заново
                            if gpu_idle and t - inflight.get('stuck_since', t) > a.stuck_min * 60:
                                say(f'!! завис: шаг {pg0.get("step")} не меняется {(t - inflight["stuck_since"]) / 60:.0f} мин при GPU {pg0.get("gpu_util")} % — гашу')
                                inflight.update(status='failed', error=f'завис на шаге {pg0.get("step")} ({pg0.get("line")})')
                                summary['stopped_by'] = 'stuck'
                                summary['stuck_at'] = pg0
                                break
                        if c == 200 and r.get('state') != 'done' and t - inflight.get('last_prog', 0) >= 120:
                            inflight['last_prog'] = t
                            pg = r.get('progress') or {}
                            say(f'  ход {t - inflight["submitted"]:.0f} с: шаг {pg.get("step")} ({pg.get("step_s")} с), GPU {pg.get("gpu_util")} %, {pg.get("gpu_mem_mb")} МБ, ядер {pg.get("cores_now")}; {str(pg.get("line"))[:90]}')
                        if c == 200 and r.get('state') == 'done':
                            res = (r.get('results') or [{}])[0]
                            inflight.update(status='done' if res.get('rc') == 0 else 'failed', meta=res, error=res.get('error') or r.get('error'))
                            od = os.path.join(a.out, inflight['tag'], inflight['sid']) if inflight.get('tag') else os.path.join(a.out, inflight['sid'])
                            os.makedirs(od, exist_ok=True)
                            for fn in ('meta.json', 'faces.npy', 'faces_class.npy'):
                                cf, raw = gw.call('GET', f'/file/{inflight["job"]}/{inflight["wsid"]}/{fn}', timeout=120, raw=True)
                                if cf == 200:
                                    open(os.path.join(od, fn), 'wb').write(raw)
                            if inflight['status'] == 'done':
                                try:
                                    inflight['check'] = check_faces(inflight['path'], os.path.join(od, 'faces.npy'))
                                    if not (inflight['check'].get('count_ok') and inflight['check'].get('order_ok')):
                                        inflight['status'] = 'failed'
                                        inflight['error'] = f'проверка граней: {inflight["check"]}'
                                except Exception as e:  # noqa: BLE001
                                    inflight.update(status='failed', error=f'check_faces: {type(e).__name__}: {e}'[:300])
                        elif t - inflight['submitted'] > a.job_timeout * 60:
                            inflight.update(status='failed', error=f'меш не закончился за {a.job_timeout} мин')
                        elif c == 200 and ((gw.call('GET', '/health', timeout=20)[1] or {}).get('phase') == 'broken'):
                            inflight.update(status='failed', error='воркер сломан (CUDA)')
                    if inflight.get('status') in ('done', 'failed'):
                        inflight['seconds'] = round(t - inflight['submitted'], 1)
                        if inflight['status'] == 'done':
                            durs.append(inflight['seconds'])
                        summary['meshes'].append(inflight)
                        say('меш', inflight['sid'], inflight.get('tag') or '-', inflight['status'], inflight.get('error') or '', f'{inflight["seconds"]} с', json.dumps({k: (inflight.get('meta') or {}).get(k) for k in ('sec_cold', 'sec_warm', 'peak_vram_gb', 'n_parts', 'n_faces')}), json.dumps(inflight.get('check') or {}))
                        if not first_done:
                            first_done = True
                            if inflight['status'] != 'done':
                                say('!! ПЕРВЫЙ меш не прошёл проверку — гашу сразу, остальные не шлю')
                                summary['stopped_by'] = 'first_mesh_check_failed'
                                break
                        if inflight['status'] == 'failed' and (inflight.get('meta') or {}).get('error', '') and 'CUDA' in str(inflight.get('error')):
                            summary['stopped_by'] = 'worker_broken'
                            break
                        inflight = None
                if inflight is None and not todo:
                    summary['stopped_by'] = summary.get('stopped_by') or 'done'
                    break
            time.sleep(10)
    finally:
        summary['stop_verified'] = BR.stop_and_verify(name)
        summary['running_s'] = round(time.time() - run_since, 1) if run_since else 0.0
        summary['cost_usd_est'] = round(TT.cost_usd(summary['running_s'], price), 3)
        json.dump(summary, open(os.path.join(a.out, f'summary-{name}.json'), 'w'), ensure_ascii=False, indent=1, default=str)
        say('ИТОГ', json.dumps({k: summary.get(k) for k in ('group', 'stopped_by', 'stop_verified', 'running_s', 'cost_usd_est', 'to_ready_s', 'load_s')}, ensure_ascii=False))
    ok = summary['stop_verified'] and summary['stopped_by'] == 'done' and all(m.get('status') == 'done' for m in summary['meshes'])
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
