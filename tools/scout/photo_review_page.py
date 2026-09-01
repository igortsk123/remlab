#!/usr/bin/env python3
"""Страница просмотра помеченных фото: по N самых «небелых» в каждой роли.

ЗАЧЕМ (владелец 01.09): «покажи топ 20 каждой категории, фото посмотрю». Метка
`photo_collage` означает «фон не белый → на проверку», а не вердикт: решает человек, и для
этого ему нужны сами фото, сгруппированные по ролям, а не число в таблице.

Сортировка внутри роли — по доле белого ПО ВОЗРАСТАНИЮ: первыми идут самые крайние случаи
(0% белого — сцена или баннер во весь кадр), последними пограничные.

  ~/venvs/scout/bin/python photo_review_page.py                 # роли по умолчанию
  ~/venvs/scout/bin/python photo_review_page.py --roles плед,ваза --top 30
"""
import html
import os
import subprocess
import sys

OUT = os.path.expanduser('~/scout-scenes/photo-review')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
ROLES = ['плед', 'люстра', 'кашпо', 'стул', 'подушка', 'бра', 'ваза']


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:300])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def q(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def main() -> None:
    roles = (sys.argv[sys.argv.index('--roles') + 1].split(',')
             if '--roles' in sys.argv else ROLES)
    top = int(sys.argv[sys.argv.index('--top') + 1]) if '--top' in sys.argv else 20
    os.makedirs(OUT, exist_ok=True)

    parts = ['<!doctype html><meta charset="utf-8"><title>Фото на проверку</title>',
             '<style>body{font:14px/1.5 system-ui;margin:20px;background:#faf9f7;color:#1a1a1a}'
             'h1{font-size:20px}h2{font-size:17px;margin:26px 0 10px;padding-top:12px;'
             'border-top:1px solid #e5e2dc}.grid{display:grid;gap:12px;'
             'grid-template-columns:repeat(auto-fill,minmax(190px,1fr))}'
             '.c{background:#fff;border:1px solid #e5e2dc;border-radius:8px;padding:8px}'
             '.c img{width:100%;height:170px;object-fit:contain;background:#fff;border-radius:4px}'
             '.n{font-size:12px;line-height:1.35;margin-top:6px;max-height:50px;overflow:hidden}'
             '.s{font-size:11px;color:#888;margin-top:4px}.dim{color:#666;font-size:13px}'
             'a{color:#1a56b8;text-decoration:none}</style>',
             '<h1>Фото, помеченные «на проверку» — по ролям</h1>']

    totals = dict(db("select coalesce(cat_role,'—'), count(*)::text from products "
                     "where photo_collage group by 1;"))
    parts.append('<p class="dim">Метка означает ОДНО: фон не белый. Это не вердикт «коллаж» — '
                 'плед на диване и рекламный баннер получают её одинаково. '
                 f'Внутри роли — самые крайние случаи сверху (доля белого по краю кадра).</p>')

    for role in roles:
        rows = db("select coalesce(name,''), coalesce(image_url_hd, image_url), "
                  "round(coalesce(photo_bg_score,0)::numeric,2)::text, "
                  "coalesce(url,''), coalesce(mesh_status,'none') "
                  f"from products where photo_collage and cat_role={q(role)} "
                  f"order by photo_bg_score asc nulls last limit {top};")
        if not rows:
            continue
        parts.append(f'<h2>{html.escape(role)} — показано {len(rows)} '
                     f'из {totals.get(role, "?")} помеченных</h2><div class="grid">')
        for name, img, score, link, mesh in rows:
            cap = html.escape(name[:70])
            mark = ' · меш есть' if mesh == 'ready' else ''
            a_open = f'<a href="{html.escape(link)}" target="_blank">' if link else ''
            a_close = '</a>' if link else ''
            parts.append(f'<div class="c">{a_open}<img src="{html.escape(img)}" loading="lazy">'
                         f'{a_close}<div class="n">{cap}</div>'
                         f'<div class="s">белого {score}{mark}</div></div>')
        parts.append('</div>')

    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write('\n'.join(parts))
    print(f'страница: {OUT}/index.html ({len(roles)} ролей, по {top})')


if __name__ == '__main__':
    main()
