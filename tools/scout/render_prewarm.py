#!/usr/bin/env python3
"""ЗАГОТОВКА КАДРОВ «СДЕЛАТЬ ФОТО» (T-20261118-07, слово владельца 18.11: «первый заказ автоматом должен идти, делаем рендеры по всем комнатам»).

Зачем: покупатель не ждёт «холодные» 25–40 с первого заказа. После каждого обновления кода рендера (меняется ключ кэша: пресет, программа, выгрузчики, Blender) и при
новом варианте витрины/тура программа САМА считает «Сделать фото» для каждой комнаты, кадры ложатся в тот же кэш (`RenderStore.cached` по ключу `render_exec.cache_key`);
заказ покупателя с нетронутой расстановкой — мгновенный `done` из кэша (`RenderQueue.submit`).

Как (поток внутри сервиса кадров, `draft_service`; запускается при старте, повторяет проход каждые `prewarm.interval_s`):
  1. Список комнат — сцены витрины /demo (`demo-data.json`, тот же файл, что читает сервис) и, если `prewarm.tours_max` > 0, свежие туры (`showcase_assets.build_scenes`);
     снимок каждой — «как заказ без своей расстановки» (предметы и ракурсы варианта).
  2. «Чего нет под текущим ключом» — `store.cached(cache_key(scene_hash, versions)) is None` (и комната не падала `prewarm.fail_max` раз подряд).
  3. Деньги: заготовке — `prewarm.day_share` дневного потолка машины (`day_cap_usd`) по её СОБСТВЕННОМУ расходу (`spent_by.prewarm` контроллера, T-20261118-20/12), общий предел дня — главный; число комнат, которое влезает, считается по цене часа машины и
     среднему замеру GPU. Не влезает всё — делаем сколько влезло и пишем строку в статус машины (`render_machine.py status`: «Заготовка кадров: …»).
  4. Машина выключена — включаем её тем же путём, что кнопка бота (`render_machine.py on --by prewarm`, предел дня и замок — в контроллере), ждём прогрева; выключит автостоп по простою.
  4б. Выключение: машину включила заготовка (`state.by == 'prewarm'`), недостающего нет, очередь пуста и `off_idle_s` (2 мин) не было заказа людей, который считали бы на машине —
     выключаем сразу (`render_machine.py off`), не ждём автостопа 20 мин (он дороже самого прохода). Заказ людей был — оставляем обычный автостоп. 0 в правилах — не выключать.
  5. Заготовки ставятся в очередь пачками (`prewarm.batch`) с признаком `warm`: после заказов людей, без пределов покупателя и мест в их очереди, считаются ТОЛЬКО на машине
     рендера (`RenderQueue.warm_ok`) — запасного исполнителя (процессор DEV) у них нет; машину погасили посреди прохода — заготовка ждёт в очереди, а не падает.
Никаких особых случаев под комнату или тур: один и тот же путь для всех. Текстов для покупателя нет — только строка статуса машины.

Самопроверка: `tools/scout/render_gpu/tests_render_prewarm.py`."""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'render_gpu'), os.path.join(HERE, 'salad')]

STATUS_FILE = os.environ.get('RENDER_PREWARM_STATUS') or os.path.expanduser('~/scout-cache/render-prewarm.json')
DEMO_DATA = os.environ.get('DEMO_DATA_FILE') or os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
DEFAULTS = {'day_share': 0.6, 'interval_s': 300, 'start_delay_s': 90, 'batch': 4, 'tours_max': 0, 'fail_max': 2, 'off_idle_s': 120, 'hot_refresh': 1}
WARMUP_COST_MIN = 5.0          # прогрев машины — платный: закладываем в расчёт, когда она выключена


class Prewarmer:
    """Один проход — `once()`; поток — `run_forever()`. Всё внешнее (очередь, исполнитель, машина, источник сцен) — параметры, чтобы проверять без сети и платного."""

    def __init__(self, queue, executor, versions: dict, machine, legacy_fn, scenes_fn=None, now=time.time, sleep=time.sleep, log=print):
        self.q, self.ex, self.versions, self.m, self.legacy_fn = queue, executor, versions, machine, legacy_fn
        self.scenes_fn = scenes_fn or self.default_scenes
        self.now, self.sleep, self.log = now, sleep, log
        self.stop = False
        self.failed: dict = {}                 # ключ → сколько раз заготовка не дала кадров
        self.noted: set = set()                # ключи, брак которых уже записан в журнал (строка — один раз на ключ и версию сторожа)
        self.on_tries: dict = {}               # дата по Лондону → сколько раз включали машину
        self.status: dict = {'state': 'start', 'ts': 0}
        self.hot_key = None                    # под какими версиями рендера и данными витрины горячий список приёмника записан в последний раз (T-20261118-09/8)
        self.hot_fn = None                     # подмена для проверок: (исполнитель) → код выхода showcase_assets

    # ——— что считать
    def rules(self) -> dict:
        r = self.m.rules()
        pw = dict(DEFAULTS)
        pw.update(r.get('prewarm') or {})
        return {'machine': r, 'pw': pw}

    def default_scenes(self, pw: dict) -> list:
        import showcase_assets as SA
        tours = int(pw.get('tours_max') or 0)
        return SA.build_scenes(DEMO_DATA, SA.REISSUE_ROOT, tours or None, demo_only=tours <= 0, log=self.log)

    def missing(self, scenes: list, pw: dict) -> list:
        import render_exec as RX
        out = []
        for label, snap in scenes:
            key = RX.cache_key(snap['scene_hash'], self.versions)
            if self.q.store.cached(key) is None and self.failed.get(key, 0) < int(pw['fail_max']) and self.q.store.brak_of(key) is None:
                out.append((label, snap, key))
        return out

    def braked(self, scenes: list) -> list:
        """Комнаты, чей текущий ключ дал БРАК сторожа (ворота шага 5, T-20261118-03/7): метка в хранилище заданий, она переживает перезапуск и действует, пока не сменится ключ кадров
        или версия сторожа. Такие комнаты заготовка НЕ считает — ни по кругу, ни после перезапуска; строка в журнал — один раз. → [(метка, ключ, находки)]."""
        import render_exec as RX
        out = []
        for label, snap in scenes:
            key = RX.cache_key(snap['scene_hash'], self.versions)
            mk = self.q.store.brak_of(key) if self.q.store.cached(key) is None else None
            if mk:
                out.append((label, key, mk.get('brak') or []))
                if key not in self.noted:
                    self.noted.add(key)
                    self.log(f'заготовка {label}: комната в браке сторожа ({mk.get("where")}): ' + '; '.join(f"{b.get('code')} {b.get('slot') or ''}".strip() for b in (mk.get('brak') or [])[:6])
                             + ' — не пересчитываю, пока не сменится ключ кадров или сторож')
        return out

    # ——— деньги
    def spent_today(self) -> float:
        """Общий расход машины за день по Лондону (все, кто её включал); общий предел дня держит контроллер (`day_cap_usd`)."""
        s = self.m.state() or {}
        import render_machine as RM
        return float(s.get('spent_usd') or 0) if s.get('spent_date') == RM.london_date(self.now()) else 0.0

    def spent_prewarm(self) -> float:
        """СОБСТВЕННЫЙ расход заготовки за день (`spent_by.prewarm`, T-20261118-20/12): потолок `day_share × day_cap_usd` сравнивается с ним, а не с общим расходом
        (заказы людей, пробы рабочих и хвосты простоя заготовку не гасят — 18.11 она встала на $1,20 общих при ≈ $0,4 своих). Поля нет (состояние до этого правила) — 0."""
        s = self.m.state() or {}
        import render_machine as RM
        if s.get('spent_date') != RM.london_date(self.now()):
            return 0.0
        sb = s.get('spent_by')
        return float((sb or {}).get('prewarm') or 0) if isinstance(sb, dict) else 0.0

    def per_room_usd(self, rules: dict) -> float:
        import render_machine as RM
        return RM.price_usd_h(rules) / 3600.0 * max(5.0, self.q.avg_sec('salad-gpu'))

    def affordable(self, rules: dict, pw: dict, n: int, machine_up: bool) -> tuple:
        """→ (сколько комнат влезает, потрачено сегодня, потолок заготовки, цена одной)."""
        cap = float(rules['day_cap_usd']) * float(pw['day_share'])
        spent = self.spent_prewarm()
        per = self.per_room_usd(rules)
        left = min(cap - spent, float(rules['day_cap_usd']) - self.spent_today()) - (0 if machine_up else self._warmup_usd(rules))   # свой потолок и общий предел дня — меньшее
        return (min(n, int(left / per)) if left > 0 and per > 0 else 0), spent, cap, per

    def _warmup_usd(self, rules: dict) -> float:
        import render_machine as RM
        return RM.price_usd_h(rules) * WARMUP_COST_MIN / 60.0

    # ——— состояние
    def put(self, state: str, note: str = '', **kw) -> dict:
        self.status = {'state': state, 'ts': round(self.now()), 'note': note, **kw}
        try:
            os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
            json.dump(self.status, open(STATUS_FILE + '.tmp', 'w', encoding='utf-8'), ensure_ascii=False)
            os.replace(STATUS_FILE + '.tmp', STATUS_FILE)
        except OSError:
            pass
        if note:
            try:
                self.m.set_note(note)
            except Exception as e:  # noqa: BLE001 — строка статуса не обязана ломать проход
                self.log(f'заготовка: строка статуса машины не записана ({e!r})')
        self.log(f'заготовка кадров: {state}' + (f' — {note}' if note else ''))
        return self.status

    def machine_up(self) -> bool:
        f = getattr(self.ex, 'warm_ok', None)
        try:
            return bool(f()) if callable(f) else False
        except Exception:  # noqa: BLE001
            return False

    def human_recent(self, window_s: float) -> bool:
        """Был ли заказ людей, которому нужна машина: в очереди/в работе, или поставлен за `window_s` секунд и считался (не из кэша). Заготовки (`warm`) и отказы не в счёт."""
        now = self.now()
        with self.q.store.lock:
            for j in self.q.store.jobs.values():
                if j.get('warm') or j.get('status') in ('error',):
                    continue
                if j.get('status') in ('queued', 'running'):
                    return True
                if now - float(j.get('ts') or 0) <= window_s and not (j.get('result') or {}).get('cached'):
                    return True
        return False

    def maybe_off(self, pw: dict) -> str:
        """Правило 4б. → '' (не выключали) или строка про выключение."""
        win = float(pw.get('off_idle_s') or 0)
        if win <= 0:
            return ''
        st = self.m.state() or {}
        if st.get('by') != 'prewarm' or st.get('desired') != 'on':
            return ''                                      # включила не заготовка (или уже выключена) — не наша машина
        c = self.q.warm_counts()
        if c['queued'] + c['running'] or self.human_recent(win):
            return ''                                      # людям нужна — обычный автостоп
        try:
            txt = self.m.turn_off('prewarm')
        except Exception as e:  # noqa: BLE001
            self.log(f'заготовка: выключение машины не вышло ({e!r}) — останется автостоп')
            return ''
        self.log(f'заготовка: машину включала заготовка, дело сделано, людей нет {int(win)} с — выключаю сразу → {txt}')
        return ' Машину включала заготовка — выключена сразу, автостоп не ждём.'

    def wait_machine(self, rules: dict, total_min: float) -> bool:
        t_end = self.now() + total_min * 60
        while self.now() < t_end and not self.stop:
            if self.machine_up():
                return True
            self.sleep(10)
        return self.machine_up()

    # ——— проход
    def once(self) -> dict:
        rr = self.rules()
        rules, pw = rr['machine'], rr['pw']
        if not callable(getattr(self.ex, 'warm_ok', None)) and not callable(getattr(getattr(self.ex, 'primary', None), 'warm_ok', None)):
            return self.put('no_gpu', 'Заготовка кадров не работает: у сервиса нет исполнителя «машина рендера».')
        scenes = self.scenes_fn(pw)
        miss = self.missing(scenes, pw)
        total = len(scenes)
        bad = self.braked(scenes)
        bad_note = f' В браке сторожа {len(bad)} (не считаем): ' + ', '.join(str(b[0]) for b in bad[:5]) + '.' if bad else ''
        if not miss:
            off = self.maybe_off(pw)
            if bad:
                return self.put('idle', f'Заготовка кадров: {total - len(bad)} из {total} комнат есть в кэше под текущим ключом.' + bad_note + off, total=total, missing=0, brak=len(bad))
            return self.put('idle', f'Заготовка кадров: все {total} комнат есть в кэше под текущим ключом.' + off, total=total, missing=0)
        up = self.machine_up()
        n_ok, spent, cap, per = self.affordable(rules, pw, len(miss), up)
        if n_ok <= 0:
            return self.put('cap', f'Заготовка кадров остановлена: лимит денег на неё ${cap:.2f} из дня (она потратила ${spent:.2f}, всего за день ${self.spent_today():.2f}); без кадров {len(miss)} из {total} комнат.',
                            total=total, missing=len(miss), spent_usd=round(spent, 3), cap_usd=round(cap, 3))
        if not up:
            day = time.strftime('%Y-%m-%d', time.gmtime(self.now()))
            if self.on_tries.get(day, 0) >= 3:
                return self.put('off', f'Заготовка кадров ждёт: машина не включилась за 3 попытки сегодня; без кадров {len(miss)} из {total} комнат.', total=total, missing=len(miss))
            self.on_tries[day] = self.on_tries.get(day, 0) + 1
            st = self.m.state() or {}
            if st.get('desired') != 'on':
                self.put('starting', f'Заготовка кадров: включаю машину рендера, комнат без кадров {len(miss)} из {total}.', total=total, missing=len(miss))
                txt = self.m.turn_on('prewarm')
                self.log(f'заготовка: включение машины → {txt}')
            if not self.wait_machine(rules, float(rules.get('warmup_max_min', 15)) + 3):
                return self.put('off', f'Заготовка кадров ждёт: машина рендера не прогрелась; без кадров {len(miss)} из {total} комнат.', total=total, missing=len(miss))
        miss = miss[:n_ok]
        t0 = self.now()
        self.put('running', f'Заготовка кадров: считаю {len(miss)} из {total} комнат (≈ ${per * len(miss):.2f}, лимит дня на неё ${cap:.2f}).', total=total, missing=len(miss), spent_usd=round(spent, 3))
        sent, batch = [], max(1, int(pw['batch']))
        for label, snap, key in miss:
            while not self.stop:
                c = self.q.warm_counts()
                if c['queued'] + c['running'] < batch:
                    break
                self.sleep(2)
            if self.stop or not self.machine_up():
                break
            if self.spent_prewarm() >= float(rules['day_cap_usd']) * float(pw['day_share']) or self.spent_today() >= float(rules['day_cap_usd']):
                break
            try:
                self.q.submit(snap, key, tour=label, legacy=self.legacy_fn(snap), warm=True)
                sent.append((label, key))
            except Exception as e:  # noqa: BLE001
                self.log(f'заготовка {label}: не поставлена — {e!r}')
        while not self.stop:                      # ждём хвост очереди заготовок
            c = self.q.warm_counts()
            if c['queued'] + c['running'] == 0 or not self.machine_up():
                break
            self.sleep(3)
        drained = self.q.warm_counts()['queued'] + self.q.warm_counts()['running'] == 0
        got = sum(1 for _, k in sent if self.q.store.cached(k) is not None)
        if drained:                               # очередь заготовок пуста, а кадров нет — это сбой комнаты: после `fail_max` подряд её не берём (брак сторожа — не сбой: у него своя метка)
            for _, k in sent:
                if self.q.store.cached(k) is None and self.q.store.brak_of(k) is None:
                    self.failed[k] = self.failed.get(k, 0) + 1
        remain = len(self.missing(scenes, pw))
        bad = self.braked(scenes)
        bad_note = f' В браке сторожа {len(bad)} (не считаем): ' + ', '.join(str(b[0]) for b in bad[:5]) + '.' if bad else ''
        off = self.maybe_off(pw) if remain == 0 else ''
        spent2 = self.spent_today()
        return self.put('done' if remain == 0 else 'partial',
                        f'Заготовка кадров: готово {got} из {len(sent)} за {round(self.now() - t0)} с, без кадров осталось {remain} из {total}, расход дня ${spent2:.2f}.' + bad_note + off,
                        total=total, missing=remain, got=got, brak=len(bad), sec=round(self.now() - t0), spent_usd=round(spent2, 3))

    def refresh_hot(self, pw: dict) -> str:
        """ГОРЯЧИЙ СПИСОК (T-20261118-09/8): ассеты витрины для подогрева кэша машины — `showcase_assets.py --demo-only` — перезаписывается, когда сменились версии рендера или данные
        витрины (раньше — только при перевыпуске туров; после выкладки кода/ximg 18.11 список остался от 03:46Z, и первый заказ на только что включённой машине докачивал 17–31 ассет
        сам: программа рендера, данные, текстуры). Один раз на ключ (версии + время `demo-data.json`), в фоне между проходами; сцены берутся из кэша подготовки — дёшево.
        Сбой (код 2: приёмник/нечего писать) ключ не закрепляет — повтор на следующем проходе. Выключить: `prewarm.hot_refresh: 0`. → '' | 'ok' | 'fail' | 'skip'."""
        if not int(pw.get('hot_refresh', 1)):
            return 'skip'
        try:
            dm = os.path.getmtime(DEMO_DATA)
        except OSError:
            dm = 0
        key = json.dumps(self.versions, sort_keys=True, default=str) + f'|{dm:.0f}'
        if key == self.hot_key:
            return ''
        ex = getattr(self.ex, 'primary', self.ex)
        try:
            if self.hot_fn is not None:
                rc = self.hot_fn(ex)
            else:
                import showcase_assets as SA
                rc = SA.main(['--demo-only'], ex=ex)
        except BaseException as e:  # noqa: BLE001 — сбой списка не роняет заготовку кадров
            self.log(f'заготовка: горячий список не записан ({e!r})')
            return 'fail'
        if rc in (0, 1):
            self.hot_key = key
            self.log(f'заготовка: горячий список витрины обновлён (код {rc})')
            return 'ok'
        self.log(f'заготовка: горячий список не записан (код {rc}) — повтор на следующем проходе')
        return 'fail'

    def run_forever(self) -> None:
        rr = self.rules()
        self.sleep(float(rr['pw']['start_delay_s']))
        while not self.stop:
            try:
                self.once()
            except BaseException as e:  # noqa: BLE001 — любой сбой — в журнал и в статус, поток не умирает молча (урок 13.10)
                self.log(f'заготовка кадров: сбой прохода {e!r}')
                try:
                    self.put('error', f'Заготовка кадров: сбой прохода ({type(e).__name__}).')
                except Exception:  # noqa: BLE001
                    pass
            try:
                self.refresh_hot(self.rules()['pw'])
            except Exception as e:  # noqa: BLE001
                self.log(f'заготовка: обновление горячего списка — сбой {e!r}')
            self.sleep(float(self.rules()['pw']['interval_s']))

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, name='render-prewarm', daemon=True)
        t.start()
        return t
