#!/usr/bin/env python3
"""НОЧНОЙ ШАГ СТОРОЖА КАДРОВ БЕЗ РЕНДЕРА (render-qa-gate-01, шаг 5 «ночной прогон — охват», T-20261118-03/8). 0 ₽: машину рендера не включаем, Blender не запускаем —
только сборка сцены (процессор) и предпроверка `frame_qa.preflight` по КАЖДОЙ комнате, которую покупатель может заказать.

Что входит (порядок важности): сперва все варианты /demo (`demo-data.json`, 16 комнат), потом комнаты опубликованных туров — по свежести (последняя `bundle-new.json` каждого тура из
прохода перевыпуска; тот же список, что у подогрева витрины `showcase_assets.build_scenes`). Одинаковая сцена (тот же `scene_hash`) в туре и в /demo — одна проверка, вторая строка «как <метка>».
Как проверяем: снимок комнаты «как заказ без своей расстановки» → `SceneExecutor._prepare` (выгрузка и сборка сцены тем же путём, что у заказа; кэш подготовки переиспользуется — свежая сцена
считается ≈30–60 с, из кэша — секунды) → `frame_qa.preflight(dump, scene-export.json, scene)`. Сборка идёт под общей очередью тяжёлых прогонов (`tools/ops/heavy_slot.py`, класс «фон» —
уступает заказам людей). Что уже проверено той же версией сторожа/правил и той же сценой — берём из памяти (`~/scout-cache/qa-night-state.json`), заново не собираем: ночь за ночью охват
сдвигается дальше, если за потолок не успели.
Потолок времени — ДАННЫЕ: `data/flat3d/frame-qa-rules.json:night.maxMinutes` (40) и `night.toursMax` (0 — все туры). Не успели — строки «не дошли», завтра с них продолжим.
Результат: журнал `~/remlab-logs/qa-night/<дата по Лондону>.tsv` (строка на комнату — пишется сразу, не в конце), `last.json` с итогом для обхода директора и краткая сводка в stdout
(чисто / предупреждения / БРАК по классам и слотам). Письма никому и записи в план не пишет: брак доносит директор.

    ~/venvs/scout/bin/python tools/scout/render_gpu/qa_night.py [--list] [--max-min 40] [--tours N] [--demo-only] [--no-state] [--out ПАПКА]
Юнит и таймер (НЕ включены): `tools/ops/systemd/remlab-qa-night.{service,timer}`. Самопроверка: `render_gpu/tests_qa_night.py`."""
import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
PROBE = os.path.join(SCOUT, 'cycles_probe')
sys.path[:0] = [HERE, SCOUT, PROBE, os.path.join(SCOUT, 'salad')]

OUT_DIR = os.environ.get('QA_NIGHT_DIR') or os.path.expanduser('~/remlab-logs/qa-night')
STATE_FILE = os.environ.get('QA_NIGHT_STATE') or os.path.expanduser('~/scout-cache/qa-night-state.json')
STATE_KEEP = 3000
COLS = ['время', 'запуск', 'источник', 'метка', 'сцена', 'вердикт', 'сек', 'очередь с', 'сборка', 'брак (класс слот)', 'предупреждения', 'примечание']


def london_date(now: float | None = None) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(now if now is not None else time.time(), ZoneInfo('Europe/London')).strftime('%Y-%m-%d')


def london_hm(now: float | None = None) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(now if now is not None else time.time(), ZoneInfo('Europe/London')).strftime('%H:%M')


def load_state(path: str | None = None) -> dict:
    path = path or STATE_FILE
    try:
        d = json.load(open(path, encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict, path: str | None = None) -> None:
    path = path or STATE_FILE
    if len(state) > STATE_KEEP:
        for k in sorted(state, key=lambda k: state[k].get('ts', 0))[:len(state) - STATE_KEEP]:
            state.pop(k, None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.tmp-{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, path)


def adapt_tour(o):
    """Публичный бандл тура НЕ несёт `sid` товара (правило `trial_bundle.py:NEVER_KEYS`), только `msid` (файл меша) — снимок заказа его не принимает (`bad_item`, открытая задача «контракт по msid»,
    T-20261118-20/3). Для сторожа достаточно того, что сцену собирают по `msid`, поэтому здесь, в копии данных, `sid := msid`. Когда заказ из тура научится принимать бандл как есть — убрать."""
    if isinstance(o, dict):
        d = {k: adapt_tour(v) for k, v in o.items()}
        if d.get('msid') and not d.get('sid'):
            d['sid'] = d['msid']
        return d
    if isinstance(o, list):
        return [adapt_tour(v) for v in o]
    return o


def snaps(data: dict, source: str, label: str) -> tuple:
    """Снимки ВСЕХ вариантов данных (как заказ без своей расстановки) → ([(источник, метка, снимок)], [(источник, метка, код отказа)]). Отказ снимка — не «чисто»: комнату заказать нельзя
    или нельзя проверить — своя строка в журнале."""
    import render_snapshot as RS
    ok, bad = [], []
    for v in data.get('variants') or []:
        vid = v.get('id')
        if not vid:
            continue
        try:
            ok.append((source, f'{label}/{vid}', RS.canonicalize(data, {'v': RS.SNAPSHOT_VERSION, 'variant_id': vid}, 'demo' if source == 'demo' else 'trial')))
        except RS.SnapshotError as e:
            bad.append((source, f'{label}/{vid}', e.code))
    return ok, bad


def build_scenes(tours: int, demo_only: bool, log=print) -> tuple:
    """→ ([(источник, метка, снимок)], [(источник, метка, код отказа снимка)]): сперва /demo, потом туры по свежести (метка `tour:<8 знаков>/<вариант>`)."""
    import showcase_assets as SA
    ok, bad = [], []
    try:
        o, b = snaps(json.load(open(SA.DEMO_DATA, encoding='utf-8')), 'demo', 'demo')
        ok, bad = ok + o, bad + b
    except (OSError, ValueError) as e:
        log(f'нет данных витрины /demo ({SA.DEMO_DATA}): {e}')
    if not demo_only:
        for label, path in SA.tour_sources(SA.REISSUE_ROOT, tours or None):
            try:
                o, b = snaps(adapt_tour(json.load(open(path, encoding='utf-8'))), 'tour', label)
                ok, bad = ok + o, bad + b
            except (OSError, ValueError) as e:
                log(f'  {label}: данные не читаются ({e})')
    return ok, bad


def fmt(fs: list) -> str:
    return '; '.join(f"{f['code']} {f.get('slot') or ''}".strip() for f in fs)


class Night:
    """Один прогон. Всё внешнее (исполнитель сборки, сторож, правила, часы) — параметры, чтобы проверять без сети, Node и Chromium."""

    def __init__(self, ex, qa, rules: dict, out_dir: str = OUT_DIR, state: dict | None = None, use_state: bool = True, now=time.time, log=print, slot=None):
        self.ex, self.Q, self.rules, self.out_dir, self.now, self.log = ex, qa, rules, out_dir, now, log
        self.slot = slot or self._heavy_slot
        self.state = state if state is not None else {}
        self.use_state = use_state
        self.rows: list = []
        self.t0 = now()
        self.run_id = london_hm(self.t0)
        self.tsv = os.path.join(out_dir, london_date(self.t0) + '.tsv')

    # ——— запись строки в журнал сразу (убили посреди ночи — то, что успели, не потеряно)
    def _write(self, row: dict) -> None:
        os.makedirs(self.out_dir, exist_ok=True)
        new = not os.path.exists(self.tsv)
        with open(self.tsv, 'a', encoding='utf-8') as f:
            if new:
                f.write('\t'.join(COLS) + '\n')
            f.write('\t'.join(str(row.get(c, '')).replace('\t', ' ').replace('\n', ' ') for c in COLS) + '\n')
        self.rows.append(row)

    def _row(self, source, label, snap, verdict, sec=0.0, build='-', errors=(), warns=(), note='', wait=0.0) -> dict:
        return {'время': london_hm(self.now()), 'запуск': self.run_id, 'источник': source, 'метка': label, 'сцена': snap['scene_hash'][:8], 'вердикт': verdict, 'сек': f'{sec:.0f}', 'очередь с': f'{wait:.0f}',
                'сборка': build, 'брак (класс слот)': fmt(errors), 'предупреждения': fmt(warns), 'примечание': note, '_errors': list(errors), '_warns': list(warns)}

    @staticmethod
    def _heavy_slot(label: str, pr: dict):
        """Общая очередь тяжёлых прогонов, класс «фон» (0): уступает заказам людей; ядра — по умолчанию очереди (2)."""
        sys.path.insert(0, os.path.join(SCOUT, '..', 'ops'))
        import heavy_slot as HS
        return HS.heavy_slot(label, min_gb=pr['min_gb'], cores=2, prio=0)

    def _state_key(self, snap: dict, pr: dict) -> str | None:
        try:
            pk = self.ex._prep_key(snap, self.ex._bundle(os.path.join(self.ex.work, 'qa-night.log')), pr)
        except Exception:  # noqa: BLE001 — нет ключа подготовки: память прогонов не используем, считаем как есть
            return None
        return f"{pk}:{self.sig}"

    def check(self, source: str, label: str, snap: dict, pr: dict) -> dict:
        t = time.time()
        sk = self._state_key(snap, pr) if self.use_state else None
        mem = self.state.get(sk) if sk else None
        if mem:
            return self._row(source, label, snap, mem['verdict'], 0, 'из памяти', mem.get('errors') or [], mem.get('warns') or [], f"проверено {mem.get('date', '?')} той же сценой и версией сторожа")
        job = self.ex._job_dir('gjob-q-', snap)
        shutil.rmtree(job, ignore_errors=True)
        os.makedirs(job)
        wait = 0.0
        try:
            timing: dict = {}
            with self.slot('qa-night-' + snap['scene_hash'][:8], pr) as info:
                wait = float((info or {}).get('waited_s') or 0)
                dump = self.ex._prepare(snap, job, os.path.join(job, 'run.log'), pr, lambda s: None, timing)
            rep = self.Q.preflight(dump, os.path.join(dump, 'scene-export.json'), os.path.join(job, 'scene'), rules=self.rules)
        except Exception as e:  # noqa: BLE001 — одна комната не должна ронять ночь; сбой сборки — своя строка, это не «чисто»
            return self._row(source, label, snap, 'не собрано', time.time() - t, '-', note=f'{type(e).__name__}: {str(e)[:160]}', wait=wait)
        finally:
            shutil.rmtree(job, ignore_errors=True)
        er = [f for f in rep['findings'] if f['level'] == 'error']
        wr = [f for f in rep['findings'] if f['level'] == 'warn']          # `info` (исключения ткани и т. п.) — не находка
        verdict = 'БРАК' if er else ('предупр.' if wr else 'чисто')
        if sk:
            self.state[sk] = {'ts': self.now(), 'date': london_date(self.now()), 'verdict': verdict, 'errors': er, 'warns': wr}
        return self._row(source, label, snap, verdict, time.time() - t, 'из кэша' if timing.get('prep_hit') else 'новая', er, wr, wait=wait)

    def run(self, scenes: list, max_min: float, rejected: list = ()) -> dict:
        import render_exec as RX
        pr = RX.preset()
        self.sig = RX.qa_signature()
        first: dict = {}
        cut = None
        for source, label, code in rejected:
            self._write(self._row(source, label, {'scene_hash': '-' * 8}, 'не принят', note=f'снимок комнаты не принят ({code}) — заказать/проверить нельзя'))
        for source, label, snap in scenes:
            h = snap['scene_hash']
            if h in first:
                src = first[h]
                self._write(self._row(source, label, snap, src['вердикт'], 0, '-', src['_errors'], src['_warns'], f"как {src['метка']}"))
                continue
            if cut or (self.now() - self.t0) > max_min * 60:
                cut = cut or label
                self._write(self._row(source, label, snap, 'не дошли', note=f'потолок {max_min:g} мин'))
                continue
            row = self.check(source, label, snap, pr)
            if row['вердикт'] != 'не собрано':          # сбой сборки дубль не повторяет: пусть второй раз попробует сам
                first[h] = row
            self._write(row)
            self.log(f"  {label}: {row['вердикт']} ({row['сборка']}, {row['сек']} с)" + (f" — {row['брак (класс слот)']}" if row['брак (класс слот)'] else ''))
        return self.summary(max_min)

    def summary(self, max_min: float) -> dict:
        counts: dict = {}
        for r in self.rows:
            counts[r['вердикт']] = counts.get(r['вердикт'], 0) + 1
        by_code: dict = {}
        brak = []
        seen: set = set()
        for r in self.rows:
            if r['вердикт'] != 'БРАК' or r['сцена'] in seen:
                continue
            seen.add(r['сцена'])
            for f in r['_errors']:
                by_code.setdefault(f['code'], []).append(f"{f.get('slot') or '-'} ({r['метка']})")
                brak.append({'label': r['метка'], 'scene': r['сцена'], 'code': f['code'], 'slot': f.get('slot'), 'why': f.get('why', '')})
        done = [r for r in self.rows if r['вердикт'] in ('чисто', 'предупр.', 'БРАК')]
        return {'date': london_date(self.t0), 'run': self.run_id, 'minutes': round((self.now() - self.t0) / 60, 1), 'max_minutes': max_min, 'total': len(self.rows), 'counts': counts,
                'built': sum(1 for r in self.rows if r['сборка'] in ('новая', 'из кэша')), 'from_memory': sum(1 for r in self.rows if r['сборка'] == 'из памяти'), 'brak': brak, 'by_code': by_code, 'tsv': self.tsv}


def print_summary(s: dict, out=print) -> None:
    c = s['counts']
    out(f"qa-night {s['date']} {s['run']}: комнат {s['total']} за {s['minutes']} мин (потолок {s['max_minutes']:g}) — чисто {c.get('чисто', 0)}, предупр. {c.get('предупр.', 0)}, "
        f"БРАК {c.get('БРАК', 0)}, не собрано {c.get('не собрано', 0)}, снимок не принят {c.get('не принят', 0)}, не дошли {c.get('не дошли', 0)}, из памяти {s['from_memory']}")
    for code, items in sorted(s['by_code'].items()):
        out(f"  БРАК {code}: {len(items)} — " + '; '.join(items[:8]) + (' …' if len(items) > 8 else ''))
    out(f"  журнал: {s['tsv']}")


def write_last(s: dict, out_dir: str = OUT_DIR) -> None:
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, 'last.json.tmp')
    json.dump(s, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(out_dir, 'last.json'))


def main(argv=None, ex=None, scenes_fn=None, qa=None, slot=None) -> int:
    ap = argparse.ArgumentParser(description='Ночной шаг сторожа кадров без рендера: предпроверка всех комнат /demo и туров')
    ap.add_argument('--list', action='store_true', help='только показать комнаты в порядке проверки (ничего не собирать)')
    ap.add_argument('--max-min', type=float, default=None, help='потолок времени, мин (по умолчанию правила: night.maxMinutes)')
    ap.add_argument('--tours', type=int, default=None, help='сколько свежих туров (по умолчанию правила: night.toursMax, 0 — все)')
    ap.add_argument('--demo-only', action='store_true')
    ap.add_argument('--no-state', action='store_true', help='не брать результаты из памяти прогонов (проверить всё заново)')
    ap.add_argument('--out', default=OUT_DIR)
    a = ap.parse_args(argv)
    Q = qa
    if Q is None:
        import frame_qa as Q  # noqa: N812
    rules = Q.load_rules()
    night = rules.get('night') or {}
    max_min = a.max_min if a.max_min is not None else float(night.get('maxMinutes') or 40)
    tours = a.tours if a.tours is not None else int(night.get('toursMax') or 0)
    if scenes_fn is None:
        def scenes_fn():
            return build_scenes(tours, a.demo_only)
    scenes, rejected = scenes_fn()
    if not scenes:
        print('qa-night: нет ни одной комнаты (нет данных /demo и туров)')
        return 2
    if a.list:
        for i, (src, lb, sn) in enumerate(scenes, 1):
            print(f'{i:3d}  {src:5s} {lb}  {sn["scene_hash"][:8]}')
        for src, lb, code in rejected:
            print(f'  -  {src:5s} {lb}  снимок не принят ({code})')
        return 0
    if ex is None:
        import render_exec as RX
        ex = RX.LocalCpuExecutor(dict(os.environ))
    state = {} if a.no_state else load_state()
    n = Night(ex, Q, rules, a.out, state, not a.no_state, slot=slot)
    print(f'qa-night: комнат {len(scenes)} (снимок не принят у {len(rejected)}), потолок {max_min:g} мин, журнал {n.tsv}', flush=True)
    s = n.run(scenes, max_min, rejected)
    if not a.no_state:
        save_state(state)
    write_last(s, a.out)
    print_summary(s)
    return 0


if __name__ == '__main__':
    sys.exit(main())
