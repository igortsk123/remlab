#!/usr/bin/env python3
"""СЕРВИС ЧЕРНОВОГО РЕНДЕРА — то, что нельзя отдать браузеру (26.08).

Ключ fal живёт только на сервере, поэтому страница присылает СВОЮ расстановку, а сервис считает
сцену, собирает коллаж с фотографиями товаров и делает один вызов модели.

  POST /draft  {"room":{...},"items":[{role,x,y,rot,w,d,h,img}]}  → {"url": "...", "sec": 15.2}
  POST /warm   {}                                                 → {"sec": 12.4}
  GET  /health                                                    → ok

Запуск: DRAFT_PORT=8099 ~/venvs/scout/bin/python draft_service.py
"""
import hashlib
import html
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

import draft_render as DR  # noqa: E402

MAX_BODY = 2 << 20
FRAME_MAX = 4 << 20          # кадр из браузера (demo-10): JPEG 2048×1489 q0.85 ≈ 0.3–0.8 МБ
# Каталог подборок монтируется из `/opt/remlab/test/share` — Caddy уже отдаёт его как /test/share/*
SHARE_DIR = os.environ.get('SHARE_DIR', os.path.join(HERE, 'share'))
PUBLIC_BASE = os.environ.get('PUBLIC_BASE', 'https://remont-lab.online')
TG_BOT = os.environ.get('SHARE_TG_BOT', '')        # имя бота без @; пусто — канал не подключён
MAX_BOT = os.environ.get('SHARE_MAX_BOT', '')
SMS_GATE = os.environ.get('SHARE_SMS_GATE', '')   # шлюз СМС; пусто — канал не подключён
esc = html.escape
from draft_guard import (ALLOWED_ORIGINS, ip_allowed,  # noqa: E402
                         queue_eta, registry_trim, safe_url, save_share_request)
from draft_jobs import JobStore, public_view  # noqa: E402
SHARE_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{{TITLE}} — подборка</title>
<style>
:root{color-scheme:light}
body{margin:0;background:#fff;color:#1A1F1C;font:17px/1.5 system-ui,-apple-system,Segoe UI,Roboto}
.wrap{max-width:1100px;margin:0 auto;padding:18px 16px 48px}
h1{font-size:clamp(24px,4.4vw,32px);margin:6px 0 4px}
.sub{color:#5C655E;font-size:16px;margin-bottom:16px}
.grid{display:grid;gap:26px;grid-template-columns:1fr}
@media(min-width:900px){.grid{grid-template-columns:1fr 1fr}}
.sum{display:flex;justify-content:space-between;font-weight:700;margin:10px 0 6px;font-size:16px}
.ps-grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
.p{border:1px solid #E4E6E2;border-radius:10px;padding:8px;text-decoration:none;color:inherit;
 display:block;background:#fff}
.p:hover{border-color:#3B76A2}
.p img,.p .noimg{width:100%;aspect-ratio:4/3;object-fit:contain;background:#F7F5F1;border-radius:7px}
.p .noimg{display:flex;align-items:center;justify-content:center;color:#A6ABA4;font-size:12px}
.p .pn{font-size:13.5px;line-height:1.3;margin-top:6px;max-height:36px;overflow:hidden}
.p .pp{font-size:15px;font-weight:700;margin-top:3px}
.p .ps{font-size:12px;color:#5C655E}
figure{margin:0}
img{width:100%;border-radius:12px;display:block;background:#F2F0EB}
figcaption{font-size:14px;color:#5C655E;margin-top:6px}
.foot{margin-top:28px;font-size:14px;color:#8A8F89}
</style></head><body><div class="wrap">
<h1>{{TITLE}}</h1>
<div class="sub">Ваша коллекция · фотографий: {{COUNT}}. Под каждым кадром — товары с ценами и
ссылками в магазин.</div>
<div class="grid">{{CARDS}}</div>
<div class="foot">Сделано в планировщике remont-lab.online. Фотографии сгенерированы по вашей
расстановке; товары — из каталогов магазинов-партнёров.</div>
</div></body></html>"""
# английская страница подборки при маске (demo-31): без слов о магазинах и ссылках
SHARE_PAGE_EN = (SHARE_PAGE.replace('<html lang="ru">', '<html lang="en">').replace('— подборка</title>', '— collection</title>')
                 .replace('''<div class="sub">Ваша коллекция · фотографий: {{COUNT}}. Под каждым кадром — товары с ценами и
ссылками в магазин.</div>''', '<div class="sub">Your collection · photos: {{COUNT}}. Under each photo — the items with prices.</div>')
                 .replace('''<div class="foot">Сделано в планировщике remont-lab.online. Фотографии сгенерированы по вашей
расстановке; товары — из каталогов магазинов-партнёров.</div>''', '<div class="foot">Made in the remont-lab.online planner. '
                          'The photos are generated from your layout.</div>'))
# СТРАНИЦА ПОДБОРКИ «отправить себе». КОЛЛЕКЦИЯ = ФОТО + ТОВАРЫ СО ССЫЛКАМИ (владелец 26.08: «человек должен получать
# коллекции»): под каждым кадром — что на нём стоит, почём и где купить. БРИТАНСКАЯ МАСКА АНГЛИЙСКОГО ДЕМО (demo-31, владелец 30.10):
# страница демо при маске шлёт уже готовое — английские название и роль, цену в валюте карточки, без магазина и ссылки — и
# `mask: true`, `currency`, `lang`; тогда страница по-английски, в £ и без ссылок в магазин. Без маски — как было (₽, магазин, ссылка).
# Тест — `tools/scout/tests/test_share_mask.py`.
def _share_opts(payload):
    mask = payload.get('mask') is True
    return {'mask': mask, 'gbp': mask and str(payload.get('currency') or '') == 'GBP', 'en': mask and payload.get('lang') == 'en'}


def _share_money(v, o):
    n = int(v or 0)
    return f'\u00a3{n:,}' if o['gbp'] else f'{n:,}'.replace(',', ' ') + ' \u20bd'


def _share_prod(p, o):
    img, href = safe_url(p.get('img')), ('' if o['mask'] else safe_url(p.get('url')))
    pic = (f'<img src="{esc(img)}" alt="" loading="lazy">'
           if img else f'<div class="noimg">{"no photo" if o["en"] else "фото нет"}</div>')
    shop = '' if o['mask'] else p.get('shop')
    inner = (pic + f'<div class="pn">{esc(p.get("name") or "")}</div>'
             f'<div class="pp">{_share_money(p.get("price"), o)}</div>'
             f'<div class="ps">{esc(p.get("role") or "")}'
             + (f' \u00b7 {esc(shop)}' if shop else '') + '</div>')
    return (f'<a class="p" href="{esc(href)}" target="_blank" rel="noopener">{inner}</a>'
            if href else f'<div class="p">{inner}</div>')


def _share_block(sh, o):
    items = [p for p in (sh.get('items') or []) if isinstance(p, dict) and p.get('name')]
    total = sum(int(p.get('price') or 0) for p in items)
    head = (f'<div class="sum"><span>{"Items in the photo" if o["en"] else "Товары на фото"} \u00b7 {len(items)}</span>'
            f'<span>{_share_money(total, o)}</span></div>' if items else '')
    grid = ('<div class="ps-grid">' + ''.join(_share_prod(p, o) for p in items) + '</div>') if items else ''
    return (f'<figure><img src="{esc(safe_url(sh["url"]))}" alt="{esc(sh.get("label") or "")}" '
            f'loading="lazy"><figcaption>{esc(sh.get("label") or "")}</figcaption>'
            f'{head}{grid}</figure>')


def _share_page(payload, shots):
    o = _share_opts(payload)
    cards = '\n'.join(_share_block(sh, o) for sh in shots)
    page = SHARE_PAGE_EN if o['en'] else SHARE_PAGE
    return (page.replace('{{TITLE}}', esc(payload.get('title') or ('Your room' if o['en'] else 'Ваша комната')))
                .replace('{{CARDS}}', cards)
                .replace('{{COUNT}}', str(len(shots))))


_LOCK = threading.Semaphore(2)          # два одновременных рендера: больше не нужно, ключ общий
_LAST_WARM = [0.0]
# ПРЕДОХРАНИТЕЛЬ РАСХОДА (26.08): эндпоинт публичный, а каждый рендер — деньги на fal. Больше
# HOURLY_CAP рендеров в час сервис не делает и честно об этом отвечает.
HOURLY_CAP = int(os.environ.get('DRAFT_HOURLY_CAP', 60))
_HITS: list = []


# ФОНОВЫЕ ЗАДАНИЯ (владелец 01.09: «периодами пишет ошибку»; на деле мобильный браузер рвёт
# минутный запрос — сервер досчитывает и отдаёт 200, а человек видит «Load failed»). Держать
# соединение минуту на телефоне нельзя в принципе. Поэтому: запрос ставится в очередь и сразу
# возвращает номер, страница потом спокойно спрашивает «готово?». Гаснущий экран, смена сети и
# закрытая вкладка перестают что-либо ломать.
# ЗАДАНИЯ — В ФАЙЛЕ РЯДОМ С РЕЕСТРОМ КАДРОВ (demo-03, 14.10): деплой пересоздаёт контейнер, и словарь в памяти
# пропадал вместе с ним — страница получала 404 на свой номер. Подробности и правила перезапуска — `draft_jobs.py`.
JOBS = JobStore(os.path.join(os.path.dirname(DR.FRAMES_DIR), 'jobs.json'))
# ДЕНЬГИ НА ПЛАТНОЕ УЛУЧШЕНИЕ ПРОВЕРЯЮТСЯ ДО ЗАДАНИЯ (demo-03, 14.10; разбор Codex): порог — цена кадра с запасом,
# а не ноль; идущие платные задания резервируют свою цену. Проверка лишь советует — истина остаётся за ответом шлюза.
PAID_MIN_USD = float(os.environ.get('REALISTIC_MIN_BALANCE', '0.30'))
PAID_COST_USD = float(os.environ.get('REALISTIC_COST_USD', '0.25'))
# ОЧЕРЕДЬ ЛОКАЛЬНОГО РЕНДЕРА (b2b-08 п.3). Раньше занятый сервер отвечал «другой рендер, попробуйте через минуту» —
# второй человек получал ошибку вместо ожидания. Фоновое задание теперь ЖДЁТ места (до QUEUE_WAIT_S), а страница
# видит своё место в очереди и оценку времени по последним замерам (`_DURS`, секунды на кадр по качеству).
# Сама очередь — в `JOBS` (под тем же замком, что и задания).
_DURS: dict = {'draft': [], 'realistic': []}
QUEUE_WAIT_S = int(os.environ.get('DRAFT_QUEUE_WAIT_S', 600))

_REG_LOCK = threading.Lock()


def _group_items(items: list) -> list:
    """ОДИН ТОВАР — ОДНА СТРОКА (владелец 02.09: «когда стула 2, надо показывать 1 карточку, а в
    модели просто 2 ставить»). В расстановке два стула — это два СЛОТА одного товара; реестр
    писал каждый слот отдельной записью, и в списке под фотографией стул задваивался.
    Количество считаем по упаковке: «Стул АСТИ 2 шт.» при двух слотах — это ОДНА покупка.
    """
    import math
    by: dict = {}
    for i in items:
        if not i.get('name'):
            continue
        k = (i.get('url') or '') + '|' + (i.get('name') or '')
        if k not in by:
            by[k] = {'role': i.get('role'), 'name': i.get('name'), 'price': i.get('price'),
                     'url': i.get('url'), 'img': i.get('img'),
                     # товар и модель — чтобы список кадра можно было сверить с витриной (demo-02, раньше терялись)
                     'sid': i.get('sid'), 'msid': i.get('msid'),
                     'pack': i.get('pack') or 1, 'slots': 0}
        by[k]['slots'] += 1
    out = []
    for v in by.values():
        pack = int(v.pop('pack') or 1) or 1
        slots = v.pop('slots')
        v['qty'] = max(1, math.ceil(slots / pack))
        out.append(v)
    return out


_CROP_KEY = re.compile(r'^\d\.\d{3}$')


def _crop_clean(crop) -> dict | None:
    """ОКНО ПРЕВЬЮ КАДРА ЗАМОРАЖИВАЕТСЯ В ЗАПИСИ (demo-22 п.2, Codex 22.10): страница считает окна по 3D-модели расстановки
    (`camCrops`: пропорция → {x,y,w,h} в долях кадра + `keep` — id предметов целиком). Камеры потом подбираются заново,
    а превью готового фото должно резаться по окну ТОГО снимка. Сюда — только форма: до 6 пропорций, доли 0…1, `keep` ≤ 40 id."""
    if not isinstance(crop, dict):
        return None
    out = {}
    for k, v in list(crop.items())[:6]:
        if not (isinstance(k, str) and _CROP_KEY.match(k) and isinstance(v, dict)):
            continue
        try:
            box = {a: round(min(1.0, max(0.0, float(v[a]))), 3) for a in ('x', 'y', 'w', 'h')}
        except (KeyError, TypeError, ValueError):
            continue
        if box['w'] <= 0 or box['h'] <= 0:
            continue
        keep = v.get('keep')
        if isinstance(keep, list):
            box['keep'] = [str(i)[:64] for i in keep[:40] if isinstance(i, (str, int))]
        out[k] = box
    return out or None


def _cams_clean(cams) -> list:
    """Позы камер кадра (demo-02) + окно превью вида (`crop`, demo-22) — для записи в реестр."""
    out = []
    for c in (cams or [])[:4] if isinstance(cams, list) else []:
        if not isinstance(c, dict):
            continue
        rec = {k: c.get(k) for k in ('name', 'x', 'y', 'rot', 'fov', 'pose')}
        crop = _crop_clean(c.get('crop'))
        if crop:
            rec['crop'] = crop
        out.append(rec)
    return out


def _registry_add(payload: dict, out: dict) -> None:
    """РЕЕСТР КАДРОВ ЖИВЁТ НА СЕРВЕРЕ (владелец 01.09: «фото должны храниться на сервере и
    отдаваться на фронт быстро — это же классика»). Сами картинки и так лежали файлами, но связь
    «какой кадр к какому стилю» хранилась ТОЛЬКО в браузере: с другого устройства коллекция
    оказывалась пустой, а предгенерация вообще не имела смысла. Теперь запись делает сервер, а
    страница её просто читает."""
    if payload.get('no_registry'):
        return          # фоновый кадр коллекции покупателя (demo-03, 2.13) — не вариант витрины, в общую ленту не идёт
    try:
        path = os.path.join(os.path.dirname(DR.FRAMES_DIR), 'shots.json')
        import uuid
        sid = str(payload.get('stateId') or '')
        rec = {'style': payload.get('style') or '', 'variant': payload.get('variant') or '',
               'quality': out.get('quality') or payload.get('quality') or 'draft',
               'model': out.get('model') or '', 'sources': out.get('sources') or '',
               # чем нарисовано фото нейросети (demo-11): качество модели, версия и отпечаток промпта
               **({k: out[k] for k in ('image_quality', 'prompt_version', 'prompt_sha', 'sheet_orient') if out.get(k)}),
               'backend': out.get('backend') or '',
               # СОСТОЯНИЕ И КАМЕРЫ КАДРА (demo-02, Codex 14.10): номер состояния присылает страница (сервер его не
               # считает), позы камер — полностью: «C1» без позы ничего не говорит, если камеру потом переставили.
               # id записи — свой, а не время: два кадра в одну миллисекунду стирали друг друга.
               'id': uuid.uuid4().hex[:16],
               'stateId': sid if len(sid) <= 64 else '',
               # pose — версия позы ракурса (`draft_render.photo_pose_heights`): кадр со старой позой страница пересъёмет
               'cams': _cams_clean(payload.get('cams')),
               'ts': int(time.time() * 1000),
               'shots': [{'camera': sh.get('camera'), 'url': sh.get('url'),
                          'thumb': DR.thumb_name(sh['url']) if sh.get('url') else None}
                         for sh in (out.get('shots') or []) if sh.get('url')],
               'items': _group_items(payload.get('items') or [])}
        if not rec['shots']:
            return
        with _REG_LOCK:
            try:
                data = json.load(open(path, encoding='utf-8'))
            except Exception:  # noqa: BLE001
                data = []
            data = [x for x in data if x.get('id') != rec['id']]
            data.append(rec)
            data = registry_trim(data)             # реестр не растёт бесконечно, свежий кадр каждого стиля не вытесняется
            tmp = path + '.tmp'
            json.dump(data, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
            os.replace(tmp, path)
    except Exception as e:  # noqa: BLE001 — реестр не должен ронять ответ
        print(f'  реестр кадров не обновлён: {str(e)[:90]}')


def _proxy_url() -> str:
    prx = os.environ.get('RENDER_PROXY') or ''
    if not prx:
        try:
            cf = os.path.join(os.path.dirname(DR.FRAMES_DIR), 'render-proxy.conf')
            prx = open(cf, encoding='utf-8').read().strip() if os.path.exists(cf) else ''
        except Exception:  # noqa: BLE001
            prx = ''
    return prx


def _render_info() -> dict:
    """Чем рисует ЭТОТ процесс фото нейросети (demo-11): модель, качество, версия промпта."""
    try:
        import improve_mode as IM
        pv = IM.PROMPT_VERSION
    except Exception:  # noqa: BLE001
        pv = ''
    return {'realistic_model': DR.REALISTIC_MODEL, 'image_quality': os.environ.get('GPT_IMAGE_QUALITY', 'medium'), 'prompt_version': pv}


def _dry_info(payload: dict) -> dict:
    """Пробный ответ: что ушло бы в модель — у рисующего процесса (за туннелем, иначе этот) и какие блоки в промпте."""
    info = {'render': _render_info(), 'render_from': 'here'}
    prx = _proxy_url()
    if prx:
        try:
            import urllib.request as _u
            base = prx.rsplit('/render', 1)[0]
            info['render'] = json.loads(_u.urlopen(base + '/health', timeout=4).read().decode())
            info['render_from'] = 'proxy'
        except Exception as e:  # noqa: BLE001 — недоступный DEV — это ответ, а не падение
            info['render_from'] = f'proxy недоступен: {str(e)[:60]}'
    try:
        import improve_mode as IM
        # мягкое запроса (demo-24): что уйдёт третьим листом и словами — видно без оплаты
        soft = IM.soft_list(IM.soft_items(payload), len(DR.decor_split(payload)[1]) + 1, payload.get('items'))
        pr = IM.prompt_for(payload.get('style') or '', soft=soft)
        info['prompt'] = {'version': IM.PROMPT_VERSION, 'sha': IM.prompt_sha(pr), 'photo_look': 'PHOTOGRAPHIC LOOK' in pr,
                          'shape_rule': 'never invent detachable cushions, throws or armrests' in pr,
                          'soft_block': 'SOFT TEXTILES FROM IMAGE 3' in pr}
        info['soft'] = soft
    except Exception as e:  # noqa: BLE001
        info['prompt'] = {'error': str(e)[:80]}
    return info


def _has_gw_key() -> bool:
    try:
        return bool(DR.gw_key())
    except SystemExit:
        return False


def _credits_here() -> dict:
    """Баланс шлюза отсюда: {'balance': float|None, 'key': bool}."""
    key = _has_gw_key()
    return {'balance': DR.gw_credits() if key else None, 'key': key}


_GATE_CACHE: list = [0.0, None]


def _paid_gate_cached(max_age_s: float = 30.0):
    """То же, что `_paid_gate`, с кэшем 30 с: `/api/draft/paid` публичный, а каждый честный ответ — поход в DEV
    через туннель (до 4 с). Платный запрос сам проверяет без кэша."""
    if time.time() - _GATE_CACHE[0] > max_age_s:
        _GATE_CACHE[:] = [time.time(), _paid_gate()]
    return _GATE_CACHE[1]


def _paid_gate():
    """Можно ли сейчас ставить платное улучшение. None — можно; иначе (код, текст) для страницы СРАЗУ.

    Ключ шлюза на проде не лежит — платный кадр рисует DEV (прокси), поэтому прод спрашивает баланс у DEV.
    Сеть до шлюза моргнула — не блокируем (проверка советует). DEV не отвечает, а своего ключа нет — платный
    путь физически невозможен, честно говорим сразу, а не через 5 минут."""
    st = _credits_here()
    if not st['key']:
        prx = _proxy_url()
        st = None
        if prx:
            try:
                import urllib.request as _u
                with _u.urlopen(prx.rsplit('/', 1)[0] + '/credits', timeout=4) as r:
                    st = json.loads(r.read())
            except Exception:  # noqa: BLE001
                st = None
        if st is None or not st.get('key'):
            return ('unavailable', 'Улучшение фото сейчас недоступно: сервер улучшения не отвечает. '
                                   'Черновое фото работает — попробуйте улучшить позже.')
    bal = st.get('balance')
    if bal is None:
        return None
    if float(bal) - PAID_COST_USD * JOBS.running('realistic') < PAID_MIN_USD:
        return ('no_credits', DR.NO_CREDITS_TEXT)
    return None


def _http_error_body(e) -> dict:
    """Тело ошибки HTTP от себя же или от DEV: JSON сервиса, иначе короткий текст."""
    try:
        j = json.loads(e.read().decode('utf-8', 'replace') or '{}')
        if isinstance(j, dict) and j.get('error'):
            return j
    except Exception:  # noqa: BLE001
        pass
    return {'error': f'рендер не удался: HTTP {getattr(e, "code", "?")}'}


def _work(jid: str) -> None:
    """ФОН ИДЁТ ТЕМ ЖЕ ПУТЁМ, ЧТО И ОБЫЧНЫЙ ЗАПРОС — через себя же, но без ожидания клиентом. Так задание
    проходит и через прокси на DEV-рендер, и через локальный фолбэк: логика маршрутизации одна."""
    import urllib.error as _ue
    import urllib.request as _u
    body = dict(JOBS.body(jid) or {})
    if not body:
        return JOBS.fail(jid, 'задание без запроса — нажмите «Повторить»', 'lost')
    body['_job'] = jid                     # внутренний номер: локальный рендер ставит задание в очередь
    try:
        _port = int(os.environ.get('DRAFT_PORT', 8099))
        req = _u.Request(f'http://127.0.0.1:{_port}/render', data=json.dumps(body).encode(), method='POST',
                         headers={'Content-Type': 'application/json'})
        with _u.urlopen(req, timeout=900) as r:
            out = json.loads(r.read())
        JOBS.finish(jid, out)
    except _ue.HTTPError as e:
        j = _http_error_body(e)
        JOBS.fail(jid, j['error'], j.get('code') or 'error')
    except BaseException as e:  # noqa: BLE001 — ЛЮБОЙ сбой обязан стать статусом
        # ПОЧЕМУ BaseException (13.10): рендер местами поднимает `SystemExit` как «ответ негоден»; фоновый поток
        # умирал молча, задание навсегда оставалось `running`, и страница через две минуты опроса писала «сервер
        # долго не отвечает» — без причины и в логе, и на экране.
        JOBS.fail(jid, f'рендер не удался: {str(e)[:200]}')


def _resume(jids: list) -> None:
    """Черновики, прерванные выкладкой, досчитываются по одному (не 40 потоков разом) — номера у страниц прежние."""
    for jid in jids:
        print(f'задание {jid}: досчитываю после перезапуска', flush=True)
        _work(jid)


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        if code == 429:
            self.send_header('Retry-After', '600')
        origin = (self.headers.get('Origin') or '').rstrip('/')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.end_headers()
        self.wfile.write(body)

    @property
    def client_ip(self) -> str:
        """Адрес человека. Caddy (без trusted_proxies) кладёт в X-Forwarded-For реальный адрес
        клиента; внутренние вызовы (фоновое задание зовёт себя же) идут без заголовка — пусто."""
        xff = (self.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
        return xff

    def _frame_upload(self, n: int):
        """КАДР ИЗ БРАУЗЕРНОЙ СЦЕНЫ (demo-10, Codex 17.10 п.5): страница грузит каждый вид отдельным запросом — тело = JPEG, имя =
        sha256 содержимого; в задании «реалистично» потом только имена (не Base64 в JSON и не в `jobs.json`). Кадр проверяется как
        картинка разумного размера; старше двух суток — удаляются здесь же."""
        ip = self.client_ip
        if ip and not ip_allowed(ip, 'render'):
            return self._send(429, {'error': 'слишком много кадров подряд, попробуйте через 10 минут'})
        if n <= 0 or n > FRAME_MAX:
            return self._send(413, {'error': 'кадр пустой или слишком большой'})
        raw = self.rfile.read(n)
        try:
            from PIL import Image as _I
            import io as _io
            im = _I.open(_io.BytesIO(raw))
            if im.format != 'JPEG' or not (256 <= im.width <= 4096 and 256 <= im.height <= 4096):
                return self._send(400, {'error': 'нужен JPEG 256…4096 px'})
            im.verify()
        except Exception:  # noqa: BLE001
            return self._send(400, {'error': 'не картинка'})
        import hashlib as _h
        fid = _h.sha256(raw).hexdigest()
        import improve_mode as IM
        path = IM.frame_path(fid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            tmp = path + '.tmp'
            open(tmp, 'wb').write(raw)
            os.replace(tmp, path)
        try:                                                 # уборка: кадры нужны только на время задания
            cut = time.time() - 2 * 86400
            d = os.path.dirname(path)
            for f in os.listdir(d):
                fp = os.path.join(d, f)
                if os.path.getmtime(fp) < cut:
                    os.remove(fp)
        except Exception:  # noqa: BLE001
            pass
        return self._send(200, {'id': fid, 'bytes': len(raw)})

    def do_OPTIONS(self):                                    # noqa: N802
        self._send(204, {})

    @property
    def route(self) -> str:
        # Caddy отдаёт полный путь (`/api/draft`), локально зовут `/draft` — принимаем оба
        p = self.path.split('?')[0]
        return p[4:] if p.startswith('/api/') else p

    def do_GET(self):                                        # noqa: N802
        if self.route.startswith(('/health', 'draft/health')) or self.route in ('/draft/health',):
            # версия образа (b2b-08): деплой сверяет её, как у приложения
            return self._send(200, {'ok': True, 'version': os.environ.get('DRAFT_VERSION', 'dev'), **_render_info()})
        if self.route.startswith(('/draft/credits', '/credits')):
            # БАЛАНС ШЛЮЗА (demo-03): прод без ключа спрашивает его у DEV перед платным заданием. Только изнутри
            # (туннель/свой адрес, без X-Forwarded-For): сумму на счёте наружу не показываем.
            if self.client_ip:
                return self._send(404, {'error': 'нет такого пути'})
            return self._send(200, _credits_here())
        if self.route.startswith(('/draft/paid', '/paid')):
            # МОЖНО ЛИ СЕЙЧАС УЛУЧШАТЬ (demo-03): да/нет и код — без суммы. Нужен живой проверке (проверить честный
            # отказ, не создавая платного задания) и странице.
            gate = _paid_gate_cached()
            return self._send(200, {'available': gate is None, 'code': gate[0] if gate else None})
        if self.route.startswith(('/draft/stats', '/stats')):
            # ВРЕМЯ КАДРА (b2b-08 п.5): среднее последних замеров по качеству — стык конвейера следит, не медленнеет ли.
            # running — идущие задания: ночная живая проверка ждёт свободного рендера (b2b-09, earlyoom 18.10)
            avg = {q: (round(sum(d) / len(d), 1) if d else None) for q, d in _DURS.items()}
            return self._send(200, {'avg_sec': avg, 'n': {q: len(d) for q, d in _DURS.items()},
                                    'queue': JOBS.waiting_n(), 'running': {q: JOBS.running(q) for q in _DURS}})
        if self.route.startswith('/job'):
            from urllib.parse import parse_qs, urlparse
            jid = (parse_qs(urlparse(self.path).query).get('id') or [''])[0]
            j = JOBS.get(jid)
            if not j:
                return self._send(404, {'error': 'задание не найдено — нажмите «Повторить»', 'code': 'not_found'})
            if j['status'] == 'running':
                st = {'status': 'running', 'sec': round(time.time() - j['ts'], 1)}
                pos = JOBS.wait_pos(jid)
                if pos:                        # ждёт места: номер в очереди и оценка до готовности
                    st.update({'queue': pos, 'eta': queue_eta(pos, j.get('quality', 'draft'), _DURS)})
                elif j.get('started'):
                    q = j.get('quality', 'draft')
                    st['eta'] = max(0, queue_eta(1, q, _DURS) - int(time.time() - j['started']))
                return self._send(200, st)
            return self._send(200, public_view(j))
        self._send(404, {'error': 'нет такого пути'})

    def do_POST(self):                                       # noqa: N802
        n = int(self.headers.get('Content-Length') or 0)
        if self.route.startswith('/render/frame'):
            return self._frame_upload(n)
        if n > MAX_BODY:
            return self._send(413, {'error': 'слишком большой запрос'})
        raw = self.rfile.read(n) if n else b'{}'
        try:
            payload = json.loads(raw or b'{}')
        except Exception:
            return self._send(400, {'error': 'не JSON'})
        if self.route.startswith('/warm'):
            # ПРОГРЕВ ЗОВЁТСЯ, КОГДА ЧЕЛОВЕК НАЧАЛ ДВИГАТЬ МЕБЕЛЬ (владелец 26.08): у модели
            # холодный старт, и без прогрева первый рендер ждал бы минуту. Чаще раза в 4 минуты
            # греть незачем — платим за вызовы.
            if time.time() - _LAST_WARM[0] < 240:
                return self._send(200, {'sec': 0, 'skipped': 'уже прогрето'})
            _LAST_WARM[0] = time.time()
            if os.environ.get('SCENE3D', '1') != '1':
                threading.Thread(target=DR.warm, daemon=True).start()
            return self._send(200, {'sec': 0, 'started': True})
        ip = self.client_ip
        if self.route.startswith('/share'):
            if ip and not ip_allowed(ip, 'share'):
                return self._send(429, {'error': 'слишком много подборок подряд, попробуйте через 10 минут'})
            return self._share(payload)
        if not self.route.startswith(('/draft', '/render')):
            return self._send(404, {'error': 'нет такого пути'})
        if ip and not ip_allowed(ip, 'render'):
            return self._send(429, {'error': 'слишком много кадров подряд, попробуйте через 10 минут'})
        if not (payload.get('room') and payload.get('items')):
            return self._send(400, {'error': 'нужны room и items'})
        # ДЛИННЫЙ ЗАПРОС УХОДИТ В ФОН. Клиент присылает `async:1` и получает номер задания.
        if payload.get('async'):
            quality = 'realistic' if payload.get('quality') == 'realistic' else 'draft'
            if quality == 'realistic':
                gate = _paid_gate()
                if gate:                       # нет денег / нет сервера улучшения — сразу, без задания
                    return self._send(402 if gate[0] == 'no_credits' else 503, {'error': gate[1], 'code': gate[0]})
            if payload.get('dry_run'):
                # ПРОБА БЕЗ ЗАДАНИЯ (demo-03, verify): живая проверка «честного отказа» шлёт тот же запрос, но задание не
                # создаётся никогда — даже если деньги пополнили между её вопросом и запросом. С demo-11 — ещё и чем будет
                # нарисовано: модель и промпт того процесса, который рисует (DEV за туннелем; его `/health`), и блоки промпта
                return self._send(200, {'dry_run': True, 'would': 'job', 'quality': quality, **_dry_info(payload)})
            body = dict(payload); body.pop('async', None)
            jid = JOBS.new(quality, body)
            threading.Thread(target=_work, args=(jid,), daemon=True).start()
            return self._send(200, {'job': jid})
        # ВРЕМЕННЫЙ КОСТЫЛЬ ДЛЯ ДЕМО (владелец 31.08): полный кадр рендерит DEV-машина
        # через ssh-туннель; конфиг кладётся файлом в share (env контейнера не пересоздать).
        # DEV молчит/упала → фолбэк на локальный (декимированный) рендер, кнопка живёт
        prx = _proxy_url()
        if prx and not payload.get('no_proxy'):
            try:
                import urllib.request as _u
                # внутренний номер задания DEV не знает — без него DEV делает кадр как обычный запрос (b2b-08, verify)
                _fwd = json.dumps({k: v for k, v in payload.items() if k != '_job'}).encode()
                req = _u.Request(prx, data=_fwd, method='POST',
                                 headers={'Content-Type': 'application/json'})
                # РЕЖИМ РЕМОНТА ЖДЁТ ДОЛЬШЕ (01.09): сборка листа плюс генерация в 2048 —
                # это минуты. Прежние 120 с роняли запрос в ФОЛБЭК на локальный рендер
                # прода, то есть человек получал кадр СТАРОГО пути и не знал об этом.
                _to = 600 if payload.get('quality') == 'realistic' else 120
                with _u.urlopen(req, timeout=_to) as r:
                    out = json.loads(r.read())
                for nm, b64 in (out.pop('frames', None) or {}).items():
                    # кадры пришли в теле — кладём в раздаваемую папку, ссылки уже прод-URL
                    import base64 as _b64
                    if '/' in nm or '..' in nm:
                        continue
                    os.makedirs(DR.FRAMES_DIR, exist_ok=True)
                    open(os.path.join(DR.FRAMES_DIR, nm), 'wb').write(_b64.b64decode(b64))
                out['backend'] = 'dev'
                if isinstance(out.get('sec'), (int, float)):   # время кадра — и с домашнего компьютера (стык frame_sec)
                    _q = 'realistic' if payload.get('quality') == 'realistic' else 'draft'
                    _DURS[_q] = (_DURS[_q] + [float(out['sec'])])[-20:]
                _registry_add(payload, out)
                return self._send(200, out)
            except Exception as e:  # noqa: BLE001
                import urllib.error as _ue
                # ОТКАЗ DEV ПО СУЩЕСТВУ — НАРУЖУ, А НЕ В ЗАПАСНОЙ РЕНДЕР (demo-03, разбор Codex): 4xx и «нет денег»
                # повторились бы локально тем же отказом (и теми же расходами). Запасной путь — только для
                # молчания DEV: обрыв, таймаут, 5xx. Платное без своего ключа локально невозможно вовсе.
                if isinstance(e, _ue.HTTPError):
                    j = _http_error_body(e)
                    if e.code < 500 or j.get('code') == 'no_credits' or (
                            payload.get('quality') == 'realistic' and not _has_gw_key()):
                        print(f'DEV отказал по существу (HTTP {e.code}): {j.get("error", "")[:120]}', flush=True)
                        return self._send(e.code, j)
                elif payload.get('quality') == 'realistic' and not _has_gw_key():
                    return self._send(503, {'error': 'Улучшение фото сейчас недоступно: сервер улучшения не '
                                                     'отвечает. Черновое фото работает — попробуйте улучшить позже.',
                                            'code': 'unavailable'})
                print(f'DEV-бэкенд молчит ({str(e)[:80]}) — рендерю локально', flush=True)
        now = time.time()
        _HITS[:] = [t for t in _HITS if now - t < 3600]
        if len(_HITS) >= HOURLY_CAP:
            return self._send(429, {'error': 'на сегодня лимит черновых рендеров исчерпан'})
        _HITS.append(now)
        jid = payload.pop('_job', None)
        if jid and JOBS.get(jid):
            # фоновое задание — ждёт своей очереди (страница видит место и оценку), а не получает отказ
            JOBS.wait_add(jid)
            try:
                got = _LOCK.acquire(timeout=QUEUE_WAIT_S)
            finally:
                JOBS.wait_remove(jid)
            if not got:
                return self._send(503, {'error': f'очередь кадров не сдвинулась за {QUEUE_WAIT_S // 60} мин — попробуйте позже'})
            JOBS.mark(jid, started=time.time())
        elif not _LOCK.acquire(blocking=False):
            return self._send(429, {'error': 'сейчас считается другой рендер, попробуйте через минуту'})
        try:
            t = time.time()
            quality = 'realistic' if payload.get('quality') == 'realistic' else 'draft'
            res = DR.render(layout=payload, quality=quality,
                            save_prefix=os.path.join(DR.OUT, 'draft-web'))
            if os.environ.get('FRAME_INLINE') == '1':
                # DEV-бэкенд: кадры уезжают в теле ответа (2 scp-рукопожатия стоили ~5с)
                import base64 as _b64
                fr = {}
                for sh in res.get('shots') or []:
                    nm = (sh.get('url') or '').rsplit('/', 1)[-1]
                    if not nm:
                        continue
                    # МИНИАТЮРА ЕДЕТ ВМЕСТЕ С КАДРОМ (владелец 02.09: «грузит 1–2 секунды»).
                    # Рядом с кадром пишется уменьшенная копия (`_publish_frame`), но в теле
                    # ответа уезжал только полный кадр — на проде миниатюры не было, страница
                    # получала 404 и по `onerror` подставляла полноразмерный файл. То есть вся
                    # экономия на превью не работала ровно для тех кадров, что снимаются сейчас.
                    for fn in (nm, DR.thumb_name(nm)):
                        fp = os.path.join(DR.FRAMES_DIR, fn)
                        if os.path.exists(fp):
                            fr[fn] = _b64.b64encode(open(fp, 'rb').read()).decode()
                if fr:
                    res['frames'] = fr
            out2 = {'shots': res['shots'], 'url': res['url'], 'model': res['model'],
                    'sources': res.get('sources'), 'timing': res.get('timing'),
                    'quality': quality, 'sec': round(time.time() - t, 1),
                    'queued_sec': round(t - (JOBS.get(jid) or {}).get('ts', t), 1) if jid else 0,
                    # КТО СНЯЛ (b2b-08 п.2b): DEV-прокси пишет 'dev', здесь — сервер сам (запасной путь, лёгкие меши)
                    'backend': 'server',
                    'frames': res.get('frames'), 'diag': res['diag'],
                    # чем нарисовано фото нейросети (demo-11): без этого поля терялись по дороге в прод и реестр
                    **({k: res[k] for k in ('image_quality', 'prompt_version', 'prompt_sha', 'sheet_orient') if res.get(k)})}
            _registry_add(payload, out2)
            _DURS[quality] = (_DURS[quality] + [out2['sec']])[-20:]   # замер для оценки очереди
            self._send(200, out2)
        except DR.NoCreditsError as e:               # нет денег у шлюза — отдельный код, без запасного пути
            print(f'РЕНДЕР: шлюз без денег (402) — {e}', flush=True)
            self._send(402, {'error': str(e), 'code': 'no_credits'})
        except SystemExit as e:                      # «ответ негоден» из рендера — тоже ответ, а не тишина
            print(f'РЕНДЕР НЕ УДАЛСЯ (SystemExit): {e}', flush=True)
            self._send(502, {'error': f'рендер не удался: {str(e)[:200]}'})
        except Exception as e:                       # noqa: BLE001 — наружу отдаём короткую причину
            # ПРИЧИНА ОБЯЗАНА ПОПАСТЬ В ЛОГ. Прод при 502 просто уходит в локальный рендер и
            # пишет у себя «DEV-бэкенд молчит (HTTP Error 502)» — без причины. Так демо
            # незаметно работало на декимированном запасном пути: качество упало, а в логах
            # с обеих сторон не было ни одной строки, по которой это видно (02.09).
            import traceback as _tb
            print(f'РЕНДЕР НЕ УДАЛСЯ: {e!r}\n{_tb.format_exc()}', flush=True)
            self._send(502, {'error': f'рендер не удался: {str(e)[:200]}'})
        finally:
            _LOCK.release()

    def _share(self, payload: dict) -> None:
        """ПОДБОРКА ФОТОГРАФИЙ (26.08, владелец: «можно отправить себе»). Сохраняем страницу с
        выбранными кадрами и отдаём короткую ссылку — её можно открыть на телефоне или переслать.
        Мессенджеры подключаются токеном бота: бот не может написать первым, поэтому это deep-link
        со `start=<id>` (тот же приём, что у лид-бота, ADR-0180)."""
        shots = [s for s in (payload.get('shots') or [])
                 if isinstance(s, dict) and safe_url(s.get('url'))][:24]
        if not shots:
            return self._send(400, {'error': 'нечего отправлять — список кадров пуст'})
        sid = hashlib.sha1((json.dumps(shots, ensure_ascii=False, sort_keys=True)
                            + str(time.time())).encode()).hexdigest()[:10]
        d = os.path.join(SHARE_DIR, sid)
        try:
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, 'index.html'), 'w', encoding='utf-8').write(_share_page(payload, shots))
        except Exception as e:                       # noqa: BLE001
            return self._send(500, {'error': f'не удалось сохранить подборку: {str(e)[:120]}'})
        url = f'{PUBLIC_BASE}/test/share/{sid}/'
        # КОНТАКТ ВМЕСТО ССЫЛКИ (владелец 26.08): ссылку на подборку наружу не отдаём — человек
        # оставляет Telegram, MAX или телефон, и доставка идёт туда. Пока каналы не подключены
        # (нет токенов ботов и SMS-шлюза), запрос честно помечается как ожидающий отправки.
        chan = str(payload.get('channel') or '').lower()
        contact = str(payload.get('contact') or '').strip()[:120]
        ready = {'telegram': bool(TG_BOT), 'max': bool(MAX_BOT), 'sms': bool(SMS_GATE)}.get(chan, False)
        # КОНТАКТ — ТОЛЬКО В БАЗУ (инцидент 13.10, ADR-0248). Раньше он ложился JSON-файлом в
        # SHARE_DIR/_queue, а эту папку Caddy раздавал всему интернету с листингом.
        saved = bool(contact) and save_share_request(
            {'shareId': sid, 'shareUrl': url, 'channel': chan if chan in ('telegram', 'max', 'sms') else '',
             'contact': contact, 'shotCount': len(shots), 'ip': self.client_ip or None})
        if contact and not saved:
            # Честно (разбор Codex 13.10): без записи в базу доставки не будет — нельзя
            # показывать человеку «придёт в течение минуты».
            return self._send(503, {'error': 'не удалось сохранить контакт — попробуйте ещё раз через минуту'})
        self._send(200, {'id': sid, 'count': len(shots), 'channel': chan,
                         'pending': not ready, 'saved': saved,
                         # Telegram: покупатель жмёт кнопку → бот → «Старт» → бот присылает ссылку (контакт не нужен)
                         'tg_link': f'https://t.me/{TG_BOT}?start=sh_{sid}' if TG_BOT and chan == 'telegram' else ''})

    def log_message(self, fmt, *a):                  # noqa: A003 — тише в логе
        sys.stderr.write('%s %s\n' % (self.address_string(), fmt % a))


def _prewarm_demo() -> None:
    """Разобрать меши демо ЗАРАНЕЕ, пока никто не ждёт.

    Замер 02.09 (эмуляция запроса со страницы): первый клик после запуска сервиса — 20 с, все
    следующие — 5 с. Разница целиком в том, что восемь GLB скачиваются, разбираются и
    упрощаются в момент нажатия. Демо показывают партнёру, и первым кликом будет именно его —
    ждать двадцать секунд он не должен. Греем в фоне на пониженном приоритете сразу после старта.
    """
    try:
        os.nice(15)
    except Exception:  # noqa: BLE001
        pass
    try:
        import json as _j
        import urllib.request as _u
        url = os.environ.get('DEMO_DATA_URL',
                             'https://remont-lab.online/demo/demo-data.json')
        data = _j.load(_u.urlopen(url, timeout=30))
        sids = []
        for v in (data.get('variants') or [])[:4]:
            for it in v.get('items') or []:
                # греем ровно те файлы, которые попросит сцена, — модели семейств (`msid`)
                sku = it.get('sku') or {}
                sid = sku.get('msid') or sku.get('sid')
                if sid and ':' not in str(sid):
                    sids.append(sid)
        seen, t0 = set(), time.time()
        DR.S3_LITE[0] = True                      # греем именно то, чем рисуется эскиз
        for sid in sids:
            if sid in seen:
                continue
            seen.add(sid)
            g = DR._scene3d_glb(sid)
            if g:
                DR._scene3d_parts(g)
        print(f'прогрев: {len(seen)} мешей демо разобрано за {time.time()-t0:.1f} с', flush=True)
    except Exception as e:  # noqa: BLE001 — прогрев не критичен, но молчать о нём нельзя
        print(f'прогрев демо не удался: {str(e)[:90]}', flush=True)


if __name__ == '__main__':
    port = int(os.environ.get('DRAFT_PORT', 8099))
    print(f'черновой рендер слушает :{port}', flush=True)
    if os.environ.get('PREWARM', '1') == '1':
        threading.Thread(target=_prewarm_demo, daemon=True).start()
    resume = JOBS.load()                    # до первого запроса: страницы спросят про свои номера сразу после старта
    srv = ThreadingHTTPServer((os.environ.get('DRAFT_HOST', '0.0.0.0'), port), H)
    if resume:                              # порт уже открыт — запрос к себе дождётся serve_forever
        threading.Thread(target=_resume, args=(resume,), daemon=True).start()
    srv.serve_forever()
