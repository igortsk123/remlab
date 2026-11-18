#!/usr/bin/env python3
"""ЗАДАНИЯ РЕНДЕРА «СДЕЛАТЬ ФОТО» (T-20261117-19/1, план `photo-render-first-01`, шаги 3–4): своя очередь, не слоты нейросети.

Рендер Blender — бесплатный для человека, но не для нас (ядра DEV, минуты). Поэтому у него свой тип задания, своя очередь и
свои пределы; слоты и деньги платного «Улучшить» (`draft_service._LOCK`, `_paid_gate`) он не трогает.

  Заказ → `canonicalize` (`render_snapshot.py`) → `scene_hash` → ключ кэша (`key` = хеш + версия рендера):
    * одинаковый ключ = ОДНО задание: идёт/ждёт — тот же номер; готов (кадры лежат в кэше) — мгновенный `done`;
    * отказ ДО постановки при заполнении (`admit`): очередь, один адрес, один тур, час — честный код и срок «попробуйте через …»;
    * один рабочий поток — один Blender за раз (`RENDER_WORKERS`, 1); интерактивные (prio 0) раньше прогрева и автофото (prio 1);
    * номер задания и готовый результат переживают перезапуск сервиса: файл заданий рядом с реестром кадров, кадры — каталогом
      `<RENDER_DIR>/<ключ>/C1.jpg, C2.jpg, meta.json`; прерванное перезапуском (в очереди или в работе) становится в очередь заново
      (рендер бесплатный и повторяемый), не больше `MAX_ATTEMPTS` раз;
    * ошибка рендера — понятный текст пары RU/EN и `retry: true`; тихого перехода на нейросеть нет.
  Исполнитель — интерфейс (`render_exec.py`): сейчас `local-cpu` (Blender на DEV под общей очередью тяжёлых прогонов), позже
  `salad-gpu` (машина рендера) — тот же вход и выход, выбор настройкой `RENDER_EXECUTOR`, без особых случаев.

Самопроверка без Blender: `python tools/scout/render_jobs.py --selftest` (исполнитель-заглушка).
"""
import json
import os
import sys
import threading
import time
import uuid

try:                                    # рядом с модулем; при импорте как скрипт путь уже верный
    from render_exec import RenderError, ExecutorUnavailable
except ImportError:  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from render_exec import RenderError, ExecutorUnavailable

MAX_ATTEMPTS = 2
CAMS = ('C1', 'C2')
DEFAULT_SEC = float(os.environ.get('RENDER_DEFAULT_SEC', 600))      # до первых замеров: честная прикидка локального процессора
MIN_SAMPLES = 5                                                      # замеров исполнителя, с которых диапазон — по ним, а не по прикидке
# прикидка по исполнителю до замеров: (мин, макс, среднее) секунд; у машины рендера на 4090 — 20…60 с (живые замеры T-24: 30–60 с), остальные — по DEFAULT_SEC
GUESS = {'salad-gpu': (float(os.environ.get('RENDER_GPU_LO', 20)), float(os.environ.get('RENDER_GPU_HI', 60)), float(os.environ.get('RENDER_GPU_AVG', 40)))}
LEGACY_EX = 'local-cpu'                                              # замеры до учёта исполнителя были процессорные


def _env_i(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


class Refusal(Exception):
    """Отказ до постановки: `status` HTTP, `code` для страницы, пара текстов, `retry_after` — секунды."""

    def __init__(self, status: int, code: str, ru: str, en: str, retry_after: int = 0):
        super().__init__(ru)
        self.status, self.code, self.ru, self.en, self.retry_after = status, code, ru, en, retry_after

    def body(self) -> dict:
        b = {'error': self.ru, 'error_en': self.en, 'code': self.code}
        if self.retry_after:
            b['retry_after'] = self.retry_after
        return b


def _pct(xs: list, p: float):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(p * (len(s) - 1))))], 1)


class RenderStore:
    """Задания и замеры — одним файлом (tmp + fsync + rename, под замком), кадры — каталогами по ключу кэша."""

    def __init__(self, path: str, results_dir: str, max_jobs: int = 300, ttl_s: int = 86400, keep_results: int = 0):
        keep_results = keep_results or _env_i('RENDER_KEEP_RESULTS', 800)     # «заранее посчитанные» кадры всех комнат (T-20261118-07) не должны вытесняться уборкой
        self.path, self.results_dir = path, results_dir
        self.max_jobs, self.ttl_s, self.keep_results = max_jobs, ttl_s, keep_results
        self.lock = threading.RLock()
        self.jobs: dict = {}
        self.durs: list = []            # секунды от начала работы до готовых двух кадров (последние 30)
        self.dur_ex: list = []          # кто считал — имя исполнителя, по одному на каждый замер (та же длина и порядок, что у durs)
        os.makedirs(results_dir, exist_ok=True)

    def save(self) -> bool:
        tmp = self.path + '.tmp'
        try:
            with self.lock:
                snap = {'v': 1, 'jobs': self.jobs, 'durs': self.durs[-30:], 'dur_ex': self.dur_ex[-30:]}
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(snap, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
            return True
        except Exception as e:  # noqa: BLE001 — без файла сервис работает, молчать нельзя
            print(f'задания рендера не сохранены в {self.path}: {str(e)[:120]}', flush=True)
            return False

    def load(self) -> int:
        """Прочитать файл после старта. Прерванные (queued/running) — снова в очередь; возвращает, сколько ждёт."""
        with self.lock:
            try:
                data = json.load(open(self.path, encoding='utf-8'))
                if not isinstance(data, dict):
                    raise ValueError('не словарь')
            except FileNotFoundError:
                data = {}
            except Exception as e:  # noqa: BLE001
                print(f'файл заданий рендера не прочитан ({str(e)[:80]}) — пустой старт', flush=True)
                data = {}
            self.jobs = {k: v for k, v in (data.get('jobs') or {}).items() if isinstance(v, dict)}
            self.durs = [float(x) for x in (data.get('durs') or []) if isinstance(x, (int, float))][-30:]
            exs = [x if isinstance(x, str) and x else LEGACY_EX for x in (data.get('dur_ex') or [])][-len(self.durs):] if self.durs else []
            self.dur_ex = [LEGACY_EX] * (len(self.durs) - len(exs)) + exs         # старый файл без исполнителей: замеры были процессорные
            for jid, j in list(self.jobs.items()):
                if j.get('status') in ('queued', 'running'):
                    if int(j.get('attempts', 0)) >= MAX_ATTEMPTS or not j.get('body'):
                        self.jobs[jid] = self._failed(j, 'lost', 'Рендер прервался: сервер перезапускался. Нажмите «Повторить».',
                                                      'The render was interrupted by a server restart. Press "Retry".')
                    else:
                        j.update(status='queued', stage='', started=None)
            self._trim()
            self.save()
            return sum(1 for j in self.jobs.values() if j.get('status') == 'queued')

    @staticmethod
    def _failed(j: dict, code: str, ru: str, en: str) -> dict:
        return {'status': 'error', 'ts': j.get('ts', time.time()), 'key': j.get('key'), 'hash': j.get('hash'), 'code': code,
                'error': ru, 'error_en': en, 'retry': True}

    def _trim(self) -> None:
        now = time.time()
        for k in [k for k, j in self.jobs.items() if j.get('status') in ('done', 'error') and now - j.get('ts', 0) > self.ttl_s]:
            self.jobs.pop(k, None)
        if len(self.jobs) > self.max_jobs:
            done = sorted((k for k, j in self.jobs.items() if j.get('status') in ('done', 'error')), key=lambda k: self.jobs[k].get('ts', 0))
            for k in done[:len(self.jobs) - self.max_jobs]:
                self.jobs.pop(k, None)

    # ——— кэш кадров по ключу
    def result_dir(self, key: str) -> str:
        return os.path.join(self.results_dir, key)

    def cached(self, key: str):
        """meta готовой пары кадров по ключу или None (нет файла или нет любого из кадров)."""
        d = self.result_dir(key)
        try:
            meta = json.load(open(os.path.join(d, 'meta.json'), encoding='utf-8'))
        except (OSError, ValueError):
            return None
        if not all(os.path.isfile(os.path.join(d, f'{c}.jpg')) for c in CAMS):
            return None
        return meta

    def trim_results(self) -> int:
        """Каталоги кадров старше лимита (по времени записи) убираются, свежие и нужные открытым заданиям остаются."""
        import shutil
        try:
            dirs = [(os.path.getmtime(os.path.join(self.results_dir, n)), n) for n in os.listdir(self.results_dir)
                    if os.path.isdir(os.path.join(self.results_dir, n))]
        except OSError:
            return 0
        busy = {j.get('key') for j in self.jobs.values() if j.get('status') in ('queued', 'running', 'done')}
        gone = 0
        for _, n in sorted(dirs)[:max(0, len(dirs) - self.keep_results)]:
            if n in busy:
                continue
            shutil.rmtree(os.path.join(self.results_dir, n), ignore_errors=True)
            gone += 1
        return gone


class RenderQueue:
    def __init__(self, store: RenderStore, executor, workers: int = 1):
        self.store, self.executor, self.workers = store, executor, max(1, workers)
        self.cond = threading.Condition(store.lock)
        self.hits: list = []             # метки времени принятых заданий (предел в час)
        self.threads: list = []
        self.stop = False
        # пределы (настройки, не константы кода)
        self.max_queue = _env_i('RENDER_MAX_QUEUE', 8)
        self.ip_max = _env_i('RENDER_IP_MAX', 2)
        self.tour_max = _env_i('RENDER_TOUR_MAX', 2)
        self.hour_cap = _env_i('RENDER_HOUR_CAP', 40)

    # ——— оценка времени: по тому исполнителю, который возьмёт заказ СЕЙЧАС (машина прогрета — её замеры, нет — запасного)
    def expected(self) -> str:
        """Имя исполнителя, который посчитает заказ, поставленный сейчас (у исполнителя без `expected` — его имя)."""
        f = getattr(self.executor, 'expected', None)
        try:
            return str(f()) if callable(f) else str(getattr(self.executor, 'name', '?'))
        except Exception:  # noqa: BLE001 — не знаем, кто возьмёт: честнее считать запасного
            return LEGACY_EX

    def durs_of(self, name: str) -> list:
        st = self.store
        return [d for d, e in zip(st.durs, st.dur_ex) if e == name]

    def avg_sec(self, name: str | None = None) -> float:
        name = name or self.expected()
        d = self.durs_of(name)[-10:]
        if d:
            return sum(d) / len(d)
        return GUESS[name][2] if name in GUESS else DEFAULT_SEC

    def range_sec(self, name: str | None = None) -> tuple:
        """Диапазон одного задания из замеров ИСПОЛНИТЕЛЯ: p50…p95; до пяти его замеров — прикидка (машина рендера — 20…60 с, прочие ×0,8…×1,6 от DEFAULT_SEC)."""
        name = name or self.expected()
        d = self.durs_of(name)
        if len(d) >= MIN_SAMPLES:
            return int(_pct(d, 0.5)), int(_pct(d, 0.95))
        if name in GUESS:
            return int(GUESS[name][0]), int(GUESS[name][1])
        return int(DEFAULT_SEC * 0.8), int(DEFAULT_SEC * 1.6)

    def _order(self) -> list:
        """Очередь: сперва интерактивные, внутри — по приходу; ждущий дольше 30 мин идёт как интерактивный (прогрев не голодает).
        Заготовка кадров (`warm`, T-20261118-07) всегда после заказов людей и не «стареет» в интерактивный: ей нельзя занять процессор DEV."""
        now = time.time()
        q = [(jid, j) for jid, j in self.store.jobs.items() if j.get('status') == 'queued']
        return [jid for jid, j in sorted(q, key=lambda t: (0 if (not t[1].get('warm') and (t[1].get('prio', 0) == 0 or now - t[1].get('ts', now) > 1800))
                                                          else 1, t[1].get('ts', 0)))]

    def warm_ok(self) -> bool:
        """Можно ли сейчас брать заготовку кадров: только если её посчитает машина рендера (исполнитель сам говорит — `warm_ok`); без неё заготовки ждут."""
        f = getattr(self.executor, 'warm_ok', None)
        try:
            return bool(f()) if callable(f) else False
        except Exception:  # noqa: BLE001
            return False

    def eta(self, jid: str) -> dict:
        """{'queue': место с 1 (0 — не ждёт), 'eta': секунды до обоих кадров, 'eta_range': [мин, макс]}."""
        with self.store.lock:
            j = self.store.jobs.get(jid) or {}
            who = self.expected()
            avg = self.avg_sec(who)
            lo, hi = self.range_sec(who)
            running = [x for x in self.store.jobs.values() if x.get('status') == 'running']
            left = 0.0
            for r in running:
                left = max(left, max(0.0, avg - (time.time() - (r.get('started') or time.time()))))
            if j.get('status') == 'queued':
                pos = self._order().index(jid) + 1
                rounds = (pos - 1) // self.workers + 1
                base = left if len(running) >= self.workers else 0.0
                return {'queue': pos, 'eta': int(base + avg * rounds), 'eta_range': [int(base + lo * rounds), int(base + hi * rounds)]}
            if j.get('status') == 'running':
                el = time.time() - (j.get('started') or time.time())
                return {'queue': 0, 'eta': int(max(0.0, avg - el)), 'eta_range': [int(max(0.0, lo - el)), int(max(0.0, hi - el))]}
        return {}

    # ——— приём
    def waiting_n(self) -> int:
        with self.store.lock:
            return sum(1 for j in self.store.jobs.values() if j.get('status') == 'queued' and not j.get('warm'))

    def warm_counts(self) -> dict:
        """Заготовки кадров по состояниям (для статуса)."""
        with self.store.lock:
            c = {'queued': 0, 'running': 0}
            for j in self.store.jobs.values():
                if j.get('warm') and j.get('status') in c:
                    c[j['status']] += 1
            return c

    def _active(self, field: str, value) -> int:
        if not value:
            return 0
        return sum(1 for j in self.store.jobs.values() if j.get('status') in ('queued', 'running') and j.get(field) == value)

    def admit(self, ip: str, tour: str) -> None:
        """Отказ ДО постановки (под замком хранилища). Пределы — настройки `RENDER_*`; срок «попробуйте через» — по замеру."""
        avg = max(30, int(self.avg_sec()))           # «попробуйте через» — не меньше полуминуты
        now = time.time()
        self.hits[:] = [t for t in self.hits if now - t < 3600]
        if self._active('ip', ip) >= self.ip_max:
            raise Refusal(429, 'render_ip_busy', 'У вас уже считаются фото. Дождитесь их и повторите.',
                          'Your photos are already being rendered. Wait for them and try again.', avg)
        if self._active('tour', tour) >= self.tour_max:
            raise Refusal(429, 'render_tour_busy', 'По этому туру уже считаются фото. Дождитесь их и повторите.',
                          'Photos for this tour are already being rendered. Wait for them and try again.', avg)
        if len(self.hits) >= self.hour_cap:
            raise Refusal(429, 'render_hour_cap', 'Сейчас много заказов фото. Попробуйте через несколько минут.',
                          'Many photo requests right now. Try again in a few minutes.', 600)
        if self.waiting_n() >= self.max_queue:
            raise Refusal(503, 'render_busy', 'Очередь фото заполнена. Попробуйте через несколько минут.',
                          'The photo queue is full. Try again in a few minutes.', avg * 2)

    def submit(self, snap: dict, key: str, ip: str = '', tour: str = '', prio: int = 0, legacy: dict | None = None, warm: bool = False) -> dict:
        """Поставить заказ. → {'job', 'status', 'deduped', 'cached'}; отказ — `Refusal`.
        `warm` — заготовка кадров программой (T-20261118-07): пределы покупателя (`admit`) её не касаются и не считают, в очереди она всегда после заказов людей
        и считается только на машине рендера (`warm_ok`); место в очереди для людей и срок ожидания она не занимает."""
        st = self.store
        with st.lock:
            for jid, j in st.jobs.items():                   # одинаковый ключ — одно задание
                if j.get('key') == key and j.get('status') in ('queued', 'running'):
                    return {'job': jid, 'status': j['status'], 'deduped': True, 'cached': False}
            meta = st.cached(key)
            if meta is not None:                              # кадры уже есть — мгновенный `done` (отказов и пределов нет: ядра не тратятся)
                for jid, j in st.jobs.items():
                    if j.get('key') == key and j.get('status') == 'done':
                        return {'job': jid, 'status': 'done', 'deduped': True, 'cached': True}
                jid = uuid.uuid4().hex[:12]
                st.jobs[jid] = {'status': 'done', 'ts': time.time(), 'key': key, 'hash': snap['scene_hash'], 'result': self._result(key, meta, 0.0, True)}
                st._trim()
                st.save()
                return {'job': jid, 'status': 'done', 'deduped': True, 'cached': True}
            if not warm:
                self.admit(ip, tour)
            jid = uuid.uuid4().hex[:12]
            st.jobs[jid] = {'status': 'queued', 'ts': time.time(), 'key': key, 'hash': snap['scene_hash'], 'prio': 1 if (prio or warm) else 0,
                            'ip': ip, 'tour': tour, 'attempts': 0, 'stage': '', 'started': None,
                            'body': {'snap': snap, 'legacy': legacy or {}}}
            if warm:
                st.jobs[jid]['warm'] = True
            else:
                self.hits.append(time.time())
            st._trim()
            st.save()
            self.cond.notify_all()
            return {'job': jid, 'status': 'queued', 'deduped': False, 'cached': False}

    # ——— вид для страницы
    def _result(self, key: str, meta: dict, sec: float, cached: bool) -> dict:
        return {'status': 'done', 'key': key, 'scene_hash': meta.get('scene_hash'), 'cached': cached, 'sec': round(sec, 1),
                'kind': 'render', 'versions': meta.get('versions') or {},
                'frames': [{'camera': c, 'url': f'/api/render/cycles/frame/{key}/{c}.jpg', 'id': (meta.get('sha') or {}).get(c),
                            'w': (meta.get('size') or [0, 0])[0], 'h': (meta.get('size') or [0, 0])[1]} for c in CAMS],
                'timing': meta.get('timing') or {}}

    def view(self, jid: str) -> dict | None:
        with self.store.lock:
            j = self.store.jobs.get(jid)
            if not j:
                return None
            if j['status'] == 'done':
                return {**j['result'], 'percent': 100, 'frames_done': 2, 'frame': None}
            if j['status'] == 'error':
                return {'kind': 'render', **{k: v for k, v in j.items() if k in ('status', 'error', 'error_en', 'code', 'retry')}}
            out = {'status': j['status'], 'kind': 'render', 'stage': j.get('stage') or '', 'sec': round(time.time() - j['ts'], 1),
                   **self.progress_of(j), **self.eta(jid)}
            return out

    def progress_of(self, j: dict) -> dict:
        """Ход для процентов страницы: `percent` 0–99 (100 — только готовый результат), `frames_done` 0–2, `frame` — какой кадр считается.
        Подготовка сцены ≈ 8 %, кадры делят остальное; внутри кадра — доля ожидаемого времени по средним замерам, но не выше 95 % кадра
        (пока Blender не вернул кадр, 100 % не обещаем). Не убывает: стадия и время идут вперёд."""
        stage = j.get('stage') or ''
        if j.get('status') != 'running':
            return {'percent': 0, 'frames_done': 0, 'frame': None}
        per = max(10.0, (self.avg_sec() * 0.92) / 2)
        el = max(0.0, time.time() - (j.get('stage_ts') or time.time()))
        inner = min(0.95, el / per)
        if stage == 'C1':
            pct, done = 8 + 46 * inner, 0
        elif stage == 'C2':
            pct, done = 54 + 45 * inner, 1
        elif stage == 'save':
            pct, done = 99, 2
        else:
            pct, done = 8 * min(0.95, el / 60.0), 0
        return {'percent': min(99, int(pct)), 'frames_done': done, 'frame': stage if stage in ('C1', 'C2') else None}

    def stats(self) -> dict:
        with self.store.lock:
            who = self.expected()
            d = self.durs_of(who)
            by = {n: {'n': len(x), 'p50': _pct(x, 0.5), 'p95': _pct(x, 0.95)} for n in sorted(set(self.store.dur_ex)) for x in [self.durs_of(n)]}
            return {'executor': getattr(self.executor, 'name', '?'), 'expected': who, 'by_executor': by, 'queue': self.waiting_n(), 'workers': self.workers,
                    'running': sum(1 for j in self.store.jobs.values() if j.get('status') == 'running'),
                    'n': len(d), 'p50': _pct(d, 0.5), 'p95': _pct(d, 0.95), 'range': list(self.range_sec(who)),
                    'limits': {'queue': self.max_queue, 'ip': self.ip_max, 'tour': self.tour_max, 'hour': self.hour_cap},
                    'hour_used': len([t for t in self.hits if time.time() - t < 3600]), 'warm': {**self.warm_counts(), 'status': {k: v for k, v in (getattr(getattr(self, 'prewarm', None), 'status', None) or {}).items() if k in ('state', 'total', 'missing')}}}   # без денег: статистика публична

    # ——— рабочий
    def start(self) -> None:
        for i in range(self.workers):
            t = threading.Thread(target=self._loop, name=f'render-{i}', daemon=True)
            t.start()
            self.threads.append(t)

    def _take(self):
        with self.cond:
            while not self.stop:
                order = self._order()
                if order and self.store.jobs[order[0]].get('warm') and not self.warm_ok():
                    order = [x for x in order if not self.store.jobs[x].get('warm')]     # заготовки ждут машину; людям она не мешает
                if order:
                    jid = order[0]
                    j = self.store.jobs[jid]
                    j.update(status='running', started=time.time(), stage='scene', attempts=int(j.get('attempts', 0)) + 1)
                    self.store.save()
                    return jid
                self.cond.wait(timeout=5)
        return None

    def _loop(self) -> None:
        while not self.stop:
            jid = self._take()
            if jid is None:
                return
            self.run_one(jid)

    def run_one(self, jid: str) -> None:
        st = self.store
        with st.lock:
            j = st.jobs.get(jid)
            if not j or j.get('status') != 'running':
                return
            body, key, t0, warm = j['body'], j['key'], j['started'], bool(j.get('warm'))

        def progress(stage: str) -> None:
            with st.lock:
                if jid in st.jobs and st.jobs[jid].get('status') == 'running':
                    st.jobs[jid]['stage'] = stage
                    st.jobs[jid]['stage_ts'] = time.time()
        who0 = self.expected()
        try:
            ex = getattr(self.executor, 'primary', self.executor) if warm else self.executor        # заготовка — только на машине рендера, запасного (процессор DEV) у неё нет
            out = ex.render(body['snap'], st.result_dir(key), progress)
            sec = time.time() - t0
            meta = st.cached(key)
            if meta is not None and body.get('legacy'):       # заказ «Улучшить»: по нему сервис берёт состояние снимка, не слова страницы
                try:
                    json.dump(body['legacy'], open(os.path.join(st.result_dir(key), 'order.json'), 'w', encoding='utf-8'), ensure_ascii=False)
                except OSError as e:
                    print(f'рендер {jid}: order.json не записан: {e}', flush=True)
            if meta is None:
                raise RenderError('render_failed', 'Рендер не дал кадров. Нажмите «Повторить».', 'The render produced no frames. Press "Retry".')
            who = (out.get('executor') if isinstance(out, dict) else None) or who0
            with st.lock:
                st.durs = (st.durs + [sec])[-30:]
                st.dur_ex = (st.dur_ex + [who])[-30:]
                st.jobs[jid] = {'status': 'done', 'ts': st.jobs[jid]['ts'], 'key': key, 'hash': body['snap']['scene_hash'],
                                'result': self._result(key, meta, sec, False), 'legacy': body.get('legacy') or {}}
                st.save()
            st.trim_results()
            print(f'рендер {jid}: готов за {sec:.0f} с ({out.get("timing") if isinstance(out, dict) else ""})', flush=True)
        except (RenderError, ExecutorUnavailable) as e:
            if warm and isinstance(e, ExecutorUnavailable):
                with st.lock:                                  # машину вытеснили/погасили посреди заготовки — не ошибка: ждёт в очереди следующего включения
                    jj = st.jobs.get(jid)
                    if jj and jj.get('status') == 'running' and int(jj.get('attempts', 0)) < MAX_ATTEMPTS + 2:
                        jj.update(status='queued', stage='', started=None)
                        st.save()
                        print(f'заготовка {jid}: машина недоступна ({e.code}) — ждёт в очереди', flush=True)
                        return
            self._fail(jid, e.code, e.ru, e.en)
        except BaseException as e:  # noqa: BLE001 — любой сбой обязан стать статусом (урок 13.10: поток умирал молча)
            print(f'рендер {jid}: сбой {e!r}', flush=True)
            self._fail(jid, 'render_failed', 'Рендер не удался. Нажмите «Повторить».', 'The render failed. Press "Retry".')

    def _fail(self, jid: str, code: str, ru: str, en: str) -> None:
        with self.store.lock:
            j = self.store.jobs.get(jid)
            if j:
                self.store.jobs[jid] = self.store._failed(j, code, ru, en)
                self.store.save()
        print(f'рендер {jid}: отказ {code}', flush=True)

    def close(self) -> None:
        with self.cond:
            self.stop = True
            self.cond.notify_all()


# ——— самопроверка (исполнитель-заглушка)
def _selftest() -> int:
    import shutil
    import tempfile
    bad = 0

    def ok(c, name):
        nonlocal bad
        print(('ok   ' if c else 'FAIL ') + name)
        bad += 0 if c else 1

    class Fake:
        name = 'fake'

        def __init__(self, store, delay=0.0, fail=None):
            self.store, self.delay, self.fail, self.calls = store, delay, fail, []

        def render(self, snap, out_dir, progress):
            self.calls.append(snap['scene_hash'])
            progress('C1')
            time.sleep(self.delay)
            if self.fail:
                raise self.fail
            os.makedirs(out_dir, exist_ok=True)
            for c in CAMS:
                open(os.path.join(out_dir, f'{c}.jpg'), 'wb').write(b'\xff\xd8x')
            json.dump({'scene_hash': snap['scene_hash'], 'size': [10, 8], 'versions': {'x': 1}, 'sha': {'C1': 'a' * 64, 'C2': 'b' * 64}},
                      open(os.path.join(out_dir, 'meta.json'), 'w'))
            return {'timing': {'t': 1}}

    def snap(h):
        return {'scene_hash': h}

    def wait(q, jid, want=('done', 'error'), t=5.0):
        t0 = time.time()
        while time.time() - t0 < t:
            v = q.view(jid)
            if v and v['status'] in want:
                return v
            time.sleep(0.02)
        return q.view(jid)

    d = tempfile.mkdtemp()
    try:
        st = RenderStore(os.path.join(d, 'jobs.json'), os.path.join(d, 'res'))
        ex = Fake(st)
        q = RenderQueue(st, ex)
        q.max_queue, q.ip_max, q.tour_max, q.hour_cap = 3, 2, 2, 100
        q.start()
        a = q.submit(snap('h1'), 'k1', ip='1.1.1.1', legacy={'room': {'w': 1}})
        v = wait(q, a['job'])
        ok(v['status'] == 'done' and [f['camera'] for f in v['frames']] == ['C1', 'C2'] and v['cached'] is False, 'заказ → два кадра')
        ok(v['kind'] == 'render' and v['frames'][0]['url'] == '/api/render/cycles/frame/k1/C1.jpg' and v['frames'][1]['id'] == 'b' * 64, 'кадры: адрес и sha256 (имя для «Улучшить»)')
        ok(json.load(open(os.path.join(st.result_dir('k1'), 'order.json')))['room'] == {'w': 1}, 'состояние снимка записано рядом с кадрами (order.json)')
        b = q.submit(snap('h1'), 'k1', ip='1.1.1.1')
        ok(b['status'] == 'done' and b['cached'] and b['job'] == a['job'] and ex.calls == ['h1'], 'тот же ключ после готовности — мгновенно из кэша, рендера нет')
        # одинаковый ключ в работе = одно задание
        slow = Fake(st, delay=0.4)
        q.executor = slow
        c1 = q.submit(snap('h2'), 'k2', ip='2.2.2.2')
        time.sleep(0.1)
        c2 = q.submit(snap('h2'), 'k2', ip='3.3.3.3')
        ok(c2['job'] == c1['job'] and c2['deduped'] and slow.calls == ['h2'], 'одинаковый ключ в работе — одно задание')
        v = q.view(c1['job'])
        ok(v['status'] == 'running' and v['stage'] == 'C1' and v['eta'] >= 0 and len(v['eta_range']) == 2, 'в работе: этап и срок с диапазоном')
        ok(v['frame'] == 'C1' and v['frames_done'] == 0 and 8 <= v['percent'] <= 54, f"в работе: проценты для страницы — кадр 1, {v['percent']} %")
        wait(q, c1['job'])
        # отказы до постановки: очередь, адрес, тур
        slow.delay = 0.5
        j0 = q.submit(snap('r0'), 'kr0', ip='9.9.9.1', tour='t1')                   # занимает рабочего
        time.sleep(0.1)
        q.submit(snap('r1'), 'kr1', ip='9.9.9.2', tour='t2')
        q.submit(snap('r2'), 'kr2', ip='9.9.9.3', tour='t3')
        q.submit(snap('r3'), 'kr3', ip='9.9.9.4', tour='t4')
        try:
            q.submit(snap('r4'), 'kr4', ip='9.9.9.5', tour='t5')
            ok(False, 'очередь заполнена — отказ до постановки')
        except Refusal as e:
            ok(e.status == 503 and e.code == 'render_busy' and e.retry_after > 0 and e.ru and e.en, 'очередь заполнена — 503 до постановки, срок, пара RU/EN')
        ok(q.waiting_n() == 3, 'отказанный заказ в очередь не попал')
        wait(q, j0['job'])
        for jid in list(st.jobs):
            wait(q, jid)
        slow.delay = 0.3
        q.submit(snap('i1'), 'ki1', ip='7.7.7.7')
        time.sleep(0.05)
        q.submit(snap('i2'), 'ki2', ip='7.7.7.7')
        try:
            q.submit(snap('i3'), 'ki3', ip='7.7.7.7')
            ok(False, 'третий заказ с одного адреса — отказ')
        except Refusal as e:
            ok(e.code == 'render_ip_busy' and e.status == 429, 'один адрес — не больше ip_max заданий')
        for jid in list(st.jobs):
            wait(q, jid)
        q.submit(snap('t1a'), 'kt1', ip='5.5.5.1', tour='tourX')
        time.sleep(0.05)
        q.submit(snap('t1b'), 'kt2', ip='5.5.5.2', tour='tourX')
        try:
            q.submit(snap('t1c'), 'kt3', ip='5.5.5.3', tour='tourX')
            ok(False, 'третий заказ по туру — отказ')
        except Refusal as e:
            ok(e.code == 'render_tour_busy', 'один тур — не больше tour_max заданий')
        for jid in list(st.jobs):
            wait(q, jid)
        # приоритет: интерактивный обгоняет прогрев; прогрев не голодает после 30 мин
        slow.delay = 0.3
        slow.calls.clear()
        q.submit(snap('p0'), 'kp0', ip='6.0.0.0')
        time.sleep(0.05)
        q.submit(snap('w1'), 'kw1', ip='6.0.0.1', prio=1)
        q.submit(snap('h9'), 'kh9', ip='6.0.0.2', prio=0)
        for jid in list(st.jobs):
            wait(q, jid)
        ok(slow.calls == ['p0', 'h9', 'w1'], 'интерактивный заказ идёт раньше прогрева')
        # ошибка исполнителя — понятный текст и retry, не молчание
        q.executor = Fake(st, fail=RenderError('render_failed', 'Не получилось', 'Failed'))
        e1 = q.submit(snap('e1'), 'ke1', ip='4.0.0.1')
        v = wait(q, e1['job'])
        ok(v['status'] == 'error' and v['retry'] is True and v['error'] and v['error_en'] and v['code'] == 'render_failed', 'ошибка рендера — текст RU/EN и «Повторить»')
        q.executor = Fake(st, fail=ExecutorUnavailable('gpu_unavailable', 'Машина рендера занята', 'The render machine is busy'))
        e2 = q.submit(snap('e2'), 'ke2', ip='4.0.0.2')
        v = wait(q, e2['job'])
        ok(v['status'] == 'error' and v['code'] == 'gpu_unavailable', 'исполнитель недоступен — отказ с кодом, без тихой подмены')
        e3 = q.submit(snap('e2'), 'ke2', ip='4.0.0.2')
        ok(e3['job'] != e2['job'], 'после ошибки повтор того же ключа — новое задание')
        q.executor = Fake(st, fail=ValueError('boom'))
        e4 = q.submit(snap('e4'), 'ke4', ip='4.0.0.4')
        v = wait(q, e4['job'])
        ok(v['status'] == 'error' and v['code'] == 'render_failed', 'любое исключение исполнителя — статус error, поток не умирает')
        q.executor = Fake(st)
        v = wait(q, q.submit(snap('e5'), 'ke5', ip='4.0.0.5')['job'])
        ok(v['status'] == 'done', 'после сбоя рабочий жив')
        q.close()
        # перезапуск: ID и готовое переживают; прерванное — снова в очередь
        st2 = RenderStore(os.path.join(d, 'jobs.json'), os.path.join(d, 'res'))
        st2.load()
        ok(st2.jobs[a['job']]['status'] == 'done', 'готовый результат переживает перезапуск')
        st2.jobs['zz1'] = {'status': 'running', 'ts': time.time(), 'key': 'kz1', 'hash': 'hz1', 'attempts': 1, 'body': {'snap': snap('hz1')}}
        st2.jobs['zz2'] = {'status': 'running', 'ts': time.time(), 'key': 'kz2', 'hash': 'hz2', 'attempts': 2, 'body': {'snap': snap('hz2')}}
        st2.save()
        st3 = RenderStore(os.path.join(d, 'jobs.json'), os.path.join(d, 'res'))
        n = st3.load()
        ok(st3.jobs['zz1']['status'] == 'queued' and n == 1, 'прерванное перезапуском — снова в очереди')
        ok(st3.jobs['zz2']['status'] == 'error' and st3.jobs['zz2']['code'] == 'lost', 'прерванное MAX_ATTEMPTS раз — честный отказ «Повторить»')
        q3 = RenderQueue(st3, Fake(st3))
        q3.start()
        ok(wait(q3, 'zz1')['status'] == 'done', 'очередь после перезапуска досчитывает по тому же номеру')
        q3.close()
        # битый файл
        open(os.path.join(d, 'bad.json'), 'w').write('{битый')
        st4 = RenderStore(os.path.join(d, 'bad.json'), os.path.join(d, 'res'))
        ok(st4.load() == 0 and st4.jobs == {}, 'битый файл — пустой старт без падения')
        # замеры и диапазон
        st5 = RenderStore(os.path.join(d, 'j5.json'), os.path.join(d, 'res5'))
        q5 = RenderQueue(st5, Fake(st5))
        ok(q5.range_sec() == (int(DEFAULT_SEC * 0.8), int(DEFAULT_SEC * 1.6)), 'до замеров — прикидка диапазона')
        st5.durs, st5.dur_ex = [100, 110, 120, 130, 400], ['fake'] * 5
        lo, hi = q5.range_sec()
        ok(lo == 120 and hi == 400, 'после пяти замеров диапазон — p50…p95')
        # диапазон — по исполнителю, который возьмёт заказ СЕЙЧАС (T-24/7 доп.)
        class Sw(Fake):
            name = 'fb'
            now = 'local-cpu'

            def expected(self):
                return self.now
        sw = Sw(st5)
        q6 = RenderQueue(st5, sw)
        st5.durs, st5.dur_ex = [100, 110, 120, 130, 400], ['local-cpu'] * 5
        ok(q6.range_sec() == (120, 400) and q6.stats()['expected'] == 'local-cpu', 'машина не годна — диапазон по замерам процессора')
        sw.now = 'salad-gpu'
        ok(q6.range_sec() == (20, 60) and q6.stats()['range'] == [20, 60] and q6.stats()['expected'] == 'salad-gpu' and q6.stats()['n'] == 0,
           'машина прогрета, замеров машины мало — прикидка 20…60 с, чужие замеры не берём')
        ok(abs(q6.avg_sec() - 40) < 1e-9, 'среднее до замеров машины — прикидка, не 600 с')
        st5.durs += [31, 35, 44, 52, 58]
        st5.dur_ex += ['salad-gpu'] * 5
        ok(q6.range_sec() == (44, 58) and q6.stats()['n'] == 5 and q6.stats()['by_executor']['local-cpu']['n'] == 5, 'пять замеров машины — p50…p95 по ним; по исполнителям — раздельно')
        st5.jobs['e1'] = {'status': 'queued', 'ts': time.time(), 'key': 'ke', 'prio': 0}
        ok(q6.eta('e1')['eta_range'][1] <= 58, 'срок для страницы: на прогретой машине — секунды, не минуты')
        sw.now = 'local-cpu'
        ok(q6.eta('e1')['eta_range'] == [120, 400], 'машину выключили — срок снова по процессору')
        st5.jobs.pop('e1')
        # исполнитель запоминается при готовности (из ответа, иначе — кто ожидался)
        st7 = RenderStore(os.path.join(d, 'j7.json'), os.path.join(d, 'res7'))
        sw7 = Sw(st7)
        sw7.now = 'salad-gpu'
        q7 = RenderQueue(st7, sw7)
        q7.start()
        wait(q7, q7.submit(snap('hx'), 'kx')['job'])
        ok(st7.dur_ex == ['salad-gpu'] and len(st7.durs) == 1, 'замер записан за исполнителем')
        st7b = RenderStore(os.path.join(d, 'j7.json'), os.path.join(d, 'res7'))
        st7b.load()
        ok(st7b.dur_ex == ['salad-gpu'], 'исполнитель замера переживает перезапуск')
        q7.close()
        json.dump({'v': 1, 'jobs': {}, 'durs': [10.0, 20.0]}, open(os.path.join(d, 'old.json'), 'w'))
        st8 = RenderStore(os.path.join(d, 'old.json'), os.path.join(d, 'res8'))
        st8.load()
        ok(st8.dur_ex == ['local-cpu', 'local-cpu'], 'старый файл без исполнителей — замеры процессорные')
        # очистка кэша: лишние каталоги уходят, нужные заданию остаются
        st5.keep_results = 1
        for k in ('a', 'b', 'c'):
            os.makedirs(os.path.join(st5.results_dir, k))
            time.sleep(0.01)
        st5.jobs['x'] = {'status': 'queued', 'key': 'a', 'ts': time.time()}
        st5.trim_results()
        left = sorted(os.listdir(st5.results_dir))
        ok('a' in left and 'c' in left and 'b' not in left, 'кэш кадров: лишнее убрано, нужное открытому заданию — нет')
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print('итог:', 'чисто' if not bad else f'{bad} провал(ов)')
    return 1 if bad else 0


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(_selftest())
