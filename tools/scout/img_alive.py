#!/usr/bin/env python3
"""ЖИВОСТЬ ФОТО ТОВАРА — контракт подбора (решение владельца 26.08: «товар без фото не должен
участвовать; пересчитывать надо на этапе сетов»).

Фид отдаёт ссылки на CDN Гдеслона, и заметная часть мертва (404): в банке появлялись позиции,
которые в витрине выглядят пустой карточкой. Поэтому «фото живое» — такое же условие подбора,
как конверт слота: проверяется ОДИН РАЗ и кэшируется (`img-alive.json`, TTL 14 дней), а сборка,
лечение и починка банка спрашивают кэш.

  img_alive.py --scan            # проверить фото всех товаров в sets3.json и обновить кэш
  img_alive.py --stats           # что в кэше
"""
from __future__ import annotations

import json
import os
import sys
import time
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
PROBE_V = 2          # версия проверки: записи старой версии перепроверяются


def _probe(url: str) -> bool:
    """Живо ли изображение. ОДНОГО HEAD НЕДОСТАТОЧНО (разбор Codex 26.08): часть CDN отвечает
    403/405 на HEAD и 200 на GET (ложные «мёртвые»), а часть отдаёт 200 с HTML-заглушкой вместо
    картинки (ложные «живые»). Поэтому: HEAD ради дешёвого положительного ответа с картинкой,
    иначе — GET первых байт и проверка сигнатуры файла."""
    full = ('https:' + url) if url.startswith('//') else url
    hdr = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://remont-lab.online/'}
    try:
        req = urllib.request.Request(full, method='HEAD', headers=hdr)
        with urllib.request.urlopen(req, timeout=12) as f:
            ct = (f.headers.get('Content-Type') or '').lower()
            ln = int(f.headers.get('Content-Length') or 0)
            if 200 <= f.status < 300 and ct.startswith('image/') and ln != 0:
                return True
    except Exception:
        pass
    try:                                     # добор: первые байты и сигнатура файла
        req = urllib.request.Request(full, headers=dict(hdr, Range='bytes=0-2047'))
        with urllib.request.urlopen(req, timeout=15) as f:
            if not (200 <= f.status < 300):
                return False
            head = f.read(2048)
        return bool(head) and (head[:4] in [m[:4] for m in _MAGIC]
                               or any(head.startswith(m) for m in _MAGIC))
    except Exception:
        return False


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
    mem[url] = {'ok': bool(ok), 'ts': int(time.time()), 'v': PROBE_V}
    _save()
    return ok


def scan(urls: list[str], workers: int = 8) -> tuple[int, int]:
    mem = _load()
    todo = [u for u in dict.fromkeys(urls)
            if u and (u not in mem or time.time() - mem[u].get('ts', 0) > TTL_DAYS * 86400
                      or mem[u].get('v', 1) < PROBE_V)]
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for u, ok in zip(todo, ex.map(_probe, todo)):
                mem[u] = {'ok': bool(ok), 'ts': int(time.time()), 'v': PROBE_V}
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


if __name__ == '__main__':
    if '--scan' in sys.argv:
        urls = _bank_urls()
        ok, tot = scan(urls)
        print(f'фото в банке: {tot} ссылок, живых {ok} ({100 * ok / max(tot, 1):.0f} %)')
    elif '--stats' in sys.argv:
        mem = _load()
        ok = sum(1 for v in mem.values() if v.get('ok'))
        print(f'кэш: {len(mem)} ссылок, живых {ok}, мёртвых {len(mem) - ok}')
    else:
        print(__doc__)
