"""СТОРОЖ ЗАВИСШИХ ЗАКАЗОВ (T-20261118-10/9; прежний `faulthandler.dump_traceback_later` один на процесс: при двух параллельных POST отмена одного снимала таймер другого,
а второй вызов перезаписывал первый). Один фоновый поток смотрит словарь «заказ → время входа»; заказ, висящий дольше `limit` секунд, ОДИН раз получает в журнал строку
с возрастом и стеки всех потоков (что держит ответ). Вход/выход заказов друг другу не мешают. `limit <= 0` — выключено (ничего не запускается).
Проверка: python tools/scout/post_stall.py --selftest"""
import faulthandler
import itertools
import sys
import threading
import time


def _dump_stacks(header: str) -> None:
    print(header, file=sys.stderr, flush=True)
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)


class StallWatch:
    def __init__(self, limit: float, dump=_dump_stacks, clock=time.time, poll: float | None = None):
        self.limit, self.dump, self.clock = float(limit), dump, clock
        self.poll = poll if poll is not None else max(0.05, min(0.5, self.limit / 4)) if self.limit > 0 else 1.0
        self._lock = threading.Lock()
        self._orders: dict = {}          # токен → [время входа, поток, уже напечатано]
        self._ids = itertools.count(1)
        self._thread = None

    def enter(self, label: str = 'POST') -> int:
        """Заказ вошёл → токен для `leave`. При выключенном сторожe — 0 и ничего не делает."""
        if self.limit <= 0:
            return 0
        tok = next(self._ids)
        with self._lock:
            self._orders[tok] = [self.clock(), threading.current_thread().name, False, label]
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name='post-stall-watch', daemon=True)
                self._thread.start()
        return tok

    def leave(self, tok: int) -> None:
        with self._lock:
            self._orders.pop(tok, None)

    def _loop(self) -> None:
        while True:
            time.sleep(self.poll)
            self.check()

    def check(self) -> int:
        """Один обход: печатает стеки для каждого заказа, зависшего дольше лимита и ещё не напечатанного. → сколько напечатано."""
        now, late = self.clock(), []
        with self._lock:
            for tok, o in self._orders.items():
                if not o[2] and now - o[0] > self.limit:
                    o[2] = True
                    late.append((tok, now - o[0], o[1], o[3]))
        for tok, age, th, label in late:
            try:
                self.dump(f'{label} #{tok} (поток {th}) идёт уже {age:.1f} с (> {self.limit:g} с) — стеки всех потоков:')
            except Exception as e:  # noqa: BLE001 — сторож не роняет сервис
                print(f'сторож заказов: стеки не напечатаны: {type(e).__name__}', file=sys.stderr, flush=True)
        return len(late)


def _selftest() -> int:
    bad = []

    def ok(n, c):
        print(('OK   ' if c else 'FAIL ') + n)
        if not c:
            bad.append(n)
    t = [100.0]
    out = []
    w = StallWatch(3, dump=out.append, clock=lambda: t[0], poll=3600)    # обход вручную: check() — без потоков и сна
    a, b = w.enter(), w.enter()
    ok('два заказа получили разные токены', a != b and a and b)
    t[0] += 2
    ok('до лимита — ничего', w.check() == 0 and out == [])
    w.leave(a)                                   # быстрый заказ ушёл — зависающий остался под присмотром
    t[0] += 2
    ok('второй завис (4 с > 3 с); первый ушёл раньше — его выход не снял слежение за вторым', w.check() == 1 and len(out) == 1 and f'#{b} ' in out[0] and f'#{a} ' not in out[0])
    t[0] += 5
    ok('повторно тот же заказ не печатается', w.check() == 0 and len(out) == 1)
    c, d = w.enter(), w.enter()
    t[0] += 4
    ok('два зависших разом — два отдельных вывода (второй не затирает первый)', w.check() == 2 and len(out) == 3)
    w.leave(b), w.leave(c), w.leave(d)
    ok('после выхода всех — пусто', w._orders == {})
    boom = StallWatch(1, dump=lambda s: 1 / 0, clock=lambda: t[0], poll=3600)
    boom.enter(); t[0] += 2
    ok('сбой печати не роняет сторож', boom.check() == 1)
    off = StallWatch(0)
    ok('limit 0 — выключено: токен 0, поток не запущен', off.enter() == 0 and off._thread is None)
    # настоящий поток и настоящее время: два параллельных заказа, один быстрый, один висит
    real = []
    rw = StallWatch(0.3, dump=real.append, poll=0.05)
    slow, fast = rw.enter('POST'), rw.enter('POST')
    time.sleep(0.1)
    rw.leave(fast)
    time.sleep(0.6)
    ok('живой поток: висящий заказ напечатан один раз, быстрый — нет', len(real) == 1 and f'#{slow} ' in real[0])
    rw.leave(slow)
    # из двух потоков одновременно — разные токены, без гонок
    tw = StallWatch(60, dump=lambda s: None, poll=3600)
    toks, ths = [], [threading.Thread(target=lambda: toks.append(tw.enter())) for _ in range(20)]
    [x.start() for x in ths]; [x.join() for x in ths]
    ok('20 потоков одновременно — 20 разных токенов', len(set(toks)) == 20 and len(tw._orders) == 20)
    print('итог:', 'чисто' if not bad else f'ПРОВАЛЕНО {len(bad)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)
