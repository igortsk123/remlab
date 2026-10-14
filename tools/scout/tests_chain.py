#!/usr/bin/env python3
"""ПРОВЕРКИ ЦЕПОЧКИ КАТАЛОГА ПО БИЗНЕС-ПРАВИЛАМ: фид → роль → стиль → «нужен меш» → очередь.

ЗАЧЕМ (владелец 13.10). Все крупные поломки 11–12.10 случились при ЗЕЛЁНЫХ тестах: роль товара
считалась в двух местах по-разному и тв-тумбы пропали целиком; дневной лимит стилей резал начало
пула и месяцами добивал ноль; закрепление владельцем не влияло на очередь. Механический тест
такого не ловит — он фотографирует текущее поведение. Здесь утверждается ПРАВИЛО ПРЕДМЕТНОЙ
ОБЛАСТИ: «товар из категории тумб под телевизор обязан доехать до подбора». Такое правило
переживает переписывание кода и краснеет ровно тогда, когда теряется смысл.

ДВА РЕЖИМА, ПОТОМУ ЧТО ЗВЕНЬЯ РАЗНОЙ ПРИРОДЫ:
  --selftest   чистые правила на фикстурах: без базы, без сети. Идёт в CI.
  --live       инварианты по живым данным дев-базы и перепись сторожей. Шаг ночного конвейера;
               расхождение печатает `WARN:` — то есть попадает в дайджест владельцу.

КАЖДАЯ ПРОВЕРКА ПЕЧАТАЕТ ЧИСЛО. «Не упало» — это не проверка: именно так месяц выглядел шаг,
который делал ноль работы и рапортовал «ок».

  ~/venvs/scout/bin/python tests_chain.py --selftest
  ~/venvs/scout/bin/python tests_chain.py --live
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FX = os.path.join(HERE, 'tests', 'fixtures')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A']


class Report:
    def __init__(self) -> None:
        self.bad = 0

    def ok(self, name: str, cond: bool, got: str) -> None:
        """Печатаем ВСЕГДА и всегда с числом: молчаливое «ок» нас уже подводило."""
        mark = ' ok ' if cond else 'FAIL'
        print(f'  [{mark}] {name}: {got}', flush=True)
        if not cond:
            self.bad += 1

    def warn(self, name: str, cond: bool, got: str) -> None:
        """Живые данные: расхождение — не падение прогона, а `WARN:` в дайджест."""
        if cond:
            print(f'  [ ok ] {name}: {got}', flush=True)
        else:
            print(f'WARN:chain_{name}: {got}', flush=True)
            self.bad += 1


# ---------------------------------------------------------------- звено 1: фид → роль
def link_feed_to_role(r: Report) -> None:
    """Категория магазина обязана давать роль, а запрещённая ветка — не давать.

    Тот самый случай: шаблон витрины искал `тв-тумб|тумб.*тв`, а магазин пишет «Тумбы под
    телевизор» — слова «тв» там нет. 471 тв-тумба в каноне превращалась в НОЛЬ в подборе.
    """
    os.environ.setdefault('SCOUT_PRIORS_PATH', os.path.join(FX, 'unit-priors-mini.json'))
    import load3

    catrole = {(99272, '26'): 'тв-тумба', (99272, '13'): None}
    known = {(99272, '26'), (99272, '13')}
    base = {'mid': 99272, 'params': {}, 'desc': '', 'price': 1000}

    tv = load3.assign({**base, 'cid': '26', 'name': 'Тумба под телевизор Харис 140x41'},
                      catrole, known)
    r.ok('фид→роль: тумба под телевизор получает роль', tv['role'] == 'тв-тумба',
         f'роль {tv["role"]!r}, принят={tv["accepted"]}')

    hall = load3.assign({**base, 'cid': '13', 'name': 'Обувница в прихожую Лотта'},
                        catrole, known)
    r.ok('фид→роль: запрещённая ветка роли не даёт', hall['role'] is None,
         f'роль {hall["role"]!r}, принят={hall["accepted"]}')

    unknown = load3.assign({**base, 'cid': '9999', 'name': 'Диван прямой Викс'}, catrole, known)
    r.ok('фид→роль: незнакомая категория не угадывается по названию', unknown['role'] is None,
         f'роль {unknown["role"]!r} (роль берётся из дерева, а не из слов в названии)')


# ---------------------------------------------------------------- звено 2: дневная добивка
def link_daily_limit(r: Report) -> None:
    """Потолок считается от НЕСОСЧИТАННЫХ. Иначе шаг молча делает ноль."""
    from catalog_rules import daily_todo

    todo = [f'товар-{i}' for i in range(10)]
    r.ok('лимит: из 10 несосчитанных при потолке 5 берём 5', len(daily_todo(todo, 5)) == 5,
         f'взято {len(daily_todo(todo, 5))}')
    r.ok('лимит: потолок больше остатка не режет', daily_todo(todo, 50) == todo,
         f'взято {len(daily_todo(todo, 50))} из {len(todo)}')
    r.ok('лимит: без потолка берём всё', daily_todo(todo, None) == todo,
         f'взято {len(daily_todo(todo, None))} из {len(todo)}')
    r.ok('лимит: пустой остаток остаётся пустым', daily_todo([], 5) == [],
         'взято 0 — добивать нечего, и это не ошибка')


# ---------------------------------------------------------------- звено 5: закреплённые
def link_pinned_first(r: Report) -> None:
    """Закреплённый владельцем идёт первым в ЛЮБОЙ очереди, а не только в боевой."""
    import mesh_priority as MP

    p = lambda role: {'role': role, 'status': 'none'}  # noqa: E731
    scored = [('m:1', p('диван'), {'сканди': 9, 'universal': False}),
              ('m:2', p('диван'), {'сканди': 8, 'universal': False})]
    prod = {s: pp for s, pp, _ in scored} | {'m:9': p('тв-тумба')}
    rows = MP.demo_pick(scored, ['сканди'], {'диван'}, 2, 0.0, 'test',
                        pinned=('m:9',), prod=prod)
    got = [x['sku'] for x in rows]
    r.ok('закреплённые: идут первыми даже вне профиля ролей', got[:1] == ['m:9'],
         f'первые: {got[:3]}')
    r.ok('закреплённые: не дублируются отбором', len(got) == len(set(got)), f'строк {len(got)}')


# ---------------------------------------------------------------- живые инварианты
def sql(q: str) -> str:
    out = subprocess.run(PSQL + ['-c', q], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr.strip()[:200])
    return out.stdout.strip()


def live_role_canon(r: Report) -> None:
    """Витрина подбора обязана отдавать роль КАНОНА, а не считать свою."""
    n = int(sql('select count(*) from products p join lr_roles l using (shop_mid, external_id) '
                'where p.cat_role is distinct from l.role') or 0)
    r.warn('role_canon', n == 0,
           f'товаров, где роль витрины расходится с картой категорий: {n} (должно быть 0)')


def mesh_roles() -> list[str]:
    """Роли, которым меш действительно нужен — ОДИН канон `rules/asset-strategies.json`.

    Первая версия проверки считала все роли подряд и дала 224 «находки», из которых ни одна не
    была ошибкой: полки и подушки режутся вырезкой, зеркало рисуется плоскостью. Проверка, которая
    кричит на здоровое, хуже отсутствующей — её перестают читать.
    """
    cfg = json.load(open(os.path.join(HERE, 'rules', 'asset-strategies.json'), encoding='utf-8'))
    roles = cfg['roles']
    default = roles.get('_default', 'hunyuan3d')
    assert default == 'hunyuan3d', 'умолчание канона сменилось — проверь список ролей'
    return [k for k, v in roles.items() if not k.startswith('_') and v == 'hunyuan3d']


def live_mesh_required(r: Report) -> None:
    """Товар с ролью, габаритами, фото и обогащением обязан быть помечен «нужен меш»."""
    lit = ', '.join("'" + x.replace("'", "''") + "'" for x in mesh_roles())
    n = int(sql(f"""select count(*) from products p join product_enrichment e using (shop_mid, external_id)
                    where p.in_stock and p.cat_role in ({lit}) and p.image_url is not null
                      and p.h_cm is not null and (p.w_cm is not null or p.dia_cm is not null)
                      and (p.d_cm is not null or p.dia_cm is not null)
                      and e.enriched_at is not null and e.payload->'model'->'styles' is not null
                      and not coalesce(p.mesh_required, false)""") or 0)
    r.warn('mesh_required', n == 0,
           f'товаров, прошедших все условия, но без пометки «нужен меш»: {n} (должно быть 0)')


def live_queue_not_empty(r: Report) -> None:
    """Есть спрос — обязана быть очередь. Пустая очередь при спросе = простой оплаченных нод."""
    demand = int(sql("select count(*) from products where in_stock and mesh_required "
                     "and mesh_uri is null") or 0)
    jobs = int(sql("select count(*) from mesh_jobs where status='queued'") or 0)
    r.warn('queue', not (demand > 0 and jobs == 0),
           f'ждут меша {demand}, заданий в очереди {jobs}')


def live_guards_scheduled(r: Report) -> None:
    """Перепись сторожей: выпавший из расписания сторож не кричит о себе сам.

    Сторож денег выпал 08.09 и молчал месяц — именно поэтому проверка смотрит РАСПИСАНИЕ,
    а не журнал: пустой журнал и отсутствие сторожа выглядят одинаково.
    """
    need = ['money_guard', 'idle_guard', 'sink_keeper', 'batch_window']
    res = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    # НЕ СМОГЛИ ПРОЧИТАТЬ ≠ «сторожей нет» (Codex 13.10, conv-06): иначе сбой чтения выглядел бы как пропажа всех
    if res.returncode != 0 and 'no crontab' not in (res.stderr or '').lower():
        r.warn('guards', False, f'расписание не прочитать (crontab -l: код {res.returncode}, {res.stderr.strip()[:80]}) — проверка не выполнена')
        return
    cron = res.stdout
    missing = [g for g in need if g not in cron]
    r.warn('guards', not missing,
           f'в расписании {len(need) - len(missing)} из {len(need)} сторожей'
           + (f'; НЕТ: {", ".join(missing)}' if missing else ''))


def live_photo_gate(r: Report) -> None:
    """Фото реально скачивается (conv-05): в очереди моделей нет товара с приговором «фото мёртвое»;
    печатаем, сколько товаров в наличии живы / мертвы / не проверены."""
    dead_q = int(sql("""select count(*) from mesh_jobs j join products p
                         on p.shop_mid::text||':'||p.external_id = j.sku
                        where j.status = 'queued' and p.photo_alive = false""") or 0)
    dist = sql("select k||'='||n from (select coalesce(photo_alive::text,'null') k, count(*) n from products "
               "where in_stock group by 1) t")
    r.warn('photo_gate', dead_q == 0, f'в очереди моделей с мёртвым фото: {dead_q}; фото товаров в наличии: '
           + ', '.join(dist.split()))


def live_demo_variants(r: Report) -> None:
    """Варианты демо полные (conv-09): у каждого ядро гостиной, ковёр, ≥ 6 предметов и ни одной роли
    «товара нет»; стили без полного набора перечисляются — их не публикуют, но владелец должен знать."""
    p = os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
    d = json.load(open(p, encoding='utf-8'))
    core = ('диван', 'столик', 'тв-тумба', 'ковёр', 'торшер')
    thin = []
    for v in d.get('variants') or []:
        roles = {(i.get('role') or '').split(' ')[0] for i in v.get('items') or []}
        miss = [c for c in core if c not in roles]
        if miss or len(v.get('items') or []) < 6 or v.get('missing_item'):
            thin.append(f"{v.get('style')}: предметов {len(v.get('items') or [])}, нет {', '.join(miss) or '—'}")
    if not d.get('variants'):
        thin.append('вариантов нет вовсе')
    r.warn('demo_variants', not thin, f"вариантов {len(d.get('variants') or [])}, неполных {len(thin)}"
           + (f" ({'; '.join(thin)})" if thin else ''))
    inc = d.get('incomplete_styles') or []
    r.warn('demo_styles', not inc, 'стилей без полного набора: ' + (
        '; '.join(f"{x['style']} (нет {', '.join(x['missing'])})" for x in inc) if inc else '0'))


def live_swap_feeds(r: Report) -> None:
    """Лента замен демо (conv-03, ADR-0271): каждый товар из пула стоит в ленте только стиля, где его балл ≥ порога
    (`rules/demo-swap.json`); пары «роль × стиль» с замен меньше `starving_below` — список (стиль голодает → приоритет
    мешей). Читает собранный `demo-data.json` и баллы из базы."""
    rules = json.load(open(os.path.join(HERE, 'rules', 'demo-swap.json'), encoding='utf-8'))
    thr, starve = float(rules['in_style_min']), int(rules['starving_below'])
    d = json.load(open(os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json'), encoding='utf-8'))
    pool = [(role, it) for role, lst in (d.get('feeds') or {}).items() for it in lst if it.get('src') == 'pool']
    sids = sorted({it['sid'] for _, it in pool if it.get('sid')})
    scores: dict = {}
    for i in range(0, len(sids), 400):
        lit = ','.join("('" + x.split('_', 1)[0] + "','" + x.split('_', 1)[1].replace("'", "''") + "')" for x in sids[i:i + 400])
        for ln in sql(f"""select shop_mid||'_'||external_id||'\t'||scores::text from product_style_scores
                           where (shop_mid::text, external_id) in ({lit})""").splitlines():
            k, _, v = ln.partition('\t')
            if v:
                scores[k] = json.loads(v)
    low = [f"{it['sid']}:{st}" for _, it in pool for st in it.get('styles') or []
           if float((scores.get(it['sid']) or {}).get(st, 0)) < thr]
    cnt: dict = {}
    for role, it in pool:
        for st in it.get('styles') or []:
            cnt[(role, st)] = cnt.get((role, st), 0) + 1
    styles = sorted({st for _, st in cnt})
    roles = sorted({ro for ro, _ in cnt})
    hungry = [f'{ro}/{st} {cnt.get((ro, st), 0)}' for ro in roles for st in styles if cnt.get((ro, st), 0) < starve]
    r.warn('swap_style_floor', not low, f'товаров ленты со стилем ниже {thr:g}: {len(low)}' + (f' ({", ".join(low[:5])}…)' if low else ''))
    r.warn('swap_starving', len(hungry) < len(roles) * len(styles), f'пар «роль × стиль» с замен < {starve}: {len(hungry)}'
           + (f' — {"; ".join(hungry[:12])}' if hungry else ''))


def main() -> int:
    live = '--live' in sys.argv
    r = Report()
    if live:
        print('проверки цепочки по ЖИВЫМ данным:', flush=True)
        for fn in (live_role_canon, live_mesh_required, live_queue_not_empty, live_guards_scheduled,
                   live_demo_variants, live_photo_gate, live_swap_feeds):
            try:
                fn(r)
            except Exception as e:  # noqa: BLE001 — одна проверка не должна ронять шаг
                print(f'WARN:chain_{fn.__name__}: не посчиталась ({type(e).__name__}: {str(e)[:90]})',
                      flush=True)
                r.bad += 1
        print(f'цепочка (живые): расхождений {r.bad}', flush=True)
        return 0          # живые расхождения — предупреждение, а не падение конвейера
    print('проверки цепочки на фикстурах:', flush=True)
    for fn in (link_feed_to_role, link_daily_limit, link_pinned_first):
        fn(r)
    print(f'tests_chain selftest: ошибок {r.bad}', flush=True)
    return 1 if r.bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
