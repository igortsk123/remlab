#!/usr/bin/env python3
"""ПРОВЕРКА КАРТОЧЕК ТОВАРОВ — обход, наблюдения, гейты, применение (31.08.2026).

Заменяет `linkcheck --probe` и записывающую часть `health.py`. Порядок жёсткий:

  обход → наблюдения в БД (всегда) → гейты магазинов → свёртка → статусы → reconcile наличия

Наблюдение пишется ВСЕГДА, даже отброшенное гейтом: иначе разбор инцидента невозможен, а
отвергнутый вердикт всё равно подхватился бы следующим прогоном (замечание Codex 31.08).

БЮДЖЕТ И ПРИОРИТЕТ. Прежняя проверка брала 400 ссылок/день по кругу в 20 000 — до второго
захода не доживал никто. Теперь 3500/день, три очереди по убыванию ценности запроса:
до 15% — ПЕРЕПРОВЕРКА СВЕЖЕСНЯТЫХ (не ошиблись ли мы вчера; берётся ДО деления бюджета по
магазинам, иначе квота режет приоритет вместе с хвостом), затем товары боевых сетов с истёкшим
TTL, затем хвост по давности. Снятые товары с живым фидом проверяются и дальше, иначе ошибочное
снятие стало бы необратимым: `linkcheck` выбирал `where in_stock` и воскресить товар не мог.

СНИМАЕМ С ПЕРВОГО ОТКАЗА (ADR-0148). Прохода подтверждения больше нет: он стоил паузы 900 с и
повторного обхода всех отрицательных, а из 347 повторов 347 подтвердили первый ответ и ни один
не отменил. Владелец принял риск («один товар из 1000 — нормально»). Взамен цена ошибки
ограничена скоростью возврата: свежеснятый перепроверяется через 6 часов и «в продаже»
возвращает его немедленно. Шесть часов переживают выкатку магазина и жизнь ошибки в кэше CDN,
чего 15-минутный повтор не переживал. Для ручного разбора инцидента остался `--confirm-wait`.

ОДНО ПРАВИЛО ДЛЯ ВСЕХ — РАЗ В НЕДЕЛЮ (ADR-0147, 01.09). Утром 01.09 у витрины был отдельный
суточный TTL («определять каждый день»), но выяснилось, чем именно владелец был недоволен:
товар висел в продаже БОЛЬШЕ НЕДЕЛИ, а не «лишние сутки». Граница приемлемого — неделя, и
двухскоростная схема оказалась лишней работой по чужим серверам. Арифметика сходится: активных
19 999, из них 1095 у магазинов с антиботом (проверить нельзя), остаётся 18 989 → недельный
круг = 2713 проверок в сутки при бюджете 3500, влезает с запасом.

ПРИОРИТЕТ ВИТРИНЫ — В ОЧЕРЕДИ, А НЕ В ЧАСТОТЕ. Товары сетов остаются отдельным блоком перед
хвостом и берутся БЕЗ ПОТОЛКА (доля 20% = 700 против 736 позиций банка отрезала каждую ночь
десятки случайных позиций). Но TTL у них теперь общий, недельный: когда неделя истекла — идут
первыми и не вытесняются хвостом при делении бюджета по магазинам, а раньше срока не ходят
никуда. Гарантия «витрина проверена не позже семи дней» держится очередью, а не частотой.

МАГАЗИН НАС НЕ ПУСКАЕТ → ВЕРИМ ГДЕСЛОНУ (решение владельца 01.09; ADR-0147). Вердикт `unknown`
не снимает и не возвращает товар. Замер 03.09 (план stock-and-dims-honesty, Н1): реальный антибот —
только mdm-complect (Яндекс SmartCaptcha, 307 → `?_ycch=`); gipfel отдаёт 200 с разметкой в `href=`,
которую прежняя регулярка не читала. Антибот-домен объявляется явно: `probe_domain_status.policy=
'disabled'` — карточки не запрашиваются, квота уходит другим; раз в неделю 5 пробных карточек.

ЗАЩИТА ОТ ЛОЖНОГО СНЯТИЯ (Н1, Codex 03.09). (1) ЯКОРЬ ДОМЕНА перед обходом: главная + до 3 недавно
живых карточек; якорь мёртв/заблокирован → домен `blocked` на сутки, ни один товар магазина в этом
прогоне не снимается. (2) КАРАНТИН ОКОНЧАТЕЛЕН: наблюдения карантинного прогона получают
`disposition='quarantined'` и в свёртку/историю больше не попадают (раньше всплывали через 90-дневную
историю). (3) Гейт считает долю по РЕШАЮЩИМ ответам (alive/oos/gone) с абсолютным пределом при малой
выборке. (4) История и свёртка — только текущая версия пробника (свидетельство 404 версии не имеет).
(5) КАНАРЕЙКА (`stock_canary`) при доле отрицательных > 30 % — гейт перед применением.

ВЕЖЛИВОСТЬ. Один одновременный запрос на домен, пауза 2–5 с с jitter, домены параллельно; gzip.

  stock_check.py                      # ночной прогон
  stock_check.py --limit 300          # короткий прогон
  stock_check.py --shop divanboss.ru  # только один магазин
  stock_check.py --dry-run            # проверить и показать, ничего не применяя
  stock_check.py --reapply [run_id]   # применить уже собранные наблюдения заново, без запросов
  stock_check.py --max-minutes 90     # ограничить время обхода (по умолчанию 150)
  STOCK_PARSER_V2=1 stock_check.py --shadow --shop tvoydom.ru [--alive 300 --unknown 300 --neg 100]
                                      # ТЕНЬ (Н0): парсер v2 пишет наблюдения disposition='shadow',
                                      # ничего не применяет; отчёт — stock_shadow_report.py
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
import zlib
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from page_alive import PARSER_V2, PROBE_VERSION, classify_full, extract_page_facts, schema_state, url_key   # noqa: E402
from stock_truth import (CONFIRM_GAP_MIN, audit, db, fold, gate, q,   # noqa: E402
                         reconcile)
import stock_canary   # noqa: E402 — канарейка адреса как гейт перед применением

REPORT = os.path.join(HERE, 'stock-report.json')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')
MAX_BYTES = 2_500_000 if PARSER_V2 else 1_200_000   # v2: inline-остаток tvoydom лежит глубже 1,2 МБ (страница 4,2 МБ, gzip)
CHUNK = 65_536
HOST_PAUSE = (2.0, 5.0)        # пауза между запросами к одному домену
BLOCK_STREAK = 5               # подряд «нас не пустили» → домен заморожен до следующего прогона
DEFAULT_LIMIT = 3500
DEFAULT_MAX_MINUTES = 150      # потолок времени обхода; остаток уезжает в следующий прогон
SHARE_CONFIRM = 0.15           # доля бюджета под подтверждения; товары сетов идут без доли

# Как часто перепроверять — по состоянию. TTL сам по себе НИЧЕГО не снимает: он только решает,
# кого поставить в очередь (устаревший вердикт — повод проверить, а не повод убрать товар).
# ОДИН ГОРИЗОНТ — НЕДЕЛЯ (ADR-0147): и живые, и снятые, и непроверяемые. Разные сроки у разных
# состояний означали бы, что мы ходим к магазину чаще, чем решил владелец, — при том что
# ускорение ничего не давало: снятый товар воскресает не быстрее живого, а к антибот-магазину
# лишний заход просто множит 403. Исключение ровно одно и оно не про периодичность:
# `suspect` ждёт ВТОРОГО ГОЛОСА, и час здесь — не «как часто проверяем», а «через сколько
# считаем второе наблюдение независимым» (сам разрыв задаёт CONFIRM_GAP_MIN).
WEEK_HOURS = 24 * 7
TTL_HOURS = {'alive': WEEK_HOURS, 'oos': WEEK_HOURS, 'gone': WEEK_HOURS,
             'unknown': WEEK_HOURS, None: 0}
ANCHOR_CARDS = 3               # недавно живых карточек в якоре домена (плюс главная)
DOMAIN_BLOCK_HOURS = 24        # на сколько замораживается домен по якорю/серии блокировок
DISABLED_PROBE_DAYS = 7        # выключенный (антибот) домен пробуем 5 карточками раз в неделю
DISABLED_PROBE_N = 5
CANARY_SHARE = 0.30            # доля отрицательных среди решающих, с которой зовём канарейку
TTL_SETS_HOURS = WEEK_HOURS    # витрина живёт по общему правилу; её преимущество — место
                               # в очереди (блок `in_sets` идёт перед хвостом), а не частота
# БЫСТРОЕ ВОСКРЕШЕНИЕ (ADR-0148). Снимаем теперь с первого отказа, поэтому цена ошибки должна
# быть ограничена не задержкой снятия, а скоростью возврата: свежеснятого перепроверяем через
# 6 часов, и «в продаже» возвращает его немедленно. Отличить ошибку от настоящей смерти заранее
# нельзя, поэтому перепроверяются ВСЕ снятые за сутки, а не «подозрительные». Шесть часов
# выбраны потому, что этот интервал переживает выкатку магазина и срок жизни кэша ошибки в CDN,
# которые 15-минутный повтор не переживал. После первых суток товар уходит на недельный круг.
TTL_GONE_FRESH_HOURS = 6
GONE_FRESH_DAYS = 1            # сколько суток после смерти действует ускоренная перепроверка


# --- сеть -------------------------------------------------------------------------------------
def _gunzip_stream():
    """Потоковый распаковщик gzip/deflate с лимитом распакованных байтов (Codex: urllib сам не даёт
    безопасного контракта — распаковываем сами и режем по MAX_BYTES)."""
    return zlib.decompressobj(16 + zlib.MAX_WBITS)


def fetch(url: str):
    """→ (http_code, body, error, final_url). Тело читаем чанками и бросаем, как только нашли
    признак наличия: у divan.ru он на 8% страницы, у tvoydom — на 11% из 4 МБ. Сжатие просим
    явно (`Accept-Encoding: gzip`): страницы tvoydom 4,3 МБ без него съедали дедлайн прогона."""
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Encoding': 'gzip',
        'Accept-Language': 'ru-RU,ru;q=0.9'})
    try:
        with urllib.request.urlopen(req, timeout=25) as f:
            gz = 'gzip' in (f.headers.get('Content-Encoding') or '').lower()
            dec = _gunzip_stream() if gz else None
            body, got = [], 0
            while got < MAX_BYTES:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                if dec is not None:
                    chunk = dec.decompress(chunk, max(0, MAX_BYTES - got) or 1)
                    if not chunk:
                        continue
                body.append(chunk)
                got += len(chunk)
                # Обрываем только по ПОЛОЖИТЕЛЬНОМУ признаку наличия — и это принципиально
                # (ADR-0148): распроданный аксессуар, чья разметка лежит выше по странице, не должен
                # останавливать чтение до «InStock» самого товара.
                if len(body) % 4 == 0 and \
                        schema_state(b''.join(body[-8:]).decode('utf-8', 'ignore')) == 'positive':
                    break
            return f.status, b''.join(body).decode('utf-8', 'ignore'), '', f.geturl()
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(CHUNK * 2)      # WAF-заглушка бывает длиннее одного чанка (Д5)
            if 'gzip' in (e.headers.get('Content-Encoding') or '').lower():
                raw = _gunzip_stream().decompress(raw, CHUNK * 2)
            body = raw.decode('utf-8', 'ignore')
        except Exception:
            body = ''
        return e.code, body, '', getattr(e, 'url', url)
    except Exception as e:
        return None, '', f'{type(e).__name__}: {e}'[:80], url


# --- здоровье доменов --------------------------------------------------------------------------
def domain_status() -> dict:
    """host → {policy, state, blocked_until, last_probe_at}."""
    rows = db("select host, policy, state, coalesce(to_char(blocked_until,'YYYY-MM-DD HH24:MI:SS'),''), "
              "coalesce(to_char(last_probe_at,'YYYY-MM-DD HH24:MI:SS'),'') from probe_domain_status;")
    out = {}
    for h, pol, st, bu, lp in rows:
        out[h] = {'policy': pol, 'state': st,
                  'blocked_until': dt.datetime.strptime(bu, '%Y-%m-%d %H:%M:%S') if bu else None,
                  'last_probe_at': dt.datetime.strptime(lp, '%Y-%m-%d %H:%M:%S') if lp else None}
    return out


def host_of(url: str, shop: str) -> str:
    return ((urllib.parse.urlsplit(url).hostname or shop or '').lower().replace('www.', ''))


def domain_unavailable(info: dict | None, now: dt.datetime) -> bool:
    """Домен нельзя дёргать: выключен владельцем/антиботом или заморожен до срока."""
    if not info:
        return False
    if info['policy'] == 'disabled':
        return True
    return info['state'] == 'blocked' and info['blocked_until'] is not None and info['blocked_until'] > now


def set_domain(host: str, state: str, reason: str, block_hours: float | None = None,
               policy: str | None = None, probed: bool = False) -> None:
    host = (host or '').lower().replace('www.', '')
    bu = f"now() + interval '{block_hours} hours'" if block_hours else 'null'
    db(f"""insert into probe_domain_status (host, probe_version, policy, state, blocked_until, reason, checked_at, last_probe_at)
           values ({q(host)}, {PROBE_VERSION}, {q(policy or 'auto')}, {q(state)}, {bu}, {q(reason[:200])}, now(),
                   {'now()' if probed else 'null'})
           on conflict (host) do update set probe_version = excluded.probe_version,
             policy = {q(policy) if policy else 'probe_domain_status.policy'},
             state = excluded.state, blocked_until = excluded.blocked_until, reason = excluded.reason,
             checked_at = now(),
             last_probe_at = {'now()' if probed else 'probe_domain_status.last_probe_at'};""")


def anchor_verdict(home_ok: bool, card_results: list) -> tuple[bool, str]:
    """Кворум якоря: главная отвечает И среди якорных карточек есть решающий ответ, и не все они
    «страницы нет» (все 404 у недавно живых = сломан маршрут карточек, а не ассортимент).
    card_results: список (verdict, failure_kind)."""
    if not home_ok:
        return False, 'главная не отвечает или заблокирована'
    if not card_results:
        return True, 'якорных карточек нет — судим по главной'
    decisive = [v for v, _ in card_results if v in ('alive', 'oos', 'gone')]
    blocked = [k for _, k in card_results if k in ('challenge', 'rate_limit')]
    if len(blocked) * 2 >= len(card_results):
        return False, f'якорные карточки заблокированы {len(blocked)}/{len(card_results)}'
    if not decisive:
        return False, f'якорные карточки без решающего ответа ({len(card_results)})'
    if all(v == 'gone' for v in decisive) and len(decisive) >= 2:
        return False, f'все якорные карточки ({len(decisive)}) отдают «страницы нет» — маршрут карточек сломан'
    return True, 'ок'


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
    # НЕ ТРАТИМ ЗАПРОСЫ НА ТЕХ, КТО МЁРТВ И ПО ФИДУ (01.09). Прежнее условие добирало снятых
    # карточкой ДАЖЕ когда фид уже отдал их как archived, а программа партнёрки — как retired:
    # такой товар не вернётся в продажу, пока не вернётся в фид, и еженедельный стук по его
    # карточке ничего не решает. Снятые с ЖИВЫМ фидом по-прежнему проверяются (первая ветка
    # их и берёт) — иначе ошибочное снятие стало бы необратимым.
    rows = db(f"""
    select p.shop_mid, p.external_id, p.shop, coalesce(p.direct_url, p.url),
           coalesce(ps.state, ''), coalesce(to_char(ps.checked_at, 'YYYY-MM-DD HH24:MI:SS'), ''),
           coalesce(ps.url_hash, ''),
           coalesce(to_char(ps.dead_since, 'YYYY-MM-DD'), '')
      from products p
      left join product_enrichment e on e.shop_mid = p.shop_mid and e.external_id = p.external_id
      left join product_page_status ps on ps.shop_mid = p.shop_mid and ps.external_id = p.external_id
      left join shop_status s on s.shop_mid = p.shop_mid
     where coalesce(p.direct_url, p.url) <> ''
       and coalesce(e.status, p.status) = 'active'
       and coalesce(s.program_state, 'active') <> 'retired'
       {f"and p.shop = {q(only_shop)}" if only_shop else ''};
    """)
    sets = _sets_skus()
    now = dt.datetime.now()
    dstat = domain_status()
    confirm, in_sets, tail, probe = [], [], [], []
    probe_left = {}
    for mid, eid, shop, url, state, checked, uhash, dead in rows:
        mid = int(mid)
        host = host_of(url, shop)
        info = dstat.get(host)
        if domain_unavailable(info, now):
            # выключенный домен: раз в DISABLED_PROBE_DAYS дней — DISABLED_PROBE_N пробных карточек,
            # чтобы заметить, что антибот сняли; квота остальных не сгорает
            if info['policy'] == 'disabled' and (info['last_probe_at'] is None or
                    (now - info['last_probe_at']).days >= DISABLED_PROBE_DAYS):
                if probe_left.get(host, DISABLED_PROBE_N) > 0:
                    probe_left[host] = probe_left.get(host, DISABLED_PROBE_N) - 1
                    probe.append((mid, eid, shop, url, 'probe', 0))
            continue
        last = dt.datetime.strptime(checked, '%Y-%m-%d %H:%M:%S') if checked else None
        age_h = (now - last).total_seconds() / 3600 if last else 10 ** 6
        item = (mid, eid, shop, url, state, age_h)
        # свежеснятый — на ускоренный круг (см. TTL_GONE_FRESH_HOURS)
        fresh_dead = False
        if state in ('gone', 'oos') and dead:
            try:
                fresh_dead = (now.date() - dt.date.fromisoformat(dead)).days <= GONE_FRESH_DAYS
            except ValueError:
                fresh_dead = False
        if fresh_dead and age_h >= TTL_GONE_FRESH_HOURS:
            confirm.append(item)                     # проверка «не ошиблись ли» — так же ценна
        elif (mid, eid) in sets and age_h >= TTL_SETS_HOURS:
            in_sets.append(item)
        elif age_h >= TTL_HOURS.get(state or None, 6):
            tail.append(item)
    for lst in (confirm, in_sets, tail):
        lst.sort(key=lambda x: -x[5])                # дольше всех не проверялся — первым
    n_conf = min(len(confirm), int(limit * SHARE_CONFIRM))
    # ВСЕ просроченные товары банка, а не доля бюджета (см. шапку). Потолок остаётся один —
    # сам бюджет: если банк когда-нибудь перерастёт прогон, порядок «дольше всех не проверялся»
    # разложит его по дням честно, а не отрежет случайные 36 позиций каждую ночь.
    n_sets = min(len(in_sets), limit)
    # ПРИОРИТЕТНЫЙ БЛОК ЗАБИРАЕМ ДО ДЕЛЕНИЯ ПО МАГАЗИНАМ (01.09). Иначе «приоритет» был
    # декларацией: пропорциональная квота резала его вместе с хвостом — на замере из 335
    # свежеснятых mnogomebeli в прогон проходили 63, остальные ждали суток. Проверка «не
    # ошиблись ли мы, сняв товар» — самый ценный запрос прогона и по объёму всегда мала
    # (единицы-десятки в установившемся режиме), поэтому она идёт вне квоты.
    reserved = confirm[:n_conf]
    queue = in_sets[:n_sets] + tail + confirm[n_conf:] + in_sets[n_sets:]
    limit = max(0, limit - len(reserved))

    # БЮДЖЕТ ДЕЛИМ ПО МАГАЗИНАМ ПРОПОРЦИОНАЛЬНО ИХ РАЗМЕРУ. Сплошная выборка по «давности»
    # отдала бы весь бюджет самому большому магазину (пока каталог не проверен, давность у всех
    # одинаковая): tvoydom с его 11 580 карточками забирал бы 3500/сутки четыре дня подряд, а
    # gipfel на 89 позиций ждал бы неделями. Поровну — тоже неверно: тогда круг у большого
    # магазина растягивается втрое против маленького. Пропорция даёт ОДИНАКОВЫЙ круг для всех,
    # а остаток бюджета разбирается по кругу — так ничей хвост не простаивает.
    by_shop: dict = {}
    for item in queue:
        by_shop.setdefault(item[2], []).append(item)
    total = sum(len(v) for v in by_shop.values()) or 1
    picked = []
    for shop, items in by_shop.items():
        quota = max(1, round(limit * len(items) / total))
        picked += items[:quota]
        by_shop[shop] = items[quota:]
    picked = picked[:limit]
    shops = sorted(by_shop, key=lambda s: -len(by_shop[s]))
    while len(picked) < limit and any(by_shop.values()):
        for shop in shops:
            if len(picked) >= limit:
                break
            if by_shop[shop]:
                picked.append(by_shop[shop].pop(0))
    picked = reserved + picked + probe
    # Считаем по ФАКТИЧЕСКОМУ составу, а не по признаку `suspect`: с приходом ускоренной
    # перепроверки (ADR-0148) приоритетный блок состоит из свежеснятых, и прежний счётчик
    # показывал бы «подтверждений 0» при полном блоке — оператор решил бы, что шаг не работает.
    in_sets_set = {(x[0], x[1]) for x in in_sets[:n_sets]}
    got_sets = sum(1 for x in picked if (x[0], x[1]) in in_sets_set)
    print(f'к проверке: {len(picked)} (перепроверка снятых {len(reserved)}, витрина {got_sets}, '
          f'хвост {len(picked) - len(reserved) - got_sets}); кандидатов всего {len(rows)}',
          flush=True)
    per = {}
    for x in picked:
        per[x[2]] = per.get(x[2], 0) + 1
    print('  по магазинам: ' + ', '.join(f'{k} {v}' for k, v in sorted(per.items(),
                                                                      key=lambda i: -i[1])),
          flush=True)
    return picked


# --- обход ---------------------------------------------------------------------------------------
class Domain:
    """Очередь одного домена: строго последовательно, с паузой и заморозкой при антиботе."""

    def __init__(self, host):
        self.host, self.items, self.blocked_streak, self.frozen = host, [], 0, False
        self.anchor_ok, self.anchor_why = True, ''


def anchor_cards(host: str) -> list:
    """Недавно живые карточки домена — якорь «маршрут карточек работает»."""
    rows = db(f"""select p.shop_mid, p.external_id, p.shop, coalesce(p.direct_url, p.url)
                 from product_page_status ps join products p using (shop_mid, external_id)
                where ps.state = 'alive' and ps.checked_at > now() - interval '14 days'
                  and lower(regexp_replace(split_part(split_part(coalesce(p.direct_url, p.url), '//', 2), '/', 1), '^www\\.', '')) = {q(host)}
                order by ps.checked_at desc limit {ANCHOR_CARDS};""")
    return [(int(r[0]), r[1], r[2], r[3]) for r in rows if len(r) == 4]


def check_anchor(d: 'Domain', obs: list, lock, run_id: str) -> None:
    """Главная + до 3 недавно живых карточек. Провал кворума → домен blocked на сутки, товары
    домена в этом прогоне не проверяются (их checked_at не двигается). Якорные наблюдения пишутся
    с disposition='anchor' — в свёртку не идут."""
    shop = d.items[0][2] if d.items else d.host
    code, body, err, final = fetch(f'https://{d.host}/')
    home = classify_full(shop, code, body, err, final, f'https://{d.host}/')
    home_ok = (code == 200 or (isinstance(code, int) and 300 <= code < 400)) and home['failure_kind'] not in ('challenge', 'rate_limit')
    if home_ok and code == 200 and home['failure_kind'] == 'no_signal':
        home_ok = True                    # у главной разметки наличия и не должно быть
    results = []
    for mid, eid, cshop, url in anchor_cards(d.host):
        time.sleep(random.uniform(*HOST_PAUSE))
        c2, b2, e2, f2 = fetch(url)
        r = classify_full(cshop, c2, b2, e2, f2, url)
        results.append((r['verdict'], r['failure_kind']))
        with lock:
            obs.append({'mid': mid, 'eid': eid, 'shop': cshop, 'url': url, 'code': c2, 'final': f2,
                        'verdict': r['verdict'], 'reason': 'якорь: ' + r['reason'], 'url_hash': url_key(url),
                        'prev': 'alive', 'kind': 'explore', 'disposition': 'anchor',
                        'response_kind': r['response_kind'], 'failure_kind': r['failure_kind'],
                        'evidence_kind': r['evidence_kind'],
                        'at': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    d.anchor_ok, d.anchor_why = anchor_verdict(home_ok, results)
    if d.anchor_ok:
        set_domain(d.host, 'open', f'якорь ок: главная {code}, карточек {len(results)}')
    else:
        set_domain(d.host, 'blocked', f'якорь: {d.anchor_why}', block_hours=DOMAIN_BLOCK_HOURS)
        print(f'ДОМЕН {d.host} ЗАБЛОКИРОВАН ЯКОРЕМ: {d.anchor_why} — {len(d.items)} проверок отменены', flush=True)


def crawl(picked: list, run_id: str, verbose: bool = True, max_minutes: int = 0) -> list:
    domains = {}
    for it in picked:
        host = host_of(it[3], it[2])          # без www и в нижнем регистре — тот же ключ, что в probe_domain_status
        domains.setdefault(host, Domain(host)).items.append(it)
    obs, lock = [], threading.Lock()
    # Внутри домена запросы строго последовательны с паузой 2–5 с, поэтому большой магазин
    # растягивает прогон: 3000 карточек = свыше трёх часов. Ночному циклу это мешает, а
    # недобранное просто уедет в завтрашний прогон — очередь и так по давности.
    deadline = time.time() + max_minutes * 60 if max_minutes else None

    def work(d: Domain):
        is_probe = all(it[4] == 'probe' for it in d.items)
        check_anchor(d, obs, lock, run_id)
        if not d.anchor_ok:
            if is_probe:
                set_domain(d.host, 'blocked', f'проба: {d.anchor_why}', block_hours=DOMAIN_BLOCK_HOURS, probed=True)
            return
        if is_probe:
            # антибот сняли — домен снова в работе (policy → auto)
            set_domain(d.host, 'open', 'проба прошла: якорь ок', policy='auto', probed=True)
            print(f'ДОМЕН {d.host}: проба прошла, снова проверяем', flush=True)
        for mid, eid, shop, url, state, _age in d.items:
            if d.frozen:
                break
            if deadline and time.time() > deadline:
                print(f'{d.host}: время прогона вышло, осталось непроверенным — уедет в следующий',
                      flush=True)
                break
            code, body, err, final = fetch(url)
            r = classify_full(shop, code, body, err, final, url)
            verdict, reason = r['verdict'], r['reason']
            facts = extract_page_facts(body) if code == 200 else {}
            with lock:
                # ВРЕМЯ НАБЛЮДЕНИЯ — МОМЕНТ ЗАПРОСА, а не момент записи: наблюдения сохраняются
                # пачкой в конце обхода, и `default now()` ставил всем проверкам прогона ОДИН
                # timestamp — правило «два голоса с разрывом ≥15 мин» опиралось бы на время
                # записи в БД. `kind` отделяет разведку от целевой перепроверки подозреваемого:
                # в проходе подтверждений 100% отрицательных ожидаемы, и гейту их считать нельзя.
                obs.append({'mid': mid, 'eid': eid, 'shop': shop, 'url': url, 'code': code,
                            'final': final, 'verdict': verdict, 'reason': reason,
                            'url_hash': url_key(url), 'prev': state, 'kind': 'explore',
                            'disposition': 'accepted',
                            'response_kind': r['response_kind'], 'failure_kind': r['failure_kind'],
                            'evidence_kind': r['evidence_kind'],
                            'price_seen': facts.get('price_seen'), 'name_seen': facts.get('name_seen'),
                            'canonical_url': facts.get('canonical_url'),
                            'at': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            if r['failure_kind'] in ('challenge', 'rate_limit'):
                d.blocked_streak += 1
                if d.blocked_streak >= BLOCK_STREAK:
                    d.frozen = True
                    set_domain(d.host, 'blocked', f'{BLOCK_STREAK} блокировок подряд', block_hours=DOMAIN_BLOCK_HOURS)
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
        f"{q(o['verdict'])}, {q(o['reason'])}, {PROBE_VERSION}, {q(run_id)}, "
        f"{q(o['at']) + '::timestamptz' if o.get('at') else 'now()'}, "
        f"{q(o.get('kind') or 'explore')}, {q(o.get('disposition') or 'accepted')}, "
        f"{q(o.get('response_kind'))}, {q(o.get('failure_kind'))}, {q(o.get('evidence_kind') or 'none')}, "
        f"{o['price_seen'] if isinstance(o.get('price_seen'), (int, float)) else 'null'}, "
        f"{q((o.get('name_seen') or '')[:200] or None)}, {q((o.get('canonical_url') or '')[:900] or None)})" for o in obs)
    db('insert into product_page_observation (shop_mid, external_id, url_hash, url, http_code, '
       'final_url, verdict, reason, probe_version, run_id, observed_at, probe_kind, disposition, '
       f'response_kind, failure_kind, evidence_kind, price_seen, name_seen, canonical_url) values {vals};')


# --- применение -----------------------------------------------------------------------------------
def history_shares(run_id: str) -> dict:
    """Историческая доля отрицательных по магазину (прошлые прогоны) — база для гейта ×3."""
    rows = db(f"""
    select p.shop_mid,
           count(*) filter (where o.verdict in ('gone','oos'))::float
             / greatest(count(*) filter (where o.verdict in ('alive','oos','gone')), 1)
      from product_page_observation o
      join products p on p.shop_mid = o.shop_mid and p.external_id = o.external_id
     where o.run_id <> {q(run_id)} and o.observed_at > now() - interval '30 days'
       and coalesce(o.probe_kind, 'explore') = 'explore' and coalesce(o.disposition, 'accepted') = 'accepted'
       and (o.probe_version = {PROBE_VERSION} or o.evidence_kind = 'http_gone')
     group by 1;""")
    return {int(r[0]): float(r[1]) for r in rows if r[0]}


def apply_run(obs: list, run_id: str, dry: bool = False) -> dict:
    """Гейты → свёртка истории → статусы → reconcile. Возвращает отчёт."""
    # Гейт судит ТОЛЬКО по разведочной части выборки. Проход подтверждений — это целевая
    # перепроверка уже известных подозреваемых, в нём 100% отрицательных ожидаемы; считая их,
    # гейт карантинил бы ровно те прогоны, ради которых он и заведён (поймано 31.08 на divanboss).
    per_shop = {}
    shop_of = {}
    for o in obs:
        if (o.get('kind') or 'explore') != 'explore' or (o.get('disposition') or 'accepted') != 'accepted':
            continue
        att, dec, neg = per_shop.get(o['mid'], (0, 0, 0))
        decisive = o['verdict'] in ('alive', 'oos', 'gone')
        per_shop[o['mid']] = (att + 1, dec + (1 if decisive else 0), neg + (1 if o['verdict'] in ('gone', 'oos') else 0))
        shop_of[o['mid']] = o['shop']
    quarantine, why = gate(per_shop, history_shares(run_id))
    # КАНАРЕЙКА АДРЕСА: при доле отрицательных выше CANARY_SHARE проверяем, что мы стучимся по правильным
    # ссылкам (испорченная схема ссылок даёт стабильный 404 на весь магазин)
    for mid, (att, dec, neg) in per_shop.items():
        if mid in quarantine or dec < 10 or neg / dec <= CANARY_SHARE:
            continue
        try:
            ok = stock_canary.check(shop_of[mid], run_id, verbose=False)
        except Exception as e:  # noqa: BLE001 — канарейка сама не должна ронять применение
            ok, e_txt = False, f'{type(e).__name__}: {str(e)[:80]}'
            why[mid] = f'канарейка не отработала ({e_txt})'
        if not ok:
            quarantine.add(mid)
            why.setdefault(mid, f'канарейка: {neg}/{dec} отрицательных, адреса не похожи на карточки')
    for mid in sorted(quarantine):
        print(f'КАРАНТИН магазина mid={mid}: {why[mid]} — вердикты НЕ применяются', flush=True)
    if quarantine and not dry:
        # карантин окончателен: наблюдения прогона больше не участвуют ни в свёртке, ни в истории
        db(f"update product_page_observation set disposition = 'quarantined' where run_id = {q(run_id)} "
           f"and shop_mid in ({','.join(str(m) for m in quarantine)}) and disposition = 'accepted';")
    touched = [(o['mid'], o['eid']) for o in obs
               if o['mid'] not in quarantine and (o.get('disposition') or 'accepted') == 'accepted']
    changes = {'gone': 0, 'oos': 0, 'alive': 0, 'unknown': 0}
    if touched and not dry:
        keys = ','.join(f"({m}, {q(e)})" for m, e in touched)
        rows = db(f"""
        select o.shop_mid, o.external_id, o.verdict, o.url_hash,
               to_char(o.observed_at, 'YYYY-MM-DD HH24:MI:SS'), coalesce(o.reason, '')
          from product_page_observation o
         where (o.shop_mid, o.external_id) in ({keys})
           and o.observed_at > now() - interval '90 days'
           and coalesce(o.disposition, 'accepted') = 'accepted'
           and (o.probe_version = {PROBE_VERSION} or o.evidence_kind = 'http_gone')
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
            # checked_at — время ПОСЛЕДНЕГО НАБЛЮДЕНИЯ, а не время применения. Иначе `--reapply`
            # (запросов не делает вовсе) объявлял бы все карточки «только что проверенными»:
            # очередь подтверждения пустела на 15 минут, TTL съезжал, а покрытие в метриках
            # показывало работу, которой не было.
            seen_at = history[-1][2].strftime('%Y-%m-%d %H:%M:%S')
            ups.append(f"({mid}, {q(eid)}, {q(state)}, {q(reason)}, {q(history[-1][1])}, {negs}, "
                       f"{q(seen_at)}::timestamptz, now(), {dead})")
        for i in range(0, len(ups), 500):
            db('insert into product_page_status (shop_mid, external_id, state, reason, url_hash, '
               'negatives, checked_at, applied_at, dead_since) values '
               + ','.join(ups[i:i + 500]) +
               ' on conflict (shop_mid, external_id) do update set state = excluded.state, '
               'reason = excluded.reason, url_hash = excluded.url_hash, '
               'negatives = excluded.negatives, checked_at = excluded.checked_at, '
               'applied_at = excluded.applied_at, '
               # ВОСКРЕС — ЗАБЫВАЕМ ДАТУ СМЕРТИ. `coalesce` держал её вечно: товар возвращался
               # в продажу, но числился умершим такого-то числа, и следующая смерть уже не
               # считалась свежей — ускоренная перепроверка (TTL_GONE_FRESH_HOURS) для него
               # больше не включалась бы никогда. Живой товар даты смерти иметь не должен.
               "dead_since = case when excluded.state in ('gone','oos') "
               'then coalesce(product_page_status.dead_since, excluded.dead_since) '
               'else null end;')
    report = {'run_id': run_id, 'checked': len(obs), 'quarantine': sorted(quarantine),
              'quarantine_why': {str(k): v for k, v in why.items()}, 'states': changes,
              'per_shop': {str(k): {'attempted': v[0], 'decisive': v[1], 'negative': v[2]} for k, v in per_shop.items()},
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
           coalesce(o.final_url, ''), o.verdict, coalesce(o.reason, ''), o.url_hash,
           to_char(o.observed_at, 'YYYY-MM-DD HH24:MI:SS'), coalesce(o.probe_kind, 'explore'),
           coalesce(o.disposition, 'accepted'), coalesce(o.response_kind, ''), coalesce(o.failure_kind, ''),
           coalesce(o.evidence_kind, 'none')
      from product_page_observation o
      join products p on p.shop_mid = o.shop_mid and p.external_id = o.external_id
     where o.run_id = {q(run_id)};""")
    return [{'mid': int(r[0]), 'eid': r[1], 'shop': r[2], 'url': r[3],
             'code': int(r[4]) if r[4].isdigit() else None, 'final': r[5], 'verdict': r[6],
             'reason': r[7], 'url_hash': r[8], 'prev': '', 'at': r[9], 'kind': r[10],
             'disposition': 'anchor' if r[11] == 'anchor' else 'accepted',   # карантин снимается при --reapply
             'response_kind': r[12] or None, 'failure_kind': r[13] or None, 'evidence_kind': r[14]}
            for r in rows]


def last_run_id() -> str:
    rows = db('select run_id from product_page_observation order by observed_at desc limit 1;')
    return rows[0][0] if rows else ''


def alert(text: str) -> None:
    sh = os.path.join(HERE, 'alert.sh')
    if os.path.exists(sh):
        os.system(f'bash {sh} "{text}" || true')


def shadow_candidates(shop: str, n_alive: int, n_unknown: int, n_neg: int) -> list:
    """Выборка для тени: недавно живые (gold: ложных негативов быть не должно), «неизвестные»
    (что v2 распознаёт) и известные снятые (ловит ли v2 их) — из принятых статусов v1."""
    out = []
    for state, n, order in (('alive', n_alive, 'ps.checked_at desc'), ('unknown', n_unknown, 'random()'),
                            ('gone', n_neg, 'random()'), ('oos', n_neg, 'random()')):
        if n <= 0:
            continue
        rows = db(f"""select p.shop_mid, p.external_id, p.shop, coalesce(p.direct_url, p.url), ps.state
                       from products p join product_page_status ps using (shop_mid, external_id)
                       join product_enrichment e using (shop_mid, external_id)
                      where lower(p.shop) = {q(shop.lower())} and ps.state = {q(state)} and e.status = 'active'
                        and coalesce(p.direct_url, p.url) <> ''
                      order by {order} limit {int(n)};""")
        out += [(int(r[0]), r[1], r[2], r[3], r[4], 0) for r in rows if len(r) == 5]
    per = {}
    for it in out:
        per[it[4]] = per.get(it[4], 0) + 1
    print(f'тень {shop}: {len(out)} карточек по прежним статусам ' + ', '.join(f'{k} {v}' for k, v in per.items()), flush=True)
    return out


def main() -> int:
    if '--shadow' in sys.argv:
        if not PARSER_V2:
            print('тень имеет смысл только с STOCK_PARSER_V2=1'); return 2
        shop = sys.argv[sys.argv.index('--shop') + 1] if '--shop' in sys.argv else ''
        if not shop:
            print('--shadow требует --shop'); return 2
        arg = lambda k, d: int(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
        max_min = arg('--max-minutes', 240)
        db(open(os.path.join(HERE, '003-stock-truth.sql'), encoding='utf-8').read())
        db(open(os.path.join(HERE, '004-stock-honesty.sql'), encoding='utf-8').read())
        run_id = dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '-shadow'
        picked = shadow_candidates(shop, arg('--alive', 300), arg('--unknown', 300), arg('--neg', 100))
        if not picked:
            print('тень: нечего проверять'); return 1
        obs = crawl(picked, run_id, max_minutes=max_min)
        for o in obs:
            if o.get('disposition') != 'anchor':
                o['disposition'] = 'shadow'
        save_observations(obs, run_id)
        print(f'тень записана: run_id={run_id}, наблюдений {len(obs)} (v{PROBE_VERSION}); применение НЕ выполнялось. '
              f'Отчёт: stock_shadow_report.py --run {run_id}', flush=True)
        return 0
    if '--reapply' in sys.argv:
        i = sys.argv.index('--reapply')
        run = sys.argv[i + 1] if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith('-') \
            else last_run_id()
        obs = observations_of_run(run)
        if not obs:
            print(f'нет наблюдений прогона {run!r}')
            return 1
        print(f'повторное применение прогона {run}: наблюдений {len(obs)}', flush=True)
        if '--dry-run' not in sys.argv:
            # карантин снимается; тень (v2 после gold) — принимается как обычные наблюдения
            db(f"update product_page_observation set disposition = 'accepted' where run_id = {q(run)} "
               "and disposition in ('quarantined', 'shadow');")
        rep = apply_run(obs, run, '--dry-run' in sys.argv)
        return 1 if rep.get('audit_mismatch', 0) else 0
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else DEFAULT_LIMIT
    only = sys.argv[sys.argv.index('--shop') + 1] if '--shop' in sys.argv else ''
    dry = '--dry-run' in sys.argv
    wait = int(sys.argv[sys.argv.index('--confirm-wait') + 1]) if '--confirm-wait' in sys.argv \
        else CONFIRM_GAP_MIN * 60
    max_min = int(sys.argv[sys.argv.index('--max-minutes') + 1]) if '--max-minutes' in sys.argv \
        else DEFAULT_MAX_MINUTES
    db(open(os.path.join(HERE, '003-stock-truth.sql'), encoding='utf-8').read())
    db(open(os.path.join(HERE, '004-stock-honesty.sql'), encoding='utf-8').read())
    run_id = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    picked = candidates(limit, only)
    if not picked:
        print('проверять нечего')
        return 0
    obs = crawl(picked, run_id, max_minutes=max_min)
    save_observations(obs, run_id)
    report = apply_run(obs, run_id, dry)

    # ПРОХОДА ПОДТВЕРЖДЕНИЯ БОЛЬШЕ НЕТ (ADR-0148). Он стоил паузы 900 с и повторного обхода всех
    # отрицательных, а по замеру 347 из 347 повторов подтвердили первый ответ и не отменили ни
    # одного. Владелец принял риск. Проверка «не ошиблись ли» переехала на 6 часов вперёд и живёт
    # в `candidates()` (`TTL_GONE_FRESH_HOURS`): свежеснятые попадают в очередь следующего прогона
    # как самые приоритетные, и «в продаже» возвращает товар. Флаг `--confirm-wait` оставлен для
    # ручного разбора инцидента: `--confirm-wait 900` повторяет старое поведение одним прогоном.
    if wait > 0 and '--confirm-wait' in sys.argv and not dry:
        fresh = [o for o in obs if o['verdict'] in ('gone', 'oos')
                 and o['mid'] not in report['quarantine']]
        if fresh:
            print(f'ручной повтор: пауза {wait} с, затем {len(fresh)} отрицательных', flush=True)
            time.sleep(wait)
            run2 = run_id + '-confirm'
            picked2 = [(o['mid'], o['eid'], o['shop'], o['url'], 'gone', 99) for o in fresh]
            obs2 = crawl(picked2, run2, max_minutes=max(30, max_min // 3))
            save_observations(obs2, run2)
            report = apply_run(obs2, run2, dry)

    bad = report.get('audit_mismatch', 0)
    if bad:
        alert(f'remlab: сторож наличия — {bad} расхождений с формулой после stock_check')
    if report['quarantine']:
        alert(f'remlab: stock_check — магазины в карантине {report["quarantine"]} '
              f'(всплеск отрицательных, вердикты не применены)')
    return 1 if bad else 0


def _selftest() -> int:
    import gzip
    bad = 0
    raw = b'<html>' + b'x' * 100000 + b'<meta itemprop="availability" content="InStock">'
    dec = _gunzip_stream()
    out = dec.decompress(gzip.compress(raw), len(raw))
    if out != raw:
        bad += 1; print('  FAIL gzip: распаковка не совпала')
    cases = [
        ((True, []), True), ((False, [('alive', None)]), False),
        ((True, [('alive', None), ('alive', None), ('gone', None)]), True),
        ((True, [('gone', None), ('gone', None), ('gone', None)]), False),   # маршрут карточек сломан
        ((True, [('unknown', 'challenge'), ('unknown', 'challenge'), ('alive', None)]), False),
        ((True, [('unknown', 'no_signal'), ('unknown', 'timeout')]), False),
        ((True, [('gone', None)]), True),   # одна карточка могла честно исчезнуть
    ]
    for (home, cards), want in cases:
        got, why = anchor_verdict(home, cards)
        if got != want:
            bad += 1; print(f'  FAIL якорь {home} {cards}: {got} ({why}), ожидалось {want}')
    now = dt.datetime.now()
    d_cases = [
        (None, False), ({'policy': 'disabled', 'state': 'blocked', 'blocked_until': None, 'last_probe_at': None}, True),
        ({'policy': 'auto', 'state': 'blocked', 'blocked_until': now + dt.timedelta(hours=1), 'last_probe_at': None}, True),
        ({'policy': 'auto', 'state': 'blocked', 'blocked_until': now - dt.timedelta(hours=1), 'last_probe_at': None}, False),
        ({'policy': 'auto', 'state': 'open', 'blocked_until': None, 'last_probe_at': None}, False),
    ]
    for info, want in d_cases:
        if domain_unavailable(info, now) != want:
            bad += 1; print(f'  FAIL domain_unavailable {info}: ожидалось {want}')
    print(f'stock_check selftest: случаев {1 + len(cases) + len(d_cases)}, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
