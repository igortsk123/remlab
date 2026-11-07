#!/usr/bin/env python3
"""СКОРОСТЬ ФОТО НЕЙРОСЕТИ — сколько ждёт покупатель «Сделать реалистичнее» и сколько думает модель (photo-speed-monitor-01,
T-20261107-37; владелец 07.11: «мониторинг, чтобы мы знали, с какой скоростью идёт обработка»). Без сети и без денег: только журнал
DEV-рендера `~/scout-scenes/dev-render.log` (туда пишет сервис `remlab-render`, код — `tools/scout/draft_render.py`).

ОТКУДА ЧИСЛА. С 07.11 на каждое задание — одна строка с датой (`draft_render.photo_mark`):
  `2026-11-07 18:00:01 ФОТО-ЗАМЕР путь=browser подготовка=1.6 модель=32.7 сохранение=0.9 всего=35.3 исход=ok`
Журнал до неё — старого формата: пара строк «улучшение: наша часть Nс (…)» / «улучшение: модель Nс (…)» без даты; отказы — «ШЛЮЗ
ОТКАЗАЛ: HTTP 503 …» / «РЕНДЕР НЕ УДАЛСЯ: …» сразу за «наша часть». Дата такой записи — последняя строка журнала с датой перед ней
(перезапуски сервиса, 2–25 в сутки), то есть «не раньше»: в таблице помечается «≈». Старый формат читается только ДО первой строки
ФОТО-ЗАМЕР — дальше задание считается по ней одной (без двойного счёта).

ПУТИ. `browser` — кадры сняла страница покупателя (подготовка ≈ 2 с); `source` — лист взят из готового исходника (прежний путь
покупателя); `server` — лист пересобран на сервере (≈ 46 с): ночная досъёмка `demo_real` и пробы агентов, покупатель этого не ждёт.
Покупатель = browser + source. «Показ» (опрос /api/job раз в 3 с и загрузка кадров телефоном) в журнале DEV не виден — не меряем.

  python3 tools/ops/photo-speed.py [--days 7]        # таблица по дням + сводка за окно (для ведущего, сводка владельцу)
  python3 tools/ops/photo-speed.py --digest          # ночной шаг refresh_daily: строка DIGEST за сутки + WARN по порогам
  python3 tools/ops/photo-speed.py --selftest        # подставные журналы: медленно → WARN, 503 считается, пусто — без ошибки
  ключи: --log ПУТЬ (журнал), --rules ПУТЬ (пороги, по умолчанию tools/scout/rules/photo-speed.json), --now 'ГГГГ-ММ-ДД ЧЧ:ММ:СС'
Код выхода 0 и при WARN (шаг ночи — warn, не FAIL); 2 — сломан файл порогов."""
import json
import os
import re
import statistics
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.expanduser('~/scout-scenes/dev-render.log')
RULES = os.path.join(HERE, '..', 'scout', 'rules', 'photo-speed.json')
TS_FMT = '%Y-%m-%d %H:%M:%S'

ANCHOR_RE = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ')
MARK_RE = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ФОТО-ЗАМЕР (.*)$')
OURS_RE = re.compile(r'улучшение: наша часть ([\d.]+)с \((.*)\)')
MODEL_RE = re.compile(r'улучшение: модель ([\d.]+)с')
GW_RE = re.compile(r'ШЛЮЗ ОТКАЗАЛ: HTTP (\d{3})')
FAIL_RE = re.compile(r'РЕНДЕР НЕ УДАЛСЯ(?: \(\w+\))?: (.*)')
BUYER = ('browser', 'source')
PATH_RU = {'browser': 'кадры из браузера', 'source': 'лист из исходника', 'server': 'пересборка на сервере'}


def classify(text: str) -> str:
    """Отказ по тексту — те же метки, что `draft_render.photo_outcome`."""
    m = re.search(r'HTTP (\d{3})', text)
    if m:
        return f'шлюз_{m.group(1)}'
    if 'NoCredits' in text or 'не хватает денег' in text or 'закончился баланс' in text:
        return 'нет_денег'
    if 'не вернул картинку' in text:
        return 'шлюз_пусто'
    if 'timed out' in text or 'TimeoutError' in text:
        return 'таймаут'
    if 'разделительную полосу' in text:
        return 'полоса'
    return 'другое'


def _num(v):
    try:
        return None if v in (None, '-') else float(v)
    except ValueError:
        return None


def parse(lines) -> list:
    """Журнал → задания [{ts: datetime, approx, path, ours, model, post, total, outcome}]."""
    jobs, anchor, pending, last_ok, new_fmt = [], None, None, None, False
    for raw in lines:
        line = raw.rstrip('\n')
        m = MARK_RE.match(line)
        if m:
            new_fmt, pending, last_ok = True, None, None
            kv = dict(p.split('=', 1) for p in m.group(2).split() if '=' in p)
            path = kv.get('путь')
            jobs.append({'ts': datetime.strptime(m.group(1), TS_FMT), 'approx': False,
                         'path': None if path in (None, '-') else path, 'ours': _num(kv.get('подготовка')),
                         'model': _num(kv.get('модель')), 'post': _num(kv.get('сохранение')),
                         'total': _num(kv.get('всего')), 'outcome': kv.get('исход') or 'другое'})
            continue
        a = ANCHOR_RE.match(line)
        if a:
            anchor = datetime.strptime(a.group(1), TS_FMT)
        if new_fmt:
            continue                       # после первой строки ФОТО-ЗАМЕР старый формат не считаем
        m = OURS_RE.search(line)
        if m:
            if pending and pending.get('outcome'):
                jobs.append(pending)       # отказ шлюза без строки «РЕНДЕР НЕ УДАЛСЯ» — закрываем следующим заданием
            how = m.group(2)
            path = 'browser' if 'браузер' in how else 'source' if 'исходника' in how else 'server'
            pending = {'ts': anchor, 'approx': True, 'path': path, 'ours': float(m.group(1)), 'model': None,
                       'post': None, 'total': None, 'outcome': None}
            last_ok = None
            continue
        m = MODEL_RE.search(line)
        if m and pending:
            pending.update(model=float(m.group(1)), outcome='ok', total=pending['ours'] + float(m.group(1)))
            jobs.append(pending)
            last_ok, pending = pending, None
            continue
        m = GW_RE.search(line)
        if m and pending:
            pending['outcome'] = f'шлюз_{m.group(1)}'
            continue
        m = FAIL_RE.search(line)
        if m:
            if pending:
                pending['outcome'] = pending.get('outcome') or classify(m.group(1))
                jobs.append(pending)
                pending = None
            elif last_ok is not None and 'разделительную полосу' in m.group(1):
                last_ok.update(outcome='полоса', total=None)   # модель ответила, резка отказала
                last_ok = None
    if pending and pending.get('outcome'):
        jobs.append(pending)
    return [j for j in jobs if j['ts'] is not None]


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[max(0, min(len(xs) - 1, round(p / 100 * (len(xs) - 1))))]


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def s(v, nd=0):
    return '—' if v is None else f'{v:.{nd}f}'


def summary(jobs: list) -> dict:
    ok = [j for j in jobs if j['outcome'] == 'ok']
    buyer = [j for j in ok if j['path'] in BUYER]
    night = [j for j in ok if j['path'] == 'server']
    fails = [j for j in jobs if j['outcome'] != 'ok']
    out = {'n': len(jobs), 'ok': len(ok), 'fails': len(fails), 'approx': any(j['approx'] for j in jobs),
           'fail_kinds': {}, 'buyer_n': len(buyer), 'night_n': len(night)}
    for j in fails:
        out['fail_kinds'][j['outcome']] = out['fail_kinds'].get(j['outcome'], 0) + 1
    for name, grp in (('buyer', buyer), ('night', night), ('all', ok)):
        for k in ('ours', 'model', 'post', 'total'):
            out[f'{name}_{k}_med'] = med([j[k] for j in grp])
            out[f'{name}_{k}_p90'] = pct([j[k] for j in grp], 90)
    return out


def load_rules(path: str) -> dict:
    r = json.load(open(path, encoding='utf-8'))
    for k in ('window_h', 'base_buyer_total_s', 'base_model_s', 'median_factor', 'p90_max_s', 'fail_share_max', 'fail_min'):
        if not isinstance(r.get(k), (int, float)) or r[k] < 0:
            raise ValueError(f'{path}: {k} = {r.get(k)!r}')
    return r


def digest(jobs: list, rules: dict, now: datetime) -> list:
    """Строки ночного шага: одна DIGEST + WARN по порогам за окно `window_h`."""
    since = now - timedelta(hours=rules['window_h'])
    win = [j for j in jobs if since <= j['ts'] <= now]
    S = summary(win)
    head = 'DIGEST:фото нейросети за сутки'
    if not win:
        return [f'{head}: заданий 0']
    parts = [f"{S['n']} заданий"]
    if S['buyer_n']:
        parts.append(f"покупатель {S['buyer_n']}: ждал медиана {s(S['buyer_total_med'])} с (модель {s(S['buyer_model_med'])} с), "
                     f"90 % ≤ {s(S['buyer_total_p90'])} с")
    else:
        parts.append('покупатель 0')
    if S['night_n']:
        parts.append(f"ночь и пробы {S['night_n']}: модель медиана {s(S['night_model_med'])} с")
    share = S['fails'] / S['n']
    kinds = ', '.join(f'{k} {v}' for k, v in sorted(S['fail_kinds'].items()))
    parts.append(f"отказов {S['fails']}" + (f" ({100 * share:.0f} %: {kinds})" if S['fails'] else ''))
    out = [f"{head}: " + '; '.join(parts) + (' (даты приблизительные — журнал старого формата)' if S['approx'] else '')]
    lim = rules['base_buyer_total_s'] * rules['median_factor']
    if S['buyer_n'] and S['buyer_total_med'] is not None and S['buyer_total_med'] > lim:
        out.append(f"WARN:photo_speed: покупатель ждёт фото медиана {s(S['buyer_total_med'])} с — больше порога {lim:.0f} с "
                   f"(база {rules['base_buyer_total_s']} с × {rules['median_factor']})")
    if S['buyer_n'] and S['buyer_total_p90'] is not None and S['buyer_total_p90'] > rules['p90_max_s']:
        out.append(f"WARN:photo_speed: каждый десятый покупатель ждёт фото ≥ {s(S['buyer_total_p90'])} с — порог {rules['p90_max_s']} с")
    mlim = rules['base_model_s'] * rules['median_factor']
    if S['all_model_med'] is not None and S['all_model_med'] > mlim:
        out.append(f"WARN:photo_speed: модель думает медиана {s(S['all_model_med'])} с — больше порога {mlim:.0f} с "
                   f"(база {rules['base_model_s']} с × {rules['median_factor']}); у шлюза или OpenAI медленно")
    if S['fails'] >= rules['fail_min'] and share > rules['fail_share_max']:
        out.append(f"WARN:photo_speed: отказов фото {S['fails']} из {S['n']} ({100 * share:.0f} %): {kinds}")
    return out


def table(jobs: list, days: int, now: datetime) -> list:
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    win = [j for j in jobs if since <= j['ts'] <= now]
    out = [f'Скорость фото нейросети за {days} дн. (журнал {LOG}; «≈» — дата приблизительная, журнал старого формата)',
           '| день | заданий | покупатель: n · всего медиана / 90 % · модель | ночь и пробы: n · модель медиана · всего | отказы |',
           '|---|---|---|---|---|']
    d = since.date()
    while d <= now.date():
        g = [j for j in win if j['ts'].date() == d]
        S = summary(g)
        mark = ' ≈' if S['approx'] else ''
        kinds = ', '.join(f'{k} {v}' for k, v in sorted(S['fail_kinds'].items()))
        out.append(f"| {d:%d.%m}{mark} | {S['n']} | {S['buyer_n']} · {s(S['buyer_total_med'], 1)} / {s(S['buyer_total_p90'], 1)} с · "
                   f"{s(S['buyer_model_med'], 1)} с | {S['night_n']} · {s(S['night_model_med'], 1)} с · {s(S['night_total_med'], 1)} с | "
                   f"{S['fails']}{f' ({kinds})' if kinds else ''} |")
        d += timedelta(days=1)
    S = summary(win)
    out += ['', f"Итого за окно: заданий {S['n']}, готово {S['ok']}, отказов {S['fails']}"
            + (f" ({', '.join(f'{k} {v}' for k, v in sorted(S['fail_kinds'].items()))})" if S['fails'] else ''),
            '| путь | n | подготовка мед / 90 % | модель мед / 90 % | сохранение мед / 90 % | всего мед / 90 % |',
            '|---|---|---|---|---|---|']
    for name, label in (('buyer', 'покупатель (браузер + исходник)'), ('night', 'ночь и пробы (пересборка)'), ('all', 'все')):
        n = S['buyer_n'] if name == 'buyer' else S['night_n'] if name == 'night' else S['ok']
        out.append(f"| {label} | {n} | " + ' | '.join(f"{s(S[f'{name}_{k}_med'], 1)} / {s(S[f'{name}_{k}_p90'], 1)} с"
                                                     for k in ('ours', 'model', 'post', 'total')) + ' |')
    out.append('«сохранение» (резка, публикация кадров) есть только в строках ФОТО-ЗАМЕР; «показ» (опрос раз в 3 с, загрузка кадров '
               'телефоном) в журнале DEV не виден.')
    return out


def last_n(jobs: list, n: int) -> list:
    """Последние N готовых заданий по каждому пути без оглядки на даты — так мерили T-33/1 (сверка «±10 %»)."""
    out = [f'Последние {n} готовых заданий по пути (без дат; журнал {LOG})',
           '| путь | n | подготовка мед / 90 % | модель мед / 90 % | всего мед / 90 % | доля подготовки |', '|---|---|---|---|---|---|']
    for p in ('browser', 'source', 'server'):
        g = [j for j in jobs if j['path'] == p and j['outcome'] == 'ok'][-n:]
        mo, mm, mt = med([j['ours'] for j in g]), med([j['model'] for j in g]), med([j['total'] for j in g])
        share = f'{100 * mo / mt:.0f} %' if mo is not None and mt else '—'
        out.append(f"| {PATH_RU[p]} | {len(g)} | {s(mo, 1)} / {s(pct([j['ours'] for j in g], 90), 1)} с | "
                   f"{s(mm, 1)} / {s(pct([j['model'] for j in g], 90), 1)} с | {s(mt, 1)} / {s(pct([j['total'] for j in g], 90), 1)} с | {share} |")
    return out


def read_lines(path: str):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.readlines()


def selftest() -> int:
    errs = []

    def check(cond, msg):
        print(('✓ ' if cond else '✗ ') + msg)
        if not cond:
            errs.append(msg)

    rules = load_rules(RULES)
    now = datetime(2026, 11, 8, 3, 0, 0)
    # 1. новый формат: 3 быстрых у покупателя — тихо
    fast = [f'2026-11-07 1{i}:00:00 ФОТО-ЗАМЕР путь=browser подготовка=1.5 модель=32.0 сохранение=1.0 всего=34.5 исход=ok\n'
            for i in range(3)]
    d = digest(parse(fast), rules, now)
    check(len(d) == 1 and d[0].startswith('DIGEST:фото нейросети за сутки: 3 заданий') and 'медиана 34 с' in d[0]
          and 'приблизительные' not in d[0], f'быстрые — одна строка DIGEST без WARN: {d}')
    # 2. медленные у покупателя → WARN по медиане и 90 %
    slow = [f'2026-11-07 1{i}:00:00 ФОТО-ЗАМЕР путь=browser подготовка=2.0 модель=70.0 сохранение=1.0 всего=73.0 исход=ok\n'
            for i in range(4)]
    d = digest(parse(slow), rules, now)
    check(sum(x.startswith('WARN:photo_speed: покупатель ждёт') for x in d) == 1, 'медленно → WARN по медиане')
    check(any('каждый десятый' in x for x in d), 'медленно → WARN по 90 %')
    check(any('модель думает' in x for x in d), 'медленная модель → WARN')
    # 3. отказы 503 считаются, порог 10 % и ≥ 2
    f503 = fast + ['2026-11-07 15:00:00 ФОТО-ЗАМЕР путь=browser подготовка=1.5 модель=- сохранение=- всего=3.0 исход=шлюз_503\n'] * 2
    d = digest(parse(f503), rules, now)
    check('отказов 2' in d[0] and 'шлюз_503 2' in d[0], f'503 в строке DIGEST: {d[0]}')
    check(any(x.startswith('WARN:photo_speed: отказов фото 2 из 5') for x in d), 'отказы 2 из 5 → WARN')
    one = digest(parse(fast * 4 + f503[-1:]), rules, now)
    check(not any(x.startswith('WARN') for x in one), 'один 503 из 13 — без WARN')
    # 4. пустой журнал и пустое окно — без ошибки
    check(digest(parse([]), rules, now) == ['DIGEST:фото нейросети за сутки: заданий 0'], 'пустой журнал — «заданий 0»')
    old = ['2026-10-01 10:00:00 ФОТО-ЗАМЕР путь=browser подготовка=1 модель=30 сохранение=1 всего=32 исход=ok\n']
    check(digest(parse(old), rules, now) == ['DIGEST:фото нейросети за сутки: заданий 0'], 'старое вне окна — «заданий 0»')
    # 5. старый формат: дата по строке-якорю, отказ шлюза и полоса, ночь отдельно
    legacy = ['2026-11-07 09:00:00 сервис запущен\n',
              'улучшение: наша часть 1.6с (кадры из браузера)\n', 'улучшение: модель 32.7с (размер 2048x3072, качество medium); итого\n',
              'улучшение: наша часть 46.0с (ИСХОДНИКА НЕ БЫЛО — пересобрал, это потеря)\n', 'улучшение: модель 29.0с (размер 2048x3072, качество medium)\n',
              'улучшение: наша часть 1.2с (кадры из браузера)\n', 'ШЛЮЗ ОТКАЗАЛ: HTTP 503 Service Unavailable | модель x\n',
              'РЕНДЕР НЕ УДАЛСЯ: SystemExit(\'шлюз отказал (HTTP 503): …\')\n',
              'улучшение: наша часть 1.4с (кадры из браузера)\n', 'улучшение: модель 31.0с (размер 2048x3072, качество medium)\n',
              "РЕНДЕР НЕ УДАЛСЯ: RuntimeError('модель закрасила разделительную полосу — резать нечем')\n"]
    J = parse(legacy)
    check([j['outcome'] for j in J] == ['ok', 'ok', 'шлюз_503', 'полоса'], f'старый формат: исходы {[j["outcome"] for j in J]}')
    check(all(j['approx'] and j['ts'] == datetime(2026, 11, 7, 9) for j in J), 'старый формат: дата по якорю, «≈»')
    d = digest(J, rules, now)
    check('покупатель 1' in d[0] and 'ночь и пробы 1' in d[0] and 'приблизительные' in d[0], f'старый формат в DIGEST: {d[0]}')
    # 6. после первой строки ФОТО-ЗАМЕР старый формат не считается дважды
    mixed = legacy[:3] + ['улучшение: наша часть 1.6с (кадры из браузера)\n', 'улучшение: модель 32.7с (размер 2048x3072)\n',
                          '2026-11-07 12:00:00 ФОТО-ЗАМЕР путь=browser подготовка=1.6 модель=32.7 сохранение=0.9 всего=35.3 исход=ok\n',
                          'улучшение: наша часть 1.6с (кадры из браузера)\n', 'улучшение: модель 32.7с (размер 2048x3072)\n']
    J = parse(mixed)
    check(len(J) == 3 and [j['approx'] for j in J] == [True, True, False],
          f'смешанный журнал: старые до первой метки + новая, без двойного счёта ({len(J)})')
    # 7. таблица за 7 дней строится и на пустом
    t = table([], 7, now)
    check(len(t) > 10 and t[3].startswith('| 02.11 | 0 |'), 'таблица на пустом журнале')
    # 8. сломанный файл порогов — ошибка, не молчание
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump({'window_h': 24}, f)
    try:
        load_rules(f.name)
        check(False, 'сломанные пороги должны падать')
    except ValueError:
        check(True, 'сломанные пороги — ValueError')
    finally:
        os.unlink(f.name)
    print(f'photo-speed selftest: ошибок {len(errs)}')
    return 1 if errs else 0


def main(a: list) -> int:
    def arg(k, default=None):
        return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else default

    if '--selftest' in a:
        return selftest()
    global LOG
    LOG = arg('--log', LOG)
    try:
        rules = load_rules(arg('--rules', RULES))
    except (OSError, ValueError) as e:
        print(f'WARN:photo_speed: пороги не прочитаны: {e}')
        return 2
    now = datetime.strptime(arg('--now'), TS_FMT) if arg('--now') else datetime.now()
    try:
        jobs = parse(read_lines(LOG))
    except OSError as e:
        print(f'DIGEST:фото нейросети за сутки: журнала нет ({LOG})')
        print(f'WARN:photo_speed: журнал DEV-рендера не прочитан: {e}')
        return 0
    if '--digest' in a:
        print('\n'.join(digest(jobs, rules, now)))
    elif '--last' in a:
        print('\n'.join(last_n(jobs, int(arg('--last', '20')))))
    else:
        print('\n'.join(table(jobs, int(arg('--days', '7')), now)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
