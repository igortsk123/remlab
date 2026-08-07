#!/usr/bin/env python3
"""Страница «10 расстановок на проверку владельцу» — вход РОВНО как в LLM (А5-калибровка).

Для каждого сета: свежая расстановка (beam со всеми фиксами 06–07.08) → сцена → схема-кубики
с номерами (2 вида) + карта глубины с выносками + план + лист эталонов товаров. Это те самые
картинки, что уходят в генератор; владелец судит РАССТАНОВКУ до всяких трат на рендеры.

  ~/venvs/scout/bin/python layout10_page.py 1 14 21 ...   # собрать и выложить
Выход: ~/scout-scenes/layout10/ (index.html + картинки) — scp в /opt/remlab/test/layout10/.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCENE_DIR = os.path.expanduser(os.environ.get('SCENE_DIR', '~/scout-scenes'))
OUT = os.path.join(SCENE_DIR, 'layout10')
PY = sys.executable


def run(n: int) -> dict:
    info = {'set': n, 'fails': [], 'soft': {}, 'missing': []}
    env = dict(os.environ, LAYOUT_SUFFIX='')
    r = subprocess.run([PY, os.path.join(HERE, 'solver_run.py'), str(n), '--v3'],
                       capture_output=True, text=True, timeout=600, env=env, cwd=HERE)
    out = r.stdout
    info['fails'] = [l.strip() for l in out.splitlines() if l.startswith('FAIL')]
    import re
    m = re.search(r'^SOFT (\{.*\})$', out, re.M)
    if m:
        info['soft'] = json.loads(m.group(1))
    m = re.search(r'НЕ размещены: (\[.*\])', out)
    if m:
        info['missing'] = eval(m.group(1))  # noqa: S307 — свой вывод
    for cmd in (['scene_build.py', str(n)], ['schema3d.py', str(n), '--cams', 'C1,C2']):
        subprocess.run([PY, os.path.join(HERE, cmd[0])] + cmd[1:],
                       capture_output=True, text=True, timeout=600, cwd=HERE)
    # лист эталонов — тем же кодом, что реальный вызов генератора
    from viz_final import identity_sheet
    from viz_marks import numbering
    sheet = identity_sheet(n, [], numbering(n))
    if sheet is not None:
        sheet.save(os.path.join(SCENE_DIR, f'scene{n}-identity10.jpg'), quality=90)
    return info


def _reparse(n: int) -> dict:
    """Инфо из уже посчитанной раскладки: солвер заново не гоняем (--collect)."""
    info = {'set': n, 'fails': [], 'soft': {}, 'missing': []}
    env = dict(os.environ, LAYOUT_SUFFIX='-info')
    r = subprocess.run([PY, os.path.join(HERE, 'solver_run.py'), str(n), '--v3'],
                       capture_output=True, text=True, timeout=600, env=env, cwd=HERE)
    import re
    info['fails'] = [l.strip() for l in r.stdout.splitlines() if l.startswith('FAIL')]
    m = re.search(r'^SOFT (\{.*\})$', r.stdout, re.M)
    if m:
        info['soft'] = json.loads(m.group(1))
    m = re.search(r'НЕ размещены: (\[.*\])', r.stdout)
    if m:
        info['missing'] = eval(m.group(1))  # noqa: S307
    return info


def collect(n: int) -> dict[str, str]:
    """Копируем артефакты сета в layout10/ (маленькие имена для html)."""
    files = {}
    for key, src in (('plan', f'scene{n}-plan.png'),
                     ('c1', f'scene{n}-C1-schema3d-marked.jpg'),
                     ('c2', f'scene{n}-C2-schema3d-marked.jpg'),
                     ('d1', f'scene{n}-C1-schema-depth-marked.jpg'),
                     ('ident', f'scene{n}-identity10.jpg')):
        p = os.path.join(SCENE_DIR, src)
        if os.path.exists(p):
            dst = f'set{n}-{key}{os.path.splitext(src)[1]}'
            shutil.copyfile(p, os.path.join(OUT, dst))
            files[key] = dst
    return files


def main() -> None:
    sets = [int(a) for a in sys.argv[1:] if a.isdigit()]
    if not sets:
        from testmode import REFERENCE_TEN
        sets = list(REFERENCE_TEN)
    os.makedirs(OUT, exist_ok=True)
    meta = json.load(open(os.path.join(HERE, 'sets3.json')))
    blocks = []
    reuse = '--collect' in sys.argv   # артефакты уже посчитаны — только пересобрать страницу
    for n in sets:
        print(f'== сет {n}', flush=True)
        info = run(n) if not reuse else _reparse(n)
        files = collect(n)
        s = meta[n - 1]
        soft_terms = info['soft'].get('terms', {})
        soft_sum = round(sum(soft_terms.values()), 1)
        worst = ', '.join(f'{k}={v}' for k, v in
                          sorted(soft_terms.items(), key=lambda kv: -kv[1])[:3])
        status = ('❌ ' + '; '.join(info['fails'] + [f"не встало: {info['missing']}"])
                  if (info['fails'] or info['missing'])
                  else f'✅ чисто; сомнение-балл {soft_sum} ({worst or "—"})')
        img = lambda k, t: (f'<figure><a href="{files[k]}" target="_blank">'
                            f'<img src="{files[k]}" loading="lazy"></a>'
                            f'<figcaption>{t}</figcaption></figure>') if k in files else ''
        blocks.append(f"""
<section>
 <h2>Сет {n} — {s['band']} м², {s['tier']}, {s.get('style', '')}</h2>
 <p class="st">{status}</p>
 <div class="row">
  {img('plan', 'план с камерами')}{img('c1', 'вид C1 — схема с номерами')}
  {img('c2', 'вид C2 — схема с номерами')}{img('d1', 'C1 — карта глубины с выносками')}
 </div>
 <div class="row">{img('ident', 'лист эталонов (уходит в модель вместе со схемами)')}</div>
</section>""")
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>10 расстановок — проверка владельцем (вход как в LLM)</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#fafafa;color:#222}}
h1{{font-size:22px}} h2{{font-size:18px;margin:28px 0 4px}}
.st{{margin:2px 0 10px;color:#444}}
.row{{display:flex;gap:10px;flex-wrap:wrap}}
figure{{margin:0}} figcaption{{font-size:12px;color:#666;margin-top:2px}}
img{{max-height:300px;width:auto;border:1px solid #ddd;border-radius:6px;background:#fff}}
section{{border-top:1px solid #ddd;padding-top:10px}}
.note{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:10px 14px;max-width:900px}}
</style></head><body>
<h1>10 расстановок — вход ровно как уходит в LLM (2026-08-07)</h1>
<div class="note">Схема-кубики с номерами (2 вида) + карта глубины + план + лист эталонов —
это и есть вход генератора. Судим РАССТАНОВКУ: логична ли схема, до трат на рендер.
Свежие правки: движок beam с пуф-порогами, Г-диван в угол (в больших комнатах — компромисс
«ТВ важнее угла»), ковёр под ножками дивана, дверь/окно свои в каждом сете.
«Сомнение-балл» — сумма мягких штрафов солвера (наша метрика «глупости», порог 12).</div>
{''.join(blocks)}
</body></html>"""
    open(os.path.join(OUT, 'index.html'), 'w').write(html)
    print(f'страница: {OUT}/index.html ({len(sets)} сетов)')
    if '--publish' in sys.argv or os.environ.get('LAYOUT10_PUBLISH') == '1':
        # публикация — часть конвейера, не ручной шаг (владелец 2026-08-07). rsync, не scp -r:
        # повторный scp клал каталог ВНУТРЬ существующего (test/layout10/layout10 → 404)
        r = subprocess.run(['rsync', '-a', '--delete', '-e', 'ssh -o ConnectTimeout=15',
                            OUT + '/', 'root@89.167.127.0:/opt/remlab/test/layout10/'],
                           capture_output=True, text=True, timeout=600)
        print('опубликовано: https://remont-lab.online/test/layout10/' if r.returncode == 0
              else f'ПУБЛИКАЦИЯ НЕ ПРОШЛА: {r.stderr[:200]}')
        if r.returncode != 0:
            sys.exit(1)


if __name__ == '__main__':
    main()
