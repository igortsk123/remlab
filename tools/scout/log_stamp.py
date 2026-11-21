"""ЖУРНАЛ СЕРВИСА КАДРОВ С ВРЕМЕНЕМ И НОМЕРОМ ЗАДАНИЯ (T-20261118-22/8, tour-speed-01).

Каждая строка `dev-render.log` — `<ISO-время> [<задание>|<тур>] текст`; вне задания — `[-|-]`. Время местное с поясом (на DEV — UTC).
Зачем: «все фото» тура по журналу не измерить, пока строки без времени (замер 21.11 шёл по косвенным данным); разбор — `tour_timing.py`.

Два слоя (оба только stdlib, сервис не зависит от них):
1. питоновый — `sys.stdout`/`sys.stderr` заменяются построчным штампером; номер задания/тура берётся из контекста потока (`context(job=…, tour=…)`: очередь
   рендера ставит его на время задания, поток заготовок тура — на время постановки);
2. дескрипторный — то, что пишут напрямую дочерние процессы (Blender, node) и C-код (`faulthandler`), идёт в трубу; поток-читатель штампует такие строки `[-|-]`
   и пишет в исходный файл журнала. Читатель упал — дескрипторы возвращаются как были (журнал не блокируется).
Выключатель — `LOG_STAMP=0` (прежний журнал без времени). Вход — `install()` один раз в начале процесса сервиса."""
import contextlib
import datetime
import os
import re
import sys
import threading

STAMP_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2} \[[^\]|\s]*\|[^\]|\s]*\] ')
_ctx = threading.local()
_lock = threading.Lock()
_state: dict = {}


def now_iso(ts: float | None = None) -> str:
    dt = datetime.datetime.fromtimestamp(ts) if ts is not None else datetime.datetime.now()
    return dt.astimezone().isoformat(timespec='seconds')


def _clean(v) -> str:
    s = re.sub(r'[\s\[\]|]+', '_', str(v or '').strip())
    return s[:80] or '-'


@contextlib.contextmanager
def context(job=None, tour=None):
    """На время блока строки потока получают номер задания и тура. Вложенность — внутренний перекрывает; пустое значение — прежнее."""
    prev = getattr(_ctx, 'v', ('-', '-'))
    _ctx.v = (_clean(job) if job else prev[0], _clean(tour) if tour else prev[1])
    try:
        yield
    finally:
        _ctx.v = prev


def tag() -> str:
    j, t = getattr(_ctx, 'v', ('-', '-'))
    return f'[{j}|{t}]'


def stamp_line(line: str, ts: float | None = None) -> str:
    """Строка без перевода строки → со штампом (уже со штампом — как есть)."""
    if STAMP_RE.match(line):
        return line
    return f'{now_iso(ts)} {tag()} {line}'


class Stamper:
    """Файлоподобная обёртка потока: полные строки получают штамп и уходят в `sink(bytes)` целиком; хвост без перевода строки ждёт в буфере потока."""

    def __init__(self, sink, name: str = 'stdout'):
        self.sink, self.name = sink, name
        self._bufs: dict = {}
        self.encoding, self.errors = 'utf-8', 'replace'

    def write(self, s) -> int:
        if not s:
            return 0
        if isinstance(s, bytes):
            s = s.decode('utf-8', 'replace')
        tid = threading.get_ident()
        buf = self._bufs.pop(tid, '') + s
        if '\n' not in buf:
            self._bufs[tid] = buf
            return len(s)
        *lines, rest = buf.split('\n')
        if rest:
            self._bufs[tid] = rest
        self.sink(''.join(stamp_line(ln) + '\n' for ln in lines).encode('utf-8', 'replace'))
        return len(s)

    def writelines(self, lines) -> None:
        for ln in lines:
            self.write(ln)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise OSError('Stamper: нет дескриптора')

    def writable(self) -> bool:
        return True


def _pump(rfd: int, out_fd: int, restore) -> None:
    """Читатель трубы: сырые строки детей и C-кода → со штампом `[-|-]`, уже проштампованные пишет как есть."""
    buf = b''
    try:
        while True:
            chunk = os.read(rfd, 65536)
            if not chunk:
                break
            buf += chunk
            *lines, buf = buf.split(b'\n')
            if lines:
                data = ''.join(stamp_line(ln.decode('utf-8', 'replace')) + '\n' for ln in lines).encode('utf-8', 'replace')
                with _lock:
                    os.write(out_fd, data)
        if buf:
            with _lock:
                os.write(out_fd, (stamp_line(buf.decode('utf-8', 'replace')) + '\n').encode('utf-8', 'replace'))
    except BaseException:  # noqa: BLE001 — читатель не должен остановить сервис: вернуть дескрипторы как были
        restore()


def install(env: dict | None = None, fd_capture: bool = True) -> bool:
    """Включить штампы для этого процесса. → True включено; False — выключено `LOG_STAMP=0`, уже включено или не получилось (журнал прежний)."""
    e = os.environ if env is None else env
    if str(e.get('LOG_STAMP', '1')) == '0' or _state.get('on'):
        return False
    try:
        out_fd = os.dup(1)
        err_fd = os.dup(2)

        def write_out(b: bytes) -> None:
            with _lock:
                os.write(out_fd, b)

        def write_err(b: bytes) -> None:
            with _lock:
                os.write(err_fd, b)

        sys.stdout.flush()
        sys.stderr.flush()
        _state.update(on=True, out_fd=out_fd, err_fd=err_fd, orig_out=sys.stdout, orig_err=sys.stderr)
        if fd_capture:
            rfd, wfd = os.pipe()

            def restore() -> None:
                try:
                    os.dup2(out_fd, 1)
                    os.dup2(err_fd, 2)
                except OSError:
                    pass
            os.dup2(wfd, 1)
            os.dup2(wfd, 2)
            os.close(wfd)
            _state.update(rfd=rfd, restore=restore)
            threading.Thread(target=_pump, args=(rfd, out_fd, restore), name='log-stamp-pump', daemon=True).start()
        sys.stdout = Stamper(write_out, 'stdout')
        sys.stderr = Stamper(write_err, 'stderr')
        return True
    except Exception:  # noqa: BLE001 — не вышло: журнал остаётся прежним
        _state.clear()
        return False
