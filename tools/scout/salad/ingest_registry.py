#!/usr/bin/env python3
"""Реестр мешей: физические поколения (`mesh_generations`) и логические ревизии (`asset_revisions`).

ДВА УРОВНЯ, И ЭТО НЕ ИЗЛИШЕСТВО (план mesh-owner-audit, разбор Codex 05.09). Ревизия — «товар ×
фото × версия конвейера» (`sku|sha16|v1`), её ключ читают точным равенством и префиксом, менять
нельзя. Но один товар с тем же фото генерируется несколько раз (seed 0, 1, 2…), и раньше все
попытки писались в ОДНУ строку ревизии: «текущим» становился файл, прочитанный последним ПО
АЛФАВИТУ job_id, а не самый свежий; отказ владельца адресовать было нечему; и каждый прогон
безусловно возвращал статус в `generated`, стирая любое человеческое решение.

Теперь:
  * каждая физическая модель — строка `mesh_generations` со своим ключом
    `sku|sha16|pipeline|seed|glb8`; вердикт владельца (`owner_verdict`) реестр НИКОГДА не трогает;
  * «текущее» поколение ревизии выбирается по монотонному `generated_at` (mtime model.glb) с
    детерминированным tie-break по ключу — порядок обхода диска на результат не влияет;
  * статус ревизии: человеческий (`owner_reject`, `replace_needed`) сохраняется ТОЛЬКО пока
    текущее поколение то же самое; новое поколение честно возвращает `generated` — новый меш
    ещё никто не смотрел, а старый вердикт остался у старого поколения;
  * хеш model.glb пересчитывается только при смене размера/mtime (иначе 11 ГБ чтения за прогон);
  * ВСЕ записи уходят в БД одним скриптом в транзакции (раньше — по `docker exec` на каталог).

  ~/venvs/scout/bin/python ingest_registry.py             # обновить реестр по диску
  ~/venvs/scout/bin/python ingest_registry.py --report    # только цифры из БД
  python3 ingest_registry.py --selftest                   # чистые правила без БД и диска
"""
import glob
import hashlib
import json
import os
import subprocess
import sys

SRC = os.environ.get('INGEST_SRC', os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2'))
PIPELINE_VERSION = os.environ.get('PIPELINE_VERSION', 'v1')   # как в revision_key (scout), не salad
ORIGIN = 'salad-pilot'
HUMAN_STATUSES = ('owner_reject', 'replace_needed')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab',
        '-d', os.environ.get('REMLAB_DEVDB_NAME', 'remlab'),
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']


def q(v) -> str:
    if v is None:
        return 'null'
    return "'" + str(v).replace("'", "''") + "'"


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:600])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


# ------------------------------------------------------------------ чистые правила (selftest)

def generation_key(sku: str, sha16: str, seed: int, glb_sha: str, pipeline: str = PIPELINE_VERSION) -> str:
    return f'{sku}|{sha16}|{pipeline}|{int(seed)}|{glb_sha[:8]}'


def revision_key(sku: str, sha16: str, pipeline: str = PIPELINE_VERSION) -> str:
    return f'{sku}|{sha16}|{pipeline}'


def pick_current(gens: list[dict]) -> dict | None:
    """Текущее поколение ревизии: самое позднее по `generated_at`, при равенстве — большее по ключу.
    Чистая функция от множества, не от порядка: `sorted` по обоим полям."""
    if not gens:
        return None
    return max(gens, key=lambda g: (float(g['generated_at']), g['generation_key']))


def revision_status(existing_status: str | None, existing_current: str | None,
                    new_current: str | None, new_status: str) -> str:
    """Человеческий статус переживает прогон ТОЛЬКО для того же поколения."""
    if existing_status in HUMAN_STATUSES and existing_current and existing_current == new_current:
        return existing_status
    return new_status


# ------------------------------------------------------------------ диск

def _sha16(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''):
            h.update(ch)
    return h.hexdigest()[:16]


def scan(src: str, known: dict[str, dict]) -> tuple[list[dict], list[dict], list[str]]:
    """Обход каталогов поколений. Возвращает (поколения, ревизии-без-модели, необъяснённые).

    `known` — уже зарегистрированные поколения по пути: хеш берём из БД, если размер и mtime
    файла не изменились. Ревизия без модели (гейт отбраковал форму) остаётся ревизией со статусом
    гейта — так было и раньше, эти 18 строк `flat_shape` держат историю брака.
    """
    gens, no_model, unexplained = [], [], []
    for mp in sorted(glob.glob(os.path.join(src, '*/*/manifest.json'))):
        d = os.path.dirname(mp)
        try:
            man = json.load(open(mp, encoding='utf-8'))
        except Exception as e:  # noqa: BLE001 — битый манифест не валит прогон, но и не молчит
            unexplained.append(f'{d}: манифест не читается ({type(e).__name__})')
            continue
        sku = man.get('sku')
        sha16 = (man.get('input') or {}).get('input_hash')
        if not sku or not sha16:
            unexplained.append(f'{d}: в манифесте нет sku/input_hash')
            continue
        glb = os.path.join(d, 'model.glb')
        if not os.path.exists(glb):
            gate = (man.get('gpu') or {}).get('gate') or 'failed'
            no_model.append({'sku': sku, 'sha16': sha16, 'status': gate, 'manifest': man})
            continue
        st = os.stat(glb)
        prev = known.get(d)
        if prev and int(prev.get('glb_bytes') or -1) == st.st_size and \
                abs(float(prev.get('glb_mtime') or -1) - st.st_mtime) < 1e-6:
            glb_sha = prev['glb_sha']
        else:
            glb_sha = _sha16(glb)
        verdict = None
        vj = os.path.join(d, 'verdict.json')
        if os.path.exists(vj):
            try:
                verdict = json.load(open(vj)).get('status')
            except Exception:  # noqa: BLE001 — вердикт приёмки необязателен
                verdict = None
        seed = int(man.get('seed') or 0)
        gens.append({'generation_key': generation_key(sku, sha16, seed, glb_sha),
                     'revision_key': revision_key(sku, sha16),
                     'sku': sku, 'sha16': sha16, 'seed': seed, 'glb_sha': glb_sha,
                     'job_id': man.get('job_id') or os.path.basename(d), 'path': d,
                     'glb_bytes': st.st_size, 'glb_mtime': st.st_mtime,
                     'generated_at': st.st_mtime, 'machine_verdict': verdict, 'manifest': man})
    return gens, no_model, unexplained


# ------------------------------------------------------------------ запись

def build_sql(gens: list[dict], no_model: list[dict]) -> str:
    """Один скрипт в транзакции. Статус ревизии решается В SQL (`case`), а не в питоне:
    между чтением и записью минутный sync мог поставить `owner_reject` — правило должно
    смотреть на строку в момент записи."""
    lines = ['begin;']
    for g in gens:
        lines.append(
            "insert into mesh_generations (generation_key, sku, source_sha, pipeline_version, seed, "
            "glb_sha, job_id, path, glb_bytes, glb_mtime, generated_at, machine_verdict) values ("
            f"{q(g['generation_key'])}, {q(g['sku'])}, {q(g['sha16'])}, {q(PIPELINE_VERSION)}, "
            f"{g['seed']}, {q(g['glb_sha'])}, {q(g['job_id'])}, {q(g['path'])}, {g['glb_bytes']}, "
            f"{g['glb_mtime']!r}, to_timestamp({g['generated_at']!r}), {q(g['machine_verdict'])}) "
            "on conflict (generation_key) do update set path=excluded.path, "
            "glb_bytes=excluded.glb_bytes, glb_mtime=excluded.glb_mtime, "
            "generated_at=excluded.generated_at, machine_verdict=excluded.machine_verdict, "
            "updated=now();")   # owner_* НЕ в списке: человеческий вердикт реестр не трогает
    by_rev: dict[str, list[dict]] = {}
    for g in gens:
        by_rev.setdefault(g['revision_key'], []).append(g)
    for rk, lst in by_rev.items():
        cur = pick_current(lst)
        lines.append(_revision_upsert(rk, cur['sku'], cur['sha16'], cur['glb_sha'], 'generated',
                                      cur['manifest'], str(cur['seed']), cur['generation_key']))
    for r in no_model:
        rk = revision_key(r['sku'], r['sha16'])
        if rk in by_rev:
            continue            # у ревизии есть модель — брак старой попытки историю не перебивает
        lines.append(_revision_upsert(rk, r['sku'], r['sha16'], None, r['status'], r['manifest'],
                                      None, None))
    lines.append('commit;')
    return '\n'.join(lines)


def _revision_upsert(rk, sku, sha16, glb_sha, status, manifest, variant, current) -> str:
    return (
        "insert into asset_revisions (revision_key, sku, glb_sha, status, origin, manifest, "
        "source_sha, generation_variant, current_generation_key) values ("
        f"{q(rk)}, {q(sku)}, {q(glb_sha)}, {q(status)}, {q(ORIGIN)}, "
        f"{q(json.dumps(manifest, ensure_ascii=False))}::jsonb, {q(sha16)}, {q(variant)}, {q(current)}) "
        "on conflict (revision_key) do update set glb_sha=excluded.glb_sha, "
        "manifest=excluded.manifest, source_sha=excluded.source_sha, "
        "generation_variant=excluded.generation_variant, "
        "current_generation_key=excluded.current_generation_key, updated=now(), "
        # человеческий статус живёт, пока текущее поколение то же (см. revision_status)
        "status=case when asset_revisions.status in ('owner_reject','replace_needed') "
        "  and asset_revisions.current_generation_key is not null "
        "  and asset_revisions.current_generation_key = excluded.current_generation_key "
        "  then asset_revisions.status else excluded.status end;")


def main() -> None:
    known = {r[1]: {'glb_bytes': r[2], 'glb_mtime': r[3], 'glb_sha': r[4]}
             for r in db("select generation_key, path, glb_bytes, glb_mtime, glb_sha from mesh_generations")
             if len(r) == 5}
    gens, no_model, unexplained = scan(SRC, known)
    hashed = sum(1 for g in gens if g['path'] not in known)
    if gens or no_model:
        db(build_sql(gens, no_model))
    revs = {g['revision_key'] for g in gens}
    skus = {g['sku'] for g in gens}
    print(f'реестр: поколений {len(gens)} (новых хешей {hashed}), ревизий с моделью {len(revs)}, '
          f'товаров {len(skus)}, ревизий без модели {len(no_model)}, необъяснённых каталогов '
          f'{len(unexplained)}', flush=True)
    for u in unexplained[:20]:
        print(f'  ?? {u}', flush=True)


def report() -> None:
    for t, sql in (('поколения', "select coalesce(owner_verdict,'-'), count(*) from mesh_generations group by 1"),
                   ('ревизии', 'select status, count(*) from asset_revisions group by 1'),
                   ('текущих указателей', 'select count(*) from asset_revisions where current_generation_key is not null')):
        rows = db(sql)
        print(f'{t}: ' + (', '.join('='.join(r) for r in rows) or 'пусто'))


def _selftest() -> int:
    bad = 0
    a = {'generation_key': 'x|s|v1|0|aaaaaaaa', 'generated_at': 100.0}
    b = {'generation_key': 'x|s|v1|1|bbbbbbbb', 'generated_at': 200.0}
    c = {'generation_key': 'x|s|v1|0|00000000', 'generated_at': 200.0}   # тот же момент, меньший ключ
    if pick_current([a, b]) is not b or pick_current([b, a]) is not b:
        bad += 1; print('  FAIL pick_current: порядок обхода влияет на результат')
    if pick_current([c, b]) is not b or pick_current([b, c]) is not b:
        bad += 1; print('  FAIL pick_current: tie-break по ключу')
    if pick_current([]) is not None:
        bad += 1; print('  FAIL pick_current: пусто')
    cases = [  # (статус в БД, текущее в БД, новое текущее, новый статус) → ожидание
        ('owner_reject', 'k1', 'k1', 'generated', 'owner_reject'),   # тот же меш — отказ живёт
        ('owner_reject', 'k1', 'k2', 'generated', 'generated'),      # перегон — новый меш чист
        ('owner_reject', None, 'k1', 'generated', 'generated'),      # указателя не было — не наследуем
        ('generated', 'k1', 'k1', 'generated', 'generated'),
        ('flat_shape', None, None, 'flat_shape', 'flat_shape'),
        ('replace_needed', 'k1', 'k1', 'generated', 'replace_needed'),
    ]
    for es, ec, nc, ns, want in cases:
        if revision_status(es, ec, nc, ns) != want:
            bad += 1; print(f'  FAIL revision_status {es},{ec},{nc},{ns}: ожидалось {want}')
    if generation_key('1:2', 'abcdef0123456789', 3, 'ffffffffffffffff') != '1:2|abcdef0123456789|v1|3|ffffffff':
        bad += 1; print('  FAIL generation_key')
    if 'owner_verdict' in build_sql([{**a, 'revision_key': 'x|s|v1', 'sku': 'x', 'sha16': 's', 'seed': 0,
                                      'glb_sha': 'aaaaaaaaaaaaaaaa', 'job_id': 'j', 'path': '/p',
                                      'glb_bytes': 1, 'glb_mtime': 1.0, 'machine_verdict': None,
                                      'manifest': {}}], []).split('on conflict (generation_key)')[1].split(';')[0]:
        bad += 1; print('  FAIL build_sql: upsert поколения трогает owner_verdict')
    print(f'ingest_registry selftest: случаев {len(cases) + 5}, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    elif '--report' in sys.argv:
        report()
    else:
        main()
