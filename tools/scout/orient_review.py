#!/usr/bin/env python3
"""Расхождения разворота «база ↔ прод» — на решение владельцу (планы flat3d-sims-ux A1/A2, conv-06; разбор Codex 14.10).

ЗАЧЕМ. На проде у 551 из 745 моделей нет записи разворота (`orient.json`), хотя в базе решение посчитано. Публиковать
решения базы массово НЕЛЬЗЯ: пробная партия 14.10 — у 25 моделей, где надёжное решение базы (`auto_resolved`, файл тот
же) расходится с тем, как модель стоит сейчас, новое лучше примерно у 5 (стулья), а у ~12 хуже (тумбы, комоды, витрины
развернулись бы задом: `legacy_front_yaw` у корпусной мебели ненадёжен, а починка фасада `cabinet_front` сломана).
Поэтому: совпадающие с текущим видом решения не трогаем, РАСХОЖДЕНИЯ — на страницу `/test/orient-review/`: фото товара,
«как сейчас» и «как предлагает база»; владелец жмёт одно из двух; `--pull` применяет выбор в `orient.json` прода
(слиянием, `salad/publish_merge.py`) с пометкой «решено человеком».

  ~/venvs/scout/bin/python orient_review.py --list            # расхождения числом и списком
  ~/venvs/scout/bin/python orient_review.py --page --publish  # отрендерить виды и выложить страницу
  ~/venvs/scout/bin/python orient_review.py --pull            # применить решения владельца
  ~/venvs/scout/bin/python orient_review.py --sync            # опубликовать записи без видимых изменений
  python3 orient_review.py --selftest
"""
import html
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = 'https://remont-lab.online'
PROD = '/opt/remlab/test/mesh-pilot10'
ORIENT_URL = f'{SITE}/test/mesh-pilot10/orient.json'
WORK = os.path.expanduser('~/scout-scenes/orient-review')
CURSOR = os.path.join(WORK, 'cursor')
SSH = ['ssh', '-p', '22222', '-o', 'BatchMode=yes', 'root@89.167.127.0']


def snap(yaw: float) -> float:
    return float(round(float(yaw) / 90.0) * 90 % 360)


def conflicts(sha: dict, prod: dict, rows: list) -> list:
    """Модели, где НАДЁЖНОЕ решение базы для ТОГО ЖЕ файла расходится с тем, как модель стоит сейчас (запись прода или 0
    по умолчанию). Чистая функция (селфтест). rows: (ключ, статус, glb_sha, legacy_front_yaw, источник, роль)."""
    out = []
    for k, status, gsha, legacy, source, role in rows:
        if k not in sha or status != 'auto_resolved' or source == 'symmetric_by_role' or not legacy:
            continue
        if (gsha or '')[:16] != sha[k][:16]:
            continue
        if str((prod.get(k) or {}).get('orient', '')).startswith('human'):
            continue                                   # уже решено человеком — не переспрашиваем
        new, cur = snap(float(legacy)), float((prod.get(k) or {}).get('yaw', 0) or 0)
        if new != cur:
            out.append({'key': k, 'role': role, 'cur': cur, 'new': new})
    return out


def classify(sha: dict, prod: dict, rows: list) -> dict:
    """Состояние разворота каждой опубликованной модели (разбор Codex 14.10): synced — запись на проде есть;
    publishable — надёжное решение совпадает с тем, как модель стоит сейчас (0 по умолчанию), записи нет — можно
    опубликовать без видимых изменений; conflict — надёжное решение расходится (решает владелец); pending — ждёт
    проверки; symmetric — симметричная; unusable — непригодна; sha_mismatch — решение для другого файла; none — решения
    нет. Чистая функция."""
    by: dict = {}
    for r in rows:
        by.setdefault(r[0], []).append(r)
    out = {}
    for k, h in sha.items():
        rs = [r for r in by.get(k, []) if (r[2] or '')[:16] == h[:16]]
        if k in prod and str(prod[k].get('orient', '')).startswith('human'):
            out[k] = 'synced'
            continue
        if not by.get(k):
            out[k] = 'synced' if k in prod else 'none'
            continue
        if not rs:
            out[k] = 'sha_mismatch'
            continue
        _k, status, _g, legacy, source, _role = rs[0][:6]
        if status != 'auto_resolved' and status != 'human_resolved':
            out[k] = 'pending' if status == 'review_pending' else status
        elif source == 'symmetric_by_role':
            out[k] = 'synced' if k in prod else 'symmetric'
        elif not legacy:
            out[k] = 'none'
        else:
            cur = float((prod.get(k) or {}).get('yaw', 0) or 0)
            if snap(float(legacy)) != cur:
                out[k] = 'conflict'
            else:
                out[k] = 'synced' if k in prod else 'publishable'
    return out


def _gather():
    r = subprocess.run(SSH + [f'cd {PROD} && for d in */; do f="${{d}}model.glb"; [ -f "$f" ] && echo "${{d%/}} $(sha256sum "$f" | cut -c1-64)"; done'],
                       capture_output=True, text=True, timeout=900)
    sha = dict(ln.split() for ln in r.stdout.splitlines() if len(ln.split()) == 2)
    prod = json.load(urllib.request.urlopen(ORIENT_URL, timeout=30))
    from mesh_queue import db
    rows = db("select replace(o.sku, ':', '_'), o.status, coalesce(o.resolution->>'glb_sha',''), "
              "coalesce(o.resolution->>'legacy_front_yaw',''), coalesce(o.resolution->>'source',''), coalesce(p.cat_role,''), "
              "coalesce(p.image_url_hd, p.image_url, '') "
              "from orientation_state o left join products p on p.shop_mid||':'||p.external_id = o.sku "
              "where o.revision_key like '%|orient-v1'")
    return sha, prod, [tuple(r) for r in rows if len(r) == 7]


def counts() -> dict:
    """Число моделей по состояниям — для стыка конвейера (`pipeline_map.py`)."""
    sha, prod, rows = _gather()
    c: dict = {}
    for st in classify(sha, prod, rows).values():
        c[st] = c.get(st, 0) + 1
    return c


def sync() -> int:
    """Опубликовать записи, которые НИЧЕГО не меняют на экране: надёжное решение = текущий вид, симметричные (их
    поворот не виден). Слиянием, без потери чужих записей; прод не прочитан — ничего не делаем."""
    sha, prod, rows = _gather()
    st = classify(sha, prod, rows)
    by = {r[0]: r for r in rows if r[0] in sha and (r[2] or '')[:16] == sha[r[0]][:16]}
    upd = {}
    for k, s0 in st.items():
        if s0 == 'publishable':
            upd[k] = {'yaw': snap(float(by[k][3])), 'orient': f'orient-v1:{by[k][1]}:{by[k][4]}:sync', 'role': by[k][5]}
        elif s0 == 'symmetric':
            upd[k] = {'yaw': float((prod.get(k) or {}).get('yaw', 0) or 0), 'orient': 'orient-v1:symmetric:sync', 'role': by[k][5]}
    if upd:
        os.makedirs(WORK, exist_ok=True)
        tmp = os.path.join(WORK, 'orient-sync.json')
        json.dump(upd, open(tmp, 'w'), ensure_ascii=False)
        rc = subprocess.run([sys.executable, os.path.join(HERE, 'salad', 'publish_merge.py'), tmp, ORIENT_URL,
                             f'root@89.167.127.0:{PROD}/orient.json'], timeout=300).returncode
        if rc:
            print('WARN:orient_review: синхронизация не опубликована — прод не прочитан', flush=True)
            return 0
    print(f'разворот: опубликовано записей без видимых изменений {len(upd)}; состояния {dict((v, list(st.values()).count(v)) for v in set(st.values()))}')
    return 0


def collect() -> list:
    sha, prod, rows = _gather()
    photo = {r[0]: r[6] for r in rows}
    out = conflicts(sha, prod, [tuple(r[:6]) for r in rows])
    for it in out:
        it['photo'] = photo.get(it['key'], '')
    return out


def page(publish: bool) -> int:
    sys.path.insert(0, os.path.join(HERE, 'salad'))
    import topview_render as T
    items = collect()
    img = os.path.join(WORK, 'img')
    os.makedirs(img, exist_ok=True)
    cards = []
    for it in items:
        k = it['key']
        d = os.path.join(WORK, 'glb', k)
        os.makedirs(d, exist_ok=True)
        for f in ('model.glb', 'input.png'):
            if not os.path.exists(os.path.join(d, f)):
                subprocess.run(['scp', '-q', '-P', '22222', f'root@89.167.127.0:{PROD}/{k}/{f}', d], check=False, timeout=300)
        for tag in ('cur', 'new'):
            out = os.path.join(img, f'{k}.{tag}.png')
            if not os.path.exists(out) and os.path.exists(os.path.join(d, 'model.glb')):
                # дочерним процессом: trimesh не отдаёт память (урок 391)
                subprocess.run([sys.executable, '-c', f'import sys; sys.path[:0]=[{HERE!r},{os.path.join(HERE, "salad")!r}]; '
                                f'import topview_render as T; T.render_front({os.path.join(d, "model.glb")!r},{it[tag]},{out!r})'],
                               check=False, timeout=300)
        ph = os.path.join(img, f'{k}.photo.png')
        if not os.path.exists(ph) and it.get('photo'):     # фото товара из карточки (у моделей на проде его нет)
            try:
                u = it['photo'] if not it['photo'].startswith('//') else 'https:' + it['photo']
                req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
                from PIL import Image
                import io
                im = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=20).read())).convert('RGB')
                im.thumbnail((500, 500))
                im.save(ph, 'PNG')
            except Exception as e:  # noqa: BLE001 — нет фото: карточка без него, решение всё равно можно принять
                print(f'  фото {k}: {type(e).__name__}')
        cards.append(f'<div class=c data-key="{html.escape(k)}"><div class=t><b>{html.escape(it["role"] or "?")}</b> · {k[-8:]}</div>'
                     f'<div class=r><figure><img loading=lazy src="img/{k}.photo.png"><figcaption>фото товара</figcaption></figure>'
                     f'<figure><img loading=lazy src="img/{k}.cur.png"><figcaption>как сейчас</figcaption></figure>'
                     f'<figure><img loading=lazy src="img/{k}.new.png"><figcaption>как предлагает база</figcaption></figure></div>'
                     '<div class=b><button data-v=cur>Как сейчас — перед виден</button><button data-v=new>Как предлагает база</button></div>'
                     '<div class=st></div></div>')
    del T
    doc = ('<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Разворот моделей</title>'
           '<style>body{font:15px system-ui;margin:16px;background:#faf8f5}.c{background:#fff;border-radius:10px;padding:10px;margin:0 0 12px}'
           '.r{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}figure{margin:0;text-align:center}img{width:100%;aspect-ratio:1;object-fit:contain;background:#f4f2ee;border-radius:8px}'
           'figcaption{font-size:13px;color:#666}.b{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}button{padding:10px 12px;border-radius:8px;border:1px solid #ccc;background:#fff;min-height:44px}'
           '.on{background:#2b2622;color:#fff}.st{color:#777;font-size:13px;margin-top:4px}</style>'
           f'<h1>Разворот моделей — {len(cards)}</h1><p>Где у модели перед? Слева фото товара, дальше — как модель стоит в 3D '
           'сейчас и как предлагает её поставить автоматическая разметка. Нажмите, где виден ПЕРЕД (сиденье, ящики, дверцы). '
           'Ничего не меняется, пока вы не выберете.</p>' + ''.join(cards) +
           '<script>document.querySelectorAll(".c").forEach(c=>c.querySelectorAll(".b button").forEach(b=>b.onclick=async()=>{'
           'const r=await fetch("/api/lab/review",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({kind:"orient",key:c.dataset.key,verdict:b.dataset.v})});'
           'c.querySelectorAll(".b button").forEach(x=>x.classList.remove("on"));if(r.ok){b.classList.add("on");c.querySelector(".st").textContent="сохранено";}'
           'else c.querySelector(".st").textContent="не сохранилось, нажмите ещё раз";}));'
           'fetch("/api/lab/review?kind=orient&after=0").then(r=>r.json()).then(j=>{const l={};(j.rows||[]).forEach(x=>l[x.itemKey]=x);'
           'document.querySelectorAll(".c").forEach(c=>{const x=l[c.dataset.key];if(!x)return;c.querySelectorAll(".b button").forEach(b=>{if(b.dataset.v===x.verdict)b.classList.add("on");});'
           'c.querySelector(".st").textContent="отмечено раньше";});});</script>')
    open(os.path.join(WORK, 'index.html'), 'w', encoding='utf-8').write(doc)
    json.dump(items, open(os.path.join(WORK, 'items.json'), 'w'), ensure_ascii=False)
    print(f'расхождений разворота: {len(items)}; страница {WORK}/index.html')
    if publish:
        subprocess.run(['bash', '-c', 'ssh -p 22222 root@89.167.127.0 "mkdir -p /opt/remlab/test/orient-review/img" && '
                        f'scp -q -P 22222 {WORK}/index.html root@89.167.127.0:/opt/remlab/test/orient-review/ && '
                        f'scp -q -P 22222 {img}/*.png root@89.167.127.0:/opt/remlab/test/orient-review/img/'], check=False, timeout=600)
        print(f'{SITE}/test/orient-review/')
    return 0


def pull() -> int:
    """Решения владельца → записи разворота на проде «решено человеком» (слиянием, без потери чужих записей)."""
    items = {i['key']: i for i in json.load(open(os.path.join(WORK, 'items.json')))} if os.path.exists(os.path.join(WORK, 'items.json')) else {}
    after = int(open(CURSOR).read().strip() or 0) if os.path.exists(CURSOR) else 0
    rows = json.load(urllib.request.urlopen(f'{SITE}/api/lab/review?kind=orient&after={after}', timeout=30)).get('rows', [])
    upd, last = {}, after
    for r in rows:
        last = max(last, int(r['id']))
        it = items.get(r['itemKey'])
        if it and r['verdict'] in ('cur', 'new'):
            upd[it['key']] = {'yaw': it[r['verdict']], 'orient': f'human:orient-review:{r["verdict"]}'}
    if upd:
        prod = json.load(urllib.request.urlopen(ORIENT_URL, timeout=30))
        for k, v in upd.items():
            upd[k] = {**(prod.get(k) or {}), **v}
        tmp = os.path.join(WORK, 'orient-upd.json')
        json.dump(upd, open(tmp, 'w'), ensure_ascii=False)
        rc = subprocess.run([sys.executable, os.path.join(HERE, 'salad', 'publish_merge.py'), tmp, ORIENT_URL,
                             f'root@89.167.127.0:{PROD}/orient.json'], timeout=300).returncode
        if rc:
            print('WARN:orient_review: решения не опубликованы — прод не прочитан, повторю завтра', flush=True)
            return 0
    os.makedirs(WORK, exist_ok=True)
    open(CURSOR, 'w').write(str(last))
    print(f'решений владельца по развороту применено: {len(upd)}')
    return 0


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    sha = {'a': 'x' * 64, 'b': 'y' * 64, 'c': 'z' * 64, 'd': 'w' * 64}
    prod = {'b': {'yaw': 180.0}, 'd': {'yaw': 0, 'orient': 'human:orient-review:cur'}}
    rows = [('a', 'auto_resolved', 'x' * 64, '179', 'orienter', 'комод'),      # 180 против 0 по умолчанию → спросить
            ('b', 'auto_resolved', 'y' * 64, '181', 'orienter', 'диван'),      # совпадает с продом → не спрашивать
            ('c', 'auto_resolved', 'q' * 64, '90', 'orienter', 'стул'),        # решение для другого файла → нет
            ('d', 'auto_resolved', 'w' * 64, '90', 'orienter', 'стул'),        # решено человеком → нет
            ('a', 'review_pending', 'x' * 64, '90', 'orienter', 'комод')]      # спорное → нет
    got = conflicts(sha, prod, rows)
    ok('расхождение надёжного решения с текущим видом — на страницу, остальное нет', [g['key'] for g in got] == ['a'])
    ok('новое значение снэплено к 90°', got and got[0]['new'] == 180.0 and got[0]['cur'] == 0.0)
    cl = classify({'p': 'p' * 64, 'q': 'q' * 64, 'r': 'r' * 64}, {},
                  [('p', 'auto_resolved', 'p' * 64, '1', 'orienter', 'диван'),        # = 0 по умолчанию → можно публиковать
                   ('q', 'review_pending', 'q' * 64, '180', 'orienter', 'комод'),
                   ('r', 'auto_resolved', 'x' * 64, '0', 'orienter', 'стул')])
    ok('состояния: публикуемое без изменений / ждёт проверки / решение для другого файла',
       cl == {'p': 'publishable', 'q': 'pending', 'r': 'sha_mismatch'})
    return 1 if bad else 0


if __name__ == '__main__':
    a = sys.argv
    if '--selftest' in a:
        sys.exit(_selftest())
    sys.path.insert(0, HERE)
    if '--list' in a:
        for it in collect():
            print(it)
        sys.exit(0)
    if '--page' in a:
        sys.exit(page('--publish' in a))
    if '--pull' in a:
        sys.exit(pull())
    if '--sync' in a:
        sys.exit(sync())
    if '--counts' in a:
        print(counts())
        sys.exit(0)
    print(__doc__)
