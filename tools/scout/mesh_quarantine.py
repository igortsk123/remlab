#!/usr/bin/env python3
"""Карантин кривых моделей (план conv-04, ADR-0276): ось модели расходится с паспортом больше порога → не готова.

ЗАЧЕМ. Владелец 13.10: «пропорции расходятся с паспортом больше чем на 15 % по любой оси — в брак, отдавать человеку»;
14.10 выбран порог 25 % (`rules/mesh-quarantine.json`). Метрика — `mesh_axes.deviation` (масштаб по высоте паспорта,
сравниваем ширину и глубину). Карантин = статус ревизии `quarantine` (`asset_revisions`): предикат готовности
(`mesh_ready`) и привязка к товару (`mesh_bind`) его не считают годным, демо и комплекты модель не берут. Прежний
статус — в `mesh_quarantine` (`012-mesh-quarantine.sql`): решение владельца на странице `/test/mesh-quarantine/`
(«принять» — вернуть, «брак» — `owner_reject`, «порезать» — остаётся в карантине до новой модели) забирает `--pull`
из `/api/lab/review` (ADR-0275). Решённое повторно в карантин не попадает.

  ~/venvs/scout/bin/python mesh_quarantine.py --apply [--limit N]   # замерить новые модели, вывести кривые
  ~/venvs/scout/bin/python mesh_quarantine.py --sync-grey [--dry]   # серая крышка: МЯГКИЙ карантин по всем мешам детектора + удержание болванок (ночью, после mesh_color_guard)
  ~/venvs/scout/bin/python mesh_quarantine.py --pull                # забрать решения владельца
  ~/venvs/scout/bin/python mesh_quarantine.py --page [--publish]    # страница разбора
  python3 mesh_quarantine.py --selftest
"""
import html
import json
import os
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mesh_photo as MP  # noqa: E402 — ЕДИНОЕ правило выбора фото меша (ADR-0452)
RULES = os.path.join(HERE, 'rules', 'mesh-quarantine.json')
CACHE = os.path.expanduser('~/scout-scenes/mesh-axes-cache.json')     # glb_sha → замер (модель не меняется)
CURSOR = os.path.expanduser('~/scout-scenes/mesh-quarantine.cursor')
PAGE = os.path.join(HERE, 'mesh-quarantine-page', 'index.html')
SITE = os.environ.get('REMLAB_SITE', 'https://remont-lab.online')
VERDICT = {'accept': 'принять', 'reject': 'брак', 'cut': 'порезать вручную'}


def threshold() -> float:
    return float(json.load(open(RULES, encoding='utf-8'))['threshold'])


def reasons(m: dict, thr: float) -> list:
    """Признаки карантина v2 — независимые (Codex 14.10): плохая вырезка, подложка, сильное искажение. Чистая функция."""
    out = []
    if m.get('mask'):
        out.append('mask')
    if m.get('slab'):
        out.append('slab')
    if m.get('max_dev') is not None and m['max_dev'] > thr:
        out.append('proportion')
    if m.get('dark') is not None:
        out.append('dark')          # модель намного темнее товара (`mesh_dark.py`, demo-05 15.10)
    if m.get('grey_top') in ('candidate', 'reject'):
        out.append('grey_top')      # верх — пустой серый фон сети paint (`mesh_grey_top.py`, T-20261118-04/12): лента и наборы берут похожий товар с годным мешем
    return out


def pick(measures: list[dict], thr: float, decided: set) -> list[dict]:
    """Кого вывести в карантин: есть хоть один признак, модель не решена владельцем. Чистая функция."""
    return [m for m in measures if reasons(m, thr) and (m['sku'], m['glb_sha']) not in decided]


# ---------- СЕРАЯ КРЫШКА — ТОЛЬКО МЯГКИЙ КАРАНТИН (T-20261119-101/3, Codex 19.11 `_intake/codex/2026-11-19-grey-quarantine-answer.md`) ----------
# Источник — ВСЕ меши детектора (`mesh-color/current.json` сторожа цвета: asset_id, owner, via_family), а не список осей `MD.rows` (паспорт, роль, решённая ориентация):
# 19.11 осевой список не видел ~⅔ серых (Харис — ориентация review_pending, Тебар — роль «шкаф», Мостар — нет в products). Единица — `(owner, glb_sha16)`:
# 149 строк сторожа = ~104 уникальных GLB, варианты семьи наследуют owner (чужой меш представителя). Строка только с причиной `grey_top` МЯГКАЯ
# (`room_bindings.soft_sql`): статус ревизии НЕ меняется (модель в индексе, замену ищут, пока её нет — роль остаётся). Прежнее поведение (`quarantine` в
# `asset_revisions` от любого flagged) было жёстким запретом в обход мягкой политики — и снимается общим правилом (`RESTORE_SQL`).
MC_DIR = os.path.expanduser(os.environ.get('MESH_COLOR_DIR') or '~/scout-scenes/catalog-assets/mesh-color')
GREY_STATE = 'grey-quarantine.json'     # снимок прохода: {owner|sha16: {severity, grey_share, offers}} — тяжесть (candidate/reject) отдельно от БД
SHAPE_HOLD = 'grey-shape-hold.json'     # удержание болванок: ключи «<sku_>/<job>»; читает ТОЛЬКО прополка (`salad/prune_shapes.py`)
GREY = 'grey_top'
# «решения», которые решениями НЕ считаются: автоснятие по замеру (v1 → v2, чистый детектор). Владельческие accept/reject/cut — терминальны для файла
NON_DECISIONS = ('auto_release_v2', 'auto_release_grey')
BAD_GREY = ('candidate', 'reject')
DECIDED_SQL = f"select sku, glb_sha from mesh_quarantine where decision is not null and decision not in {NON_DECISIONS}"


def grey_units(rows: dict, glb_of: dict | None = None) -> dict:
    """Строки сторожа цвета (`current.json: rows`, поле `grey_top` есть только у candidate/reject после снятия «серый товар») → {(owner, sha16): {severity, grey_share, offers, glb}}.
    owner — чей меш (представитель у варианта семьи), sha16 — из `asset_id` («sha256:…»), как `asset_revisions.glb_sha`. Тяжесть — худшая по строкам. Чистая функция."""
    glb_of = glb_of or {}
    out: dict = {}
    for sku, r in sorted(rows.items()):
        g = r.get('grey_top') or {}
        sha = str(r.get('asset_id') or '').removeprefix('sha256:')[:16]
        if g.get('verdict') not in BAD_GREY or not sha:
            continue
        u = out.setdefault((r.get('owner') or sku, sha), {'severity': g['verdict'], 'grey_share': g.get('grey_share'), 'offers': [], 'glb': None})
        if g['verdict'] == 'reject':
            u['severity'] = 'reject'
        u['offers'].append(sku)
        u['glb'] = u['glb'] or glb_of.get(sku)
    return out


def seen_units(rows: dict) -> set:
    """Все (owner, sha16), которые детектор ОЦЕНИЛ в этом проходе (любая строка таблицы с asset_id), — снимать мягкую строку можно только у них."""
    return {(r.get('owner') or sku, str(r['asset_id']).removeprefix('sha256:')[:16]) for sku, r in rows.items() if r.get('asset_id')}


def plan_grey(units: dict, mq: dict, rev: dict, detector_ran: bool = True, seen: set | None = None) -> dict:
    """Что сделать с таблицей карантина. `mq` — {(sku, sha16): {decision, reasons, prev}} (decision '' = нет), `rev` — {(sku, sha16): статус ревизии}.
      insert  — нет строки: мягкая строка (причина `grey_top`, статус ревизии не трогаем);
      reopen  — строка с `auto_release_v2/auto_release_grey` на ТОТ ЖЕ GLB: автоснятие решением не считается, строка снова мягкая;
      blocked — решение владельца (accept/reject/cut) на этот GLB: не трогаем (терминально для файла; новый GLB — новая строка);
      hard    — строка без решения с другими причинами (ось/маска/подложка/тёмная): остаётся жёсткой, `grey_top` ей не добавляем;
      clear   — мягкая строка, которую детектор оценил и больше не держит (фото совпало, правила уточнены): автоснятие. Только если проход детектора шёл (`detector_ran`) и мешом
                из `seen` (оценён в таблице сторожа); мешов, которых в таблице нет (не в привязке), не трогаем — «не оценён» ≠ «чист». Новый GLB — другой ключ: старая строка
                остаётся историей (она и так не влияет — решение по прежнему GLB).
    Чистая функция: → словарь списков. Статус ревизии не меняет ни одна ветка — возврат из `quarantine` делает общее правило `RESTORE_SQL`."""
    out: dict = {'insert': [], 'reopen': [], 'blocked': [], 'hard': [], 'clear': [], 'soft': []}
    for (sku, sha), u in sorted(units.items()):
        row = mq.get((sku, sha))
        if row is None:
            prev = rev.get((sku, sha))
            out['insert'].append((sku, sha, prev if prev and prev != 'quarantine' else 'generated'))
        elif row['decision'] in NON_DECISIONS:
            out['reopen'].append((sku, sha))
        elif row['decision']:
            out['blocked'].append((sku, sha, row['decision']))
        elif row['reasons'] == GREY:
            out['soft'].append((sku, sha))
        else:
            out['hard'].append((sku, sha, row['reasons']))
    if detector_ran:
        for (sku, sha), row in sorted(mq.items()):
            if (sku, sha) not in units and (seen is None or (sku, sha) in seen) and not row['decision'] and row['reasons'] == GREY:
                out['clear'].append((sku, sha))
    return out


def hold_keys(units: dict, mq: dict, has_shape_file) -> list:
    """Какие болванки держать от прополки: все НЕРЕШЁННЫЕ помеченные меши ТЕКУЩЕГО поколения (candidate и reject), у которых лежит `shape.glb`.
    Ключ «<sku_>/<job>» — как `prune_shapes.key`. Не через `redo` (оно запрещает товар банку, `bank_ready.py`). Новое поколение — другой job → ключ
    не повторяется и держание снимается само; решение владельца (accept/reject/cut) на этот GLB — тоже снимает. `has_shape_file(glb)` — есть ли рядом болванка."""
    out = set()
    for (sku, sha), u in units.items():
        d = (mq.get((sku, sha)) or {}).get('decision') or ''
        if d and d not in NON_DECISIONS:
            continue
        glb = u.get('glb')
        if glb and has_shape_file(glb):
            out.add('/'.join(os.path.normpath(os.path.dirname(glb)).split(os.sep)[-2:]))
    return sorted(out)


def soft_cond() -> str:
    import room_bindings as RB
    return RB.soft_sql()


# Общее правило: ревизия в `quarantine` ТОЛЬКО из-за мягкой причины (строка без решения, причины целиком из `soft_reasons`) возвращается в прежний статус.
# Подзапрос с неполными именами (decision/reasons — колонки `mesh_quarantine`), чтобы не путать с колонками `asset_revisions`
def restore_sql() -> str:
    return ("update asset_revisions r set status = mq.prev_status, updated = now() from mesh_quarantine mq "
            "where r.sku = mq.sku and r.glb_sha = mq.glb_sha and r.status = 'quarantine' and mq.prev_status in ('accepted','generated') "
            f"and (mq.sku, mq.glb_sha) in (select sku, glb_sha from mesh_quarantine where {soft_cond()});")


def grey_sql(plan: dict, units: dict, thr: float) -> list:
    """SQL по плану — по транзакции на ~100 строк; ни одна не трогает `asset_revisions` и `mesh_decisions` (кроме общего возврата `restore_sql`, он первым)."""
    from mesh_queue import q
    out = [restore_sql()]

    def batch(stmts):
        for i in range(0, len(stmts), 100):
            out.append('begin;\n' + '\n'.join(stmts[i:i + 100]) + '\ncommit;')
    batch([f"insert into mesh_quarantine (sku, glb_sha, prev_status, axis, threshold, reasons, metric_version) values ({q(s)}, {q(h)}, {q(p)}, "
           f"{q('grey:' + units[(s, h)]['severity'])}, {thr}, '{GREY}', 2) on conflict (sku, glb_sha) do nothing;" for s, h, p in plan['insert']])
    batch([f"update mesh_quarantine set decision = null, decided_at = null, reasons = '{GREY}', axis = {q('grey:' + units[(s, h)]['severity'])} "
           f"where sku = {q(s)} and glb_sha = {q(h)} and decision in {NON_DECISIONS};" for s, h in plan['reopen']])
    batch([f"update mesh_quarantine set axis = {q('grey:' + units[(s, h)]['severity'])} where sku = {q(s)} and glb_sha = {q(h)} and decision is null and reasons = '{GREY}';"
           for s, h in plan['soft']])
    batch([f"update mesh_quarantine set decision = 'auto_release_grey', decided_at = now() where sku = {q(s)} and glb_sha = {q(h)} and decision is null and reasons = '{GREY}';"
           for s, h in plan['clear']])
    return out


def sync_grey(dry: bool = False) -> int:
    """Ночной шаг (после `mesh_color_guard`, до `room_bindings`): мягкий карантин «серая крышка» по ВСЕМ мешам детектора + удержание болванок.
    `--dry` — только чтение базы и печать (SQL не выполняется, файлы не пишутся)."""
    import datetime
    import mesh_color_check as MCC
    from mesh_queue import db
    path = os.path.join(MC_DIR, MCC.TABLE)
    try:
        T = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError) as e:
        print(f'WARN:серая крышка: таблицы сторожа нет ({type(e).__name__}) — карантин не менялся', flush=True)
        return 0
    counts = T.get('counts') or {}
    ran = 'grey_top_reject' in counts
    glb_of = {}
    try:
        snap = json.load(open(MCC.BINDINGS, encoding='utf-8'))
        if snap.get('content_sha') == T.get('bindings_sha'):
            glb_of = {p['sku']: p['glb'] for p in MCC.pairs_of(snap)}
        else:
            print('WARN:серая крышка: привязка в таблице сторожа и текущая разные — болванки сегодня не пересчитываю', flush=True)
    except (OSError, ValueError) as e:
        print(f'WARN:серая крышка: привязка не прочитана ({type(e).__name__}) — болванки сегодня не пересчитываю', flush=True)
    units = grey_units(T.get('rows') or {}, glb_of)
    mq = {}
    for r in db("select sku, glb_sha, coalesce(decision,''), coalesce(reasons,''), prev_status from mesh_quarantine"):
        if len(r) >= 5:
            mq[(r[0], r[1])] = {'decision': r[2], 'reasons': r[3], 'prev': r[4]}
    owners = sorted({s for s, _ in units})
    rev = {}
    if owners:
        inl = ','.join("'" + o.replace("'", "''") + "'" for o in owners)
        for r in db(f"select distinct on (sku, glb_sha) sku, glb_sha, status from asset_revisions where glb_sha is not null and sku in ({inl}) order by sku, glb_sha, updated desc"):
            if len(r) >= 3:
                rev[(r[0], r[1])] = r[2]
    plan = plan_grey(units, mq, rev, detector_ran=ran and bool(units), seen=seen_units(T.get('rows') or {}))
    hold = hold_keys(units, mq, lambda g: os.path.isfile(os.path.join(os.path.dirname(g), 'shape.glb'))) if glb_of else None
    sev = {k: sum(1 for u in units.values() if u['severity'] == k) for k in BAD_GREY}
    print(f'серая крышка (мягкий карантин): уникальных мешей {len(units)} (отказ {sev["reject"]}, на проверку {sev["candidate"]}; строк сторожа '
          f'{sum(len(u["offers"]) for u in units.values())}); новых строк {len(plan["insert"])}, снято автоснятие {len(plan["reopen"])}, '
          f'уже мягких {len(plan["soft"])}, решение владельца {len(plan["blocked"])}, жёсткие по другим причинам {len(plan["hard"])}, '
          f'снимается (детектор не держит) {len(plan["clear"])}'
          + (f'; болванок под удержанием {len(hold)}' if hold is not None else '; болванки не пересчитаны'), flush=True)
    sqls = grey_sql(plan, units, threshold())
    if dry:
        print(f'СУХО: SQL не выполняется ({len(sqls)} блоков; первый — общий возврат ревизий из quarantine)', flush=True)
        return 0
    for s in sqls:
        db(s)
    state = {'built_at': datetime.datetime.now().isoformat(timespec='seconds'), 'bindings_sha': T.get('bindings_sha'),
             'units': {f'{s}|{h}': {'severity': u['severity'], 'grey_share': u['grey_share'], 'offers': len(u['offers'])} for (s, h), u in units.items()}}
    MCC._atomic_json(os.path.join(MC_DIR, GREY_STATE), state)
    if hold is not None:
        MCC._atomic_json(os.path.join(MC_DIR, SHAPE_HOLD), {'built_at': state['built_at'], 'bindings_sha': T.get('bindings_sha'), 'keys': hold})
    return 0


def apply(limit: int = 0) -> int:
    import mesh_axes as MA
    import mesh_dims as MD
    from mesh_queue import db, q
    thr = threshold()
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    items = MD.rows(MA.ROLES)
    key = lambda it: 'v2:' + it['glb_sha'][:16]  # noqa: E731 — замер v2 считается заново (кэш v1 не годится)
    todo = [it for it in items if it['glb_sha'] and key(it) not in cache][: limit or None]
    print(f'готовых моделей с паспортом {len(items)}, замерить (v2) {len(todo)}', flush=True)

    def one(it):
        glb = MD.find_glb(it['sku'], it['glb_sha'])
        if not glb:
            return key(it), {}
        raw = MD.raw_measure(glb)
        dev = MA.deviation2(raw, it['w'], it['d'], it['h']) if raw else None
        out = dict(dev or {})
        if raw and raw.get('slab'):
            out['slab'] = raw['slab']
        mk = MD.mask_flag(glb)
        if mk:
            out['mask'] = mk
        return key(it), out

    # ТЁМНАЯ МОДЕЛЬ (demo-05 15.10): свой кэш — замер новый, а v2-замеры пересчитывать не нужно
    import mesh_dark as MDK
    dkey = lambda it: 'dark2:' + it['glb_sha'][:16]  # noqa: E731 — v2 правила (15.10): светлое название + тёмная модель
    dtodo = [it for it in items if it['glb_sha'] and dkey(it) not in cache][: limit or None]

    def dark_one(it):
        glb = MD.find_glb(it['sku'], it['glb_sha'])
        if not glb:
            return dkey(it), None
        try:
            return dkey(it), MDK.measure(glb, it.get('name') or '')
        except Exception as e:  # noqa: BLE001 — модель не открылась: считаем, печатаем, не глотаем молча
            print(f'  dark: {it["sku"]} не замерена ({str(e)[:60]})', flush=True)
            return dkey(it), None

    # СЕРАЯ КРЫШКА здесь больше не меряется и не пишется: её ведёт `sync_grey` (все меши детектора, МЯГКИЙ карантин; T-20261119-101/3)

    done = 0
    with ThreadPoolExecutor(3) as ex:
        for k, dev in ex.map(one, todo):
            cache[k] = dev
            done += 1
            if done % 100 == 0:                       # кэш по ходу: долгий прогон не теряется при обрыве
                json.dump(cache, open(CACHE, 'w'))
                print(f'  замерено {done}/{len(todo)}', flush=True)
    print(f'замерить тёмные модели {len(dtodo)}', flush=True)
    # по одной: модель с текстурой 2048² в памяти ~0,5 ГБ, три потока на DEV снимал сторож памяти (15.10)
    for n, it in enumerate(dtodo, 1):
        k, v = dark_one(it)
        cache[k] = v
        if n % 50 == 0:                        # кэш по ходу: обрыв не теряет замеренное
            json.dump(cache, open(CACHE, 'w'))
            print(f'  тёмные: замерено {n}/{len(dtodo)}', flush=True)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(cache, open(CACHE, 'w'))
    # решением владельца считается accept/reject/cut; автоснятие замера (`auto_release_*`) — НЕТ: оно блокировало новые признаки на тот же GLB навсегда (Харис/Мелтон 19.11)
    decided = {(r[0], r[1]) for r in db(DECIDED_SQL) if len(r) == 2}
    measures = [{'sku': it['sku'], 'glb_sha': it['glb_sha'][:16], **cache.get(key(it), {}),
                 **({'dark': cache[dkey(it)]} if cache.get(dkey(it)) is not None else {})} for it in items]
    flagged = {(m['sku'], m['glb_sha']): m for m in pick(measures, thr, decided)}
    # НЕРЕШЁННЫЕ ПО v1, КОТОРЫХ v2 НЕ ДЕРЖИТ, — вернуть в работу (ложная тревога замера v1)
    released = 0
    for r in db("select sku, glb_sha from mesh_quarantine where decision is null and metric_version = 1"):
        if len(r) == 2 and (r[0], r[1]) not in flagged:
            db(f"""begin;
update asset_revisions r set status = mq.prev_status, updated = now() from mesh_quarantine mq
 where mq.sku = {q(r[0])} and mq.glb_sha = {q(r[1])} and r.sku = mq.sku and r.glb_sha = mq.glb_sha and r.status = 'quarantine';
update mesh_quarantine set decision = 'auto_release_v2', decided_at = now() where sku = {q(r[0])} and glb_sha = {q(r[1])};
commit;""")
            released += 1
    for (sku, sha), m in flagged.items():
        rs = ','.join(reasons(m, thr))
        db(f"""begin;
insert into mesh_quarantine (sku, glb_sha, prev_status, axis, dev, dw, dd, threshold, reasons, metric_version, slab, mask)
select r.sku, r.glb_sha, r.status, {q(m.get('axis', ''))}, {m.get('max_dev') if m.get('max_dev') is not None else 'null'},
       {m.get('dl', 'null')}, {m.get('ds', 'null')}, {thr}, {q(rs)}, 2, {q(m.get('slab')) if m.get('slab') else 'null'},
       {q(m.get('mask')) if m.get('mask') else 'null'}
  from asset_revisions r where r.sku = {q(sku)} and r.glb_sha = {q(sha)} and r.status in ('accepted','generated','quarantine')
on conflict (sku, glb_sha) do update set reasons = excluded.reasons || case when coalesce(mesh_quarantine.reasons,'') like '%{GREY}%' then ',{GREY}' else '' end, metric_version = 2, slab = excluded.slab,
       mask = excluded.mask, dev = excluded.dev, dw = excluded.dw, dd = excluded.dd, axis = excluded.axis, threshold = excluded.threshold;
update asset_revisions set status = 'quarantine', updated = now()
 where sku = {q(sku)} and glb_sha = {q(sha)} and status in ('accepted','generated');
commit;""")
    total = db("select count(*) from mesh_quarantine where decision is null or decision = 'cut'")
    print(f'v2: в карантине {len(flagged)} (без решения владельца), возвращено из v1 {released}; ждут решения {total[0][0] if total else "?"}', flush=True)
    return 0


def pull() -> int:
    from mesh_queue import db, q
    after = int(open(CURSOR).read().strip() or 0) if os.path.exists(CURSOR) else 0
    with urllib.request.urlopen(f'{SITE}/api/lab/review?kind=quarantine&after={after}', timeout=30) as r:
        rows = json.loads(r.read()).get('rows', [])
    for row in rows:
        sku, _, sha = row['itemKey'].partition('|')
        v, c = row['verdict'], (row.get('comment') or '')[:300]
        status = {'accept': 'mq.prev_status', 'reject': "'owner_reject'", 'cut': "'quarantine'"}[v]
        db(f"""begin;
update asset_revisions r set status = {status}, updated = now() from mesh_quarantine mq
 where mq.sku = {q(sku)} and mq.glb_sha = {q(sha)} and r.sku = mq.sku and r.glb_sha = mq.glb_sha;
update mesh_quarantine set decision = {q(v)}, comment = {q(c)}, decided_at = now() where sku = {q(sku)} and glb_sha = {q(sha)};
commit;""")
        after = max(after, int(row['id']))
    open(CURSOR, 'w').write(str(after))
    print(f'решений владельца забрано: {len(rows)}', flush=True)
    return 0


REASON_TEXT = {'mask': 'фото товара — коллаж (надписи, вставки): проверьте, не попали ли они в модель', 'slab': 'под предметом «подложка» — кусок фона на полу',
               'proportion': 'сильно искажены пропорции (после растяжки под паспорт будет заметно)',
               'grey_top': 'верх (столешница) — пустой серый фон генерации, а не цвет товара: на странице и в кадре стол выходит с серой крышкой'}
IMGDIR = os.path.expanduser('~/scout-scenes/mesh-quarantine-img')


def page(publish: bool) -> int:
    """Страница v2 (14.10): фото товара, вырезка, по которой делалась модель, и вид модели спереди — сразу, без кнопок;
    подпись — настоящая причина. Сверху — ждущие решения; решённые владельцем — ниже, с его отметкой."""
    import mesh_dims as MD
    from mesh_queue import db
    # ТОВАРЫ КОМНАТ (T-20261106-82/2): меши спальни и прихожей лежат в `room_catalog`, не в `products` — прежний `join products`
    # прятал их брак от владельца. Карточка — из `products`, иначе из `room_catalog` (первая комната по имени); нет ни там, ни там —
    # не показываем, как раньше.
    rows = db("""select mq.sku, mq.glb_sha, coalesce(mq.reasons,''), coalesce(mq.decision,''), coalesce(mq.mask,''),
                        coalesce(mq.dev::text,''), coalesce(p.name, rc.name, mq.sku), coalesce(p.cat_role, rc.role, '—'),
                        coalesce(""" + MP.photo_sql('p') + """, rc.img, ''),
                        coalesce(coalesce(p.w_cm, rc.w_cm)::text, '?'), coalesce(coalesce(p.d_cm, rc.d_cm)::text, '?'), coalesce(coalesce(p.h_cm, rc.h_cm)::text, '?')
                   from mesh_quarantine mq
                   left join products p on p.shop_mid||':'||p.external_id = mq.sku
                   left join lateral (select r.name, r.role, """ + MP.photo_sql('r') + """ as img, r.w_cm, r.d_cm, r.h_cm
                                        from room_catalog r where r.shop_mid||':'||r.external_id = mq.sku
                                       order by r.room limit 1) rc on p.external_id is null
                  where coalesce(mq.decision,'') not in ('auto_release_v2', 'auto_release_grey')
                    and (p.external_id is not null or rc.name is not null or coalesce(mq.reasons,'') like '%grey_top%')   -- серая крышка идёт и по мешам без товара/комнаты (T-20261119-101/3)
                  order by (mq.decision is null) desc, mq.reasons""")
    os.makedirs(IMGDIR, exist_ok=True)
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    slab_of = {f'{r[0]}|{r[1]}': (cache.get('v2:' + r[1]) or {}).get('slab') for r in rows if len(r) >= 2}
    try:
        grey_state = json.load(open(os.path.join(MC_DIR, GREY_STATE), encoding='utf-8')).get('units') or {}
    except (OSError, ValueError):
        grey_state = {}
    cards = []
    for r in rows:
        if len(r) < 12:
            continue
        sku, sha, rs, dec, mask, dev, name, role, img, w, d, h = r
        key = f'{sku}|{sha}'
        k = sku.replace(':', '_', 1) + '_' + sha
        front, cut = os.path.join(IMGDIR, k + '.front.png'), os.path.join(IMGDIR, k + '.cut.png')
        if not os.path.exists(front) or not os.path.exists(cut):
            glb = MD.find_glb(sku, sha) if len(sha) == 64 else None
            if glb is None:
                import glob as _g
                import hashlib as _h
                for f in _g.glob(os.path.join(MD.MESH_DIR, sku.replace(':', '_', 1), '*', 'model.glb')):
                    if _h.sha256(open(f, 'rb').read()).hexdigest().startswith(sha):
                        glb = f
            if glb:
                if not os.path.exists(front):
                    subprocess.run([sys.executable, '-c', f'import sys; sys.path[:0]=[{HERE!r},{os.path.join(HERE, "salad")!r}]; '
                                    f'import topview_render as T; T.render_front({glb!r},0,{front!r})'], check=False, timeout=300)
                cp = os.path.join(os.path.dirname(glb), 'cutout.png')
                if os.path.exists(cp) and not os.path.exists(cut):
                    from PIL import Image
                    im = Image.open(cp)
                    im.thumbnail((400, 400))
                    im.save(cut)
        why = [REASON_TEXT[x] for x in rs.split(',') if x in REASON_TEXT] or (['решено вами по замеру v1'] if dec else ['замер v1'])
        gu = grey_state.get(f'{sku}|{sha}')
        if gu:     # снимок детектора: тяжесть и доля серого (подпись у карточек без товара в каталоге)
            why.append(f'детектор: {"отказ" if gu["severity"] == "reject" else "на проверку"}, серого на верху {round(100 * float(gu.get("grey_share") or 0))} % '
                       f'(предметов в лентах и вариантах семьи: {gu.get("offers")}); модель остаётся, пока нет замены, — решение владельца главнее')
        if mask:
            why.append('конвейер записал: ' + mask)
        if dec == 'accept' and slab_of.get(key):
            why.append('вы приняли, но новый замер видит подложку — проверьте ещё раз')
        cards.append(
            f'<div class=c data-key="{html.escape(key)}"><div class=r>'
            f'<figure><img loading=lazy src="{html.escape(img)}" alt=""><figcaption>фото товара</figcaption></figure>'
            f'<figure><img loading=lazy src="img/{k}.cut.png" alt=""><figcaption>вырезка (вход модели)</figcaption></figure>'
            f'<figure><img loading=lazy src="img/{k}.front.png" alt=""><figcaption>модель спереди</figcaption></figure></div>'
            f'<div class=t><b>{html.escape(role)}</b> · {html.escape(name[:80])}<br>паспорт {w}×{d}×{h} см<br>'
            + ''.join(f'<span class=bad>• {html.escape(x)}</span><br>' for x in why) + '</div>'
            f'<div class=b>' + ''.join(f'<button data-v={kk}>{t}</button>' for kk, t in VERDICT.items()) +
            f'</div><input class=cm maxlength=300 placeholder="комментарий (необязательно)"><div class=st>'
            f'{"решено: " + VERDICT.get(dec, dec) if dec else ""}</div></div>')
    doc = ('<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'
           '<title>Карантин моделей</title><style>body{font:15px system-ui;margin:16px;background:#faf8f5}'
           '.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:12px}.c{background:#fff;border-radius:10px;padding:10px}'
           '.r{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}figure{margin:0;text-align:center}figure img{width:100%;aspect-ratio:1;object-fit:contain;background:#f4f2ee;border-radius:8px}'
           'figcaption{font-size:12px;color:#777}.bad{color:#b3261e}.b{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}'
           'button{padding:8px 10px;border-radius:8px;border:1px solid #ccc;background:#fff;min-height:40px}.on{background:#2b2622;color:#fff}'
           '.cm{width:100%;box-sizing:border-box;padding:6px}.st{color:#777;font-size:13px;margin-top:4px}</style>'
           f'<h1>Карантин моделей — {len(cards)}</h1><p>v2 (14.10): в карантин попадает только то, что видно глазом и не лечится '
           'растяжкой модели под размеры товара: плохая вырезка (фон, надписи), «подложка» под предметом, очень сильное искажение. '
           'Слева фото товара, в центре — вырезка, по которой делалась модель, справа — модель. «Принять» — вернуть в работу, «брак» — '
           'убрать, «порезать вручную» — оставить до новой модели.</p><div class=g>' + ''.join(cards) +
           '</div><script>document.querySelectorAll(".c").forEach(c=>{'
           'c.querySelectorAll(".b button").forEach(b=>b.onclick=async()=>{const r=await fetch("/api/lab/review",{method:"POST",'
           'headers:{"content-type":"application/json"},body:JSON.stringify({kind:"quarantine",key:c.dataset.key,verdict:b.dataset.v,'
           'comment:c.querySelector(".cm").value||undefined})});c.querySelectorAll(".b button").forEach(x=>x.classList.remove("on"));'
           'if(r.ok){b.classList.add("on");c.querySelector(".st").textContent="сохранено: "+b.textContent;}else{c.querySelector(".st").textContent="не сохранилось, нажмите ещё раз";}});});'
           'fetch("/api/lab/review?kind=quarantine&after=0").then(r=>r.json()).then(j=>{const last={};(j.rows||[]).forEach(x=>last[x.itemKey]=x);document.querySelectorAll(".c").forEach(c=>{const x=last[c.dataset.key];if(!x)return;c.querySelectorAll(".b button").forEach(b=>{if(b.dataset.v===x.verdict)b.classList.add("on");});if(x.comment)c.querySelector(".cm").value=x.comment;c.querySelector(".st").textContent="отмечено раньше";});});</script>')
    os.makedirs(os.path.dirname(PAGE), exist_ok=True)
    open(PAGE, 'w', encoding='utf-8').write(doc)
    print(f'страница: {PAGE} ({len(cards)} моделей)')
    if publish:
        subprocess.run(['bash', '-c', 'ssh -p 22222 root@89.167.127.0 "mkdir -p /opt/remlab/test/mesh-quarantine/img" && '
                        f'scp -q -P 22222 "{PAGE}" root@89.167.127.0:/opt/remlab/test/mesh-quarantine/index.html && '
                        f'rsync -a -e "ssh -p 22222" {IMGDIR}/ root@89.167.127.0:/opt/remlab/test/mesh-quarantine/img/'], check=False, timeout=900)
        print(f'{SITE}/test/mesh-quarantine/')
    return 0


def _selftest() -> int:
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp (T-20261107-13)
    remlab_tmp.use('mesh_quarantine-selftest')
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    ms = [{'sku': 'a', 'glb_sha': '1', 'max_dev': 0.30}, {'sku': 'b', 'glb_sha': '2', 'max_dev': 0.20},
          {'sku': 'c', 'glb_sha': '3', 'max_dev': 0.40}, {'sku': 'd', 'glb_sha': '4'}]
    ok('выше порога 25 % — в карантин, ниже — нет, без замера — нет', [m['sku'] for m in pick(ms, 0.25, set())] == ['a', 'c'])
    ok('решённое владельцем повторно не попадает', [m['sku'] for m in pick(ms, 0.25, {('c', '3')})] == ['a'])
    ok('порог пропорций из правил: выключен (владелец принимает искажения — их лечит растяжка)', threshold() >= 9)
    ok('v2: плохая вырезка и подложка — карантин независимо от пропорций',
       reasons({'mask': 'коллаж', 'slab': 'merged', 'max_dev': 0.1}, 0.6) == ['mask', 'slab'])
    ok('v2: умеренное расхождение без признаков — не карантин', reasons({'max_dev': 0.4}, 0.6) == [])
    ok('тёмная модель светлого товара — карантин «dark»', reasons({'dark': 11.0}, 0.6) == ['dark'])
    ok('серая крышка: candidate и reject — карантин «grey_top», ok/na — нет; независимо от пропорций',
       reasons({'grey_top': 'reject'}, 0.6) == ['grey_top'] and reasons({'grey_top': 'candidate', 'max_dev': 0.1}, 0.6) == ['grey_top']
       and reasons({'grey_top': 'ok'}, 0.6) == [] and reasons({'grey_top': 'na'}, 0.6) == [])
    ok('серая крышка: решённое владельцем («принять») повторно в карантин не возвращается',
       pick([{'sku': 's', 'glb_sha': 'g', 'grey_top': 'reject'}], 0.6, {('s', 'g')}) == [])
    ok('серая крышка: у причины есть текст для страницы', 'grey_top' in REASON_TEXT)
    # новая схема (мягкий карантин по всем мешам детектора, T-20261119-101/3) проверяется целиком в `tests/test_grey_soft.py`
    ok('решением владельца не считается автоснятие замера (auto_release_*): запрос «решённых» их исключает',
       all(n in DECIDED_SQL for n in NON_DECISIONS) and 'not in' in DECIDED_SQL)
    return 1 if bad else 0


if __name__ == '__main__':
    a = sys.argv
    if '--selftest' in a:
        sys.exit(_selftest())
    if '--apply' in a:
        sys.exit(apply(int(a[a.index('--limit') + 1]) if '--limit' in a else 0))
    if '--sync-grey' in a:
        sys.exit(sync_grey(dry='--dry' in a))
    if '--pull' in a:
        sys.exit(pull())
    if '--page' in a:
        sys.exit(page('--publish' in a))
    print(__doc__)
