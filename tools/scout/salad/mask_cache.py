#!/usr/bin/env python3
"""ДИСКОВЫЙ КЭШ СЫРОЙ МАСКИ НА ЦП (T-20261127-175/mask-cache; владелец TG 3689/3692, P-072; решение Fable `~/remlab-logs/fable-1126/otvet-30.md` § 3, § 5 п.5 и 27.11 19:11).

ЗАЧЕМ. Сеть вырезки на ЦП гоняли по ~минуте на фото несколько раз подряд разные рабочие на ОДНИХ И ТЕХ ЖЕ фото. Считаем один раз — храним.

ЧТО ЛЕЖИТ. Только альфа сырой маски (`cutout_one.mask_cpu`): 8 бит, размер = размер фото, PNG без потерь. Цвета RGBA при попадании берутся из самого фото — результат
побайтно тот же, что при пересчёте (проверка — `tests_mask_cache.py`). Маски с видеокарты (Salad/fal) сюда НЕ попадают и отсюда не подставляются: кэш внутри `mask_cpu`, больше нигде.

КЛЮЧ (имя файла `<ab>/<sha256>.png`): sha256 от «ШxВ:RGB:» + байты ДЕКОДИРОВАННОГО фото + строка среды `tag` (репозиторий и РЕВИЗИЯ весов, вход сети 1024, «cpu-full-fp32», версия
кода кэша `MASK_CACHE_VERSION`, версия torch). Смена фото на 1 байт, ревизии весов, версии torch или версии кода — другой ключ (промах). Число потоков в ключ НЕ входит: первая
посчитанная маска и есть общая — на ЦП разные потоки дают отличия в последних битах, а смысл кэша в том, чтобы маска была одна для всех.

ПРАВИЛА — `tools/scout/rules/cutout-mask-cache.json`: `enabled` (ПО УМОЛЧАНИЮ false до приёмки Fable; включает директор, только на границе ступени — файл меняет, откуда берётся сырая
маска, поэтому включённый кэш пишется в метку происхождения: `origin.mask.cache`), `dir` (по умолчанию `~/remlab-logs/mask-cache`), `max_gb` (потолок 3 ГБ числом; не поднимать до замера байт/фото).
Для тестов и проб — переменные `MASK_CACHE` (0/1), `MASK_CACHE_DIR`, `MASK_CACHE_MAX_GB`, `MASK_CACHE_RULES` (путь к файлу правил). Выключенный кэш: не читается, не пишется, метка прежняя.

ПОВЕДЕНИЕ.
  • попадание — `os.utime` (давность использования), модель НЕ грузится;
  • битый файл (не PNG, не 8-битный, чужой размер) — строка `MASK-CACHE: битый файл …`, пересчёт, перезапись; молча не падает и битое не отдаёт;
  • запись — атомарно (временный файл рядом + `os.replace`): два писателя одного ключа не портят файл; ошибка записи — строка, результат вычисления не теряется;
  • потолок — перед записью самые давние по использованию файлы УХОДЯТ (единственное удаление, строго внутри папки кэша и только по потолку);
  • мало места — свободно на диске меньше порога стопа (`rules/dev-disk.json`: `start_min_free_gb` на `start_guard_path`, один источник) — не пишем, строка
    `кэш: диск, запись пропущена`; чтение продолжается.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(os.path.dirname(HERE), 'rules', 'cutout-mask-cache.json')
DISK_RULES = os.path.join(os.path.dirname(HERE), 'rules', 'dev-disk.json')
MASK_CACHE_VERSION = 1        # поднимать при ЛЮБОЙ правке того, что меняет сырую маску (Resize, нормировка, сигмоида, dtype) — старые файлы станут промахами
DEFAULT_DIR = '~/remlab-logs/mask-cache'
DEFAULT_MAX_GB = 3.0
DEFAULT_MIN_FREE_GB = 15.0
PREFIX = 'MASK-CACHE: '
_SEQ = [0]
_SEQ_LOCK = threading.Lock()


def say(msg: str) -> None:
    print(PREFIX + msg, file=sys.stderr, flush=True)


def rules(path: str | None = None) -> dict:
    """Правила кэша с учётом переменных окружения. Нет файла/битый — кэш ВЫКЛЮЧЕН (не гадаем)."""
    try:
        r = json.load(open(path or os.environ.get('MASK_CACHE_RULES') or RULES, encoding='utf-8'))
        if not isinstance(r, dict):
            r = {}
    except Exception:  # noqa: BLE001
        r = {}
    en = r.get('enabled') is True
    if os.environ.get('MASK_CACHE') in ('0', '1'):
        en = os.environ['MASK_CACHE'] == '1'
    d = os.environ.get('MASK_CACHE_DIR') or r.get('dir') or DEFAULT_DIR
    try:
        mg = float(os.environ.get('MASK_CACHE_MAX_GB') or r.get('max_gb') or DEFAULT_MAX_GB)
    except (TypeError, ValueError):
        mg = DEFAULT_MAX_GB
    return {'enabled': en, 'dir': os.path.expanduser(d), 'max_gb': mg if mg > 0 else DEFAULT_MAX_GB}


def enabled() -> bool:
    return rules()['enabled']


def label() -> str | None:
    """Строка для метки происхождения (`origin.mask.cache`): правило включено → версия кода кэша; выключено → None (метка прежняя, байт в байт)."""
    return f'v{MASK_CACHE_VERSION}' if enabled() else None


def torch_version() -> str:
    try:
        from importlib import metadata
        return metadata.version('torch')
    except Exception:  # noqa: BLE001
        return 'none'


def env_tag(repo: str, revision: str) -> str:
    return f'{repo}@{revision}|in1024|cpu-full-fp32|v{MASK_CACHE_VERSION}|torch{torch_version()}'


def key_for(src: Image.Image, tag: str) -> str:
    im = src.convert('RGB')
    h = hashlib.sha256(f'{im.width}x{im.height}:RGB:'.encode())
    h.update(im.tobytes())
    h.update(b'|' + tag.encode('utf-8'))
    return h.hexdigest()


def path_for(root: str, key: str) -> str:
    return os.path.join(root, key[:2], key + '.png')


def free_gb(path: str) -> float:
    return shutil.disk_usage(path).free / 1e9


def min_free_gb() -> tuple[float, str]:
    """Порог «мало места» — тот же, что у стопа heavy-slot (`dev-disk.json`), не своя цифра."""
    try:
        d = json.load(open(DISK_RULES, encoding='utf-8'))
        return float(d.get('start_min_free_gb', DEFAULT_MIN_FREE_GB)), os.path.expanduser(d.get('start_guard_path') or '/')
    except Exception:  # noqa: BLE001
        return DEFAULT_MIN_FREE_GB, '/'


def get(src: Image.Image, tag: str, cfg: dict | None = None) -> Image.Image | None:
    """Альфа из кэша (режим 'L', размер как у фото) или None (нет/битый — битый с пояснением). При попадании обновляет давность использования."""
    cfg = cfg or rules()
    p = path_for(cfg['dir'], key_for(src, tag))
    if not os.path.exists(p):
        return None
    try:
        a = Image.open(p)
        a.load()
        if a.mode != 'L' or a.size != src.size:
            raise ValueError(f'режим {a.mode}, размер {a.size} вместо L {src.size}')
    except Exception as e:  # noqa: BLE001 — битый файл кэша не роняет и не подставляется
        say(f'битый файл {os.path.basename(p)} ({type(e).__name__}: {str(e)[:80]}) — пересчитываю')
        return None
    try:
        os.utime(p, None)                    # давность использования: вытеснение по ней
    except OSError:
        pass
    return a


def _scan(root: str) -> list[tuple[float, int, str]]:
    out = []
    try:
        subs = [e.path for e in os.scandir(root) if e.is_dir()]
    except OSError:
        return out
    for d in subs:
        try:
            for f in os.scandir(d):
                if f.is_file() and f.name.endswith('.png'):
                    st = f.stat()
                    out.append((st.st_mtime, st.st_size, f.path))
        except OSError:
            continue
    return out


def evict(root: str, need: int, max_bytes: int) -> int:
    """Освободить место под `need` байт: уходят самые давние по использованию файлы ТОЛЬКО внутри `root`, пока сумма + need ≤ max_bytes. → сколько файлов ушло."""
    files = sorted(_scan(root))
    total = sum(s for _, s, _ in files)
    gone = 0
    for _, size, p in files:
        if total + need <= max_bytes:
            break
        if not os.path.abspath(p).startswith(os.path.abspath(root) + os.sep):
            continue
        try:
            os.remove(p)
            total -= size
            gone += 1
        except OSError:
            continue
    return gone


def put(alpha: Image.Image, src: Image.Image, tag: str, cfg: dict | None = None) -> bool:
    """Записать альфу в кэш атомарно. → записано ли. Не бросает: нет места / не пишется — строка и результат вычисления остаётся у вызывающего."""
    cfg = cfg or rules()
    try:
        need_gb, guard = min_free_gb()
        os.makedirs(cfg['dir'], exist_ok=True)
        fr = free_gb(cfg['dir'] if os.path.exists(cfg['dir']) else guard)
        if fr < need_gb:
            say(f'кэш: диск, запись пропущена (свободно {fr:.1f} ГБ < {need_gb:g})')
            return False
        key = key_for(src, tag)
        p = path_for(cfg['dir'], key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with _SEQ_LOCK:
            _SEQ[0] += 1
            n = _SEQ[0]
        tmp = f'{p}.tmp{os.getpid()}-{threading.get_ident()}-{n}'
        try:
            alpha.convert('L').save(tmp, 'PNG', compress_level=3)
            size = os.path.getsize(tmp)
            max_bytes = int(cfg['max_gb'] * 1e9)
            if size > max_bytes:
                say(f'кэш: файл {size} Б больше потолка {cfg["max_gb"]:g} ГБ — запись пропущена')
                return False
            gone = evict(cfg['dir'], size, max_bytes)
            if gone:
                say(f'кэш: потолок {cfg["max_gb"]:g} ГБ — убрано старых файлов: {gone}')
            os.replace(tmp, p)
            tmp = ''
            return True
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    except Exception as e:  # noqa: BLE001
        say(f'кэш: запись не удалась ({type(e).__name__}: {str(e)[:100]}) — идём без кэша')
        return False
