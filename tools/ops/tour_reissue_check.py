#!/usr/bin/env python3
"""ПРОВЕРКА «ДЕМО И ТУРЫ ОДИНАКОВЫ» после прохода автоперевыпуска (T-20261112-92; план `plans/tour-auto-reissue-01.md` п.3).
Зовёт `tools/ops/tour-reissue.sh`; 0 ₽, ключи покупателя не нужны.

  страница — у каждого опубликованного тура `release` (ответ сервера, `reissue.py` → report.json) == ожидаемое имя витрины
             (`tools/ops/demo-release-hash.mjs` по файлам, которые прод отдаёт сейчас): те же байты страницы и движка, что /demo,
             значит те же высоты подвеса, двери плана, ленты «Заменить» и все константы страницы — они в этих файлах;
  данные   — выборочно 3 тура (первый и последний в списке прохода, один со спальней) по их новой сборке `<run>/<id>/bundle-new.json`
             против `demo-data.json` /demo: метка правил сборщика (`build`, `tools/scout/build_stamp.py`), правила страницы `rules`
             (кроме полос размера `slot_band_cm` — они считаются по каталогу самой квартиры), план с дверями, непустые ленты
             «Заменить» там, где непусты у /demo.
Расхождение — строка `WARN:tour_reissue: …` (обёртка поднимает тревогу/DIGEST); вывод без WARN — сверено.

  tour_reissue_check.py --run <папка прохода> --expect <имя витрины|-> --demo-data <путь|адрес demo-data.json>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scout'))
import build_stamp as BS  # noqa: E402

DATA_RULES = ('slot_band_cm',)          # правила, посчитанные по каталогу квартиры, — у тура свои по смыслу


def load_json(src: str) -> dict:
    if src.startswith(('http://', 'https://')):
        req = urllib.request.Request(src, headers={'Accept-Encoding': 'identity', 'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8'))
    return json.loads(Path(src).read_text(encoding='utf-8'))


def summary(rows: list[dict]) -> tuple[str, list[str]]:
    """→ (строка-итог прохода, WARN-строки отказов и сбоев с id туров — не молча)."""
    st = lambda s: [r for r in rows if r.get('status') == s]  # noqa: E731
    pub, same = st('published'), [r for r in rows if r.get('unchanged')]
    page = [r for r in pub if r.get('repeated') and not r.get('unchanged')]
    skip = st('skipped')
    why: dict[str, int] = {}
    for r in skip:
        why[str(r.get('why'))] = why.get(str(r.get('why')), 0) + 1
    parts = [f'туров {len(rows)}', f'перевыпущено {len(pub) - len(same)}' + (f' (из них «только страница» {len(page)})' if page else '')]
    if same:
        parts.append(f'без изменений {len(same)}')
    if st('built'):
        parts.append(f'собрано без публикации {len(st("built"))}')
    if skip:
        parts.append(f'пропущено {len(skip)} (' + ', '.join(f'{k} {v}' for k, v in sorted(why.items())) + ')')
    parts.append(f'отказ {len(st("refused"))}')
    if st('failed'):
        parts.append(f'сбой {len(st("failed"))}')
    warns = [f"WARN:tour_reissue: тур {r['id']} — отказ сборщика {r.get('why')}, тур остался прежним" for r in st('refused')]
    warns += [f"WARN:tour_reissue: тур {r['id']} — сбой {str(r.get('why'))[:80]}, тур остался прежним" for r in st('failed')]
    return 'tour_reissue: ' + ' · '.join(parts), warns


def check_release(rows: list[dict], expect: str) -> list[str]:
    """→ WARN-строки: опубликованные туры не на витрине /demo."""
    if not expect or expect == '-':
        return []
    bad = [r for r in rows if r.get('status') == 'published' and r.get('release') != expect]
    return [f"WARN:tour_reissue: тур {r['id']} на витрине {str(r.get('release'))[:12]}, /demo — {expect[:12]}" for r in bad]


def sample(rows: list[dict], run: Path) -> list[str]:
    """3 тура для сверки данных: первый, последний, один со спальней — из собранных в этом проходе (есть bundle-new.json)."""
    ids = [r['id'] for r in rows if r.get('status') in ('published', 'built') and (run / r['id'] / 'bundle-new.json').is_file()]
    if len(ids) <= 3:
        return ids
    pick = [ids[0], ids[-1]]
    for i in ids[1:-1]:
        d = json.loads((run / i / 'bundle-new.json').read_text(encoding='utf-8'))
        if any(str(k).startswith('bedroom') for k in d.get('rooms_enabled') or d.get('rooms_geo') or {}):
            pick.append(i)
            break
    else:
        pick.append(ids[len(ids) // 2])
    return pick


def check_data(jid: str, tour: dict, demo: dict) -> list[str]:
    """→ расхождения тура с /demo по признакам сборщика (пусто — сверено)."""
    out = []
    tr, dr = BS.rules_of(tour.get('build')), BS.rules_of(demo.get('build'))
    if dr and not tr:                      # у /demo метки нет (выложено до T-92) — сверять не с чем
        out.append('нет метки сборки у тура')
    elif dr and tr != dr:
        out.append(f'правила сборщика {tr} ≠ /demo {dr}')
    strip = lambda r: {k: v for k, v in (r or {}).items() if k not in DATA_RULES}  # noqa: E731
    diff = sorted(k for k in set(strip(tour.get('rules'))) | set(strip(demo.get('rules')))
                  if strip(tour.get('rules')).get(k) != strip(demo.get('rules')).get(k))
    if diff:
        out.append('правила страницы отличаются: ' + ', '.join(diff[:6]))
    panels = (tour.get('trial') or {}).get('panels') or []
    if not panels or not any(p.get('rooms') for p in panels):
        out.append('нет плана комнат')
    elif not any(o.get('kind') == 'door' for p in panels for o in p.get('openings') or []):
        out.append('на плане нет дверей')
    feeds, dfeeds = tour.get('feeds') or {}, demo.get('feeds') or {}
    empty = sorted(k for k, v in feeds.items() if not v and dfeeds.get(k.split(':')[-1]))
    if empty:
        out.append('пустые ленты «Заменить»: ' + ', '.join(empty[:6]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Проверка «демо и туры одинаковы» после автоперевыпуска')
    ap.add_argument('--run', required=True, help='папка прохода reissue.py (report.json, <id>/bundle-new.json)')
    ap.add_argument('--expect', required=True, help='имя витрины /demo (demo-release-hash.mjs); «-» — не сверять')
    ap.add_argument('--demo-data', required=True, help='demo-data.json /demo: путь или адрес')
    a = ap.parse_args(argv)
    run = Path(a.run)
    try:
        rows = json.loads((run / 'report.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        print(f'WARN:tour_reissue: нет отчёта прохода {run}/report.json — {type(e).__name__}')
        return 0
    line, warns = summary(rows)
    print(line)
    warns += check_release(rows, a.expect)
    pub = sum(1 for r in rows if r.get('status') == 'published')
    off = sum(1 for w in warns if ' на витрине ' in w)
    print(f'демо = туры, страница: на витрине /demo {pub - off} из {pub} опубликованных' if a.expect != '-' else
          'демо = туры, страница: не сверялась (имя витрины /demo не получено)')
    try:
        demo = load_json(a.demo_data)
    except (OSError, ValueError) as e:
        warns.append(f'WARN:tour_reissue: данные /demo не прочитаны ({type(e).__name__}) — сверка данных не сделана')
        demo = None
    if demo is not None:
        if not BS.rules_of(demo.get('build')):
            print('у /demo метки сборки ещё нет (выложено до T-92) — правила сборщика не сверяю, остальное сверяю')
        for jid in sample(rows, run):
            tour = json.loads((run / jid / 'bundle-new.json').read_text(encoding='utf-8'))
            bad = check_data(jid, tour, demo)
            print(f"демо = туры, данные {jid}: " + ('сверено' if not bad else '; '.join(bad)))
            if bad:
                warns.append(f"WARN:tour_reissue: тур {jid} собран не как /demo — {'; '.join(bad)}")
    for w in warns:
        print(w)
    return 0


if __name__ == '__main__':
    os.umask(0o022)
    sys.exit(main())
