#!/usr/bin/env python3
"""ПЕРЕВЫРЕЗКА ВСЕХ ТОВАРОВ ЖИВОГО /demo (T-20261119-104, владелец TG 2098/2102): список → маски на Salad → цепочка у нас → папка на проверку.

ЗАЧЕМ. Владелец: «сначала демо только укомплектовать, вырезать и дать мне на проверку визуально, что косяков нет». Меши не делаем — только вырезка.

УСТРОЙСТВО (три шага, каждый можно гонять отдельно и повторять на той же папке):
  list   — какие товары показывает живое /demo (`demo-data.json`, обход карточек как у `product_names.cards`), у каждого роль, адрес фото (то же
           правило, что у хеша фото и меша: `product_photo_current`, нет — `mesh_photo.photo_sql`) и есть ли вырезка текущей версии (`photo_assessment`).
  masks  — ОДНА машина Salad в режиме `MASK_ONLY` (группа-канарейка `mesh-q-mask-canary`, образ — слой поверх боевого, `salad/image_append.py`):
           нода считает ТОЛЬКО маску BiRefNet (Hunyuan не грузится), мы кладём её рядом (`masks/<sha>.png`, сырая, как пришла). Деньги — по времени
           `running` × тариф группы, потолок `--cap` ($3), стоп по потолку/времени/серии отказов; в конце группа ГАСИТСЯ и проверяется `stopped`.
  chain  — цепочка вырезки `cutout_sync.chain` (гибрид → связность → заливка → чистка ореола → обрезка) по сохранённым маскам, на нашем ЦП: правка цепочки
           после отметок владельца перегоняется БЕЗ новой оплаты Salad. Вырезки — в `cut/<sha>.png` ЭТОЙ папки; боевой кэш `~/scout-scenes/cutouts`
           и таблица `photo_assessment` не трогаются (откат тривиален: ничего не менялось).

Папка прогона — `~/remlab-logs/t104-1119/<метка>/` (метка по умолчанию — время старта; повтор — `--run <метка>`). Всё в ней: products.json, photos/, masks/, cut/,
masks.jsonl (результат каждого фото), chain.jsonl, summary-*.json, log.txt.

  ~/venvs/scout/bin/python cutout_redo.py list
  ~/venvs/scout/bin/python cutout_redo.py masks --run <метка> --trial 5           # проба: 5 товаров (комод, диван, люстра с тросами — первыми)
  ~/venvs/scout/bin/python cutout_redo.py masks --run <метка> --all               # все, чего ещё нет в masks/
  ~/venvs/scout/bin/python ../ops/heavy-slot.sh … cutout_redo.py chain --run <метка> [--only sku,sku]   # цепочка на ЦП — под heavy-slot
  ~/venvs/scout/bin/python cutout_redo.py --selftest                              # без сети и базы
"""
import argparse
import base64
import collections
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'salad'))
sys.path.insert(0, os.path.join(HERE, 'render_gpu'))
import mesh_photo as MP        # noqa: E402 — единое правило «какое фото брать»
import product_names as PN     # noqa: E402 — обход карточек демо

ROOT = os.path.expanduser('~/remlab-logs/t104-1119')
DEMO = os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
GROUP = 'mesh-q-mask-canary'
QUEUE = 'mesh-q-mask'
# Первыми в пробе — товары, названные в задании (`--first sku,sku`; ID в коде не держим), затем люстры с тросами (проверка 8-связности T-99) — по роли ниже.
STREAK_MAX = 10              # отказов подряд — стоп (как у `cutout_sync.run_jobs`)
POLL_S = 2.0
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']


def say(*a) -> None:
    print(time.strftime('%H:%M:%S', time.gmtime()), *a, flush=True)


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, capture_output=True, text=True, input=sql)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def q(v) -> str:
    return 'null' if v is None else "'" + str(v).replace("'", "''") + "'"


def run_dir(label: str | None) -> str:
    d = os.path.join(ROOT, label or time.strftime('%Y%m%d-%H%M%S'))
    for sub in ('photos', 'masks', 'cut'):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def jl_append(path: str, rec: dict, lock: threading.Lock) -> None:
    with lock, open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def jl_read(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    return [json.loads(ln) for ln in open(path, encoding='utf-8') if ln.strip()]


# ------------------------------------------------------------------ list

def demo_cards(path: str = DEMO) -> dict:
    """{sku: карточка} — по одной на товар; sku в форме `shop:id` (в данных демо `sid` — через `_`)."""
    data = json.load(open(path, encoding='utf-8'))
    out = {}
    for c in PN.cards(data):
        out.setdefault(PN.key(c['sid']).replace('_', ':', 1), c)
    return out


def assessor_version() -> str:
    """Версия оценщика — из `salad/preprocess.py` разбором текста (импорт тянет torch; здесь он нужен только шагу chain)."""
    import re
    m = re.search(r"^ASSESSOR_VERSION = '([^']+)'", open(os.path.join(HERE, 'salad', 'preprocess.py'), encoding='utf-8').read(), re.M)
    return m.group(1) if m else 'a1'


def build_list(cards: dict) -> list[dict]:
    """Строка на товар /demo: роль, адрес фото и признак «вырезка текущей версии уже есть». Адреса нет → `photo_url: null` (отказ учтём в отчёте)."""
    vals = ','.join(q(s) for s in cards)
    ppc = {r[0]: (r[1], r[2]) for r in db(f"select sku, image_url, source_sha from product_photo_current where sku in ({vals})") if len(r) == 3}
    prod = {r[0]: (r[1], r[2]) for r in db(
        f"select p.shop_mid||':'||p.external_id, p.cat_role, {MP.photo_sql('p')} from products p "
        f"where p.shop_mid||':'||p.external_id in ({vals})") if len(r) == 3}
    room = {r[0]: (r[1], r[2]) for r in db(
        f"select r.shop_mid||':'||r.external_id, r.role, {MP.photo_sql('r')} from room_catalog r "
        f"where r.shop_mid||':'||r.external_id in ({vals})") if len(r) == 3}
    shas = {s for _, s in ppc.values() if s}
    have = set()
    if shas:
        have = {r[0] for r in db("select source_sha from photo_assessment where assessor_version = " + q(assessor_version())
                                 + " and source_sha in (" + ','.join(q(s) for s in shas) + ')')}
    rows = []
    for sku, c in sorted(cards.items()):
        role = (prod.get(sku) or room.get(sku) or ('', ''))[0] or None
        url = (ppc.get(sku) or (None, None))[0] or (prod.get(sku) or room.get(sku) or ('', ''))[1] or None
        sha = (ppc.get(sku) or (None, None))[1]
        rows.append({'sku': sku, 'sid': c.get('sid'), 'role': role, 'name': c.get('name'), 'name_en': c.get('name_en'), 'shop': c.get('shop'),
                     'price': c.get('price'), 'shop_url': c.get('url'), 'demo_img': c.get('img'), 'photo_url': url,
                     'db_sha': sha, 'has_current': bool(sha and sha in have)})
    return rows


def cmd_list(a) -> int:
    d = run_dir(a.run)
    cards = demo_cards()
    rows = build_list(cards)
    json.dump(rows, open(os.path.join(d, 'products.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    no_url = [r['sku'] for r in rows if not r['photo_url']]
    roles = collections.Counter(r['role'] or '—' for r in rows)
    say(f'папка {d}')
    say(f'товаров /demo: {len(rows)} (карточек в данных: {sum(1 for _ in PN.cards(json.load(open(DEMO, encoding="utf-8"))))}), '
        f'с вырезкой текущей версии: {sum(r["has_current"] for r in rows)}, без адреса фото: {len(no_url)}')
    say('роли:', dict(roles.most_common()))
    return 0


# ------------------------------------------------------------------ masks (Salad)

def classify(out: dict | None, raw_sha: str) -> tuple[str, str]:
    """Ответ ноды → ('ok'|'moved'|'fail', причина). Чистая: маска есть и sha совпал — ok; фото подменили — moved; прочее — fail с причиной."""
    if not isinstance(out, dict):
        return 'fail', 'нет ответа воркера'
    st = out.get('status')
    if st != 'mask':
        return 'fail', f'{st}: {str(out.get("error") or "")[:160]}'
    if not out.get('mask_png_b64'):
        return 'fail', 'mask: пустая маска'
    if out.get('sha256') != raw_sha:
        return 'moved', f'фото изменилось (наш sha {raw_sha[:8]}, у ноды {str(out.get("sha256"))[:8]})'
    return 'ok', ''


def cost_usd(paid_s: float, price_h: float) -> float:
    return paid_s / 3600.0 * price_h


def pick_trial(rows: list[dict], n: int, first: tuple = ()) -> list[dict]:
    """Проба: названные в задании товары, затем люстры, затем разные роли по одному — чтобы увидеть и массивное, и тонкое."""
    by = {r['sku']: r for r in rows if r['photo_url']}
    out = [by[s] for s in first if s in by]
    seen = {r['sku'] for r in out}
    for want in ('люстра', 'торшер', 'ковёр', 'стул', 'кровать', 'ваза'):
        for r in rows:
            if len(out) >= n:
                break
            if r['photo_url'] and r['sku'] not in seen and r['role'] == want:
                out.append(r)
                seen.add(r['sku'])
                break
    for r in rows:
        if len(out) >= n:
            break
        if r['photo_url'] and r['sku'] not in seen:
            out.append(r)
            seen.add(r['sku'])
    return out[:n]


def fetch_photo(url: str, tries: int = 3) -> bytes:
    import cutout_sync as CS
    last = None
    for i in range(tries):
        try:
            return CS.fetch(url, 60)
        except Exception as e:  # noqa: BLE001 — повтор, затем отказ с причиной (в счётчик)
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f'скачивание: {type(last).__name__}: {str(last)[:100]}')


def cmd_masks(a) -> int:
    import bench_run as BR
    import migrate_groups as MG
    import queue_run as QR
    import salad_groups as SG
    MG.env_from_file()
    d = run_dir(a.run)
    rows = json.load(open(os.path.join(d, 'products.json'), encoding='utf-8'))
    done = {r['sha'] for r in jl_read(os.path.join(d, 'masks.jsonl')) if r.get('status') == 'ok'}
    todo = pick_trial(rows, a.trial, tuple(x for x in a.first.split(',') if x)) if a.trial else [r for r in rows if r['photo_url']]
    price = SG.price(a.group)
    if not price:
        sys.exit(f'{a.group}: нет цены в rules/salad-groups.json — деньги без цены не считаем')
    lock = threading.Lock()
    mpath = os.path.join(d, 'masks.jsonl')
    stat = collections.Counter()
    reasons = collections.Counter()
    state = {'streak': 0, 'stop': None}

    def one(r: dict) -> None:
        if state['stop']:
            stat['skipped'] += 1
            return
        sku = r['sku']
        try:
            raw = fetch_photo(r['photo_url'])
        except Exception as e:  # noqa: BLE001
            return fail(r, None, f'photo: {e}')
        sha = hashlib.sha256(raw).hexdigest()
        if sha in done or os.path.exists(os.path.join(d, 'masks', sha + '.png')):
            stat['already'] += 1
            return
        open(os.path.join(d, 'photos', sha + '.img'), 'wb').write(raw)
        for attempt in (1, 2):
            qid, why = QR.submit(a.queue, {'sku': sku, 'image_url': r['photo_url'], 'role': r['role']}, {'t': 'T-104', 'sku': sku})
            if not qid:
                reason = f'submit: {why}'
                continue
            out = wait_job(a.queue, qid)
            st, reason = classify(out, sha)
            if st == 'ok':
                open(os.path.join(d, 'masks', sha + '.png'), 'wb').write(base64.b64decode(out['mask_png_b64']))
                with lock:
                    stat['ok'] += 1
                    state['streak'] = 0
                jl_append(mpath, {'sku': sku, 'sha': sha, 'status': 'ok', 'secs': out.get('secs'), 'photo_url': r['photo_url']}, lock)
                return
            if st == 'moved':
                break
        return fail(r, sha, reason)

    def fail(r, sha, reason) -> None:
        with lock:
            stat['fail'] += 1
            reasons[reason.split(':')[0][:40] + ':' + reason.split(':', 1)[-1][:60]] += 1
            state['streak'] += 1
            if state['streak'] >= STREAK_MAX and not state['stop']:
                state['stop'] = f'{STREAK_MAX} отказов подряд — последний: {r["sku"]}: {reason}'
        jl_append(mpath, {'sku': r['sku'], 'sha': sha, 'status': 'fail', 'error': reason, 'photo_url': r['photo_url']}, lock)
        say(f'  ✗ {r["sku"]}: {reason}')

    def wait_job(queue: str, qid: str) -> dict | None:
        t0 = time.time()
        while time.time() - t0 < a.job_max_s:
            code, qj = QR.get(queue, qid)
            if code == 200 and qj.get('status') in ('succeeded', 'failed', 'cancelled'):
                return QR.to_result(qj, {'sku': None})
            time.sleep(POLL_S)
        QR.cancel(queue, qid)
        return {'status': 'transport_failed', 'error': f'queue/timeout {a.job_max_s:.0f} c'}

    say(f'к вырезке масок: {len(todo)} (папка {d}, группа {a.group}, тариф ${price}/ч, потолок ${a.cap})')
    code, g = MG.api(f'/{a.group}')
    st0 = (g.get('current_state') or {}).get('status') if code == 200 else None
    if st0 != 'stopped':
        sys.exit(f'группа {a.group}: статус {st0!r}, нужен stopped (создаётся/уже запущена) — не стартую')
    t_start = time.time()
    code, _ = MG.api(f'/{a.group}/start', 'POST')
    say('start HTTP', code)
    if code >= 300:
        sys.exit(1)
    run_since, paid, stopped_by, ok_stop = None, 0.0, None, False
    pool = ThreadPoolExecutor(max_workers=a.workers)
    futs = []
    try:
        while True:
            t = time.time()
            c, stt, cnt = BR.group_state(a.group)
            ready = QR.ready_by_group([a.group])[a.group]
            _, ins = BR.instances(a.group)
            if any(i.get('state') == 'running' for i in ins) and run_since is None:
                run_since = t
                say(f'первый running: t+{t - t_start:.0f} с от /start')
            if run_since is not None:
                paid = t - run_since
            if stt in ('failed',):
                stopped_by = f'группа в статусе {stt}'
                break
            if ready and not futs:
                say(f'машина готова (ready={ready}) — кладу задания')
                futs = [pool.submit(one, r) for r in todo]
            if futs and all(f.done() for f in futs):
                stopped_by = 'готово'
                break
            if state['stop']:
                stopped_by = state['stop']
                break
            if cost_usd(paid, price) >= a.cap:
                stopped_by = f'потолок денег ${a.cap}'
                break
            if run_since is None and t - t_start > a.ready_max_s:
                stopped_by = f'за {a.ready_max_s / 60:.0f} мин машина не вышла в running (платили 0)'
                break
            if run_since is not None and not ready and t - run_since > a.ready_max_s:
                stopped_by = f'running есть, но ready нет {a.ready_max_s / 60:.0f} мин (прогрев не прошёл) — причина в журнале контейнера'
                break
            if int(t - t_start) % 60 < 10:
                say(f'ход: статус {stt} {cnt}, ready {ready}, ok {stat["ok"]}, отказов {stat["fail"]}, платных минут {paid / 60:.1f} (≈${cost_usd(paid, price):.3f})')
            time.sleep(10)
    finally:
        state['stop'] = state['stop'] or (stopped_by or 'прервано')
        pool.shutdown(wait=True, cancel_futures=True)
        ok_stop = BR.stop_and_verify(a.group)
    summary = {'group': a.group, 'todo': len(todo), 'ok': stat['ok'], 'fail': stat['fail'], 'already': stat['already'], 'skipped': stat['skipped'],
               'reasons': dict(reasons), 'running_s': round(paid, 1), 'price_usd_h': price, 'cost_usd_est': round(cost_usd(paid, price), 3),
               'stopped_by': stopped_by, 'stop_verified': ok_stop, 'to_first_running_s': round(run_since - t_start, 1) if run_since else None}
    json.dump(summary, open(os.path.join(d, f'summary-masks-{time.strftime("%H%M%S")}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    say('ИТОГ', json.dumps(summary, ensure_ascii=False))
    return 0 if ok_stop and not stat['fail'] else 2


# ------------------------------------------------------------------ chain (наш ЦП)

def cmd_chain(a) -> int:
    from PIL import Image
    import cutout_sync as CS
    from photo_fit import verdict_from_metrics
    d = run_dir(a.run)
    rows = json.load(open(os.path.join(d, 'products.json'), encoding='utf-8'))
    only = set(a.only.split(',')) if a.only else None
    ok_masks = {r['sku']: r['sha'] for r in jl_read(os.path.join(d, 'masks.jsonl')) if r.get('status') == 'ok'}
    todo = [r for r in rows if r['sku'] in ok_masks and (not only or r['sku'] in only)]
    lock = threading.Lock()
    cpath = os.path.join(d, 'chain.jsonl')
    stat = collections.Counter()
    say(f'цепочка по сохранённым маскам: {len(todo)} (папка {d}, потоков {a.workers})')

    def one(r: dict) -> None:
        sku, sha = r['sku'], ok_masks[r['sku']]
        try:
            src = Image.open(os.path.join(d, 'photos', sha + '.img')).convert('RGB')
            mask = Image.open(os.path.join(d, 'masks', sha + '.png')).convert('L')
            if mask.size != src.size:
                mask = mask.resize(src.size, Image.LANCZOS)
            net = src.convert('RGBA')
            net.putalpha(mask)
            cut, info = CS.chain(src, net, role=r['role'])
            cut.save(os.path.join(d, 'cut', sha + '.png'))
            verdict, reason = verdict_from_metrics(r['role'], info)[:2]
            rec = {'sku': sku, 'sha': sha, 'status': 'ok', 'verdict': verdict, 'reason': reason, 'cut_wh': list(cut.size), 'frame_wh': list(src.size),
                   'mask_verdict': info.get('verdict'), 'hybrid_error': info.get('hybrid_error')}
            with lock:
                stat['ok'] += 1
        except Exception as e:  # noqa: BLE001 — отказ считаем и пишем с причиной
            rec = {'sku': sku, 'sha': sha, 'status': 'fail', 'error': f'{type(e).__name__}: {str(e)[:160]}'}
            with lock:
                stat['fail'] += 1
            say(f'  ✗ {sku}: {rec["error"]}')
        jl_append(cpath, rec, lock)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, todo))
    say(f'цепочка: готово {stat["ok"]}, отказов {stat["fail"]}')
    return 0 if not stat['fail'] else 2


# ------------------------------------------------------------------ selftest / main

def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    sha = hashlib.sha256(b'x').hexdigest()
    good = {'status': 'mask', 'sha256': sha, 'mask_png_b64': 'AAAA'}
    ok('маска и sha совпали — ok', classify(good, sha)[0] == 'ok')
    ok('sha разошёлся — moved (фото подменили)', classify({**good, 'sha256': 'ff' * 32}, sha)[0] == 'moved')
    ok('input_failed — fail с причиной', classify({'status': 'input_failed', 'error': 'HTTP 404'}, sha) == ('fail', 'input_failed: HTTP 404'))
    ok('пустой ответ и пустая маска — fail', classify(None, sha)[0] == 'fail' and classify({**good, 'mask_png_b64': ''}, sha)[0] == 'fail')
    ok('деньги: 30 мин по $0.10/ч = $0.05', abs(cost_usd(1800, 0.10) - 0.05) < 1e-9)
    rows = [{'sku': s, 'role': r, 'photo_url': 'u'} for s, r in [('a', 'диван'), ('s_komod', 'комод'), ('s_divan', 'диван'),
                                                                 ('l1', 'люстра'), ('l2', 'люстра'), ('t', 'торшер'), ('n', None)]]
    p = pick_trial(rows, 5, ('s_komod', 's_divan'))
    ok('проба: названные первыми, затем люстра и торшер, ровно 5',
       [r['sku'] for r in p][:2] == ['s_komod', 's_divan'] and len(p) == 5 and p[2]['role'] == 'люстра' and p[3]['role'] == 'торшер')
    ok('проба без фото-адреса такие товары пропускает', len(pick_trial([{'sku': 'z', 'role': 'диван', 'photo_url': None}], 3)) == 0)
    print('ИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not bad else f'{bad} провалов')
    return 1 if bad else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('list', 'masks', 'chain'):
        p = sub.add_parser(name)
        p.add_argument('--run', default=None, help='метка папки прогона (по умолчанию — время старта)')
    m = sub.choices['masks']
    m.add_argument('--trial', type=int, default=0, help='проба: N товаров')
    m.add_argument('--first', default='', help='sku через запятую: идут в пробе первыми (названные в задании)')
    m.add_argument('--all', action='store_true')
    m.add_argument('--group', default=GROUP)
    m.add_argument('--queue', default=QUEUE)
    m.add_argument('--cap', type=float, default=3.0, help='потолок денег, $')
    m.add_argument('--workers', type=int, default=4)
    m.add_argument('--job-max-s', type=float, default=900)
    m.add_argument('--ready-max-s', type=float, default=5400, help='сколько ждать running/ready, с (холодная закачка образа — до ~60 мин)')
    c = sub.choices['chain']
    c.add_argument('--only', default=None)
    c.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    if a.cmd == 'masks' and not (a.trial or a.all):
        sys.exit('нужен --trial N или --all')
    return {'list': cmd_list, 'masks': cmd_masks, 'chain': cmd_chain}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
