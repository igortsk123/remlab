"""T-20261127-176 — Opus-агент по подписке читает листы Этажей вместо платного Opus (план Fable `fable-1126/plan-t176.md`).

Точка входа `one(cid, key, prompt, img)` — та же, что у `vetka_a_run.one` (платный путь через шлюз): `run_sb100.py` подменяет `R.one` на неё
(`attach`), как подменяет заглушкой `--fake`. Вход байт в байт как у платного: текст (prompt0 + добавка из объявления) и JPEG листа; хеши — в журнал.
Вызов — `claude -p --input-format stream-json` (картинка блоком в сообщении), модель claude-opus-5-5, без инструментов, из пустой папки вне проекта,
без наших настроек/подключений/сессий, нейтральный системный запрос; `--bare` НЕ ставим (он отключает вход по подписке и идёт платным ключом).
Из окружения убраны ВСЕ имена с ключами/токенами/шлюзом (их список — в журнал); вход по подписке проверяется `apiKeySource` в ответе программы.

Что ни одно сообщение не молчит:
  • программы нет / не вошла в учётку / накладные входные токены контрольного вызова > 1000 / вход не по подписке → `AgentStop` до первого листа (`preflight`);
  • код возврата ≠ 0, таймаут 600 с — один повтор, снова сбой → отказ с причиной; пустой ответ, обрыв по длине, отказ модели — отказ без повтора;
  • лимит подписки — стоп ВСЕЙ пачки (файл `<out>/STOP` с временем сброса), повторов нет; пятичасовое окно ≥ 70 % — пауза до сброса, неделя ≥ 60 % — стоп
    (разовое исключение — `OPUS_AGENT_WEEK_ALLOW='<N>:<YYYY-MM-DD>[/<YYYY-MM-DD>]:<TG владельца>'`: не больше N листов сверх 60 % и только в эти даты UTC, каждый лист — строка журнала с причиной
    «допуск TG…», счёт N по журналу переживает перезапуск; `OPUS_AGENT_WEEK_HARD` — жёсткий потолок недели, %, по умолчанию 60: с него стоп всегда; битая строка — стоп с причиной);
  • у листа нет добавки из объявления (`dlya_llm`) — отказ БЕЗ вызова (`refuse_no_addendum`), а не запрос со словом «None».
Журнал `<out>/vetka-a/calls.jsonl` — строка на каждый вызов и каждый отказ (деньги `usd` = 0.0: подписка; `usd_list` — цена по прейскуранту из ответа программы, для сравнения).
Денег не тратится; платных ключей нет."""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

MODEL = 'claude-opus-5-5'
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')  # допустимые значения `claude --effort` (2.1.332)
EFFORT = 'medium'                                    # одно значение на всю пачку (директор 27.11 14:31: замер 3 листа — рассуждений ×0,81 от платного, high ×1,27); меняется set_effort / --agent-effort
LABELS5_CAP_MAX = 3.0                                # потолок шага подписей labels5 при агенте, $ (задание 27.11)
LABELS5_WORST = 0.07                                 # худший замеренный вызов labels5 ($0,054) с запасом
SYSTEM = 'You are a helpful assistant.'              # нейтральный системный запрос (ваш пустой запрос программа не принимает как «нет»)
TIMEOUT = 600
MAX_OUT = '32000'                                    # как у платного пути (R.MAX_TOK = 32000 в run_sb100)
OVERHEAD_MAX = 1000                                  # накладные входные токены контрольного вызова: больше — окружение протекло
FIVE_PAUSE = 70                                      # % пятичасового окна: с этого — пауза до сброса
WEEK_STOP = 60                                       # % недели: с этого — стоп пачки
MAX_FAILS = 3                                        # отказов вызова подряд — стоп пачки
KEY_RX = re.compile(r'(API_?KEY|TOKEN|SECRET|GATEWAY|ANTHROPIC|OPENAI|VERCEL|GEMINI|GOOGLE_API|CREDENTIAL|PASSWORD|TELEGRAM)', re.I)   # TELEGRAM_STATE_DIR: без неё claude -p не поднимает Telegram-плагин и не выбивает канал владельца (27.11)
LIMIT_RX = re.compile(r'(usage limit|rate limit|limit reached|limit will reset|quota|overloaded_limit|5-hour limit|weekly limit)', re.I)
NO_ADDENDUM = 'нет добавки из объявления (dlya_llm)'

CLAUDE = os.environ.get('OPUS_AGENT_CLAUDE') or ''   # путь к программе; пусто — искать claude в PATH
LIMIT_CMD = os.environ.get('OPUS_AGENT_LIMIT_CMD') or os.path.expanduser('~/.local/bin/limit-tekst')
CWD = os.environ.get('OPUS_AGENT_CWD') or os.path.expanduser('~/remlab-logs/t176/cwd-empty')

A = None                                             # <out>/vetka-a — как у платного модуля (задаёт run_sb100: R.A = A)
OUT = None                                           # <out> — там STOP-файл, который уже читает run_sb100
lock = threading.Lock()
spent = [0.0]                                        # платных денег нет — всегда 0.0 (совместимость с R.spent_total)
STATE = {'version': None, 'removed': [], 'preflight': None}
sleep = time.sleep                                   # подменяется в тестах


class AgentStop(Exception):
    """Пачку нельзя начинать/продолжать: причина — в тексте."""


def sha(b):
    return hashlib.sha256(b if isinstance(b, bytes) else str(b).encode('utf-8')).hexdigest()


def clean_env(environ=None):
    """Окружение запуска: без единого имени с ключом/токеном/шлюзом; предел ответа как у платного пути. Возвращает (env, убранные имена)."""
    src = dict(os.environ if environ is None else environ)
    removed = sorted(k for k in src if KEY_RX.search(k))
    env = {k: v for k, v in src.items() if k not in removed}
    env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = MAX_OUT
    return env, removed


def find_claude():
    p = CLAUDE or shutil.which('claude') or ''
    if not p or not os.path.exists(p):
        raise AgentStop('программа claude не найдена (OPUS_AGENT_CLAUDE=%r, PATH) — пачку не начинаю' % CLAUDE)
    return p


def build_cmd(claude, effort=None):
    """Ключи — по `claude --help` 2.1.332. НЕТ --bare (отключает подписку). Запуск из пустой папки: ни CLAUDE.md, ни памяти проекта."""
    return [claude, '-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose', '--model', MODEL, '--tools', '',
            '--effort', effort or EFFORT, '--setting-sources', '', '--strict-mcp-config', '--no-session-persistence', '--system-prompt', SYSTEM]


def build_message(prompt, img):
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'text', 'text': prompt},
        {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': base64.b64encode(img).decode()}}]}}


def parse_stream(stdout):
    """Из потока событий программы: init, result, статус лимита. Нет result — None (программа оборвалась)."""
    init = res = lim = None
    for ln in (stdout or '').splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        t = e.get('type')
        if t == 'result':
            res = e
        elif t == 'system' and e.get('subtype') == 'init':
            init = e
        elif t == 'rate_limit_event':
            lim = e.get('rate_limit_info') or {}
    return {'init': init, 'result': res, 'rate': lim}


def limit_hit(parsed):
    """Признак лимита подписки: статус события лимита не allowed*, либо ошибка результата с текстом про лимит."""
    r = parsed.get('rate') or {}
    st = str(r.get('status') or 'allowed')
    if not st.startswith('allowed'):
        return 'статус лимита %s (%s, сброс %s)' % (st, r.get('rateLimitType'), r.get('resetsAt'))
    res = parsed.get('result') or {}
    if res.get('is_error') and LIMIT_RX.search(str(res.get('result') or '')):
        return 'ответ программы про лимит: %s' % str(res.get('result'))[:200]
    return None


def limit_numbers():
    """`limit-tekst --chisla` → (п5, сброс5, п7, сброс7). Программы нет/ответ не разобран — AgentStop (счётчик обязателен, без него не гоним)."""
    if not os.path.exists(LIMIT_CMD):
        raise AgentStop('нет счётчика лимита %s — пачку не гоню' % LIMIT_CMD)
    p = subprocess.run([LIMIT_CMD, '--chisla'], capture_output=True, text=True, timeout=60)
    try:
        a = [int(x) for x in p.stdout.split()]
        if p.returncode != 0 or len(a) != 4:
            raise ValueError(p.stdout)
    except ValueError:
        raise AgentStop('счётчик лимита ответил не «п5 сброс5 п7 сброс7» (rc=%s): %r %r' % (p.returncode, p.stdout[:100], p.stderr[:100]))
    return tuple(a)


ALLOW_RX = re.compile(r'^(\d+):(\d{4}-\d{2}-\d{2})(?:/(\d{4}-\d{2}-\d{2}))?:(\S.*)$')


def week_hard():
    """OPUS_AGENT_WEEK_HARD — жёсткий потолок недели, %: с него стоп ВСЕГДА, даже с допуском. Не задан — равен WEEK_STOP (допуск ничего не открывает). Битое значение — AgentStop."""
    s = (os.environ.get('OPUS_AGENT_WEEK_HARD') or '').strip()
    if not s:
        return WEEK_STOP
    try:
        v = int(s)
        if not 1 <= v <= 100:
            raise ValueError(s)
    except ValueError:
        raise AgentStop('битая OPUS_AGENT_WEEK_HARD=%r — ждали целое 1…100 (%% недели), пачку не гоню' % s)
    return v


def week_allow(s=None):
    """OPUS_AGENT_WEEK_ALLOW='<N>:<YYYY-MM-DD>[/<YYYY-MM-DD>]:<TG владельца>' — разовый допуск: не больше N листов СВЕРХ WEEK_STOP и только в названные даты (UTC; две даты — обе разрешены, не диапазон).
    Не задана/пуста → None (стоп как раньше). Битая → AgentStop с причиной (не молча). → {'n','dates','tg','key'}; key (TG+даты, без N) связывает строки журнала одного допуска."""
    s = os.environ.get('OPUS_AGENT_WEEK_ALLOW') if s is None else s
    s = (s or '').strip()
    if not s:
        return None
    bad = AgentStop('битая OPUS_AGENT_WEEK_ALLOW=%r — ждали <N>:<YYYY-MM-DD>[/<YYYY-MM-DD>]:<TG владельца>, N ≥ 1; пачку не гоню' % s)
    m = ALLOW_RX.match(s)
    if not m or int(m.group(1)) < 1:
        raise bad
    dates = [d for d in (m.group(2), m.group(3)) if d]
    try:
        for d in dates:
            time.strptime(d, '%Y-%m-%d')
    except ValueError:
        raise bad
    tg = m.group(4).strip()
    return {'n': int(m.group(1)), 'dates': dates, 'tg': tg, 'key': '%s|%s' % (tg, '/'.join(dates))}


def gate(nums, now=None, allow=None, used=0, hard=None):
    """('ok'|'pause'|'stop', причина, секунд паузы). Неделя ≥ 60 % — стоп; пятичасовое ≥ 70 % — пауза до сброса окна.
    allow (week_allow) и used (сколько листов этого допуска уже вызвано): неделя между WEEK_STOP и hard (week_hard) пускает, если сегодня (UTC) — названная дата и used < N;
    тогда ответ 'ok' с НЕПУСТОЙ причиной «допуск …» (одно резервирование листа делает вызывающий). Неделя ≥ hard — стоп всегда. Пятичасовая пауза — как была."""
    p5, r5, p7, r7 = nums
    now = time.time() if now is None else now
    hard = week_hard() if hard is None else hard
    over = ''
    if (p7 >= WEEK_STOP or p7 >= hard) and r7 > now:
        base = 'неделя %d %% ≥ %d %% (сброс %s)' % (p7, min(WEEK_STOP, hard), time.strftime('%d.%m %H:%M UTC', time.gmtime(r7)))
        if p7 >= hard:
            return 'stop', base + ('' if hard == WEEK_STOP else ' · жёсткий потолок %d %%: допуск не действует' % hard), 0
        if allow is None:
            return 'stop', base, 0
        today = time.strftime('%Y-%m-%d', time.gmtime(now))
        if today not in allow['dates']:
            return 'stop', base + ' · допуск %s не на сегодня (%s UTC; допуск на %s)' % (allow['tg'], today, '/'.join(allow['dates'])), 0
        if used >= allow['n']:
            return 'stop', base + ' · допуск %s исчерпан: %d из %d листов' % (allow['tg'], used, allow['n']), 0
        over = 'допуск %s: лист %d из %d (осталось %d), неделя %d %% ≥ %d %%, потолок %d %%' % (allow['tg'], used + 1, allow['n'], allow['n'] - used - 1, p7, WEEK_STOP, hard)
    if p5 >= FIVE_PAUSE and r5 > now:
        return 'pause', '5 часов %d %% ≥ %d %%: пауза до сброса %s' % (p5, FIVE_PAUSE, time.strftime('%H:%M UTC', time.gmtime(r5))), int(r5 - now) + 30
    return 'ok', over, 0


def allow_used(allow):
    """сколько листов этого допуска (тот же TG и даты) уже записано в calls.jsonl — при перезапуске пачки счёт не обнуляется (два запуска ≠ 2N)"""
    n = 0
    try:
        with open(A + '/calls.jsonl', encoding='utf-8') as f:
            for ln in f:
                try:
                    n += 1 if json.loads(ln).get('допуск_ключ') == allow['key'] else 0
                except ValueError:
                    continue
    except OSError:
        pass
    return n


def gate_reserve(nums, now=None):
    """gate + резервирование листа допуска под lock (потоки пачки не выдадут N+1). → (вердикт, причина, пауза, grant|None); grant — поля для строки журнала листа.
    Резерв снимается в _log, когда строка листа записана (до этого учитывается в STATE['allow_pending'])."""
    with lock:
        allow = week_allow()
        used = allow_used(allow) + STATE.get('allow_pending', 0) if allow else 0
        v, why, secs = gate(nums, now, allow, used)
        grant = None
        if v == 'ok' and why:
            STATE['allow_pending'] = STATE.get('allow_pending', 0) + 1
            grant = {'допуск': why, 'допуск_ключ': allow['key'], 'допуск_n': allow['n'], 'допуск_лист': used + 1, 'допуск_осталось': allow['n'] - used - 1}
        return v, why, secs, grant


def _log(rec):
    with lock:
        with open(A + '/calls.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        if rec.get('допуск_ключ'):                    # лист допуска записан — теперь его считает allow_used по файлу, резерв снимаем
            STATE['allow_pending'] = max(0, STATE.get('allow_pending', 0) - 1)


def _stop(reason):
    """Стоп всей пачки: STOP-файл рядом с выходом (его читает run_sb100 перед каждым вызовом) с причиной."""
    if OUT:
        with open(OUT + '/STOP', 'w', encoding='utf-8') as f:
            f.write('%s · %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()), reason))


def _run(cmd, msg, env):
    return subprocess.run(cmd, input=json.dumps(msg, ensure_ascii=False) + '\n', capture_output=True, text=True, cwd=CWD, env=env, timeout=TIMEOUT)


def preflight(out_dir, effort=None):
    """До первого листа: программа есть, версия, вход по подписке, накладные токены контрольного вызова БЕЗ картинки (тысячи = окружение протекло),
    счётчик лимита читается. Итог — <out>/agent-preflight.json; любая беда — AgentStop с причиной."""
    claude = find_claude()
    os.makedirs(CWD, exist_ok=True)
    env, removed = clean_env()
    try:
        ver = subprocess.run([claude, '--version'], capture_output=True, text=True, timeout=60, env=env).stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        raise AgentStop('программа claude не запускается: %s' % e)
    nums = limit_numbers()
    week_hard()
    allow = week_allow()                              # битая строка допуска/потолка — стоп до первого листа
    p = _run(build_cmd(claude, effort), build_message_text('Reply with the single word: OK'), env)
    parsed = parse_stream(p.stdout)
    res, init = parsed['result'], parsed['init']
    if p.returncode != 0 or not res or res.get('is_error'):
        raise AgentStop('контрольный вызов не удался (rc=%s): %s %s' % (p.returncode, (res or {}).get('result', '')[:200], p.stderr[:200]))
    src = (init or {}).get('apiKeySource')
    if src != 'none':
        raise AgentStop('вход НЕ по подписке: apiKeySource=%r (ждали none) — платный ключ подхвачен, пачку не начинаю' % src)
    u = res.get('usage') or {}
    over = (u.get('input_tokens') or 0) + (u.get('cache_creation_input_tokens') or 0) + (u.get('cache_read_input_tokens') or 0)
    if over > OVERHEAD_MAX:
        raise AgentStop('накладные входные токены %d > %d: в запрос попало наше окружение (правила/память) — листы не запускаю' % (over, OVERHEAD_MAX))
    info = {'вход': 'подписка', 'apiKeySource': src, 'версия': ver, 'путь': claude, 'модель': MODEL, 'усилие': effort or EFFORT, 'системный запрос': SYSTEM,
            'накладные входные токены': over, 'убраны из окружения': removed, 'пустая папка': CWD, 'лимит п5/сброс5/п7/сброс7': list(nums),
            'ключи': build_cmd('claude', effort)[1:], 'допуск недели': allow, 'жёсткий потолок недели %': week_hard()}
    info['усилие'] = effort or EFFORT
    STATE.update(version=ver, removed=removed, preflight=info)
    os.makedirs(out_dir, exist_ok=True)
    with open(out_dir + '/agent-preflight.json', 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    return info


def build_message_text(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]}}


def refuse_no_addendum(cid, key):
    """Лист без dlya_llm: отказ БЕЗ вызова (запрос со словом «None» — другой вход, чем на стенде, числа несравнимы)."""
    rec = {'id': cid, 'model': MODEL, 'at': time.strftime('%H:%M:%S'), 'ok': False, 'usd': 0.0, 'sec': 0.0, 'error': NO_ADDENDUM, 'called': False,
           'addendum': False}
    _log(rec)
    print(cid, key, 'ОТКАЗ без вызова:', NO_ADDENDUM, flush=True)
    return False


def one(cid, key, prompt, img):
    """Тот же контракт, что vetka_a_run.one: True — ответ записан в <A>/raw/<key>/<cid>.txt; False — отказ (причина в calls.jsonl). Платного нет."""
    t0 = time.time()
    rec = {'id': cid, 'model': MODEL, 'at': time.strftime('%H:%M:%S'), 'effort': EFFORT, 'вход': 'подписка', 'called': True, 'addendum': True,
           'text_sha256': sha(prompt), 'img_sha256': sha(img), 'img_bytes': len(img), 'version': STATE['version'], 'usd': 0.0}
    try:
        claude = find_claude()
        while True:                                   # счётчик лимита перед каждым листом
            if OUT and os.path.exists(OUT + '/STOP'):
                raise AgentStop('файл STOP')
            nums = limit_numbers()
            try:
                v, why, secs, grant = gate_reserve(nums)
            except AgentStop as e:                    # битая OPUS_AGENT_WEEK_ALLOW / _HARD: стоп ВСЕЙ пачки с причиной (STOP-файл), а не отказ каждого листа по очереди
                _stop(str(e))
                raise
            if v == 'stop':
                _stop(why)
                raise AgentStop('стоп пачки: ' + why)
            if v == 'pause':
                rec.setdefault('pauses', []).append(why)
                print(cid, key, why, flush=True)
                sleep(min(secs, 600))                 # короткими отрезками: STOP-файл и счётчик перечитываются
                continue
            if grant:                                 # разовый допуск сверх недельного стопа: лист записан с причиной (TG, номер листа, сколько осталось)
                rec.update(grant)
                print(cid, key, why, flush=True)
            break
        env, _ = clean_env()
        msg = build_message(prompt, img)
        last = None
        for attempt in (1, 2):
            try:
                p = _run(build_cmd(claude), msg, env)
                parsed = parse_stream(p.stdout)
                rec['rc'] = p.returncode
            except subprocess.TimeoutExpired:
                last = 'таймаут %d с' % TIMEOUT
                continue
            hit = limit_hit(parsed)
            if hit:                                   # лимит подписки: стоп всей пачки, повторов нет
                _stop(hit)
                raise AgentStop('лимит подписки: ' + hit)
            res = parsed['result']
            if not res and LIMIT_RX.search(p.stderr or ''):   # программа оборвалась с текстом про лимит на stderr
                _stop('stderr про лимит: ' + (p.stderr or '')[:200])
                raise AgentStop('лимит подписки (stderr): ' + (p.stderr or '')[:200])
            if p.returncode != 0 or not res or res.get('is_error'):
                last = 'сбой программы rc=%s: %s' % (p.returncode, ((res or {}).get('result') or p.stderr or 'нет result')[:200])
                continue
            u = res.get('usage') or {}
            rec.update(sec=round(time.time() - t0, 1), finish=res.get('stop_reason'), usd_list=round(res.get('total_cost_usd') or 0.0, 5),
                       tokens_in=(u.get('input_tokens') or 0) + (u.get('cache_creation_input_tokens') or 0) + (u.get('cache_read_input_tokens') or 0),
                       tokens_out=u.get('output_tokens'), thinking_tokens=(u.get('output_tokens_details') or {}).get('thinking_tokens'), usage=u, attempts=attempt)
            raw = res.get('result') or ''
            rec['chars'] = len(raw)
            if not raw.strip():
                rec.update(ok=False, error='пустой ответ')
            elif res.get('stop_reason') == 'refusal':
                rec.update(ok=False, error='модель отказалась отвечать: ' + raw[:200])
            elif res.get('stop_reason') == 'max_tokens':
                rec.update(ok=False, error='обрыв по длине (max_tokens)')
            else:
                os.makedirs('%s/raw/%s' % (A, key), exist_ok=True)
                with open('%s/raw/%s/%s.txt' % (A, key, cid), 'w', encoding='utf-8') as f:
                    f.write(raw)
                rec['ok'] = True
            break
        else:
            rec.update(sec=round(time.time() - t0, 1), ok=False, error=last, attempts=2)
    except AgentStop as e:
        rec.update(sec=round(time.time() - t0, 1), ok=False, error=str(e), stop=True)
    except BaseException as e:  # noqa: BLE001 — сбой записываем, пачку не роняем молча
        rec.update(sec=round(time.time() - t0, 1), ok=False, error='%s: %s' % (type(e).__name__, str(e)[:300]))
    with lock:                                        # три отказа ВЫЗОВОВ подряд — стоп пачки (отказ без вызова «нет добавки» сюда не входит)
        STATE['fails'] = 0 if rec['ok'] else STATE.get('fails', 0) + 1
        if not rec['ok'] and STATE['fails'] >= MAX_FAILS and not rec.get('stop'):
            rec['error'] = '%s · %d отказа подряд — стоп пачки' % (rec.get('error'), STATE['fails'])
            _stop('%d отказа подряд' % STATE['fails'])
    _log(rec)
    print(cid, key, 'ok' if rec['ok'] else 'ОТКАЗ', rec.get('finish') or '', 'агент (подписка, $0)', rec.get('error', ''), flush=True)
    return rec['ok']


def spent_total():
    return 0.0


def set_effort(effort):
    """Усилие рассуждения на всю пачку; не из списка `claude --effort` — AgentStop с причиной (а не молчаливое «low»)."""
    global EFFORT
    if effort not in EFFORTS:
        raise AgentStop('усилие %r не из %s' % (effort, ', '.join(EFFORTS)))
    EFFORT = effort
    return EFFORT


def paid_think(calls_path, sids, suffix='__b'):
    """Рассуждения платного Opus по листам: sid → reasoning_tokens из журнала платной стороны (calls.jsonl, usage.completion_tokens_details). Берём только
    успешные вызовы Opus по ТЕМ ЖЕ листам (id = <лист>__b), при повторах — последний. Нет файла → None (не число): «не меряется»."""
    if not calls_path or not os.path.exists(calls_path):
        return None
    want = set('%s%s' % (s, suffix) for s in sids)
    out = {}
    for ln in open(calls_path, encoding='utf-8'):
        if not ln.strip():
            continue
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get('ok') and r.get('id') in want and 'opus' in str(r.get('model', '')).lower():
            n = ((r.get('usage') or {}).get('completion_tokens_details') or {}).get('reasoning_tokens')
            if isinstance(n, (int, float)):
                out[r['id'][:-len(suffix)]] = n
    return out


def effort_line(rows, paid=None):
    """Строка шапки таблицы: усилие и расхождение числом — рассуждений на лист у агента против платного. Платное — НЕ константа: paid = paid_think(...) по тем же
    листам (None/пусто → «не меряется: нет журнала»). Сравнение — по общим листам; среднее агента по всем его листам — рядом. rows — строки calls.jsonl агента."""
    ag = {}
    for r in rows:
        if r.get('ok') and isinstance(r.get('thinking_tokens'), (int, float)) and str(r.get('id', '')).endswith('__b'):
            ag[r['id'][:-3]] = r['thinking_tokens']
    if not ag:
        return 'усилие %s; рассуждений на лист: агент нет данных (ни одного успешного вызова) / платный %s' % (
            EFFORT, 'не меряется: нет журнала' if not paid else 'не сравнить')
    m_all = round(sum(ag.values()) / len(ag))
    if not paid:
        return 'усилие %s; рассуждений на лист: агент %d (по %d листам) / платный не меряется: нет журнала' % (EFFORT, m_all, len(ag))
    common = sorted(set(ag) & set(paid))
    if not common:
        return 'усилие %s; рассуждений на лист: агент %d (по %d листам) / платный не меряется: в журнале нет этих листов' % (EFFORT, m_all, len(ag))
    return 'усилие %s; рассуждений на лист: агент %d / платный %d (по %d общим листам из %d; агент по всем %d листам — %d)' % (
        EFFORT, round(sum(ag[s] for s in common) / len(common)), round(sum(paid[s] for s in common) / len(common)), len(common), len(ag), len(ag), m_all)


K_OK = 'верно (проверено И легло)'
K_OK_NOLAID = 'проверено, но не легло/частично/не проверено'
K_PART = 'проверено частично (только с объявлением)'
K_BELL = 'звонок'
K_OTHER = 'отказ/прочее'
VERDICT_OK = re.compile(r'^проверено(\s*\(справка:[^)]*\))?\s*$')    # вердикт РОВНО «проверено» (справка в скобках — можно)


def outcome_of(verdict, overlay_status):
    """Исход одного листа — по ВЕРДИКТУ сторожа, не по подстроке: «проверено частично …» не равно «проверено» (подписей не хватило, часть проверок не работала)."""
    v = (verdict or '').strip()
    if VERDICT_OK.match(v):
        return K_OK if overlay_status == 'легло' else K_OK_NOLAID
    if v.startswith('проверено частично'):
        return K_PART
    if v.startswith('звонок'):
        return K_BELL
    return K_OTHER


def count_outcomes(rows):
    """Исходы шага Б. «Верно» = вердикт РОВНО «проверено» (со справкой или без) И наложение «легло»; «проверено частично …» — отдельной строкой, в «верно» не идёт.
    rows — строки таблицы run_sb100: {'opus': вердикт, 'overlay': {'overlay_status': …}}."""
    c = {'всего': 0, K_OK: 0, K_OK_NOLAID: 0, K_PART: 0, K_BELL: 0, K_OTHER: 0}
    for r in rows:
        c['всего'] += 1
        c[outcome_of(r.get('opus'), (r.get('overlay') or {}).get('overlay_status'))] += 1
    return c


def outcomes_line(rows):
    c = count_outcomes(rows)
    return 'исходы: ' + ' · '.join('%s %d' % (k, v) for k, v in c.items())


def read_table_tsv(path):
    """Строки готового прогона из table.tsv → [{'лист','opus','overlay':{'overlay_status'}}]. Нет нужных колонок — AgentStop (не молчаливый нуль)."""
    lines = [ln.rstrip('\n') for ln in open(path, encoding='utf-8') if ln.strip() and not ln.startswith('#')]
    if not lines:
        raise AgentStop('table.tsv пуст: %s' % path)
    head = lines[0].split('\t')
    need = ('лист', 'Opus проверено/звонок', 'наложение (Opus)')
    miss = [n for n in need if n not in head]
    if miss:
        raise AgentStop('в table.tsv нет колонок %s: %s' % (miss, path))
    ix = [head.index(n) for n in need]
    rows = []
    for ln in lines[1:]:
        f = ln.split('\t')
        if len(f) <= max(ix):
            raise AgentStop('короткая строка table.tsv (%d полей из %d): %s' % (len(f), len(head), ln[:80]))
        rows.append({'лист': f[ix[0]], 'opus': f[ix[1]], 'overlay': {'overlay_status': f[ix[2]]}})
    return rows


def recount(run_dir, out_dir):
    """ПЕРЕСЧЁТ исходов готового прогона по сохранённой таблице (вердикты сторожа уже в table.tsv): моделей и агента НЕ зовёт, сторож не гоняет.
    Пишет НОВУЮ папку out_dir (table.md с новой строкой исходов, iskhody.tsv, iskhody.json); исходный прогон не трогает; непустая out_dir или out_dir внутри run_dir — отказ."""
    run_dir = os.path.abspath(os.path.expanduser(run_dir))
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    if out_dir == run_dir or out_dir.startswith(run_dir + os.sep):
        raise AgentStop('папка пересчёта не должна быть внутри прогона (чужие файлы не перезаписываем): %s' % out_dir)
    if os.path.exists(out_dir) and os.listdir(out_dir):
        raise AgentStop('папка пересчёта не пуста — отказ, ничего не перезаписываю: %s' % out_dir)
    tsv = run_dir + '/table.tsv'
    rows = read_table_tsv(tsv)
    c = count_outcomes(rows)
    old_ok = sum(1 for r in rows if (r['opus'] or '').startswith('проверено') and r['overlay']['overlay_status'] == 'легло')   # прежний счёт (startswith) — для «было→стало»
    os.makedirs(out_dir, exist_ok=True)
    line = '**' + outcomes_line(rows) + '**'
    note = ('**ПЕРЕСЧЁТ исходов (T-176, правка Fable 27.11): вердикты из table.tsv прогона %s (sha256 %s); моделей и агента не вызывали, сторож не гоняли; '
            'прежний счёт по подстроке «проверено» давал «верно» %d, по вердикту РОВНО «проверено» — %d, «проверено частично» отдельно — %d**' % (
                run_dir, hashlib.sha256(open(tsv, 'rb').read()).hexdigest()[:16], old_ok, c[K_OK], c[K_PART]))
    md_p = run_dir + '/table.md'
    md = open(md_p, encoding='utf-8').read().splitlines() if os.path.exists(md_p) else []
    res, done = [], False
    for ln in md:
        if ln.startswith('**исходы:'):
            res.append(line)
            done = True
        else:
            res.append(ln)
    if not done:
        res += ['', line]
    with open(out_dir + '/table.md', 'w', encoding='utf-8') as f:
        f.write(note + '\n\n' + '\n'.join(res) + '\n')
    with open(out_dir + '/iskhody.tsv', 'w', encoding='utf-8') as f:
        f.write('лист\tвердикт\tналожение\tисход\n')
        for r in rows:
            f.write('%s\t%s\t%s\t%s\n' % (r['лист'], r['opus'], r['overlay']['overlay_status'], outcome_of(r['opus'], r['overlay']['overlay_status'])))
    with open(out_dir + '/iskhody.json', 'w', encoding='utf-8') as f:
        json.dump({'прогон': run_dir, 'листов': len(rows), 'исходы': c, 'верно_по_старому_startswith': old_ok}, f, ensure_ascii=False, indent=1)
    return c, old_ok


def labels5_budget(arg_cap, total_cap, spent_models=0.0):
    """Потолок шага подписей labels5 при агенте: не больше LABELS5_CAP_MAX ($3) и не больше остатка общего потолка; больше — отказ с причиной."""
    if arg_cap is None:
        arg_cap = LABELS5_CAP_MAX
    if arg_cap > LABELS5_CAP_MAX + 1e-9:
        raise AgentStop('--labels5-cap %.2f больше допустимых $%.2f при агенте — отказ' % (arg_cap, LABELS5_CAP_MAX))
    return min(arg_cap, total_cap - spent_models)


def labels5_may_call(spent, budget):
    """Можно ли ещё звать labels5: потрачено + худший вызов ≤ потолка; иначе — причина остановки (строка), можно — None."""
    if spent + LABELS5_WORST > budget:
        return 'подписи: потолок шага $%.2f (потрачено $%.3f)' % (budget, spent)
    return None


def save_input_jpegs(im, a_dir, sid, variants=('b', 'd')):
    """Входной JPEG листа под обоими именами (<лист>__b.jpg и __d.jpg: тот же файл; q92): замороженный сторож читает __d.jpg, хотя GPT при агенте не зовём.
    im — PIL-картинка (уже без прозрачности). Возвращает список записанных путей; нет ни одного — AgentStop."""
    os.makedirs(a_dir + '/input', exist_ok=True)
    out = []
    for v in variants:
        p = '%s/input/%s__%s.jpg' % (a_dir, sid, v)
        im.convert('RGB').save(p, 'JPEG', quality=92)
        out.append(p)
    if not out:
        raise AgentStop('ни одной входной картинки листа %s не сохранено' % sid)
    return out


def attach(R, out_dir):
    """Подмена платного читателя в модуле vetka_a_run (R): R.one = one. Платный путь не вызывается; всё, что R.one писал, пишем сюда же."""
    global A, OUT
    A = R.A
    OUT = out_dir
    R.one = one
    R.spent_total = spent_total
    return one


def jobs_for(reader, jobs):
    """Читатель «агент» заменяет ТОЛЬКО Opus: платный GPT-вызов не делаем (денег не тратим). «платный» — jobs без изменений."""
    return tuple(j for j in jobs if j[0] == 'opus') if reader == 'agent' else jobs


def has_addendum(plans, sid):
    try:
        d = json.load(open('%s/%s/listing.json' % (plans, sid), encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return bool(((d.get('obyavlenie') or {}).get('dlya_llm') or '').strip())


if __name__ == '__main__':
    # пересчёт исходов готового прогона (моделей не зовёт): python -I opus_agent.py --recount <папка прогона> --out <НОВАЯ папка>
    av = sys.argv[1:]
    if len(av) == 4 and av[0] == '--recount' and av[2] == '--out':
        try:
            cnt, old = recount(av[1], av[3])
        except AgentStop as e:
            print('отказ: %s' % e)
            sys.exit(2)
        print('листов %d · было по подстроке: верно %d → стало: верно %d, проверено частично %d, проверено но не легло %d, звонок %d, отказ/прочее %d · выход %s' % (
            cnt['всего'], old, cnt[K_OK], cnt[K_PART], cnt[K_OK_NOLAID], cnt[K_BELL], cnt[K_OTHER], av[3]))
    else:
        print('использование: opus_agent.py --recount <папка прогона> --out <новая папка>')
        sys.exit(2)
