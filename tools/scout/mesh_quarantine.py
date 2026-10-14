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
RULES = os.path.join(HERE, 'rules', 'mesh-quarantine.json')
CACHE = os.path.expanduser('~/scout-scenes/mesh-axes-cache.json')     # glb_sha → замер (модель не меняется)
CURSOR = os.path.expanduser('~/scout-scenes/mesh-quarantine.cursor')
PAGE = os.path.join(HERE, 'mesh-quarantine-page', 'index.html')
SITE = os.environ.get('REMLAB_SITE', 'https://remont-lab.online')
VERDICT = {'accept': 'принять', 'reject': 'брак', 'cut': 'порезать вручную'}


def threshold() -> float:
    return float(json.load(open(RULES, encoding='utf-8'))['threshold'])


def pick(measures: list[dict], thr: float, decided: set) -> list[dict]:
    """Кого вывести в карантин: отклонение > порога, модель не решена владельцем. Чистая функция."""
    return [m for m in measures if m.get('max_dev') is not None and m['max_dev'] > thr
            and (m['sku'], m['glb_sha']) not in decided]


def apply(limit: int = 0) -> int:
    import mesh_axes as MA
    import mesh_dims as MD
    from mesh_queue import db, q
    thr = threshold()
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    items = MD.rows(MA.ROLES)
    todo = [it for it in items if it['glb_sha'] and it['glb_sha'][:16] not in cache][: limit or None]
    print(f'готовых моделей с паспортом {len(items)}, замерить новых {len(todo)}', flush=True)

    def one(it):
        glb = MD.find_glb(it['sku'], it['glb_sha'])
        ex = MD.extents(glb, it['resolution']['R']) if glb else None
        dev = MA.deviation(ex, it['w'], it['d'], it['h']) if ex and min(ex) > 0 else None
        return it['glb_sha'][:16], (dev or {})

    with ThreadPoolExecutor(3) as ex:
        for sha, dev in ex.map(one, todo):
            cache[sha] = dev
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(cache, open(CACHE, 'w'))
    decided = {(r[0], r[1]) for r in db('select sku, glb_sha from mesh_quarantine') if len(r) == 2}
    measures = [{'sku': it['sku'], 'glb_sha': it['glb_sha'][:16], **cache.get(it['glb_sha'][:16], {})} for it in items]
    new = pick(measures, thr, decided)
    for m in new:
        db(f"""begin;
insert into mesh_quarantine (sku, glb_sha, prev_status, axis, dev, dw, dd, threshold)
select r.sku, r.glb_sha, r.status, {q(m.get('axis', ''))}, {m['max_dev']}, {m.get('dw', 'null')}, {m.get('dd', 'null')}, {thr}
  from asset_revisions r where r.sku = {q(m['sku'])} and r.glb_sha = {q(m['glb_sha'])} and r.status in ('accepted','generated')
on conflict do nothing;
update asset_revisions set status = 'quarantine', updated = now()
 where sku = {q(m['sku'])} and glb_sha = {q(m['glb_sha'])} and status in ('accepted','generated');
commit;""")
    total = db("select count(*) from mesh_quarantine where coalesce(decision,'cut') = 'cut'")
    print(f'порог {thr:.0%}: в карантин сейчас {len(new)}, всего в карантине {total[0][0] if total else "?"}', flush=True)
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


def page(publish: bool) -> int:
    from mesh_queue import db
    rows = db("""select mq.sku, mq.glb_sha, mq.axis, mq.dev, mq.dw, mq.dd, coalesce(mq.decision,''), p.name, p.cat_role,
                        coalesce(p.image_url_hd, p.image_url, ''), coalesce(p.w_cm::text,''), coalesce(p.d_cm::text,''),
                        coalesce(p.h_cm::text,''), coalesce(p.mesh_family_rep, mq.sku)
                   from mesh_quarantine mq join products p on p.shop_mid||':'||p.external_id = mq.sku
                  order by (mq.decision is null) desc, mq.dev desc""")
    cards = []
    for r in rows:
        if len(r) < 14:
            continue
        sku, sha, axis, dev, dw, dd, dec, name, role, img, w, d, h, rep = r
        glb = f"/test/mesh-pilot10/{rep.replace(':', '_', 1)}/model.glb"
        key = f'{sku}|{sha}'
        sign = 'больше' if float((dw if axis == 'ширина' else dd) or 0) > 0 else 'меньше'
        cards.append(
            f'<div class=c data-key="{html.escape(key)}"><div class=ph><img loading=lazy src="{html.escape(img)}" alt=""></div>'
            f'<div class=t><b>{html.escape(role)}</b> · {html.escape(name[:80])}<br>паспорт {w}×{d}×{h} см · '
            f'<span class=bad>{html.escape(axis)} модели {sign} на {float(dev):.0%}</span></div>'
            f'<button class=v3 data-glb="{glb}">посмотреть 3D</button><div class=mv></div>'
            f'<div class=b>' + ''.join(f'<button data-v={k}>{t}</button>' for k, t in VERDICT.items()) +
            f'</div><input class=cm maxlength=300 placeholder="комментарий (необязательно)"><div class=st>'
            f'{"решено: " + VERDICT.get(dec, dec) if dec else ""}</div></div>')
    doc = ('<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'
           '<title>Карантин моделей</title><style>body{font:15px system-ui;margin:16px;background:#faf8f5}'
           '.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}.c{background:#fff;border-radius:10px;padding:10px}'
           '.ph img{width:100%;aspect-ratio:1;object-fit:contain}.bad{color:#b3261e}.b{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}'
           'button{padding:8px 10px;border-radius:8px;border:1px solid #ccc;background:#fff;min-height:40px}.on{background:#2b2622;color:#fff}'
           '.cm{width:100%;box-sizing:border-box;padding:6px}.st{color:#777;font-size:13px;margin-top:4px}model-viewer{width:100%;height:240px}</style>'
           f'<h1>Карантин моделей — {len(cards)}</h1><p>Модель расходится с размерами товара больше чем на '
           f'{threshold():.0%} по ширине или глубине. «Принять» — вернуть в работу, «брак» — убрать, «порезать вручную» — '
           'оставить в карантине до новой модели. Комментарий сохраняется вместе с нажатием.</p><div class=g>' + ''.join(cards) +
           '</div><script type=module src="https://cdn.jsdelivr.net/npm/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>'
           '<script>document.querySelectorAll(".c").forEach(c=>{c.querySelector(".v3").onclick=e=>{const g=e.target.dataset.glb;'
           'c.querySelector(".mv").innerHTML=`<model-viewer src="${g}" camera-controls auto-rotate></model-viewer>`;};'
           'c.querySelectorAll(".b button").forEach(b=>b.onclick=async()=>{const r=await fetch("/api/lab/review",{method:"POST",'
           'headers:{"content-type":"application/json"},body:JSON.stringify({kind:"quarantine",key:c.dataset.key,verdict:b.dataset.v,'
           'comment:c.querySelector(".cm").value||undefined})});c.querySelectorAll(".b button").forEach(x=>x.classList.remove("on"));'
           'if(r.ok){b.classList.add("on");c.querySelector(".st").textContent="сохранено: "+b.textContent;}else{c.querySelector(".st").textContent="не сохранилось, нажмите ещё раз";}});});' + 'fetch("/api/lab/review?kind=quarantine&after=0").then(r=>r.json()).then(j=>{const last={};(j.rows||[]).forEach(x=>last[x.itemKey]=x);document.querySelectorAll(".c").forEach(c=>{const x=last[c.dataset.key];if(!x)return;c.querySelectorAll(".b button").forEach(b=>{if(b.dataset.v===x.verdict)b.classList.add("on");});if(x.comment)c.querySelector(".cm").value=x.comment;c.querySelector(".st").textContent="отмечено раньше";});});' + '</script>')
    os.makedirs(os.path.dirname(PAGE), exist_ok=True)
    open(PAGE, 'w', encoding='utf-8').write(doc)
    print(f'страница: {PAGE} ({len(cards)} моделей)')
    if publish:
        subprocess.run(['bash', '-c', 'ssh -p 22222 root@89.167.127.0 "mkdir -p /opt/remlab/test/mesh-quarantine" && '
                        f'scp -q -P 22222 "{PAGE}" root@89.167.127.0:/opt/remlab/test/mesh-quarantine/index.html'], check=False, timeout=120)
        print(f'{SITE}/test/mesh-quarantine/')
    return 0


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    ms = [{'sku': 'a', 'glb_sha': '1', 'max_dev': 0.30}, {'sku': 'b', 'glb_sha': '2', 'max_dev': 0.20},
          {'sku': 'c', 'glb_sha': '3', 'max_dev': 0.40}, {'sku': 'd', 'glb_sha': '4'}]
    ok('выше порога 25 % — в карантин, ниже — нет, без замера — нет', [m['sku'] for m in pick(ms, 0.25, set())] == ['a', 'c'])
    ok('решённое владельцем повторно не попадает', [m['sku'] for m in pick(ms, 0.25, {('c', '3')})] == ['a'])
    ok('порог читается из правил', threshold() == 0.25)
    return 1 if bad else 0


if __name__ == '__main__':
    a = sys.argv
    if '--selftest' in a:
        sys.exit(_selftest())
    if '--apply' in a:
        sys.exit(apply(int(a[a.index('--limit') + 1]) if '--limit' in a else 0))
    if '--pull' in a:
        sys.exit(pull())
    if '--page' in a:
        sys.exit(page('--publish' in a))
    print(__doc__)
