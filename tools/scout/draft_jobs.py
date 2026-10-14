#!/usr/bin/env python3
"""ЗАДАНИЯ СЕРВИСА КАДРОВ ПЕРЕЖИВАЮТ ДЕПЛОЙ (план demo-03 п.1, остаток ADR-0278; разбор Codex 14.10).

Раньше задания жили в словаре процесса: выкладка сервиса пересоздаёт контейнер, словарь пропадает, страница
спрашивала «готово?» про номер, которого больше нет, и получала 404 (живой прогон 14.10, сценарий 2.9).
Теперь каждое изменение статуса пишется файлом рядом с реестром кадров (каталог share — том, он переживает
пересоздание контейнера). При старте:
  - незаконченный ЧЕРНОВИК (бесплатный) перезапускается сам — человек дождётся кадра по тому же номеру;
  - незаконченное УЛУЧШЕНИЕ (платное) не повторяется молча: неизвестно, успел ли шлюз списать деньги, —
    задание получает `code: lost` и честный текст, повтор — только кнопкой человека.
Все составные операции (создать/обрезать/обновить/очередь) — под одним замком; файл пишется под тем же замком
целиком (tmp + fsync + rename). Межпроцессного замка нет: compose с фиксированным `container_name` гасит
старый контейнер ДО запуска нового, перекрытия процессов нет (если появится blue/green — нужен flock).

Самопроверка без рендера: `python tools/scout/draft_jobs.py --selftest`.
"""
import json
import os
import sys
import threading
import time
import uuid

LOST_PAID = ('Улучшение прервалось: сервер обновлялся. Результат неизвестен — повтор может потребовать '
             'новую оплату. Нажмите «Повторить», если фото всё ещё нужно.')


class JobStore:
    def __init__(self, path: str, max_jobs: int = 40, ttl_s: int = 7200):
        self.path, self.max_jobs, self.ttl_s = path, max_jobs, ttl_s
        self.lock = threading.RLock()
        self.jobs: dict = {}
        self.waiting: list = []

    # ——— файл
    def _save(self) -> bool:
        snap = {}
        for k, j in self.jobs.items():
            x = {kk: vv for kk, vv in j.items() if kk != 'body' or j.get('status') == 'running'}
            snap[k] = x
        tmp = self.path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(snap, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            return True
        except Exception as e:  # noqa: BLE001 — без файла сервис работает, но молчать нельзя
            print(f'задания не сохранены в {self.path}: {str(e)[:120]}', flush=True)
            return False

    def load(self) -> list:
        """Прочитать файл после старта процесса. Возвращает номера ЧЕРНОВИКОВ, которые надо перезапустить."""
        with self.lock:
            try:
                data = json.load(open(self.path, encoding='utf-8'))
                if not isinstance(data, dict):
                    raise ValueError('не словарь')
            except FileNotFoundError:
                data = {}
            except Exception as e:  # noqa: BLE001 — битый файл не валит сервис
                print(f'файл заданий не прочитан ({str(e)[:80]}) — начинаем с пустого', flush=True)
                data = {}
            self.jobs = {k: v for k, v in data.items() if isinstance(v, dict)}
            self._trim()
            resume = []
            for jid, j in self.jobs.items():
                if j.get('status') != 'running':
                    continue
                if j.get('quality') == 'realistic' or not j.get('body'):
                    self.jobs[jid] = {'status': 'error', 'ts': j.get('ts', time.time()),
                                      'quality': j.get('quality', 'draft'), 'code': 'lost', 'error': LOST_PAID
                                      if j.get('quality') == 'realistic' else
                                      'Задание прервалось при обновлении сервера — нажмите «Повторить».'}
                else:
                    j.pop('started', None)
                    resume.append(jid)
            self._save()
            return sorted(resume, key=lambda k: self.jobs[k].get('ts', 0))

    # ——— задания
    def _trim(self) -> None:
        now = time.time()
        for k in [k for k, j in self.jobs.items() if now - j.get('ts', 0) > self.ttl_s]:
            self.jobs.pop(k, None)                  # сначала старше срока
        if len(self.jobs) > self.max_jobs:          # затем — не больше max_jobs, старые первыми
            for k in sorted(self.jobs, key=lambda k: self.jobs[k].get('ts', 0))[:len(self.jobs) - self.max_jobs]:
                self.jobs.pop(k, None)

    def new(self, quality: str, body: dict) -> str:
        with self.lock:
            jid = uuid.uuid4().hex[:12]
            self.jobs[jid] = {'status': 'running', 'ts': time.time(), 'quality': quality, 'body': body}
            self._trim()                            # новое — самое свежее, обрезка его не тронет
            self._save()
            return jid

    def get(self, jid: str):
        with self.lock:
            j = self.jobs.get(jid)
            return dict(j) if j else None

    def body(self, jid: str):
        with self.lock:
            j = self.jobs.get(jid)
            return (j or {}).get('body')

    def mark(self, jid: str, **kw) -> None:
        """Поле задания (например `started`). Удалённое обрезкой задание молча игнорируется."""
        with self.lock:
            if jid in self.jobs:
                self.jobs[jid].update(kw)

    def finish(self, jid: str, result: dict) -> None:
        with self.lock:
            j = self.jobs.get(jid)
            if not j:
                return
            self.jobs[jid] = {'status': 'done', 'ts': j['ts'], 'quality': j.get('quality', 'draft'), 'result': result}
            self._save()

    def fail(self, jid: str, error: str, code: str = 'error') -> None:
        with self.lock:
            j = self.jobs.get(jid)
            if not j:
                return
            self.jobs[jid] = {'status': 'error', 'ts': j['ts'], 'quality': j.get('quality', 'draft'),
                              'error': error, 'code': code}
            self._save()

    def running(self, quality: str) -> int:
        with self.lock:
            return sum(1 for j in self.jobs.values() if j.get('status') == 'running' and j.get('quality') == quality)

    # ——— очередь
    def wait_add(self, jid: str) -> None:
        with self.lock:
            self.waiting.append(jid)

    def wait_remove(self, jid: str) -> None:
        with self.lock:
            if jid in self.waiting:
                self.waiting.remove(jid)

    def wait_pos(self, jid: str) -> int:
        """Место в очереди с 1; 0 — не ждёт."""
        with self.lock:
            return self.waiting.index(jid) + 1 if jid in self.waiting else 0

    def waiting_n(self) -> int:
        with self.lock:
            return len(self.waiting)


def public_view(j: dict) -> dict:
    """Что видит страница по GET /job: без тела запроса."""
    if j.get('status') == 'done':
        return j.get('result') or {'status': 'done'}
    return {k: v for k, v in j.items() if k in ('status', 'error', 'code')}


def _selftest() -> int:
    import tempfile
    fails = 0

    def ok(cond, name):
        nonlocal fails
        print(('ok   ' if cond else 'FAIL ') + name)
        fails += 0 if cond else 1

    d = tempfile.mkdtemp()
    p = os.path.join(d, 'jobs.json')
    s = JobStore(p, max_jobs=3)
    a = s.new('draft', {'room': 1})
    b = s.new('realistic', {'room': 2})
    c = s.new('draft', {'room': 3})
    s.finish(c, {'shots': [{'url': 'x'}]})
    ok(s.running('realistic') == 1 and s.running('draft') == 1, 'счёт идущих по качеству')
    # «перезапуск процесса»: новый объект читает тот же файл
    s2 = JobStore(p, max_jobs=3)
    resume = s2.load()
    ok(resume == [a], 'черновик перезапускается сам')
    ok(s2.get(b)['code'] == 'lost' and 'оплат' in s2.get(b)['error'], 'платное — lost с честным текстом')
    ok(s2.get(c)['status'] == 'done' and public_view(s2.get(c))['shots'], 'готовое переживает перезапуск')
    ok('body' not in json.load(open(p))[c], 'тело запроса не хранится у законченного')
    # обрезка: старше срока — вон; затем лимит
    s2.jobs[c]['ts'] -= 99999
    s2.new('draft', {})
    ok(c not in s2.jobs, 'старше срока удаляется')
    for _ in range(5):
        s2.new('draft', {})
    ok(len(s2.jobs) <= 3, 'не больше max_jobs')
    s2.finish('нет-такого', {})
    s2.fail('нет-такого', 'x')
    ok(True, 'позднее завершение удалённого задания не падает')
    # битый файл
    open(p, 'w').write('{битый')
    s3 = JobStore(p)
    ok(s3.load() == [] and s3.jobs == {}, 'битый файл — пустой старт без падения')
    # параллельные обновления
    s4 = JobStore(os.path.join(d, 'j4.json'), max_jobs=100)
    ids = [s4.new('draft', {}) for _ in range(20)]
    th = [threading.Thread(target=s4.finish, args=(i, {'n': 1})) for i in ids]
    [t.start() for t in th]
    [t.join() for t in th]
    ok(all(s4.get(i)['status'] == 'done' for i in ids), '20 параллельных завершений не теряются')
    ok(len(json.load(open(os.path.join(d, 'j4.json')))) == 20, 'файл после параллельных записей целый')
    s4.wait_add('q1')
    s4.wait_add('q2')
    ok(s4.wait_pos('q2') == 2 and s4.wait_pos('zz') == 0, 'место в очереди')
    s4.wait_remove('q1')
    ok(s4.wait_pos('q2') == 1, 'очередь сдвигается')
    print('итог:', 'чисто' if not fails else f'{fails} провал(ов)')
    return 1 if fails else 0


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(_selftest())
