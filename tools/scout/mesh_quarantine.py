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


def reasons(m: dict, thr: float) -> list:
    """Признаки карантина v2 — независимые (Codex 14.10): плохая вырезка, подложка, сильное искажение. Чистая функция."""
    out = []
    if m.get('mask'):
        out.append('mask')
    if m.get('slab'):
        out.append('slab')
    if m.get('max_dev') is not None and m['max_dev'] > thr:
        out.append('proportion')
    return out


def pick(measures: list[dict], thr: float, decided: set) -> list[dict]:
    """Кого вывести в карантин: есть хоть один признак, модель не решена владельцем. Чистая функция."""
    return [m for m in measures if reasons(m, thr) and (m['sku'], m['glb_sha']) not in decided]


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

    done = 0
    with ThreadPoolExecutor(3) as ex:
        for k, dev in ex.map(one, todo):
            cache[k] = dev
            done += 1
            if done % 100 == 0:                       # кэш по ходу: долгий прогон не теряется при обрыве
                json.dump(cache, open(CACHE, 'w'))
                print(f'  замерено {done}/{len(todo)}', flush=True)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(cache, open(CACHE, 'w'))
    decided = {(r[0], r[1]) for r in db("select sku, glb_sha from mesh_quarantine where decision is not null") if len(r) == 2}
    measures = [{'sku': it['sku'], 'glb_sha': it['glb_sha'][:16], **cache.get(key(it), {})} for it in items]
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
on conflict (sku, glb_sha) do update set reasons = excluded.reasons, metric_version = 2, slab = excluded.slab,
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


REASON_TEXT = {'mask': 'вырезка плохая — в модель попал фон или надписи', 'slab': 'под предметом «подложка» — кусок фона на полу',
               'proportion': 'сильно искажены пропорции (после растяжки под паспорт будет заметно)'}
IMGDIR = os.path.expanduser('~/scout-scenes/mesh-quarantine-img')


def page(publish: bool) -> int:
    """Страница v2 (14.10): фото товара, вырезка, по которой делалась модель, и вид модели спереди — сразу, без кнопок;
    подпись — настоящая причина. Сверху — ждущие решения; решённые владельцем — ниже, с его отметкой."""
    import mesh_dims as MD
    from mesh_queue import db
    rows = db("""select mq.sku, mq.glb_sha, coalesce(mq.reasons,''), coalesce(mq.decision,''), coalesce(mq.mask,''),
                        coalesce(mq.dev::text,''), p.name, p.cat_role, coalesce(p.image_url_hd, p.image_url, ''),
                        coalesce(p.w_cm::text,''), coalesce(p.d_cm::text,''), coalesce(p.h_cm::text,'')
                   from mesh_quarantine mq join products p on p.shop_mid||':'||p.external_id = mq.sku
                  where coalesce(mq.decision,'') not in ('auto_release_v2')
                  order by (mq.decision is null) desc, mq.reasons""")
    os.makedirs(IMGDIR, exist_ok=True)
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
        why = [REASON_TEXT[x] for x in rs.split(',') if x in REASON_TEXT] or ['v1: расхождение размеров (замер v1 ошибочен)']
        if mask:
            why.append('конвейер записал: ' + mask)
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
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    ms = [{'sku': 'a', 'glb_sha': '1', 'max_dev': 0.30}, {'sku': 'b', 'glb_sha': '2', 'max_dev': 0.20},
          {'sku': 'c', 'glb_sha': '3', 'max_dev': 0.40}, {'sku': 'd', 'glb_sha': '4'}]
    ok('выше порога 25 % — в карантин, ниже — нет, без замера — нет', [m['sku'] for m in pick(ms, 0.25, set())] == ['a', 'c'])
    ok('решённое владельцем повторно не попадает', [m['sku'] for m in pick(ms, 0.25, {('c', '3')})] == ['a'])
    ok('порог читается из правил (v2: 60 % — растяжка по осям лечит умеренное)', threshold() == 0.6)
    ok('v2: плохая вырезка и подложка — карантин независимо от пропорций',
       reasons({'mask': 'коллаж', 'slab': 'merged', 'max_dev': 0.1}, 0.6) == ['mask', 'slab'])
    ok('v2: умеренное расхождение без признаков — не карантин', reasons({'max_dev': 0.4}, 0.6) == [])
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
