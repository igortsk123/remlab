#!/usr/bin/env python3
"""T-180/4 · сводка и страницы прогона покраски — числа и кадры автоматом, не руками (владелец TG 1251, 1258; поправки директора по приёмке отчёта 1).

ЗАЧЕМ: одно и то же число («сколько остановилось, сколько покрашено, сколько показано») считали по памяти и ошиблись; теперь его считает код
из тех же решений этапов, что воронка (`paint_funnel.analyse`), и сам проверяет, что сумма сходится. Страницы — для владельца: названия товаров и этапов
словами, причины одной строкой («код причины → фраза» в `tools/scout/rules/paint-reasons.json`), числа — в свёрнутом «подробно».

ЧТО ДЕЛАЕТ (только чтение готового прогона; платного и нейросети нет):
  ① сводка — вошло N · не дошли до готовой модели (по этапам, с причиной каждого товара) · покрашено (есть итоговая модель `08-material/material.glb`;
     из них итог этапа 9) · карточек на странице. `summary.md` + `summary.json`.
     Самопроверка (`verify`): N совпало с числом папок товаров на диске; не дошли + покрашено = N; сумма по этапам = не дошедшим; у каждого не дошедшего есть причина;
     кадров «фото | наш 3D» = покрашено; карточек = N. Не сошлось — ненулевой код возврата и строка «ОШИБКА СВОДКИ».
  ② страница прогона `index.html` — сверху сводка и ссылки на этапы; карточки ВСЕХ товаров: покрашенные «фото | наш 3D» (как `tex_visible`: итоговая текстура
     этапа 8 по растру камеры этапа 4, без света), не дошедшие «фото | последний кадр, который есть» с подписью «встал на: …». Без скриптов и кода доступа,
     телефон 375 и ПК, картинки JPEG ≤1600 px (PNG 1536² Телеграм не берёт).
  ②б страницы этапов `<этап>/index.html` — по КАЖДОМУ этапу все товары набора: «фото | результат этапа» (`<товар>/<этап>/frame.png`), подпись «этап NN · название ·
     готовность этапа N %», вошло/прошло/встало, ссылки на соседние этапы. Готовность и названия этапов — `tools/scout/rules/paint-readiness.json` (нет файла или ключа — «не задана»).
  Публикация — только `--publish` (rsync на `/opt/remlab/test/paint-<прогон>/`); по умолчанию всё лежит локально в `--out`.

«Покрашено» = у товара есть итоговая модель этапа 8 (решение директора 22.11): именно её можно показать. Остальные — «не дошли»: этап — первый отказ (при отказе и «нет check.json»
берётся отказ), причина — слова самого конвейера (`paint_check`). ID товаров в код не попадают.

  ②в страница этапа «вырезка» — `paint_run_report.py cutout --set <набор.json> --run <папка прогона вырезки> [--publish]`: «исходное фото | вырезка» по всем товарам набора + сводка.

Запуск (обычно — само, в конце `paint_funnel.py`; отдельно так):
  python3 paint_run_report.py <прогон> [<прогон> …] [--out <папка>] [--name <имя>] [--publish]     # несколько прогонов — один набор (повтор sku берётся из первого)
Код возврата 0 — всё сошлось; 1 — самопроверка нашла расхождение или кадр не построился."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paint_funnel as pf  # noqa: E402

MODEL = os.path.join('08-material', 'material.glb')
MAX_SIDE = 1600
JPEG_Q = 88
REMOTE = 'root@89.167.127.0'
REMOTE_ROOT = '/opt/remlab/test'
URL_ROOT = 'https://remont-lab.online/test'
MATERIAL = '08-material'
READINESS = os.path.join('tools', 'scout', 'rules', 'paint-readiness.json')
REASONS = os.path.join('tools', 'scout', 'rules', 'paint-reasons.json')
VERDICT = {'ok': 'прошёл проверку', 'soft': 'прошёл с замечаниями', 'refused': 'не прошёл', 'missing': 'проверка не запускалась'}
STAGE_VERDICT = {'ok': 'прошёл', 'soft': 'прошёл с замечаниями', 'refused': 'встал', 'missing': 'не дошёл'}


def slug(name: str) -> str:
    s = re.sub(r'[^A-Za-z0-9]+', '-', name).strip('-')                # регистр сохраняем: /test/paint-e2eHD-1121-union/ (директор 22.11)
    s = re.sub(r'^(paint(-|$))+', '', s, flags=re.I)                      # имя уже с префиксом (--name paint-forms-set40) — второй раз его не добавляем: был /test/paint-paint-forms-set40/ (22.11)
    return 'paint-' + (s or 'run')


# ---------- метка свежести данных (директор 22.11): папка прогона ещё меняется, а страница её читает ----------
FRESH_MIN = 10                                                            # папка менялась позже, чем N минут назад — прогон ещё идёт


def _pid_alive(pid) -> bool:
    try:
        return os.path.exists(f'/proc/{int(pid)}')
    except (TypeError, ValueError):
        return False


def heavy_jobs(runs: list, state_dir: str | None = None) -> list:
    """Живые задания heavy-slot (держатели `holder*` и очередь `wait/*`) с меткой `paint-…`, чья команда `cmd=` называет папку одного из прогонов. Файл состояния без живого процесса не считается. Возвращает метки заданий."""
    d = os.path.expanduser(state_dir or os.environ.get('HEAVY_SLOT_DIR') or '~/.cache/remlab-heavy-slot')
    files = []
    try:
        files += [os.path.join(d, f) for f in os.listdir(d) if f.startswith('holder')]
        files += [os.path.join(d, 'wait', f) for f in os.listdir(os.path.join(d, 'wait'))]
    except OSError:
        return []
    pats = [re.compile(re.escape(os.path.abspath(os.path.expanduser(r)).rstrip('/')) + r'(?=[/\s"\']|$)') for r in runs]
    out = []
    for f in files:
        try:
            kv = dict(ln.rstrip('\n').split('=', 1) for ln in open(f, encoding='utf-8') if '=' in ln)
        except OSError:
            continue
        if _pid_alive(kv.get('pid')) and (kv.get('label') or '').startswith('paint-') and any(p.search(kv.get('cmd', '')) for p in pats):   # только задания самого прогона (`paint-…`); чужая задача, читающая файлы из папки, прогоном не считается
            out.append(kv.get('label') or os.path.basename(f))
    return sorted(set(out))


def last_change(runs: list) -> float:
    """Самое позднее время изменения (mtime) любого файла/папки внутри прогона до глубины `<товар>/<этап>/файл` (по sku-папкам — как читает страница)."""
    best = 0.0
    for r in runs:
        r = os.path.expanduser(r)
        stack = [(r, 0)]
        while stack:
            p, lvl = stack.pop()
            try:
                best = max(best, os.stat(p).st_mtime)
                if lvl < 3 and os.path.isdir(p):
                    stack += [(os.path.join(p, n), lvl + 1) for n in os.listdir(p) if not (lvl >= 1 and n in ('work', 'stages'))]
            except OSError:
                pass
    return best


PROGRESS_STALE_MIN = 180                                                  # журнал пакета молчит дольше, и заданий нет — пакет считаем остановленным


def progress_state(run: str, now: float) -> dict | None:
    """Журнал пакета `<прогон>/progress.log` (T-176/2): строки `ГГГГ-ММ-ДД ЧЧ:ММ:СС старт|конец <товар> …` и `… ВСЁ, …`. Пакет не закончил, если ПОСЛЕДНЕЕ из событий (старт/конец/ВСЁ) — не «ВСЁ» (старые «ВСЁ» выше по журналу не в счёт). Нет журнала — None."""
    from datetime import datetime
    p = os.path.join(os.path.expanduser(run), 'progress.log')
    try:
        lines = [x.rstrip('\n') for x in open(p, encoding='utf-8') if x.strip()]
    except OSError:
        return None
    ev = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (старт|конец|ВСЁ)\b\s*(\S*)')
    last = next((m for m in (ev.match(x) for x in reversed(lines)) if m), None)
    if not last:
        return None
    ts_last = None
    for x in reversed(lines):
        try:
            ts_last = datetime.strptime(x[:19], '%Y-%m-%d %H:%M:%S').timestamp()           # время журнала — местное машины, где писали
            break
        except ValueError:
            continue
    ago = max(0, round((now - ts_last) / 60)) if ts_last else None
    return {'run': os.path.basename(os.path.expanduser(run).rstrip('/')), 'event': last.group(2), 'product': last.group(3) if last.group(2) != 'ВСЁ' else '', 'unfinished': last.group(2) != 'ВСЁ', 'last_line_min_ago': ago, 'last_line_ts': ts_last}


def run_state(runs: list, now: float | None = None, state_dir: str | None = None) -> dict:
    """Метка данных: когда прочитаны (Лондон) и идёт ли прогон. Идёт = есть живые задания heavy-slot этого прогона ИЛИ пакет не закончил (журнал `progress.log`: последнее событие не «ВСЁ» и запись не старше PROGRESS_STALE_MIN) ИЛИ папка менялась < FRESH_MIN мин назад."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = time.time() if now is None else now
    jobs = heavy_jobs(runs, state_dir)
    lc = last_change(runs)
    ago = max(0, round((now - lc) / 60)) if lc else None
    prog = [x for x in (progress_state(r, now) for r in runs) if x]
    live_prog = [x for x in prog if x['unfinished'] and (x['last_line_min_ago'] is None or x['last_line_min_ago'] < PROGRESS_STALE_MIN)]
    stuck = [x for x in prog if x['unfinished'] and x not in live_prog]
    running = bool(jobs) or bool(live_prog) or (ago is not None and ago < FRESH_MIN)
    tz = ZoneInfo('Europe/London')
    at = datetime.fromtimestamp(now, tz).strftime('%H:%M')
    why = []
    if jobs:
        why.append(f"заданий heavy-slot этого прогона: {len(jobs)} ({', '.join(jobs[:4])}{'…' if len(jobs) > 4 else ''})")
    for x in live_prog:
        t = datetime.fromtimestamp(x['last_line_ts'], tz).strftime('%H:%M') if x.get('last_line_ts') else '—'
        why.append(f"пакет {x['run']} не закончен: последняя запись {t} «{x['event']}{(' ' + x['product']) if x['product'] else ''}»")
    for x in stuck:
        why.append(f"пакет {x['run']}: «ВСЁ» не писал, но молчит {x['last_line_min_ago']} мин")
    if ago is not None:
        why.append(f'папка менялась {ago} мин назад' if ago < 120 else 'папка не менялась больше двух часов')
    text = f"данные на {at} · прогон " + ('ещё идёт — числа могут измениться' if running else 'закончен')           # видимая строка — короткая (директор 22.11); остальное — в `details`, на странице под «подробно»
    details = 'время — по Лондону' + (': ' + '; '.join(why) if why else '')
    return {'at': at, 'tz': 'Europe/London', 'running': running, 'jobs': jobs, 'progress': [{k: v for k, v in x.items() if k != 'last_line_ts'} for x in prog], 'last_change_min_ago': ago, 'text': text, 'details': details}


def state_html(state: dict | None) -> str:
    if not state:
        return ''
    return (f"<div class='meta stamp' style='{'color:var(--soft);font-weight:600' if state['running'] else ''}'>{html.escape(state['text'])}"
            + (f"<details style='font-weight:400'><summary>подробно</summary>{html.escape(state['details'])}</details>" if state.get('details') else '') + '</div>')


# ---------- слова для владельца: названия этапов и фразы причин — из json рядом с правилами, не из кода ----------

def _load(repo: str, rel: str) -> dict:
    try:
        d = json.load(open(os.path.join(repo, rel), encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def load_words(repo: str) -> dict:
    """{'stages': {папка этапа: {name, pct}}, 'updated': …, 'phrases': [{has, say}]}. Нет файла — пусто: этап называется кодом, причина — своим текстом."""
    r = _load(repo, READINESS)
    return {'stages': r.get('stages') or {}, 'updated': r.get('updated'), 'phrases': (_load(repo, REASONS).get('phrases') or []), 'cutout': (_load(repo, REASONS).get('cutout') or {}), 'forms': (_load(repo, REASONS).get('forms') or {})}


def stage_name(W: dict, code: str) -> str:
    return ((W.get('stages') or {}).get(code) or {}).get('name') or code


def frame_caption(W: dict, code: str) -> str:
    """Одна строка «что на кадре этапа» — `frame_caption` в paint-readiness.json (нет — пусто)."""
    return ((W.get('stages') or {}).get(code) or {}).get('frame_caption') or ''


def frame_tiles(W: dict, code: str) -> int:
    """На сколько равных частей резать кадр этапа (ракурсы в ряд) — поле `frame_tiles` в paint-readiness.json; 1 — не резать."""
    try:
        return max(1, int(((W.get('stages') or {}).get(code) or {}).get('frame_tiles') or 1))
    except Exception:  # noqa: BLE001
        return 1


def stage_pct(W: dict, code: str):
    v = ((W.get('stages') or {}).get(code) or {}).get('pct')
    return v if isinstance(v, (int, float)) else None


def say(W: dict, reason: str) -> str:
    """Причина одной строкой словами: фразы всех подошедших строк таблицы (без повторов, по порядку таблицы). Ни одна не подошла — сам текст причины, укороченный."""
    out = []
    for p in W.get('phrases') or []:
        if p.get('has') and p['has'] in (reason or '') and p.get('say') and p['say'] not in out:
            out.append(p['say'])
    if out:
        return '; '.join(out)
    r = (reason or '').strip()
    return r if len(r) <= 120 else r[:117] + '…'


def stop_of(rows: list) -> tuple[str, str]:
    """Где остановился товар без крашеной модели: первый ОТКАЗ (пустой check.json раньше отказа — не причина, этап мог просто не писать его), иначе первый «нет check.json»."""
    for want in ('refused', 'missing'):
        for r in rows:
            if r['status'] == want:
                return r['stage'], (r.get('reason') or '').strip() or 'причина не записана'
    return rows[-1]['stage'] if rows else '—', 'все этапы прошли, но итоговой модели (08-material/material.glb) нет'


def summarise(per: dict, painted: set, label: str, n_dirs: int | None = None, frames: int | None = None, names: dict | None = None, cards: int | None = None) -> dict:
    """Сводка по `per` ({sku: [решения этапов]}) и множеству `painted` (sku с итоговой моделью). Чистая функция — считает и ничего не читает с диска."""
    names = names or {}
    stopped: dict = {}
    for sku in sorted(per):
        if sku in painted:
            continue
        st, why = stop_of(per[sku])
        stopped.setdefault(st, []).append({'sku': sku, 'name': names.get(sku) or sku, 'reason': why})
    stages = [{'stage': st, 'count': len(v), 'items': v} for st, v in sorted(stopped.items())]
    fin = {'ok': 0, 'soft': 0, 'refused': 0, 'missing': 0}
    strict = 0
    prow = []
    for sku in sorted(per):
        if sku not in painted:
            continue
        rows = per[sku]
        last = next((r for r in rows if r['stage'] == pf.NINE), rows[-1])
        fin[last['status']] = fin.get(last['status'], 0) + 1
        is_strict = pf.passed_all(rows, True)
        strict += is_strict
        prow.append({'sku': sku, 'name': names.get(sku) or sku, 'final': last['status'], 'strict': is_strict, 'reason': last.get('reason') or ''})
    s = {'label': label, 'n': len(per), 'n_dirs': n_dirs, 'stopped': sum(x['count'] for x in stages), 'stopped_by_stage': stages,
         'painted': len(painted & set(per)), 'painted_final': fin, 'painted_strict': strict, 'painted_items': prow, 'frames': frames, 'cards': cards}
    s['errors'] = verify(s)
    return s


def verify(s: dict) -> list:
    """Самопроверка сводки: каждое число считается двумя путями. Пустой список — сошлось."""
    e = []
    if s['n_dirs'] is not None and s['n'] != s['n_dirs']:
        e.append(f"вошло {s['n']} ≠ папок товаров на диске {s['n_dirs']}")
    if s['stopped'] + s['painted'] != s['n']:
        e.append(f"не дошли {s['stopped']} + покрашено {s['painted']} ≠ вошло {s['n']}")
    if sum(x['count'] for x in s['stopped_by_stage']) != s['stopped'] or sum(len(x['items']) for x in s['stopped_by_stage']) != s['stopped']:
        e.append('сумма по этапам остановки ≠ числу не дошедших')
    if any(not i['reason'] for x in s['stopped_by_stage'] for i in x['items']):
        e.append('у не дошедшего товара нет причины')
    if sum(s['painted_final'].values()) != s['painted'] or len(s['painted_items']) != s['painted']:
        e.append('итоги этапа 9 по покрашенным не сходятся с числом покрашенных')
    if s['frames'] is not None and s['frames'] != s['painted']:
        e.append(f"кадров «фото | наш 3D» {s['frames']} ≠ покрашено {s['painted']}")
    if s.get('cards') is not None and s['cards'] != s['n']:
        e.append(f"карточек на странице {s['cards']} ≠ вошло {s['n']}")
    return e


def render_md(s: dict, W: dict | None = None) -> str:
    W = W or {}
    f = s['painted_final']
    out = [f"# Прогон покраски `{s['label']}` — сводка (автоматом, `paint_run_report.py`)", '',
           (f"- **{s['data_state']['text']}** ({s['data_state'].get('details', '')})" if s.get('data_state') else '- данные: метка свежести не посчитана'),
           f"- **Вошло: {s['n']}**",
           f"- **Не дошли до готовой модели: {s['stopped']}**" + ('' if s['stopped'] else ' — нет')]
    for x in s['stopped_by_stage']:
        out.append(f"  - {stage_name(W, x['stage'])} (`{x['stage']}`) — {x['count']}: " + '; '.join(f"{i.get('name') or i['sku']} (`{i['sku']}`) — {say(W, i['reason'])}" for i in x['items']))
    out.append(f"- **Покрашено (есть итоговая модель этапа 8): {s['painted']}** — итог проверки: прошли {f['ok']} · с замечаниями {f['soft']} · не прошли {f['refused']}"
               + (f" · проверка не запускалась {f['missing']}" if f.get('missing') else '') + f"; без замечаний ни на одном этапе: {s['painted_strict']}")
    ch = s.get('stage_chain') or {}
    if ch:
        out.append('- **Цепочка по этапам** (вошло(следующий) = вошло − встало):')
        for k, v in ch.items():
            out.append(f"  - {stage_name(W, k)} (`{k}`): вошло {v['entered']} · прошло {v['ok']} · с замечаниями {v['soft']} · встало {v['refused']}" + (f" · нет данных этапа {v['nodata']}" if v['nodata'] else '') + f" · не дошло {v['not_reached']}")
    out.append(f"- **Кадров «фото | наш 3D»: {'не строились' if s['frames'] is None else s['frames']}** · карточек на странице: {'—' if s.get('cards') is None else s['cards']}")
    out.append('')
    if s['errors']:
        out += ['**ОШИБКА СВОДКИ:**'] + [f'- {x}' for x in s['errors']]
    else:
        out.append('Самопроверка сошлась: вошло = не дошли + покрашено; сумма по этапам = не дошедшим' + ('; кадров = покрашено; карточек = вошло.' if s['frames'] is not None else '.'))
    return '\n'.join(out) + '\n'


def painted_set(per: dict, runof: dict) -> set:
    return {sku for sku in per if os.path.exists(os.path.join(runof[sku], sku, MODEL))}


def product_meta(run: str, sku: str) -> dict:
    try:
        return json.load(open(os.path.join(run, sku, 'work', 'product.json'), encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return {}


def load_catalog(path: str | None) -> dict:
    """Выгрузка каталога (JSON-список записей с `sid` или `id`, `name`, `role`) → {товар: запись}. Нужна для названий тех товаров, что остановились раньше этапа 8: `work/product.json` там ещё не написан."""
    if not path:
        return {}
    d = json.load(open(os.path.expanduser(path), encoding='utf-8'))
    if isinstance(d, dict) and isinstance(d.get('items'), list):          # набор в виде {items: [...]} (например `set40.json` р.2)
        d = d['items']
    return {(r.get('sid') or r.get('id')): r for r in (d if isinstance(d, list) else [d]) if isinstance(r, dict) and (r.get('sid') or r.get('id'))}


NAMES_RU = os.path.join('tools', 'scout', 'data', 'names-en.json')


def load_names_ru(repo: str) -> dict:
    """Русские названия витрины из репозитория (`names-en.json`: ключ — sid, `ru` — название): запасной источник, когда нет ни `product.json`, ни выгрузки `--catalog`."""
    d = _load(repo, NAMES_RU)
    return {k: v['ru'] for k, v in d.items() if isinstance(v, dict) and v.get('ru')}


def photo_paths(per: dict, runof: dict) -> dict:
    """Фото товара: манифест этапа 5, а у остановившихся раньше — аргумент `--photo` из `run_all.json` (его пишет сам запуск прогона)."""
    out = {}
    for sku in per:
        base = os.path.join(runof[sku], sku)
        p = None
        try:
            p = json.load(open(os.path.join(base, 'work', 'manifest05.json'), encoding='utf-8'))[0]['path']
        except Exception:  # noqa: BLE001
            try:
                m = re.search(r'"--photo",\s*"([^"]+)"', open(os.path.join(base, 'run_all.json'), encoding='utf-8').read())
                p = m.group(1) if m else None
            except Exception:  # noqa: BLE001
                p = None
        if not (p and os.path.exists(p)):                                # встал на 01–02: пути фото в данных нет — берём вырезку фото рядом с формой (`<папка форм>/../inputs/<товар>.hd.rgba.png`)
            try:
                g = re.search(r'"--glb",\s*"([^"]+)"', open(os.path.join(base, 'run_all.json'), encoding='utf-8').read())
                q = os.path.join(os.path.dirname(os.path.dirname(g.group(1))), 'inputs', f'{sku}.hd.rgba.png') if g else None
                p = q if q and os.path.exists(q) else None
            except Exception:  # noqa: BLE001
                p = None
        out[sku] = p if p and os.path.exists(p) else None
    return out


def _jpeg(src: str, dst: str) -> None:
    from PIL import Image
    im = Image.open(src)
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        bgim = Image.new('RGB', im.size, (232, 232, 232))
        bgim.paste(im, mask=im.split()[-1])
        im = bgim
    else:
        im = im.convert('RGB')
    if max(im.size) > MAX_SIDE:
        k = MAX_SIDE / max(im.size)
        im = im.resize((round(im.size[0] * k), round(im.size[1] * k)), Image.LANCZOS)
    im.save(dst, 'JPEG', quality=JPEG_Q, optimize=True)


def _tiles(src: str, dst_base: str, n: int) -> list:
    """Режет кадр-полосу на n равных частей (ракурсы в ряд) → `<dst_base>_1.jpg` …; ширина части не похожа на высоту (±20 %) — не режет (пусто)."""
    from PIL import Image
    im = Image.open(src)
    w, h = im.size
    if n < 2 or abs(w / n - h) > 0.2 * h:
        return []
    parts = [im.convert('RGB').crop((round(k * w / n), 0, round((k + 1) * w / n), h)) for k in range(n)]
    box = None                                                       # общая рамка непустого во всех ракурсах (белые поля режем, чтобы товар был крупнее); одна рамка на все — ракурсы остаются сопоставимы
    for part in parts:
        b = part.convert('L').point(lambda v: 255 if v < 245 else 0).getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    if box:
        pad = round(0.04 * max(box[2] - box[0], box[3] - box[1]))
        pw, ph = parts[0].size
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(pw, box[2] + pad), min(ph, box[3] + pad))
        parts = [p.crop(box) for p in parts]
    out = []
    for k, part in enumerate(parts):
        p = f'{dst_base}_{k + 1}.png'
        part.save(p)
        _jpeg(p, f'{dst_base}_{k + 1}.jpg')
        os.remove(p)
        out.append(f'{dst_base}_{k + 1}.jpg')
    return out


def build_frames(repo: str, runof: dict, skus: list, out: str) -> dict:
    """Кадры «фото | наш 3D» (как `tex_visible`: фото карточки в кадре камеры этапа 4 и итоговая текстура этапа 8 по растру той же камеры, без света) — JPEG ≤1600 px.
    Возвращает {'ok': {sku: {'foto': путь, 'view3d': путь}}, 'errors': {sku: текст}}; сбой одного товара не рушит остальных (сводка ловит нехватку)."""
    import numpy as np
    from PIL import Image
    sys.path[:0] = [os.path.join(repo, 'tools', 'scout', 'salad', 'trellis'), os.path.join(repo, 'tools', 'scout')]
    import tex_visible as TV  # noqa: E402
    bg = 232
    os.makedirs(os.path.join(out, 'img'), exist_ok=True)
    res, errs = {}, {}
    for sku in skus:
        try:
            base = os.path.join(runof[sku], sku)
            photo = json.load(open(os.path.join(base, 'work', 'manifest05.json'), encoding='utf-8'))[0]['path']
            st = TV.load_stage(base)
            geoms = TV.load_shape(os.path.join(base, MODEL))
            P = np.asarray(Image.open(photo).convert('RGBA'))
            prgb, pmask = TV.photo_to_frame(P, st['P'], st['px'])
            after = TV.frame_from_tex(st, geoms, [g['tex'] for g in geoms])
            f1 = np.full(prgb.shape, bg, np.uint8)
            f1[pmask] = prgb[pmask]
            f2 = np.full(after.shape, bg, np.uint8)
            f2[st['mask']] = after[st['mask']]
            paths = {}
            for key, arr in (('foto', f1), ('view3d', f2)):
                im = Image.fromarray(arr[..., :3]).convert('RGB')
                if max(im.size) > MAX_SIDE:
                    k = MAX_SIDE / max(im.size)
                    im = im.resize((round(im.size[0] * k), round(im.size[1] * k)), Image.LANCZOS)
                p = os.path.join('img', f'{sku}_{"1-foto" if key == "foto" else "2-3d"}.jpg')
                im.save(os.path.join(out, p), 'JPEG', quality=JPEG_Q, optimize=True)
                paths[key] = p
            res[sku] = paths
        except Exception as ex:  # noqa: BLE001 — один товар не должен ронять страницу; нехватку поймает самопроверка
            errs[sku] = f'{type(ex).__name__}: {ex}'
    return {'ok': res, 'errors': errs}


def stopped_frames(runof: dict, per: dict, stopped: list, photos: dict, out: str) -> dict:
    """Для не дошедших: фото + последний кадр, который есть (от этапа остановки назад). {sku: {'foto','frame','frame_stage'}}; нет кадра — None (карточка всё равно будет)."""
    os.makedirs(os.path.join(out, 'img'), exist_ok=True)
    res = {}
    for sku, stage in stopped:
        c = {'foto': None, 'frame': None, 'frame_stage': None}
        try:
            if photos.get(sku):
                _jpeg(photos[sku], os.path.join(out, 'img', f'{sku}_1-foto.jpg'))
                c['foto'] = f'img/{sku}_1-foto.jpg'
        except Exception:  # noqa: BLE001
            pass
        order = [r['stage'] for r in per[sku]]
        cand = order[:order.index(stage) + 1][::-1] if stage in order else order[::-1]
        for st in cand:
            fr = os.path.join(runof[sku], sku, st, 'frame.png')
            if os.path.exists(fr):
                try:
                    _jpeg(fr, os.path.join(out, 'img', f'{sku}_2-stop.jpg'))
                    c['frame'], c['frame_stage'] = f'img/{sku}_2-stop.jpg', st
                    break
                except Exception:  # noqa: BLE001
                    continue
        res[sku] = c
    return res


CSS = """
:root{--bg:#fff;--fg:#1c1c1c;--mut:#666;--card:#f4f4f2;--line:#ddd;--ok:#1d7a3c;--soft:#9a6b00;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--mut:#aaa;--card:#222;--line:#444;--ok:#5fcf86;--soft:#e6b34a;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:16px/1.4 system-ui,sans-serif;max-width:1400px;margin-inline:auto}
h1{font-size:1.25rem;margin:0 0 8px}h2{font-size:1.05rem;margin:20px 0 8px}.sum{background:var(--card);border-radius:10px;padding:12px 14px;margin-bottom:16px}
.sum b{font-weight:650}.sum ul{margin:6px 0 0;padding-left:18px}.sum li{margin:3px 0;font-size:.92rem;word-break:break-word}.sum a{color:inherit}
.card{border:1px solid var(--line);border-radius:10px;padding:10px;margin-bottom:16px}.card h3{font-size:1rem;margin:0}.id,.meta,small{color:var(--mut);font-size:.78rem;opacity:.85}.meta{font-size:.85rem;opacity:1}
.badge{display:inline-block;font-size:.8rem;border-radius:99px;padding:1px 9px;border:1px solid currentColor;margin-left:6px;white-space:nowrap}.ok{color:var(--ok)}.soft{color:var(--soft)}.refused,.missing{color:var(--bad)}.waitb{color:var(--mut)}.retryb{color:var(--soft)}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}.pair figure{margin:0}.pair img{width:100%;height:auto;display:block;border-radius:6px;background:#e8e8e8}
.pair figcaption{font-size:.8rem;color:var(--mut);text-align:center;margin-top:2px}.why{font-size:.9rem;margin-top:6px}details{margin-top:4px;font-size:.8rem;color:var(--mut)}details summary{cursor:pointer}
.nofr{display:flex;align-items:center;justify-content:center;min-height:120px;border:1px dashed var(--line);border-radius:6px;color:var(--mut);font-size:.85rem}nav{margin:6px 0 12px;font-size:.95rem}nav a{padding:0 2px}
.pair3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:8px}.pair3 figure{margin:0}.pair3 img{width:100%;aspect-ratio:var(--ar,4/3);object-fit:contain;display:block;border-radius:6px;background:#fff}.pair3 .nofr{aspect-ratio:var(--ar,4/3);display:flex;align-items:center;justify-content:center;background:#f3f3f1;border-radius:6px;color:var(--mut);font-size:.85rem;text-align:center}.pair3 figcaption{font-size:.8rem;color:var(--mut);text-align:center;margin-top:2px}
.no{float:right;font-size:2.4rem;font-weight:800;line-height:1;color:var(--ink,#222);margin:2px 4px 0 12px;white-space:nowrap}
.tiles{display:grid;grid-template-columns:1fr 1fr;grid-auto-rows:minmax(0,1fr);gap:4px;aspect-ratio:var(--ar,auto)}.tiles img{width:100%;height:100%;min-height:0;object-fit:contain;display:block;border-radius:6px;background:#fff}
@media (max-width:640px){.pair,.tiles,.pair3{grid-template-columns:1fr}.tiles{aspect-ratio:auto;grid-auto-rows:auto}.tiles img{height:auto}}
"""


def _head(title: str, body: str) -> str:
    e = html.escape
    return (f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'>"
            f"<title>{e(title)}</title><style>{CSS}</style></head><body>{body}</body></html>")


def _card(c: dict, badge_class: str, badge: str, W: dict, caption: str, cap1: str, cap2: str, why: str = '', detail: str = '') -> str:
    e = html.escape
    ph = f"<figure><img src='{e(c['foto'])}' loading='lazy' alt='фото'><figcaption>{e(cap1)}</figcaption></figure>" if c.get('foto') else "<figure><div class='nofr'>фото нет</div></figure>"
    key = 'view3d' if c.get('view3d') else 'frame'
    if c.get('tiles'):                                               # кадр из нескольких ракурсов в ряд — сеткой, каждый крупно (на телефоне — по одному на всю ширину)
        fr = f"<figure><div class='tiles'{(' style=\'--ar:' + str(c['photo_ar']) + '\'') if c.get('photo_ar') and c.get('foto') else ''}>" + ''.join(f"<img src='{e(t)}' loading='lazy' alt='ракурс {i + 1}'>" for i, t in enumerate(c['tiles'])) + f"</div><figcaption>{e(cap2)}</figcaption></figure>"
    else:
        fr = (f"<figure><img src='{e(c[key])}' loading='lazy' alt='результат'><figcaption>{e(cap2)}</figcaption></figure>" if c.get(key) else "<figure><div class='nofr'>кадра нет</div></figure>")
    return (f"<div class='card'><h3>{e(c['name'])}<span class='badge {e(badge_class)}'>{e(badge)}</span></h3><div class='id'>{e(c['sku'])}</div>"
            + (f"<div class='meta'>{e(caption)}</div>" if caption else '') + f"<div class='pair'>{ph}{fr}</div>"
            + (f"<div class='why'>{e(why)}</div>" if why else '') + (f"<details><summary>подробно</summary>{e(detail)}</details>" if detail else '') + '</div>')


def render_page(s: dict, cards: list, stopped_cards: list, title: str, W: dict | None = None, stage_links: dict | None = None, state: dict | None = None) -> str:
    W = W or {}
    e = html.escape
    f = s['painted_final']
    li = ''.join(f"<li><b>{e(stage_name(W, x['stage']))}</b> <small>({e(x['stage'])})</small> — {x['count']}: "
                 + '; '.join(f"{e(i.get('name') or i['sku'])} — {e(say(W, i['reason']))}" for i in x['items']) + '</li>' for x in s['stopped_by_stage'])
    summ = (f"<div class='sum'><div><b>Вошло {s['n']}</b> · <b>не дошли до готовой модели {s['stopped']}</b> · <b>покрашено {s['painted']}</b> · <b>карточек на странице {len(cards) + len(stopped_cards)}</b></div>"
            f"<div>у покрашенных: прошли проверку {f['ok']} · с замечаниями {f['soft']} · не прошли {f['refused']}" + (f" · проверка не запускалась {f['missing']}" if f.get('missing') else '') + '</div>'
            + (f'<ul>{li}</ul>' if li else '') + (f"<div class='why'><b>ОШИБКА СВОДКИ:</b> {e('; '.join(s['errors']))}</div>" if s['errors'] else '') + '</div>')
    nav = ''
    if stage_links:
        nav = ("<div class='sum'><b>По этапам</b> (вошло в следующий этап = вошло − встало; «нет данных» — этап пропущен в данных):<ul>" + ''.join(
            f"<li><a href='{e(k)}/'>{e(stage_name(W, k))}</a> <small>({e(k)})</small> — вошло {v['entered']}, встало {v['refused']}{(', нет данных ' + str(v['nodata'])) if v['nodata'] else ''}</li>" for k, v in stage_links.items()) + '</ul></div>')
    body = []
    for c in cards:
        verdict = VERDICT.get(c['final'], c['final'])
        body.append(_card(c, c['final'], verdict, W, '', 'фото товара', 'наш 3D (без света)', say(W, c['reason']) if c['final'] != 'ok' and c['reason'] else '', c['reason'] if c['final'] != 'ok' else ''))
    stop = []
    for c in stopped_cards:
        st = c['stop_stage']
        cap = f"встал на: {stage_name(W, st)} ({st})"
        fs = c.get('frame_stage')
        cap2 = (f"последний кадр: {stage_name(W, fs)} ({fs})" + (f" — {frame_caption(W, fs)}" if frame_caption(W, fs) else '')) if fs else 'кадра нет'
        stop.append(_card(c, 'refused', 'не дошёл до готовой модели', W, cap, 'фото товара', cap2, say(W, c['reason']), c['reason']))
    return _head(title, f"<h1>{e(title)}</h1>{state_html(state)}{summ}{nav}<h2>Покрашенные: фото | наш 3D</h2>{''.join(body)}"
                 + (f"<h2>Не дошли до готовой модели: фото | последний кадр</h2>{''.join(stop)}" if stop else ''))


# ---------- страницы по этапам (T-180/4 доп., владелец TG 1258): после КАЖДОГО этапа — «фото | результат этапа» по всем товарам набора ----------
# Цепочка этапов (директор 22.11, владелец ловил несходящиеся числа): товар идёт по этапам, пока не встанет; всё, что в данных ПОСЛЕ его остановки (раннер порой гнал дальше отказа), на странице этапа не считается.
#   вошло(этап) = товары, не вставшие раньше; из них: прошёл · с замечаниями · встал · «нет данных этапа» (check.json не записан, а дальше товар шёл);
#   вошло(следующий) = вошло(этап) − встало(этап) — это самопроверка `verify_table`; «покрашено» = вошло(08) − встало(08).
# Товар с итоговой моделью (08-material/material.glb) не встаёт до этапа 9: отказ его этапа ≤ 8 при готовой модели — «с замечаниями» (модель есть, проверка не прошла), отказ этапа 9 — его итог.

NOTE_PAINTED_REFUSED = 'итоговая модель есть, а проверка этапа не прошла'


def effective(rows: list, painted: bool, partial: bool = False) -> dict:
    """{этап: {'status': ok|soft|refused|nodata|after, 'reason', 'note'}} по решениям этапов одного товара. `after` — этап после остановки товара (не считается)."""
    out = {}
    order = [r['stage'] for r in rows]
    stop = None if painted else stop_of(rows)
    if partial:                                                      # частичный путь (часть этапов не запускали нарочно): остановка — только настоящий отказ; нет check.json — «нет данных», не «встал»
        ref = [r for r in rows if r['status'] == 'refused']
        stop = (ref[0]['stage'], (ref[0].get('reason') or '').strip() or 'причина не записана') if ref else None
    for r in rows:
        st, why, note = r['status'], (r.get('reason') or '').strip(), ''
        if partial:
            if stop is None or order.index(r['stage']) < order.index(stop[0]):
                st = 'nodata' if st == 'missing' else st
            elif r['stage'] == stop[0]:
                st = 'refused'
            else:
                st = 'after'
        elif painted:
            if st == 'refused' and r['stage'] != pf.NINE:
                st, note = 'soft', NOTE_PAINTED_REFUSED
            elif st == 'missing':
                st = 'nodata'
        else:
            si = order.index(stop[0]) if stop[0] in order else len(order)
            i = order.index(r['stage'])
            if i > si:
                st = 'after'
            elif i == si:
                st, why = 'refused', stop[1] if st != 'refused' else why          # остановка: отказ; нет данных/«всё прошло, а модели нет» — тоже остановка со своей причиной
            elif st == 'missing':
                st = 'nodata'
        out[r['stage']] = {'status': st, 'reason': why, 'note': note}
    return out


def stage_table(per: dict, painted: set, partial: bool = False) -> tuple:
    """(этапы по порядку, {этап: сводка}) для набора. Сводка: entered, ok, soft, refused, nodata, not_reached (= N − вошло), items {товар: effective}."""
    stages = sorted({r['stage'] for rows in per.values() for r in rows})
    eff = {sku: effective(rows, sku in painted, partial) for sku, rows in per.items()}
    table = {}
    for st in stages:
        c = {'ok': 0, 'soft': 0, 'refused': 0, 'nodata': 0, 'after': 0}
        items = {}
        for sku in per:
            e = eff[sku].get(st) or {'status': 'nodata', 'reason': '', 'note': ''}
            c[e['status']] += 1
            items[sku] = e
        entered = c['ok'] + c['soft'] + c['refused'] + c['nodata']
        table[st] = {'stage': st, 'n': len(per), 'entered': entered, 'ok': c['ok'], 'soft': c['soft'], 'refused': c['refused'], 'nodata': c['nodata'], 'not_reached': c['after'], 'no_frame': 0, 'items': items}
    return stages, table


def verify_table(stages: list, table: dict, n: int, painted: int | None = None) -> list:
    """Самопроверка цепочки: вошло(1) = N; сумма статусов этапа = вошло; вошло(N+1) = вошло(N) − встало(N); вошло(08) − встало(08) = покрашено. Пустой список — сошлось."""
    e = []
    if stages and table[stages[0]]['entered'] != n:
        e.append(f"этап {stages[0]}: вошло {table[stages[0]]['entered']} ≠ N {n}")
    for a, b in zip(stages, stages[1:]):
        want = table[a]['entered'] - table[a]['refused']
        if table[b]['entered'] != want:
            e.append(f"цепочка: {a} вошло {table[a]['entered']} − встало {table[a]['refused']} = {want}, а {b} вошло {table[b]['entered']}")
    for st in stages:
        t = table[st]
        if t['ok'] + t['soft'] + t['refused'] + t['nodata'] != t['entered'] or t['entered'] + t['not_reached'] != n:
            e.append(f'этап {st}: прошло+замечания+встало+нет данных ≠ вошло, или вошло+не дошло ≠ N')
    if painted is not None and MATERIAL in table:
        t = table[MATERIAL]
        if t['entered'] - t['refused'] != painted:
            e.append(f"вошло в {MATERIAL} {t['entered']} − встало {t['refused']} = {t['entered'] - t['refused']} ≠ покрашено {painted}")
    return e


def stage_cards(runof: dict, table: dict, stage: str, W: dict, out: str, photos: dict, names: dict) -> tuple:
    """Карточки одного этапа: фото и `<товар>/<этап>/frame.png` (только у вошедших в этап). Возвращает (карточки, ошибки обработки файлов). Нет кадра — карточка с пометкой «кадра нет» (считается в `no_frame`)."""
    d = os.path.join(out, stage, 'img')
    os.makedirs(d, exist_ok=True)
    cards, errs = [], []
    for sku, e in sorted(table[stage]['items'].items()):
        c = {'sku': sku, 'name': names.get(sku) or sku, 'status': e['status'], 'reason': e['reason'], 'note': e['note'], 'foto': None, 'frame': None, 'stop': e.get('stop')}
        try:
            if photos.get(sku):
                _jpeg(photos[sku], os.path.join(d, f'{sku}_1-foto.jpg'))
                c['foto'] = f'img/{sku}_1-foto.jpg'
                from PIL import Image
                pw_, ph_ = Image.open(os.path.join(d, f'{sku}_1-foto.jpg')).size
                c['photo_ar'] = round(pw_ / ph_, 3) if ph_ else None                      # сетка ракурсов — тех же пропорций, что фото (одна высота)
        except Exception as ex:  # noqa: BLE001
            errs.append(f'{stage}: фото {sku}: {type(ex).__name__}: {ex}')
        fr = os.path.join(runof[sku], sku, stage, 'frame.png')
        if e['status'] != 'after' and os.path.exists(fr):
            try:
                tl = _tiles(fr, os.path.join(d, f'{sku}_2-{stage[:2]}'), frame_tiles(W, stage))
                if tl:
                    c['tiles'] = [f'img/{os.path.basename(x)}' for x in tl]
                    c['frame'] = c['tiles'][0]
                else:
                    _jpeg(fr, os.path.join(d, f'{sku}_2-{stage[:2]}.jpg'))
                    c['frame'] = f'img/{sku}_2-{stage[:2]}.jpg'
            except Exception as ex:  # noqa: BLE001
                errs.append(f'{stage}: кадр {sku}: {type(ex).__name__}: {ex}')
        cards.append(c)
    return cards, errs


STAGE_WORDS = {'ok': 'прошёл', 'soft': 'прошёл с замечаниями', 'refused': 'встал', 'nodata': 'нет данных этапа', 'after': 'не дошёл'}


def render_stage_page(s: dict, cards: list, stages: list, label: str, W: dict, state: dict | None = None) -> str:
    e = html.escape
    st = s['stage']
    pct = stage_pct(W, st)
    cap = f"этап {st[:2]} · {stage_name(W, st)} · готовность этапа " + (f'{pct} %' if pct is not None else 'не задана')
    nav = f"<a href='../'>весь прогон</a> · " + ' · '.join((f"<b>{e(x[:2])}</b>" if x == st else f"<a href='../{e(x)}/' title='{e(stage_name(W, x))}'>{e(x[:2])}</a>") for x in stages)
    legend = frame_caption(W, st)
    summ = (f"<div class='sum'><div><b>вошло {s['entered']}</b> · <b>прошло {s['ok']}</b> · с замечаниями {s['soft']} · <b>встало {s['refused']}</b>"
            + (f" · <b>нет данных этапа {s['nodata']}</b>" if s['nodata'] else '') + f" · не дошло {s['not_reached']} (встали раньше; из {s['n']})"
            + (f" · без кадра этапа {s['no_frame']}" if s['no_frame'] else '') + '</div>'
            + (f"<div class='why'><b>На кадре:</b> {e(legend)}</div>" if legend else '') + f"<div class='meta'>готовность обновлена: {e(str(W.get('updated') or '—'))}</div></div>")
    body = []
    for c in cards:
        why = say(W, c['reason']) if c['status'] in ('refused', 'soft') and c['reason'] else ''
        if c['note']:
            why = c['note'] + ('; ' + why if why else '')
        if c['status'] == 'after':
            why = f"встал раньше: {stage_name(W, c['stop'][0])} ({c['stop'][0]})" if c.get('stop') else 'встал раньше'
        if c['status'] == 'nodata':
            why = 'check.json этапа не записан, хотя товар шёл дальше'
        body.append(_card(c, 'missing' if c['status'] in ('after', 'nodata') else c['status'], STAGE_WORDS[c['status']], W, cap, 'фото товара', frame_caption(W, st) or f'после этапа {st[:2]}',
                          why, c['reason'] if c['status'] in ('refused', 'soft') else ''))
    return _head(f'{label}: {cap}', f"<h1>{e(cap)}</h1>{state_html(state)}<nav>{nav}</nav>{summ}{''.join(body)}")


def stage_pages(per: dict, painted: set, runof: dict, out: str, W: dict, label: str, names: dict, photos: dict, partial: bool = False, state: dict | None = None) -> tuple:
    """Страницы всех этапов набора в `<out>/<этап>/index.html`. Возвращает ({этап: сводка}, ошибки). Цепочка не сошлась — страницы НЕ строятся, вернутся только ошибки."""
    stages, table = stage_table(per, painted, partial)
    for sku in per:                                                  # у остановившегося — где встал (подпись у карточек «не дошёл»)
        if sku not in painted:
            stop = stop_of(per[sku]) if not partial else next(((r['stage'], r['reason']) for r in per[sku] if r['status'] == 'refused'), None)
            if stop is None:
                continue
            for st in stages:
                if table[st]['items'][sku]['status'] == 'after':
                    table[st]['items'][sku]['stop'] = stop
    errs = verify_table(stages, table, len(per), None if partial else len(painted & set(per)))
    sums = {st: {k: v for k, v in t.items() if k != 'items'} for st, t in table.items()}
    if errs:
        return sums, errs
    for st in stages:
        s = table[st]
        cards, e = stage_cards(runof, table, st, W, out, photos, names)
        errs += e
        s['no_frame'] = sums[st]['no_frame'] = sum(1 for c in cards if c['status'] in ('ok', 'soft', 'refused') and not c['frame'])
        os.makedirs(os.path.join(out, st), exist_ok=True)
        open(os.path.join(out, st, 'index.html'), 'w', encoding='utf-8').write(render_stage_page(s, cards, stages, label, W, state))
    json.dump(sums, open(os.path.join(out, 'stages.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return sums, errs


def publish(out: str, name: str) -> str:
    remote = f'{REMOTE_ROOT}/{name}'
    sh = lambda *c: subprocess.run(c, check=True)  # noqa: E731
    sh('ssh', '-o', 'BatchMode=yes', REMOTE, f'mkdir -p {remote}')
    sh('rsync', '-a', '--size-only', '-e', 'ssh -o BatchMode=yes', '--exclude', '*.png', '--exclude', 'page_*', out + '/', f'{REMOTE}:{remote}/')
    sh('ssh', '-o', 'BatchMode=yes', REMOTE, f'chmod -R a+rX {remote}')
    return f'{URL_ROOT}/{name}/'


def report(runs: list, per_by_label: dict, out: str, repo: str, name: str | None = None, do_publish: bool = False, frames_fn=None, with_stages: bool = True, catalog: str | None = None) -> int:
    """Сводка + страницы для набора прогонов. `per_by_label` — {метка прогона: {sku: решения}} в порядке `runs`; повтор sku — из первого прогона. Возвращает код возврата."""
    labels = list(per_by_label)
    per, runof = {}, {}
    seen = set()
    for r, lab in zip(runs, labels):
        for sku in pf.products(r):
            seen.add(sku)
        for sku, rows in per_by_label[lab].items():
            if sku not in per:
                per[sku], runof[sku] = rows, r
    n_dirs = len(seen)
    label = name or '+'.join(labels)
    W = load_words(repo)
    cat = load_catalog(catalog)
    ru = load_names_ru(repo)
    gone = 'товар снят с продажи' if cat else ''                      # выгрузка базы дана, а товара в ней нет — он снят (директор 22.11); без выгрузки честно показываем id
    names = {sku: product_meta(runof[sku], sku).get('name') or (cat.get(sku) or {}).get('name') or ru.get(sku) or gone or sku for sku in per}
    painted = painted_set(per, runof)
    os.makedirs(out, exist_ok=True)
    photos = photo_paths(per, runof)
    built = (frames_fn or build_frames)(repo, runof, sorted(painted), out)
    stop_list = [(sku, stop_of(rows)[0]) for sku, rows in sorted(per.items()) if sku not in painted]
    sf = stopped_frames(runof, per, stop_list, photos, out)
    s = summarise(per, painted, label, n_dirs, len(built['ok']), names, None)
    extra = [f'кадр не построен: {sku}: {er}' for sku, er in sorted(built['errors'].items())]
    cards = []
    for it in s['painted_items']:
        if it['sku'] in built['ok']:
            cards.append({**it, **built['ok'][it['sku']]})
    stopped_cards = []
    reasons = {i['sku']: i['reason'] for x in s['stopped_by_stage'] for i in x['items']}
    for sku, stg in stop_list:
        stopped_cards.append({'sku': sku, 'name': names[sku], 'stop_stage': stg, 'reason': reasons.get(sku, ''), **sf[sku]})
    s['cards'] = len(cards) + len(stopped_cards)
    s['errors'] = verify(s) + extra
    state = run_state(runs)                                          # метка свежести: когда прочитаны данные и идёт ли прогон
    s['data_state'] = state
    stage_sums = {}
    if with_stages:                                                    # страницы по этапам: `<out>/<этап>/index.html` — фото | результат этапа по всем товарам набора
        stage_sums, serrs = stage_pages(per, painted, runof, out, W, label, names, photos, state=state)
        s['errors'] += serrs
    s['stage_chain'] = {k: {x: y for x, y in v.items() if x != 'items'} for k, v in stage_sums.items()}
    open(os.path.join(out, 'summary.md'), 'w', encoding='utf-8').write(render_md(s, W))
    json.dump(s, open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if s['errors']:                                                  # не сошлось — страница прогона не строится (вместо неё — причина), выкладка заблокирована
        open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(_head('Страница не построена', '<h1>Страница не построена: сводка не сошлась</h1><ul>' + ''.join(f'<li>{html.escape(x)}</li>' for x in s['errors']) + '</ul>'))
    else:
        open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(render_page(s, cards, stopped_cards, f'Прогон покраски {label}', W, stage_sums, state))
    print(render_md(s, W))
    print(f'страница: {os.path.join(out, "index.html")}')
    if do_publish and not s['errors']:
        print('выложено:', publish(out, slug(label)))
    elif do_publish:
        print('НЕ выложено: сводка не сошлась')
    return 1 if s['errors'] else 0


# ---------- страница этапа «вырезка» (до конвейера покраски; вход — набор товаров и журнал вырезки, а не папки прогона) ----------

def read_chain(path: str) -> dict:
    """Журнал вырезки (`chain.jsonl` / `cut.jsonl`: по строке на товар {sku, sha, status, verdict, reason, mask_verdict, hybrid_error}) → {id с «_»: строка}; повтор — последняя строка."""
    out = {}
    for ln in open(os.path.expanduser(path), encoding='utf-8'):
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(r, dict) and r.get('sku'):
            if 'status' not in r:                                           # журнал `make_cut_v2.py` (T-178/2): поле `refused` (причина отказа) вместо `status`, файлы названы по товару, а не по sha
                r['status'] = 'refused' if r.get('refused') else 'ok'
            if not r.get('sha'):
                r['sha'] = str(r['sku']).replace(':', '_', 1)
            out[str(r['sku']).replace(':', '_', 1)] = r
    return out


def cut_reason(r: dict) -> str:
    """Причина вырезки из полей журнала словами-кодами (фразы — в paint-reasons.json): только то, что не «ок»."""
    bits = []
    if r.get('status') != 'ok' and not r.get('refused'):                    # у журнала make_cut_v2 `status` выведен нами из `refused` — служебное слово не показываем
        bits.append(f"status={r.get('status')}")
    if r.get('verdict') not in (None, 'ok'):
        bits.append(f"verdict={r.get('verdict')}")
    if r.get('mask_verdict') not in (None, 'ok'):
        bits.append(f"mask_verdict={r.get('mask_verdict')}")
    if r.get('hybrid_error'):
        bits.append(f"hybrid_error={r.get('hybrid_error')}")
    if r.get('reason'):
        bits.append(str(r['reason']))
    if r.get('refused'):
        bits.append(str(r['refused']))
    return '; '.join(bits)


def small_side(r: dict, rules: dict | None) -> int | None:
    """Мерка вырезки по правилу сторожа размера (`mesh_photo.check_size`, порог и «какая сторона» — из `rules/mesh-photo.json`): число px, если сторож её НЕ пропускает; иначе None. Своего порога здесь нет."""
    if not rules or not r.get('cut_wh'):
        return None
    import mesh_photo as MP
    good, _why = MP.check_size(list(r['cut_wh']), rules)
    if good:
        return None
    return int(min(r['cut_wh']) if rules.get('measure', 'min') == 'min' else max(r['cut_wh']))


def cut_status(r: dict | None, has_file: bool, rules: dict | None = None) -> str:
    """ok — вырезка есть и журнал чист; soft — есть, но фото маленькое / маска под вопросом; small — вырезка хорошая, но фото магазина мало для формы (сторож размера; с `rules`); refused — сбой, коллаж, плохая маска или файла нет; missing — товара нет в журнале."""
    if r is None:
        return 'missing'
    if has_file and small_side(r, rules) is not None and not r.get('hybrid_error') and r.get('mask_verdict') != 'bad' and r.get('verdict') != 'collage':
        return 'small'                                                       # отказ только по размеру: сама вырезка не виновата
    if r.get('status') != 'ok' or not has_file or r.get('verdict') == 'collage' or r.get('mask_verdict') == 'bad':
        return 'refused'
    if r.get('verdict') not in (None, 'ok') or r.get('mask_verdict') not in (None, 'ok'):
        return 'soft'
    return 'ok'


def cutout_line(s: dict) -> str:
    """Строка сводки этапа: вырезка есть (все) · годна для формы · фото мало; «не получилась» и «нет в журнале» — только если есть."""
    return (f"<b>вырезка есть {s['made']}</b> · <b>годна для формы {s['fit']}</b> (чистая {s['ok']}, с замечаниями {s['soft']}) · <b>фото мало {s['small']}</b>"
            + (f" · <b>не получилась {s['refused']}</b>" if s['refused'] else '') + (f" · нет в журнале {s['missing']}" if s['missing'] else ''))


def cutout_page(items: list, chain: dict, photos: str, cuts: str, out: str, W: dict, label: str, names: dict | None = None, rules: dict | None = None) -> tuple:
    """Страница `<out>/index.html`: по каждому товару набора «исходное фото | вырезка» + сводка вошло/есть вырезка/нет. Возвращает (сводка, ошибки); самопроверка: сумма статусов = N, карточек = N."""
    e = html.escape
    d = os.path.join(out, 'img')
    os.makedirs(d, exist_ok=True)
    cards, errs = [], []
    c = {'ok': 0, 'soft': 0, 'small': 0, 'refused': 0, 'missing': 0}
    CW = W.get('cutout') or {}
    for it in items:
        sku = it['id']
        r = chain.get(sku)
        sha = (r or {}).get('sha')
        cutf = os.path.join(cuts, f'{sha}.png') if sha else ''
        st = cut_status(r, bool(sha) and os.path.exists(cutf), rules)
        c[st] += 1
        reason = cut_reason(r) if r is not None and st != 'ok' else ('нет в журнале вырезки — будет сделана заново' if r is None else '')
        card = {'sku': sku, 'name': (names or {}).get(sku) or it.get('name') or sku, 'status': st, 'reason': reason, 'foto': None, 'frame': None}
        if st == 'small':                                                    # причина словами из paint-reasons.json (`cutout.small_reason`), число и порог — из мерки сторожа
            card['why'] = (CW.get('small_reason') or 'фото магазина маленькое ({side} сторона {n} px, нужно ≥{thr}) — форму не делаем').format(
                side=(CW.get('side_min') or 'меньшая') if rules.get('measure', 'min') == 'min' else (CW.get('side_long') or 'большая'), n=small_side(r, rules), thr=rules.get('min_cut_side_px'))
        for key, src, tag in (('foto', os.path.join(photos, f'{sha}.img') if sha else '', '1-foto'), ('frame', cutf, '2-cut')):
            if src and os.path.exists(src):
                try:
                    _jpeg(src, os.path.join(d, f'{sku}_{tag}.jpg'))
                    card[key] = f'img/{sku}_{tag}.jpg'
                except Exception as ex:  # noqa: BLE001
                    errs.append(f'{sku}: {tag}: {type(ex).__name__}: {ex}')
        cards.append(card)
    n = len(items)
    s = {'stage': 'cutout', 'n': n, 'ok': c['ok'], 'soft': c['soft'], 'small': c['small'], 'refused': c['refused'], 'missing': c['missing'], 'made': c['ok'] + c['soft'] + c['small'], 'fit': c['ok'] + c['soft'], 'cards': len(cards), 'errors': errs}
    if sum(c.values()) != n:
        s['errors'].append(f'вырезка: сумма статусов {sum(c.values())} ≠ N {n}')
    if len(cards) != n:
        s['errors'].append(f'вырезка: карточек {len(cards)} ≠ N {n}')
    pct = stage_pct(W, 'cutout')
    cap = f"этап вырезка · {stage_name(W, 'cutout')} · готовность этапа " + (f'{pct} %' if pct is not None else 'не задана')
    legend = frame_caption(W, 'cutout')
    summ = (f"<div class='sum'><div><b>вошло {n}</b> · {cutout_line(s)}</div>"
            + (f"<div class='why'><b>На кадре:</b> {e(legend)}</div>" if legend else '') + (f"<div class='why'><b>ОШИБКА СВОДКИ:</b> {e('; '.join(s['errors']))}</div>" if s['errors'] else '') + '</div>')
    words = {'ok': 'вырезка чистая', 'soft': 'вырезка с замечаниями', 'small': CW.get('small_label') or 'фото мало для формы', 'refused': 'вырезка не получилась', 'missing': 'нет в журнале'}
    css = {'small': 'soft'}                                                  # жёлтая метка (как «с замечаниями»), не красная: вырезка хорошая
    body = ''.join(_card(cd, css.get(cd['status'], cd['status']), words[cd['status']], W, cap, 'исходное фото', 'вырезка без фона', cd.get('why') or (say(W, cd['reason']) if cd['reason'] else ''), cd['reason']) for cd in cards)
    open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(_head(f'{label}: {cap}', f"<h1>{e(cap)}</h1>{summ}{body}"))
    json.dump({k: v for k, v in s.items()}, open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return s, s['errors']


def main_cutout(argv: list) -> int:
    ap = argparse.ArgumentParser(prog='paint_run_report.py cutout', description='страница этапа «вырезка»: исходное фото | вырезка по всем товарам набора (самопроверка: сумма = N, карточек = N)')
    ap.add_argument('--set', required=True, help='набор: JSON {items:[{id,name,…}]} или список (как set40.json)')
    ap.add_argument('--run', help='папка прогона вырезки: chain.jsonl, photos/<sha>.img, cut/<sha>.png (например ~/remlab-logs/t104-1119/1119-a)')
    ap.add_argument('--chain')
    ap.add_argument('--photos')
    ap.add_argument('--cuts')
    ap.add_argument('--out')
    ap.add_argument('--name')
    ap.add_argument('--repo')
    ap.add_argument('--publish', action='store_true')
    a = ap.parse_args(argv)
    run = os.path.expanduser(a.run) if a.run else None
    chain_p = a.chain or (os.path.join(run, 'chain.jsonl') if run else None)
    photos = os.path.expanduser(a.photos or (os.path.join(run, 'photos') if run else ''))
    cuts = os.path.expanduser(a.cuts or (os.path.join(run, 'cut') if run else ''))
    if not chain_p or not photos or not cuts:
        ap.error('нужен --run или все три: --chain, --photos, --cuts')
    repo = a.repo or os.path.abspath(os.path.join(HERE, '..', '..'))
    raw = json.load(open(os.path.expanduser(a.set), encoding='utf-8'))
    items = raw['items'] if isinstance(raw, dict) else raw
    name = a.name or ('cutout-' + os.path.splitext(os.path.basename(a.set))[0])
    out = os.path.expanduser(a.out or os.path.join(os.path.dirname(os.path.abspath(os.path.expanduser(a.set))), '_report-' + name))
    W = load_words(repo)
    sys.path.insert(0, os.path.join(repo, 'tools', 'scout'))
    import mesh_photo as MP                                                  # порог размера — из того же места, что сторож (rules/mesh-photo.json)
    s, errs = cutout_page(items, read_chain(os.path.expanduser(chain_p)), photos, cuts, out, W, name, rules=MP.load_rules(os.path.join(repo, 'tools', 'scout', 'rules', 'mesh-photo.json')))
    print(re.sub(r'</?b>', '', f"вошло {s['n']} · {cutout_line(s)} · карточек {s['cards']}"))
    print('ОШИБКА СВОДКИ: ' + '; '.join(errs) if errs else 'Самопроверка сошлась.')
    print(f'страница: {os.path.join(out, "index.html")}')
    if a.publish and not errs:
        print('выложено:', publish(out, slug(name)))
    return 1 if errs else 0


# ---------- страница этапа «форма» (T-180/5, директор 22.11, владелец TG 1228): фото | серый рендер формы 2 ракурса; утверждение владельцем ----------

def find_glb(dir_: str, sku: str) -> str | None:
    """GLB формы товара в папке: `<товар>*.glb`, предпочтительно `-hd`, из равных — свежий. Нет — None."""
    try:
        names = [n for n in os.listdir(dir_) if (n.startswith(sku + '-') or n == sku + '.glb') and n.endswith('.glb') and not n.endswith(('.audit.glb', '.raw.glb'))]      # `<товар>-…`: иначе id, являющийся началом другого id, взял бы чужой GLB
    except OSError:
        return None
    if not names:
        return None
    names.sort(key=lambda n: (('-hd' in n), os.path.getmtime(os.path.join(dir_, n))), reverse=True)
    return os.path.join(dir_, names[0])


def read_trial(path: str | None) -> dict:
    """Итог пакета форм (`summary-trial-*.json`: jobs[{sku, status, error}]) → {id с «_»: (статус, ошибка)}. Нет файла — пусто."""
    out = {}
    if not path or not os.path.exists(os.path.expanduser(path)):
        return out
    try:
        for j in json.load(open(os.path.expanduser(path), encoding='utf-8')).get('jobs') or []:
            if j.get('sku'):
                out[str(j['sku']).replace(':', '_', 1)] = (j.get('status'), j.get('error'))
    except Exception:  # noqa: BLE001
        pass
    return out


def form_status(r: dict | None, glb: str | None, frames: list, trial: tuple | None, rules: dict | None, final: bool, retry: bool = False) -> tuple:
    """(статус, причина): ok — форма и оба кадра есть; small — фото магазина мало для формы (форму не запускали); failed — форма не получилась (причина); wait — форма ещё считается (только до конца пакета, при final=True это failed); retry — форма не получилась, идёт повтор (товар в списке повтора, GLB ещё нет)."""
    if r is None:
        return ('failed', 'вырезки в журнале нет — форму не запускали') if final else ('wait', 'вырезки в журнале ещё нет')
    cs = cut_status(r, True, rules)
    if cs == 'small':
        return 'small', ''
    if cs == 'refused' or (r.get('refused') and cs != 'small'):
        return 'failed', 'вырезка не получилась — форму не запускали: ' + (cut_reason(r) or 'причина не записана')
    if glb and frames:
        return 'ok', ''
    if retry and not glb:
        return 'retry', ''
    if trial and trial[0] not in (None, 'done', 'ok') or (trial and trial[1]):
        return 'failed', f'форма не получилась: {trial[1] or trial[0]}'
    if glb:
        return ('failed', 'форма есть, кадры не отрисованы') if final else ('wait', 'форма есть, кадры ещё рисуются')
    return ('failed', 'формы в результате пакета нет') if final else ('wait', 'форма ещё считается')


def forms_page(items: list, chain: dict, photos: str, glbs: str, frames: str, out: str, W: dict, label: str, rules: dict | None = None, trial: dict | None = None, final: bool = False, retry: set | None = None) -> tuple:
    """Страница `<out>/index.html`: по товару набора крупный номер, фото | два серых рендера формы (az000 «как на фото» и az225 3/4 сзади, один свет), статус «форма есть / форма упала (причина) / фото мало». Самопроверка: сумма статусов = N, карточек = N, у «форма есть» два кадра."""
    e = html.escape
    d = os.path.join(out, 'img')
    os.makedirs(d, exist_ok=True)
    CW = W.get('forms') or {}
    words = {'ok': CW.get('ok') or 'форма есть', 'failed': CW.get('failed') or 'форма упала', 'small': CW.get('small') or 'фото мало', 'wait': CW.get('wait') or 'форма ещё считается', 'retry': CW.get('retry') or 'форма не получилась — идёт повтор'}
    css = {'ok': 'ok', 'failed': 'refused', 'small': 'soft', 'wait': 'waitb', 'retry': 'retryb'}
    c = {k: 0 for k in words}
    errs, blocks = [], []
    for n, it in enumerate(items, 1):
        sku = it['id']
        r = chain.get(sku)
        glb = next((g for g in (find_glb(x, sku) for x in glbs.split(',') if x) if g), None)          # несколько папок через запятую (основной пакет и повтор)
        fr = []
        dd = os.path.join(frames, sku)
        for v in ('az000', 'az225'):
            m = [f for f in sorted(os.listdir(dd)) if f.endswith(f'_{v}_clay.png')] if os.path.isdir(dd) else []
            if m:
                fr.append(os.path.join(dd, m[0]))
        if len(fr) != 2:
            fr = []
        st, why = form_status(r, glb, fr, (trial or {}).get(sku), rules, final, sku in (retry or ()))
        c[st] += 1
        if st == 'retry':
            why = CW.get('retry_reason') or 'сбой отправки к шлюзу, повтор'
        if st == 'small':
            why = (W.get('cutout') or {}).get('small_reason', '').format(side=('меньшая' if (rules or {}).get('measure', 'min') == 'min' else 'большая'), n=small_side(r, rules), thr=(rules or {}).get('min_cut_side_px')) or 'фото магазина маленькое — форму не делаем'
        sha = (r or {}).get('sha')
        foto = os.path.join(photos, f'{sha}.img') if sha else ''
        card = {'sku': sku, 'name': it.get('name') or sku, 'foto': None, 'tiles': []}
        if foto and os.path.exists(foto):
            try:
                _jpeg(foto, os.path.join(d, f'{sku}_1-foto.jpg'))
                card['foto'] = f'img/{sku}_1-foto.jpg'
            except Exception as ex:  # noqa: BLE001
                errs.append(f'{sku}: фото: {type(ex).__name__}: {ex}')
        if fr:
            try:
                crops = _forms_crop(fr)
                card['ar'] = round(min(1.7, max(0.6, crops[0].width / crops[0].height)), 3)               # одна рамка на три кадра карточки
                for t, p in zip(('az000', 'az225'), crops):
                    p.save(os.path.join(d, f'{sku}_{t}.jpg'), 'JPEG', quality=88)
                    card['tiles'].append(f'img/{sku}_{t}.jpg')
            except Exception as ex:  # noqa: BLE001
                errs.append(f'{sku}: кадры формы: {type(ex).__name__}: {ex}')
        if st == 'ok' and len(card['tiles']) != 2:
            errs.append(f'{sku}: «форма есть», а кадров {len(card["tiles"])} ≠ 2')
        blocks.append(_forms_card(n, card, css[st], words[st], CW.get('caption') or 'вырезка новая П1.96', why, CW))
    n_all = len(items)
    s = {'stage': 'forms', 'n': n_all, 'ok': c['ok'], 'failed': c['failed'], 'small': c['small'], 'wait': c['wait'], 'retry': c['retry'], 'cards': len(blocks), 'final': final, 'errors': errs}
    if sum(c.values()) != n_all:
        errs.append(f'форма: сумма статусов {sum(c.values())} ≠ N {n_all}')
    if len(blocks) != n_all:
        errs.append(f'форма: карточек {len(blocks)} ≠ N {n_all}')
    line = f"<b>вошло {n_all}</b> · <b>форма есть {c['ok']}</b> · <b>форма упала {c['failed']}</b> · <b>фото мало {c['small']}</b>" + (f" · форма ещё считается {c['wait']}" if c['wait'] else '') + (f" · идёт повтор {c['retry']}" if c['retry'] else '')
    cap = (W.get('forms') or {}).get('title') or 'Формы 3D по новой вырезке — утвердите'
    ask = (W.get('forms') or {}).get('ask') or 'Номер товара — крупно в углу карточки: напишите «не годны: № …», если форма не подходит.'
    summ = f"<div class='sum'><div>{line}</div><div class='why'>{e(ask)}</div>" + (f"<div class='why'><b>ОШИБКА СВОДКИ:</b> {e('; '.join(errs))}</div>" if errs else '') + '</div>'
    open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(_head(f'{label}: {cap}', f"<h1>{e(cap)}</h1>{summ}{''.join(blocks)}"))
    json.dump(s, open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return s, errs


def _forms_card(n: int, c: dict, badge_class: str, badge: str, caption: str, why: str, CW: dict) -> str:
    """Карточка формы: крупный номер справа, ниже в ряд три кадра одного размера — фото магазина | ракурс 1 | ракурс 2 (на телефоне — по одному в строке)."""
    e = html.escape
    fig = lambda src, cap: (f"<figure><img src='{e(src)}' loading='lazy' alt='{e(cap)}'><figcaption>{e(cap)}</figcaption></figure>" if src else f"<figure><div class='nofr'>{e(cap)}: {'формы нет' if badge_class in ('refused', 'soft') else 'кадр ещё не готов'}</div></figure>")
    t = c.get('tiles') or [None, None]
    return (f"<div class='card'><div class='no'>№ {n}</div><h3>{e(c['name'])}<span class='badge {e(badge_class)}'>{e(badge)}</span></h3><div class='id'>{e(c['sku'])}</div>"
            f"<div class='meta'>{e(caption)}</div><div class='pair3' style='--ar:{c.get('ar') or 1.333}'>{fig(c.get('foto'), CW.get('cap_photo') or 'фото магазина')}{fig(t[0], CW.get('cap_v1') or 'форма: как на фото (0°)')}{fig(t[1], CW.get('cap_v2') or 'форма: 3/4 сзади (225°)')}</div>"
            + (f"<div class='why'>{e(why)}</div>" if why else '') + '</div>')


def _forms_crop(paths: list) -> list:
    """Два серых кадра формы → одинаковые по размеру: общая рамка по предмету (не по фону) с полем 4 %; фон кадра — по углу."""
    from PIL import Image, ImageChops
    ims = [Image.open(p).convert('RGB') for p in paths]
    box = None
    for im in ims:
        bg = Image.new('RGB', im.size, im.getpixel((2, 2)))
        diff = ImageChops.difference(im, bg).convert('L').point(lambda v: 255 if v > 14 else 0)
        b = diff.getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    if not box:
        return ims
    pad = int(0.04 * max(box[2] - box[0], box[3] - box[1]))
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(ims[0].width, box[2] + pad), min(ims[0].height, box[3] + pad))
    return [im.crop(box) for im in ims]


def main_forms(argv: list) -> int:
    ap = argparse.ArgumentParser(prog='paint_run_report.py forms', description='страница этапа «форма»: фото | серый рендер формы (az000, az225) по набору; статусы форма есть / форма упала / фото мало')
    ap.add_argument('--set', required=True)
    ap.add_argument('--cutlog', required=True, help='журнал вырезки (cut.jsonl р.2)')
    ap.add_argument('--photos', required=True, help='папка исходных фото вырезки (`<товар>.img`)')
    ap.add_argument('--glbs', required=True, help='папка форм (GLB); несколько — через запятую')
    ap.add_argument('--retry', default='', help='id товаров, у которых идёт повтор формы (через запятую)')
    ap.add_argument('--frames', required=True, help='папка кадров forms_render.py')
    ap.add_argument('--trial', help='итог пакета форм summary-trial-*.json (причины отказов)')
    ap.add_argument('--final', action='store_true', help='пакет закончен: «ещё считается» не бывает — нет результата = форма упала')
    ap.add_argument('--out', required=True)
    ap.add_argument('--name', default='forms-set40')
    ap.add_argument('--repo')
    ap.add_argument('--publish', action='store_true')
    a = ap.parse_args(argv)
    repo = a.repo or os.path.abspath(os.path.join(HERE, '..', '..'))
    raw = json.load(open(os.path.expanduser(a.set), encoding='utf-8'))
    items = raw['items'] if isinstance(raw, dict) else raw
    sys.path.insert(0, os.path.join(repo, 'tools', 'scout'))
    import mesh_photo as MP
    rules = MP.load_rules(os.path.join(repo, 'tools', 'scout', 'rules', 'mesh-photo.json'))
    s, errs = forms_page(items, read_chain(a.cutlog), os.path.expanduser(a.photos), ','.join(os.path.expanduser(x) for x in a.glbs.split(',')), os.path.expanduser(a.frames), os.path.expanduser(a.out), load_words(repo), a.name, rules, read_trial(a.trial), a.final, {x for x in a.retry.split(',') if x})
    print(f"вошло {s['n']} · форма есть {s['ok']} · форма упала {s['failed']} · фото мало {s['small']} · ещё считается {s['wait']} · идёт повтор {s['retry']} · карточек {s['cards']}")
    print('ОШИБКА СВОДКИ: ' + '; '.join(errs) if errs else 'Самопроверка сошлась.')
    print(f'страница: {os.path.join(os.path.expanduser(a.out), "index.html")}')
    if a.publish and not errs:
        print('выложено:', publish(os.path.expanduser(a.out), slug(a.name)))
    return 1 if errs else 0


# ---------- частичный путь (T-180/4, директор 22.11): прогон, где нарочно запускали часть этапов (например 04 и 06) — страницы этих этапов без «покрашено» ----------

def partial_report(run: str, stage_codes: list, out: str, repo: str, name: str, catalog: str | None = None, photos_dir: str | None = None, do_publish: bool = False) -> int:
    """Страницы выбранных этапов одного прогона `<out>/<этап>/` + `index.html` (список этапов с числами). Цепочка сверяется так же; «покрашено» не считается — других этапов нет."""
    e = html.escape
    PC, PS, rules, _ = pf.load_pc(repo)
    _stages, per_all = pf.analyse(PC, PS, rules, run)
    unknown = [c for c in stage_codes if c not in _stages]
    if unknown:
        print('нет таких этапов:', unknown)
        return 2
    per = {sku: [r for r in rows if r['stage'] in stage_codes] for sku, rows in per_all.items()}
    runof = {sku: run for sku in per}
    W = load_words(repo)
    cat = load_catalog(catalog)
    ru = load_names_ru(repo)
    gone = 'товар снят с продажи' if cat else ''
    names = {sku: product_meta(run, sku).get('name') or (cat.get(sku) or {}).get('name') or ru.get(sku) or gone or sku for sku in per}
    photos = photo_paths(per, runof)
    if photos_dir:
        for sku in per:
            q = os.path.join(os.path.expanduser(photos_dir), f'{sku}.hd.rgba.png')
            if not photos.get(sku) and os.path.exists(q):
                photos[sku] = q
    os.makedirs(out, exist_ok=True)
    state = run_state([run])
    sums, errs = stage_pages(per, set(), runof, out, W, name, names, photos, partial=True, state=state)
    skipped = [pf_stage for pf_stage in _stages if pf_stage not in stage_codes]
    ch = ''.join(f"<li><a href='{e(k)}/'>{e(stage_name(W, k))}</a> <small>({e(k)})</small> — вошло {v['entered']}, прошло {v['ok']}, с замечаниями {v['soft']}, встало {v['refused']}" + (f", нет данных {v['nodata']}" if v['nodata'] else '') + f", не дошло {v['not_reached']}</li>" for k, v in sums.items())
    body = (f"<h1>{e(name)}</h1>{state_html(state)}<div class='sum'><div><b>Частичный путь:</b> здесь прогнаны только этапы {', '.join(e(c[:2]) for c in stage_codes)}; этапы {', '.join(e(c[:2]) for c in skipped)} в этом прогоне не запускались, поэтому «покрашено» не считается. Товаров в прогоне: {len(per)}.</div>"
            f"<div>Правило цепочки: вошло в следующий этап = вошло − встало.</div></div><div class='sum'><b>По этапам</b><ul>{ch}</ul></div>")
    if errs:
        body = f"<h1>Страница не построена: сводка не сошлась</h1><ul>{''.join(f'<li>{e(x)}</li>' for x in errs)}</ul>"
    open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(_head(name, body))
    json.dump({'run': run, 'stages': stage_codes, 'n': len(per), 'data_state': state, 'chain': sums, 'errors': errs}, open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for k, v in sums.items():
        print(f"{k}: вошло {v['entered']} · прошло {v['ok']} · с замечаниями {v['soft']} · встало {v['refused']} · нет данных {v['nodata']} · не дошло {v['not_reached']} · без кадра {v['no_frame']}")
    print('ОШИБКА СВОДКИ: ' + '; '.join(errs) if errs else 'Самопроверка сошлась.')
    print(f'страница: {os.path.join(out, "index.html")}')
    if do_publish and not errs:
        print('выложено:', publish(out, slug(name)))
    return 1 if errs else 0


def main_partial(argv: list) -> int:
    ap = argparse.ArgumentParser(prog='paint_run_report.py partial', description='страницы выбранных этапов одного прогона (частичный путь, без «покрашено»)')
    ap.add_argument('run')
    ap.add_argument('--stages', required=True, help='коды этапов через запятую, например 04-camera,06-visible')
    ap.add_argument('--out')
    ap.add_argument('--name')
    ap.add_argument('--repo')
    ap.add_argument('--catalog')
    ap.add_argument('--photos-dir', help='папка с вырезками фото `<товар>.hd.rgba.png`, если пути фото в прогоне нет')
    ap.add_argument('--publish', action='store_true')
    a = ap.parse_args(argv)
    run = os.path.expanduser(a.run).rstrip('/')
    repo = a.repo or os.path.abspath(os.path.join(HERE, '..', '..'))
    name = a.name or os.path.basename(run)
    out = os.path.expanduser(a.out or os.path.join(run, '_report-' + name))
    return partial_report(run, [x.strip() for x in a.stages.split(',') if x.strip()], out, repo, name, a.catalog, a.photos_dir, a.publish)


def main(argv: list) -> int:
    if argv and argv[0] == 'cutout':
        return main_cutout(argv[1:])
    if argv and argv[0] == 'partial':
        return main_partial(argv[1:])
    if argv and argv[0] == 'forms':
        return main_forms(argv[1:])
    ap = argparse.ArgumentParser(description='сводка и страницы прогона покраски (самопроверка: сумма сходится, кадров = покрашено, карточек = вошло)')
    ap.add_argument('runs', nargs='+')
    ap.add_argument('--out')
    ap.add_argument('--name')
    ap.add_argument('--repo')
    ap.add_argument('--catalog', help='выгрузка каталога (JSON-список {sid|id, name, role}) — названия товаров, остановившихся до этапа 8')
    ap.add_argument('--publish', action='store_true')
    a = ap.parse_args(argv)
    runs = [os.path.expanduser(r).rstrip('/') for r in a.runs]
    PC, PS, rules, repo = pf.load_pc(a.repo)
    per_by = {}
    for r in runs:
        _stages, per = pf.analyse(PC, PS, rules, r)
        per_by[os.path.basename(r)] = per
    out = a.out or os.path.join(runs[0], '_report')
    return report(runs, per_by, out, repo, a.name, a.publish, catalog=a.catalog)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
