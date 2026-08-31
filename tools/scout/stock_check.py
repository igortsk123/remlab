#!/usr/bin/env python3
"""ПРОВЕРКА КАРТОЧЕК ТОВАРОВ — обход, наблюдения, гейты, применение (31.08.2026).

Заменяет `linkcheck --probe` и записывающую часть `health.py`. Порядок жёсткий:

  обход → наблюдения в БД (всегда) → гейты магазинов → свёртка → статусы → reconcile наличия

Наблюдение пишется ВСЕГДА, даже отброшенное гейтом: иначе разбор инцидента невозможен, а
отвергнутый вердикт всё равно подхватился бы следующим прогоном (замечание Codex 31.08).

БЮДЖЕТ И ПРИОРИТЕТ. Прежняя проверка брала 400 ссылок/день по кругу в 20 000 — до второго
захода не доживал никто, и порог «два 404 подряд» не срабатывал НИ РАЗУ. Теперь 3500/день:
15% — подтверждения (`suspect` ждёт второго голоса), 20% — товары боевых сетов (их видит
пользователь), 65% — хвост по давности. Снятые товары тоже проверяются, иначе ошибочное
снятие необратимо: `linkcheck` выбирал `where in_stock` и воскресить товар не мог.

ВЕЖЛИВОСТЬ. Один одновременный запрос на домен, пауза 2–5 с с jitter, домены параллельно.
Поток 403/429/капчи → домен замораживается до следующего прогона: массово «снимать» товары
магазина, который просто выставил антибота, — худший из возможных исходов.

  stock_check.py                      # ночной прогон
  stock_check.py --limit 300          # короткий прогон
  stock_check.py --shop divanboss.ru  # только один магазин
  stock_check.py --dry-run            # проверить и показать, ничего не применяя
  stock_check.py --reapply [run_id]   # применить уже собранные наблюдения заново, без запросов
"""
import datetime as dt
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from page_alive import PROBE_VERSION, classify, schema_state, url_key   # noqa: E402
from stock_truth import (CONFIRM_GAP_MIN, audit, db, fold, gate, q,   # noqa: E402
                         reconcile)

REPORT = os.path.join(HERE, 'stock-report.json')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')
MAX_BYTES = 1_200_000          # schema бывает и на 62% страницы (divanboss) — читаем чанками
CHUNK = 65_536
HOST_PAUSE = (2.0, 5.0)        # пауза между запросами к одному домену
BLOCK_STREAK = 5               # подряд «нас не пустили» → домен заморожен до следующего прогона
DEFAULT_LIMIT = 3500
SHARE_CONFIRM, SHARE_SETS = 0.15, 0.20

# Как часто перепроверять — по состоянию. TTL сам по себе НИЧЕГО не снимает: он только решает,
# кого поставить в очередь (устаревший вердикт — повод проверить, а не повод убрать товар).
TTL_HOURS = {'alive': 24 * 7, 'oos': 24 * 3, 'gone': 24 * 3, 'suspect': 1, 'unknown': 6, None: 0}
TTL_SETS_HOURS = 24            # то, что видит пользователь, проверяем ежедневно


# --- сеть -------------------------------------------------------------------------------------
def fetch(url: str):
    """→ (http_code, body, error, final_url). Тело читаем чанками и бросаем, как только нашли
    признак наличия: у divan.ru он на 8% страницы, у tvoydom — на 11% из 4 МБ."""
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'ru-RU,ru;q=0.9'})
    try:
        with urllib.request.urlopen(req, timeout=25) as f:
            body, got = [], 0
            while got < MAX_BYTES:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                body.append(chunk)
                got += len(chunk)
                # Обрываем только по НАСТОЯЩЕМУ признаку наличия. Первая версия останавливалась
                # на слове «availability» в любом месте (оно есть и в JS) и отрезала страницу
                # до самой разметки — живые товары divanboss приезжали как «unknown».
                if len(body) % 4 == 0 and \
                        schema_state(b''.join(body[-8:]).decode('utf-8', 'ignore')):
                    break
            return f.status, b''.join(body).decode('utf-8', 'ignore'), '', f.geturl()
    except urllib.error.HTTPError as e:
        try:
            body = e.read(CHUNK).decode('utf-8', 'ignore')
        except Exception:
            body = ''
        return e.code, body, '', getattr(e, 'url', url)
    except Exception as e:
        return None, '', f'{type(e).__name__}: {e}'[:80], url


# --- выбор кандидатов --------------------------------------------------------------------------
def _sets_skus() -> set:
    """Товары боевых наборов — их видит пользователь, проверяем чаще прочих."""
    out = set()
    for f in ('sets3.json', 'sets2.json', 'sets.json'):
        p = os.path.join(HERE, f)
        if not os.path.exists(p):
            continue
        try:
            for s in json.load(open(p, encoding='utf-8')):
                for it in (s.get('items') or {}).values():
                    if it and it.get('mid'):
                        out.add((int(it['mid']), str(it['eid'])))
        except Exception as e:
            print(f'{f}: не прочитан ({e}) — приоритет сетов без него', flush=True)
    return out


def candidates(limit: int, only_shop: str = '') -> list:
    """Кого проверяем в этот прогон: подтверждения → сеты → хвост по давности.

    Берём и снятые товары (`state in (gone, oos)`): без этого снятие необратимо автоматикой.
    Не берём архивные по фиду — они и так вне продажи, тратить на них запросы незачем.
    """
    rows = db(f"""
    select p.shop_mid, p.external_id, p.shop, coalesce(p.direct_url, p.url),
           coalesce(ps.state, ''), coalesce(to_char(ps.checked_at, 'YYYY-MM-DD HH24:MI:SS'), ''),
           coalesce(ps.url_hash, '')
      from products p
      left join product_enrichment e on e.shop_mid = p.shop_mid and e.external_id = p.external_id
      left join product_page_status ps on ps.shop_mid = p.shop_mid and ps.external_id = p.external_id
     where coalesce(p.direct_url, p.url) <> ''
       and (coalesce(e.status, p.status) = 'active' or coalesce(ps.state, '') in ('gone', 'oos'))
       {f"and p.shop = {q(only_shop)}" if only_shop else ''};
    """)
    sets = _sets_skus()
    now = dt.datetime.now()
    confirm, in_sets, tail = [], [], []
    for mid, eid, shop, url, state, checked, uhash in rows:
        mid = int(mid)
        last = dt.datetime.strptime(checked, '%Y-%m-%d %H:%M:%S') if checked else None
        age_h = (now - last).total_seconds() / 3600 if last else 10 ** 6
        item = (mid, eid, shop, url, state, age_h)
        if state == 'suspect' and age_h >= CONFIRM_GAP_MIN / 60:
            confirm.append(item)                     # ждёт второго голоса — самый ценный запрос
        elif (mid, eid) in sets and age_h >= TTL_SETS_HOURS:
            in_sets.append(item)
        elif age_h >= TTL_HOURS.get(state or None, 6):
            tail.append(item)
    for lst in (confirm, in_sets, tail):
        lst.sort(key=lambda x: -x[5])                # дольше всех не проверялся — первым
    n_conf = min(len(confirm), int(limit * SHARE_CONFIRM))
    n_sets = min(len(in_sets), int(limit * SHARE_SETS))
    picked = confirm[:n_conf] + in_sets[:n_sets]
    picked += tail[:max(0, limit - len(picked))]
    if len(picked) < limit:                          # бюджет не выбран — доливаем из очередей
        rest = confirm[n_conf:] + in_sets[n_sets:]
        picked += rest[:limit - len(picked)]
    print(f'к проверке: {len(picked)} (подтверждений {n_conf}, сеты {n_sets}, '
          f'хвост {len(picked) - n_conf - n_sets}); кандидатов всего {len(rows)}', flush=True)
    return picked


# --- обход ---------------------------------------------------------------------------------------
class Domain:
    """Очередь одного домена: строго последовательно, с паузой и заморозкой при антиботе."""

    def __init__(self, host):
        self.host, self.items, self.blocked_streak, self.frozen = host, [], 0, False


def crawl(picked: list, run_id: str, verbose: bool = True) -> list:
    domains = {}
    for it in picked:
        host = urllib.parse.urlsplit(it[3]).hostname or it[2]
        domains.setdefault(host, Domain(host)).items.append(it)
    obs, lock = [], threading.Lock()

    def work(d: Domain):
        for mid, eid, shop, url, state, _age in d.items:
            if d.frozen:
                break
            code, body, err, final = fetch(url)
            verdict, reason = classify(shop, code, body, err, final, url)
            with lock:
                obs.append({'mid': mid, 'eid': eid, 'shop': shop, 'url': url, 'code': code,
                            'final': final, 'verdict': verdict, 'reason': reason,
                            'url_hash': url_key(url), 'prev': state})
            if verdict == 'unknown' and ('не пустили' in reason or 'антибот' in reason):
                d.blocked_streak += 1
                if d.blocked_streak >= BLOCK_STREAK:
                    d.frozen = True
                    print(f'ДОМЕН ЗАМОРОЖЕН: {d.host} — {BLOCK_STREAK} блокировок подряд, '
                          f'остальные {len(d.items)} проверок отменены', flush=True)
            else:
                d.blocked_streak = 0
            time.sleep(random.uniform(*HOST_PAUSE))

    with ThreadPoolExecutor(max_workers=max(1, len(domains))) as ex:
        list(ex.map(work, domains.values()))
    if verbose:
        per = {}
        for o in obs:
            per[(o['shop'], o['verdict'])] = per.get((o['shop'], o['verdict']), 0) + 1
        for (shop, v), n in sorted(per.items()):
            print(f'  {shop:16s} {v:8s} {n}', flush=True)
    return obs


def save_observations(obs: list, run_id: str) -> None:
    if not obs:
        return
    vals = ','.join(
        f"({o['mid']}, {q(o['eid'])}, {q(o['url_hash'])}, {q(o['url'][:900])}, "
        f"{o['code'] if isinstance(o['code'], int) else 'null'}, {q((o['final'] or '')[:900])}, "
        f"{q(o['verdict'])}, {q(o['reason'])}, {PROBE_VERSION}, {q(run_id)})" for o in obs)
    db('insert into product_page_observation (shop_mid, external_id, url_hash, url, http_code, '
       f'final_url, verdict, reason, probe_version, run_id) values {vals};')


# --- применение -----------------------------------------------------------------------------------
def history_shares(run_id: str) -> dict:
    """Историческая доля отрицательных по магазину (прошлые прогоны) — база для гейта ×3."""
    rows = db(f"""
    select p.shop_mid,
           count(*) filter (where o.verdict in ('gone','oos'))::float / greatest(count(*), 1)
      from product_page_observation o
      join products p on p.shop_mid = o.shop_mid and p.external_id = o.external_id
     where o.run_id <> {q(run_id)} and o.observed_at > now() - interval '30 days'
     group by 1;""")
    return {int(r[0]): float(r[1]) for r in rows if r[0]}


def apply_run(obs: list, run_id: str, dry: bool = False) -> dict:
    """Гейты → свёртка истории → статусы → reconcile. Возвращает отчёт."""
    per_shop = {}
    for o in obs:
        n, neg = per_shop.get(o['mid'], (0, 0))
        per_shop[o['mid']] = (n + 1, neg + (1 if o['verdict'] in ('gone', 'oos') else 0))
    quarantine, why = gate(per_shop, history_shares(run_id))
    for mid in sorted(quarantine):
        print(f'КАРАНТИН магазина mid={mid}: {why[mid]} — вердикты НЕ применяются', flush=True)
    touched = [(o['mid'], o['eid']) for o in obs if o['mid'] not in quarantine]
    changes = {'gone': 0, 'oos': 0, 'alive': 0, 'suspect': 0, 'unknown': 0}
    if touched and not dry:
        keys = ','.join(f"({m}, {q(e)})" for m, e in touched)
        rows = db(f"""
        select o.shop_mid, o.external_id, o.verdict, o.url_hash,
               to_char(o.observed_at, 'YYYY-MM-DD HH24:MI:SS'), coalesce(o.reason, '')
          from product_page_observation o
         where (o.shop_mid, o.external_id) in ({keys})
           and o.observed_at > now() - interval '90 days'
         order by o.shop_mid, o.external_id, o.observed_at;""")
        by_sku = {}
        for mid, eid, verdict, uhash, at, reason in rows:
            by_sku.setdefault((int(mid), eid), []).append(
                (verdict, uhash, dt.datetime.strptime(at, '%Y-%m-%d %H:%M:%S'), reason))
        ups = []
        for (mid, eid), history in by_sku.items():
            state, negs, reason = fold(history)
            changes[state] = changes.get(state, 0) + 1
            dead = "current_date" if state in ('gone', 'oos') else 'null'
            ups.append(f"({mid}, {q(eid)}, {q(state)}, {q(reason)}, {q(history[-1][1])}, {negs}, "
                       f"now(), now(), {dead})")
        for i in range(0, len(ups), 500):
            db('insert into product_page_status (shop_mid, external_id, state, reason, url_hash, '
               'negatives, checked_at, applied_at, dead_since) values '
               + ','.join(ups[i:i + 500]) +
               ' on conflict (shop_mid, external_id) do update set state = excluded.state, '
               'reason = excluded.reason, url_hash = excluded.url_hash, '
               'negatives = excluded.negatives, checked_at = excluded.checked_at, '
               'applied_at = excluded.applied_at, '
               'dead_since = coalesce(product_page_status.dead_since, excluded.dead_since);')
    report = {'run_id': run_id, 'checked': len(obs), 'quarantine': sorted(quarantine),
              'quarantine_why': {str(k): v for k, v in why.items()}, 'states': changes,
              'per_shop': {str(k): {'n': v[0], 'negative': v[1]} for k, v in per_shop.items()},
              'dry_run': dry, 'finished': dt.datetime.now().strftime('%F %T')}
    if not dry:
        report['reconciled'] = reconcile()
        report['audit_mismatch'] = audit()
    json.dump(report, open(REPORT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'OK: {os.path.basename(REPORT)}', flush=True)
    return report


def observations_of_run(run_id: str) -> list:
    """Наблюдения уже выполненного прогона — чтобы применить их повторно, без новых запросов.

    Нужно, когда прогон ушёл в карантин (или сменились пороги): 986 обходов магазина — это час
    работы и час чужого трафика, выбрасывать их из-за одной настройки неправильно.
    """
    rows = db(f"""
    select o.shop_mid, o.external_id, p.shop, o.url, coalesce(o.http_code::text, ''),
           coalesce(o.final_url, ''), o.verdict, coalesce(o.reason, ''), o.url_hash
      from product_page_observation o
      join products p on p.shop_mid = o.shop_mid and p.external_id = o.external_id
     where o.run_id = {q(run_id)};""")
    return [{'mid': int(r[0]), 'eid': r[1], 'shop': r[2], 'url': r[3],
             'code': int(r[4]) if r[4].isdigit() else None, 'final': r[5], 'verdict': r[6],
             'reason': r[7], 'url_hash': r[8], 'prev': ''} for r in rows]


def last_run_id() -> str:
    rows = db('select run_id from product_page_observation order by observed_at desc limit 1;')
    return rows[0][0] if rows else ''


def alert(text: str) -> None:
    sh = os.path.join(HERE, 'alert.sh')
    if os.path.exists(sh):
        os.system(f'bash {sh} "{text}" || true')


def main() -> int:
    if '--reapply' in sys.argv:
        i = sys.argv.index('--reapply')
        run = sys.argv[i + 1] if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith('-') \
            else last_run_id()
        obs = observations_of_run(run)
        if not obs:
            print(f'нет наблюдений прогона {run!r}')
            return 1
        print(f'повторное применение прогона {run}: наблюдений {len(obs)}', flush=True)
        rep = apply_run(obs, run, '--dry-run' in sys.argv)
        return 1 if rep.get('audit_mismatch', 0) else 0
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else DEFAULT_LIMIT
    only = sys.argv[sys.argv.index('--shop') + 1] if '--shop' in sys.argv else ''
    dry = '--dry-run' in sys.argv
    wait = int(sys.argv[sys.argv.index('--confirm-wait') + 1]) if '--confirm-wait' in sys.argv \
        else CONFIRM_GAP_MIN * 60
    db(open(os.path.join(HERE, '003-stock-truth.sql'), encoding='utf-8').read())
    run_id = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    picked = candidates(limit, only)
    if not picked:
        print('проверять нечего')
        return 0
    obs = crawl(picked, run_id)
    save_observations(obs, run_id)
    report = apply_run(obs, run_id, dry)

    # ВТОРОЙ ГОЛОС В ТОМ ЖЕ ПРОГОНЕ. Иначе подтверждение приедет только завтра, и товар,
    # которого нет, ещё сутки будет числиться в продаже. Ждём разрыв и добираем свежих suspect.
    fresh = [o for o in obs if o['verdict'] in ('gone', 'oos') and o['mid'] not in report['quarantine']]
    if fresh and wait > 0 and not dry:
        print(f'подтверждение: пауза {wait} с, затем повтор {len(fresh)} отрицательных', flush=True)
        time.sleep(wait)
        run2 = run_id + '-confirm'
        picked2 = [(o['mid'], o['eid'], o['shop'], o['url'], 'suspect', 99) for o in fresh]
        obs2 = crawl(picked2, run2)
        save_observations(obs2, run2)
        report = apply_run(obs2, run2, dry)

    bad = report.get('audit_mismatch', 0)
    if bad:
        alert(f'remlab: сторож наличия — {bad} расхождений с формулой после stock_check')
    if report['quarantine']:
        alert(f'remlab: stock_check — магазины в карантине {report["quarantine"]} '
              f'(всплеск отрицательных, вердикты не применены)')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
