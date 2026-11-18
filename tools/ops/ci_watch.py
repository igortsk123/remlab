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

    python3 tools/ops/ci_watch.py              один обход (крон pakardev */5; журнал ~/remlab-logs/ci-watch.log)
    python3 tools/ops/ci_watch.py --status     что сторож помнит и что бы сделал (без отправки)
    CI_WATCH_PROBE=1 python3 -c "import sys; sys.path.insert(0,'tools/ops'); import ci_watch as W; print([W.Real().tmux(m, 'x') for m in ('pakardev','common','algor')])"
                                               проба маршрута к окнам директоров без печати текста
    python3 tools/ops/ci_watch.py --selftest   на фикстурах, без сети/Telegram/tmux/ssh (шаг CI gate)

Telegram — готовый `tools/scout/alert.sh` (ключи в `.env.alert` рядом, вне git; здесь не читаются). Состояние —
`CI_WATCH_STATE` или `~/.local/state/ci-watch/state.json`. Подмена для проверок: `CI_STATUS_FIXTURE`, `CI_STATUS_NOW`, `CI_WATCH_DRY=1`
(отправки не делаются, только список «что отправили»)."""
import json
import os
import re
import shlex
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


def tick(actor, plan_text: str, now: datetime, repo: str, st_path: str) -> int:
    """Один обход. 0 — обработано; 2 — API не ответил (молча, состояние не тронуто)."""
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
        st['tmux_done'] = bool(machine) and actor.tmux(machine, text)

    if v['state'] == 'red':
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
            text = f'❗ CI красный: {what} · коммит {sha} · с {_london(since_iso)} (прогонов подряд {v["n"]}). Выкладка стоит, пока красный.'
            if actor.tg(text):
                st.update(state='red', red_key=key, since=since_iso, last_alert=now.timestamp(), last_sha=sha, last_text=text)
                push(text)
            else:
                st.update(state='red', red_key=key, since=since_iso, last_alert=0)   # Telegram не ушёл — повтор в следующий обход
        elif red_sec >= REPEAT_AFTER_MIN * 60 and now.timestamp() - float(st.get('last_alert') or 0) >= REPEAT_EVERY_SEC:
            text = f'❗ CI всё ещё красный {_dur(red_sec)}: {what} · коммит {sha} · с {_london(since_iso)}.'
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
    rc = tick(actor, plan_text, now, CS.repo_here(), sp)
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
    print(f'ci_watch selftest: ошибок {len(bad)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
