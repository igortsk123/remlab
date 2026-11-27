"""T-20261127-176 — Opus-агент по подписке читает листы Этажей вместо платного Opus (план Fable `fable-1126/plan-t176.md`).

Точка входа `one(cid, key, prompt, img)` — та же, что у `vetka_a_run.one` (платный путь через шлюз): `run_sb100.py` подменяет `R.one` на неё
(`attach`), как подменяет заглушкой `--fake`. Вход байт в байт как у платного: текст (prompt0 + добавка из объявления) и JPEG листа; хеши — в журнал.
Вызов — `claude -p --input-format stream-json` (картинка блоком в сообщении), модель claude-opus-5-5, без инструментов, из пустой папки вне проекта,
без наших настроек/подключений/сессий, нейтральный системный запрос; `--bare` НЕ ставим (он отключает вход по подписке и идёт платным ключом).
Из окружения убраны ВСЕ имена с ключами/токенами/шлюзом (их список — в журнал); вход по подписке проверяется `apiKeySource` в ответе программы.

Что ни одно сообщение не молчит:
  • программы нет / не вошла в учётку / накладные входные токены контрольного вызова > 1000 / вход не по подписке → `AgentStop` до первого листа (`preflight`);
  • код возврата ≠ 0, таймаут 600 с — один повтор, снова сбой → отказ с причиной; пустой ответ, обрыв по длине, отказ модели — отказ без повтора;
  • лимит подписки — стоп ВСЕЙ пачки (файл `<out>/STOP` с временем сброса), повторов нет; пятичасовое окно ≥ 70 % — пауза до сброса, неделя ≥ 60 % — стоп;
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
import threading
import time

MODEL = 'claude-opus-5-5'
EFFORT = 'low'                                       # одно значение на всю пачку; платный вызов шёл без рассуждений — ближайшее к нему
SYSTEM = 'You are a helpful assistant.'              # нейтральный системный запрос (ваш пустой запрос программа не принимает как «нет»)
TIMEOUT = 600
MAX_OUT = '32000'                                    # как у платного пути (R.MAX_TOK = 32000 в run_sb100)
OVERHEAD_MAX = 1000                                  # накладные входные токены контрольного вызова: больше — окружение протекло
FIVE_PAUSE = 70                                      # % пятичасового окна: с этого — пауза до сброса
WEEK_STOP = 60                                       # % недели: с этого — стоп пачки
MAX_FAILS = 3                                        # отказов вызова подряд — стоп пачки
KEY_RX = re.compile(r'(API_?KEY|TOKEN|SECRET|GATEWAY|ANTHROPIC|OPENAI|VERCEL|GEMINI|GOOGLE_API|CREDENTIAL|PASSWORD)', re.I)
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


def gate(nums, now=None):
    """('ok'|'pause'|'stop', причина, секунд паузы). Неделя ≥ 60 % — стоп; пятичасовое ≥ 70 % — пауза до сброса окна."""
    p5, r5, p7, r7 = nums
    now = time.time() if now is None else now
    if p7 >= WEEK_STOP and r7 > now:
        return 'stop', 'неделя %d %% ≥ %d %% (сброс %s)' % (p7, WEEK_STOP, time.strftime('%d.%m %H:%M UTC', time.gmtime(r7))), 0
    if p5 >= FIVE_PAUSE and r5 > now:
        return 'pause', '5 часов %d %% ≥ %d %%: пауза до сброса %s' % (p5, FIVE_PAUSE, time.strftime('%H:%M UTC', time.gmtime(r5))), int(r5 - now) + 30
    return 'ok', '', 0


def _log(rec):
    with lock:
        with open(A + '/calls.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')


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
            'ключи': build_cmd('claude', effort)[1:]}
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
            v, why, secs = gate(limit_numbers())
            if v == 'stop':
                _stop(why)
                raise AgentStop('стоп пачки: ' + why)
            if v == 'pause':
                rec.setdefault('pauses', []).append(why)
                print(cid, key, why, flush=True)
                sleep(min(secs, 600))                 # короткими отрезками: STOP-файл и счётчик перечитываются
                continue
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
                       tokens_out=u.get('output_tokens'), usage=u, attempts=attempt)
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
