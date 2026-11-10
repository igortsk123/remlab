#!/usr/bin/env python3
"""Конвейер пробы после стен (план agent-trial-08, задачи З/И/Е; T-20261109-23): версии данных страницы по очереди, `done` — последним.

Воркер DEV (`worker.py`) после `pipeline.py job` (стены и план готовы, `result.json`) зовёт `Conveyor.run`:
  1. версия 1 — `trial_bundle.py` без сцены: 3D без мебели, гостиные и спальни `pending`, прочее `not_furnished`;
  2. гостиная — `trial_demo.py` (сам берёт общую очередь тяжёлых `machine_slot`) → версия 2 с мебелью или честным исходом;
  3. спальни — `trial_bedroom.py` (если модуль влит: файл и `bundle_parts`) → версия 3. Модуля нет — спальни в версии 2 ещё `pending`,
     в последней версии — отказ `stage_unavailable` (иначе задание не дошло бы до `done`);
  4. воркер шлёт `result` (`done`) — только если в последней принятой версии у каждой гостиной и спальни есть исход
     (`trial.complete`), или если версию не собрать вовсе (тогда страница остаётся на сером туре, код — в журнал);
  5. после `done` — `after_done` (заглушка: фото `trial_hero.py` — отдельный план agent-trial-05).
Комнаты, которые ждут проверки размера (`awaiting_check`: флаг «размер не сошёлся» или масштаб всей квартиры не подтверждён —
`trial_bundle.size_check`, владелец 09.11 TG 531/533), стадиями не обставляются и `done` не держат; все цели ждут проверки — сразу
`done` после версии 1. Потом по кнопке «Обустроить» — пересборка `Rebuild` (одна итоговая версия, см. класс).
Сбой, таймаут стадии мебели или отказ сборщика с её куском (утечка магазина и т. п.) — комната получает отказ с кодом
(`stage_failed` / `stage_timeout` / код сборщика), 3D остаётся, задание всё равно завершается.

Каждая стадия — отдельный процесс (своя группа: снимается целиком при потере аренды, остановке воркера, таймауте).
Версия: точные байты + sha256 → POST `/api/trial/worker/bundle` (`app/api/trial/worker/bundle/route.ts`), потолок
`TRIAL_BUNDLE_MAX_BYTES` 8 МБ проверяется до отправки. Одинаковое не шлётся дважды: сервер сравнивает с последней версией
(`bundle_hash`), а журнал задания `<база>/<id>/published.json` помнит все принятые хэши и между попытками — перезапуск воркера
не откатывает страницу к пустой версии 1, если она уже была. Аренда потеряна (409) — стоп, ничего больше не пишем.
Ошибки — строкой `conveyor <id>: <код> …` в журнал воркера.

  python tools/floorplan/conveyor.py bedrooms <job_id> <result.json> <parts.json>   # стадия спален (так её зовёт конвейер)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCOUT = HERE.parent / 'scout'
BUNDLE_MAX_BYTES = 8 * 1024 * 1024          # = lib/trial/bundle.ts:TRIAL_BUNDLE_MAX_BYTES
BEDROOM = 'bedroom'                          # = trial_bundle.BEDROOM
# Класс в общей очереди тяжёлых прогонов (`tools/ops/heavy_slot.py`, переменная HEAVY_SLOT_PRIO — стадии берут слот сами):
# агент ждёт на открытой странице. Загрузка тура — 1, «Обустроить» — 2 (раньше всех). Порог памяти тот же (T-20261109-31).
SLOT_PRIO_TRIAL = 1
SLOT_PRIO_REBUILD = 2


def bedroom_stage_ready() -> bool:
    """Ветка спален влита: есть `trial_bedroom.py` с `bundle_parts` (импорт не делаем — тяжёлый, его делает процесс стадии)."""
    p = SCOUT / 'trial_bedroom.py'
    try:
        return 'def bundle_parts(' in p.read_text(encoding='utf-8')
    except OSError:
        return False


def default_cmds(py: str) -> dict:
    """Команды стадий (префиксы; аргументы добавляет конвейер). `bedrooms: None` — модуля спален нет."""
    return {'bundle': [py, str(SCOUT / 'trial_bundle.py')],
            'living': [py, str(SCOUT / 'trial_demo.py')],
            'bedrooms': [py, str(HERE / 'conveyor.py'), 'bedrooms'] if bedroom_stage_ready() else None}


def bedroom_refusals(result: dict, code: str) -> dict:
    """Кусок спален без стадии: каждая спальня плана — отказ кодом (страница пишет «не удалось подобрать», 3D остаётся)."""
    rooms = [{'id': f'{BEDROOM}-x{i}', 'panel': p['id'], 'src_id': r['id'], 'kind': BEDROOM, 'furniture_state': 'refused',
              'furniture_code': code}
             for i, (p, r) in enumerate(((p, r) for p in result.get('panels') or [] for r in p.get('rooms') or []
                                         if r.get('kind') == BEDROOM), 1)]
    return {'rooms_geo': {}, 'apartment_rooms': rooms, 'variants': []}


def failed_scene(job_id: str, code: str, detail: str = '') -> dict:
    """Сцена гостиной без мебели: стадия упала / не уложилась / сборщик её не принял."""
    return {'trial_id': job_id, 'status': 'failed', 'flags': [], 'problems': [], 'refusal': {'code': code, 'detail': detail[:300]}}


class Conveyor:
    PRIO = SLOT_PRIO_TRIAL                           # класс стадий в очереди heavy_slot (`_env`)

    def __init__(self, w, lease: dict, wd: Path, hb, result_path: Path, job_id: str | None = None):
        self.w, self.cfg, self.lease, self.wd, self.hb = w, w.cfg, lease, wd, hb
        self.jid = job_id or lease['id']             # у пересборки аренда своя (id пересборки), задание — отдельно
        self.result_path = result_path
        self.result = json.loads(result_path.read_text(encoding='utf-8'))
        self.cmds = self.cfg.stage_cmds or default_cmds(self.cfg.python)
        self.journal = wd.parent / 'published.json'
        self.n = 0                                   # номер сборки в этой попытке (имена файлов)
        self.last = None                             # последняя ПРИНЯТАЯ сервером версия (dict) — по ней решается `done`
        self.cur = None                              # последняя СОБРАННАЯ версия — по ней решается, какие стадии нужны
        self.cur_bytes: bytes | None = None          # её точные байты (итоговая публикация «только последней» — `final_only`)
        self.final_only = False                      # пересборка: промежуточные версии не публикуются, только итог
        self.release: list = []
        self.timings: dict = {}
        self.stopped = None                          # 'lost' | 'stop' — дальше ничего не пишем

    def log(self, msg: str) -> None:
        self.w.log(f'conveyor {self.jid}: {msg}')

    # ── процессы стадий ──
    def _env(self) -> dict:
        return {**os.environ, 'TRIAL_SCENES_ROOT': str(self.cfg.scenes_root), 'HEAVY_SLOT_PRIO': str(self.PRIO)}

    def _stage(self, name: str, cmd: list, timeout: float) -> tuple[int | None, str | None]:
        rc, why = self.w.run_child(cmd, self.wd / f'{name}.log', timeout, self.hb, env=self._env())
        if why in ('lost', 'stop'):
            self.stopped = why
        return rc, why

    # ── версии ──
    def _published(self) -> list:
        try:
            got = json.loads(self.journal.read_text())
            return got if isinstance(got, list) else []
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            self.log(f'journal_unreadable {type(e).__name__}: {e}')
            return []

    def build(self, tag: str, scene: Path | None = None, parts: Path | None = None) -> tuple[bytes | None, str | None]:
        """→ (байты версии, None) или (None, код отказа сборщика / сбоя)."""
        self.n += 1
        out = self.wd / f'bundle-{self.n}-{tag}.json'
        cmd = self.cmds['bundle'] + [self.jid, str(self.result_path)]
        if scene:
            cmd += ['--scene', str(scene)]
        if parts:
            cmd += ['--parts', str(parts)]
        if self.release:
            cmd += ['--release', ','.join(self.release)]
        cmd += ['--out', str(out)]
        rc, why = self._stage(f'bundle-{self.n}-{tag}', cmd, self.cfg.bundle_timeout_s)
        if why:
            return None, f'bundle_{why}'
        if rc == 2:
            try:
                ref = json.loads((self.wd / f'bundle-{self.n}-{tag}.log').read_text(encoding='utf-8').strip().splitlines()[-1])
                return None, str(ref.get('refusal') or 'bundle_refused')
            except (OSError, ValueError, IndexError) as e:
                return None, f'bundle_refused_unparsed:{type(e).__name__}'
        if rc != 0 or not out.exists():
            return None, f'bundle_rc_{rc}'
        data = out.read_bytes()
        if len(data) > self.cfg.bundle_max_bytes:
            return None, 'bundle_too_large'
        return data, None

    def publish(self, tag: str, data: bytes) -> bool:
        """Версия на сервер. → True — принята (или уже была); False — нет (код в журнале). 409 — аренда потеряна: стоп."""
        sha = hashlib.sha256(data).hexdigest()
        done = self._published()
        body = json.loads(data)
        if sha in done:
            self.log(f'{tag}: та же версия уже опубликована ({sha[:12]}) — не шлю')
            self.last = body
            return True
        st, resp = self.w.post_json('/api/trial/worker/bundle',
                                    {**self.lease, 'bundle': data.decode('utf-8'), 'sha256': sha, 'spentUsd': self.w.spent(self.wd)})
        if st == 200:
            self.last = body
            self.journal.write_text(json.dumps(done + [sha]))
            self.log(f'{tag}: версия {(resp or {}).get("version")} принята{" (повтор)" if (resp or {}).get("repeated") else ""}, '
                     f'{len(data)} Б, complete={body["trial"]["complete"]}')
            return True
        if st == 409:
            self.stopped = 'lost'
            self.log(f'{tag}: lease_lost')
            return False
        self.log(f'{tag}: bundle_rejected http={st} {json.dumps(resp or {}, ensure_ascii=False)[:300]}')
        return False

    def step(self, tag: str, scene: Path | None, parts: Path | None, fallback, publish: bool = True) -> tuple[Path | None, Path | None]:
        """Собрать и отправить версию; сборщик не принял кусок стадии — `fallback(код)` → (сцена, куски) с отказом и ещё раз.
        → (сцена, куски), которые реально легли в версию: следующая стадия строится на них, а не на отвергнутых."""
        data, code = self.build(tag, scene, parts)
        if data is None and code and not self.stopped and fallback:
            self.log(f'{tag}: {code} — комната получает отказ этим кодом')
            scene, parts = fallback(code)
            data, code = self.build(tag + '-refused', scene, parts)
        if data is None:
            if not self.stopped:
                self.log(f'{tag}: {code} — версию не собрать')
            return scene, parts
        self.cur, self.cur_bytes = json.loads(data), data
        if publish:
            self.publish(tag, data)
        return scene, parts

    def _write(self, name: str, obj: dict) -> Path:
        p = self.wd / name
        p.write_text(json.dumps(obj, ensure_ascii=False))
        return p

    # ── стадии ──
    def living(self) -> Path:
        """`trial_demo.py` → путь к сцене; упал / не уложился / сцена не дописана — сцена-отказ с кодом."""
        t0 = time.time()
        scene_p = Path(self.cfg.scenes_root) / self.jid / 'scene.json'
        rc, why = self._stage('living', self.cmds['living'] + [self.jid, str(self.result_path)], self.cfg.living_timeout_s)
        self.timings['living_s'] = round(time.time() - t0, 1)
        if self.stopped:
            return scene_p
        code = None
        if why == 'timeout':
            code = 'stage_timeout'
        elif rc not in (0, 2, 3):
            code = 'stage_failed'
        else:
            try:
                fresh = scene_p.stat().st_mtime >= t0 - 1
                status = json.loads(scene_p.read_text(encoding='utf-8')).get('status') if fresh else None
            except (OSError, ValueError) as e:
                self.log(f'living: scene_unreadable {type(e).__name__}: {e}')
                status = None
            if status not in ('ok', 'partial', 'no_products', 'refused', 'failed'):
                code = 'stage_failed'
                self.log(f'living: сцена не дописана (rc={rc}, статус {status!r})')
        if code:
            self.log(f'living: {code} (rc={rc}, {self.timings["living_s"]} с)')
            return self._write('scene-refused.json', failed_scene(self.jid, code, f'rc={rc}'))
        self.log(f'living: rc={rc}, {self.timings["living_s"]} с')
        return scene_p

    def bedrooms(self) -> Path:
        """Стадия спален → куски для сборщика; модуля нет, упала или не уложилась — отказ кодом по каждой спальне."""
        if self.cmds.get('bedrooms') is None:
            parts = bedroom_refusals(self.result, 'stage_unavailable')
            if parts['apartment_rooms']:
                self.log(f'bedrooms: stage_unavailable (модуль спален не влит) — спален {len(parts["apartment_rooms"])}')
            return self._write('bedrooms-parts.json', parts)
        t0 = time.time()
        out = self.wd / 'bedrooms-parts.json'
        rc, why = self._stage('bedrooms', self.cmds['bedrooms'] + [self.jid, str(self.result_path), str(out)],
                              self.cfg.bedroom_timeout_s)
        self.timings['bedrooms_s'] = round(time.time() - t0, 1)
        if self.stopped:
            return out
        if why == 'timeout' or rc != 0 or not out.exists():
            code = 'stage_timeout' if why == 'timeout' else 'stage_failed'
            self.log(f'bedrooms: {code} (rc={rc}, {self.timings["bedrooms_s"]} с)')
            return self._write('bedrooms-parts.json', bedroom_refusals(self.result, code))
        self.log(f'bedrooms: rc={rc}, {self.timings["bedrooms_s"]} с')
        return out

    def _state(self, rid: str) -> str | None:
        return next((r['furniture_state'] for r in (self.cur or {}).get('apartment_rooms') or [] if r['id'] == rid), None)

    def _pending_bedrooms(self) -> bool:
        return any(r.get('kind') == BEDROOM and r['furniture_state'] == 'pending' for r in (self.cur or {}).get('apartment_rooms') or [])

    def run(self, room_ids=None) -> str:
        """→ 'result' — слать `result` (done); 'lost' — аренда потеряна; 'stop' — воркер останавливают.
        `room_ids` — комнаты (id страницы: `living`, `bedroom-1`), с которых агент снял «проверку размера» (кнопка «Обустроить»):
        сборщик ведёт их обычным путём (`trial_bundle --release`); без списка — комнаты с флагом размера ждут проверки и стадии
        мебели для них не запускаются. Версия 1 при списке не публикуется (страница уже есть — не откатываем её к пустой)."""
        t0 = time.time()
        self.release = [str(x) for x in room_ids or []]
        quiet = bool(self.release) or self.final_only      # по кнопке / по тексту — только итоговая версия
        self.step('v1-walls', None, None, None, publish=not quiet)
        if self.stopped:
            return self.stopped
        self.timings['v1_s'] = round(time.time() - t0, 1)
        if self.cur is None:
            self.log('версия 1 не собрана — мебель не подбираю, задание закрываю серым туром')
            return 'result'
        if self.cur['trial']['complete'] and not self.release:
            self.log('ни одной комнаты не ждёт мебель (проверка размера / отказы) — стадии мебели не нужны')
            if self.final_only:                      # версия 1 и есть итог: стадий не будет
                self.publish('v1-final', self.cur_bytes)
            return self._finish(t0)
        if self._state('living') == 'pending':
            scene = self.living()
            if self.stopped:
                return self.stopped
            scene, _ = self.step('v2-living', scene, None,
                                 lambda code: (self._write('scene-refused.json', failed_scene(self.jid, code)), None),
                                 publish=not quiet)               # по кнопке — только итоговая версия: спальни не мигают «подбирается»
            if self.stopped:
                return self.stopped
        else:                                     # главная гостиная ждёт проверки размера (или не построена) — подбор не запускаем
            self.log(f'living: стадия не нужна (состояние {self._state("living")!r})')
            scene = self._write('scene-refused.json', failed_scene(self.jid, 'size_check'))
        if not self._pending_bedrooms():
            self.log('bedrooms: стадия не нужна (нет спален в «подбирается»)')
            parts = None
        else:
            parts = self.bedrooms()
            if self.stopped:
                return self.stopped
        self.step('v3-bedrooms', scene, parts,
                  lambda code: (scene, self._write('bedrooms-parts-refused.json', bedroom_refusals(self.result, code))))
        if self.stopped:
            return self.stopped
        return self._finish(t0)

    def _finish(self, t0: float) -> str:
        self.timings['total_s'] = round(time.time() - t0, 1)
        complete = bool(self.last and self.last['trial']['complete'])
        self.log(f'итог: complete={complete}, время {json.dumps(self.timings)}')
        if not complete:
            # не должно случаться (у каждой стадии есть отказ кодом); не держим задание вечно — `done`, а код в журнале
            self.log('incomplete: в последней принятой версии есть комнаты pending')
        return 'result'


APPROX_CONSENT = 'approx_consent'            # = trial_bundle.APPROX_CONSENT


class Rebuild(Conveyor):
    """Пересборка «Обустроить» / «Обустроить всё» (план agent-trial-08, Р1; T-20261109-27): ОДНА новая версия страницы.

    Исходник — сохранённый `result` задания из Postgres (claim пересборки; рабочие папки DEV чистятся по сроку). Комнаты страницы,
    с которых агент снял проверку размера, — накопленный набор задания (`trial_jobs.released_rooms` ∪ эта пересборка, `*` — все).
    Шаги: версия-проверка без снятия (какие комнаты сейчас `awaiting_check`) → выбранным комнатам в копии результата флаг
    `approx_consent` (решатели не отказывают по масштабу, страница пишет «размеры примерные») → обычный конвейер со снятием
    (`run(release)`: версии 1 и 2 НЕ публикуются) → итоговая версия на `/api/trial/worker/rebuild/publish`.
    Мебель прочих комнат не теряется: все комнаты, которые и раньше обставлялись, проходят стадии заново из того же результата
    (детерминированно; ночное обновление каталога может сменить подбор), комнаты без снятия остаются «ждут проверки».
    Сервер ещё раз сверяет `base_version` под замком: страница сменилась — 409 `stale`, ничего не пишется.
    Стадии пересборки идут в очереди heavy_slot первыми (`PRIO`, T-20261109-31): агент нажал и ждёт."""

    PRIO = SLOT_PRIO_REBUILD

    def __init__(self, w, lease: dict, wd: Path, hb, result_path: Path, job_id: str, rooms):
        super().__init__(w, lease, wd, hb, result_path, job_id=job_id)
        self.want = [str(x) for x in rooms or []]
        self.outcome = None                          # 'published' | 'stale' | 'rejected' — итог отправки версии

    def publish(self, tag: str, data: bytes) -> bool:
        sha = hashlib.sha256(data).hexdigest()
        body = json.loads(data)
        st, resp = self.w.post_json('/api/trial/worker/rebuild/publish',
                                    {**self.lease, 'jobId': self.jid, 'bundle': data.decode('utf-8'), 'sha256': sha,
                                     'spentUsd': self.w.spent(self.wd), **self.publish_extra()})
        err = (resp or {}).get('error')
        if st == 200:
            self.last, self.outcome = body, 'published'
            self.log(f'{tag}: пересборка → версия {(resp or {}).get("version")}{" (повтор)" if (resp or {}).get("repeated") else ""}, '
                     f'{len(data)} Б{" · " + str((resp or {}).get("warning")) if (resp or {}).get("warning") else ""}')
            return True
        if st == 409 and err == 'stale':
            self.outcome = 'stale'
            self.log(f'{tag}: stale — страница сменилась, пока подбирали; версию не пишем')
            return False
        if st == 409:
            self.stopped = 'lost'
            self.log(f'{tag}: lease_lost')
            return False
        self.outcome = 'rejected'
        self.log(f'{tag}: bundle_rejected http={st} {json.dumps(resp or {}, ensure_ascii=False)[:300]}')
        return False

    def publish_extra(self) -> dict:
        """Добавка к телу публикации (пересборка по тексту агента шлёт новый `result` задания)."""
        return {}

    def chosen(self) -> tuple[list, dict] | None:
        """Версия-проверка без снятия → (комнаты страницы к обустройству, эта версия) или None (сборщик не собрал)."""
        data, code = self.build('v0-check', None, None)
        if data is None:
            if not self.stopped:
                self.log(f'v0-check: {code} — версию не собрать')
            return None
        cur = json.loads(data)
        waiting = [r['id'] for r in cur['apartment_rooms'] if r.get('furniture_state') == 'awaiting_check']
        want = set(self.want)
        return (waiting if '*' in want else [r for r in waiting if r in want]), cur

    def consent(self, cur: dict, pick: list) -> None:
        """Копия результата: выбранным комнатам (id страницы → панель и id плана) флаг `approx_consent`; дальше конвейер идёт по ней."""
        src = {x['id']: (p['id'], x['src_id']) for p in cur['trial']['panels'] for x in p['rooms']}
        keys = {src[r] for r in pick if r in src}
        res = json.loads(json.dumps(self.result))
        for p in res['panels']:
            for r in p['rooms']:
                if (p['id'], r['id']) in keys and APPROX_CONSENT not in (r.get('flags') or []):
                    r['flags'] = list(r.get('flags') or []) + [APPROX_CONSENT]
        self.result_path = self._write('result-consent.json', res)
        self.result = res

    def rebuild(self) -> str:
        """→ 'published' | 'stale' | 'lost' | 'stop' | 'failed:<код>' (код — для `/rebuild/fail`)."""
        t0 = time.time()
        got = self.chosen()
        if self.stopped:
            return self.stopped
        if got is None:
            return 'failed:pipeline_error'
        pick, cur = got
        if not pick:
            self.log(f'нечего обустраивать: просили {self.want}, ждут проверки {[r["id"] for r in cur["apartment_rooms"] if r.get("furniture_state") == "awaiting_check"]}')
            return 'failed:nothing_to_furnish'
        self.log(f'обустраиваю {pick} (просили {self.want})')
        self.consent(cur, pick)
        self.run(pick)
        self.timings['rebuild_s'] = round(time.time() - t0, 1)
        if self.stopped:
            return self.stopped
        self.log(f'пересборка: {self.outcome}, время {json.dumps(self.timings)}')
        if self.outcome in ('published', 'stale'):
            return self.outcome
        return 'failed:pipeline_error'


SCALE_TEXT = ('listing', 'verified')         # опоры по длинам (подписи плана / «A на B» текстом); площадь — сверка, не опора


def text_applied(old: dict, new: dict) -> bool:
    """Текст агента лёг на план: у какой-то комнаты размеры из текста, или масштаб стал опираться на длины (был без них).
    Только общая площадь («кухня 10 м²», «54 м²») — не опора (владелец/ведущий 09.11): это `no_match`, страница как была."""
    rooms = (r for p in new.get('panels') or [] for r in p.get('rooms') or [])
    if any((r.get('dims') or {}).get('src') == 'listing' for r in rooms):
        return True
    was, now = (old.get('scale') or {}).get('status'), (new.get('scale') or {}).get('status')
    return now in SCALE_TEXT and was not in SCALE_TEXT


class ListingRebuild(Rebuild):
    """«Размеры своими словами» (план agent-trial-08, Р2-текст; T-20261109-33): текст агента после `done` → план перечитывается
    `pipeline.py job --cache-only --cap-usd 0` (исходный лист под арендой пересборки + кэш чтения плана, 0 $) → мебель обычным
    конвейером → ОДНА итоговая версия вместе с новым `result` задания (масштаб и комнаты, одной транзакцией на сервере).
    Листа или кэша нет — `source_gone` («загрузите план заново»); текст ни к чему не подошёл — `no_match`, ничего не публикуем.
    Комнаты, с которых агент раньше снял проверку (`rooms` claim), снимаются и в новой версии. Текст в журнал не пишется."""

    def __init__(self, w, lease: dict, wd: Path, hb, result_path: Path, job_id: str, rooms, text: str, mime: str, ext: str):
        super().__init__(w, lease, wd, hb, result_path, job_id=job_id, rooms=rooms)
        self.text, self.mime, self.ext = text, mime, ext
        self.final_only = True
        self.new_result: dict | None = None

    def publish_extra(self) -> dict:
        return {'result': self.new_result} if self.new_result is not None else {}

    def source(self) -> Path | str:
        """Исходный лист под арендой → путь; иначе код исхода ('lost' | 'failed:<код>')."""
        inp = self.wd / 'plan' / ('input' + self.ext)
        inp.parent.mkdir(parents=True, exist_ok=True)
        try:
            st, info = self.w.api.call('GET', f'/api/trial/worker/rebuild/{self.lease["id"]}/input', stream_to=inp,
                                       headers={'X-Trial-Attempt': str(self.lease['attempt']), 'X-Trial-Lease': self.lease['leaseToken']})
        except Exception as e:                       # noqa: BLE001 — сеть (NetError воркера): повторяемо
            self.log(f'input: {type(e).__name__}: {e}')
            return 'failed:internal'
        if st == 409:
            self.stopped = 'lost'
            return 'lost'
        if st == 410:
            self.log('input: исходного листа уже нет (срок хранения)')
            return 'failed:source_gone'
        if st != 200 or (info or {}).get('too_large'):
            self.log(f'input: http {st}')
            return 'failed:internal'
        return inp

    def reread(self, inp: Path) -> str | None:
        """План заново с текстом → None (новый результат в `self.new_result`) или код исхода."""
        pw = self.wd / 'plan'
        lst = pw / 'listing.txt'
        lst.write_text(self.text[:5000], encoding='utf-8')
        cmd = self.cfg.pipeline + ['job', '--input', str(inp), '--mime', self.mime, '--workdir', str(pw),
                                   '--vlm-root', str(self.cfg.vlm_root), '--job-id', self.jid, '--cap-usd', '0', '--cache-only',
                                   '--listing-file', str(lst)]
        if self.cfg.an_cache:
            cmd += ['--an-cache', self.cfg.an_cache]
        t0 = time.time()
        rc, why = self._stage('pipeline', cmd, self.cfg.job_timeout_s)
        self.timings['reread_s'] = round(time.time() - t0, 1)
        if self.stopped:
            return self.stopped
        if why == 'timeout':
            return 'failed:timeout'
        res_p, err_p = pw / 'result.json', pw / 'error.json'
        if rc == 0 and res_p.exists():
            self.new_result = json.loads(res_p.read_text(encoding='utf-8'))
            return None
        try:
            code = str(json.loads(err_p.read_text(encoding='utf-8')).get('code') or 'pipeline_error')
        except (OSError, ValueError):
            code = 'pipeline_error'
        self.log(f'план с текстом: rc={rc}, код {code}')
        return f'failed:{code}'

    def rebuild(self) -> str:
        t0 = time.time()
        inp = self.source()
        if isinstance(inp, str):
            return inp
        bad = self.reread(inp)
        if bad:
            return bad
        old, new = self.result, self.new_result
        if not text_applied(old, new):
            self.log(f'текст не лёг на план: масштаб {(old.get("scale") or {}).get("status")} → {(new.get("scale") or {}).get("status")}')
            return 'failed:no_match'
        n = sum(1 for p in new['panels'] for r in p['rooms'] if (r.get('dims') or {}).get('src') == 'listing')
        self.log(f'текст лёг на план: масштаб {(old.get("scale") or {}).get("status")} → {new["scale"]["status"]}, комнат с размером '
                 f'из текста {n}')
        self.result_path = self._write('result-listing.json', new)
        self.result = new
        pick = None
        if self.want:                                # снятые раньше комнаты — снова снять в новой версии (если ещё ждут проверки)
            got = self.chosen()
            if self.stopped:
                return self.stopped
            if got is None:
                return 'failed:pipeline_error'
            pick, cur = got
            if pick:
                self.consent(cur, pick)
        self.run(pick or None)
        self.timings['rebuild_s'] = round(time.time() - t0, 1)
        if self.stopped:
            return self.stopped
        self.log(f'пересборка по тексту: {self.outcome}, время {json.dumps(self.timings)}')
        if self.outcome in ('published', 'stale'):
            return self.outcome
        return 'failed:pipeline_error'


def furnish_rooms(w, lease: dict, wd: Path, hb, result_path: Path, room_ids) -> str:
    """Точка входа будущей кнопки «Обустроить» / «Обустроить всё» (другая задача): стадии мебели по списку комнат страницы,
    с которых агент снял проверку размера. Аренда, heartbeat и `result` — у вызывающего (как в `Worker._process`)."""
    return Conveyor(w, lease, wd, hb, result_path).run(room_ids=list(room_ids))


def after_done(w, lease: dict, wd: Path, bundle: dict | None) -> None:
    """Точка подключения фото после `done` (план agent-trial-05, `trial_hero.py`) — пока ничего не делает."""
    return None


def bedrooms_main(job_id: str, result_path: str, out_path: str) -> int:
    """Стадия спален отдельным процессом: `trial_bedroom.build` под общей очередью тяжёлых → `bundle_parts` → файл кусков."""
    sys.path.insert(0, str(SCOUT))
    import trial_bedroom as TBR
    import trial_bundle as TB
    result = json.loads(Path(result_path).read_text(encoding='utf-8'))
    slot = getattr(TBR, '_slot', None)
    if slot is None:
        import trial_demo as TD
        slot = TD.machine_slot
    with slot(f'trial-bedroom-{job_id}'):
        job = TBR.build(job_id, result)
    smap, _ = TB.storeys(result['panels'])
    parts = TBR.bundle_parts(job, {result['panels'][i]['id']: s for i, s in smap.items()})
    TB.write_atomic(out_path, parts)
    print(json.dumps({'status': job.get('status'), 'rooms': len(parts.get('apartment_rooms') or [])}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) == 4 and a[0] == 'bedrooms':
        sys.exit(bedrooms_main(*a[1:]))
    print(__doc__)
    sys.exit(0)
