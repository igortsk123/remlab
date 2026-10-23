#!/usr/bin/env python3
"""НОЧНАЯ ПЕРЕСБОРКА КАНДИДАТА БАНКА `bank_prepare` (conv-14 шаг 2.2, разбор Codex 22.10 § 2 «Место в ночи»).

ЗАЧЕМ. Кандидат `sets3.next.json` до сих пор собирался только руками, а ожидание готовности (`bank_pending`) и будущая подмена
(шаги 3–4) судят именно его: без ночной сборки кандидат стареет, его товары уходят из продажи, а очередь мешей просит модели
для вчерашнего состава. Шаг собирает кандидат из живого каталога каждую ночь.

ПОРЯДОК (за флагом `rules/bank-candidate.json:prepare_enabled`, по умолчанию ВЫКЛЮЧЕН — тогда шаг `ok` со строкой «выключено»):
  1. сборка — `compose2.py --style --bands all` с `SETS_OUTPUT` = сырой файл рядом (`sets3.next.build.json`); живой
     `sets3.json` сборщик отвергает сам (`bank_paths.compose_output`), здесь — вторая проверка до запуска; пишет ТОЛЬКО
     `set_identity.write_bank` (атомарно); чёрный список — из состояния ожидания (`compose_gates` по `compose_reject_blacklist`);
  1б. медиа из каталога (`catalog_media.sync_sets`, как ночной `bank_media` у живого банка): сборщик кладёт прямую ссылку фида,
     партнёрскую ссылку, фото, магазин и габариты ставит сверка (без неё все ссылки кандидата «не текущие» — прогон 22.10);
     сырая сборка → кандидат `sets3.next.json` через `write_bank` — кандидат меняется только целиком готовым;
  2. инварианты `bank_invariants.check` против живого банка: идентичность и карта номеров — ФАТАЛЬНО (код 1), содержимое
     (ушедшие, ссылки, контракты, пары, запасные, ключевые роли) — отчётом `WARN:`; отчёт → `~/scout-scenes/bank-prepare.json`;
  3. состояние ожидания — НЕ здесь (T-20261023-08, Codex 23.10): отдельный шаг ночи `bank_pending.py --night` ПОСЛЕ ранней
     привязки мешей, иначе меш, привязанный этой ночью, promote увидел бы только завтра. Здесь — отметка `pending_due` в отчёте:
     кандидат этой ночи прошёл медиа и идентичность, его можно судить.
Сбой сборки/медиа/идентичности — ненулевой код: `step` ночи пишет FAIL в дайджест и идёт дальше; прежний кандидат остаётся
нетронутым (запись атомарная). Сам банк здесь не меняется — подмена только шагами 3–4.

  ~/venvs/scout/bin/python bank_prepare.py            # ночной шаг (флаг из правил)
  ~/venvs/scout/bin/python bank_prepare.py --force    # ручной прогон при выключенном флаге
  env BANK_CANDIDATE=<путь> — куда собирать (ручная проверка во временный файл); BANK_PENDING — файл состояния
  python3 bank_prepare.py --selftest
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RULES_PATH = os.path.join(HERE, 'rules', 'bank-candidate.json')
LIVE = os.path.join(HERE, 'sets3.json')
CANDIDATE = os.path.abspath(os.environ.get('BANK_CANDIDATE') or os.path.join(HERE, 'sets3.next.json'))
REPORT = os.path.expanduser(os.environ.get('BANK_PREPARE_REPORT', '~/scout-scenes/bank-prepare.json'))
CONTENT = (('gone', 'ушедших'), ('url_stale', 'ссылок не текущих'), ('contracts', 'вне контракта'),
           ('pair_mismatch', 'пар разошлось'), ('alt_bad', 'запасных негодных'), ('core_missing', 'без ключевых ролей'))


def rules() -> dict:
    try:
        return json.load(open(RULES_PATH, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def verdict(r: dict) -> tuple[bool, list]:
    """Итог инвариантов кандидата → (фатально ли, строки содержимого). Идентичность и карта номеров — фатально."""
    fatal = not r.get('identity_ok') or r.get('map_ok') is False
    content = [f'{name} {r[k]}' for k, name in CONTENT if r.get(k)]
    return fatal, content


def _compose(out: str, timeout_s: int) -> int:
    t0 = time.time()
    env = {**os.environ, 'SETS_OUTPUT': out}
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, 'compose2.py'), '--style', '--bands', 'all'], cwd=HERE,
                           env=env, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        print(f'bank_prepare: сборка не уложилась в {timeout_s // 60} мин — кандидат прежний', flush=True)
        return 124
    tail = [ln for ln in (p.stdout or '').splitlines() if ln.startswith(('OK:', '!!', '[compose_gates]', 'ворота'))]
    for ln in tail[-6:] + ((p.stderr or '').strip().splitlines()[-8:] if p.returncode else []):
        print('  ' + ln[:300], flush=True)
    print(f'bank_prepare: сборка rc={p.returncode} за {time.time() - t0:.0f} с', flush=True)
    return p.returncode


def build_path(out: str) -> str:
    """Сырая сборка — рядом с кандидатом: кандидат перезаписывается только готовым (после сверки медиа)."""
    return (out[:-5] if out.endswith('.json') else out) + '.build.json'


def _media(build: str, out: str) -> dict:
    """Медиа кандидата — из каталога (как `bank_media` у живого банка; разбор Codex § 2: «к рабочей копии»): сборщик пишет
    прямую ссылку фида, партнёрскую ссылку, фото, магазин и габариты ставит только сверка. Сырая сборка `build` → кандидат
    `out` через `write_bank` (атомарно, идентичность — по живому банку)."""
    import catalog_media as CM
    import set_identity as SI
    sets = json.load(open(build, encoding='utf-8'))
    st = CM.sync_sets(sets)
    SI.write_bank(sets, out, LIVE)
    print(f"bank_prepare: медиа кандидата — сверено {st['ok']}, ссылок исправлено {st['fixed_url']}, фото {st['fixed_img']}, "
          f"габаритов {st['fixed_dims']}, ушли {st['gone']}, магазин в карантине {st['unknown']}", flush=True)
    return st


def _invariants(out: str) -> dict:
    import bank_invariants as BI
    import sets_incremental as SI
    from catalog_media import media
    from item_function import fits_role
    new, live = json.load(open(out, encoding='utf-8')), json.load(open(LIVE, encoding='utf-8'))
    r = BI.check(new, live, media, SI._slot_ok, SI.sync_pairs, fits_role)
    print(BI._line('кандидат', r), flush=True)
    return r


def _save(rep: dict) -> None:
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    tmp = REPORT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, REPORT)


def run(force: bool = False, R: dict | None = None, out: str = CANDIDATE, compose=_compose, media=_media,
        invariants=_invariants, save=_save) -> int:
    """Шаг ночи. Зависимости подменяемые (селфтест без базы и сборки)."""
    R = rules() if R is None else R
    if not (R.get('prepare_enabled') or force):
        print('bank_prepare: выключено (rules/bank-candidate.json:prepare_enabled=false) — кандидат не собирается', flush=True)
        return 0
    if os.path.realpath(LIVE) in (os.path.realpath(out), os.path.realpath(build_path(out))):
        print(f'bank_prepare: {out} — это живой банк; кандидат пишется только рядом', flush=True)
        return 2
    t0, rep = time.time(), {'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'candidate': out}
    rc = compose(build_path(out), int(R.get('prepare_timeout_min') or 40) * 60)
    rep['compose_rc'] = rc
    if rc:
        why = 'идентичность сетов нарушена — банк не записан' if rc == 3 else 'сборка упала'
        print(f'ERROR:bank_prepare: {why} (rc={rc}); прежний кандидат не тронут', flush=True)
        save(rep)
        return rc
    try:
        rep['media'] = media(build_path(out), out)
    except Exception as e:  # noqa: BLE001 — база недоступна / идентичность: кандидат без медиа судить нельзя
        print(f'ERROR:bank_prepare: сверка медиа кандидата не прошла ({type(e).__name__}: {str(e)[:200]}) — ожидание не обновляю',
              flush=True)
        rep['media_error'] = f'{type(e).__name__}: {e}'
        save(rep)
        return 1
    r = invariants(out)
    fatal, content = verdict(r)
    rep['invariants'] = {k: r.get(k) for k in ('sets', 'identity_ok', 'identity', 'map_ok') + tuple(k for k, _ in CONTENT)}
    if fatal:
        print('ERROR:bank_prepare: идентичность кандидата против живого банка нарушена — ожидание не обновляю', flush=True)
        save(rep)
        return 1
    if content:
        print(f'WARN:bank_prepare: кандидат: {", ".join(content)} — это отчёт, подмена судит ячейки отдельно (шаг 3)', flush=True)
    rep['pending_due'] = True          # суд ячеек — шаг `bank_pending --night` после ранней привязки мешей
    rep['seconds'] = round(time.time() - t0)
    save(rep)
    print(f'bank_prepare: готово за {rep["seconds"]} с; ожидание ячеек — шагом bank_pending после привязки мешей', flush=True)
    return 0


def _selftest() -> int:
    import contextlib
    import io
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    calls = []
    good = {'sets': 126, 'identity_ok': True, 'identity': [], 'gone': 0, 'url_stale': 0}

    def go(R, comp_rc=0, inv=good, out='/x/sets3.next.json', force=False, media_fn=lambda: {'ok': 1}):
        calls.clear()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(force, R, out, compose=lambda o, t: calls.append(('compose', t, o)) or comp_rc,
                     media=lambda b, o: calls.append(('media', b, o)) or media_fn(),
                     invariants=lambda o: calls.append(('inv',)) or inv,
                     save=lambda rep: calls.append(('save', rep)))
        return rc, buf.getvalue(), [c[0] for c in calls]
    rc, txt, cl = go({})
    ok('флаг выключен — ok и «выключено», ничего не собирается', rc == 0 and 'выключено' in txt and cl == [], (rc, cl))
    rc, txt, cl = go({}, force=True)
    ok('--force при выключенном флаге — собирает', rc == 0 and cl == ['compose', 'media', 'inv', 'save'], cl)
    rc, txt, cl = go({'prepare_enabled': True, 'prepare_timeout_min': 5})
    ok('включено: сборка → медиа → инварианты → отчёт с pending_due (ожидание — отдельный шаг после привязки); предел из правил',
       rc == 0 and cl == ['compose', 'media', 'inv', 'save'] and calls[0][1] == 300 and calls[-1][1].get('pending_due'),
       (rc, calls))
    ok('сборка пишет сырой файл рядом, кандидат — только сверка медиа',
       calls[0][2] == '/x/sets3.next.build.json' and calls[1][1:] == ('/x/sets3.next.build.json', '/x/sets3.next.json'), calls)

    def boom():
        raise RuntimeError('база недоступна')
    rc, txt, cl = go({'prepare_enabled': True}, media_fn=boom)
    ok('медиа упало — FAIL, кандидат не трогаем, судить нечего (нет pending_due)', rc == 1 and 'ERROR:bank_prepare' in txt
       and cl == ['compose', 'media', 'save'] and not calls[-1][1].get('pending_due'), (rc, cl))
    rc, txt, cl = go({'prepare_enabled': True}, out=LIVE)
    ok('кандидат = живой банк — отказ до сборки', rc == 2 and cl == [], (rc, cl))
    rc, txt, cl = go({'prepare_enabled': True}, comp_rc=3)
    ok('сборка: идентичность нарушена (rc 3) — FAIL, ожидание не трогаем', rc == 3 and 'ERROR:bank_prepare' in txt
       and not calls[-1][1].get('pending_due') and 'inv' not in cl, (rc, cl))
    rc, txt, cl = go({'prepare_enabled': True}, inv={**good, 'identity_ok': False, 'identity': ['дубль']})
    ok('инварианты: идентичность против живого — фатально, ожидание не обновляем', rc == 1 and not calls[-1][1].get('pending_due'),
       (rc, cl))
    rc, txt, cl = go({'prepare_enabled': True}, inv={**good, 'map_ok': False})
    ok('инварианты: карта номеров разошлась — фатально', rc == 1)
    rc, txt, cl = go({'prepare_enabled': True}, inv={**good, 'gone': 3, 'contracts': 2})
    ok('содержимое — WARN отчётом, шаг идёт дальше', rc == 0 and 'WARN:bank_prepare: кандидат: ушедших 3, вне контракта 2' in txt
       and calls[-1][1].get('pending_due'), txt)
    ok('verdict: чистый кандидат — не фатально, без строк', verdict(good) == (False, []))
    print(f'bank_prepare selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    sys.exit(run('--force' in sys.argv))
