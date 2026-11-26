"""Чистка входа листа (T-20261126-98/4): фон скана → белый, выпрямление по линиям; оба шага за флагами, по умолчанию выкл.

Синтетика без внешних файлов (идёт в CI): план из толстых стен и бледных заливок на белом листе.
  • скан-фон 7/7: жёлтый тон + градиент света + шум → фон ≥ 235, чернил после/до 0,8…1,3, схожесть с оригиналом ≥ 0,95;
  • цветной лист застройщика и белый лист не меняются (ни пикселя), заливка на белом поле — тоже;
  • перекос без краёв бумаги: выпрямление применяется и поднимает долю линий на осях; ровный лист не трогается;
  • флаги выкл — `prepare()` отдаёт тот же лист, что и без модуля; FP_CLEAN_BG=1 — чистый фон.
  • стенд A–G: 0 изменений (только DEV, где лежат листы стенда; в CI пропуск).
"""
import glob
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import cleanup as cl  # noqa: E402

BENCH = Path('/home/pakar/remlab-logs/floorplan-bench')


def plan(seed, W=1200, H=900, fill=True):
    """белый лист, внешняя стена + 2–3 перегородки, бледные заливки комнат, мелкие «подписи»"""
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), 255, np.uint8)
    x0, y0, x1, y1 = 150, 120, W - 150, H - 120
    xs = sorted(rng.integers(x0 + 220, x1 - 220, 2))
    ym = int(rng.integers(y0 + 250, y1 - 250))
    cols = [(230, 214, 200), (200, 226, 214)]    # BGR, бледные
    if fill:
        cv2.rectangle(img, (x0, y0), (int(xs[0]), y1), cols[0], -1)            # заливки — меньшая часть листа (как на плане с белыми полями)
        cv2.rectangle(img, (int(xs[0]), y0), (int(xs[1]), ym), cols[1], -1)
    t = 9
    cv2.rectangle(img, (x0, y0), (x1, y1), (40, 40, 40), t)
    cv2.line(img, (int(xs[0]), y0), (int(xs[0]), y1), (40, 40, 40), t)
    cv2.line(img, (int(xs[1]), y0), (int(xs[1]), y1), (40, 40, 40), t)
    cv2.line(img, (int(xs[0]), ym), (int(xs[1]), ym), (40, 40, 40), t)
    for i in range(6):                         # «подписи»
        cx, cy = int(rng.integers(x0 + 60, x1 - 120)), int(rng.integers(y0 + 60, y1 - 60))
        cv2.putText(img, f'{rng.uniform(5, 30):.1f}', (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2, cv2.LINE_AA)
    return img


def scan_of(img, seed):
    """жёлто-серый тон + градиент света + шум + лёгкая размытость (как фото/скан листа)"""
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    r = rng.uniform(0.88, 0.94)
    tint = np.array([rng.uniform(0.62, 0.72), r - rng.uniform(0.05, 0.08), r], np.float32)   # B,G,R: бумажный жёлтый (оттенок ≤ 32), не зеленоватый
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
    light = (0.75 + 0.25 * (gx / w * 0.6 + gy / h * 0.4))[..., None]
    sc = img.astype(np.float32) * tint * light + rng.normal(0, 4, img.shape).astype(np.float32)
    return cv2.GaussianBlur(np.clip(sc, 0, 255).astype(np.uint8), (0, 0), 0.8)


def zncc(a, b):
    ga = cv2.GaussianBlur(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 2)
    gb = cv2.GaussianBlur(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 2)
    z = lambda x: (x - x.mean()) / (x.std() + 1e-6)   # noqa: E731
    return float((z(ga) * z(gb)).mean())


def tilted(img, rot_deg=6.0, tilt=0.12):
    """поворот + перспектива, кадр = вписанный в лист прямоугольник (края бумаги не видны)"""
    h, w = img.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    d = tilt * w
    dst = np.float32([[d * 0.9, d * 0.3], [w - d * 0.1, 0], [w, h], [0, h - d * 0.4]])
    M = cv2.getPerspectiveTransform(src, dst)
    R = cv2.getRotationMatrix2D((w / 2, h / 2), rot_deg, 1.0)
    M = np.vstack([R, [0, 0, 1]]) @ M
    out = cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    pc = cv2.perspectiveTransform(src.reshape(-1, 1, 2), M).reshape(-1, 2)
    xa, xb = int(max(pc[0, 0], pc[3, 0])) + 25, int(min(pc[1, 0], pc[2, 0])) - 25
    ya, yb = int(max(pc[0, 1], pc[1, 1])) + 25, int(min(pc[2, 1], pc[3, 1])) - 25
    return out[max(ya, 0):yb, max(xa, 0):xb]


# ───────────────── (б) фон скана ─────────────────

@pytest.mark.parametrize('seed', range(7))
def test_scan_background_becomes_white(seed):
    orig = plan(seed)
    sc = scan_of(orig, seed + 100)
    out, ops, info = cl.clean_bgr(sc, rectify=False, background=True)
    assert ops == ['background'], info
    bg = info['bg']
    assert bg['bg_after'] >= 235
    assert cl.INK_RATIO[0] <= bg['ink_ratio'] <= cl.INK_RATIO[1]
    assert zncc(orig, out) >= 0.95
    assert zncc(orig, out) > zncc(orig, sc) - 1e-6            # не хуже входа


def test_room_fills_survive_background_clean():
    orig = plan(3)
    out, ops, _ = cl.clean_bgr(scan_of(orig, 1), rectify=False, background=True)
    assert ops == ['background']
    # внутри комнаты заливка осталась заливкой (не белая): точка в левой комнате
    px = out[500, 200].astype(int)
    assert px.min() < 245 and (px.max() - px.min()) >= 8


@pytest.mark.parametrize('kind', ['white', 'developer_green', 'fill_in_white'])
def test_clean_sheets_untouched(kind):
    if kind == 'white':
        img = plan(5, fill=False)
    elif kind == 'developer_green':        # лист застройщика: вся площадь залита зелёным, белых полей нет
        img = np.full((900, 1200, 3), (176, 232, 176), np.uint8)
        cv2.rectangle(img, (110, 90), (1090, 810), (40, 40, 40), 9)
        cv2.line(img, (600, 90), (600, 810), (40, 40, 40), 9)
    else:                                   # заливка внутри белого поля
        img = plan(5, fill=True)
    out, ops, info = cl.clean_bgr(img, rectify=False, background=True)
    assert ops == [] and out is img, info


# ───────────────── (а) выпрямление ─────────────────

def test_rectify_fixes_tilted_sheet_and_leaves_straight_alone():
    base = plan(2, W=1400, H=1000, fill=False)
    # ровный лист: не трогаем
    out, ops, info = cl.clean_bgr(base, rectify=True, background=False)
    assert ops == [] and out is base and 'ровный' in info['rect'].get('reason', '')
    # перекос: гомография применяется, доля линий на осях растёт
    tl = tilted(base, rot_deg=6.0, tilt=0.12)
    out, ops, info = cl.clean_bgr(tl, rectify=True, background=False)
    assert ops == ['rectify'], info
    r = info['rect']
    assert r['score_after'] >= cl.SCORE_MIN_AFTER and r['score_after'] - r['score_before'] >= cl.SCORE_GAIN
    asp = out.shape[1] / out.shape[0] / (tl.shape[1] / tl.shape[0])
    assert 1 / cl.ASPECT_MAX <= asp <= cl.ASPECT_MAX


def test_rectify_blank_sheet_is_refused_not_crashed():
    out, ops, info = cl.clean_bgr(np.full((600, 800, 3), 255, np.uint8), rectify=True, background=True)
    assert ops == [] and info['rect']['reason']


# ───────────────── флаги и prepare() ─────────────────

def _write(tmp_path, img, name='in.png'):
    p = tmp_path / name
    cv2.imwrite(str(p), img)
    return p


def test_flags_off_by_default(monkeypatch):
    from PIL import Image
    monkeypatch.delenv('FP_CLEAN_BG', raising=False)
    monkeypatch.delenv('FP_CLEAN_RECT', raising=False)
    sheet = Image.fromarray(cv2.cvtColor(scan_of(plan(1), 1), cv2.COLOR_BGR2RGB))
    out, ops = cl.clean_sheet(sheet)
    assert out is sheet and ops == []


def test_prepare_flag_gated(tmp_path, monkeypatch):
    import pipeline as pl
    from PIL import Image
    sc = scan_of(plan(4), 7)
    src = _write(tmp_path, sc)
    monkeypatch.delenv('FP_CLEAN_BG', raising=False)
    monkeypatch.delenv('FP_CLEAN_RECT', raising=False)
    off, _, _ = pl.prepare(src, 'image/png', tmp_path / 'off')
    assert np.array_equal(np.asarray(Image.open(off).convert('RGB')), np.asarray(Image.open(src).convert('RGB')))
    monkeypatch.setenv('FP_CLEAN_BG', '1')
    on, source, _ = pl.prepare(src, 'image/png', tmp_path / 'on')
    a = np.asarray(Image.open(on).convert('RGB'))
    assert np.median(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)) >= 235
    assert source['imageW'] == a.shape[1] and source['imageH'] == a.shape[0]


def test_clean_sheet_failure_returns_sheet(monkeypatch):
    from PIL import Image
    monkeypatch.setenv('FP_CLEAN_BG', '1')
    monkeypatch.setattr(cl, 'clean_background', lambda b: (_ for _ in ()).throw(RuntimeError('boom')))
    sheet = Image.fromarray(np.full((200, 300, 3), 200, np.uint8))
    out, ops = cl.clean_sheet(sheet)
    assert out is sheet and ops == []


# ───────────────── усиление бледных линий (FP_CLEAN_LINES) ─────────────────

def faint_plan(seed, line=(185, 185, 185), W=1000, H=800, paper=246):
    """бледный серый скан БТИ: тонкие светло-серые линии и «подписи» на светлой бумаге с лёгким шумом"""
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), paper, np.uint8)
    cv2.rectangle(img, (120, 100), (W - 120, H - 100), line, 3)
    cv2.line(img, (480, 100), (480, H - 100), line, 2)
    cv2.line(img, (120, 420), (480, 420), line, 2)
    for k in range(8):
        cv2.putText(img, '%d.%d' % (k + 1, k * 3), (200 + 60 * k, 300), cv2.FONT_HERSHEY_SIMPLEX, 0.6, line, 1, cv2.LINE_AA)
    noise = rng.normal(0, 1.2, (H, W, 1))
    return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def test_lines_faint_become_darker_paper_untouched():
    img = faint_plan(1)
    out, info = cl.strengthen_lines(img)
    assert out is not None, info
    g0, g1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    ink = g0 < 225
    assert g1[ink].mean() < g0[ink].mean() - 40                  # линии заметно темнее
    paper = cv2.erode((g0 >= 240).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    assert np.abs(g1[paper].astype(int) - g0[paper]).max() <= 2  # бумага вдали от линий не изменилась
    assert out.shape == img.shape                                # геометрия та же
    assert info['paper_leak'] <= 0.001 and 1.0 <= info['ink_area_ratio'] <= 2.6


def test_lines_already_contrasty_refused():
    img = faint_plan(2, line=(40, 40, 40))
    out, info = cl.strengthen_lines(img)
    assert out is None and 'контрастные' in info['reason']


def test_lines_blank_and_uneven_refused():
    assert cl.strengthen_lines(np.full((400, 600, 3), 245, np.uint8))[0] is None
    img = faint_plan(3)
    grad = np.linspace(0, 110, img.shape[1], dtype=np.float32)[None, :, None]
    img = np.clip(img.astype(np.float32) - grad, 0, 255).astype(np.uint8)                          # сильный градиент света — неровный фон
    out, info = cl.strengthen_lines(img)
    assert out is None and ('неровный' in info['reason'] or 'контрастные' in info['reason'])    # на ярко-неровном фоне усиление не делаем


def test_lines_grain_not_amplified():
    """зерно бумаги (отдельные пятна неглубокие) не усиливается: от линий не больше, чем «штрихи»"""
    img = faint_plan(4)
    rng = np.random.default_rng(5)
    grain = cv2.GaussianBlur(rng.normal(0, 1, img.shape[:2]).astype(np.float32), (0, 0), 3) * 18
    img = np.clip(img.astype(np.float32) + grain[..., None], 0, 255).astype(np.uint8)
    out, info = cl.strengthen_lines(img)
    if out is not None:
        g0, g1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        away = cv2.erode((g0 > 215).astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
        assert (g0.astype(int) - g1)[away].max() <= 6


def test_lines_flag_gated(monkeypatch):
    from PIL import Image
    sheet = Image.fromarray(cv2.cvtColor(faint_plan(6), cv2.COLOR_BGR2RGB))
    monkeypatch.delenv('FP_CLEAN_BG', raising=False)
    monkeypatch.delenv('FP_CLEAN_RECT', raising=False)
    monkeypatch.delenv('FP_CLEAN_LINES', raising=False)
    out, ops, steps = cl.clean_sheet_steps(sheet)
    assert out is sheet and ops == [] and steps == []
    monkeypatch.setenv('FP_CLEAN_LINES', '1')
    out, ops, steps = cl.clean_sheet_steps(sheet)
    assert ops == ['lines'] and steps == [] and out.size == sheet.size          # геометрия не меняется → обратное преобразование пустое


# ───────────────── стенд A–G (DEV) ─────────────────

def _bench_sheets():
    items = []
    for n in ('A-uk-house-125m2.jpg', 'B-uk-floor-90m2.jpg', 'C-uk-nethercote-611m2.png'):
        p = BENCH / 'inputs' / n
        if p.exists():
            items.append(p)
    for g in 'DEFG':
        c = [x for x in sorted(glob.glob(str(BENCH / 'blind' / g / '*.*'))) if Path(x).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp') and 'dims' not in x]
        if c:
            items.append(Path(c[0]))
    return items


@pytest.mark.skipif(len(_bench_sheets()) < 7, reason='нет листов стенда A–G (только DEV)')
def test_bench_A_to_G_zero_changes():
    from PIL import Image
    changed = []
    for p in _bench_sheets():
        im = Image.open(p)
        im.load()
        rgb = im.convert('RGB')
        bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
        if bgr.shape[0] > 2000 or bgr.shape[1] > 2000:
            k = 2000 / max(bgr.shape[:2])
            bgr = cv2.resize(bgr, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        _, ops, info = cl.clean_bgr(bgr, rectify=True, background=True)
        if ops:
            changed.append((p.name, ops, info))
    assert not changed, changed
