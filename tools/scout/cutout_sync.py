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
  ~/venvs/scout/bin/python cutout_sync.py --report   # что посчитано, что ждёт (и отдельно по комнатам)
  CUTOUT_DAILY_MAX=0 ~/venvs/scout/bin/python cutout_sync.py --rooms-limit 10   # только товары комнат (T-46), 10 штук
  PHOTO_ROOMS_LIMIT=500 CUTOUT_ROOMS_MAX=300 ~/venvs/scout/bin/python cutout_sync.py --rooms-only   # ночной шаг комнат (T-84)
"""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
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
import photo_hash as PH   # noqa: E402  (единственный писатель хеша фото, план mesh-14)
import pool_gate as PG    # noqa: E402  (ворота пула и граница 0.65)

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


class FatalBackend(RuntimeError):
    """Источник маски не ответит ни на одно фото (баланс, блок учётки) — повторять и идти дальше бессмысленно."""


def fal_fatal(code: int, body: str) -> str | None:
    """Причина остановки ВСЕГО прогона по ответу fal или None. 403 у fal бывает и за темп (тогда повторяем), и за
    исчерпанный баланс — «User is locked. Reason: Exhausted balance» (05→06.11: 7 ч молча шли по отказам, T-46). Чистая."""
    low = (body or '').lower()
    if code in (401, 403) and ('locked' in low or 'exhausted balance' in low or ('balance' in low and 'top up' in low)):
        return f'fal: учётка заблокирована — {body.strip()[:160]} (пополнить баланс: fal.ai/dashboard/billing)'
    return None


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
            try:
                body = e.read().decode('utf-8', 'replace')
            except Exception:  # noqa: BLE001 — тело ответа только для причины
                body = ''
            fatal = fal_fatal(e.code, body)
            if fatal:
                raise FatalBackend(fatal) from e
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
# РЕВИЗИЯ ВЕСОВ И КОДА BiRefNet ЗАКРЕПЛЕНА (T-46/3): модель грузится с trust_remote_code=True, а без ревизии transformers
# тянет свежий birefnet.py из репозитория автора — чужой код исполняется у нас без проверки. Хеш — снимок, прошедший пробу
# 3/3 и массовую добивку 06.11 (~/.cache/huggingface/hub/models--ZhengPeng7--BiRefNet/refs/main). Смена — только с пробой.
BIREFNET_REPO = 'ZhengPeng7/BiRefNet'
BIREFNET_REVISION = 'e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4'


def mask_local(raw: bytes) -> Image.Image:
    """BiRefNet на CPU. Веса те же (`ZhengPeng7/BiRefNet`), но в float32: fp16 на CPU не считается."""
    global _LOCAL
    src = Image.open(io.BytesIO(raw)).convert('RGB')
    if _LOCAL is None:
        import torch
        from torchvision import transforms
        from transformers import AutoModelForImageSegmentation
        m = AutoModelForImageSegmentation.from_pretrained(
            BIREFNET_REPO, trust_remote_code=True, revision=BIREFNET_REVISION)
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
# Ворота пула и граница качества — `pool_gate.py` (одно место; 0.65 включительно, план mesh-14).
POOL_SQL = PG.POOL_SQL


def pool_size() -> int:
    return int(db('select count(*)' + POOL_SQL)[0][0])


def sync_photos(limit: int) -> int:
    """Хеш байтов фото — теперь `photo_hash.sync` (ЕДИНСТВЕННЫЙ писатель `product_photo_current`, план mesh-14).

    Раньше хешировали здесь и только пул подбора (качество ≥ 0.65), а меш нужен и товарам ниже порога: 405
    представителей `mesh_required` остались без хеша, готовые меши висели в вечном stale. Кого хешировать и в каком
    порядке (сначала mesh-товары stale/none, потом пул; HD в приоритете) — решает `photo_hash.targets_sql`."""
    return PH.sync(limit)['hashed']


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


# ТОВАРЫ КОМНАТ (room-pipeline-01 В-2, T-46): спальня и прихожая живут в `room_catalog`, а `todo` знает только `products`.
# Кого брать и с какой ролью — `photo_hash.pick_rooms` (одно правило на хеш и вырезку); `todo` гостиной не тронут.
# Комнаты идут ПОСЛЕ гостиной и своим лимитом (`--rooms-limit N` / `CUTOUT_ROOMS_MAX`, по умолчанию 0 — ночь та же).
ROOMS_MAX = int(os.environ.get('CUTOUT_ROOMS_MAX', '0'))


def rooms_todo(limit: int, skip_shas: set) -> list[tuple[str, str, str, str]]:
    """(sku, role, image_url, source_sha) товаров комнат без вырезки текущей версии; sha, уже стоящие у гостиной, — мимо."""
    if limit <= 0:
        return []
    picked, _ = PH.pick_rooms(PH.parse_room_rows(db(PH.rooms_rows_sql(PRE.ASSESSOR_VERSION))))
    return PH.room_cutout_jobs(picked, skip_shas, limit)


STOP = threading.Event()   # поднят — оставшиеся работы прогона не начинаются (баланс, N отказов подряд)
FAIL_STREAK_MAX = int(os.environ.get('CUTOUT_FAIL_STREAK', '10'))
PROGRESS_EVERY = 50


def one(job) -> tuple[str, str | None]:
    sku, role, url, sha = job
    dst = os.path.join(CACHE, sha + '.png')
    if STOP.is_set():
        return 'skipped', None
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
    except FatalBackend as e:
        STOP.set()
        return 'fatal', str(e)
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
    PH.print_rooms_stats(PRE.ASSESSOR_VERSION)


def run_jobs(jobs: list[tuple[str, str, str, str]], label: str = '', fn=None) -> dict:
    """Прогон работ с предохранителями (T-46/3): источник маски сказал «баланс исчерпан» — стоп сразу; FAIL_STREAK_MAX
    отказов подряд — стоп; ход — каждые PROGRESS_EVERY фото. Остановленный прогон печатает `WARN:cutout:` (дайджест) и
    не валит ночную цепочку: оставшиеся просто ждут следующего раза. `fn` — подмена `one` для теста."""
    fn = fn or one
    STOP.clear()
    print(f'к вырезке{label}: {len(jobs)} (источник {BACKEND}, потоков {WORKERS})', flush=True)
    stat, errs = {'ok': 0, 'fail': 0, 'moved': 0, 'skipped': 0, 'fatal': 0}, []
    streak, why, done = 0, None, 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for st, err in ex.map(fn, jobs):
            stat[st] += 1
            done += 1
            if err:
                errs.append(err)
            if st == 'fatal' and not why:
                why = err
            streak = streak + 1 if st == 'fail' else 0 if st == 'ok' else streak
            if streak >= FAIL_STREAK_MAX and not why:
                why = f'{streak} отказов подряд — последний: {err}'
                STOP.set()
            if done % PROGRESS_EVERY == 0 and st != 'skipped':
                print(f"  ход{label}: {done}/{len(jobs)} · вырезано {stat['ok']} · отказов {stat['fail']} · "
                      f"фото сменилось {stat['moved']}", flush=True)
    print(f"вырезано{label} {stat['ok']}, фото сменилось у {stat['moved']}, отказов {stat['fail']}"
          + (f", не начато {stat['skipped']}" if stat['skipped'] else ''))
    if why:
        print(f'WARN:cutout: прогон остановлен — {why}', flush=True)
    for e in errs[:10]:
        print('   ✗', e)
    stat['stopped'] = why
    return stat


def rooms_only(rooms_max: int) -> int:
    """НОЧНОЙ ШАГ КОМНАТ (план room-conveyor-02 К1, T-20261106-84): хеши фото товаров комнат (`PHOTO_ROOMS_LIMIT`) и вырезка
    (`CUTOUT_ROOMS_MAX` / `--rooms-limit`, 0 = только хеши) — после каталогов комнат, гостиную не трогает (её хеши и вырезка —
    шаг `cutout`). Отказы считаются; есть отказы — строка WARN (шаг warn, ночь идёт дальше), товар ждёт следующей ночи."""
    h = PH.sync_rooms(PH.ROOMS_LIMIT)
    print(f"хеши фото комнат: целей {h['targets']}, посчитано {h['hashed']}, отказов {h['failed']}", flush=True)
    rjobs = rooms_todo(rooms_max, set())
    # итог `run_jobs` читаем через .get: стоп источника маски (баланс fal, отказы подряд — T-20261105-46/3) печатает свой WARN
    st = run_jobs(rjobs, ' (комнаты)') if rjobs else {}
    if not rjobs:
        print('вырезка комнат: ' + ('актуальна — считать нечего' if rooms_max > 0 else 'выключена (CUTOUT_ROOMS_MAX=0)'))
    if h['failed'] or st.get('fail'):
        print(f"WARN:rooms_cutout: отказов — хеш {h['failed']} из {h['targets']}, вырезка {st.get('fail', 0)} из {len(rjobs)} "
              '(ждут следующей ночи)', flush=True)
    return 0


def _selftest() -> int:
    """Предохранители прогона на заглушке (без сети и базы). Не в CI: модуль тянет torch через preprocess."""
    global FAIL_STREAK_MAX, PROGRESS_EVERY
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    body = '{"detail":"User is locked. Reason: Exhausted balance. Top up your balance at fal.ai/dashboard/billing."}'
    ok('403 «Exhausted balance» — стоп всего прогона', bool(fal_fatal(403, body)))
    ok('403 за темп и 429 — не стоп (повторяем)', fal_fatal(403, 'Forbidden') is None and fal_fatal(429, body) is None)
    jobs = [(f'1:{i}', 'кровать', '//u', f's{i}') for i in range(200)]
    seen = []

    def stub_fatal(job):            # как `one`: стоп поднят — работа не начинается
        if STOP.is_set():
            return 'skipped', None
        seen.append(job[0])
        if job[0] == '1:3':
            STOP.set()
            return 'fatal', 'fal: учётка заблокирована'
        return 'ok', None
    old_w, old_s, old_p = globals()['WORKERS'], FAIL_STREAK_MAX, PROGRESS_EVERY
    globals()['WORKERS'], PROGRESS_EVERY = 1, 1000
    st = run_jobs(jobs, ' (тест)', fn=stub_fatal)
    ok('баланс: остановились на 4-м фото, остальные 196 не начаты, причина в итоге',
       len(seen) == 4 and st['ok'] == 3 and st['skipped'] == 196 and 'заблокирована' in (st['stopped'] or ''))
    FAIL_STREAK_MAX, calls = 10, []

    def stub_fail(job):
        if STOP.is_set():
            return 'skipped', None
        calls.append(job[0])
        time.sleep(0.005)               # фото режется не мгновенно — иначе поток убегает от счёта главного на все 200
        return ('ok', None) if job[0] in ('1:0', '1:5') else ('fail', f'{job[0]}: HTTPError 500')
    st = run_jobs(jobs, ' (тест)', fn=stub_fail)
    # счёт ведёт главный поток, поэтому заглушка без пауз успевает «перебежать» на несколько работ — в жизни это фото в полёте
    ok('10 отказов подряд — стоп; удачный сбрасывает счёт (1:5): стоп не раньше 16-го, почти всё не начато',
       16 <= len(calls) < 40 and st['skipped'] > 150 and (st['stopped'] or '').startswith('10 отказов подряд'))
    PROGRESS_EVERY = 50
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        st = run_jobs(jobs[:120], ' (тест)', fn=lambda j: ('ok', None))
    ok('ход печатается каждые 50 фото, без стопа', buf.getvalue().count('ход (тест):') == 2 and st['stopped'] is None)
    globals()['WORKERS'], FAIL_STREAK_MAX, PROGRESS_EVERY = old_w, old_s, old_p
    STOP.clear()
    # ревизия BiRefNet доходит до from_pretrained (заглушка transformers: ни сети, ни весов)
    import types
    got = {}

    class _Stop(Exception):
        pass

    class _Auto:
        @staticmethod
        def from_pretrained(repo, **kw):
            got.update(kw, repo=repo)
            raise _Stop
    global _LOCAL
    saved, saved_local = sys.modules.get('transformers'), _LOCAL
    sys.modules['transformers'], _LOCAL = types.SimpleNamespace(AutoModelForImageSegmentation=_Auto), None
    try:
        buf = io.BytesIO()
        Image.new('RGB', (4, 4)).save(buf, 'PNG')
        mask_local(buf.getvalue())
    except _Stop:
        pass
    finally:
        if saved is None:
            sys.modules.pop('transformers', None)
        else:
            sys.modules['transformers'] = saved
        _LOCAL = saved_local
    ok('BiRefNet: ревизия закреплена полным хешем и передаётся в from_pretrained',
       re.fullmatch(r'[0-9a-f]{40}', BIREFNET_REVISION) is not None and got.get('revision') == BIREFNET_REVISION
       and got.get('repo') == BIREFNET_REPO and got.get('trust_remote_code') is True)
    print(f'cutout_sync selftest: ошибок {bad}')
    return 1 if bad else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    if '--report' in sys.argv:
        report()
        return 0
    if BACKEND not in BACKENDS:
        print(f'неизвестный источник маски: {BACKEND}')
        return 1
    rooms_max = int(sys.argv[sys.argv.index('--rooms-limit') + 1]) if '--rooms-limit' in sys.argv else ROOMS_MAX
    if '--rooms-only' in sys.argv:
        return rooms_only(rooms_max)
    added = sync_photos(int(os.environ.get('CUTOUT_SHA_MAX', '400')))
    if added:
        print(f'посчитано хешей фото: {added}', flush=True)
    jobs = todo(DAILY_MAX)
    if not jobs:
        print('вырезки актуальны — считать нечего')
    elif run_jobs(jobs).get('stopped'):
        return 0   # источник маски встал (баланс, отказы подряд) — комнатам идти некуда; причина уже в WARN
    # Комнаты — после гостиной, своим лимитом (T-46); при 0 шаг молчит, вывод гостиной прежний.
    rjobs = rooms_todo(rooms_max, {j[3] for j in jobs})
    if rjobs:
        run_jobs(rjobs, ' (комнаты)')
    elif rooms_max > 0:
        print('вырезки комнат актуальны — считать нечего')
    # Отказы не валят ночную цепочку: товар без вырезки просто ждёт следующего прогона.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
