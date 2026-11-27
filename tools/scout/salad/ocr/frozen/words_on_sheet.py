#!/usr/bin/env python3
"""T-98/15: на листе плана есть ИМЕНА КОМНАТ СЛОВАМИ? (кухня, ванная, санузел …) — OCR кириллицы на наших ядрах, $0.
  words_on_sheet(путь_листа) -> {'words': bool, 'found': [слова], 'conf': float, 'n_lines': int}
Один источник флага для р.5 (neutral_names, п.10) и сторожа (storozh.n_labels_r5). Словарь и пороги — words_rules.json (не в коде).
Запуск (venv ocr-trial, Python 3.14):  ~/venvs/ocr-trial/bin/python -I words_on_sheet.py <лист.jpg> [...]  → JSON на строку.
Цифры, площади, размеры, «м²», номера квартир и английские слова словами не считаются: совпадение только со словарём имён помещений."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = json.load(open(HERE + '/words_rules.json', encoding='utf-8'))
_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
        p = {'Rec.lang_type': getattr(LangRec, RULES['lang'].upper()), 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': getattr(ModelType, RULES.get('rec_model_type', 'mobile').upper())}
        if RULES.get('det_limit_side_len'):
            p['Det.limit_side_len'] = RULES['det_limit_side_len']
            p['Det.limit_type'] = 'max'
        _ENGINE = RapidOCR(params=p)
    return _ENGINE


def norm(s):
    return re.sub(r'\s+', ' ', str(s).lower().replace('ё', 'е')).strip()


def lev(a, b):
    """расстояние Левенштейна (короткие слова)"""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def match_word(tok, words=None):
    """токен OCR → слово словаря или None. Точное совпадение; для слов ≥ edit_min_len — расстояние ≤ max_edit."""
    tok = norm(tok).strip('.,;:()[]{}«»"\'_-—–')
    if len(tok) < 2:
        return None
    for w in (words or RULES['words']):
        if tok == w:
            return w
    for w in (words or RULES['words']):
        if len(w) >= RULES['edit_min_len'] and abs(len(tok) - len(w)) <= RULES['max_edit'] and lev(tok, w) <= RULES['max_edit']:
            return w
    return None


def find_words(lines):
    """lines: [(текст, уверенность)] → (найденные слова, макс. уверенность)."""
    found, conf = [], 0.0
    for txt, sc in lines:
        if sc < RULES['min_conf']:
            continue
        t = norm(txt)
        cands = [t] + [x for x in re.split(r'[\s,;:()]+', t) if x]       # строка целиком (с/у, «кухня-гостиная») и по словам
        for c in cands:
            w = match_word(c)
            if w:
                if w not in found:
                    found.append(w)
                conf = max(conf, float(sc))
                break
    return found, conf


def _items(r, dx=0, dy=0):
    txts = list(r.txts) if getattr(r, 'txts', None) is not None else []
    scs = list(r.scores) if getattr(r, 'scores', None) is not None else []
    boxes = list(r.boxes) if getattr(r, 'boxes', None) is not None else []
    return [(t, float(s), [(float(p[0]) + dx, float(p[1]) + dy) for p in b]) for t, s, b in zip(txts, scs, boxes)]


def ocr_items(path):
    """→ [(текст, уверенность, бокс в координатах листа)]. Целый лист + (если сторона > tile_min_side) плитки tile_px с перекрытием tile_overlap:
    на больших листах с жирными стенами детектор целиком не видит мелкий текст (novosibirsk «Общая площадь» — 0 строк), плитки видят."""
    import cv2
    eng = _engine()
    items = _items(eng(path))
    tp = RULES.get('tile_px')
    if tp:
        img = cv2.imread(path)
        h, w = img.shape[:2]
        if max(h, w) > RULES.get('tile_min_side', 1200):
            step = tp - RULES.get('tile_overlap', 100)
            for y in range(0, max(h - RULES.get('tile_overlap', 100), 1), step):
                for x in range(0, max(w - RULES.get('tile_overlap', 100), 1), step):
                    items += _items(eng(img[y:y + tp, x:x + tp]), x, y)
    return items


def ocr_lines(path):
    return [(t, s) for t, s, _b in ocr_items(path)]


def words_on_sheet(path):
    lines = ocr_lines(path)
    found, conf = find_words(lines)
    return {'words': len(found) >= RULES['min_words'], 'found': found, 'conf': round(conf, 3), 'n_lines': len(lines)}


CACHE = os.environ.get('WORDS_FLAGS_CACHE') or HERE + '/words_flags.json'     # T-98/16: прогон из снимка пишет промахи кэша в свою папку, а не в снимок


def sheet_sha(path):
    """ключ кэша — sha256 ФАЙЛА листа (не id): новый лист под тем же id не получит старый флаг (директор 26.11)"""
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def rules_ver():
    """версия правил: поменялись словарь/пороги/плитки → записи кэша со старой версией считаются промахом"""
    import hashlib
    return hashlib.sha256(open(HERE + '/words_rules.json', 'rb').read()).hexdigest()[:12]


def _cache_load():
    try:
        return json.load(open(CACHE, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def cache_lookup(path):
    """→ запись кэша (dict) или None (промах: нет файла/ключа или другая версия правил)"""
    e = _cache_load().get(sheet_sha(path))
    return e if e and e.get('rules') == rules_ver() else None


def words_cached(path):
    """кэш по sha256 файла листа; промах → OCR (нужен venv ocr-trial) → запись в кэш (атомарно). → dict как words_on_sheet + 'cache': bool"""
    e = cache_lookup(path)
    if e:
        return {**{k: e[k] for k in ('words', 'found', 'conf', 'n_lines')}, 'cache': True}
    r = words_on_sheet(path)
    c = _cache_load()
    c[sheet_sha(path)] = {**r, 'rules': rules_ver(), 'sheet': os.path.basename(os.path.dirname(os.path.abspath(path)))}
    tmp = CACHE + '.tmp%d' % os.getpid()
    json.dump(c, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    os.replace(tmp, CACHE)
    return {**r, 'cache': False}


def flag_for(path):
    """Для ЛЮБОГО venv (storozh, neutral_names): кэш → иначе OCR подпроцессом в venv ocr-trial (он же запишет кэш). → dict или None"""
    e = cache_lookup(path)
    if e:
        return {**{k: e[k] for k in ('words', 'found', 'conf', 'n_lines')}, 'cache': True}
    return words_flag(path)


def words_flag(path):
    """Для вызова из ДРУГИХ venv (neutral_names, storozh — они не в ocr-trial): запускает этот же файл в venv ocr-trial и возвращает тот же dict.
    Модуль без rapidocr импортируется где угодно (rapidocr грузится лениво в _engine)."""
    import subprocess
    py = os.path.expanduser('~/venvs/ocr-trial/bin/python')
    out = subprocess.run([py, '-I', HERE + '/words_on_sheet.py', path], capture_output=True, text=True, timeout=300).stdout.strip().splitlines()
    return json.loads(out[-1]) if out else None


if __name__ == '__main__':
    for p in sys.argv[1:]:
        print(json.dumps({'лист': p, **words_cached(p)}, ensure_ascii=False), flush=True)
