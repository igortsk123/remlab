"""СТОРОЖ CI (T-20261118-20/8; владелец 18.11, TG 1851: «если GitHub проблема — надо узнавать сразу»).

17.11 18:18 → 18.11 13:10 «CI gate» был красным ~19 ч, и выкладка стояла: узнали из ночной сводки (`ci_status.py --digest`) и по следам.
Сторож зовётся кроном каждые 5 минут, смотрит последний завершённый прогон «CI gate» на main (публичный API, без токена — функции
`ci_status.py`) и ПЕРЕХОД состояния помнит в файле вне git:

  зелёный → красный   ОДНО сообщение владельцу в Telegram («CI красный: job: шаг, коммит, с какого времени по Лондону»)
                      + толчок в tmux окно действующего директора (машина — из строки «Директор: <машина> с …» шапки
                      `.memory_bank/plan-zadach.md`; окно ведущего remlab (pakardev/common — `<машина>:tg-remlab`, algor — `tg-remlab:claude`); чужая машина — по ssh, как ночной свод памяти)
  красный дольше 30 мин   повтор раз в час («CI всё ещё красный N ч: …»), не чаще
  красный → зелёный   одна строка «CI снова зелёный» (Telegram + толчок)
  API не ответил      МОЛЧА (код 2, строка в журнал крона) — это не тревога, состояние не меняется

ХВОСТ ОШИБКИ (T-20261119-103, владелец 19.11, TG 2109/2115: «чинить за минуты, а не 30 мин вслепую»). К первому сообщению и к часовому повтору сторож
добавляет выжимку `gh run view <id> --log-failed`: по каждому упавшему job (до 3) — «job: шаг» и последние ≤15 строк с `##[error]|Error|FAIL|Traceback|assert`
вместе со строкой вокруг (без меток времени, цвета и эха самого скрипта шага), весь хвост ≤1500 знаков, строки похожие на ключ/токен — `***`. Тот же хвост идёт
в толчок директору (в одну строку: перевод строки в tmux = Enter) и в журнал крона. gh читает логи ключом GitHub только на чтение (pakardev), его сторож не печатает.
Нет gh / нет ключа / gh упал / не ответил за 20 с → сообщение БЕЗ хвоста, как раньше, и строка в журнал «ci_watch: лог ошибки не получен: <причина>»; сторож не падает,
состояние и повторы не меняются. gh зовётся только когда сообщение уходит (не каждые 5 минут).

    python3 tools/ops/ci_watch.py              один обход (крон pakardev */5; журнал ~/remlab-logs/ci-watch.log)
    python3 tools/ops/ci_watch.py --status     что сторож помнит и что бы сделал (без отправки); при красном — и выжимка хвоста ошибки
    python3 tools/ops/ci_watch.py --log-of ID  выжимка хвоста для прогона ID (живой gh, только чтение) — сухая проба на прошедшем красном
    CI_WATCH_PROBE=1 python3 -c "import sys; sys.path.insert(0,'tools/ops'); import ci_watch as W; print([W.Real().tmux(m, 'x') for m in ('pakardev','common','algor')])"
                                               проба маршрута к окнам директоров без печати текста
    python3 tools/ops/ci_watch.py --selftest   на фикстурах, без сети/Telegram/tmux/ssh (шаг CI gate)

Telegram — готовый `tools/scout/alert.sh` (ключи в `.env.alert` рядом, вне git; здесь не читаются). Состояние —
`CI_WATCH_STATE` или `~/.local/state/ci-watch/state.json`. Подмена для проверок: `CI_STATUS_FIXTURE`, `CI_STATUS_NOW`, `CI_WATCH_DRY=1`
(отправки не делаются, только список «что отправили»). Подмена хвоста — файл `log-<id>.txt` рядом с runs.json (вывод `gh run view <id> --log-failed`)."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ci_status as CS  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
PLAN = os.path.join(REPO_ROOT, '.memory_bank', 'plan-zadach.md')
ALERT = os.path.join(REPO_ROOT, 'tools', 'scout', 'alert.sh')
LONDON = ZoneInfo('Europe/London')
REPEAT_AFTER_MIN = 30        # красный дольше этого — повторяем
REPEAT_EVERY_SEC = 3600      # …и не чаще раза в час
# машина директора → как достучаться до её tmux (вкладка ведущего remlab — `<сессия>:tg-remlab`)
HOSTS = {'pakardev': None, 'common': 'common@192.168.0.45', 'algor': 'algor@192.168.0.33'}
TMUX_WINDOW = {'pakardev': 'pakardev:tg-remlab', 'common': 'common:tg-remlab', 'algor': 'tg-remlab:claude'}
GH_TIMEOUT = 20              # сек на `gh run view --log-failed`; дольше — сообщение без хвоста
TAIL_MAX = 1500              # знаков на весь хвост ошибки (Telegram режет на 4000, толчок в окно — короче)
TAIL_LINES = 15              # строк на упавший шаг
TAIL_JOBS = 3                # упавших job в хвосте
LINE_MAX = 220               # знаков на строку
PUSH_MAX = 1800              # знаков в толчке директору

# ---- хвост ошибки из `gh run view --log-failed` -------------------------------------------------------------------
# строка вывода: `job<TAB>шаг<TAB>[BOM]2026-11-19T20:33:58.5Z текст`
_ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
_TS = re.compile(r'^\d{4}-\d\d-\d\dT[\d:.]+Z ?')
_HIT = re.compile(r'##\[error\]|Error|ERROR|FAIL|Traceback|[Aa]ssert')
_SECRET = [
    re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}'),
    re.compile(r'\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}'),
    re.compile(r'\bAKIA[0-9A-Z]{12,}'),
    re.compile(r'\bxox[abprs]-[A-Za-z0-9-]{10,}'),
    re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*'),
    re.compile(r'(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}'),
    re.compile(r'\b[0-9a-fA-F]{41,}\b'),                                                  # длинный hex (хэш 40 знаков — коммит git — оставляем)
    re.compile(r'\b(?![0-9a-f]{40}\b)(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{40,}\b'),  # длинная смесь букв и цифр — ключ
]
_SECRET_KV = re.compile(r'(?i)(\b[\w.-]*(?:token|secret|passw(?:or)?d|passwd|api[_-]?key|apikey|authorization|private[_-]?key)[\w.-]*\s*[=:]\s*)("[^"]*"|\'[^\']*\'|\S+)')


def mask(s: str) -> str:
    """Строки, похожие на ключ/токен/пароль, → `***` (имя переменной остаётся: видно, что за значение скрыто)."""
    s = _SECRET_KV.sub(lambda m: m.group(1) + '***', s)
    for rx in _SECRET:
        s = rx.sub('***', s)
    return s


def _noise(raw_body: str) -> bool:
    """Эхо самого скрипта шага (`##[group]Run …`, строки в цвете `[36;1m`), `shell:`/`env:` — не ошибка."""
    b = raw_body.lstrip()
    return b.startswith(('##[group]', '##[endgroup]', 'shell:', 'env:')) or '\x1b[36;1m' in raw_body


def excerpt(raw: str, max_chars: int = TAIL_MAX, max_lines: int = TAIL_LINES, max_jobs: int = TAIL_JOBS) -> str:
    """Вывод `gh run view --log-failed` → короткий хвост: «job: шаг» и последние ≤max_lines строк с ошибкой (+ строка вокруг), всё ≤max_chars знаков, секреты — `***`. '' — нечего показать."""
    groups: dict = {}
    for ln in (raw or '').splitlines():
        parts = ln.split('\t', 2)
        job, step, body = (parts[0], parts[1], parts[2]) if len(parts) == 3 else ('', '', ln)
        body = _TS.sub('', body.lstrip('﻿'), count=1)
        if _noise(body):
            continue
        body = _ANSI.sub('', body).strip()
        if not body:
            continue
        groups.setdefault((job.strip('﻿'), step), []).append(body)
    blocks = []
    for (job, step), lines in list(groups.items())[:max_jobs]:
        hits = [i for i, l in enumerate(lines) if _HIT.search(l)]
        if hits:
            keep = sorted({j for i in hits[-max_lines:] for j in (i - 1, i, i + 1) if 0 <= j < len(lines)})[-max_lines:]
        else:
            keep = list(range(max(0, len(lines) - 8), len(lines)))
        out, seen = [], set()
        for i in keep:
            l = mask(lines[i])[:LINE_MAX]
            core = l[len('##[error]'):] if l.startswith('##[error]') else l      # Actions дублирует трассу строками `##[error]…` — второй раз не берём
            core = core.strip()
            if core and core not in seen:
                seen.add(core)
                out.append(l)
        head = mask(f'{job}: {step}'.strip(': '))[:70]
        blocks.append((head, out))
    if not blocks:
        return ''
    more = len(groups) - len(blocks)
    tailnote = f'\n(и ещё упавших job: {more})' if more > 0 else ''
    share = max(300, (max_chars - len(tailnote) - len(blocks)) // len(blocks))      # знаков на «▸ заголовок + строки» одного job
    res = []
    for head, out in blocks:
        txt = '\n'.join(out)
        room = share - len(head) - 3
        if len(txt) > room:
            txt = '…' + txt[-(room - 1):]                         # хвост важнее начала
        res.append(f'▸ {head}\n{txt}')
    s = '\n'.join(res) + tailnote
    return s if len(s) <= max_chars else '…' + s[-(max_chars - 1):]


def _gh_failed_log(run_id, repo: str) -> str:
    """Вывод `gh run view <id> --log-failed` (только чтение; ключ — в конфиге gh). Нет gh/ключа/ответа → исключение с понятным текстом."""
    fx = os.environ.get('CI_STATUS_FIXTURE')
    if fx:
        with open(os.path.join(fx, f'log-{run_id}.txt'), encoding='utf-8') as f:
            return f.read()
    if not shutil.which('gh'):
        raise RuntimeError('gh не установлен')
    r = subprocess.run(['gh', 'run', 'view', str(run_id), '--log-failed', '-R', repo], capture_output=True, text=True, errors='replace',
                       timeout=GH_TIMEOUT, env=dict(os.environ, GH_PROMPT_DISABLED='1', NO_COLOR='1'))
    if r.returncode != 0:
        err = (r.stderr or '').strip().splitlines()
        raise RuntimeError(f'gh завершился с кодом {r.returncode}: {mask(err[-1])[:100] if err else "без сообщения"}')
    return r.stdout


def _why(e: Exception) -> str:
    if isinstance(e, subprocess.TimeoutExpired):
        return f'gh ответил дольше {GH_TIMEOUT} с'
    if isinstance(e, FileNotFoundError):
        return 'нет файла/gh'
    if type(e) is RuntimeError:                                  # наш собственный текст («gh не установлен», «gh завершился с кодом …»)
        return mask(str(e))[:140]
    return mask(f'{type(e).__name__}: {e}')[:140]


def failed_tail(run_id, repo: str, runner=None) -> tuple:
    """(хвост ошибки, причина): хвост '' — не получен, причина — для журнала. Никогда не бросает: сторож от сбоя gh не падает."""
    try:
        raw = (runner or _gh_failed_log)(run_id, repo)
    except Exception as e:  # noqa: BLE001 — любой сбой gh = «без хвоста»
        return '', _why(e)
    t = excerpt(raw)
    return (t, '') if t else ('', 'в логе нет строк упавшего шага')


def flat(text: str) -> str:
    """Толчок в tmux: перевод строки = Enter (отправил бы кусок и начал следующий) → одной строкой."""
    return re.sub(r'\s*\n\s*', ' ⏎ ', text).strip()[:PUSH_MAX]


def state_path() -> str:
    return os.environ.get('CI_WATCH_STATE') or os.path.expanduser('~/.local/state/ci-watch/state.json')


def load_state(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: str, s: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.ci-watch-', dir=os.path.dirname(path))
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def director(plan_text: str) -> str:
    """Машина действующего директора — из строки «Директор: <машина> с …» шапки плана задач ('' — не нашли)."""
    m = re.search(r'^Директор:\s*([A-Za-zА-Яа-я0-9_-]+)', plan_text or '', re.M)
    return m.group(1).lower() if m else ''


class Real:
    """Настоящие отправки: Telegram — `tools/scout/alert.sh`, толчок — `tmux send-keys` (чужая машина — по ssh)."""

    def tg(self, text: str) -> bool:
        # 0 — доставлено; 2 — Telegram не настроен (alert.sh пишет громкий маркер-файл) — повторять нечего; 1 — не ответил → повтор в следующий обход
        try:
            return subprocess.run(['bash', ALERT, text], capture_output=True, text=True, timeout=240).returncode in (0, 2)
        except (OSError, subprocess.SubprocessError):
            return False

    def tmux(self, machine: str, text: str) -> bool:
        win = TMUX_WINDOW.get(machine)
        if not win or machine not in HOSTS:
            return False
        # печатать в окно с выбором («Enter to confirm»/«Esc to cancel») нельзя — клавиши выберут пункт; занятая сессия принимает — встанет в очередь
        sh = (f'p={shlex.quote(win)}; tmux list-panes -a -F "#{{session_name}}:#{{window_name}}" 2>/dev/null | grep -qxF "$p" || exit 4; '
              f'if tmux capture-pane -p -t "$p" | grep -qE "Enter to confirm|Esc to cancel"; then exit 3; fi; '
              + ('exit 0; ' if os.environ.get('CI_WATCH_PROBE') == '1' else '')      # проба маршрута: окно есть и свободно от выбора, текст НЕ печатаем
              + f'tmux send-keys -t "$p" -l {shlex.quote(text)} && tmux send-keys -t "$p" Enter')
        host = HOSTS[machine]
        cmd = ['bash', '-c', sh] if host is None else ['ssh', '-n', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host, sh]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


class Dry:
    def __init__(self, tg_ok: bool = True, tmux_ok: bool = True):
        self.sent, self.tg_ok, self.tmux_ok = [], tg_ok, tmux_ok

    def tg(self, text: str) -> bool:
        self.sent.append(('tg', text))
        return self.tg_ok

    def tmux(self, machine: str, text: str) -> bool:
        self.sent.append(('tmux:' + machine, text))
        return self.tmux_ok


def _london(iso: str) -> str:
    return CS._ts(iso).astimezone(LONDON).strftime('%d.%m %H:%M') + ' по Лондону'


def _dur(sec: float) -> str:
    return CS._hours(sec / 3600) if sec >= 3600 else f'{max(1, round(sec / 60))} мин'


def tick(actor, plan_text: str, now: datetime, repo: str, st_path: str, tail_fn=None, show_log: bool = False) -> int:
    """Один обход. 0 — обработано; 2 — API не ответил (молча, состояние не тронуто). `tail_fn(run_id, repo) → (хвост, причина)` — подмена gh в проверках; `show_log` — `--status`: показать выжимку."""
    tail_fn = tail_fn or failed_tail
    try:
        runs = CS.fetch(f'/repos/{repo}/actions/workflows/ci.yml/runs?branch=main&status=completed&per_page=100').get('workflow_runs') or []
    except Exception as e:  # noqa: BLE001 — сеть, лимит, плохой JSON: не тревога
        print(f'ci_watch: API не ответил ({type(e).__name__}: {str(e)[:80]}) — молчу, состояние прежнее')
        return 2
    v = CS.verdict(runs)
    if v['state'] == 'unknown':
        print(f'ci_watch: нет завершённых прогонов — {v.get("why", "")}; молчу')
        return 2
    st = load_state(st_path)
    old = st.get('state')
    sha = (v['last'].get('head_sha') or '')[:8]
    machine = director(plan_text)

    def push(text: str, key: str = '') -> None:
        """Толчок в окно директора: Telegram уже ушёл; не принято (в окне выбор, ssh) — повторяем в следующие обходы, пока красный."""
        st['tmux_done'] = bool(machine) and actor.tmux(machine, flat(text))

    _tail: list = []

    def tail_block() -> str:
        """Хвост ошибки для сообщения: один вызов gh на обход; не получен — '' и строка в журнал (сообщение уйдёт как раньше)."""
        if not _tail:
            try:
                t, why = tail_fn(v['last']['id'], repo)
            except Exception as e:  # noqa: BLE001 — подмена/сбой: не роняем сторожа
                t, why = '', _why(e)
            if t:
                print(f'ci_watch: хвост ошибки (прогон {v["last"]["id"]}):\n{t}')
            else:
                print(f'ci_watch: лог ошибки не получен: {why}')
            _tail.append(f'\n\n📄 Хвост ошибки:\n{t}' if t else '')
        return _tail[0]

    if v['state'] == 'red':
        if show_log:
            tail_block()
        steps = []
        try:
            steps = CS.failed_steps(CS.fetch(f'/repos/{repo}/actions/runs/{v["last"]["id"]}/jobs'))
        except Exception as e:  # noqa: BLE001
            steps = [f'шаги не прочитаны ({type(e).__name__})']
        what = '; '.join(steps) if steps else 'шаг не известен'
        first = v['first']
        since_iso = first['created_at']
        red_sec = (now - CS._ts(since_iso)).total_seconds()
        key = f'red:{first["id"]}'
        if old != 'red' or st.get('red_key') != key or not st.get('last_alert'):      # первое сообщение (или прошлое не дошло)
            text = f'❗ CI красный: {what} · коммит {sha} · с {_london(since_iso)} (прогонов подряд {v["n"]}). Выкладка стоит, пока красный.' + tail_block()
            if actor.tg(text):
                st.update(state='red', red_key=key, since=since_iso, last_alert=now.timestamp(), last_sha=sha, last_text=text)
                push(text)
            else:
                st.update(state='red', red_key=key, since=since_iso, last_alert=0)   # Telegram не ушёл — повтор в следующий обход
        elif red_sec >= REPEAT_AFTER_MIN * 60 and now.timestamp() - float(st.get('last_alert') or 0) >= REPEAT_EVERY_SEC:
            text = f'❗ CI всё ещё красный {_dur(red_sec)}: {what} · коммит {sha} · с {_london(since_iso)}.' + tail_block()
            if actor.tg(text):
                st['last_alert'] = now.timestamp()
                st['last_text'] = text
                push(text)
        elif not st.get('tmux_done') and st.get('last_text') and machine:      # в окне директора был выбор/ssh не прошёл — пробуем снова, пока красный
            push(st['last_text'])
        save_state(st_path, st)
        return 0

    # зелёный
    if old == 'red':
        dur = ''
        if st.get('since'):
            dur = f' (красный был {_dur((now - CS._ts(st["since"])).total_seconds())})'
        text = f'✅ CI снова зелёный · коммит {sha}{dur}.'
        if actor.tg(text):
            st.update(state='green', last_sha=sha)
            for k in ('red_key', 'since', 'last_alert'):
                st.pop(k, None)
            push(text)
    else:
        st.update(state='green', last_sha=sha)
    save_state(st_path, st)
    return 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    if '--log-of' in argv:      # выжимка для прогона по номеру (живой gh, только чтение): сухая проба без состояния и отправок
        i = argv.index('--log-of')
        if i + 1 >= len(argv) or not argv[i + 1].isdigit():
            print('ci_watch: --log-of <номер прогона>')
            return 64
        t, why = failed_tail(argv[i + 1], CS.repo_here())
        print(t if t else f'ci_watch: лог ошибки не получен: {why}')
        return 0 if t else 1
    now = CS._ts(os.environ['CI_STATUS_NOW']) if os.environ.get('CI_STATUS_NOW') else datetime.now(timezone.utc)
    try:
        with open(PLAN, encoding='utf-8') as f:
            plan_text = f.read(4000)
    except OSError:
        plan_text = ''
    sp = state_path()
    if '--status' in argv:      # «что бы сделал» — на копии состояния, настоящее не трогаем
        tmp = os.path.join(tempfile.mkdtemp(prefix='ci-watch-status-'), 'state.json')
        save_state(tmp, load_state(sp))
        sp = tmp
    actor = Dry() if (os.environ.get('CI_WATCH_DRY') == '1' or '--status' in argv) else Real()
    rc = tick(actor, plan_text, now, CS.repo_here(), sp, show_log='--status' in argv)
    if isinstance(actor, Dry):
        for kind, text in actor.sent:
            print(f'[сухо] {kind}: {text}')
        print('состояние:', json.dumps(load_state(sp), ensure_ascii=False))
    return rc


def _run(i, sha, concl, at, status='completed', name='CI gate'):
    return {'id': i, 'name': name, 'head_sha': sha * 5, 'status': status, 'conclusion': concl, 'created_at': at}


def _selftest() -> int:
    sys.path.insert(0, os.path.join(HERE, '..', 'scout'))
    import remlab_tmp
    remlab_tmp.use('ci-watch')
    bad = []

    def check(cond, msg, got=None):
        print(('OK   ' if cond else 'FAIL ') + msg + ('' if cond else f': {got!r}'))
        if not cond:
            bad.append(msg)

    d = tempfile.mkdtemp(prefix='ci-watch-')
    sp = os.path.join(d, 'state.json')
    os.environ['CI_STATUS_FIXTURE'] = d
    plan = 'x\nДиректор: common с 16.11 14:26 (подхват: …)\n'
    jobs = {'jobs': [{'name': 'planner', 'conclusion': 'failure', 'steps': [{'name': 'Run pytest', 'conclusion': 'failure'}]}]}

    def put(runs, js=None):
        with open(os.path.join(d, 'runs.json'), 'w', encoding='utf-8') as f:
            json.dump({'workflow_runs': runs}, f)
        for r in runs:
            with open(os.path.join(d, f'jobs-{r["id"]}.json'), 'w', encoding='utf-8') as f:
                json.dump(js or jobs, f)

    t0 = CS._ts('2026-11-18T12:00:00Z')

    def at(min_):
        return datetime.fromtimestamp(t0.timestamp() + min_ * 60, timezone.utc)

    green = _run(1, 'aaaa', 'success', '2026-11-18T11:00:00Z')
    # 1. первый обход, зелёный: тихо, состояние запомнено
    put([green])
    a = Dry()
    check(tick(a, plan, at(0), 'o/r', sp) == 0 and a.sent == [] and load_state(sp).get('state') == 'green', 'зелёный с первого обхода — тихо, состояние запомнено', (a.sent, load_state(sp)))
    # 2. зелёный → красный: одно сообщение в Telegram + толчок директору (common), текст: job: шаг, коммит, время по Лондону
    red = _run(2, 'bbbb', 'failure', '2026-11-18T12:00:00Z')
    put([red, green])
    a = Dry()
    tick(a, plan, at(1), 'o/r', sp)
    kinds = [k for k, _ in a.sent]
    check(kinds == ['tg', 'tmux:common'], 'зелёный → красный: Telegram и толчок в окно директора (common)', a.sent)
    txt = a.sent[0][1] if a.sent else ''
    check('CI красный' in txt and 'planner: Run pytest' in txt and 'коммит bbbbbbbb' in txt and 'с 18.11 12:00 по Лондону' in txt, 'текст: job: шаг, коммит, с какого времени по Лондону', txt)
    # 3. красный держится <30 мин — тишина; 4. ≥30 мин, но <1 ч от первого сообщения — тишина; 5. ≥1 ч — повтор раз
    for m_, want, name in ((10, 0, 'красный <30 мин — тишина'), (40, 0, 'красный ≥30 мин, но от сообщения <1 ч — тишина'), (62, 2, 'красный ≥1 ч от сообщения — повтор (Telegram+толчок)')):
        a = Dry()
        tick(a, plan, at(m_), 'o/r', sp)
        check(len(a.sent) == want, name, a.sent)
    check('всё ещё красный' in (a.sent[0][1] if a.sent else ''), 'повтор: «всё ещё красный N ч»', a.sent)
    a = Dry()
    tick(a, plan, at(70), 'o/r', sp)
    check(a.sent == [], 'после повтора до следующего часа — тишина', a.sent)
    # 6. новый красный коммит в той же полосе — НЕ новое сообщение
    put([_run(3, 'cccc', 'failure', '2026-11-18T13:00:00Z'), red, green])
    a = Dry()
    tick(a, plan, at(75), 'o/r', sp)
    check(a.sent == [], 'ещё один красный коммит в той же полосе — без нового сообщения', a.sent)
    # 7. красный → зелёный: одна строка; дальше тишина
    put([_run(4, 'dddd', 'success', '2026-11-18T13:20:00Z'), _run(3, 'cccc', 'failure', '2026-11-18T13:00:00Z'), red, green])
    a = Dry()
    tick(a, plan, at(95), 'o/r', sp)
    check([k for k, _ in a.sent] == ['tg', 'tmux:common'] and 'CI снова зелёный' in a.sent[0][1] and 'коммит dddddddd' in a.sent[0][1], 'красный → зелёный: одна строка «CI снова зелёный»', a.sent)
    a = Dry()
    tick(a, plan, at(100), 'o/r', sp)
    check(a.sent == [] and load_state(sp).get('state') == 'green', 'зелёный держится — тишина', a.sent)
    # 8. сбой API — молча, код 2, состояние прежнее
    with open(os.path.join(d, 'runs.json'), 'w', encoding='utf-8') as f:
        f.write('{не json')
    before = load_state(sp)
    a = Dry()
    check(tick(a, plan, at(105), 'o/r', sp) == 2 and a.sent == [] and load_state(sp) == before, 'API не ответил — код 2, молчим, состояние не тронуто', (a.sent, load_state(sp)))
    # 9. Telegram не ушёл — красный запоминается без отметки сообщения, следующий обход повторяет (и толчок директору — один раз на событие)
    sp2 = os.path.join(d, 'state2.json')
    put([_run(6, 'eeee', 'failure', '2026-11-18T12:00:00Z'), green])
    a = Dry(tg_ok=False)
    tick(a, plan, at(1), 'o/r', sp2)
    check([k for k, _ in a.sent] == ['tg'] and not load_state(sp2).get('last_alert'), 'Telegram не ушёл — следующий обход повторит, толчок без Telegram не шлём', (a.sent, load_state(sp2)))
    a = Dry()
    tick(a, plan, at(6), 'o/r', sp2)
    check([k for k, _ in a.sent] == ['tg', 'tmux:common'], 'повтор после сбоя Telegram: ушло сообщение и толчок', a.sent)
    sp4 = os.path.join(d, 'state4.json')
    put([_run(7, 'ffff', 'failure', '2026-11-18T12:00:00Z'), green])
    a = Dry(tmux_ok=False)
    tick(a, plan, at(1), 'o/r', sp4)
    a = Dry()
    tick(a, plan, at(6), 'o/r', sp4)
    check([k for k, _ in a.sent] == ['tmux:common'], 'в окне директора был выбор (толчок не прошёл) — следующий обход повторяет ТОЛЬКО толчок, без второго Telegram', a.sent)
    a = Dry()
    tick(a, plan, at(11), 'o/r', sp4)
    check(a.sent == [], 'толчок дошёл — дальше тишина', a.sent)
    # 10. директор: другие машины, нет строки, неизвестная машина
    check(director('Директор: pakardev с 12.11') == 'pakardev' and director('Директор: algor с 12.11') == 'algor' and director('нет строки') == '', 'машина директора из шапки плана', None)
    sp3 = os.path.join(d, 'state3.json')
    a = Dry()
    tick(a, 'без строки директора', at(1), 'o/r', sp3)
    check([k for k, _ in a.sent] == ['tg'], 'директор неизвестен — Telegram всё равно уходит, толчка нет', a.sent)
    # 11. Telegram-часть настоящего отправителя без сети: alert.sh в сухом режиме (текст — в stdout, без отправки)
    r = subprocess.run(['bash', ALERT, 'проверка сторожа CI'], capture_output=True, text=True, env=dict(os.environ, ALERT_DRY='1'))
    check(r.returncode == 0 and 'проверка сторожа CI' in r.stdout, 'alert.sh в сухом режиме — текст в stdout, код 0', (r.returncode, r.stdout))
    # 12. хвост ошибки (T-20261119-103): выжимка `gh run view --log-failed` на фикстуре формата gh (job<TAB>шаг<TAB>[BOM]время текст), без сети
    import contextlib
    import io
    sha40 = '3c44566b58f0f6b56d7b143fadbf89f2d506c636'
    pre = 'planner\tRun pytest\t'
    raw = '\n'.join([
        pre + '﻿2026-11-19T20:33:58.1Z ##[group]Run pytest -q',
        pre + '2026-11-19T20:33:58.2Z \x1b[36;1mpytest -q | grep -E "FAIL|Error"\x1b[0m',
        pre + '2026-11-19T20:33:58.3Z shell: /usr/bin/bash -e {0}',
        pre + '2026-11-19T20:33:59.0Z collected 12 items',
        pre + '2026-11-19T20:33:59.1Z tests/test_a.py::test_one PASSED',
        pre + '2026-11-19T20:33:59.2Z \x1b[31mFAILED\x1b[0m tests/test_b.py::test_two - AssertionError: 3 != 4',
        pre + '2026-11-19T20:33:59.3Z API_TOKEN=abcdef123456 and ghp_' + 'A' * 30 + ' leaked',
        pre + '2026-11-19T20:33:59.4Z Authorization: Bearer abcdefghijklmnop1234',
        pre + f'2026-11-19T20:33:59.5Z commit {sha40} digest ' + 'f' * 64,
        pre + '2026-11-19T20:33:59.6Z ##[error]Process completed with exit code 1.',
        'web\tBuild\t2026-11-19T20:34:00.0Z ok',
        'web\tBuild\t2026-11-19T20:34:00.1Z Error: Cannot find module x',
    ])
    ex = excerpt(raw)
    check('▸ planner: Run pytest' in ex and '▸ web: Build' in ex, 'хвост: заголовки «job: шаг» у каждого упавшего job', ex)
    check('2026-11-19T' not in ex and '\x1b' not in ex and 'grep -E' not in ex and '##[group]' not in ex and 'shell:' not in ex, 'хвост: без меток времени, цвета и эха самого скрипта шага', ex)
    check('AssertionError: 3 != 4' in ex and 'exit code 1' in ex and 'Cannot find module x' in ex and 'test_one PASSED' in ex and 'collected 12 items' not in ex,
          'хвост: строки с ошибкой и одна строка вокруг, дальние строки не берём', ex)
    check('abcdef123456' not in ex and 'ghp_' + 'A' * 30 not in ex and 'f' * 64 not in ex and 'abcdefghijklmnop1234' not in ex and '***' in ex and sha40 in ex,
          'хвост: ключ/токен/Bearer/длинный hex → ***, хэш коммита (40 знаков) остаётся', ex)
    big = '\n'.join(f'job\tstep\t2026-11-19T20:33:59.0Z Error number {i}: ' + 'x' * 90 for i in range(300))
    eb = excerpt(big)
    check(0 < len(eb) <= TAIL_MAX and eb.count('\n') <= TAIL_LINES and 'Error number 299' in eb and 'Error number 0:' not in eb, 'хвост: длина ≤ 1500 знаков, ≤ 15 строк на шаг, берутся ПОСЛЕДНИЕ', (len(eb), eb.count('\n')))
    dup = excerpt('j\ts\t2026-11-19T20:33:59.0Z RuntimeError: boom\nj\ts\t2026-11-19T20:33:59.1Z ##[error]RuntimeError: boom\nj\ts\t2026-11-19T20:33:59.2Z ##[error]Process completed with exit code 1.')
    check(dup.count('RuntimeError: boom') == 1 and 'Process completed with exit code 1' in dup, 'хвост: трасса и её копия `##[error]…` — один раз', dup)
    check(excerpt('') == '' and excerpt('job\tstep\t2026-11-19T20:33:59.0Z ##[group]Run x') == '' and excerpt('job\tstep\t2026-11-19T20:33:59.0Z a\njob\tstep\t2026-11-19T20:33:59.1Z b').count('\n') == 2,
          'хвост: пустой лог — пусто; без строк-ошибок — последние строки шага', None)
    # где хвост появляется: первое сообщение, часовой повтор, толчок (в одну строку), тишина — без обращения к gh
    calls = []

    def gh_ok(i, r):
        calls.append(i)
        return raw

    tf = lambda rid, repo_: failed_tail(rid, repo_, runner=gh_ok)  # noqa: E731
    sp5 = os.path.join(d, 'state5.json')
    put([_run(20, 'gggg', 'failure', '2026-11-18T12:00:00Z'), green])
    a = Dry()
    tick(a, plan, at(1), 'o/r', sp5, tail_fn=tf)
    tg_t = a.sent[0][1] if a.sent else ''
    tm_t = a.sent[1][1] if len(a.sent) > 1 else ''
    check(tg_t.startswith('❗ CI красный: planner: Run pytest') and '📄 Хвост ошибки:\n▸ planner: Run pytest' in tg_t and 'AssertionError: 3 != 4' in tg_t,
          'красный: в Telegram — прежняя строка, потом хвост ошибки', tg_t)
    check(tm_t and '\n' not in tm_t and ' ⏎ ' in tm_t and 'AssertionError: 3 != 4' in tm_t, 'толчок директору — тот же хвост, но одной строкой (перевод строки в tmux = Enter)', tm_t)
    a = Dry()
    tick(a, plan, at(10), 'o/r', sp5, tail_fn=tf)
    check(a.sent == [] and calls == [20], 'тишина — gh не зовём (один вызов на отправку, не каждые 5 минут)', (a.sent, calls))
    a = Dry()
    tick(a, plan, at(62), 'o/r', sp5, tail_fn=tf)
    check('всё ещё красный' in (a.sent[0][1] if a.sent else '') and 'Хвост ошибки' in a.sent[0][1] and calls == [20, 20], 'часовой повтор тоже с хвостом', a.sent)
    # сбои gh → сообщение как раньше, строка в журнал, сторож не падает, состояние верное
    def fail_with(exc):
        def run(i, r):
            raise exc
        return lambda rid, repo_: failed_tail(rid, repo_, runner=run)
    for exc, want in ((RuntimeError('gh не установлен'), 'gh не установлен'), (subprocess.TimeoutExpired('gh', GH_TIMEOUT), 'дольше 20 с'),
                      (RuntimeError('gh завершился с кодом 1: HTTP 401'), 'кодом 1: HTTP 401'), (ValueError('странное'), 'ValueError')):
        spx = os.path.join(d, 'statex.json')
        if os.path.exists(spx):
            os.remove(spx)
        a = Dry()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = tick(a, plan, at(1), 'o/r', spx, tail_fn=fail_with(exc))
        t0_ = a.sent[0][1] if a.sent else ''
        check(rc == 0 and 'Хвост' not in t0_ and t0_.startswith('❗ CI красный') and [k for k, _ in a.sent] == ['tg', 'tmux:common'] and f'лог ошибки не получен: ' in buf.getvalue() and want in buf.getvalue()
              and load_state(spx).get('state') == 'red' and load_state(spx).get('last_alert'), f'gh не дал лог ({want}): сообщение без хвоста, строка в журнал, состояние красный', (rc, a.sent, buf.getvalue()))
    a = Dry()
    buf = io.StringIO()
    spy = os.path.join(d, 'statey.json')
    with contextlib.redirect_stdout(buf):
        rc = tick(a, plan, at(1), 'o/r', spy, tail_fn=lambda rid, repo_: (_ for _ in ()).throw(OSError('boom')))
    check(rc == 0 and len(a.sent) == 2 and 'Хвост' not in a.sent[0][1], 'даже если сама подмена хвоста бросила исключение — сторож отправляет сообщение как раньше', (rc, a.sent))
    # настоящий путь: подмена-файл log-<id>.txt рядом с runs.json; и «нет gh» без подмены (PATH пустой)
    with open(os.path.join(d, 'log-21.txt'), 'w', encoding='utf-8') as f:
        f.write(raw)
    put([_run(21, 'hhhh', 'failure', '2026-11-18T12:00:00Z'), green])
    a = Dry()
    tick(a, plan, at(1), 'o/r', os.path.join(d, 'state6.json'))
    check('AssertionError: 3 != 4' in (a.sent[0][1] if a.sent else ''), 'по умолчанию (подмена CI_STATUS_FIXTURE): хвост из файла log-<id>.txt, без gh и сети', a.sent)
    old_fx, old_path = os.environ.pop('CI_STATUS_FIXTURE'), os.environ['PATH']
    try:
        os.environ['PATH'] = tempfile.mkdtemp(prefix='ci-watch-nopath-')
        got = failed_tail(1, 'o/r')
    finally:
        os.environ['PATH'], os.environ['CI_STATUS_FIXTURE'] = old_path, old_fx
    check(got == ('', 'gh не установлен'), 'нет gh в PATH → ("", «gh не установлен»), без исключения', got)
    # --status: при красном показывает выжимку, ничего не отправляя
    a = Dry()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        tick(a, plan, at(1), 'o/r', os.path.join(d, 'state6.json'), tail_fn=tf, show_log=True)
    check('▸ planner: Run pytest' in buf.getvalue() and a.sent == [], '--status при красном печатает выжимку, сообщений не шлёт', (buf.getvalue(), a.sent))
    print(f'ci_watch selftest: ошибок {len(bad)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
