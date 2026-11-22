#!/usr/bin/env python3
"""Замер размеров входа мешей (план mesh-input-hd-01, шаг 2; ADR-0452): сколько товаров отсечёт сторож размера при разных порогах.

БЕСПЛАТНО и бережно к чужим серверам: из сети — только первые `HEAD_BYTES` байт каждого HD-файла (заголовок картинки даёт размеры), по одному
запросу, с паузой `PAUSE_S`; тел картинок не качаем. Размер ВЫРЕЗКИ берём не из сети, а из уже посчитанных измерений ноды (`photo_assessment.metrics.photo`,
считались по тому же адресу, что хеш: `coalesce(image_url_hd, image_url)`), поэтому выборка — именно те товары, что реально идут в меши (прошли вырезку).

  mesh_photo_survey.py --n 300 --seed 1 --out <папка>   # выборка, замер, таблица порог → сколько отсечём; файлы survey.json и survey.md
  mesh_photo_survey.py --selftest                       # без БД и сети

Мерки: `cut_min` — меньшая сторона вырезки (как в плане), `cut_long` — большая (TRELLIS.2 режет квадрат по МАСКЕ, то есть его сторона = большая сторона вырезки).
Порог по меньшей стороне режет и «тонкие по природе» вещи (торшер, стеллаж), поэтому рядом всегда считается порог по большей стороне и разбивка по ролям.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mesh_photo as MP  # noqa: E402

HEAD_BYTES = 65536
PAUSE_S = 0.4
THRESHOLDS = (384, 512, 640)
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) remlab-catalog/1.0'}


def sample_sql(n: int, seed: str, assessor: str) -> str:
    """Товары, у которых вырезка ТЕКУЩЕЙ версии оценщика есть и годна (`ok`): ровно тот пул, что идёт в меши. Порядок — по хешу, повторяем при том же seed."""
    return (f"select p.shop_mid||':'||p.external_id, coalesce(p.cat_role,''), {MP.photo_sql('p')}, coalesce(p.image_url,''), "
            "       a.metrics::text "
            "  from products p "
            "  join product_photo_current c on c.sku = p.shop_mid||':'||p.external_id "
            f"  join photo_assessment a on a.source_sha = c.source_sha and a.assessor_version = '{assessor}' "
            f" where p.in_stock and a.verdict = 'ok' and {MP.photo_sql('p')} is not null "
            f" order by md5(p.shop_mid||':'||p.external_id||'{seed}') limit {int(n)}")


ROLES_WIDE = ('диван', 'кресло', 'стул', 'тв-тумба', 'стеллаж', 'столик', 'стол обеденный', 'торшер', 'лампа', 'камин', 'пуф', 'шкаф', 'комод')


def sample_hd_sql(per_role: int, seed: str) -> str:
    """Выборка ПО РОЛЯМ без оглядки на вырезку (вырезка есть лишь у четырёх ролей): `per_role` товаров на роль, порядок по хешу."""
    roles = ','.join("'" + r.replace("'", "''") + "'" for r in ROLES_WIDE)
    return (f"select sku, role, url from (select p.shop_mid||':'||p.external_id as sku, p.cat_role as role, {MP.photo_sql('p')} as url, "
            f"row_number() over (partition by p.cat_role order by md5(p.shop_mid||':'||p.external_id||'{seed}')) as rn "
            f"from products p where p.in_stock and p.mesh_required and p.cat_role in ({roles}) and {MP.photo_sql('p')} is not null) t "
            f"where rn <= {int(per_role)} order by role, rn")


def quantile(vals: list, q: float):
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))] if v else None


def survey_hd(rows_db: list, measured: list, fetch=None, pause: float = PAUSE_S) -> dict:
    """Размер оригинала по ролям БЕЗ вырезки: HD читаем по заголовку; размер вырезки ОЦЕНИВАЕМ долей кадра, снятой на товарах с настоящей вырезкой
    (`measured` — items первого замера): доля большей/меньшей стороны вырезки к длинной стороне кадра, квартили 10/50/90. Это ОЦЕНКА, не замер."""
    fetch = fetch or head_size
    rl = [m['cut_long'] / max(m['frame_wh']) for m in measured if max(m['frame_wh'])]
    rm = [m['cut_min'] / max(m['frame_wh']) for m in measured if max(m['frame_wh'])]
    ratios = {q: (quantile(rl, q), quantile(rm, q)) for q in (0.1, 0.5, 0.9)}
    items, fails = [], []
    for sku, role, url in rows_db:
        try:
            wh = fetch(url)
        except Exception as e:  # noqa: BLE001
            wh = None
            fails.append({'sku': sku, 'why': f'HD не прочитан: {type(e).__name__}: {str(e)[:60]}'})
        time.sleep(pause)
        if wh:
            items.append({'sku': sku, 'role': role, 'hd_wh': list(wh), 'hd_min': min(wh), 'hd_long': max(wh)})
    out = {'n': len(items), 'failed': fails, 'ratios_long_min': {str(q): r for q, r in ratios.items()}, 'by_role': {}}
    for role in sorted({i['role'] for i in items}):
        sub = [i for i in items if i['role'] == role]
        band = {}
        for t in THRESHOLDS:
            lo_med_hi = []
            for q in (0.1, 0.5, 0.9):           # q=0.1 — вырезка «мелкая» (оптимистичная для отсечения: больше отсечённых)
                rlong, rmin = ratios[q]
                lo_med_hi.append(sum(1 for i in sub if i['hd_long'] * rmin < t))
            band[str(t)] = lo_med_hi
        out['by_role'][role] = {'n': len(sub), 'hd_long_median': quantile([i['hd_long'] for i in sub], 0.5),
                                'hd_long_min': min(i['hd_long'] for i in sub), 'hd_under_700': sum(1 for i in sub if i['hd_long'] < 700),
                                'cut_min_below': band}
    out['items'] = items
    return out


def render_hd_md(res: dict) -> str:
    L = [f"# Оригиналы по ролям (без вырезки): {res['n']} товаров, отказов {len(res['failed'])}", '',
         'Размер ВЫРЕЗКИ здесь оценён по доле кадра, снятой на товарах с настоящей вырезкой (меньшая сторона вырезки / длинная сторона кадра, квартили 10/50/90 %: '
         + ', '.join(f"{k}: {v[1]:.2f}" for k, v in res['ratios_long_min'].items()) + '). Это оценка, а не замер.', '',
         '| роль | n | длинная сторона HD: медиана | минимум | HD < 700 px | отсечём по меньшей стороне вырезки (оценка, 10/50/90 %-я доля): <384 | <512 | <640 |',
         '|---|---|---|---|---|---|---|---|']
    for role, v in res['by_role'].items():
        c = v['cut_min_below']
        L.append(f"| {role} | {v['n']} | {v['hd_long_median']} | {v['hd_long_min']} | {v['hd_under_700']} | " + ' | '.join('/'.join(str(x) for x in c[str(t)]) for t in THRESHOLDS) + ' |')
    return '\n'.join(L) + '\n'


def image_size(raw: bytes):
    """(ширина, высота) по началу файла или None."""
    from PIL import ImageFile
    p = ImageFile.Parser()
    try:
        p.feed(raw)
    except Exception:  # noqa: BLE001 — обрезанный файл: размеры уже могли быть прочитаны
        pass
    im = p.image
    return tuple(im.size) if im is not None else None


def head_size(url: str, timeout: int = 15):
    """Размеры картинки по первым HEAD_BYTES байт (заголовок Range; сервер может отдать больше — читаем не более HEAD_BYTES)."""
    if url.startswith('//'):
        url = 'https:' + url
    req = urllib.request.Request(url, headers={**UA, 'Range': f'bytes=0-{HEAD_BYTES - 1}'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return image_size(r.read(HEAD_BYTES))


def table(rows: list, thresholds=THRESHOLDS) -> list:
    """rows: [{'cut_min','cut_long',…}] → [{'порог': t, 'по_меньшей': n, 'по_большей': m, доли}]. Чистая функция."""
    n = len(rows) or 1
    out = []
    for t in thresholds:
        a = sum(1 for r in rows if r['cut_min'] < t)
        b = sum(1 for r in rows if r['cut_long'] < t)
        out.append({'threshold': t, 'below_min': a, 'below_min_pct': round(100 * a / n, 1), 'below_long': b, 'below_long_pct': round(100 * b / n, 1)})
    return out


def survey(rows_db: list, fetch=head_size, pause: float = PAUSE_S) -> dict:
    items, fails = [], []
    for sku, role, url, thumb, raw in rows_db:
        try:
            m = json.loads(raw)['photo']
            cw, ch = m['object_wh']
            fw, fh = m['frame_wh']
        except Exception as e:  # noqa: BLE001
            fails.append({'sku': sku, 'why': f'нет измерений вырезки: {type(e).__name__}'})
            continue
        hd = None
        try:
            hd = fetch(url)
        except Exception as e:  # noqa: BLE001 — счётчик отказов обязателен
            fails.append({'sku': sku, 'why': f'HD не прочитан: {type(e).__name__}: {str(e)[:60]}'})
        time.sleep(pause)
        scale = (450.0 / max(fw, fh)) if max(fw, fh) > 450 else 1.0      # во сколько раз вырезка была бы меньше на превью 450 px
        items.append({'sku': sku, 'role': role, 'frame_wh': [fw, fh], 'hd_wh': list(hd) if hd else None,
                      'cut_wh': [cw, ch], 'cut_min': min(cw, ch), 'cut_long': max(cw, ch),
                      'cut_min_thumb': round(min(cw, ch) * scale), 'cut_long_thumb': round(max(cw, ch) * scale)})
    thumb_rows = [{'cut_min': r['cut_min_thumb'], 'cut_long': r['cut_long_thumb']} for r in items]
    by_role = {}
    for r in items:
        by_role.setdefault(r['role'] or '(без роли)', []).append(r)
    return {'n': len(items), 'failed': fails, 'table_hd': table(items), 'table_if_thumb450': table(thumb_rows),
            'by_role': {k: {'n': len(v), 'table': table(v)} for k, v in sorted(by_role.items(), key=lambda kv: -len(kv[1]))},
            'hd_matches_frame': sum(1 for r in items if r['hd_wh'] and r['hd_wh'] == r['frame_wh']),
            'items': items}


def render_md(res: dict) -> str:
    L = [f"# Замер входа мешей: {res['n']} товаров с годной вырезкой, отказов замера: {len(res['failed'])}", '',
         'Фото — как идёт в меши сегодня (`coalesce(image_url_hd, image_url)`); размер вырезки — из измерений ноды.', '',
         '| порог px | отсечём по МЕНЬШЕЙ стороне вырезки | отсечём по БОЛЬШЕЙ стороне | было бы на превью 450 px (меньшая) | (большая) |', '|---|---|---|---|---|']
    th = {t['threshold']: t for t in res['table_if_thumb450']}
    for t in res['table_hd']:
        w = th[t['threshold']]
        L.append(f"| {t['threshold']} | {t['below_min']} ({t['below_min_pct']} %) | {t['below_long']} ({t['below_long_pct']} %) | {w['below_min']} ({w['below_min_pct']} %) | {w['below_long']} ({w['below_long_pct']} %) |")
    L += ['', f"Размер кадра в измерениях совпал с размером HD-файла по заголовку: {res['hd_matches_frame']} из {res['n']}.", '', '## По ролям (меньшая сторона)', '',
          '| роль | n | <384 | <512 | <640 |', '|---|---|---|---|---|']
    for role, v in res['by_role'].items():
        t = {x['threshold']: x for x in v['table']}
        L.append(f"| {role} | {v['n']} | {t[384]['below_min']} | {t[512]['below_min']} | {t[640]['below_min']} |")
    if res['failed']:
        L += ['', '## Отказы замера', ''] + [f"- {f['sku']}: {f['why']}" for f in res['failed'][:20]]
    return '\n'.join(L) + '\n'


def selftest() -> int:
    rows = [{'cut_min': m, 'cut_long': l} for m, l in ((300, 900), (400, 500), (520, 700), (700, 1000))]
    t = {x['threshold']: x for x in table(rows)}
    ok = (t[384]['below_min'] == 1 and t[512]['below_min'] == 2 and t[640]['below_min'] == 3 and t[384]['below_long'] == 0
          and t[512]['below_long'] == 1 and t[640]['below_long'] == 1 and t[512]['below_min_pct'] == 50.0)
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (800, 600), (9, 9, 9)).save(buf, 'JPEG')
    ok = ok and image_size(buf.getvalue()[:2000]) == (800, 600)
    fake = [('a:1', 'диван', 'http://x/a', 'http://x/t', json.dumps({'photo': {'object_wh': [500, 300], 'frame_wh': [900, 600]}})),
            ('a:2', 'комод', 'http://x/b', 'http://x/t', 'не json')]
    res = survey(fake, fetch=lambda u: (900, 600), pause=0)
    ok = ok and res['n'] == 1 and len(res['failed']) == 1 and res['items'][0]['cut_min'] == 300 and res['items'][0]['cut_min_thumb'] == 150 and res['hd_matches_frame'] == 1
    meas = [{'cut_long': 600, 'cut_min': 300, 'frame_wh': [1000, 800]}, {'cut_long': 800, 'cut_min': 500, 'frame_wh': [1000, 1000]}]
    sr = survey_hd([('a:1', 'диван', 'u1'), ('a:2', 'диван', 'u2')], meas, fetch=lambda u: (2000, 1000) if u == 'u1' else (500, 400), pause=0)
    ok = ok and sr['n'] == 2 and sr['by_role']['диван']['hd_under_700'] == 1 and sr['by_role']['диван']['hd_long_min'] == 500
    ok = ok and 'sample_hd_sql' and 'row_number()' in sample_hd_sql(5, '1')
    print('selftest', 'OK' if ok else 'FAIL')
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=300)
    ap.add_argument('--seed', default='1')
    ap.add_argument('--out', default=None)
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--hd-roles', type=int, default=0, help='по N товаров на роль БЕЗ вырезки: только размер оригинала + оценка (нужен --measured)')
    ap.add_argument('--measured', default=None, help='survey.json первого замера (доли вырезки к кадру)')
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.hd_roles:
        r = subprocess.run(PSQL, capture_output=True, text=True, input=sample_hd_sql(a.hd_roles, a.seed))
        if r.returncode != 0:
            sys.exit('БД: ' + r.stderr[:300])
        rows = [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]
        print(f'выборка по ролям: {len(rows)} товаров', flush=True)
        res = survey_hd(rows, json.load(open(a.measured, encoding='utf-8'))['items'])
        md = render_hd_md(res)
        print(md)
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            json.dump(res, open(os.path.join(a.out, 'survey-roles.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            open(os.path.join(a.out, 'survey-roles.md'), 'w', encoding='utf-8').write(md)
        return
    import re   # версия оценщика — из файла: импорт `preprocess` тянет torch
    ASSESSOR_VERSION = re.search(r"^ASSESSOR_VERSION\s*=\s*'([^']+)'", open(os.path.join(HERE, 'salad', 'preprocess.py'), encoding='utf-8').read(), re.M).group(1)
    r = subprocess.run(PSQL, capture_output=True, text=True, input=sample_sql(a.n, a.seed, ASSESSOR_VERSION))
    if r.returncode != 0:
        sys.exit('БД: ' + r.stderr[:300])
    rows = [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]
    print(f'выборка: {len(rows)} товаров', flush=True)
    res = survey(rows)
    md = render_md(res)
    print(md)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        json.dump(res, open(os.path.join(a.out, 'survey.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        open(os.path.join(a.out, 'survey.md'), 'w', encoding='utf-8').write(md)


if __name__ == '__main__':
    main()
