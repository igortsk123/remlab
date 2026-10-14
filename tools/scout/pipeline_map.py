#!/usr/bin/env python3
"""Стыки конвейера — числа, пороги и тревоги (план conv-06, ADR-0272).

ЗАЧЕМ. Поломки 11–12.10 прятались при зелёных тестах: шаги отрабатывали, а смысл терялся на стыках (роль, стиль,
размеры, фото). Здесь у каждого стыка — число сегодня и в прошлом успешном прогоне, порог жёлтый/красный, владелец
и что делать (`rules/pipeline-map.json`). Метрики считаются ТОЛЬКО здесь (одна истина; SQL не живёт в JSON).

ШУМ. Тревога (`WARN:` → дайджест) только при смене состояния: OK→жёлтый/красный, ухудшении, истечении срока
отсрочки и восстановлении; повтор — жёлтый раз в 72 ч, красный раз в 24 ч (Codex 14.10). Состояние — вне git
(`~/scout-scenes/pipeline-state.json`), история — `~/scout-scenes/pipeline-history.jsonl`. Отсрочка (`waiver`
в карте: причина и срок) глушит известный стык до даты.

  ~/venvs/scout/bin/python pipeline_map.py            # посчитать, сравнить, тревоги, страница
  ~/venvs/scout/bin/python pipeline_map.py --publish  # …и выложить /test/pipeline/
  python3 pipeline_map.py --selftest                  # фикстуры: сломанный стык даёт красный
"""
import html
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
MAP = os.path.join(HERE, 'rules', 'pipeline-map.json')
STATE = os.path.expanduser(os.environ.get('PIPELINE_STATE', '~/scout-scenes/pipeline-state.json'))
HISTORY = os.path.expanduser(os.environ.get('PIPELINE_HISTORY', '~/scout-scenes/pipeline-history.jsonl'))
PAGE = os.path.join(HERE, 'pipeline-page', 'index.html')
LEVEL = {'ok': 0, 'unknown': 0, 'info': 0, 'yellow': 1, 'red': 2}


def _sql(q: str) -> str:
    if os.environ.get('PIPELINE_DB_GUARD') == 'test':
        raise SystemExit('тестовый режим: к боевой дев-базе не ходим')
    r = subprocess.run(['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-qtA', '-c', q],
                       capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:200])
    return r.stdout.strip()


def _n(q: str) -> float:
    v = _sql(q)
    return float(v) if v not in ('', None) else 0.0


def collect() -> dict:
    """Метрики стыков на сейчас. Единственное место, где они считаются."""
    m: dict = {}
    m['catalog_active'] = _n("select count(*) from products where status='active'")
    m['in_stock'] = ins = _n('select count(*) from products where in_stock')
    m['photo_share'] = _n("select count(*) from products where in_stock and coalesce(image_url_hd,image_url) is not null "
                          "and coalesce(photo_alive,true)") / ins if ins else 0
    m['role_share'] = _n('select count(*) from lr_roles l join products p using (shop_mid, external_id) '
                         'where l.role is not null and p.in_stock') / ins if ins else 0
    m['dims_share'] = _n('select count(*) from products where in_stock and w_cm is not null and d_cm is not null '
                         'and h_cm is not null') / ins if ins else 0
    m['enrich_backlog'] = _n('select count(*) from products p left join product_enrichment e using (shop_mid, external_id) '
                             'where p.in_stock and e.shop_mid is null')
    m['style_backlog'] = _n('select count(*) from products p left join product_style_scores s using (shop_mid, external_id) '
                            'where p.in_stock and s.shop_mid is null')
    m['mesh_ready'] = ready = _n("select count(*) from products where in_stock and mesh_status='ready'")
    stale = _n("select count(*) from products where in_stock and mesh_status='stale'")
    m['stale_share'] = stale / (ready + stale) if ready + stale else 0
    m['queue_oldest_hours'] = _n("select coalesce(extract(epoch from now()-min(created))/3600, 0) from mesh_jobs "
                                 "where status='queued'")
    m['dead_photo_queued'] = _n("select count(*) from mesh_jobs j join products p on p.shop_mid::text||':'||p.external_id = j.sku "
                                "where j.status='queued' and p.photo_alive = false")
    try:
        m['sets_count'] = float(len(json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8'))))
    except Exception:  # noqa: BLE001 — нет файла: метрика неизвестна
        m['sets_count'] = None
    demo = os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
    try:
        d = json.load(open(demo, encoding='utf-8'))
        m['demo_variants'] = float(len(d.get('variants') or []))
    except Exception:  # noqa: BLE001
        m['demo_variants'] = None
    m['swap_below_floor'], m['swap_hungry'] = _swap_stats()
    # карантин моделей (ADR-0276): ждут решения владельца; цены «по странице», у которых страница устарела (ADR-0260)
    m['quarantine_open'] = _n("select count(*) from mesh_quarantine where decision is null")
    m['price_stale'] = _n("select count(*) from products where in_stock and price_basis = 'feed-stale'")
    m['mesh_unpublished'], m['orient_missing'] = _publish_stats()
    return m


def _publish_stats() -> tuple[float | None, float | None]:
    """Стык «публикация» (conv-06): готовые меши комплектов, которых нет в индексе прода; опубликованные модели без
    записи разворота на проде (3D и демо ставят их «как получится», 14.10: 551 из 745). Ключи — как у `mesh_publish`."""
    try:
        import urllib.request
        import mesh_publish as MP
        idx = json.load(urllib.request.urlopen(MP.PROD_IDX, timeout=30))
        ori = json.load(urllib.request.urlopen(MP.PROD_IDX.replace('mesh-index.json', 'orient.json'), timeout=30))
        want = {k.replace(':', '_') for k in MP.ready_skus()}
        return float(len(want - set(idx))), float(sum(1 for k in idx if k not in ori))
    except Exception:  # noqa: BLE001 — нет сети/базы: метрика неизвестна, а не ноль
        return None, None


def _swap_stats() -> tuple[float | None, float | None]:
    """Через расчёт ленты из tests_chain (одна реализация): товаров ниже порога стиля; голодающих пар ядра."""
    try:
        import tests_chain as TC
        x = TC.swap_feed_stats()
        return float(len(x['low'])), float(len(x['hungry']))
    except Exception:  # noqa: BLE001 — нет демо/базы: метрика неизвестна
        return None, None


def level(stage: dict, cur: float | None, prev: float | None) -> str:
    """Уровень стыка: ok / yellow / red / unknown / info. Чистая функция — проверяется фикстурами."""
    k = stage['kind']
    if k == 'info':
        return 'info'
    if cur is None:
        return 'unknown'
    if k == 'zero':
        return 'ok' if cur == 0 else 'red'
    if k == 'share':
        return 'red' if cur < stage['red'] else ('yellow' if cur < stage['yellow'] else 'ok')
    if k in ('backlog', 'max_share'):
        return 'red' if cur > stage['red'] else ('yellow' if cur > stage['yellow'] else 'ok')
    if k == 'drop':
        if prev is None or prev <= 0:
            return 'unknown'                                # первый день — сравнивать не с чем, не «зелёный»
        drop = (prev - cur) / prev
        return 'red' if drop > stage['red'] else ('yellow' if drop > stage['yellow'] else 'ok')
    return 'unknown'


def alerts(stages: list, levels: dict, values: dict, prev_state: dict, now: float, remind: dict,
           waivers: dict | None = None) -> tuple[list[str], dict]:
    """Какие тревоги отправить и новое состояние. Только переходы, ухудшения, напоминания по сроку и восстановление."""
    out, state = [], {}
    for st in stages:
        sid, lv = st['id'], levels[st['id']]
        old = prev_state.get(sid) or {}
        olv = old.get('level', 'ok')
        w = (waivers or {}).get(sid)
        waived = bool(w and w.get('expires', '') > datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%d'))
        rec = {'level': lv, 'since': old.get('since', now) if olv == lv else now, 'notified': old.get('notified', 0)}
        bad = LEVEL.get(lv, 0) > 0
        msg = None
        if bad and not waived:
            if LEVEL[lv] > LEVEL.get(olv, 0):
                msg = 'стал ' + ('КРАСНЫМ' if lv == 'red' else 'жёлтым')
            elif now - rec['notified'] >= remind['red' if lv == 'red' else 'yellow'] * 3600:
                msg = 'всё ещё ' + ('красный' if lv == 'red' else 'жёлтый')
        elif not bad and LEVEL.get(olv, 0) > 0:
            msg = 'восстановился'
        if msg:
            rec['notified'] = now
            v = values.get(st['metric'])
            vs = '—' if v is None else (f'{v:.1%}' if st['kind'] in ('share', 'max_share', 'info') and v <= 1 else f'{v:,.0f}'.replace(',', ' '))
            out.append(f"{'WARN:pipe_' + sid if bad else 'OK:pipe_' + sid}: {st['title']} — {msg}: {vs}"
                       + (f" · что делать: {st['runbook']}" if bad else ''))
        state[sid] = rec
    return out, state


def _prev_values(now: float, max_age_h: float) -> dict:
    if not os.path.exists(HISTORY):
        return {}
    last = None
    for ln in open(HISTORY, encoding='utf-8'):
        try:
            j = json.loads(ln)
        except ValueError:
            continue
        if now - j['ts'] <= max_age_h * 3600 and now - j['ts'] > 3600:
            last = j
    return (last or {}).get('values', {})


def page(stages: list, values: dict, prev: dict, levels: dict) -> str:
    color = {'ok': '#2e7d32', 'yellow': '#b8860b', 'red': '#c62828', 'unknown': '#777', 'info': '#555'}
    word = {'ok': 'норма', 'yellow': 'внимание', 'red': 'сломано', 'unknown': 'нет прошлого', 'info': 'справочно'}

    def fmt(st: dict, v: float | None) -> str:
        if v is None:
            return '—'
        return f'{v:.1%}' if st['kind'] in ('share', 'max_share', 'info') and v <= 1 else f'{v:,.0f}'.replace(',', ' ')
    rows = ''.join(
        f"<tr><td>{html.escape(st['title'])}</td><td>{fmt(st, values.get(st['metric']))}</td>"
        f"<td>{fmt(st, prev.get(st['metric']))}</td><td style='color:{color[levels[st['id']]]}'>"
        f"{word[levels[st['id']]]}</td><td class=m>{html.escape(st.get('runbook', ''))}</td></tr>" for st in stages)
    ts = datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M UTC')
    return ('<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'
            '<title>Стыки конвейера</title><style>body{font:15px system-ui;margin:16px;background:#faf8f5}'
            'table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #e5ded6;text-align:left}'
            '.m{color:#777;font-size:13px}</style>'
            f'<h1>Стыки конвейера</h1><p class=m>{ts}. Сегодня / прошлый успешный прогон (не старше 36 ч) / состояние.</p>'
            f'<table><tr><th>Стык</th><th>Сегодня</th><th>Прошлый</th><th>Состояние</th><th>Что делать</th></tr>{rows}</table>')


def main() -> int:
    cfg = json.load(open(MAP, encoding='utf-8'))
    now = time.time()
    values = collect()
    prev = _prev_values(now, cfg['baseline_max_age_hours'])
    levels = {st['id']: level(st, values.get(st['metric']), prev.get(st['metric'])) for st in cfg['stages']}
    old = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}
    msgs, state = alerts(cfg['stages'], levels, values, old, now, cfg['remind_hours'], cfg.get('waivers'))
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(state, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False)
    with open(HISTORY, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': now, 'values': values}, ensure_ascii=False) + '\n')
    for st in cfg['stages']:
        v = values.get(st['metric'])
        print(f"  {levels[st['id']]:8} {st['title']}: {v if v is None else round(v, 4)}")
    for m in msgs:
        print(m)
    os.makedirs(os.path.dirname(PAGE), exist_ok=True)
    open(PAGE, 'w', encoding='utf-8').write(page(cfg['stages'], values, prev, levels))
    if '--publish' in sys.argv:
        subprocess.run(['bash', '-c', 'ssh -p 22222 root@89.167.127.0 "mkdir -p /opt/remlab/test/pipeline" && '
                        f'scp -q -P 22222 "{PAGE}" root@89.167.127.0:/opt/remlab/test/pipeline/index.html'], check=False, timeout=120)
        print('страница: https://remont-lab.online/test/pipeline/')
    return 0


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    cfg = json.load(open(MAP, encoding='utf-8'))
    st = {s['id']: s for s in cfg['stages']}
    ok('у каждого стыка есть метрика, вид и что делать', all(s.get('metric') and s.get('kind') and s.get('runbook') for s in cfg['stages']))
    ok('доля роли 99.7 % — норма, 99.2 % — жёлтый, 0 % — красный (сломанный стык)',
       [level(st['role'], v, None) for v in (0.997, 0.992, 0.0)] == ['ok', 'yellow', 'red'])
    ok('падение каталога на 1 % — норма, 3 % — жёлтый, 6 % — красный',
       [level(st['catalog_active'], c, 100) for c in (99, 97, 94)] == ['ok', 'yellow', 'red'])
    ok('первый день без истории — «нет прошлого», не зелёный', level(st['catalog_active'], 100, None) == 'unknown')
    ok('мёртвое фото в очереди: 0 — норма, 1 — красный', [level(st['dead_photo_in_queue'], v, None) for v in (0, 1)] == ['ok', 'red'])
    # шум: тревога только при смене; напоминание по сроку; восстановление
    stages = [st['role']]
    m1, s1 = alerts(stages, {'role': 'red'}, {'role_share': 0.0}, {}, 1000.0, cfg['remind_hours'])
    m2, s2 = alerts(stages, {'role': 'red'}, {'role_share': 0.0}, s1, 1000.0 + 3600, cfg['remind_hours'])
    m3, s3 = alerts(stages, {'role': 'red'}, {'role_share': 0.0}, s2, 1000.0 + 25 * 3600, cfg['remind_hours'])
    m4, _ = alerts(stages, {'role': 'ok'}, {'role_share': 0.998}, s3, 1000.0 + 26 * 3600, cfg['remind_hours'])
    ok('сломанный стык: тревога сразу, через час — тишина, через сутки — напоминание, починили — «восстановился»',
       len(m1) == 1 and 'КРАСНЫМ' in m1[0] and m1[0].startswith('WARN:pipe_role') and not m2 and len(m3) == 1
       and len(m4) == 1 and 'восстановился' in m4[0])
    m5, _ = alerts(stages, {'role': 'red'}, {'role_share': 0.0}, {}, 1000.0, cfg['remind_hours'],
                   {'role': {'reason': 'известно', 'expires': '2999-01-01'}})
    ok('отсрочка с причиной и сроком глушит тревогу', not m5)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else main())
