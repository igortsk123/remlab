#!/usr/bin/env python3
"""ЖИВОСТЬ ФОТО ТОВАРА — контракт подбора (решение владельца 26.08: «товар без фото не должен
участвовать; пересчитывать надо на этапе сетов»).

Фид отдаёт ссылки на CDN Гдеслона, и заметная часть мертва (404): в банке появлялись позиции,
которые в витрине выглядят пустой карточкой. Поэтому «фото живое» — такое же условие подбора,
как конверт слота: проверяется ОДИН РАЗ и кэшируется (`img-alive.json`, TTL 14 дней), а сборка,
лечение и починка банка спрашивают кэш.

  img_alive.py --scan            # фото банка sets3.json (быстро, ~600 ссылок)
  img_alive.py --pool            # фото ВСЕГО пула подбора, с бюджетом времени (по умолчанию 25 мин)
  img_alive.py --all             # фото всех товаров каталога (~32 тыс., ≈45 мин при 16 потоках)
  img_alive.py --stats           # что в кэше

Обход идёт от САМЫХ ДАВНО НЕ ПРОВЕРЕННЫХ: если бюджет времени кончился, завтрашний прогон
продолжит с того места, и за 2–3 дня пул обходится целиком даже при жёстком лимите.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'img-alive.json')
TTL_DAYS = 14
_MEM: dict | None = None


def _load() -> dict:
    global _MEM
    if _MEM is None:
        try:
            _MEM = json.load(open(CACHE, encoding='utf-8'))
        except Exception:
            _MEM = {}
    return _MEM


def _save() -> None:
    if _MEM is not None:
        json.dump(_MEM, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)


_MAGIC = (b'\xff\xd8\xff', b'\x89PNG', b'GIF8', b'RIFF', b'<svg', b'\x00\x00\x00 ftypavif')
# 3 (29.08): проба стала трёхзначной — «не смог проверить» больше не равно «мертво».
# Подъём версии обязателен: он заставляет перепроверить 12 632 записи, из которых, по замеру
# на 150 ссылках, ~81% были ложными приговорами от троттлинга CDN.
PROBE_V = 3          # версия проверки: записи старой версии перепроверяются


def _probe(url: str):
    """Живо ли изображение → True / False / **None**.

    ОДНОГО HEAD НЕДОСТАТОЧНО (разбор Codex 26.08): часть CDN отвечает 403/405 на HEAD и 200 на
    GET (ложные «мёртвые»), а часть отдаёт 200 с HTML-заглушкой вместо картинки (ложные «живые»).
    Поэтому: HEAD ради дешёвого положительного ответа с картинкой, иначе — GET первых байт и
    проверка сигнатуры файла.

    **None = «не смог проверить», и это НЕ «мертво» (поймано 29.08).** Прежняя версия возвращала
    False на любом исключении: таймаут, обрыв, троттлинг CDN. При ночном обходе `imgng.gdeslon.ru`
    режет темп — и живые товары получали приговор на 14 дней. Перепроверка 150 «мёртвых» ссылок
    в спокойном режиме: живы 122 из 150, то есть 81% вердиктов были ложными. А `_slot_ok`
    спрашивает `alive_now`, значит живой товар молча выбрасывался из сетов.

    Приговор выносим ТОЛЬКО по явному ответу сервера: 404/410 (нет ресурса) или 200 с содержимым,
    не похожим на картинку. Всё остальное — «не знаю», и в кэш это не пишется.
    """
    full = ('https:' + url) if url.startswith('//') else url
    hdr = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://remont-lab.online/'}
    gone = False
    try:
        req = urllib.request.Request(full, method='HEAD', headers=hdr)
        with urllib.request.urlopen(req, timeout=12) as f:
            ct = (f.headers.get('Content-Type') or '').lower()
            ln = int(f.headers.get('Content-Length') or 0)
            if 200 <= f.status < 300 and ct.startswith('image/') and ln != 0:
                return True
    except urllib.error.HTTPError as e:
        gone = e.code in (404, 410)          # ресурса нет — это ответ, а не сбой
    except Exception:
        pass                                 # сеть/таймаут — решать по добору
    try:                                     # добор: первые байты и сигнатура файла
        req = urllib.request.Request(full, headers=dict(hdr, Range='bytes=0-2047'))
        with urllib.request.urlopen(req, timeout=15) as f:
            if not (200 <= f.status < 300):
                return None
            head = f.read(2048)
        if not head:
            return None
        return bool(head[:4] in [m[:4] for m in _MAGIC]
                    or any(head.startswith(m) for m in _MAGIC))
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return False                     # подтверждённо мертво
        return False if gone else None       # 403/429/5xx — троттлинг, а не приговор
    except Exception:
        return False if gone else None       # таймаут/обрыв — «не знаю»


def alive(url: str | None, unknown: bool = True) -> bool:
    """Живо ли фото. `unknown=True` — непроверенное считаем живым (не блокируем сборку до скана);
    после `--scan` кэш заполнен, и решение становится настоящим."""
    if not url:
        return False
    rec = _load().get(url)
    if not rec:
        return unknown
    if time.time() - rec.get('ts', 0) > TTL_DAYS * 86400 or rec.get('v', 1) < PROBE_V:
        return unknown
    return bool(rec.get('ok'))


def alive_now(url: str | None) -> bool:
    """Строгая проверка: непроверенное фото ПРОВЕРЯЕМ СРАЗУ и кладём в кэш. Нужна там, где
    выбирается ЗАМЕНА (26.08): с мягким `unknown=True` починка ставила товар с непроверенной
    ссылкой, следующий скан объявлял её мёртвой, и банк сходился к живым фото за 6+ раундов."""
    if not url:
        return False
    mem = _load()
    rec = mem.get(url)
    if rec and rec.get('v', 1) >= PROBE_V and time.time() - rec.get('ts', 0) <= TTL_DAYS * 86400:
        return bool(rec.get('ok'))
    ok = _probe(url)
    if ok is None:
        # Не смогли проверить — вердикт не выносим и в кэш не пишем: иначе троттлинг CDN
        # похоронит живой товар на 14 дней. До выяснения считаем живым, как и непроверенное.
        return True
    mem[url] = {'ok': bool(ok), 'ts': int(time.time()), 'v': PROBE_V}
    _save()
    return bool(ok)


def scan(urls: list[str], workers: int = 8) -> tuple[int, int]:
    mem = _load()
    force = '--force' in sys.argv          # ежедневный прогон банка: TTL не ждём
    todo = [u for u in dict.fromkeys(urls)
            if u and (force or u not in mem or time.time() - mem[u].get('ts', 0) > TTL_DAYS * 86400
                      or mem[u].get('v', 1) < PROBE_V)]
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            unknown = 0
            for u, ok in zip(todo, ex.map(_probe, todo)):
                if ok is None:               # не проверилось — оставляем как было, не хороним
                    unknown += 1
                    continue
                mem[u] = {'ok': bool(ok), 'ts': int(time.time()), 'v': PROBE_V}
            if unknown:
                print(f'не удалось проверить: {unknown} ссылок (вердикт не вынесен)', flush=True)
        _save()
    uniq = list(dict.fromkeys(u for u in urls if u))
    ok = sum(1 for u in uniq if mem.get(u, {}).get('ok'))
    return ok, len(uniq)


def _bank_urls() -> list[str]:
    sets = json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8'))
    out = []
    for s in sets:
        for it in (s.get('items') or {}).values():
            if it.get('img'):
                out.append(it['img'])
    return out


def _pool_urls(all_products: bool = False) -> list:
    """Ссылки на фото: весь каталог (--all) или пул подбора (`candidates-index.json`)."""
    if all_products:
        import subprocess
        out = subprocess.run(['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab',
                              '-d', 'remlab', '-tAc',
                              "select image_url from products where in_stock and image_url is not null"],
                             capture_output=True, text=True).stdout
        return [u.strip() for u in out.splitlines() if u.strip()]
    p = os.path.join(HERE, 'candidates-index.json')
    if not os.path.exists(p):
        return []
    c = json.load(open(p, encoding='utf-8'))
    return [v['img'] for v in c['items'].values() if v.get('img')]


def sweep(urls: list, minutes: float = 25.0, workers: int = 16) -> tuple:
    """Обойти ссылки от самых давно проверенных, уложившись в бюджет времени."""
    mem = _load()
    uniq = list(dict.fromkeys(u for u in urls if u))
    uniq.sort(key=lambda u: (mem.get(u, {}).get('v', 0) >= PROBE_V,
                             mem.get(u, {}).get('ts', 0)))       # непроверенные и старые — первыми
    deadline = time.time() + minutes * 60
    done = 0
    step = workers * 8
    for i in range(0, len(uniq), step):
        if time.time() > deadline:
            break
        batch = uniq[i:i + step]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for u, ok in zip(batch, ex.map(_probe, batch)):
                mem[u] = {'ok': bool(ok), 'ts': int(time.time()), 'v': PROBE_V}
        done += len(batch)
        _save()
    live = sum(1 for u in uniq if mem.get(u, {}).get('ok'))
    known = sum(1 for u in uniq if u in mem and mem[u].get('v', 1) >= PROBE_V)
    return done, live, known, len(uniq)


def _cli_pool(all_products: bool) -> None:
    mins = 25.0
    if '--minutes' in sys.argv:
        mins = float(sys.argv[sys.argv.index('--minutes') + 1])
    urls = _pool_urls(all_products)
    done, live, known, total = sweep(urls, minutes=mins)
    scope = 'каталога' if all_products else 'пула подбора'
    print(f'фото {scope}: всего {total}, проверено за прогон {done}, известно {known}, '
          f'живых {live} ({live * 100 // max(known, 1)}% от проверенных)')


if __name__ == '__main__':
    if '--scan' in sys.argv:
        urls = _bank_urls()
        ok, tot = scan(urls)
        print(f'фото в банке: {tot} ссылок, живых {ok} ({100 * ok / max(tot, 1):.0f} %)')
    elif '--pool' in sys.argv or '--all' in sys.argv:
        _cli_pool('--all' in sys.argv)
    elif '--stats' in sys.argv:
        mem = _load()
        ok = sum(1 for v in mem.values() if v.get('ok'))
        print(f'кэш: {len(mem)} ссылок, живых {ok}, мёртвых {len(mem) - ok}')
    else:
        print(__doc__)
