"""Разбор замеров прототипа света (T-20261111-22): цвет предметов «фото товара / альбедо модели / кадр 3D при каждом свете» + склейки.

Вход — папка `shoot.cjs` (`<tag>.json`, `<tag>-m-{beauty,ids,albedo}.png`, `<tag>-3d.png`), где tag = v<вариант>-<ширина>-<свет>.
Маска предмета — пиксели его цвета в кадре-маске, с эрозией 1 px (края со сглаживанием не берём). Фото товара — без фона:
фон = близкое к цвету углов (ΔE < 10) или почти белое. Среднее Lab — по пикселям маски (перцептивно), ΔL = кадр − фото.
Выход: `color.md` (таблица по предметам и сводка по вариантам), `color.json`, склейки `cmp-<вариант>-<ширина>.jpg`.
  python color.py <папка> [--ref спальня.png] [--ref2 гостиная.jpg] [--base https://remont-lab.online/demo/]
"""
import json
import os
import sys
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def lab(rgb):
    c = np.asarray(rgb, np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def mean_lab(img, mask):
    px = img[mask]
    if len(px) < 30:
        return None
    L = lab(px)
    return {'L': round(float(L[:, 0].mean()), 1), 'a': round(float(L[:, 1].mean()), 1), 'b': round(float(L[:, 2].mean()), 1),
            'n': int(len(px)), 'clip': round(float((px.max(1) >= 250).mean()), 3)}


def photo_lab(path):
    im = np.asarray(Image.open(path).convert('RGB'))
    h, w, _ = im.shape
    k = max(4, min(h, w) // 25)
    corners = np.concatenate([im[:k, :k].reshape(-1, 3), im[:k, -k:].reshape(-1, 3), im[-k:, :k].reshape(-1, 3), im[-k:, -k:].reshape(-1, 3)])
    bg = lab(np.median(corners, 0))
    L = lab(im.reshape(-1, 3)).reshape(h, w, 3)
    d = np.sqrt(((L - bg) ** 2).sum(-1))
    fg = (d >= 10) & ~((L[..., 0] > 96) & (np.hypot(L[..., 1], L[..., 2]) < 4))
    share = float(fg.mean())
    r = mean_lab(im, fg)
    if r:
        r['fg'] = round(share, 2)
        r['unsure'] = share < 0.05 or share > 0.95
    return r


def erode(m):
    e = m.copy()
    e[1:, :] &= m[:-1, :]; e[:-1, :] &= m[1:, :]; e[:, 1:] &= m[:, :-1]; e[:, :-1] &= m[:, 1:]
    return e


def main():
    d = sys.argv[1]
    args = sys.argv[2:]
    opt = {args[i]: args[i + 1] for i in range(0, len(args) - 1, 2)}
    base = opt.get('--base', 'https://remont-lab.online/demo/')
    tags = sorted(f[:-5] for f in os.listdir(d) if f.endswith('.json') and f.startswith('v') and f.count('-') == 2)
    os.makedirs(os.path.join(d, 'photos'), exist_ok=True)
    photos, per_cam, frame = {}, {}, {}
    for tag in tags:
        J = json.load(open(os.path.join(d, tag + '.json')))
        key = (J['vi'], J['W'])
        bym = {it['msid']: it for it in J['items'] if it.get('msid')}
        fr = []
        for M in J.get('meas') or []:
            ct = f"{tag}-c{M['cam']}"
            bpath = os.path.join(d, ct + '-m-beauty.png')
            if not os.path.exists(bpath):
                continue
            beauty = np.asarray(Image.open(bpath).convert('RGB'))
            ids = np.asarray(Image.open(os.path.join(d, ct + '-m-ids.png')).convert('RGB')).astype(int)
            albedo = np.asarray(Image.open(os.path.join(d, ct + '-m-albedo.png')).convert('RGB'))
            Lf = lab(beauty.reshape(-1, 3))[:, 0]
            fr.append((float(Lf.mean()), float(np.percentile(Lf, 95)), float((beauty.reshape(-1, 3).min(1) >= 250).mean())))
            for lg in M['legend']:
                mask = erode((np.abs(ids - np.array(lg['id'])).max(-1) <= 6))
                it = bym.get(lg.get('meshId')) or {}
                name = it.get('role') or lg.get('title') or lg['slot']
                row = per_cam.setdefault((key, lg['slot'], M['cam']), {'room': key[0], 'W': key[1], 'slot': lg['slot'], 'role': name,
                                         'kind': lg.get('kind'), 'msid': lg.get('meshId'), 'img': it.get('img'), 'lights': {}, 'cam': M['cam']})
                row['lights'][J['light']] = mean_lab(beauty, mask)
                if J['light'] == 'v0':
                    row['albedo'] = mean_lab(albedo, mask)
        if fr:
            frame[(key, J['light'])] = {'L_mean': round(float(np.mean([x[0] for x in fr])), 1), 'L_p95': round(float(np.mean([x[1] for x in fr])), 1),
                                        'clip': round(float(np.mean([x[2] for x in fr])), 4)}
    # предмет — из того вида, где его видно больше всего (по кадру «было»): одна точка для всех вариантов света
    rows = {}
    for (key, slot, cam), r in per_cam.items():
        n = ((r['lights'].get('v0') or {}).get('n')) or 0
        cur = rows.get((key, slot))
        if not cur or n > (((cur['lights'].get('v0') or {}).get('n')) or 0):
            rows[(key, slot)] = r
    for row in rows.values():
        img = row.get('img')
        if not img:
            continue
        if img not in photos:
            local = os.path.join(d, 'photos', os.path.basename(img))
            if not os.path.exists(local):
                try:
                    urllib.request.urlretrieve(base + img, local)
                except Exception as e:  # noqa: BLE001 — фото не скачалось: строка без фото, причина в отчёте
                    print('фото не скачалось', img, e, file=sys.stderr)
                    photos[img] = None
                    continue
            photos[img] = photo_lab(local)
        row['photo'] = photos[img]

    def dl(x, y):
        if not x or not y:
            return None
        return {'dL': round(x['L'] - y['L'], 1), 'dab': round(float(np.hypot(x['a'] - y['a'], x['b'] - y['b'])), 1)}

    lights = sorted({lt for r in rows.values() for lt in r['lights']})
    out = ['# Цвет предметов: фото товара / альбедо модели / кадр 3D при каждом свете', '',
           'ΔL = кадр − фото (L* 0…100), Δab — расхождение оттенка. Альбедо — модель без света (её собственная краска).', '']
    summary = {}
    for key in sorted({(r['room'], r['W']) for r in rows.values()}):
        R = [r for r in rows.values() if (r['room'], r['W']) == key]
        out += [f'## Вариант демо {key[0]}, ширина {key[1]}', '',
                '| предмет | фото L | альбедо L (ΔL) | ' + ' | '.join(f'{lt} L (ΔL / Δab)' for lt in lights) + ' |',
                '|---|---|---|' + '---|' * len(lights)]
        for r in sorted(R, key=lambda r: r['role'] or ''):
            ph = r.get('photo')
            al = r.get('albedo')
            cells = [f"{r['role']}" + (' (фото без фона?)' if ph and ph.get('unsure') else ''),
                     f"{ph['L']}" if ph else '—',
                     f"{al['L']} ({dl(al, ph)['dL']:+})" if al and ph else (f"{al['L']}" if al else '—')]
            for lt in lights:
                x = r['lights'].get(lt)
                dd = dl(x, ph)
                cells.append(f"{x['L']} ({dd['dL']:+} / {dd['dab']})" if dd else (f"{x['L']}" if x else '—'))
            out.append('| ' + ' | '.join(cells) + ' |')
        out += ['', '| свет | медиана ΔL | медиана \\|ΔL\\| | макс \\|ΔL\\| | медиана Δab | предметов | разброс ΔL после сдвига на медиану (σ) | кадр: средняя L* / p95 / выбито |', '|---|---|---|---|---|---|---|---|']
        for lt in ['albedo'] + lights:
            ds = [dl(r.get('albedo') if lt == 'albedo' else r['lights'].get(lt), r.get('photo')) for r in R if r.get('photo') and not r['photo'].get('unsure')]
            ds = [x for x in ds if x]
            if not ds:
                continue
            L = np.array([x['dL'] for x in ds])
            ab = np.array([x['dab'] for x in ds])
            fr = frame.get((key, lt), {})
            s = {'median_dL': round(float(np.median(L)), 1), 'median_abs_dL': round(float(np.median(np.abs(L))), 1), 'max_abs_dL': round(float(np.abs(L).max()), 1),
                 'median_dab': round(float(np.median(ab)), 1), 'n': len(ds), 'sigma_after_shift': round(float(np.std(L - np.median(L))), 1), 'frame': fr}
            summary[f'{key[0]}-{key[1]}-{lt}'] = s
            out.append(f"| {lt} | {s['median_dL']:+} | {s['median_abs_dL']} | {s['max_abs_dL']} | {s['median_dab']} | {s['n']} | {s['sigma_after_shift']} | "
                       + (f"{fr.get('L_mean')} / {fr.get('L_p95')} / {fr.get('clip', 0) * 100:.2f} %" if fr else '—') + ' |')
        out.append('')
    open(os.path.join(d, 'color.md'), 'w').write('\n'.join(out))
    json.dump({'rows': [dict(r, key=None) for r in rows.values()], 'summary': summary}, open(os.path.join(d, 'color.json'), 'w'), ensure_ascii=False, indent=1, default=str)
    montage(d, tags, opt)
    print('\n'.join(out))


def font(sz):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def montage(d, tags, opt):
    """Склейка на вариант света: «было» | вариант | эталон, одной высоты, с подписями."""
    refs = {'v6': opt.get('--ref'), 'v11': opt.get('--ref'), 'v0': opt.get('--ref2'), 'v1': opt.get('--ref2')}
    F = font(26)
    G = 12

    def label(im, text, hh):
        im = im.resize((max(1, round(im.width * hh / im.height)), hh), Image.LANCZOS)
        dr = ImageDraw.Draw(im)
        dr.rectangle([0, 0, 12 + dr.textlength(text, font=F) + 12, 44], fill=(255, 255, 255))
        dr.text((12, 8), text, fill=(20, 20, 20), font=F)
        return im

    def hstack(ims):
        out = Image.new('RGB', (sum(i.width for i in ims) + G * (len(ims) - 1), max(i.height for i in ims)), (255, 255, 255))
        x = 0
        for i in ims:
            out.paste(i, (x, 0))
            x += i.width + G
        return out

    def vstack(ims):
        out = Image.new('RGB', (max(i.width for i in ims), sum(i.height for i in ims) + G * (len(ims) - 1)), (255, 255, 255))
        y = 0
        for i in ims:
            out.paste(i, (0, y))
            y += i.height + G
        return out

    names = {'v1': 'v1 свет', 'v2': 'v2 свет + пятна-тени', 'v3': 'v3 свет + запечённые тени + шторы', 'v4': 'v4 v3 + окно-источник + GTAO'}
    for t in tags:
        vi, w, lt = t.split('-')
        if lt == 'v0':
            continue
        hh = 520 if int(w) > 700 else 640
        rows = []
        for cam in (0, 1):
            a, b = os.path.join(d, f'{vi}-{w}-v0-c{cam}-3d.png'), os.path.join(d, f'{t}-c{cam}-3d.png')
            if os.path.exists(a) and os.path.exists(b):
                rows.append(hstack([label(Image.open(a).convert('RGB'), 'было', hh), label(Image.open(b).convert('RGB'), names.get(lt, lt), hh)]))
        if not rows:
            continue
        body = vstack(rows)
        ref = refs.get(vi) or opt.get('--ref')
        if ref and os.path.exists(ref):
            r = Image.open(ref).convert('RGB')
            r = label(r, 'эталон владельца', max(1, round(r.height * body.width / r.width)))
            body = vstack([body, r])
        body.save(os.path.join(d, f'cmp-{vi}-{w}-{lt}.jpg'), quality=85)


if __name__ == '__main__':
    main()
