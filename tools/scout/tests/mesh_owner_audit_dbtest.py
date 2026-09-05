#!/usr/bin/env python3
"""`--dbtest` учёта мешей (план mesh-owner-audit): транзакционные гарантии на ОДНОРАЗОВОЙ базе.

`--selftest` в CI гоняет чистые правила без базы, но главное здесь — как правила ведут себя на
живых таблицах: не откатит ли повторный прогон реестра отказ владельца, отвяжет ли `mesh_bind`
отвергнутый меш и не воскресит ли старую попытку, не унаследует ли перегон ориентацию старого
файла. Поэтому создаётся база `remlab_dbtest_<pid>` в том же контейнере `remlab-devdb`, к ней
применяются те же миграции, во временном каталоге раскладываются «меши», и вызываются ТЕ ЖЕ
функции, что зовёт конвейер. База и каталог удаляются в `finally` — боевую базу тест не трогает.

  ~/venvs/scout/bin/python tests/mesh_owner_audit_dbtest.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.dirname(HERE)
DBNAME = f'remlab_dbtest_{os.getpid()}'
WORK = tempfile.mkdtemp(prefix='mesh-dbtest-', dir=os.path.expanduser('~/.cache'))
SRC = os.path.join(WORK, 'v2')
os.environ['REMLAB_DEVDB_NAME'] = DBNAME
os.environ['INGEST_SRC'] = SRC
sys.path.insert(0, os.path.join(SCOUT, 'salad'))
sys.path.insert(0, SCOUT)

ADMIN = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'postgres',
         '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A']
FAILS: list[str] = []


def admin(sql: str) -> None:
    r = subprocess.run(ADMIN, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])


def check(cond: bool, what: str) -> None:
    print(('  ok   ' if cond else '  FAIL ') + what, flush=True)
    if not cond:
        FAILS.append(what)


def make_gen(sku: str, sha16: str, seed: int, job: str, body: bytes, mtime: float,
             verdict: str | None = 'generated') -> str:
    d = os.path.join(SRC, sku.replace(':', '_', 1), job)
    os.makedirs(d, exist_ok=True)
    json.dump({'sku': sku, 'job_id': job, 'pipeline_version': 'v2', 'seed': seed,
               'input': {'input_hash': sha16, 'image_url': 'https://x/y.jpg'}},
              open(os.path.join(d, 'manifest.json'), 'w'))
    glb = os.path.join(d, 'model.glb')
    open(glb, 'wb').write(body)
    os.utime(glb, (mtime, mtime))
    if verdict:
        json.dump({'status': verdict}, open(os.path.join(d, 'verdict.json'), 'w'))
    return hashlib.sha256(body).hexdigest()[:16]


def main() -> int:
    admin(f'create database {DBNAME}')
    try:
        import mesh_queue
        import ingest_registry as IR
        import mesh_bind as MB
        import mesh_ready as MR
        db = mesh_queue.db
        db(mesh_queue.SCHEMA)
        db("""create table products (shop_mid int, external_id text, cat_role text, name text,
                in_stock boolean default true, image_url text, image_url_hd text,
                w_cm numeric, d_cm numeric, h_cm numeric, status text default 'active',
                asset_strategy text, params jsonb)""")
        for f in ('006-mesh-binding.sql', '008-mesh-owner-audit.sql', '009-mesh-family.sql'):
            db(open(os.path.join(SCOUT, f), encoding='utf-8').read())
        print('база и миграции готовы', flush=True)

        A, B = '1:100', '2:200'
        SHA_A, SHA_B = 'a' * 16, 'b' * 16
        # старая попытка с ЛЕКСИКОГРАФИЧЕСКИ БОЛЬШИМ job_id, новая — с меньшим: алфавит не должен решать
        old_a = make_gen(A, SHA_A, 0, 'zzz-old', b'OLD-A', 1000.0)
        new_a = make_gen(A, SHA_A, 1, 'aaa-new', b'NEW-A', 2000.0)
        gen_b = make_gen(B, SHA_B, 0, 'job-b', b'B', 1500.0)
        make_gen('3:300', 'c' * 16, 0, 'job-rug', b'RUG', 1600.0)   # ковёр: меш на диске есть, вклейка
        IR.main()
        rk_a = f'{A}|{SHA_A}|v1'
        key_new_a = f'{A}|{SHA_A}|v1|1|{new_a[:8]}'
        row = db(f"select glb_sha, current_generation_key, status from asset_revisions where revision_key='{rk_a}'")[0]
        check(row[0] == new_a and row[1] == key_new_a, 'текущее поколение — по времени, не по алфавиту')
        check(row[2] == 'generated', 'свежая ревизия — generated')
        check(int(db("select count(*) from mesh_generations")[0][0]) == 4, 'четыре физических меша — четыре строки поколений (ковёр в реестре остаётся)')

        db(f"""insert into products (shop_mid, external_id, cat_role, w_cm, h_cm, asset_strategy)
               values (1,'100','диван',200,90,'hunyuan3d'),(2,'200','кресло',80,90,'hunyuan3d'),(3,'300','ковёр',160,230,'procedural_plane');
               insert into product_photo_current (sku, source_sha) values ('{A}','{SHA_A + '0' * 48}'),('{B}','{SHA_B + '0' * 48}');
               insert into mesh_demand (sku, role, priority, source_sha) values ('{A}','диван',1,'{SHA_A + '0' * 48}'),('{B}','кресло',1,'{SHA_B + '0' * 48}');""")
        bound, unbound = MB.bind_ready()
        check(bound == 2 and unbound == 0, f'первая привязка: bound={bound}, unbound={unbound}')
        check(db("select coalesce(mesh_uri,'-') from products where external_id='300'")[0][0] == '-',
              'ковёр (вклейка по канону) к карточке не привязан, хоть меш и лежит на диске')
        # coalesce обязателен: строку из одних NULL psql печатает как «\x1f», а `str.strip()`
        # считает этот байт пробелом — строка исчезает из вывода `mesh_queue.db`
        st = db("select coalesce(mesh_status,''), coalesce(mesh_generation_key,'') from products where external_id='100'")[0]
        check(st[0] == 'ready' and st[1] == key_new_a, 'товар A привязан к новому поколению')

        # --- отказ владельца (то, что сделает sync): вердикт поколению + CAS на ревизии
        db(f"""update mesh_generations set owner_verdict='redo', owner_decision_id=1, owner_verdict_at=now()
                where generation_key='{key_new_a}';
               update asset_revisions set status='owner_reject', rejected_reason='owner'
                where revision_key='{rk_a}' and current_generation_key='{key_new_a}';""")
        IR.main()          # повторный прогон реестра
        row = db(f"select status, current_generation_key from asset_revisions where revision_key='{rk_a}'")[0]
        check(row[0] == 'owner_reject' and row[1] == key_new_a, 'повторный ingest НЕ откатывает owner_reject того же поколения')
        check(db(f"select owner_verdict from mesh_generations where generation_key='{key_new_a}'")[0][0] == 'redo',
              'ingest не трогает вердикт владельца у поколения')
        bound, unbound = MB.bind_ready()
        # пустые поля в КОНЦЕ строки psql тоже теряются (`strip` режет хвостовые \x1f) — сентинел «-»
        st = db("select coalesce(mesh_status,'-'), coalesce(mesh_uri,'-'), coalesce(mesh_generation_key,'-') from products where external_id='100'")[0]
        check(unbound == 1 and st[0] == 'rejected' and st[1] == '-' and st[2] == '-',
              f'отказ → товар без меша (rejected, ссылка пуста); старая попытка seed 0 не воскрешена')
        MB.enforce_ready_invariant()
        check(db("select coalesce(mesh_status,'') from products where external_id='100'")[0][0] == 'rejected',
              'инвариант ready/stale не возвращает отвергнутому товару ready')
        bound, unbound = MB.bind_ready()
        check(bound == 1 and unbound == 1, 'повторная привязка идемпотентна (B привязан, A отвязан)')

        # --- готовность по glb_sha: ориентация старого файла не делает новый готовым
        db(f"""insert into orientation_state (revision_key, sku, status, resolution)
               values ('{B}|{'f' * 16}|orient-v1','{B}','auto_resolved','{{"glb_sha":"{'f' * 64}"}}'::jsonb)""")
        MR._CACHE = None
        check(not MR.mesh_ready(B), 'ориентация ЧУЖОГО файла не даёт готовности')
        db(f"""update orientation_state set resolution=jsonb_set(resolution,'{{glb_sha}}','"{gen_b + 'e' * 48}"') where sku='{B}'""")
        MR._CACHE = None
        check(MR.mesh_ready(B), 'ориентация ТОГО ЖЕ файла — готов')
        MR._CACHE = None
        check(not MR.mesh_ready(A), 'отвергнутый товар не готов, даже с ориентацией')

        # --- перегон: новое поколение чисто, товар снова привязан
        newer_a = make_gen(A, SHA_A, 2, 'mmm-newer', b'NEWER-A', 3000.0)
        IR.main()
        key_newer_a = f'{A}|{SHA_A}|v1|2|{newer_a[:8]}'
        row = db(f"select status, current_generation_key, glb_sha from asset_revisions where revision_key='{rk_a}'")[0]
        check(row[0] == 'generated' and row[1] == key_newer_a and row[2] == newer_a,
              'перегон: новое поколение текущее и generated, отказ не унаследован')
        check(db(f"select owner_verdict from mesh_generations where generation_key='{key_new_a}'")[0][0] == 'redo',
              'вердикт старого поколения сохранён в истории')
        bound, unbound = MB.bind_ready()
        st = db("select coalesce(mesh_status,''), coalesce(mesh_generation_key,'') from products where external_id='100'")[0]
        check(st[0] == 'ready' and st[1] == key_newer_a, 'товар A привязан к перегону')

        # --- семейства: один меш на модель — вариант цвета получает меш представителя
        import mesh_family as MF
        db("""insert into products (shop_mid, external_id, cat_role, name, w_cm, d_cm, h_cm, asset_strategy, mesh_required, params)
               values (1,'101','диван','Диван Тест Велюр Синий',200,90,80,'hunyuan3d',true,'{"Ткань":"Велюр"}'),
                      (1,'100b','кресло','Кресло Другое',80,80,90,'hunyuan3d',true,'{}');
               update products set mesh_required=true, params='{"Ткань":"Велюр"}', name='Диван Тест Велюр Белый', d_cm=90, h_cm=80 where external_id='100';
               update products set mesh_required=true where external_id='200';""")
        MF.fill()
        fam = {r[0]: (r[1], r[2]) for r in db("select external_id, coalesce(mesh_family,'-'), coalesce(mesh_family_rep,'-') from products where shop_mid=1")}
        check(fam['100'][0] == fam['101'][0] and fam['100'][0] != '-', 'варианты цвета — одно семейство')
        check(fam['100'][1] == '1:100' and fam['101'][1] == '1:100', 'представитель — тот, у кого есть меш (A), вариант указывает на него')
        check(fam['100b'][1] == '1:100b', 'другая модель — сама себе представитель')
        MB.bind_ready(); MB.enforce_ready_invariant(); nv = MB.propagate_family()
        v = db("select coalesce(mesh_status,'-'), coalesce(mesh_generation_key,'-'), coalesce(mesh_uri,'-') from products where external_id='101'")[0]
        check(nv == 1 and v[1] == key_newer_a and v[2].startswith('file://'), f'вариант получил меш представителя: {v}')
        MR._CACHE = None
        check(MR.mesh_ready('1:101') == MR.mesh_ready('1:100') is False, 'без ориентации представителя не готовы оба')
        db(f"""insert into orientation_state (revision_key, sku, status, resolution)
               values ('{A}|{newer_a}|orient-v1','{A}','auto_resolved','{{"glb_sha":"{newer_a + 'e' * 48}"}}'::jsonb)""")
        MR._CACHE = None
        check(MR.mesh_ready('1:100') and MR.mesh_ready('1:101'), 'вариант готов, когда готов представитель')
        # представитель липкий: новый меш у варианта не перехватывает семейство
        make_gen('1:101', 'd' * 16, 0, 'job-var', b'VAR', 4000.0)
        IR.main(); MF.fill()
        check(db("select mesh_family_rep from products where external_id='101'")[0][0] == '1:100', 'представитель не меняется от нового меша варианта')
        # отказ владельца по представителю гасит всё семейство
        db(f"""update mesh_generations set owner_verdict='redo', owner_decision_id=9 where generation_key='{key_newer_a}';
               update asset_revisions set status='owner_reject' where current_generation_key='{key_newer_a}';""")
        MB.bind_ready(); MB.enforce_ready_invariant(); MB.propagate_family()
        check(db("select coalesce(mesh_status,'-')||'/'||coalesce(mesh_uri,'-') from products where external_id='101'")[0][0] == 'rejected/-',
              'отказ по представителю: вариант тоже без меша')
        MR._CACHE = None
        check(not MR.mesh_ready('1:101'), 'вариант не готов после отказа по представителю')
        # --- хеш из кэша: повторный прогон без изменений файлов ничего не хеширует заново
        known = {r[1]: {'glb_bytes': r[2], 'glb_mtime': r[3], 'glb_sha': r[4]}
                 for r in db("select generation_key, path, glb_bytes, glb_mtime, glb_sha from mesh_generations")}
        gens, _, unexpl = IR.scan(SRC, known)
        check(len(gens) == 6 and not unexpl and all(g['path'] in known for g in gens), 'кэш хешей по размеру и mtime')
    finally:
        try:
            admin(f"select pg_terminate_backend(pid) from pg_stat_activity where datname='{DBNAME}' and pid <> pg_backend_pid()")
            admin(f'drop database if exists {DBNAME}')
        finally:
            shutil.rmtree(WORK, ignore_errors=True)
    print(f'dbtest: ошибок {len(FAILS)}' + (': ' + '; '.join(FAILS) if FAILS else ''), flush=True)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
