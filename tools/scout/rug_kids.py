#!/usr/bin/env python3
"""ДЕТСКИЕ И «ВЕСЁЛЫЕ» КОВРЫ — ПО КАРТИНКЕ (план demo-05, дополнение 17.10). Отсев детского по названию
(`category_map.KIDS`) не видит ковёр «Милна Фанни» с надписью «Play» — в названии ничего детского. Здесь — вопрос
нейросети-зрителю (qwen3-vl через шлюз, как `orient_worker.py`) по фото каждого ковра в продаже: мультяшный мотив,
буквы/цифры/слова, персонажи и животные-рисунки, карта, дороги и машинки, игровые классики → «детский».

Решение кэшируется по картинке (`~/scout-scenes/rug-kids.json`, ключ — `load3.image_hash` адреса фото): загрузчик
каталога читает кэш и снимает роль «ковёр» у детских (`load3.assign`, без сети), этот шаг проверяет новые ковры и
сразу снимает роль в базе — чтобы не ждать следующей загрузки. Ошибка вызова — «не решено»: ковёр остаётся, счётчик
отказов печатается громко (сеть не должна выкидывать товары из каталога).

    ~/venvs/scout/bin/python rug_kids.py --scan [--limit N]   # проверить ковры без решения, снять роль у детских
    ~/venvs/scout/bin/python rug_kids.py --report             # сколько и каких отсеяно
    ~/venvs/scout/bin/python rug_kids.py --page               # страница отсеянных /test/share/rugs-kids/
"""
import base64
import html
import io
import json
import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser(os.environ.get('RUG_KIDS_CACHE', '~/scout-scenes/rug-kids.json'))
CHAT_URL = 'https://ai-gateway.vercel.sh/v1/chat/completions'
MODEL = os.environ.get('RUG_KIDS_MODEL', 'alibaba/qwen3-vl-instruct')
PROMPT_VER = 'rug-kids-v2'
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-At', '-F', '\x1f', '-q']
# формулировка — по критике Codex 17.10: детское только при явном смысловом мотиве, геометрия и яркость — не повод; спорное — нет
PROMPT = (
    'Это фото ковра из интернет-магазина. Оцени только рисунок самого ковра, не название товара и не яркость цветов.\n'
    'kids=true только при явном детском смысловом мотиве: мультяшные или детские персонажи и нарисованные животные; алфавит или '
    'счёт; учебная или игровая карта; игровая автодорога с машинами или дорожными знаками; классики, игровое поле; крупная детская '
    'игровая надпись вроде "LET\'S PLAY".\n'
    'kids=false для абстрактной и взрослой декоративной геометрии: ромбы, треугольники, круги, полосы, клетка, волны, пятна, '
    'Memphis и Bauhaus, просто яркие цвета, этника, цветы и листья, однотонный и фактурный. Не считай буквами орнамент, водяной '
    'знак, логотип магазина или символы, лишь похожие на буквы и цифры. Если изображение неясное или признак спорный — kids=false.\n'
    'Верни только JSON без markdown: {"kids": true|false, "why": "один короткий видимый признак по-русски"}')
PROMPT_SHA = __import__('hashlib').sha1(PROMPT.encode()).hexdigest()[:12]


def image_key(url: str) -> str:
    """Тот же ключ, что `load3.image_hash` (нормализованный адрес фото) — загрузчик читает кэш без сети."""
    sys.path.insert(0, HERE)
    import load3  # noqa: E402 — лёгкий импорт: функции, без прогона
    return load3.image_hash(url)


def load_cache() -> dict:
    try:
        return json.load(open(CACHE, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_cache(c: dict) -> None:
    tmp = CACHE + '.tmp'
    json.dump(c, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, CACHE)


def gw_key() -> str:
    k = os.environ.get('VERCEL_AI_GATEWAY_KEY')
    if k:
        return k.strip()
    for p in (os.path.join(HERE, '.env'), os.path.join(HERE, '..', '..', '.env')):
        try:
            for line in open(p, encoding='utf-8'):
                if line.startswith('VERCEL_AI_GATEWAY_KEY='):
                    return line.split('=', 1)[1].strip().strip('"\'')
        except OSError:
            continue
    raise RuntimeError('нет ключа шлюза VERCEL_AI_GATEWAY_KEY')


def fetch_image(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 remlab-rug-check'})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def ask(img: bytes) -> dict:
    from PIL import Image
    im = Image.open(io.BytesIO(img)).convert('RGB')
    im.thumbnail((768, 768))
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=85)
    body = {'model': MODEL, 'max_tokens': 160, 'temperature': 0,
            'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': PROMPT},
                {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()}}]}]}
    req = urllib.request.Request(CHAT_URL, json.dumps(body).encode(),
                                 {'Authorization': 'Bearer ' + gw_key(), 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        txt = json.loads(r.read())['choices'][0]['message']['content'] or ''
    return parse(txt)


def parse(txt: str) -> dict:
    """Строго: ровно {kids: bool, why: str}; markdown, лишние ключи, не тот тип — исключение («не решено»), а не «не детский»
    (Codex 17.10)."""
    d = json.loads(txt.strip())
    if not isinstance(d, dict) or set(d) != {'kids', 'why'} or not isinstance(d['kids'], bool) or not isinstance(d['why'], str):
        raise ValueError(f'ответ не по форме: {txt[:120]}')
    return {'kids': d['kids'], 'motifs': [d['why'][:80]] if d['why'] else []}


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, capture_output=True, text=True, input=sql)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def rugs() -> list[dict]:
    """Ковры в продаже с фото — и уже снятые этим шагом (роль пуста, причина в кэше), чтобы отчёт видел их."""
    rows = db("select shop_mid, external_id, name, coalesce(image_url_hd, image_url), cat_role, coalesce(image_url, '') from products "
              "where status='active' and coalesce(image_url_hd, image_url) is not null "
              "and (cat_role='ковёр' or (cat_role is null and name ~* '^ков[её]р'))")
    return [{'mid': r[0], 'eid': r[1], 'name': r[2], 'img': r[3], 'role': r[4] or None, 'img2': r[5] or None} for r in rows if len(r) >= 6]


def verdict(it: dict, cache: dict) -> dict | None:
    """Решение по ковру — под адресом крупного фото или обычного (загрузчик берёт крупное, если есть)."""
    for u in (it.get('img'), it.get('img2')):
        if u and image_key(u) in cache:
            return cache[image_key(u)]
    return None


def scan(limit: int) -> int:
    cache, items = load_cache(), rugs()
    todo = [it for it in items if (verdict(it, cache) or {}).get('prompt_sha') != PROMPT_SHA and it['role'] == 'ковёр']
    print(f'ковров в продаже: {len(items)}; без решения: {len(todo)}; проверю: {min(len(todo), limit)}', flush=True)
    ok = fail = kids = 0
    for it in todo[:limit]:
        try:
            v = ask(fetch_image(it['img']))
        except Exception as e:  # noqa: BLE001 — не решено, ковёр остаётся; счётчик ниже громкий
            fail += 1
            print(f'  ОТКАЗ {it["name"][:50]}: {str(e)[:120]}', flush=True)
            continue
        rec = {**v, 'ver': PROMPT_VER, 'prompt_sha': PROMPT_SHA, 'model': MODEL, 'name': it['name'], 'img': it['img']}
        for u in {it['img'], it.get('img2')} - {None, ''}:
            cache[image_key(u)] = rec
        save_cache(cache)
        ok += 1
        if v['kids']:
            kids += 1
            print(f'  ДЕТСКИЙ {it["name"][:60]} — {", ".join(v["motifs"])}', flush=True)
    # снять роль у детских прямо сейчас (загрузчик каталога сделает то же при следующем прогоне по кэшу)
    off = [it for it in items if it['role'] == 'ковёр' and (verdict(it, cache) or {}).get('kids')]
    if off:
        vals = ','.join(f"({int(it['mid'])},'{it['eid'].replace(chr(39), chr(39) * 2)}')" for it in off)
        db(f"update products p set cat_role = null from (values {vals}) v(mid,eid) "
           f"where p.shop_mid = v.mid and p.external_id = v.eid and p.cat_role = 'ковёр'")
    print(f'rug_kids: проверено {ok}, детских новых {kids}, роль снята у {len(off)}, отказов {fail}', flush=True)
    if fail:
        print(f'WARN:rug_kids_vlm_failed: {fail}', flush=True)   # refresh_daily поднимает WARN в статус
    return 1 if fail and not ok else 0


def flagged() -> list[dict]:
    cache, seen, out = load_cache(), set(), []
    for k, v in sorted(cache.items(), key=lambda kv: kv[1].get('name') or ''):
        if v.get('kids') and (v.get('name'), v.get('img')) not in seen:
            seen.add((v.get('name'), v.get('img'))); out.append({'key': k, **v})
    return out


def report() -> int:
    c, f = load_cache(), flagged()
    print(f'решений в кэше: {len({(v.get("name"), v.get("img")) for v in c.values()})}, детских: {len(f)}')
    for x in f:
        print(f'  {x.get("name")} — {", ".join(x.get("motifs") or [])}')
    return 0


def page() -> int:
    """Страница отсеянных: фото, название, что увидела нейросеть — владелец смотрит ложные срабатывания."""
    sys.path.insert(0, HERE)
    import category_map  # noqa: E402
    items, c = rugs(), load_cache()
    by_name = [it for it in items if category_map.is_kids(it['name'], 'ковёр')]
    f = flagged()
    cards = ''.join(f'<figure><img src="{html.escape(x["img"])}" loading="lazy" alt=""><figcaption><b>{html.escape(x.get("name") or "")}</b>'
                    f'<br>{html.escape(", ".join(x.get("motifs") or []))}</figcaption></figure>' for x in f[:40])
    names = ''.join(f'<li>{html.escape(it["name"])}</li>' for it in by_name)
    out = ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>Детские ковры</title><style>:root{--ink:#2b2622;--muted:#6f665e;--line:#e6dfd6;--bg:#faf7f2;--card:#fff}'
           '@media(prefers-color-scheme:dark){:root{--ink:#eee7df;--muted:#b3a99e;--line:#3a332d;--bg:#1d1a17;--card:#26221e}}'
           'body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}main{max-width:1000px;margin:0 auto;padding:20px 16px 60px}'
           '.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}figure{margin:0;background:var(--card);border:1px solid var(--line);'
           'border-radius:12px;overflow:hidden}figure img{width:100%;aspect-ratio:1;object-fit:cover;display:block}figcaption{padding:8px 10px;font-size:14px;color:var(--muted)}'
           'figcaption b{color:var(--ink);font-weight:600}.lead{color:var(--muted)}</style></head><body><main>'
           f'<h1>Детские ковры — отсеяны из гостиной</h1><p class="lead">Проверено ковров: {len({(v.get("name"), v.get("img")) for v in c.values()})}. По картинке отсеяно: {len(f)} '
           f'(нейросеть-зритель, вопрос «нужен только для детской?»). По словам в названии: {len(by_name)}. Посмотрите, нет ли среди них '
           'обычных ковров — такие вернём.</p><div class="g">' + (cards or '<p>пока никого</p>') + '</div>'
           + (f'<h2>По названию</h2><ul>{names}</ul>' if names else '') + '</main></body></html>')
    p = '/tmp/rugs-kids.html'
    open(p, 'w', encoding='utf-8').write(out)
    subprocess.run(['ssh', '-o', 'BatchMode=yes', 'root@89.167.127.0', 'mkdir -p /opt/remlab/test/share/rugs-kids'], check=True)
    subprocess.run(['scp', '-q', p, 'root@89.167.127.0:/opt/remlab/test/share/rugs-kids/index.html'], check=True)
    print(f'выложено: https://remont-lab.online/test/share/rugs-kids/ · по картинке {len(f)}, по названию {len(by_name)}')
    return 0


def is_kids_rug(img_url: str | None, cache: dict | None = None) -> bool:
    """Для загрузчика: детский ли ковёр по уже принятому решению (без сети)."""
    if not img_url:
        return False
    c = cache if cache is not None else load_cache()
    return bool(c.get(image_key(img_url), {}).get('kids'))


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--scan' in a:
        lim = int(a[a.index('--limit') + 1]) if '--limit' in a else 400
        sys.exit(scan(lim))
    if '--report' in a:
        sys.exit(report())
    if '--page' in a:
        sys.exit(page())
    print(__doc__)
