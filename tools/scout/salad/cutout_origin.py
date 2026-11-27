#!/usr/bin/env python3
"""ПРОИСХОЖДЕНИЕ ВХОДА ФОРМЫ — метка версии единой цепочки вырезки и запись «откуда этот вход» (T-20261127-175/9, Fable 29 шаги 1–2).

ЗАЧЕМ. Форму TRELLIS.2 строят по вырезке. В банке жили три способа вырезки; вход мог быть сделан любым, а по самому файлу не отличить. Теперь вход делает один
модуль (`cutout_one.py`), а эта запись — его паспорт: кто сделал (способ + версия цепочки + набор шагов), из какой маски (источник + версия весов), каким кодом,
из какого фото (sha256), когда. Запись лежит в ДВУХ местах: поле `origin` в `inputs.json` и текстовая метка `remlab.origin` внутри самого PNG (файл, унесённый
отдельно от inputs.json, остаётся опознаваемым). Проверка «метка актуальна» — `check()` / `check_png()`: на старте круга (задача 175/10) и в `trellis_trial.py`.

МЕТКА ВЕРСИИ `CHAIN_VERSION` — НЕ `preprocess.ASSESSOR_VERSION`: та входит в ключ кэша оценок (`photo_assessment`, ~16,6 тыс. фото) и менять её = пересчитать весь пул.
`CHAIN_VERSION` ключа кэша не меняет: поднимать при любой правке шагов цепочки, влияющей на байты вырезки (тогда старые входы формы станут «неактуальными»
и откажутся на старте круга, а ночная оценка пула останется как есть — её версия своя).

Модуль лёгкий (stdlib; PIL — только внутри функций с PNG): его читают проверки, у которых нет torch/scipy.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess

CHAIN_VERSION = 'c1'                   # версия единой цепочки `cutout_one.cut_shape` (см. выше; НЕ ASSESSOR_VERSION)
ORIGIN_FORMAT = 1                      # версия формата записи
METHOD = 'cutout_one'                  # способ вырезки (единственный разрешённый для входа формы)
MASK_SOURCE = 'birefnet-full-cpu-fp32'  # источник сырой маски входа формы: ПОЛНАЯ BiRefNet на ЦП, float32 (fal-Light — только ночная оценка)
BIREFNET_REPO = 'ZhengPeng7/BiRefNet'
# Ревизия закреплена полным хешем (T-46/3): без неё transformers тянет свежий код автора и исполняет его без проверки. Смена — только с пробой.
BIREFNET_REVISION = 'e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4'
STEPS_ALL = ('attached_prune', 'main_object')   # необязательные шаги старой цепочки, перенесённые в единый модуль (по умолчанию выключены)
PNG_KEY = 'remlab.origin'              # ключ текстовой метки внутри PNG
FIELDS = ('format', 'method', 'chain_version', 'steps', 'mask', 'code', 'photo_sha256', 'pixels_sha256', 'created')


def code_version(root: str | None = None) -> str:
    """Короткий хеш коммита кода (`git rev-parse --short HEAD` в каталоге модуля); нет git — 'unknown' (проверка такой код не принимает)."""
    root = root or os.path.dirname(os.path.abspath(__file__))
    try:
        r = subprocess.run(['git', '-C', root, 'rev-parse', '--short=9', 'HEAD'], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
        v = r.stdout.strip()
        return v if r.returncode == 0 and re.fullmatch(r'[0-9a-f]{7,40}', v) else 'unknown'
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def pixels_sha256(img) -> str:
    """Хеш СОДЕРЖИМОГО вырезки: sha256 от «ШxВ:RGBA» и байтов пикселей (не файла). От даты, текстовых меток и кодировщика PNG не зависит — по нему программа
    сравнения («вход равнозначен», задача 175/10) узнаёт ту же вырезку в любом файле. Хеш ФАЙЛА — `input_png_sha256` в inputs.json (включает метку с датой)."""
    im = img.convert('RGBA')
    return hashlib.sha256(f'{im.width}x{im.height}:RGBA:'.encode() + im.tobytes()).hexdigest()


def build(raw: bytes, steps=(), now: datetime.datetime | None = None, code: str | None = None, *, shape=None, pixels: str | None = None) -> dict:
    """Запись происхождения входа, сделанного из фото `raw` (исходные байты) единой цепочкой с набором шагов `steps`; `shape` — готовая вырезка полного холста (RGBA) или (для тестов) готовый `pixels` — хеш содержимого."""
    if shape is None and pixels is None:
        raise ValueError('нужна готовая вырезка (shape) — хеш её содержимого входит в запись')
    st = sorted(set(steps))
    bad = [s for s in st if s not in STEPS_ALL]
    if bad:
        raise ValueError(f'неизвестные шаги цепочки {bad}: допустимо {STEPS_ALL}')
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return {'format': ORIGIN_FORMAT, 'method': METHOD, 'chain_version': CHAIN_VERSION, 'steps': st,
            'mask': {'source': MASK_SOURCE, 'repo': BIREFNET_REPO, 'revision': BIREFNET_REVISION},
            'code': code if code is not None else code_version(),
            'photo_sha256': hashlib.sha256(raw).hexdigest(),
            'pixels_sha256': pixels if pixels is not None else pixels_sha256(shape),
            'created': now.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}


def check(origin) -> list[str]:
    """Ошибки записи происхождения (пусто = вход сделан актуальной цепочкой). Каждая — фраза для человека, без исключений."""
    if not isinstance(origin, dict):
        return ['нет метки происхождения (поле origin): вход сделан не единым модулем вырезки — сделай его заново `salad/trellis/make_inputs.py`']
    errs = []
    miss = [k for k in FIELDS if k not in origin]
    if miss:
        errs.append(f'в метке нет полей {miss}')
    if origin.get('format') != ORIGIN_FORMAT:
        errs.append(f'формат метки {origin.get("format")!r} ≠ {ORIGIN_FORMAT}')
    if origin.get('method') != METHOD:
        errs.append(f'способ вырезки {origin.get("method")!r} ≠ {METHOD!r}')
    if origin.get('chain_version') != CHAIN_VERSION:
        errs.append(f'версия цепочки {origin.get("chain_version")!r} ≠ актуальной {CHAIN_VERSION!r} — вход устарел, пересчитать')
    st = origin.get('steps')
    if not isinstance(st, list) or any(s not in STEPS_ALL for s in st):
        errs.append(f'steps={st!r}: допустимо подмножество {STEPS_ALL}')
    m = origin.get('mask')
    if not isinstance(m, dict) or (m.get('source'), m.get('repo'), m.get('revision')) != (MASK_SOURCE, BIREFNET_REPO, BIREFNET_REVISION):
        errs.append(f'источник маски {m!r} ≠ {{source: {MASK_SOURCE}, repo: {BIREFNET_REPO}, revision: {BIREFNET_REVISION[:8]}…}}')
    code = origin.get('code')
    if not isinstance(code, str) or not re.fullmatch(r'[0-9a-f]{7,40}', code):
        errs.append(f'версия кода {code!r}: нужен хеш коммита (git недоступен при сборке входа?)')
    ph = origin.get('photo_sha256')
    if not isinstance(ph, str) or not re.fullmatch(r'[0-9a-f]{64}', ph):
        errs.append('photo_sha256: нужен sha256 исходных байтов фото (64 hex)')
    px = origin.get('pixels_sha256')
    if not isinstance(px, str) or not re.fullmatch(r'[0-9a-f]{64}', px):
        errs.append('pixels_sha256: нужен sha256 содержимого вырезки (64 hex)')
    cr = origin.get('created')
    try:
        datetime.datetime.strptime(cr, '%Y-%m-%dT%H:%M:%SZ')
    except (TypeError, ValueError):
        errs.append(f'created={cr!r}: нужна дата ГГГГ-ММ-ДДTЧЧ:ММ:ССZ')
    return errs


def png_text(origin: dict) -> str:
    """Канонический текст метки для PNG (ключи по алфавиту, без пробелов): одна и та же запись → один и тот же текст."""
    return json.dumps(origin, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def png_bytes(img, origin: dict) -> bytes:
    """PNG картинки с текстовой меткой `remlab.origin`. Пиксели те же, что без метки (метка — отдельный блок файла)."""
    import io
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text(PNG_KEY, png_text(origin))
    buf = io.BytesIO()
    img.save(buf, 'PNG', pnginfo=info)
    return buf.getvalue()


def read_png(path: str) -> dict | None:
    """Метка из PNG (разбор блоков tEXt/iTXt без PIL: проверка работает и там, где Pillow нет); нет метки / файл не PNG / битая — None."""
    import struct
    import zlib
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return None
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    key = PNG_KEY.encode()
    i, text = 8, None
    try:
        while i + 8 <= len(data):
            n, typ = struct.unpack('>I4s', data[i:i + 8])
            body = data[i + 8:i + 8 + n]
            i += 12 + n
            if typ == b'tEXt':
                k, _, v = body.partition(b'\0')
                if k == key:
                    text = v.decode('latin-1')
            elif typ == b'iTXt':
                k, rest = body.split(b'\0', 1)
                if k == key:
                    flag, rest = rest[0], rest[2:]               # флаг сжатия, метод
                    _, rest = rest.split(b'\0', 1)               # язык
                    _, rest = rest.split(b'\0', 1)               # перевод ключа
                    text = (zlib.decompress(rest) if flag else rest).decode('utf-8')
            elif typ == b'IEND':
                break
        v = json.loads(text) if text else None
    except (ValueError, struct.error, zlib.error, IndexError):
        return None
    return v if isinstance(v, dict) else None


def placeholder_png(origin: dict) -> bytes:
    """ДЛЯ ТЕСТОВ: минимальный PNG 1×1 с меткой `remlab.origin` — без Pillow (тесты проб, где настоящая вырезка не нужна, а файл рядом с inputs.json должен быть)."""
    import struct
    import zlib

    def chunk(t, b):
        return struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
            + chunk(b'tEXt', PNG_KEY.encode() + b'\0' + png_text(origin).encode('latin-1', 'replace'))
            + chunk(b'IDAT', zlib.compress(b'\0\0\0\0\0')) + chunk(b'IEND', b''))


def check_png(path: str, entry: dict | None = None) -> list[str]:
    """Проверка файла входа: метка внутри PNG есть и актуальна; если дана запись товара `entry` из inputs.json — метка совпадает с её `origin`, а sha256 файла —
    с её `input_png_sha256`."""
    entry = entry or {}
    want = entry.get('origin')
    got = read_png(path)
    errs = [f'в PNG {os.path.basename(path)}: ' + e for e in check(got)]
    if got is not None and isinstance(want, dict) and got != want:
        errs.append(f'метка внутри PNG {os.path.basename(path)} расходится с origin в inputs.json')
    sha = entry.get('input_png_sha256')
    if sha and os.path.exists(path):
        h = hashlib.sha256(open(path, 'rb').read()).hexdigest()
        if h != sha:
            errs.append(f'sha256 файла {os.path.basename(path)} ({h[:12]}…) ≠ input_png_sha256 ({str(sha)[:12]}…): файл подменён после записи')
    return errs


def inputs_errors(inputs: dict, skus, inputs_dir: str | None = None) -> list[str]:
    """Для проверки перед платным запуском: у каждого товара из `skus` запись `origin` актуальна; если рядом лежит `<товар>.rgba.png` — и метка внутри него."""
    errs = []
    for sku in skus:
        e = (inputs or {}).get(sku)
        if not isinstance(e, dict):
            errs.append(f'{sku}: нет записи в inputs.json')
            continue
        errs += [f'{sku}: {x}' for x in check(e.get('origin'))]
        if inputs_dir:
            p = os.path.join(inputs_dir, sku.replace(':', '_') + '.rgba.png')
            if os.path.exists(p):
                errs += [f'{sku}: {x}' for x in check_png(p, e)]
            else:      # проверка не смогла сработать — говорим об этом, а не молчим «чисто»
                errs.append(f'{sku}: файла вырезки {os.path.basename(p)} нет в {inputs_dir} — метку внутри PNG проверить нечем')
    return errs


def write_test_inputs(inputs_dir: str, skus) -> dict:
    """ТОЛЬКО для тестов: пишет `inputs.json` с актуальной меткой и минимальный `<товар>.rgba.png` с той же меткой и честным sha256 — вход, который проверка пропускает."""
    png = placeholder_png(example())
    sha = hashlib.sha256(png).hexdigest()
    inp = {}
    for sku in skus:
        open(os.path.join(inputs_dir, sku.replace(':', '_') + '.rgba.png'), 'wb').write(png)
        inp[sku] = {'input_png_sha256': sha, 'origin': example()}
    with open(os.path.join(inputs_dir, 'inputs.json'), 'w', encoding='utf-8') as f:
        json.dump(inp, f)
    return inp


def example(now: datetime.datetime | None = None) -> dict:
    """Пример АКТУАЛЬНОЙ записи (для тестов, где нужен «годный» inputs.json без настоящего фото)."""
    return build(b'example', (), now=now or datetime.datetime(2026, 11, 27, tzinfo=datetime.timezone.utc), code='0000000', pixels=hashlib.sha256(b'example-pixels').hexdigest())


if __name__ == '__main__':
    import sys
    if '--selftest' in sys.argv:
        o = example()
        assert check(o) == [], check(o)
        assert check(dict(o, chain_version='a0')) and check(None) and check(dict(o, code='unknown'))
        assert check(dict(o, mask=dict(o['mask'], revision='0' * 40)))
        print('cutout_origin: OK')
    else:
        print(f'CHAIN_VERSION={CHAIN_VERSION} METHOD={METHOD} MASK={MASK_SOURCE} {BIREFNET_REPO}@{BIREFNET_REVISION}')
