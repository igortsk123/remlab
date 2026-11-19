#!/usr/bin/env python3
"""ДРАЙВЕР ПРОБЫ UltraTex НА RUNPOD (T-20261119-90/2): подбор карты 80 ГБ по ЖИВОМУ каталогу → под → прогрев → задания → GLB → под ГАСИТСЯ и стоп проверяется.

  runpod_trial.py --dry-run [--image …]            # сухой прогон: живой каталог (цена), баланс, список подов, тело запроса создания. Под НЕ создаётся.
  runpod_trial.py --cap 5 --skus 114667:… 112923:… --shape-dir … --inputs … --out …   # платный прогон; без --cap платное не стартует

Правила (владелец/директор): потолок денег ОБЯЗАТЕЛЕН (--cap, $); срок жизни пода = min(90 мин, потолок/цена·0,85) — под сам выходит по сторожу воркера; драйвер при любом исходе
(успех, исключение, Ctrl-C, потолок) удаляет под и проверяет, что его нет в списке. Ключ RUNPOD_API_KEY и HF_TOKEN читаются из ~/scout-scenes/salad.env тем же помощником, что у Salad
(`migrate_groups.env_from_file`), в журнал и вывод не попадают. Каждое действие — строкой с временем."""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.abspath(os.path.join(HERE, '..', '..', 'salad'))
API = 'https://api.runpod.io/v2'
IMAGE = 'ghcr.io/igortsk123/mesh-ultratex-trial:ultratex-trial'
HARD_LIFETIME_S = 5400
SEC_KEYS = ('RUNPOD_API_KEY', 'HF_TOKEN')


def say(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def redact(text: str) -> str:
    for k in SEC_KEYS:
        v = os.environ.get(k)
        if v and v in text:
            text = text.replace(v, f'<{k}>')
    return text


class Api:
    """Тонкий клиент REST RunPod (https://api.runpod.io/v2, Bearer). transport подменяется в тестах: transport(method, url, headers, data) -> (status, bytes)."""

    def __init__(self, key: str, transport=None):
        self.key, self.transport = key, transport or self._urllib

    @staticmethod
    def _urllib(method, url, headers, data):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return -1, str(e).encode()

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        st, raw = self.transport(method, f'{API}{path}', {'Authorization': f'Bearer {self.key}', 'Content-Type': 'application/json'}, data)
        try:
            return st, json.loads(raw or b'{}')
        except ValueError:
            return st, {'raw': redact(raw[:300].decode('utf-8', 'replace'))}


# ---------------------------------------------------------------- выбор карты и тело пода (чистые функции)
def pick_gpu(catalog: dict, min_gb: int = 80, families=('A100', 'H100'), cloud: str = 'secure') -> dict | None:
    """Самая дешёвая карта ≥ min_gb из семейств, под которые собран образ (A100 sm_80, H100 sm_90). H200/B200 и прочее НЕ берём — не проверяли."""
    best = None
    for g in catalog.get('gpus', []):
        name = (g.get('name') or '') + ' ' + (g.get('id') or '')
        if int(g.get('memory') or 0) < min_gb or not any(f in name for f in families):
            continue
        if not g.get(cloud):
            continue
        price = (g.get('price') or {}).get(cloud)
        if not price or str(g.get('availability', '')).upper() in ('NONE', 'UNAVAILABLE', 'OUT_OF_STOCK'):
            continue
        if best is None or price < best['price']:
            best = {'id': g['id'], 'name': g.get('name'), 'memory': g['memory'], 'price': float(price), 'cloud': cloud.upper(), 'availability': g.get('availability')}
    return best


def lifetime_for_cap(cap_usd: float, price_per_h: float, hard_s: int = HARD_LIFETIME_S) -> int:
    """Срок жизни, за который при этой цене не потратим больше 85 % потолка (запас на докачку/остановку)."""
    return max(300, min(hard_s, int(cap_usd / price_per_h * 3600 * 0.85)))


def pod_body(gpu: dict, image: str, cap_usd: float, hf_token: str = '', registry: str | None = None, disk_gb: int = 120, name: str | None = None) -> dict:
    life = lifetime_for_cap(cap_usd, gpu['price'])
    env = {'MAX_LIFETIME_S': str(life), 'IDLE_S': '900', 'PORT': '8000', 'ULTRATEX_ROOT': '/root/ultratex'}
    if hf_token:
        env['HF_TOKEN'] = hf_token
    body = {'name': name or f"ultratex-trial-{time.strftime('%m%d-%H%M')}", 'image': image, 'cloud': gpu['cloud'], 'disk': disk_gb, 'ports': ['8000/http'], 'env': env,
            'gpu': {'id': gpu['id'], 'count': 1, 'minCudaVersion': '12.4', 'minRamPerGpu': 64}}
    if registry:
        body['registry'] = registry
    return body


def shown_body(body: dict) -> dict:
    """Тело для печати: токены скрыты."""
    out = json.loads(json.dumps(body))
    for k in SEC_KEYS:
        if k in out.get('env', {}):
            out['env'][k] = '<скрыт>'
    return out


# ---------------------------------------------------------------- ход прогона
def pod_url(pod_id: str) -> str:
    return f'https://{pod_id}-8000.proxy.runpod.net'


# Прокси RunPod стоит за Cloudflare, который режет `Python-urllib` (403) — шлём заголовок обычного клиента (T-90/2, 19.11)
UA = 'curl/8.5.0'


def http_json(method: str, url: str, body: dict | None = None, timeout: int = 120) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={'Content-Type': 'application/json', 'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return -1, {}


def terminate_and_verify(api: Api, pod_id: str, tries: int = 6, sleep=time.sleep) -> bool:
    """Удалить под и убедиться, что его нет в списке (или он TERMINATED). Возвращает True при подтверждённом стопе."""
    for i in range(tries):
        st, _ = api.call('DELETE', f'/pods/{pod_id}')
        say(f'удаление пода {pod_id}: HTTP {st}')
        sleep(2 + 2 * i)
        st, lst = api.call('GET', '/pods')
        pods = lst.get('pods', lst if isinstance(lst, list) else [])
        mine = [p for p in pods if p.get('id') == pod_id and p.get('status') != 'TERMINATED']
        if st == 200 and not mine:
            say(f'СТОП ПОДТВЕРЖДЁН: пода {pod_id} нет в списке')
            return True
    say(f'❗ НЕ ПОДТВЕРЖДЁН стоп пода {pod_id} — погасить вручную в консоли RunPod')
    return False


def sku_key(sku: str) -> str:
    return sku.replace(':', '_')


SHAPE_NAME = '{key}-1024-42-0.{tag}.glb'


def shape_path(args, key: str) -> str:
    name = getattr(args, 'shape_name', None) or SHAPE_NAME
    return os.path.join(args.shape_dir, name.format(key=key, tag=args.shape_tag))


def missing_inputs(args) -> list[str]:
    """Файлы формы и фото каждого товара: чего нет — перечислить ДО создания пода (платный под не должен падать на пропавшем файле)."""
    out = []
    for sku in args.skus:
        key = sku_key(sku)
        for f in (shape_path(args, key), os.path.join(args.inputs, f'{key}.rgba.png')):
            if not os.path.isfile(f):
                out.append(f)
    return out


def iso_epoch(s: str) -> float:
    import datetime
    s = s.replace('Z', '+00:00')
    d = datetime.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.timestamp()


def run(api: Api, args, gpu: dict, sleep=time.sleep, now=time.time) -> dict:
    os.makedirs(args.out, exist_ok=True)
    if getattr(args, 'pod_id', None):                         # взять уже созданный под: цена из API, потолок и срок — от его создания
        st, pod = api.call('GET', f'/pods/{args.pod_id}')
    else:
        body = pod_body(gpu, args.image, args.cap, os.environ.get('HF_TOKEN', ''), args.registry)
        st, pod = api.call('POST', '/pods', body)
    summary: dict = {'gpu': gpu, 'cap': args.cap, 'per_sku': {}, 'stop_verified': False}
    if st not in (200, 201, 202) or not pod.get('id'):
        say(f'создание пода отказано: HTTP {st} {redact(json.dumps(pod, ensure_ascii=False)[:300])}')
        summary['error'] = f'create HTTP {st}'
        return summary
    pid, t0 = pod['id'], now()
    if getattr(args, 'pod_id', None) and pod.get('createdAt'):
        t0 = min(t0, iso_epoch(pod['createdAt']))
    price = float(pod.get('cost') or gpu['price'])
    summary.update(pod_id=pid, price_per_h=price)
    say(f'под {pid} {"взят" if getattr(args, "pod_id", None) else "создан"}, цена ${price}/ч, статус {pod.get("status")}, затрат уже ≈ ${(now() - t0) / 3600 * price:.2f}')
    try:
        url = args.pod_url or pod_url(pid)
        deadline = max(t0 + args.warm_timeout, now() + 600) if getattr(args, 'pod_id', None) else t0 + args.warm_timeout
        phase, h = '', {}
        while now() < deadline:
            if (now() - t0) / 3600 * price >= args.cap:
                raise RuntimeError('потолок денег достигнут до готовности')
            st, h = http_json('GET', f'{url}/health', timeout=30)
            if st == 200 and h.get('phase') != phase:
                phase = h['phase']
                say(f"воркер: фаза {phase} {json.dumps(h.get('weights') or {}, ensure_ascii=False)[:200]} {h.get('error', '')[:200]}")
            if st == 200 and phase in ('ready', 'broken'):
                break
            sleep(20)
        if phase != 'ready':
            raise RuntimeError(f'воркер не готов: фаза «{phase or "нет ответа"}» {h.get("error", "") if phase else ""}')
        for sku in args.skus:
            key = sku_key(sku)
            for steps in (getattr(args, 'steps_by_sku', None) or {}).get(sku, args.steps):
                tag = f'{key}-s{steps}'
                png = open(os.path.join(args.inputs, f'{key}.rgba.png'), 'rb').read()
                glb = open(shape_path(args, key), 'rb').read()
                job = {'job_id': tag, 'image_b64': base64.b64encode(png).decode(), 'glb_b64': base64.b64encode(glb).decode(),
                       'resolution': args.resolution, 'steps': steps, 'seed': args.seed}
                st, r = http_json('POST', f'{url}/generate', job, timeout=300)
                say(f'задание {tag}: HTTP {st} {json.dumps(r, ensure_ascii=False)[:120]}')
                if st != 202:
                    summary['per_sku'][tag] = {'status': 'rejected', 'http': st, 'resp': r}
                    continue
                while True:
                    if (now() - t0) / 3600 * price >= args.cap:
                        raise RuntimeError('потолок денег достигнут во время задания')
                    st, r = http_json('GET', f'{url}/result/{tag}', timeout=30)
                    if st == 200 and r.get('status') in ('done', 'failed'):
                        break
                    sleep(10)
                summary['per_sku'][tag] = {'status': r['status'], 'metrics': r.get('metrics'), 'error': r.get('error')}
                if r['status'] == 'done':
                    req = urllib.request.Request(f'{url}/result/{tag}/glb', headers={'User-Agent': UA})
                    with urllib.request.urlopen(req, timeout=300) as resp:
                        open(os.path.join(args.out, f'{tag}-ultratex.glb'), 'wb').write(resp.read())
                    say(f"готово {tag}: {json.dumps(r.get('metrics'), ensure_ascii=False)[:300]}")
                else:
                    say(f"❗ отказ {tag}: {r.get('error')}")
    except BaseException as exc:                              # noqa: BLE001 (в т.ч. Ctrl-C: под гасим при любом исходе)
        summary['error'] = redact(f'{type(exc).__name__}: {exc}')
        say(f"❗ прогон прерван: {summary['error']}")
    finally:
        summary['stop_verified'] = terminate_and_verify(api, pid, sleep=sleep)
        summary['uptime_s'] = round(now() - t0)
        summary['cost_usd_est'] = round(summary['uptime_s'] / 3600 * price, 3)
        with open(os.path.join(args.out, 'summary-ultratex.json'), 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)
        say('ИТОГ ' + json.dumps({k: summary[k] for k in ('pod_id', 'stop_verified', 'uptime_s', 'cost_usd_est')}, ensure_ascii=False))
    return summary


def apply_jobs(args) -> None:
    if args.jobs:
        args.skus, args.steps_by_sku = [], {}
        for j in args.jobs:
            sku, _, st = j.partition('@')
            if sku not in args.skus:
                args.skus.append(sku)
            args.steps_by_sku.setdefault(sku, []).append(int(st or 25))


def dry_run(api: Api, args) -> int:
    miss = missing_inputs(args)
    if args.skus:
        say('файлы формы и фото: ' + ('все найдены' if not miss else 'НЕ НАЙДЕНЫ ' + ', '.join(miss)))
    st, cat = api.call('GET', '/catalog/gpus?include=AVAILABILITY&product=POD')
    say(f'каталог карт: HTTP {st}, карт {len(cat.get("gpus", []))}')
    gpu = pick_gpu(cat)
    st2, bal = api.call('GET', '/billing/balance')
    st3, pods = api.call('GET', '/pods')
    n_pods = len(pods.get('pods', pods if isinstance(pods, list) else []))
    say(f'баланс: HTTP {st2} {json.dumps(bal)[:120]}; подов сейчас: {n_pods} (HTTP {st3})')
    if not gpu:
        say('❗ подходящей карты (A100/H100 80 ГБ) в каталоге нет — тело не собираю')
        return 2
    body = pod_body(gpu, args.image, args.cap or 5.0, os.environ.get('HF_TOKEN', ''), args.registry)
    life = int(body['env']['MAX_LIFETIME_S'])
    say(f"карта: {gpu['name']} {gpu['memory']} ГБ, {gpu['cloud']}, ${gpu['price']}/ч, наличие {gpu['availability']}; срок жизни пода {life} с (≈ ${gpu['price'] * life / 3600:.2f} при потолке ${args.cap or 5.0})")
    print(json.dumps(shown_body(body), ensure_ascii=False, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--image', default=IMAGE)
    ap.add_argument('--registry', default=None, help='id реквизитов реестра RunPod (если пакет GHCR закрытый)')
    ap.add_argument('--cap', type=float, default=None, help='потолок денег, $ (обязателен для платного)')
    ap.add_argument('--skus', nargs='*', default=[])
    ap.add_argument('--shape-dir', default=os.path.expanduser('~/remlab-logs/mesh-models-1118/trellis2'))
    ap.add_argument('--shape-tag', default='clean2')
    ap.add_argument('--shape-name', default=None, help='шаблон имени файла формы в --shape-dir, поля {key} и {tag}; по умолчанию {key}-1024-42-0.{tag}.glb')
    ap.add_argument('--inputs', default=os.path.expanduser('~/remlab-logs/mesh-models-1118/trellis/inputs30'))
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/T-20261119-90/run'))
    ap.add_argument('--steps', type=int, nargs='+', default=[25])
    ap.add_argument('--resolution', type=int, default=2048)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--warm-timeout', type=int, default=2400)
    ap.add_argument('--jobs', nargs='*', default=[], help='точный порядок заданий «товар@шаги» (например 112923:13224664101879413845@25 …); вместо --skus × --steps')
    ap.add_argument('--pod-url', default=None)
    ap.add_argument('--pod-id', default=None, help='взять существующий под (не создавать); цена из API, потолок и срок — от его создания')
    args = ap.parse_args(argv)
    sys.path.insert(0, SALAD)
    import migrate_groups as MG
    MG.env_from_file()
    key = os.environ.get('RUNPOD_API_KEY', '')
    if not key:
        say('нет RUNPOD_API_KEY в ~/scout-scenes/salad.env')
        return 2
    api = Api(key)
    apply_jobs(args)
    if args.dry_run:
        return dry_run(api, args)
    if not args.cap or args.cap <= 0 or args.cap > 5.0:
        say('платное — только с --cap в пределах (0; 5] $ (решение директора: потолок пробы $5)')
        return 2
    if not args.skus:
        say('нет --skus')
        return 2
    if args.pod_id:
        gpu = {'id': 'existing', 'price': 0.0, 'cloud': 'SECURE'}
    else:
        st, cat = api.call('GET', '/catalog/gpus?include=AVAILABILITY&product=POD')
        gpu = pick_gpu(cat)
        if not gpu:
            say('❗ нет карты A100/H100 80 ГБ в наличии — под не создаю')
            return 2
    miss = missing_inputs(args)
    if miss:
        say('❗ нет входных файлов, под не создаю: ' + ', '.join(miss))
        return 2
    res = run(api, args, gpu)
    bad = [k for k, v in res['per_sku'].items() if v.get('status') != 'done']
    return 0 if res.get('stop_verified') and not bad and not res.get('error') else 1


if __name__ == '__main__':
    sys.exit(main())
