"""Фото нейросети из тура пробы для агентов (план agent-trial-08 § «Правило фото»; T-20261109-34) — что сервис кадров делает иначе, чем для
`/demo`, когда в заказе есть `trial` (id задания; ставит ручка `app/api/trial/[id]/photo`):

* суточный предел на задание `TRIAL_PHOTO_DAILY` (10) — второй замок к счёту в базе приложения: прямой запрос в `/api/render` с `trial`
  мимо ручки тоже в него упирается (`TrialDaily`, файл рядом с реестром кадров);
* только по двум кадрам из 3D браузера (`views`): серверной сцены для тура нет — без 3D фото нет (`no_views`);
* фото товаров — из каталога DEV по модели (`msid` → `products.image_url`, `fill_imgs`): в данных тура полей магазина нет совсем, а ссылкам
  со страницы не верим; сами картинки — из копий витрины на нашем сервере или из магазина с повторами (`warm_photos`);
* метка расхода `trial` (`photo-cost.jsonl`), в общий реестр кадров демо не пишется, запасного рендера на проде нет.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TRIAL_RE = re.compile(r'^[A-Za-z0-9_-]{22}$')
DAY_S = 86400


def trial_id(payload: dict) -> str | None:
    """id задания пробы из заказа: нет поля — None (заказ демо); кривое значение — '' (заказ отклоняется `bad_trial`, не идёт как демо)."""
    t = payload.get('trial')
    return t if isinstance(t, str) and TRIAL_RE.match(t) else (None if t in (None, '', False) else '')


def daily_limit(env=os.environ) -> int:
    try:
        n = int(env.get('TRIAL_PHOTO_DAILY') or 10)
    except ValueError:
        n = 10
    return min(max(n, 1), 100)


def has_views(payload: dict) -> bool:
    vs = payload.get('views')
    return isinstance(vs, list) and len(vs) >= 2 and all(isinstance(v, dict) and isinstance(v.get('id'), str) for v in vs[:2])


def _rnd(v) -> int:
    """Как `Math.round(+v||0)` на странице: половина — вверх, не число — 0."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0
    return 0 if math.isnan(x) or math.isinf(x) else math.floor(x + 0.5)


def room_sig(room) -> str:
    """Подпись комнаты: размеры и проёмы — тот же порядок, что `roomSig` страницы (`flat215-demo/index.html`)."""
    if not isinstance(room, dict):
        return ''
    ops = [o for o in (room.get('openings') or []) if isinstance(o, dict)]
    s = lambda v: '' if v is None else str(v)
    parts = sorted(':'.join([s(o.get('kind')), s(o.get('wall')), str(_rnd(o.get('offset_cm'))), str(_rnd(o.get('width_cm')))]) for o in ops)
    return f"{_rnd(room.get('w'))}x{_rnd(room.get('d'))}|" + ';'.join(parts)


def views_room_mismatch(payload: dict) -> bool:
    """КАДРЫ ЧУЖОЙ КОМНАТЫ (T-20261112-108/2, заказ f24c0cc7): кадр из 3D несёт подпись комнаты сцены (`views[].room`); она не равна
    комнате заказа — фото нарисовалось бы в чужих стенах, заказ не принимаем. Кадр без подписи (страница до правила) — пропускаем."""
    vs = payload.get('views')
    if not isinstance(vs, list):
        return False
    want = room_sig(payload.get('room'))
    return any(isinstance(v, dict) and isinstance(v.get('room'), str) and v['room'] and v['room'] != want for v in vs)


class TrialDaily:
    """Счёт заказов по заданию за скользящие сутки — JSON-файлом {id: [время, …]} под замком процесса; запись — подменой файла.
    Файл не читается (битый) — начинаем с пустого: лишний заказ дешевле, чем тур без фото навсегда."""

    def __init__(self, path: str, limit: int):
        self.path, self.limit, self.lock = path, limit, threading.Lock()

    def _load(self) -> dict:
        try:
            with open(self.path, encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def take(self, tid: str, now: float | None = None) -> bool:
        """Есть место — учесть заказ и True; предел исчерпан — False (ничего не пишем)."""
        now = time.time() if now is None else now
        with self.lock:
            d = {k: [t for t in v if isinstance(t, (int, float)) and now - t < DAY_S] for k, v in self._load().items() if isinstance(v, list)}
            d = {k: v for k, v in d.items() if v}
            if len(d.get(tid, [])) >= self.limit:
                return False
            d.setdefault(tid, []).append(now)
            os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            tmp = f'{self.path}.{os.getpid()}.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(d, f)
            os.replace(tmp, self.path)
            return True


# ───────── фото товаров по модели ─────────

_IMG_CACHE: dict = {}
_IMG_LOCK = threading.Lock()
_KEY_RE = re.compile(r'^(\d{1,9})[_:](.{1,80})$')


def _split(msid: str) -> tuple[int, str] | None:
    m = _KEY_RE.match(msid or '')
    return (int(m.group(1)), m.group(2)) if m else None


def catalog_imgs(msids: list, fetch=None) -> dict:
    """msid (`<shop_mid>_<external_id>`) → фото товара из `products` каталога DEV; нет строки или фото — нет ключа. Кэш процесса
    (и отсутствующих). База не читается — пусто: лист товаров не соберётся, и `paid_gate` откажет ДО оплаты."""
    keys = {m: _split(m) for m in set(msids) if isinstance(m, str)}
    with _IMG_LOCK:
        need = {m: k for m, k in keys.items() if k and m not in _IMG_CACHE}
    if need:
        try:
            if fetch is None:
                import catalog_items as CI
                fetch = CI.fetch
            from catalog_items import _lit
            pairs = ','.join(f'({mid},{_lit(eid)})' for mid, eid in need.values())
            rows = fetch(f'select shop_mid, external_id, image_url from products where (shop_mid, external_id) in ({pairs})')
            got = {(int(r[0]), r[1]): r[2] for r in rows if r and r[2]}
        except Exception as e:  # noqa: BLE001 — сбой базы: фото не подставили, платный вызов не случится (paid_gate)
            print(f'  фото товаров тура: каталог не прочитан — {str(e)[:120]}', flush=True)
            return {m: _IMG_CACHE[m] for m in keys if _IMG_CACHE.get(m)}
        with _IMG_LOCK:
            if len(_IMG_CACHE) > 5000:
                _IMG_CACHE.clear()
            for m, k in need.items():
                _IMG_CACHE[m] = got.get(k)
    with _IMG_LOCK:
        return {m: _IMG_CACHE[m] for m in keys if _IMG_CACHE.get(m)}


def photo_sources(u: str, base: str) -> list:
    """Откуда брать фото товара для листа, по порядку: копия витрины на нашем сервере (`flat215_demo` кладёт её в `/demo/img/` под
    `md5(адрес)[:16]` — крупная `-l.jpg`, затем плитка), затем сам адрес магазина. Магазин (`imgng.gdeslon.ru`) отвечает 403 через раз."""
    n = hashlib.md5(u.encode()).hexdigest()[:16]
    full = ('https:' + u) if u.startswith('//') else u
    return ([f'{base}/demo/img/{n}-l.jpg', f'{base}/demo/img/{n}.jpg'] if base else []) + [full]


def _get(url: str, tries: int) -> bytes | None:
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://remont-lab.online/'})
            with urllib.request.urlopen(req, timeout=15) as f:
                return f.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                      # копии нет — следующий источник, без повторов
        except Exception:  # noqa: BLE001 — сеть: повтор, затем следующий источник
            pass
        if k < tries - 1:
            time.sleep(1.0)
    return None


def warm_photos(urls, cache_dir: str, base: str, get=_get) -> int:
    """Кладёт фото товаров в кэш `draft_render.photo` (`<cache>/<md5(адрес)[:16]>.png`, тот же ключ и размер), беря их из
    `photo_sources`; сам `photo` делает одну попытку без Referer и молча теряет фото магазина. → сколько фото в кэше."""
    from PIL import Image
    os.makedirs(cache_dir, exist_ok=True)

    def one(u: str) -> bool:
        p = os.path.join(cache_dir, hashlib.md5(u.encode()).hexdigest()[:16] + '.png')
        if os.path.exists(p):
            return True
        for i, src in enumerate(photo_sources(u, base)):
            raw = get(src, 1 if i < 2 and base else 3)
            if not raw:
                continue
            try:
                im = Image.open(io.BytesIO(raw)).convert('RGB')
            except Exception:  # noqa: BLE001 — не картинка: следующий источник
                continue
            im.thumbnail((640, 640))
            tmp = f'{p}.{os.getpid()}.{threading.get_ident()}.tmp'
            im.save(tmp, 'PNG')
            os.replace(tmp, p)
            return True
        return False
    todo = sorted({u for u in urls if isinstance(u, str) and u})
    with ThreadPoolExecutor(max_workers=6) as ex:
        return sum(ex.map(one, todo))


# ───────── готовое фото — туру (T-20261112-115 Ф1) ─────────
# Раньше готовое фото тура видела только вкладка, которая его заказала (опрос `/api/job`): после перезагрузки его не было. Теперь по
# готовности фонового задания кадры уходят приложению (`POST /api/trial/worker/<id>/photo`, сеть remlab-net, ключ INTERNAL_API_TOKEN —
# как заявка «отправить себе»): оно кладёт файлы в папку тура и отмечает заказ готовым; сбой задания — `failed` с кодом.
REPORT_URL = os.environ.get('TRIAL_PHOTO_SINK_URL', 'http://remlab-app:3000/api/trial/worker/{id}/photo')
REPORT_DELAYS = (0, 5, 20, 60)            # строка заказа пишется сразу после номера задания — 404 в первые секунды повторяем
SHOT_MAX = 6 * 1024 * 1024                # = contracts/trial-photos.ts:PHOTO_MAX_BYTES
THUMB_MAX = 1024 * 1024                   # = PHOTO_THUMB_MAX_BYTES
CODE_RE = re.compile(r'^[a-z_]{1,40}$')


def _read_small(path: str, limit: int) -> bytes | None:
    """Обычный файл не больше `limit` (симлинк и папка — нет)."""
    try:
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > limit:
            return None
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return None


def report_body(jid: str, out: dict | None, frames_dir: str, thumb_name, code: str = '') -> dict:
    """Тело для приложения: готово — кадры файлами из `frames_dir` (имя — из адреса кадра, миниатюра рядом); кадров нет на диске —
    `failed`/`no_file`; сбой задания — `failed` с кодом (кривой код — `draft_failed`)."""
    import base64
    if out is not None:
        shots = []
        for sh in (out.get('shots') or [])[:4]:
            name = str((sh or {}).get('url') or '').rsplit('/', 1)[-1]
            cam = str((sh or {}).get('camera') or '')
            if not name or '..' in name or not re.match(r'^C[1-4]$', cam):
                continue
            img = _read_small(os.path.join(frames_dir, name), SHOT_MAX)
            if not img:
                continue
            rec = {'camera': cam, 'img': base64.b64encode(img).decode()}
            th = _read_small(os.path.join(frames_dir, thumb_name(name)), THUMB_MAX)
            if th:
                rec['thumb'] = base64.b64encode(th).decode()
            shots.append(rec)
        if shots:
            return {'draft_job': jid, 'status': 'done', 'shots': shots}
        code = 'no_file'
    return {'draft_job': jid, 'status': 'failed', 'code': code if CODE_RE.match(code or '') else 'draft_failed'}


def _post(url: str, body: dict, token: str) -> int:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'x-internal-token': token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def report(tid: str, body: dict, token: str | None = None, post=_post, sleep=time.sleep, delays=REPORT_DELAYS) -> bool:
    """Отдать готовое (или сбой) приложению: 200 — True; 404 (строки ещё нет), 5xx, обрыв — повтор по `delays`; прочие 4xx — сразу
    False. Каждый исход — строка в журнал (без кадров)."""
    token = os.environ.get('INTERNAL_API_TOKEN', '') if token is None else token
    tag = f'фото тура {tid[:6]}… задание {body.get("draft_job")}: {body.get("status")}'
    if not token:
        print(f'{tag} — не отдано туру: нет INTERNAL_API_TOKEN', flush=True)
        return False
    url = REPORT_URL.replace('{id}', tid)
    st = 0
    for d in delays:
        if d:
            sleep(d)
        try:
            st = post(url, body, token)
        except Exception as e:  # noqa: BLE001 — сеть: повтор, итог — в журнал
            print(f'{tag} — сеть: {str(e)[:120]}', flush=True)
            st = 0
            continue
        if st == 200:
            print(f'{tag} — отдано туру', flush=True)
            return True
        if st != 404 and st < 500:
            break
    print(f'{tag} — не отдано туру (HTTP {st})', flush=True)
    return False


def fill_imgs(payload: dict, lookup=catalog_imgs) -> tuple[int, int]:
    """Фото товаров заказа тура — только из каталога по `msid` (ссылки страницы снимаются). → (предметов, из них с фото)."""
    items = [it for it in payload.get('items') or [] if isinstance(it, dict)]
    for it in items:
        for k in ('img', 'img_hd', 'url', 'url_direct', 'shop', 'price'):
            it.pop(k, None)
    imgs = lookup([it.get('msid') for it in items if it.get('msid')])
    n = 0
    for it in items:
        u = imgs.get(it.get('msid'))
        if u:
            it['img'] = u
            n += 1
    return len(items), n
