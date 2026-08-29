#!/usr/bin/env python3
"""Вырезка фона как ШАГ КОНВЕЙЕРА: поменялось фото — маска пересчитывается сама.

ЧТО ИМЕННО АВТОМАТИЗИРУЕМ. Вырезка — вход генератора мешей и одновременно то, по чему видно,
годится ли товар вообще (коллаж, брак маски). Пока она делалась разовыми скриптами, ответ
«а что там сейчас» приходилось добывать руками. Теперь это ночной шаг: прошёлся по спросу,
досчитал недостающее, записал измерения в `photo_assessment` — и `photo_fit` сразу видит свежую
картину, а страница `/test/sets-preview/` показывает её владельцу.

КЛЮЧ — SHA БАЙТОВ ФОТО, не SKU и не URL. Магазин подменил картинку под тем же адресом → у товара
новый `source_sha` (за этим следит `mesh_queue.ingest`) → строки в `photo_assessment` для него
нет → товар автоматически попадает в работу. Ничего «помечать устаревшим» руками не надо.
Версия оценщика (`preprocess.ASSESSOR_VERSION`) входит в ключ: меняем цепочку вырезки —
пересчёт происходит сам, а старые замеры остаются в истории.

ИСТОЧНИК МАСКИ СМЕННЫЙ (`CUTOUT_BACKEND`):
  fal    — сейчас: `birefnet/v2`, те же веса BiRefNet, что в образе Salad. ~$0.0005/фото.
  local  — BiRefNet на CPU, ~14 с/фото на 12 ядрах. Бесплатно, если некуда спешить.
  salad  — когда подключим ноду: маска считается там же, где меши, и бесплатно.

ТЕМП ВАЖНЕЕ ПАРАЛЛЕЛЬНОСТИ. fal отвечает 403 не по ключу и не по балансу, а по темпу: на шести
потоках 376 отказов из 508, на трёх с короткими паузами — 242, на двух с паузами до минуты —
ноль. Отсюда дефолты: 2 потока, 8 попыток, пауза 3·2^n до 60 с. За отказ денег не берут, но
товар без вырезки — это товар, о котором конвейер ничего не знает.

  ~/venvs/scout/bin/python cutout_sync.py            # досчитать недостающее
  ~/venvs/scout/bin/python cutout_sync.py --report   # что посчитано, что ждёт
"""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'salad'))
sys.path.insert(0, HERE)

import collage            # noqa: E402
import components         # noqa: E402
import hybrid_mask        # noqa: E402
import preprocess as PRE  # noqa: E402  (defringe/trim_alpha/mask_verdict — они без GPU)

CACHE = os.path.expanduser(os.environ.get('CUTOUT_CACHE', '~/scout-scenes/cutouts'))
BACKEND = os.environ.get('CUTOUT_BACKEND', 'fal')
WORKERS = int(os.environ.get('CUTOUT_WORKERS', '2'))
DAILY_MAX = int(os.environ.get('CUTOUT_DAILY_MAX', '400'))
UA = {'User-Agent': 'remlab-cutout/1.0'}

PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, capture_output=True, text=True, input=sql)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def q(v) -> str:
    return 'null' if v is None else "'" + str(v).replace("'", "''") + "'"


def fetch(url: str, timeout: int = 40) -> bytes:
    if url.startswith('//'):
        url = 'https:' + url
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


# ------------------------------------------------------------------ источники маски

def _fal_key() -> str:
    for ln in open(os.path.join(HERE, '.env')):
        m = re.match(r'FAL_KEY=(.+)', ln.strip())
        if m:
            return m.group(1)
    raise SystemExit('нет FAL_KEY — см. .memory_bank/_secrets/ACCESS.md')


def mask_fal(raw: bytes, tries: int = 8) -> Image.Image:
    key = _fal_key()
    uri = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode()
    r = None
    for attempt in range(tries):
        req = urllib.request.Request(
            'https://queue.fal.run/fal-ai/birefnet/v2', method='POST',
            data=json.dumps({'image_url': uri}).encode(),
            headers={'Authorization': f'Key {key}', 'Content-Type': 'application/json'})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=60).read())
            break
        except urllib.error.HTTPError as e:
            if e.code not in (403, 429, 500, 502, 503) or attempt == tries - 1:
                raise
            time.sleep(min(60, 3 * 2 ** attempt))
    t0 = time.time()
    while time.time() - t0 < 300:
        time.sleep(2)
        s = json.loads(urllib.request.urlopen(urllib.request.Request(
            r['status_url'], headers={'Authorization': f'Key {key}'}), timeout=60).read())
        if s.get('status') == 'COMPLETED':
            res = json.loads(urllib.request.urlopen(urllib.request.Request(
                r['response_url'], headers={'Authorization': f'Key {key}'}), timeout=120).read())
            url = ((res.get('image') or {}).get('url')
                   or (res.get('images') or [{}])[0].get('url'))
            return Image.open(io.BytesIO(fetch(url, 180))).convert('RGBA')
        if s.get('status') in ('FAILED', 'ERROR'):
            raise RuntimeError(str(s)[:200])
    raise TimeoutError('fal не ответил за 300 с')


_LOCAL = None


def mask_local(raw: bytes) -> Image.Image:
    """BiRefNet на CPU. Веса те же (`ZhengPeng7/BiRefNet`), но в float32: fp16 на CPU не считается."""
    global _LOCAL
    src = Image.open(io.BytesIO(raw)).convert('RGB')
    if _LOCAL is None:
        import torch
        from torchvision import transforms
        from transformers import AutoModelForImageSegmentation
        m = AutoModelForImageSegmentation.from_pretrained(
            'ZhengPeng7/BiRefNet', trust_remote_code=True)
        m.float().eval()
        torch.set_num_threads(int(os.environ.get('THREADS', '12')))
        _LOCAL = (torch, m, transforms.Compose([
            transforms.Resize((1024, 1024)), transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])]))
    torch, m, tf = _LOCAL
    with torch.no_grad():
        pred = m(tf(src).unsqueeze(0))[-1].sigmoid()[0].squeeze()
    out = src.convert('RGBA')
    out.putalpha(Image.fromarray((pred.numpy() * 255).astype(np.uint8)).resize(src.size))
    return out


def mask_salad(raw: bytes) -> Image.Image:
    raise NotImplementedError(
        'нода Salad ещё не подключена; когда подключим — маска считается там же, где меши '
        '(режим MODE=mask_only, эндпоинт /assess в tools/scout/salad/worker.py)')


BACKENDS = {'fal': mask_fal, 'local': mask_local, 'salad': mask_salad}


# ------------------------------------------------------------------ цепочка и запись

def chain(src: Image.Image, net: Image.Image, role: str | None = None) -> tuple[Image.Image, dict]:
    """Наша цепочка — ровно та же, что в `salad/preprocess._cut_chain`, но с готовой маской.

    `role` нужен точечным правкам: рост по связности — только коврам, заливка силуэта —
    только вазам/кашпо/статуэткам. Остальные 95% товаров идут ровно как раньше.
    """
    try:
        refined, info = hybrid_mask.refine(src, net, role=role)
    except Exception as e:  # noqa: BLE001 — гибрид не должен ронять шаг; факт отказа виден
        refined, info = net, {'hybrid_error': f'{type(e).__name__}: {str(e)[:100]}'}
    a = np.asarray(refined)[..., 3].astype(np.float32) / 255.0
    cleaned, comp = components.clean(a)
    # Дырки, внутри которых НЕ фон, — это потерянная основа товара (серый ковёр, узор которого
    # сеть удержала, а поле потеряла). Просветы проволоки и реек внутри показывают фон и
    # остаются нетронутыми — различаем по содержимому, а не по размеру (урок 307).
    cleaned, holes = components.fill_holes_unlike_bg(cleaned, np.asarray(src), role=role)
    comp.update(holes)
    info['components'] = comp
    refined = Image.fromarray(np.dstack([np.asarray(refined)[..., :3],
                                         (np.clip(cleaned, 0, 1) * 255).astype(np.uint8)]), 'RGBA')
    is_col, why, feats = collage.is_collage(np.asarray(src).astype(np.float32), cleaned)
    info['collage'] = {'verdict': bool(is_col), 'why': why, 'features': feats}
    shape = PRE.defringe(refined)
    cut = PRE.trim_alpha(shape)
    info.update(PRE.mask_verdict(cut))
    if is_col:
        info.update(verdict='bad', reason='фото-коллаж: ' + ', '.join(why[1:] or ['баннер']))
    fw, fh = src.size
    cw, ch = cut.size
    info['photo'] = {'frame_wh': [fw, fh], 'object_wh': [cw, ch],
                     'object_share': round(cw * ch / max(fw * fh, 1), 4),
                     'object_rel_side': round(max(cw, ch) / max(max(fw, fh), 1), 3),
                     'object_min_side': int(min(cw, ch))}
    return cut, info


# ОХВАТ — ВЕСЬ ПУЛ, А НЕ СПРОС МЕШЕЙ (решение владельца 29.08). Резать надо всё, что
# ТЕОРЕТИЧЕСКИ может попасть в сет, и делать это ДО сборки: тогда негодное фото не доходит
# ни до комплекта, ни до очереди мешей. Спрос мешей (`mesh_demand`, 1667) — это следствие
# сборки, то есть слишком поздно и слишком узко.
# Ворота пула — те же, что у подбора: роль, активен, в наличии, есть фото и цена,
# обогащение активно, quality >= 0.65. На 29.08 это 16 653 товара, из них 14 989 идут и на меши.
POOL_SQL = """
  from products p join product_enrichment e using (shop_mid, external_id)
 where p.cat_role is not null and p.status='active' and p.in_stock
   and p.image_url is not null and p.price_rub is not null
   and e.status='active' and e.payload is not null and e.quality >= %s
"""
MIN_QUALITY = os.environ.get('CUTOUT_MIN_QUALITY', '0.65')


def pool_size() -> int:
    return int(db('select count(*)' + (POOL_SQL % MIN_QUALITY))[0][0])


def sync_photos(limit: int) -> int:
    """Хеш байтов фото для пула — без него нечем ключевать оценку.

    Держим отдельно от `mesh_demand.source_sha`: спрос мешей узок, а резать надо весь пул.
    Перехеширование раз в `SHA_MAX_AGE_DAYS` — магазин подменяет картинку под тем же адресом.
    """
    # КРУПНОЕ ФОТО В ПРИОРИТЕТЕ (29.08). `image_url_hd` — картинка с CDN магазина, 800×600
    # против 450×338 в фиде. На 450 px проволочная ножка занимает 1–2 пикселя физически, и
    # никакой вырезальщик её не восстановит; вдвое больше по стороне — это вчетверо больше
    # информации ровно там, где мы теряем детали. Хеш считается по ТЕМ байтам, которые режем,
    # поэтому появление HD у товара автоматически ставит его на перерезку.
    rows = db(
        "select p.shop_mid||':'||p.external_id, coalesce(p.image_url_hd, p.image_url) "
        + (POOL_SQL % MIN_QUALITY) +
        "   and not exists (select 1 from product_photo_current c "
        "        where c.sku = p.shop_mid||':'||p.external_id and c.image_url = p.image_url "
        f"          and c.observed_at > now() - interval '{os.environ.get('SHA_MAX_AGE_DAYS', '30')} days') "
        f" order by p.shop_mid, p.external_id limit {limit}")
    n = 0
    for r in rows:
        if len(r) != 2:
            continue
        sku, url = r
        try:
            sha = hashlib.sha256(fetch(url)).hexdigest()
        except Exception as e:  # noqa: BLE001 — мёртвое фото не валит прогон
            print(f'  хеш {sku}: {type(e).__name__}: {str(e)[:70]}', flush=True)
            continue
        db("insert into product_photo_current (sku, image_url, source_sha, observed_at) "
           f"values ({q(sku)}, {q(url)}, {q(sha)}, now()) "
           "on conflict (sku) do update set image_url=excluded.image_url, "
           "source_sha=excluded.source_sha, observed_at=now()")
        n += 1
    return n


def todo(limit: int) -> list[tuple[str, str, str, str]]:
    """(sku, role, image_url, source_sha) — у кого фото ещё не оценено текущей версией.

    Товары, стоящие в комплектах, идут первыми: их вырезку владелец видит на витрине сегодня.
    """
    rows = db(
        "select c.sku, p.cat_role, c.image_url, c.source_sha, "
        "       case when d.priority = 1 then 0 else 1 end as ord "
        "  from product_photo_current c "
        "  join products p on p.shop_mid||':'||p.external_id = c.sku "
        "  left join mesh_demand d on d.sku = c.sku "
        " where c.source_sha is not null "
        "   and not exists (select 1 from photo_assessment a "
        f"      where a.source_sha = c.source_sha and a.assessor_version = {q(PRE.ASSESSOR_VERSION)}) "
        f" order by ord, c.sku limit {limit}")
    return [tuple(r[:4]) for r in rows if len(r) == 5]


def one(job) -> tuple[str, str | None]:
    sku, role, url, sha = job
    dst = os.path.join(CACHE, sha + '.png')
    try:
        raw = fetch(url)
        got = hashlib.sha256(raw).hexdigest()
        if got != sha:
            # Байты разъехались с тем, что записал ingest: фото подменили между прогонами.
            # Считать по НОВЫМ байтам нельзя — запишем результат под чужим ключом; пусть
            # следующий ingest обновит sha, и товар вернётся сюда сам.
            return 'moved', f'{sku}: фото изменилось (sha {sha[:8]} → {got[:8]})'
        src = Image.open(io.BytesIO(raw)).convert('RGB')
        net = BACKENDS[BACKEND](raw)
        if net.size != src.size:
            net = net.resize(src.size, Image.LANCZOS)
        cut, info = chain(src, net, role=role)
        os.makedirs(CACHE, exist_ok=True)
        cut.save(dst)
        info['backend'] = BACKEND
        from photo_fit import verdict_from_metrics
        verdict = verdict_from_metrics(role, info)[0]
        db("insert into photo_assessment (source_sha, assessor_version, metrics, verdict) "
           f"values ({q(sha)}, {q(PRE.ASSESSOR_VERSION)}, "
           f"{q(json.dumps(info, ensure_ascii=False))}::jsonb, {q(verdict)}) "
           "on conflict (source_sha, assessor_version) do update set "
           "metrics=excluded.metrics, verdict=excluded.verdict")
        return 'ok', None
    except Exception as e:  # noqa: BLE001 — считаем отказы, молчать нельзя
        return 'fail', f'{sku}: {type(e).__name__}: {str(e)[:110]}'


def report() -> None:
    rows = db("select a.verdict, count(*) from photo_assessment a "
              f"where a.assessor_version = {q(PRE.ASSESSOR_VERSION)} group by 1 order by 2 desc")
    total = sum(int(r[1]) for r in rows if len(r) == 2)
    print(f'оценено фото: {total} (оценщик {PRE.ASSESSOR_VERSION}, источник маски {BACKEND})')
    for r in rows:
        if len(r) == 2:
            print(f'  {r[0]:12} {int(r[1]):6}  ({100 * int(r[1]) / max(total, 1):.1f}%)')
    print(f'пул «может попасть в сет»: {pool_size()}')
    print(f'  у скольких известен хеш фото: '
          f"{db('select count(*) from product_photo_current')[0][0]}")
    print(f'  ждут вырезки: {len(todo(100000))}')


def main() -> int:
    if '--report' in sys.argv:
        report()
        return 0
    if BACKEND not in BACKENDS:
        print(f'неизвестный источник маски: {BACKEND}')
        return 1
    added = sync_photos(int(os.environ.get('CUTOUT_SHA_MAX', '400')))
    if added:
        print(f'посчитано хешей фото: {added}', flush=True)
    jobs = todo(DAILY_MAX)
    if not jobs:
        print('вырезки актуальны — считать нечего')
        return 0
    print(f'к вырезке: {len(jobs)} (источник {BACKEND}, потоков {WORKERS})', flush=True)
    stat, errs = {'ok': 0, 'fail': 0, 'moved': 0}, []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for st, err in ex.map(one, jobs):
            stat[st] += 1
            if err:
                errs.append(err)
    print(f"вырезано {stat['ok']}, фото сменилось у {stat['moved']}, отказов {stat['fail']}")
    for e in errs[:10]:
        print('   ✗', e)
    # Отказы не валят ночную цепочку: товар без вырезки просто ждёт следующего прогона.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
