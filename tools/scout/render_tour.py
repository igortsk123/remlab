#!/usr/bin/env python3
"""ТУР → ФОТО ВСЕХ КОМНАТ И СТИЛЕЙ, МАШИНА ПРОГРЕТА С ПЕРВОЙ СЕКУНДЫ (T-20261118-20/13/2; план `tour-render-01`, слово владельца 18.11 TG 1867–1874:
«нет фото — рендер всегда; при создании тура всегда рендеры; как только фото планировки получено — включаешь, пока мебель расставляется машина прогрета; норматив 5 минут»).

Два крючка воркера тура (DEV, `tools/floorplan/worker.py`) и один поток сервиса кадров (DEV, `draft_service.py`) — связь между ними ФАЙЛАМИ в папке `SPOOL` (одна машина, одна
учётка; секретов не нужно: у сервиса кадров на DEV нет `INTERNAL_API_TOKEN`, у воркера нет ключа сервиса — маршрут с ключом на DEV не заработал бы):

  ① «ФОТО ПОЛУЧЕНО» — воркер взял задание (или пересборку «Обустроить»/правку): `begin(jid)` — метка `<jid>.active` + в фоне `render_machine.py on --by tour-<8 знаков>`
     (контроллер сам: уже включена — только метка/продление, предел дня — отказ строкой). Сбой — строка в журнал, тур не трогает.
  ② «ВЕРСИЯ ТУРА ПРИНЯТА» — после каждой принятой версии данных (v1 серая → v2 гостиная → v3 всё) воркер кладёт её в SPOOL: `publish(jid, bytes, tag)`.
     Поток сервиса (`TourWarmer`) каждые `poll_s` с забирает запросы, строит снимки ВСЕХ вариантов комнат, где «фото можно» (`apartment_rooms[].photo_ok`, как проверка заказа
     `lib/trial/repo-photo.ts:photoRoomProblem`), берёт ключ кадра тем же путём, что страница и заказ (`render_exec.frame_key_of`), и ставит недостающие в очередь заготовок
     (`RenderQueue.submit(..., warm=True, wprio=1, ttl_s)`: после заказов людей, раньше заготовки витрины, только на машине рендера). Готовые (кэш) — не ставит, дубли отсеивает очередь.
     Версия 2 (гостиная) → кадры гостиной, пока считаются спальни; версия 3 → остальные.
  ③ КОНЕЦ — воркер закончил: `finish(jid)` снимает метку. Машину, включённую туром (`state.by` класса `tour`), поток выключает сразу (как заготовка), когда: нет живых меток туров, нет
     запросов в SPOOL, нет заготовок в очереди, людям она не нужна (`human_recent`) и `off_idle_s` с последнего дела — иначе общий автостоп (20 мин). Жил дольше `active_stale_s` без
     обновления — метка не в счёт (воркер упал).
  Срок жизни заготовки тура в очереди — `ttl_s` (30 мин): не дождалась машины (потолок дня, машина не поднялась) — снимается строкой в журнал, не висит вечно.
  Предел дня — главный: машина отказала потолком — заготовки не ставим (строка в журнал и в статус), страница честно видит `machine.state` через `check` (`render_exec.machine_info`).

Никаких особых случаев под тур/комнату/товар. Правила — `tools/scout/rules/salad-groups.json` → `render_machine.tour` (нет ключа — DEFAULTS ниже; `enabled: 0` — всё выключено).
Самопроверка: `tools/scout/render_gpu/tests_render_tour.py`."""
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'render_gpu')]

SPOOL = os.environ.get('RENDER_TOUR_SPOOL') or os.path.expanduser('~/scout-cache/tour-warm')
TRIAL_ROOT = os.environ.get('TRIAL_WORK_DIR') or os.path.expanduser('~/remlab-logs/trial')
TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{22}$')          # = tools/floorplan/worker.py:TOKEN_RE — номер задания
DEFAULTS = {'enabled': 1, 'on_claim': 1, 'warm': 1, 'ttl_s': 1800, 'poll_s': 3, 'off_idle_s': 120, 'active_stale_s': 2400, 'max_variants': 80, 'on_timeout_s': 180}
RM_SCRIPT = os.path.join(HERE, 'render_gpu', 'render_machine.py')


def tour_rules(rules: dict | None = None) -> dict:
    """Правила тура: DEFAULTS + `render_machine.tour` из `salad-gpu.json`; без файла правил — DEFAULTS."""
    r = dict(DEFAULTS)
    try:
        if rules is None:
            import render_machine as RM
            rules = RM.load_rules()
        r.update((rules or {}).get('tour') or {})
    except Exception:  # noqa: BLE001 — правила не читаются: работаем по умолчанию, тур не страдает
        pass
    return r


def by_label(jid: str) -> str:
    return 'tour-' + str(jid)[:8]


def _atomic(path: str, data: bytes) -> None:
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


# ——— сторона воркера (только stdlib: воркер живёт в своём процессе)
def machine_on(jid: str, python: str, log=print, runner=None, spool: str = SPOOL) -> str:
    """Включить машину с меткой тура: `render_machine.py on --by tour-<id>`. → `started|already|refused|error`; текст ответа и итог — в журнал и в метку `<jid>.active`.
    Исход по тексту контроллера (`tr('on_*')`): «Не включаю» — отказ (предел дня / образ), «Не получилось» — сбой; иначе включена/уже включена."""
    by = by_label(jid)
    t0 = time.time()
    try:
        if runner is not None:
            txt = str(runner([python, RM_SCRIPT, 'on', '--by', by]))
        else:
            r = subprocess.run([python, RM_SCRIPT, 'on', '--by', by], capture_output=True, text=True, timeout=float(tour_rules()['on_timeout_s']))
            txt = (r.stdout or r.stderr or '').strip()
    except Exception as e:  # noqa: BLE001 — сбой включения не роняет разбор тура
        txt = f'{type(e).__name__}: {e}'
        out = 'error'
    else:
        out = 'refused' if txt.startswith('Не включаю') or txt.startswith('Not starting') else 'error' if (txt.startswith('Не получилось') or txt.startswith('Could not')) \
            else 'already' if ('уже включена' in txt or 'already' in txt.lower()) else 'started'
    log(f'тур {jid}: фото получено — машина рендера ({by}) → {out} за {time.time() - t0:.1f} с: {txt[:160]}')
    _mark(jid, spool, machine=out)
    return out


def _mark(jid: str, spool: str, **kw) -> None:
    try:
        os.makedirs(spool, exist_ok=True)
        p = os.path.join(spool, f'{jid}.active')
        cur = {}
        try:
            cur = json.load(open(p, encoding='utf-8'))
        except (OSError, ValueError):
            pass
        cur.update(ts=round(time.time()), by=by_label(jid), **kw)
        _atomic(p, json.dumps(cur, ensure_ascii=False).encode('utf-8'))
    except OSError:
        pass


def begin(jid: str, python: str, log=print, runner=None, spool: str = SPOOL, rules: dict | None = None):
    """КРЮЧОК ① — задание/пересборка взяты воркером. Метка «тур идёт» и включение машины в фоне. → поток включения (None — крючок выключен). Не бросает."""
    try:
        r = tour_rules(rules)
        if not int(r['enabled']) or not TOKEN_RE.match(str(jid)):
            return None
        _mark(jid, spool, machine='pending')
        if not int(r['on_claim']):
            return None
        t = threading.Thread(target=machine_on, args=(jid, python, log, runner, spool), name=f'tour-on-{jid[:6]}', daemon=True)
        t.start()
        return t
    except Exception as e:  # noqa: BLE001
        log(f'тур {jid}: крючок «фото получено» не сработал: {e!r}')
        return None


def publish(jid: str, data: bytes, tag: str, log=print, spool: str = SPOOL, rules: dict | None = None) -> bool:
    """КРЮЧОК ② — версия данных тура принята сервером: кладём в SPOOL (поток сервиса кадров поставит рендеры). Побеждает последняя версия: в ней всё, что было до. Не бросает."""
    try:
        r = tour_rules(rules)
        if not int(r['enabled']) or not int(r['warm']) or not TOKEN_RE.match(str(jid)):
            return False
        os.makedirs(spool, exist_ok=True)
        b = os.path.join(spool, f'{jid}.{int(time.time() * 1000)}.bundle.json')          # своё имя на каждую версию: быстрый следующий запрос не теряет данные прежнего
        _atomic(b, data)
        _atomic(os.path.join(spool, f'{jid}.req.json'), json.dumps({'jid': jid, 'tag': str(tag)[:40], 'bundle': os.path.basename(b), 'ts': round(time.time())}).encode('utf-8'))
        _mark(jid, spool)
        return True
    except Exception as e:  # noqa: BLE001
        log(f'тур {jid}: крючок «версия принята» не сработал: {e!r}')
        return False


def finish(jid: str, spool: str = SPOOL) -> None:
    """КРЮЧОК ③ — воркер закончил с заданием: метка «тур идёт» снимается (после неё поток вправе выключить машину, когда очередь пуста)."""
    try:
        os.remove(os.path.join(spool, f'{jid}.active'))
    except OSError:
        pass


# ——— сторона сервиса кадров
def eligible_snaps(data: dict, label: str, log=print, limit: int = 80) -> list:
    """Снимки вариантов тура, которым можно фото: комната с `photo_ok` в данных (как `photoRoomProblem` на заказе). → [(метка, снимок)]; не принятый контрактом — пропуск со строкой."""
    import render_snapshot as RS
    rooms = {str(r.get('id')) for r in (data.get('apartment_rooms') or []) if isinstance(r, dict) and r.get('photo_ok') is True}
    out = []
    for v in data.get('variants') or []:
        if not isinstance(v, dict) or not v.get('id') or str(v.get('room_id') or 'living') not in rooms:
            continue
        if len(out) >= limit:
            log(f'  {label}: вариантов больше {limit} — остальные не греем')
            break
        try:
            out.append((f'{label}/{v["id"]}', RS.canonicalize(data, {'v': RS.SNAPSHOT_VERSION, 'variant_id': v['id']}, 'trial')))
        except RS.SnapshotError as e:
            log(f'  {label}/{v["id"]}: снимок не принят ({e.code}) — не греем')
    return out


def by_rounds(snaps: list) -> list:
    """ПОРЯДОК ПОСТАНОВКИ ПО КРУГАМ КОМНАТ (T-20261118-22/3, R6 tour-speed-01): первый вариант КАЖДОЙ комнаты, потом второй каждой и так далее (комнаты — в порядке данных, варианты
    комнаты — тоже). Очередь заготовок берёт по приходу, и раньше четыре спальни шли одна за другой: у последней первое фото было после 18 чужих кадров (≈4 мин), теперь — после 4.
    Набор кадров и их число те же (деньги и порядок оплаты не меняются), меняется только очерёдность; комната без варианта кадр не отнимает. → [(метка, снимок)]."""
    rooms: dict = {}
    for item in snaps:
        rooms.setdefault(str((item[1].get('variant') or {}).get('room_id') or 'living'), []).append(item)
    out, i = [], 0
    while any(i < len(v) for v in rooms.values()):
        out += [v[i] for v in rooms.values() if i < len(v)]
        i += 1
    return out


def recent_job_bundles(root: str = TRIAL_ROOT, max_age_s: float = 86400.0, max_jobs: int = 5) -> list:
    """ЗАПАСНОЙ ПУТЬ (`prewarm.tours_max`): свежие задания в папках воркера — последняя версия данных каждого (`bundle-<n>-<тег>.json` с наибольшим n в самой свежей попытке).
    → [(метка, путь)], свежие сперва. Нет папки / нечего читать — пусто."""
    import glob
    now = time.time()
    found = []
    try:
        names = [n for n in os.listdir(root) if TOKEN_RE.match(n) and os.path.isdir(os.path.join(root, n))]
    except OSError:
        return []
    for n in names:
        best = None
        for p in glob.glob(os.path.join(root, n, '*', 'bundle-*.json')):
            m = re.search(r'bundle-(\d+)-', os.path.basename(p))
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            if m and now - mt <= max_age_s and (best is None or mt > best[0] or (mt == best[0] and int(m.group(1)) > best[2])):
                best = (mt, p, int(m.group(1)))
        if best:
            found.append((best[0], f'tour:{n}', best[1]))
    return [(lb, p) for _, lb, p in sorted(found, reverse=True)[:max_jobs]]


class TourWarmer:
    """Поток сервиса кадров: запросы воркера → заготовки рендеров тура; выключение машины, включённой туром. Всё внешнее — параметры (очередь, машина, часы) — проверяется без сети."""

    def __init__(self, queue, executor, versions: dict, machine, legacy_fn, spool: str = SPOOL, now=time.time, sleep=time.sleep, log=print, rules_fn=None):
        self.q, self.ex, self.versions, self.m, self.legacy_fn = queue, executor, versions, machine, legacy_fn
        self.spool, self.now, self.sleep, self.log = spool, now, sleep, log
        self.rules_fn = rules_fn or (lambda: tour_rules(self.m.rules()))
        self.stop = False
        self.status: dict = {}                 # jid → последний итог постановки (для журнала и статуса)

    # ——— постановка
    def ingest(self, jid: str, bundle_path: str, ttl_s: float, limit: int) -> dict:
        """Данные версии → заготовки. → {'jid', 'variants', 'have', 'queued', 'skipped', 'state'}; state: ok | cap | no_data."""
        import log_stamp as LS
        with LS.context(tour=f'tour:{jid}'):                    # строки постановки — с номером тура (T-20261118-22/8)
            return self._ingest(jid, bundle_path, ttl_s, limit)

    def _ingest(self, jid: str, bundle_path: str, ttl_s: float, limit: int) -> dict:
        import render_exec as RX
        try:
            data = json.load(open(bundle_path, encoding='utf-8'))
        except (OSError, ValueError) as e:
            self.log(f'тур {jid}: данные версии не читаются ({e!r})')
            return {'jid': jid, 'state': 'no_data', 'variants': 0, 'have': 0, 'queued': 0, 'skipped': 0}
        snaps = by_rounds(eligible_snaps(data, f'tour:{jid}', self.log, limit))
        res = {'jid': jid, 'state': 'ok', 'variants': len(snaps), 'have': 0, 'queued': 0, 'skipped': 0}
        if snaps and self.cap_reached():
            res['state'] = 'cap'
            self.log(f'тур {jid}: потолок дня на машине исчерпан — {len(snaps)} фото не ставлю (страница покажет 3D и «Сделать фото»)')
            return res
        for label, snap in snaps:
            try:
                key = RX.frame_key_of(snap, self.versions)
            except RX.RenderError as e:
                res['skipped'] += 1
                self.log(f'тур {label}: ключ кадра не получен ({e.code}) — не ставлю')
                continue
            if self.q.store.cached(key) is not None:
                res['have'] += 1
                continue
            if self.q.store.brak_of(key) is not None:
                res['skipped'] += 1
                continue
            try:
                r = self.q.submit(snap, key, tour=f'tour:{jid}', legacy=self.legacy_fn(snap), warm=True, wprio=1, ttl_s=ttl_s)
                res['queued' if not r.get('deduped') else 'have'] += 1
            except Exception as e:  # noqa: BLE001
                res['skipped'] += 1
                self.log(f'тур {label}: не поставлена — {e!r}')
        self.log(f'тур {jid}: фото в заготовки — вариантов {res["variants"]}, уже готово/в очереди {res["have"]}, поставлено {res["queued"]}, пропущено {res["skipped"]}')
        return res

    def cap_reached(self) -> bool:
        try:
            import render_machine as RM
            s, r = self.m.state() or {}, self.m.rules()
            return s.get('spent_date') == RM.london_date(self.now()) and float(s.get('spent_usd') or 0) >= float(r.get('day_cap_usd', 1e9)) and s.get('desired') != 'on'
        except Exception:  # noqa: BLE001
            return False

    def pending(self) -> list:
        try:
            return sorted(n for n in os.listdir(self.spool) if n.endswith('.req.json'))
        except OSError:
            return []

    def actives(self, stale_s: float) -> list:
        out = []
        try:
            for n in os.listdir(self.spool):
                if n.endswith('.active') and self.now() - os.path.getmtime(os.path.join(self.spool, n)) <= stale_s:
                    out.append(n[:-7])
        except OSError:
            pass
        return out

    def take(self, name: str):
        """Забрать запрос атомарным переименованием (воркер к этому моменту мог положить новый — он останется для следующего прохода). → (jid, путь данных) | None."""
        src = os.path.join(self.spool, name)
        dst = src + '.taken'
        try:
            os.replace(src, dst)
            req = json.load(open(dst, encoding='utf-8'))
            os.remove(dst)
        except (OSError, ValueError):
            return None
        jid = str(req.get('jid') or '')
        b = os.path.basename(str(req.get('bundle') or ''))
        if not TOKEN_RE.match(jid) or not (b.startswith(jid + '.') and b.endswith('.bundle.json')):
            self.log(f'тур: запрос {name} с неверным номером/файлом — пропуск')
            return None
        return jid, os.path.join(self.spool, b)

    # ——— выключение
    def maybe_off(self, tr: dict) -> str:
        """Машину включил тур (`state.by` класса `tour`), дело сделано, людям не нужна → выключаем сразу. → '' | строка про выключение."""
        win = float(tr.get('off_idle_s') or 0)
        if win <= 0:
            return ''
        import render_machine as RM
        from render_prewarm import human_recent
        st = self.m.state() or {}
        if st.get('desired') != 'on' or RM.by_class(st.get('by')) != 'tour':
            return ''
        c = self.q.warm_counts()
        if c['queued'] + c['running'] or self.pending() or self.actives(float(tr['active_stale_s'])) or human_recent(self.q, self.now(), win):
            return ''
        if self.now() - float(st.get('last_activity') or 0) < win:
            return ''                                      # последнее дело на машине было только что — подождём окно (второй тур/заказ подряд не ждёт холодного старта)
        try:
            txt = self.m.turn_off('tour-warm')
        except Exception as e:  # noqa: BLE001
            self.log(f'тур: выключение машины не вышло ({e!r}) — останется автостоп')
            return ''
        self.log(f'тур: машину включил тур ({st.get("by")}), заготовок нет, людей нет {int(win)} с — выключаю сразу → {txt}')
        return txt

    # ——— проход и поток
    def expire(self) -> int:
        f = getattr(self.q, 'expire_warm', None)
        return f() if callable(f) else 0

    def once(self) -> dict:
        tr = self.rules_fn()
        if not int(tr.get('enabled', 1)):
            return {'state': 'disabled'}
        done = []
        for name in self.pending():
            got = self.take(name)
            if got:
                jid, path = got
                done.append(self.ingest(jid, path, float(tr['ttl_s']), int(tr['max_variants'])))
                self.status[jid] = done[-1]
                try:
                    os.remove(path)
                except OSError:
                    pass
        self.expire()
        off = self.maybe_off(tr)
        return {'state': 'ok', 'ingested': done, 'off': off}

    def run_forever(self) -> None:
        clean_spool(self.spool)
        while not self.stop:
            try:
                self.once()
            except BaseException as e:  # noqa: BLE001 — любой сбой — в журнал, поток не умирает молча (урок 13.10)
                self.log(f'тур: сбой прохода {e!r}')
            self.sleep(float(self.rules_fn().get('poll_s', 3)))

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, name='render-tour-warm', daemon=True)
        t.start()
        return t


def clean_spool(spool: str = SPOOL, older_s: float = 86400.0) -> int:
    """Старые остатки (упавший воркер): данные/запросы/метки старше суток — убрать."""
    n = 0
    try:
        for f in os.listdir(spool):
            p = os.path.join(spool, f)
            if time.time() - os.path.getmtime(p) > older_s:
                os.remove(p)
                n += 1
    except OSError:
        pass
    return n
