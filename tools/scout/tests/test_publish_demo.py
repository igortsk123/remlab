"""publish_demo.sh: копия прежней версии перед публикацией и откат (T-20261105-59).
Без сети: в PATH подменены `ssh` (команда исполняется локально, stdin — серверный скрипт), `scp` (копия файла по пути
после «хост:») и `curl` (код ответа — из FAKE_HTTP). «Сервер» — временная папка (PUB_ROOT), chown выключен.
- первая публикация — без копии; файлы версий одного размера и одной секунды обновляются (сверка содержимого); дальше перед каждой — копия `demo.prev-<метка>` с прежним содержимым (sha файлов),
  `topsprites/` живой папки не трогается и в копию не идёт; файл, исчезнувший из сборки, уходит с витрины;
- хранится PUB_KEEP копий, старшие убраны; чужие папки рядом (`demo.prev-junk`, `demo-x.prev-…`) не тронуты;
- откат без метки возвращает прошлую версию (sha), сам каталог тот же (inode — монтирование Caddy, урок 430),
  то, что было до отката, — в `…-undo`; второй откат — ещё на шаг назад; откат на `…-undo` — отмена отката;
  смена «файл ↔ папка» между версиями переживается;
- запреты: PUB_DIR не demo/test/<имя>, кривая метка, сборка без index.html (витрина не тронута), страница не ответила
  после публикации — код 1 с подсказкой про откат;
- не молчит и не живёт в /tmp (T-20261106-87): архив — в PUB_TMP; упаковка упала без вывода (`tar` подменён) — код 2 и строка
  «сбой в строке … tar czf … (код 2)»; места мало (`df` подменён) — отказ до упаковки с цифрами; отказы-проверки строку сбоя не печатают.
- фото нейросети до выкладки (T-20261107-34): ручная выкладка главной сперва снимает фото новой сборки (подменная команда вместо
  ПЛАТНОГО demo-real.sh), ночь (PUB_PHOTOS_DONE=1) и проба /test/ — без съёмки; съёмка упала / openai.off — публикация есть, WARN.
Папка случая: PUB_TEST_DIR (не удаляется) или во временной папке процесса на диске (`remlab_tmp.use`): успех — убирается,
провал — остаётся (T-20261107-13; раньше — в /tmp навсегда).
    python3 tools/scout/tests/test_publish_demo.py"""
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
import build_stamp  # noqa: E402
remlab_tmp.use('test_publish_demo')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, '..', 'publish_demo.sh')
BAD = []


def ok(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True)
    if not cond:
        BAD.append(msg)


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def tree(d, skip=('topsprites',)):
    """{относительный путь: sha256} — файлы, без topsprites."""
    out = {}
    for root, dirs, files in os.walk(d):
        if os.path.relpath(root, d) == '.':
            dirs[:] = [x for x in dirs if x not in skip]
        for f in files:
            p = os.path.join(root, f)
            out[os.path.relpath(p, d)] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    return out


def shims(bin_dir):
    os.makedirs(bin_dir, exist_ok=True)
    files = {
        # ssh -p N -o X host "команда" — исполнить команду здесь же, stdin как есть
        'ssh': '#!/usr/bin/env bash\necho "ssh $*" >> "$SHIM_LOG"\nfor a; do last=$a; done\nexec bash -c "$last"\n',
        # scp -P N -o X файл хост:путь — копия по пути после «:»
        'scp': '#!/usr/bin/env bash\necho "scp $*" >> "$SHIM_LOG"\nargs=("$@"); n=${#args[@]}\n'
               'cp "${args[$((n-2))]}" "${args[$((n-1))]#*:}"\n',
        'curl': '#!/usr/bin/env bash\necho "curl $*" >> "$SHIM_LOG"\nprintf %s "${FAKE_HTTP:-200}"\n',
        # вместо `tools/ops/demo-real.sh` (ПЛАТНО) — запись «что сняли бы» и код FAKE_PHOTOS_RC (T-20261107-34)
        'photos': '#!/usr/bin/env bash\necho "photos DEMO_LOCAL=$DEMO_LOCAL $*" >> "$SHIM_LOG"\nexit "${FAKE_PHOTOS_RC:-0}"\n',
        # сжатие упало целиком (нет node и т.п., T-20261110-43/2) — ничего не сделав
        'precompress-fail': '#!/usr/bin/env bash\necho "precompress-fail $*" >> "$SHIM_LOG"\nexit 1\n',
        # вместо `tools/ops/tour-reissue.sh` (автоперевыпуск туров, T-20261112-92) — запись «перевыпустили бы» и код FAKE_REISSUE_RC
        'reissue': '#!/usr/bin/env bash\necho "reissue $*" >> "$SHIM_LOG"\nexit "${FAKE_REISSUE_RC:-0}"\n',
        # FAKE_TAR_FAIL=1 — упаковка (czf) падает молча с кодом 2, как `tar` при забитом /tmp, когда и его сообщение
        # некуда записать (T-20261106-87); иначе — настоящий tar (распаковка на «сервере» тоже идёт через него)
        'tar': '#!/usr/bin/env bash\nif [ -n "${FAKE_TAR_FAIL:-}" ] && [ "${1:-}" = czf ]; then exit 2; fi\n'
               'exec "$(PATH=${PATH#*:} command -v tar)" "$@"\n',
        # FAKE_DF_FREE=N — «свободно N МБ» в любой папке; иначе — настоящий df
        'df': '#!/usr/bin/env bash\nif [ -n "${FAKE_DF_FREE:-}" ]; then\n'
              '  echo "Filesystem 1048576-blocks Used Available Capacity Mounted on"; echo "fake 1000 0 $FAKE_DF_FREE 0% /"; exit 0\nfi\n'
              'exec "$(PATH=${PATH#*:} command -v df)" "$@"\n',
    }
    for name, body in files.items():
        p = os.path.join(bin_dir, name)
        with open(p, 'w') as f:
            f.write(body)
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def main():
    base = os.environ.get('PUB_TEST_DIR') or tempfile.mkdtemp(prefix='pubdemo-test-')
    os.makedirs(base, exist_ok=True)
    print('папка случая:', base)
    srv, rtmp, src_root, bin_dir = (os.path.join(base, x) for x in ('srv', 'rtmp', 'src', 'bin'))
    for d in (srv, rtmp, src_root):
        os.makedirs(d, exist_ok=True)
    shims(bin_dir)
    src = os.path.join(src_root, 'flat215-demo')
    live = os.path.join(srv, 'demo')

    def env(**kw):
        # метку ночного прогона (REFRESH_DAILY_RUN) не наследуем: самопроверку может звать сама ночь — случаи задают её явно
        e = {k: v for k, v in os.environ.items() if not k.startswith('PUB_') and k != 'REFRESH_DAILY_RUN'}
        e.update(PATH=bin_dir + os.pathsep + os.environ['PATH'], PUB_ROOT=srv, PUB_RTMP=rtmp, PUB_CHOWN='',
                 PUB_SRC=src, PUB_KEEP='3', SHIM_LOG=os.path.join(base, 'shim.log'), TMPDIR=base,
                 PUB_TMP=os.path.join(base, 'pubtmp'),
                 # съёмка фото до выкладки — всегда подменная, рубильник openai.off — свой файл случая (не tools/scout/openai.off)
                 PUB_PHOTOS_CMD=os.path.join(bin_dir, 'photos'), PUB_OFF_FLAG=os.path.join(base, 'openai.off'),
                 # перевыпуск туров после выкладки — всегда подменный (настоящий пересобрал бы туры агентов на проде)
                 PUB_REISSUE_CMD=os.path.join(bin_dir, 'reissue'))
        e.update(kw)
        return e

    def run(*args, **kw):
        r = subprocess.run(['bash', SCRIPT, *args], env=env(**kw), capture_output=True, text=True, timeout=120)
        with open(os.path.join(base, 'runs.log'), 'a', encoding='utf-8') as f:
            f.write(f'$ {" ".join(args)} {kw}\nrc={r.returncode}\n{r.stdout}{r.stderr}\n')
        return r

    def build(ver, extra=None, mock_dir=False):
        """Сборка версии `ver`: index.html, demo-data.json, lib/scene.js, файл только этой версии; mock — файл или папка."""
        shutil.rmtree(src, ignore_errors=True)
        put(os.path.join(src, 'index.html'), f'<html>v{ver}</html>')
        # метка правил = правила этой копии: публикатор сверяет её до выкладки (T-20261112-121, шаг 5; случай 15 — отказы)
        put(os.path.join(src, 'demo-data.json'), '{"v": %d, "build": "test.%s"}' % (ver, build_stamp.rules_hash()))
        put(os.path.join(src, 'lib', 'scene.js'), f'// v{ver}')
        put(os.path.join(src, f'only-v{ver}.txt'), str(ver))
        if mock_dir:
            put(os.path.join(src, 'mock', 'a.txt'), f'mock dir v{ver}')
        else:
            put(os.path.join(src, 'mock'), f'mock file v{ver}')
        for k, v in (extra or {}).items():
            put(os.path.join(src, k), v)
        # версии пишутся в одну секунду и файлы одного размера: публикация обязана сверять содержимое (--checksum),
        # а не «размер+время» rsync (сухой прогон T-59: lib/scene.js не обновился)
        return tree(src)

    def prevs(kind='reg'):
        out = []
        for n in sorted(os.listdir(srv)):
            if re.fullmatch(r'demo\.prev-\d{8}-\d{6}(-undo)?', n):
                undo = n.endswith('-undo')
                if kind == 'all' or (kind == 'undo') == undo:
                    out.append(n)
        return out

    # чужие папки рядом — скрипт их трогать не должен
    for n in ('demo.prev-junk', 'demo-x.prev-20200101-000000', 'demo.prevX'):
        put(os.path.join(srv, n, 'keep.txt'), n)
    put(os.path.join(srv, 'demo.prev-2020-01-01', 'keep.txt'), 'неверный вид метки')

    # 1. первая публикация
    v1 = build(1)
    r = run()
    ok(r.returncode == 0, f'первая публикация: код 0 ({r.returncode}: {(r.stdout + r.stderr).strip()[-200:]})')
    ok(tree(live) == v1, 'витрина = сборка v1')
    ok(prevs() == [], 'копии при первой публикации нет')
    ok('прежней версии нет' in r.stdout, 'сказано, что копию не делаем')
    # виды сверху приезжают на сервер отдельно
    put(os.path.join(live, 'topsprites', 's1.png'), 'sprite')
    ino = os.stat(live).st_ino

    # 2. вторая публикация: копия v1
    v2 = build(2, mock_dir=True)
    r = run()
    ok(r.returncode == 0, 'вторая публикация: код 0')
    t = tree(live)
    ok(t == v2, f'витрина = v2 (файл только v1 ушёл, mock стал папкой) {sorted(set(t.items()) ^ set(v2.items()))}')
    ok(len(prevs()) == 1 and tree(os.path.join(srv, prevs()[0])) == v1, f'копия прежней версии = v1 ({prevs()})')
    ok(not os.path.exists(os.path.join(srv, prevs()[0], 'topsprites')), 'topsprites в копию не идут')
    ok(os.path.exists(os.path.join(live, 'topsprites', 's1.png')), 'topsprites витрины на месте')
    ok(os.stat(live).st_ino == ino, 'каталог витрины тот же (inode)')
    ok(not os.path.exists(os.path.join(srv, '.demo-new')) and not os.listdir(rtmp), 'временные папка и архив убраны')

    # 3. ещё три публикации: хранится 3 копии, старшая убрана
    vers = {1: v1, 2: v2}
    for k in (3, 4, 5):
        vers[k] = build(k, mock_dir=(k == 4))
        r = run()
        ok(r.returncode == 0, f'публикация v{k}: код 0')
    ok(tree(live) == vers[5], 'витрина = v5')
    ps = prevs()
    ok(len(ps) == 3, f'хранится 3 копии ({ps})')
    ok([tree(os.path.join(srv, p)) for p in ps] == [vers[2], vers[3], vers[4]], 'копии = v2, v3, v4 (v1 убрана)')
    ok('убрана старая копия' in r.stdout, 'уборка старшей копии сказана в журнале')
    for n in ('demo.prev-junk', 'demo-x.prev-20200101-000000', 'demo.prevX', 'demo.prev-2020-01-01'):
        ok(os.path.exists(os.path.join(srv, n, 'keep.txt')), f'чужая папка {n} не тронута')
    lst = run('--list')
    ok(lst.returncode == 0 and all(p in lst.stdout for p in ps), '--list показывает копии')

    # 4. откат без метки → v4
    r = run('--rollback')
    ok(r.returncode == 0, f'откат: код 0 ({(r.stdout + r.stderr).strip()[-200:]})')
    ok(tree(live) == vers[4], 'после отката витрина = v4 (sha всех файлов)')
    ok(os.stat(live).st_ino == ino, 'откат не подменил сам каталог (inode тот же)')
    ok(os.path.exists(os.path.join(live, 'topsprites', 's1.png')), 'topsprites после отката на месте')
    ok(os.path.isdir(os.path.join(live, 'mock')), 'mock снова папка, как в v4')
    u = prevs('undo')
    ok(len(u) == 1 and tree(os.path.join(srv, u[0])) == vers[5], f'то, что было до отката (v5), — в {u}')
    ok(len(prevs()) == 2, f'копия v4 израсходована, обычных копий 2 ({prevs()})')
    ok('--rollback ' + u[0].split('.prev-')[1] in r.stdout, 'напечатано, как отменить откат')

    # 5. второй откат без метки → ещё шаг назад (v3), а не обратно на плохую v5
    r = run('--rollback')
    ok(r.returncode == 0 and tree(live) == vers[3], 'второй откат: витрина = v3')
    ok(not os.path.isdir(os.path.join(live, 'mock')) and os.path.isfile(os.path.join(live, 'mock')), 'mock снова файл (v3)')

    # 6. отмена отката: на первую копию «до отката» → v5
    r = run('--rollback', u[0].split('.prev-')[1])
    ok(r.returncode == 0 and tree(live) == vers[5], f'откат на {u[0]} вернул v5')
    ok(os.stat(live).st_ino == ino, 'каталог витрины всё тот же')

    # 7. запреты
    for args, kw, why in ((('--rollback', '2026-11-06'), {}, 'кривая метка'),
                          (('--rollback', "1'; touch /tmp/x; '"), {}, 'метка с кавычкой'),
                          ((), {'PUB_DIR': 'caddy'}, 'PUB_DIR не demo/test'),
                          ((), {'PUB_DIR': 'test/../demo'}, 'PUB_DIR с ..'),
                          ((), {'PUB_DIR': '/opt/remlab/demo'}, 'PUB_DIR абсолютный'),
                          ((), {'PUB_ROOT': '/x; rm -rf /'}, 'PUB_ROOT со спецсимволами'),
                          (('--what',), {}, 'неизвестный ключ')):
        r = run(*args, **kw)
        ok(r.returncode == 2, f'{why}: отказ, код 2 ({r.returncode})')
    ok(tree(live) == vers[5], 'после запретов витрина не тронута')
    r = run('--rollback', '20990101-000000')
    ok(r.returncode == 1 and 'нет' in r.stdout, 'откат на несуществующую метку: код 1')

    # 8. сборка без index.html — не публикуем, витрина цела
    before = tree(live)
    os.unlink(os.path.join(src, 'index.html'))
    r = run()
    ok(r.returncode == 1 and tree(live) == before, 'нет index.html в сборке: код 1, витрина цела')

    # 9. страница не ответила после публикации — код 1 и подсказка про откат
    build(6)
    r = run(FAKE_HTTP='404')
    ok(r.returncode == 1 and '--rollback' in r.stdout, 'HTTP 404 после публикации: код 1, подсказка про откат')
    r = run('--rollback')
    ok(r.returncode == 0 and tree(live) == vers[5], 'и откат после неё вернул прежнюю версию (v5)')

    # 10. проба на /test/<имя>: своя папка и свои копии, главная не тронута
    main_before = tree(live)
    build(7)
    r = run(PUB_DIR='test/pubsafe-probe')
    r2 = run(PUB_DIR='test/pubsafe-probe')
    tdir = os.path.join(srv, 'test')
    ok(r.returncode == 0 and r2.returncode == 0, 'публикация в test/pubsafe-probe: код 0')
    ok(any(n.startswith('pubsafe-probe.prev-') for n in os.listdir(tdir)), 'копия появилась рядом с папкой пробы')
    ok(tree(live) == main_before, 'главная витрина при пробе не тронута')
    ok(any('remont-lab.online/test/pubsafe-probe/' in ln for ln in open(os.path.join(base, 'shim.log'))),
       'проверка страницы — по адресу пробы')

    # 11. архив — в PUB_TMP (на диске), не в /tmp (T-20261106-87)
    pubtmp = os.path.join(base, 'pubtmp')
    scps = [ln for ln in open(os.path.join(base, 'shim.log')) if ln.startswith('scp ')]
    ok(scps and all(pubtmp + '/flat215-demo.' in ln for ln in scps), 'архив сборки создаётся в PUB_TMP, не в /tmp')
    ok(os.path.isdir(pubtmp) and not os.listdir(pubtmp), 'после публикаций в PUB_TMP архивов не осталось')

    # 12. упаковка упала молча (код 2, без вывода — забитый /tmp 06.11): код не 0 и названа причина; витрина цела
    before = tree(live)
    build(8)
    r = run(FAKE_TAR_FAIL='1')
    out = r.stdout + r.stderr
    ok(r.returncode == 2, f'tar упал: код скрипта 2, как у tar ({r.returncode})')
    ok('сбой в строке' in out and 'tar czf' in out and '(код 2)' in out, f'причина напечатана: {out.strip()[-200:]!r}')
    ok(tree(live) == before and not os.listdir(pubtmp), 'витрина цела, недописанный архив убран')

    # 13. места под архив мало — отказ до упаковки, с цифрами
    r = run(FAKE_DF_FREE='5')
    out = r.stdout + r.stderr
    ok(r.returncode == 1 and 'мало места под архив' in out and 'свободно 5 МБ' in out, f'мало места: код 1 и цифры ({out.strip()[-160:]!r})')
    ok(tree(live) == before, 'при нехватке места витрина цела')

    # 15. ФОТО НЕЙРОСЕТИ ДО ВЫКЛАДКИ (photo-before-publish-01, T-20261107-34): ручная выкладка главной сперва снимает фото новой
    # сборки (DEMO_LOCAL = сборка) и только потом пакует; ночь (PUB_PHOTOS_DONE=1) и проба под /test/ — без съёмки; съёмка упала
    # или openai.off — публикация всё равно идёт (держим фото, не сборку: TG 378), с WARN
    def shim_since(n):
        return open(os.path.join(base, 'shim.log'), encoding='utf-8').read().splitlines()[n:]

    def shim_len():
        return len(open(os.path.join(base, 'shim.log'), encoding='utf-8').read().splitlines())
    n0 = shim_len()
    v9 = build(9)
    r = run()
    lines = shim_since(n0)
    ph = [i for i, ln in enumerate(lines) if ln.startswith('photos ')]
    sc = [i for i, ln in enumerate(lines) if ln.startswith('scp ')]
    ok(r.returncode == 0 and tree(live) == v9 and len(ph) == 1 and sc and ph[0] < sc[0] and lines[ph[0]] == f'photos DEMO_LOCAL={src} ',
       f'ручная выкладка главной: сперва фото новой сборки (DEMO_LOCAL — сборка), потом архив и публикация ({lines[:3]!r})')
    for kw, why in (({'PUB_PHOTOS_DONE': '1'}, 'ночь (PUB_PHOTOS_DONE=1) — фото уже сняты'),
                    ({'PUB_DIR': 'test/pubsafe-probe'}, 'проба под /test/')):
        n0 = shim_len()
        build(10)
        r = run(**kw)
        ok(r.returncode == 0 and not any(ln.startswith('photos ') for ln in shim_since(n0)), f'{why} — без съёмки, публикация есть')
    n0 = shim_len()
    v11 = build(11)
    r = run(FAKE_PHOTOS_RC='3')
    ok(r.returncode == 0 and tree(live) == v11 and 'WARN:publish_demo: досъёмка фото — код 3' in r.stdout
       and any(ln.startswith('photos ') for ln in shim_since(n0)), f'съёмка упала — публикация всё равно есть, WARN ({r.stdout[-200:]!r})')
    put(os.path.join(base, 'openai.off'), '')
    n0 = shim_len()
    v12 = build(12)
    r = run()
    os.remove(os.path.join(base, 'openai.off'))
    ok(r.returncode == 0 and tree(live) == v12 and 'WARN:publish_demo: платные шаги выключены (openai.off)' in r.stdout
       and not any(ln.startswith('photos ') for ln in shim_since(n0)), 'openai.off — без съёмки, с WARN, публикация есть')

    # 16. ЗАРАНЕЕ СЖАТЫЕ КОПИИ (T-20261110-43/2): тексты ≥ 1 КБ уезжают с `.br`/`.gz` рядом (Caddy `precompressed`); исходник
    # переписан — копии новые; сжатие упало целиком — старые копии сборки убраны и на витрину не едут (устаревшая копия хуже
    # сжатия на лету: Caddy отдал бы старый текст); мелкие файлы (случаи выше) — без копий
    import gzip
    big = lambda v: '<html>' + f'<p>версия {v}</p>' * 300 + '</html>'   # noqa: E731
    build(13, extra={'index.html': big(13)})
    r = run(PUB_PHOTOS_DONE='1')
    gz = os.path.join(live, 'index.html.gz')
    ok(r.returncode == 0 and os.path.isfile(os.path.join(live, 'index.html.br')) and os.path.isfile(gz)
       and gzip.decompress(open(gz, 'rb').read()).decode() == big(13), f'сжатые копии разметки на витрине ({r.stdout[-200:]!r})')
    ok(not os.path.exists(os.path.join(live, 'demo-data.json.br')), 'файл < 1 КБ — без сжатой копии')
    ok(tree(live) == tree(src), 'витрина = сборка вместе со сжатыми копиями')
    build(14, extra={'index.html': big(14)})
    r = run(PUB_PHOTOS_DONE='1')
    ok(r.returncode == 0 and gzip.decompress(open(gz, 'rb').read()).decode() == big(14), 'новая сборка — копии пересжаты')
    build(15, extra={'index.html': big(15)})
    put(os.path.join(src, 'index.html.br'), 'старая копия')
    put(os.path.join(src, 'index.html.gz'), 'старая копия')
    r = run(PUB_PHOTOS_DONE='1', PUB_PRECOMPRESS_CMD=os.path.join(bin_dir, 'precompress-fail'))
    ok(r.returncode == 0 and 'WARN:publish_demo: заранее сжать не вышло' in r.stdout
       and not os.path.exists(os.path.join(live, 'index.html.br')) and not os.path.exists(gz)
       and open(os.path.join(live, 'index.html'), encoding='utf-8').read() == big(15),
       f'сжатие упало — публикация есть, старых сжатых копий на витрине нет ({r.stdout[-200:]!r})')

    # 17. АВТОПЕРЕВЫПУСК ТУРОВ (T-20261112-92): после выкладки главной и после отката — перевыпуск туров агентов; PUB_REISSUE=0
    # (ночь зовёт его своим шагом) и проба под /test/ — нет; сбой перевыпуска выкладку не валит (WARN)
    reissued = lambda n: [ln for ln in shim_since(n) if ln.startswith('reissue ')]  # noqa: E731
    build(16)
    n = shim_len()
    r = run(PUB_PHOTOS_DONE='1')
    ok(r.returncode == 0 and reissued(n) == ['reissue --why выкладка'], f'выкладка главной — перевыпуск туров ({reissued(n)})')
    n = shim_len()
    r = run('--rollback')
    ok(r.returncode == 0 and reissued(n) == ['reissue --why откат'], f'откат главной — перевыпуск туров ({reissued(n)})')
    build(17)
    # PUB_REISSUE=0 — ТОЛЬКО НОЧИ (T-20261112-92/11): живой прогон refresh_daily (его pid в REFRESH_DAILY_RUN; здесь — pid самой
    # самопроверки, он жив) — без перевыпуска; без метки, с мёртвым pid или мусором — перевыпуск всё равно и WARN (13.11 ручные
    # выкладки с PUB_REISSUE=0 оставили 18 туров на старой витрине)
    n = shim_len()
    r = run(PUB_PHOTOS_DONE='1', PUB_REISSUE='0', REFRESH_DAILY_RUN=str(os.getpid()))
    ok(r.returncode == 0 and not reissued(n) and 'WARN:publish_demo: PUB_REISSUE=0' not in r.stdout,
       'PUB_REISSUE=0 от ночного прогона — без перевыпуска')
    p = subprocess.Popen(['true']); p.wait(); dead_pid = p.pid   # завершённый процесс — его pid больше не жив
    for why, mark in (('без метки ночи', None), ('pid ночи не жив', str(dead_pid)), ('метка не число', 'ночь')):
        build(17)
        n = shim_len()
        kw = dict(PUB_PHOTOS_DONE='1', PUB_REISSUE='0')
        if mark is not None:
            kw['REFRESH_DAILY_RUN'] = mark
        r = run(**kw)
        ok(r.returncode == 0 and reissued(n) == ['reissue --why выкладка']
           and 'WARN:publish_demo: PUB_REISSUE=0 принимается только от ночного прогона' in r.stdout,
           f'PUB_REISSUE=0 {why} — перевыпуск всё равно, WARN ({reissued(n)})')
    n = shim_len()
    r = run('--rollback', PUB_REISSUE='0')
    ok(r.returncode == 0 and reissued(n) == ['reissue --why откат'] and 'WARN:publish_demo: PUB_REISSUE=0' in r.stdout,
       f'откат с PUB_REISSUE=0 без ночи — перевыпуск всё равно ({reissued(n)})')
    n = shim_len()
    r = run(PUB_DIR='test/pubsafe-probe')
    ok(r.returncode == 0 and not reissued(n), 'проба под /test/ — без перевыпуска')
    build(18)
    r = run(PUB_PHOTOS_DONE='1', FAKE_REISSUE_RC='3')
    ok(r.returncode == 0 and 'WARN:publish_demo: перевыпуск туров — код 3' in r.stdout, 'сбой перевыпуска — выкладка есть, WARN')
    # ночь ставит метку прогона ДО своей строки публикации с PUB_REISSUE=0 — иначе ночь перевыпускала бы туры дважды (с WARN)
    rd = open(os.path.join(HERE, '..', 'refresh_daily.sh'), encoding='utf-8').read()
    i_mark, i_pub = rd.find('export REFRESH_DAILY_RUN=$$'), rd.find('PUB_REISSUE=0 bash publish_demo.sh')
    ok(0 <= i_mark < i_pub, 'refresh_daily.sh: метка ночи (export REFRESH_DAILY_RUN=$$) стоит до строки публикации')

    # 14. запреты (код 2 из проверок) не печатают ложный «сбой в строке»
    r = run(PUB_DIR='caddy')
    ok(r.returncode == 2 and 'сбой в строке' not in r.stdout + r.stderr, 'отказ по PUB_DIR — без строки «сбой»')

    # 15. сборка не по правилам этой копии (T-20261112-121, шаг 5): нет метки / другие правила / битые данные — код 1 до съёмки
    # и упаковки, витрина цела, «пересоберите flat215_demo.py»
    for why, text in (('без метки правил', '{"v": 19}'),
                      ('метка других правил', '{"v": 19, "build": "test.0123456789"}'),
                      ('битые данные', '{"v": 19')):
        build(19)
        put(os.path.join(src, 'demo-data.json'), text)
        before, n = tree(live), shim_len()
        r = run()
        out = r.stdout + r.stderr
        ok(r.returncode == 1 and tree(live) == before and not shim_since(n) and 'flat215_demo.py' in out
           and 'сбой в строке' not in out, f'{why}: отказ (код {r.returncode}), витрина цела, без съёмки и scp: {out.strip()[-160:]}')

    print('итог:', 'OK' if not BAD else f'FAIL ({len(BAD)})')
    if BAD:
        remlab_tmp.keep('провал test_publish_demo')   # папка случая — для разбора (успех — убирается, T-20261107-13)
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
