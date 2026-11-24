#!/usr/bin/env python3
"""ЗАЩИТА ОТ КОМПЛЕКТУЮЩИХ — роль мебели снимается с групп товаров, которые по данным не мебель (T-20261124-08/2, правило Г).

ЗАЧЕМ. Магазин-поставщик фурнитуры (замер 24.11: 824 товара в наличии — штанги, ролики, рамки, кронштейны) получил роли «шкаф»/«стеллаж»
по родителю пути категории («Шкафы. Гардеробные. Двери / …», `category_map.classify`: откат с листа на путь) или от листа вроде
«Стеллажная система UNICO». Такие товары видны как мебель в `lr_roles`, `catalog_ready`, счётчиках. Точечные OVERRIDES по магазину —
заплатка; здесь общее правило по данным, а не по ID (владелец: каждое правило — на все магазины и будущие загрузки).

ПРАВИЛО Г. Категория (магазин + category_id) теряет мебельную роль, если ВСЁ:
  1. роль ∈ `dimless.ROLES` (мебель/свет/декор; текстиль, у которого высоты нет по природе, — вне);
  2. категория в карантине `dimless.decide`: n ≥ MIN_N и ни одного ИЗМЕРЕННОГО Ш×В (тот же код и порог, включая «ветка»/«магазин»);
  3. размеры не были раньше: среди прежних строк категории (архив/пропали) доля с Ш×В < `max_prior_dims_share` — иначе это сбой
     фида, а не «товаров без размеров»: снятие приостановлено, строка WARN;
  4. И (роль дана ПРЕДКОМ при неподтверждённом листе — `classify` вернул «по категории фида»,
     ИЛИ ≥ `min_share_names` названий категории содержат слова-комплектующие из `rules/component-guard.json`).
«Система» признаком не служит (Codex 24.11, п.2): «система хранения» бывает мебелью.

ЧТО ДЕЛАЕТ. `cat_role = NULL` при `accepted=True` — строка грузится и в архив НЕ уходит (как детское, кровать, секция дивана); `product_kind
= 'component'` (обычный товар — NULL), `kind_reason` — причина, `role_before` — роль для возврата. Роль «комплектующие» в `cat_role` НЕ вводим:
`accepted = bool(role)`, любой потребитель, проверяющий непустую роль, пропустил бы деталь как мебель (Codex п.3).
ЛИПКОСТЬ. Ночной `load3` и `category_map --apply` пишут роль из карты заново — оба после записи гасят роль у строк `product_kind='component'`
(SQL с проверкой наличия колонки: до миграции — как прежде). Возврат: категория перестала подходить (появились размеры, словарь, предок) →
`cat_role = role_before`, `product_kind = NULL`; решение пересчитывается каждый прогон и на строках, уже снятых.
ПРЕДОХРАНИТЕЛИ. Новых снятий за прогон больше `limits.max_new_abs`, или на магазин больше `limits.max_new_share` его мебельных строк (новый
магазин-фурнитура целиком) — не применять без явного `--allow-new N` (слово владельца/директора); колонок нет (миграция не применена) — отказ.
Выключатель — `rules/component-guard.json:enabled` (по умолчанию false): `--nightly` при false ничего не читает и не пишет.

  python3 component_guard.py                       # --report: кандидаты и контрпримеры, БЕЗ записи (SELECT)
  python3 component_guard.py --report --json f     # + таблица в json
  python3 component_guard.py --apply [--allow-new N]   # записать (одна транзакция); только по слову директора
  python3 component_guard.py --nightly             # шаг ночи: enabled=false → одна строка и выход 0
Env: REMLAB_DEVDB_NAME — одноразовая база (как у dimless).
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import category_map as CM  # noqa: E402
import dimless  # noqa: E402

RULES_PATH = os.environ.get('SCOUT_COMPONENT_GUARD_RULES') or os.path.join(HERE, 'rules', 'component-guard.json')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', os.environ.get('REMLAB_DEVDB_NAME', 'remlab'),
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
KIND_COLS = ('product_kind', 'kind_reason', 'role_before')
WHY_LEAF = 'по листу категории фида'
WHY_PATH = 'по категории фида'


def load_rules(path: str | None = None) -> dict:
    return json.load(open(path or RULES_PATH, encoding='utf-8'))


def words_rx(rules: dict) -> re.Pattern:
    """Слова-комплектующие: левая граница слова, дальше — основа (направляющ → «направляющая», «направляющие»)."""
    return re.compile(r'(?<![а-яёa-z0-9])(?:' + '|'.join(rules['words']) + ')', re.I)


def name_share(names: list[str], rx: re.Pattern) -> float:
    return sum(1 for n in names if rx.search(n or '')) / len(names) if names else 0.0


def ancestor_role(path: str, role: str, key: str) -> bool:
    """Роль группы дана ПРЕДКОМ пути при неподтверждённом листе: `classify` ответил «по категории фида» (не «по листу»).
    Ключи OVERRIDES/MIXED решаются иначе (точечно/по названию) — не предок."""
    if not path or key in CM.OVERRIDES or key in CM.MIXED:
        return False
    r, why = CM.classify(path)
    return r == role and why == WHY_PATH


def evaluate(groups: dict, decided: dict, rules: dict, paths: dict) -> list[dict]:
    """Чистое решение по категориям (без БД). groups {(mid, cid): {shop, leaf, role, n, m, comp_n, new_n, prior_n, prior_wh, names}},
    decided — `dimless.decide`, paths {(mid, cid): полный путь}. Вердикт: снять / держим (причина) / вернуть / не в карантине."""
    rx = words_rx(rules)
    out = []
    for key, g in sorted(groups.items(), key=lambda kv: -kv[1]['n']):
        mid, cid = key
        path = paths.get(key) or ''
        prior_share = g['prior_wh'] / g['prior_n'] if g['prior_n'] else None
        anc = ancestor_role(path, g['role'], f'{mid}:{cid}')
        share = name_share(g.get('names') or [], rx)
        row = dict(mid=mid, cid=cid, shop=g['shop'], leaf=g['leaf'], path=path, role=g['role'], n=g['n'], m=g['m'], comp_n=g['comp_n'], new_n=g['new_n'],
                   prior_n=g['prior_n'], prior_share=prior_share, ancestor=anc, name_share=share, quarantine=decided.get(key))
        if key not in decided:
            row.update(verdict='вернуть' if g['comp_n'] else 'не в карантине', reason='размеры есть или категория мала' if g['comp_n'] else '')
        elif prior_share is not None and prior_share >= rules['max_prior_dims_share']:
            row.update(verdict='вернуть' if g['comp_n'] else 'держим',
                       reason=f'размеры раньше были ({prior_share:.0%} прежних строк) — похоже на сбой фида, снятие приостановлено',
                       paused=bool(anc or share >= rules['min_share_names']))
        elif anc or share >= rules['min_share_names']:
            why = ['роль от предка при неподтверждённом листе'] if anc else []
            if share >= rules['min_share_names']:
                why.append(f'слов-комплектующих {share:.0%} названий')
            row.update(verdict='снять', reason=f"карантин без размеров ({decided[key]}); " + '; '.join(why))
        else:
            row.update(verdict='вернуть' if g['comp_n'] else 'держим', reason=f'лист подтверждает роль, слов-комплектующих {share:.0%} < {rules["min_share_names"]:.0%}')
        out.append(row)
    return out


# --- БД ----------------------------------------------------------------------------------------------------------------------------
def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:600])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def has_kind_cols(run=db) -> bool:
    got = run("select count(*) from information_schema.columns where table_name='products' and column_name in ("
              + ','.join("'" + c + "'" for c in KIND_COLS) + ")")
    return bool(got) and int(got[0][0]) == len(KIND_COLS)


def stats_sql(kind_cols: bool) -> str:
    comp, free, role = (("product_kind = 'component'", 'product_kind is null', 'coalesce(role_before, cat_role)') if kind_cols
                        else ('false', 'true', 'cat_role'))
    roles = dimless._roles_sql()
    return f"""with a as (
  select shop_mid, category_id, min(shop) shop, min(category_path) leaf, count(*) n, count(*) filter (where {dimless.MEASURED_SQL}) m,
         count(*) filter (where {comp}) comp_n, count(*) filter (where cat_role is not null and {free}) new_n,
         mode() within group (order by {role}) role
    from products
   where status = 'active' and (cat_role = any({roles}) or {comp}) and category_id is not null
   group by shop_mid, category_id),
 b as (select shop_mid, category_id, count(*) prior_n, count(*) filter (where w_cm > 0 and h_cm > 0) prior_wh
         from products where status <> 'active' and category_id is not null group by shop_mid, category_id)
select a.shop_mid, a.category_id, a.shop, a.leaf, a.n, a.m, a.comp_n, a.new_n, a.role, coalesce(b.prior_n, 0), coalesce(b.prior_wh, 0)
  from a left join b using (shop_mid, category_id)"""


def names_sql(keys: list[tuple], kind_cols: bool) -> str:
    comp = "product_kind = 'component'" if kind_cols else 'false'
    lit = ','.join(f"({int(m)},'{str(c).replace(chr(39), chr(39) * 2)}')" for m, c in keys)
    return (f"select shop_mid, category_id, replace(name, E'\\x1f', ' ') from products where status = 'active' "
            f"and (cat_role = any({dimless._roles_sql()}) or {comp}) and (shop_mid, category_id::text) in ({lit})")


def gather(run=db) -> tuple[dict, dict, bool]:
    """(groups, paths, kind_cols) из БД — только SELECT."""
    kc = has_kind_cols(run)
    groups = {}
    for r in run(stats_sql(kc)):
        if len(r) < 11:
            continue
        groups[(int(r[0]), r[1])] = dict(shop=r[2], leaf=r[3], n=int(r[4]), m=int(r[5]), comp_n=int(r[6]), new_n=int(r[7]), role=r[8],
                                         prior_n=int(r[9]), prior_wh=int(r[10]), names=[])
    paths = dimless._paths()
    return groups, paths, kc


def attach_names(groups: dict, decided: dict, kc: bool, run=db) -> None:
    keys = [k for k in decided if k in groups]
    if not keys:
        return
    for r in run(names_sql(keys, kc)):
        if len(r) >= 3:
            groups[(int(r[0]), r[1])]['names'].append(r[2])


def plan(run=db, rules: dict | None = None) -> tuple[list[dict], bool]:
    rules = rules or load_rules()
    groups, paths, kc = gather(run)
    decided = dimless.decide({k: (g['n'], g['m']) for k, g in groups.items()}, paths)
    attach_names(groups, decided, kc, run)
    return evaluate(groups, decided, rules, paths), kc


# --- применение --------------------------------------------------------------------------------------------------------------------
def q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def apply_sql(rows: list[dict]) -> str:
    """Один SQL-скрипт транзакции: снять (первый раз: роль → role_before) и вернуть (категории, что перестали подходить)."""
    take = [r for r in rows if r['verdict'] == 'снять' and r['new_n']]
    back = [r for r in rows if r['verdict'] == 'вернуть']
    parts = ['begin;']
    if take:
        vals = ','.join(f"({r['mid']},{q(r['cid'])},{q(r['reason'])})" for r in take)
        parts.append("update products p set role_before = p.cat_role, cat_role = null, product_kind = 'component', kind_reason = v.reason "
                     f"from (values {vals}) as v(mid, cid, reason) "
                     "where p.shop_mid = v.mid and p.category_id::text = v.cid and p.cat_role is not null and p.product_kind is null;")
    if back:
        vals = ','.join(f"({r['mid']},{q(r['cid'])})" for r in back)
        parts.append("update products p set cat_role = p.role_before, product_kind = null, kind_reason = null, role_before = null "
                     f"from (values {vals}) as v(mid, cid) "
                     "where p.shop_mid = v.mid and p.category_id::text = v.cid and p.product_kind = 'component';")
    parts.append('commit;')
    return '\n'.join(parts) if (take or back) else ''


def safety(rows: list[dict], rules: dict, allow_new: int = 0) -> tuple[bool, list[str]]:
    """(можно ли применять, причины отказа): новых снятий больше потолка — без явного разрешения не применять."""
    lim = rules['limits']
    take = [r for r in rows if r['verdict'] == 'снять']
    total = sum(r['new_n'] for r in take)
    why = []
    if total > max(lim['max_new_abs'], allow_new):
        why.append(f"новых снятий {total} > потолка {max(lim['max_new_abs'], allow_new)} (limits.max_new_abs / --allow-new)")
    shop_all: dict[str, int] = {}
    shop_new: dict[str, int] = {}
    for r in rows:
        shop_all[r['shop']] = shop_all.get(r['shop'], 0) + r['n']
    for r in take:
        shop_new[r['shop']] = shop_new.get(r['shop'], 0) + r['new_n']
    for s, k in shop_new.items():
        if k > allow_new and shop_all.get(s) and k / shop_all[s] > lim['max_new_share']:
            why.append(f"магазин {s}: новых снятий {k} из {shop_all[s]} мебельных ({k / shop_all[s]:.0%}) > {lim['max_new_share']:.0%}")
    return not why, why


def digest(rows: list[dict], applied: bool, prefix: str = 'WARN:component_guard: ') -> list[str]:
    lines = []
    by: dict[str, list[dict]] = {}
    for r in rows:
        if r['verdict'] == 'снять' and r['new_n']:
            by.setdefault(r['shop'], []).append(r)
    verb = 'снята роль мебели' if applied else 'будет снята роль мебели (отчёт, записи нет)'
    for shop, rs in sorted(by.items(), key=lambda kv: -sum(x['new_n'] for x in kv[1])):
        top = ', '.join(f"«{x['leaf']}» {x['new_n']}" for x in rs[:3])
        lines.append(f"{prefix}магазин {shop} — {verb}: {sum(x['new_n'] for x in rs)} товаров в {len(rs)} категориях, причина — {rs[0]['reason'].split('; ', 1)[-1] if len(rs) == 1 else 'карантин без размеров + предок/слова'} ({top}{'…' if len(rs) > 3 else ''})")
    back = [r for r in rows if r['verdict'] == 'вернуть']
    if back:
        lines.append(f"{prefix}возврат роли: {sum(r['comp_n'] for r in back)} товаров в {len(back)} категориях — «{back[0]['leaf']}» и др.: категория перестала подходить")
    paused = [r for r in rows if r.get('paused')]
    for r in paused:
        lines.append(f"{prefix}приостановлено: магазин {r['shop']} «{r['leaf']}» ({r['n']} товаров) — {r['reason']}")
    return lines


def cmd_report(rules: dict, json_out: str = '') -> int:
    rows, kc = plan(rules=rules)
    print(f"колонок product_kind/kind_reason/role_before: {'есть' if kc else 'НЕТ (миграция не применена — отчёт по тем же правилам, писать нельзя)'}; категорий с мебельной ролью: {len(rows)}")
    take = [r for r in rows if r['verdict'] == 'снять']
    print(f"\n== СНЯТЬ: {len(take)} категорий, {sum(r['new_n'] for r in take)} новых товаров (всего с уже снятыми {sum(r['n'] for r in take)})")
    for r in take:
        print(f"  {r['shop'][:14]:14} {r['role'][:9]:9} n={r['n']:4} новых={r['new_n']:4} слов {r['name_share']:4.0%} предок={'да' if r['ancestor'] else 'нет'} прежде={'—' if r['prior_share'] is None else f'{r["prior_share"]:.0%}'}/{r['prior_n']} | {r['path'][:60] or r['leaf']}")
    print('\n== КОНТРПРИМЕРЫ — карантин без размеров, но НЕ снимаем (почему)')
    for r in rows:
        if r['verdict'] in ('держим', 'вернуть') and r['quarantine']:
            print(f"  {r['shop'][:14]:14} {r['role'][:9]:9} n={r['n']:4} | {r['path'][:60] or r['leaf']} | {r['reason']}")
    anc = [r for r in rows if r['ancestor'] and r['verdict'] == 'не в карантине']
    print(f"\n== РОЛЬ ОТ ПРЕДКА, но не карантин (размеры есть/категория мала) — не трогаем: {len(anc)} категорий, {sum(r['n'] for r in anc)} товаров")
    for r in sorted(anc, key=lambda r: -r['n'])[:12]:
        print(f"  {r['shop'][:14]:14} {r['role'][:9]:9} n={r['n']:4} измерено={r['m']:4} | {r['path'][:60] or r['leaf']}")
    cand = [r for r in rows if r['verdict'] == 'не в карантине' and not r['ancestor'] and r['name_share'] >= rules['min_share_names']]
    print(f"\n== СЛОВА-КОМПЛЕКТУЮЩИЕ ≥ порога, но НЕ в карантине (размеры есть) — не трогаем: {len(cand)}")
    ok, why = safety(rows, rules)
    print(f"\nпредохранители: {'пройдены' if ok else 'НЕ пройдены — ' + '; '.join(why) + ' (применять только с --allow-new N по слову директора)'}")
    for ln in digest(rows, applied=False, prefix='дайджест: '):
        print(ln)
    if json_out:
        json.dump(rows, open(json_out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return 0


def cmd_apply(rules: dict, allow_new: int = 0) -> int:
    rows, kc = plan(rules=rules)
    if not kc:
        print('component_guard: СТОП — колонок product_kind/kind_reason/role_before нет (миграция tools/scout/019-product-kind.sql не применена); данные не менялись')
        return 1
    ok, why = safety(rows, rules, allow_new)
    for r in rows:
        if r.get('paused'):
            print(f"WARN:component_guard: приостановлено: магазин {r['shop']} «{r['leaf']}» ({r['n']} товаров) — {r['reason']}", flush=True)
    if not ok:
        print('WARN:component_guard: снятие НЕ применено — предохранитель: ' + '; '.join(why), flush=True)
        for ln in digest(rows, applied=False):
            print(ln)
        return 0
    sql = apply_sql(rows)
    if sql:
        r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
        if r.returncode != 0:
            print('component_guard: СТОП — транзакция откатилась, данные не менялись:', r.stderr[:500])
            return 1
    for ln in digest(rows, applied=True):
        print(ln, flush=True)
    print(f"component_guard: снято новых {sum(x['new_n'] for x in rows if x['verdict'] == 'снять')}, возвращено {sum(x['comp_n'] for x in rows if x['verdict'] == 'вернуть')}, "
          f"держим в карантине без снятия {sum(1 for x in rows if x['verdict'] == 'держим' and x['quarantine'])} категорий", flush=True)
    return 0


def main(argv: list[str]) -> int:
    rules = load_rules()
    if '--nightly' in argv:
        if not rules.get('enabled'):
            print('component_guard: выключен (rules/component-guard.json enabled=false) — ничего не читаю и не пишу')
            return 0
        return cmd_apply(rules)
    if '--apply' in argv:
        allow = int(argv[argv.index('--allow-new') + 1]) if '--allow-new' in argv else 0
        return cmd_apply(rules, allow)
    return cmd_report(rules, argv[argv.index('--json') + 1] if '--json' in argv else '')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
