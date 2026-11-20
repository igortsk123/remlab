"""Очередь прогонов покраски StableGen — ОДНА на RunPod (`sg_runpod.py`) и Salad (`sg_salad.py`), чтобы правила не дублировались (T-20261119-90/12, директор 20.11).

Что делает (после того как нода готова и мост поднят):
  • стартует следующий товар, как только у предыдущего кончилась генерация на ноде (status.json: stage bake/export) — нода НЕ ждёт локального запекания («перекрытие»);
  • сторож запекания: bake дольше BAKE_EXPECT_S × BAKE_WATCH_FACTOR → процесс убит, товар помечен «запекание зависло»;
  • тайм-аут прогона целиком (job_timeout_s), строка хода раз в 10 минут;
  • «проба»: пока ни один товар не удался, ПЕРВАЯ неудача останавливает группу (stop «probe_failed»); потом — FAIL_STREAK неудач подряд (stop «failures»);
  • ворота между товарами (gate) — необязательно.
Драйвер ноды даёт три вещи: `start(key, var, t)` → прогон (словарь с key/variant/label/dir/proc/started/last_say; в нём стоп «форма без UV» — это `sg_salad.build_cfg`),
`finish(it, rc, t)` → (ok, доп. поля записи) и `say`. Остановка по деньгам/времени/здоровью ноды и её удаление — в драйвере ноды (они разные у RunPod и Salad)."""
from __future__ import annotations

import json
import os
import shutil

BAKE_EXPECT_S, BAKE_WATCH_FACTOR = 300, 3                  # ожидаемое запекание ≈4–5 мин (комод 226 с); дольше 3× — зависло (T-90/11: форма без UV крутилась 55 мин)
FAIL_STREAK = 2
MIN_FREE_GB = 1.5                                          # сторож места (директор 20.11): меньше — новый товар не даём, группу гасим, строка «диск»
SLIM_DROP = ('session.blend',)                             # после успешного прогона: сессия Blender (≈96 МБ из 125) не нужна; остаются painted.glb, 8 видов (generated), cfg, журналы
SLIM_DROP_DIRS = ('inpaint', 'controlnet', 'baked')        # промежуточные копии внутри sg-output/<сцена>/<время>/


def slim_run(d: str) -> int:
    """Убрать тяжёлое промежуточное из папки УСПЕШНОГО прогона; вернёт освобождённые байты. Ошибки удаления — молча (не ронять драйвер)."""
    freed = 0
    for f in SLIM_DROP:
        p = os.path.join(d, 'blender', f)
        if os.path.isfile(p):
            freed += os.path.getsize(p)
            try:
                os.remove(p)
            except OSError:
                freed -= os.path.getsize(p) if os.path.exists(p) else 0
    root = os.path.join(d, 'blender', 'sg-output')
    for dp, dns, _fn in os.walk(root):
        for dn in list(dns):
            if dn in SLIM_DROP_DIRS:
                p = os.path.join(dp, dn)
                freed += sum(os.path.getsize(os.path.join(a, b)) for a, _x, bs in os.walk(p) for b in bs)
                shutil.rmtree(p, ignore_errors=True)
                dns.remove(dn)
    return freed


def free_gb(path: str = '/home') -> float:
    return shutil.disk_usage(path).free / 2 ** 30


def bake_started_at(it: dict) -> float | None:
    """Когда у прогона начался шаг bake (часы драйвера): старт прогона + время шага из status.json; None — ещё не дошёл."""
    try:
        steps = json.load(open(os.path.join(it['dir'], 'blender', 'status.json'), encoding='utf-8')).get('steps') or []
    except (OSError, ValueError):
        return None
    return next((it['started'] + float(t_rel) for t_rel, name in steps if name == 'bake'), None)


def stage_of(it: dict) -> str:
    try:
        return json.load(open(os.path.join(it['dir'], 'blender', 'status.json'), encoding='utf-8')).get('stage') or ''
    except (OSError, ValueError):
        return ''


class RunQueue:
    def __init__(self, runs, summary: dict, *, start, finish, say, progress, job_timeout_s: float, gate=None, fail_streak: int = FAIL_STREAK, free_gb=free_gb, min_free_gb: float = MIN_FREE_GB):
        self.pending, self.summary = list(runs), summary
        self.start, self.finish, self.say, self.progress, self.gate = start, finish, say, progress, gate
        self.job_timeout_s, self.fail_streak_max = job_timeout_s, fail_streak
        self.free_gb, self.min_free_gb = free_gb, min_free_gb
        self.cur, self.baking = None, []
        self.fail_streak, self.ever_ok = 0, False
        summary.setdefault('runs', [])
        summary.setdefault('failed', 0)

    @property
    def done(self) -> bool:
        return not self.pending and self.cur is None and not self.baking

    def procs(self) -> list:
        return [x['proc'] for x in ([self.cur] if self.cur else []) + self.baking]

    def step(self, t: float, cost: float = 0.0, cap: float = 0.0) -> str | None:
        """Один шаг. Возвращает причину остановки группы или None."""
        if self.pending and self.free_gb() < self.min_free_gb:
            self.say(f'!! диск: свободно {self.free_gb():.1f} ГБ < {self.min_free_gb} — новый товар не даю, группу гашу (осталось {len(self.pending)} в очереди)')
            self.summary['disk_low'] = True
            return 'disk'
        if self.cur is None and self.pending:
            g = self.gate(t, len(self.summary['runs'])) if self.gate else 'go'
            if g == 'stop':
                return 'gate_stop'
            if g == 'go':
                key, var = self.pending.pop(0)
                self.cur = self.start(key, var, t)
                self.say('прогон', key, var, '→', self.cur['dir'])
        if self.cur is not None and self.gate is None and stage_of(self.cur) in ('bake', 'export'):
            self.baking.append(self.cur)                   # генерация на ноде кончилась — нода свободна, следующий товар стартует на следующем шаге
            self.say('нода свободна (идёт запекание', self.cur['key'], self.cur['variant'], 'локально) — следующий товар на ноду')
            self.cur = None
        for it in ([self.cur] if self.cur is not None else []) + list(self.baking):
            rc = it['proc'].poll()
            if rc is None and t - it['last_say'] >= 600:
                it['last_say'] = t
                self.say(self.progress(f'{it["key"]} {it["variant"]}: {stage_of(it) or "старт Blender"}', cost, cap))
            if rc is None:
                bs = bake_started_at(it)
                if bs is not None and t - bs > BAKE_EXPECT_S * BAKE_WATCH_FACTOR:               # сторож: запекание зависло — убить, нода берёт следующий
                    it['proc'].terminate()
                    it['bake_hung'] = True
                    self.say(f'!! запекание зависло: {it["key"]} {it["variant"]} идёт {(t - bs) / 60:.0f} мин при ожидаемых {BAKE_EXPECT_S / 60:.0f} — убиваю')
                    rc = -2
            if rc is None and t - it['started'] > self.job_timeout_s:
                it['proc'].terminate()
                self.say(f'!! прогон не закончился за {self.job_timeout_s / 60:.0f} мин — прерываю')
                rc = -1
            if rc is None:
                continue
            glb = os.path.join(it['dir'], 'blender', 'painted.glb')
            ok, extra = self.finish(it, rc, t)
            rec = {'key': it['key'], 'variant': it['variant'], 'label': it['label'], 'dir': it['dir'], 'rc': rc, 'ok': ok, **extra, 'seconds': round(t - it['started'], 1), 'glb': glb if ok else None}
            if it.get('bake_hung'):
                rec['note'] = 'запекание зависло'
            if ok:
                freed = slim_run(it['dir'])
                rec['freed_mb'] = round(freed / 2 ** 20)
            self.summary['runs'].append(rec)
            self.summary['failed'] += not ok
            self.say('прогон', it['key'], it['variant'], 'ГОТОВО' if ok else f'УПАЛ (rc={rc}, смотри {it["dir"]}/run.log)', f'{rec["seconds"]} с')
            self.fail_streak = 0 if ok else self.fail_streak + 1
            probe = not ok and not self.ever_ok
            self.ever_ok = self.ever_ok or ok
            if it is self.cur:
                self.cur = None
            else:
                self.baking.remove(it)
            if probe:
                self.say('!! проба не удалась (первый товар) — стоп группы, разбор')
                return 'probe_failed'
            if self.fail_streak >= self.fail_streak_max:
                self.say(f'!! {self.fail_streak_max} прогона подряд упали — стоп (чинить в коде, не жечь деньги)')
                return 'failures'
        return None
