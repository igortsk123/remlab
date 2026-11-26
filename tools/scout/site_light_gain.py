"""T-99/11 шаг 2 (Fable 14 §2.2/§3): яркость Ш4а — под СВЕТ САЙТА. Серые плашки (несколько уровней) один раз под светом сайта и под светом подгонки Ш4а (model-viewer neutral) →
кривая отклика по каналам (Fable ждал три множителя, но замер показал, что множитель зависит от уровня серого: ×1,87 / ×1,57 / ×1,14 на 64 / 128 / 200 — свет сайта и тонмаппинг нелинейны; одно число было бы неверным).
Кривая — свойство света, одна на все товары: лежит в rules/part-material.json fit.site_light.curve вместе с отпечатком света сайта (`light_sha`); сменился свет сайта
(data/flat3d/sides-sheet.json site.light) — отпечаток не сходится, Ш4а воздерживается (не красит старыми числами).
  python3 site_light_gain.py [--write]   — померить (и вписать числа в правила);  site_light_gain.py --check — только сверить отпечаток.
Все функции чистые, кроме measure/CLI (они снимают кадры Chromium)."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SHEET_JSON = os.path.join(HERE, '..', '..', 'data', 'flat3d', 'sides-sheet.json')
RULES_PM = os.path.join(HERE, 'rules', 'part-material.json')


def site_spec(path: str = SHEET_JSON) -> dict:
    """Свет сайта (зеркало lib/viewer3d/window-light.ts:LIGHT) и библиотеки three — из data/flat3d/sides-sheet.json site."""
    with open(path, encoding='utf-8') as f:
        return json.load(f)['site']


def light_sha(site: dict) -> str:
    """Отпечаток света сайта: числа света + fov (тонмаппинг и env вшиты в site_light_render.js, его правка — повод пересъёмки вручную)."""
    return hashlib.sha1(json.dumps({'light': site['light'], 'fov': site['fov']}, sort_keys=True).encode()).hexdigest()[:12]


def curve_from(levels: list) -> dict:
    """levels: [{'plate_srgb', 'neutral': [r,g,b] лин., 'site': [r,g,b] лин.}] → кривая {a: альбедо плашки (лин.), neutral: [[r,g,b]…], site: [[r,g,b]…]}.
    Свет сайта и свет подгонки по-разному нелинейны (тонмаппинг, «носок» тёмного) — множитель зависит от уровня (плашки 64/128/200: ×1,87/×1,57/×1,14), поэтому не одно число, а кривая."""
    import part_material as PM
    a = [round(float(PM.srgb2lin(L['plate_srgb'])), 5) for L in levels]
    return {'a': a, 'neutral': [[round(x, 5) for x in L['neutral']] for L in levels], 'site': [[round(x, 5) for x in L['site']] for L in levels]}


def multipliers(curve: dict, at_srgb: int = 128) -> list:
    """Множители по каналам на уровне серого at_srgb (для отчёта и сравнения с «три множителя» Fable): site-альбедо / neutral-альбедо при том же отклике."""
    import part_material as PM
    a = float(PM.srgb2lin(at_srgb))
    f = remap_lin(np.array([[a] * 3]), curve)[0]
    return [round(float(x / a), 4) for x in f]


def remap_lin(x: np.ndarray, curve: dict) -> np.ndarray:
    """x (N,3) — линейное альбедо, подобранное под свет подгонки (отклик там = тон фото). → альбедо, которое под светом САЙТА даёт ТОТ ЖЕ отклик по ЯРКОСТИ: Y' = S⁻¹(N(Y)),
    все каналы умножаются на Y'/Y (цветность — оттенок и насыщенность фото — не меняется; по каналам отдельно свет сайта (тёплое солнце) сдвинул оттенок верха Хостера 74,6° → 80,5°,
    luma_only Ш4а из-за этого и ввели, T-99/7). N и S — кривые отклика серой плашки (по яркости: среднее трёх каналов), кусочно-линейные, (0,0) добавлен; выше предела отклика сайта — 1,0."""
    a = np.concatenate([[0.0], np.asarray(curve['a'], float)])
    n = np.concatenate([[0.0], np.asarray(curve['neutral'], float).mean(1)])
    s = np.concatenate([[0.0], np.asarray(curve['site'], float).mean(1)])
    x = np.asarray(x, float)
    y = 0.2126 * x[:, 0] + 0.7152 * x[:, 1] + 0.0722 * x[:, 2]
    y2 = np.interp(np.interp(y, a, n), s, a)                              # S⁻¹(N(Y))
    return np.clip(x * (y2 / np.maximum(y, 1e-6))[:, None], 0.0, 1.0)


def remap_srgb8(tex: np.ndarray, mask: np.ndarray, curve: dict) -> np.ndarray:
    """Текстура uint8 sRGB: тексели mask — через remap_lin (линейно ↔ sRGB 8 бит); остальное — байт в байт."""
    import part_material as PM
    out = tex.copy()
    px = tex[mask].reshape(-1, 3)
    if len(px):
        lin = PM.srgb2lin(px)
        out[mask] = np.clip(PM.lin2srgb(remap_lin(lin, curve)) + 0.5, 0, 255).astype(np.uint8)
    return out


def plate_glb(path: str, srgb: int, rough: float, size: float = 10.0) -> None:
    """Горизонтальная плашка (нормаль вверх), ровный серый sRGB `srgb`, шероховатость как у кадров подбора."""
    import trimesh
    from PIL import Image
    h = size / 2
    V = np.array([[-h, 0, -h], [h, 0, -h], [h, 0, h], [-h, 0, h]], float)
    F = np.array([[0, 2, 1], [0, 3, 2]])
    UV = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], float)
    im = Image.fromarray(np.full((16, 16, 3), int(srgb), np.uint8))
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=im, metallicFactor=0.0, roughnessFactor=float(rough))
    m = trimesh.Trimesh(vertices=V, faces=F, process=False, visual=trimesh.visual.TextureVisuals(uv=UV, material=mat))
    m.export(path, file_type='glb')


def centre_lin(png: str, frac: float = 0.3) -> list:
    """Медиана линейного цвета по центральному квадрату кадра (доля стороны frac)."""
    from PIL import Image
    a = np.asarray(Image.open(png).convert('RGB'))
    h, w = a.shape[:2]
    dy, dx = int(h * frac / 2), int(w * frac / 2)
    c = a[h // 2 - dy:h // 2 + dy, w // 2 - dx:w // 2 + dx].reshape(-1, 3)
    import part_material as PM
    return [float(x) for x in np.median(PM.srgb2lin(c), axis=0)]


def measure(rules: dict, workdir: str, runner=None) -> dict:
    """Плашка серого на каждом уровне rules.fit.site_light.plate_srgb → кадр под светом сайта и под светом подгонки (model-viewer, orbit top_orbit)."""
    import part_material as PM
    sl = rules['fit']['site_light']
    site = site_spec()
    os.makedirs(workdir, exist_ok=True)
    jobs_site, jobs_nv, lv = [], [], []
    for s in sl['plate_srgb']:
        g = os.path.join(workdir, 'plate-%d.glb' % s)
        plate_glb(g, s, rules['unlit_roughness'])
        jobs_nv.append({'glb': g, 'out': os.path.join(workdir, 'plate-%d-neutral.png' % s), 'orbit': rules['fit']['top_orbit'], 'size': 420})
        jobs_site.append({'glb': g, 'out': os.path.join(workdir, 'plate-%d-site.png' % s), 'th': 0, 'polar': 1.0, 'k': 1.05})
        lv.append(s)
    PM.render_jobs(jobs_nv, rules, workdir)
    spec = {'size': 420, 'libs': site['libs'], 'light': site['light'], 'fov': site['fov'], 'chromium_args': rules['tools']['chromium_args'], 'jobs': jobs_site}
    sp = os.path.join(workdir, 'site-spec.json')
    with open(sp, 'w', encoding='utf-8') as f:
        json.dump(spec, f)
    js = os.path.join(HERE, 'site_light_render.js')
    r = (runner or (lambda s: subprocess.run(['node', js, s], capture_output=True, text=True, env=PM.node_env(), timeout=3000)))(sp)
    if r.returncode:
        raise RuntimeError('кадры света сайта: ' + (r.stdout + r.stderr)[-600:])
    return [{'plate_srgb': s, 'neutral': centre_lin(j['out']), 'site': centre_lin(k['out'])} for s, j, k in zip(lv, jobs_nv, jobs_site)]


def current_curve(rules: dict) -> tuple:
    """(кривая или None, причина) — для Ш4а: выкл → None; отпечаток света сайта не сходится → ошибка (не красить старыми числами)."""
    sl = (rules.get('fit') or {}).get('site_light') or {}
    if not sl.get('enabled'):
        return None, 'выкл'
    sha = light_sha(site_spec())
    if sl.get('light_sha') != sha:
        raise ValueError('свет сайта изменился (отпечаток %s, в правилах %s): пересними кривую — python3 tools/scout/site_light_gain.py --write' % (sha, sl.get('light_sha')))
    c = sl.get('curve')
    if not c or len(c.get('a', [])) < 3:
        raise ValueError('в правилах fit.site_light нет кривой: python3 tools/scout/site_light_gain.py --write')
    return c, 'ok'


def write_rules(curve: dict, sha: str, path: str = RULES_PM) -> None:
    """Вписать кривую и отпечаток в текст правил (без пересборки JSON — файл остаётся как набран)."""
    s = open(path, encoding='utf-8').read()
    s2 = re.sub(r'("curve": )(null|\{[^{}]*\})', lambda m: m.group(1) + json.dumps(curve, separators=(',', ':')), s, count=1)
    s2 = re.sub(r'("light_sha": )"[^"]*"', lambda m: m.group(1) + json.dumps(sha), s2, count=1)
    if s2 == s:
        print('правила не изменились')
        return
    json.loads(s2)
    open(path, 'w', encoding='utf-8').write(s2)


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    sys.path.insert(0, HERE)
    rules = json.load(open(RULES_PM, encoding='utf-8'))
    sha = light_sha(site_spec())
    if '--check' in argv:
        ok = rules['fit']['site_light'].get('light_sha') == sha
        print('отпечаток света сайта %s, в правилах %s — %s' % (sha, rules['fit']['site_light'].get('light_sha'), 'сходится' if ok else 'НЕ СХОДИТСЯ'))
        return 0 if ok else 1
    wd = tempfile.mkdtemp(prefix='site-light-')
    lv = measure(rules, wd)
    curve = curve_from(lv)
    print(json.dumps({'кривая': curve, 'множители_на_128': multipliers(curve, 128), 'на_64': multipliers(curve, 64), 'на_200': multipliers(curve, 200), 'отпечаток': sha, 'кадры': wd}, ensure_ascii=False))
    if '--write' in argv:
        write_rules(curve, sha)
    return 0


if __name__ == '__main__':
    sys.exit(main())
