"""СТОРОЖ ЧТЕНИЙ ВХОДА РЕНДЕРА (T-20261118-04/16/1, план `render-key-01` п.3; подключён в `conveyor_check.py`).

Ключ кадра комнаты (`tools/scout/render_input.py`) честен, пока ВСЁ, что страница-дампер читает, лежит в нём. Дампер (`demo_scene_dump.mjs`) пишет `dump/reads.json`, исполнитель
сверяет его с входом комнаты ПЕРЕД рендером (`render_exec.check_dump_reads`); здесь — предохранитель на САМ дампер, чтобы новая дорога чтения не прошла незамеченной в коммите:
  • каждая отдача файла страницы идёт через `sendLocal` (он пишет чтение), голых `createReadStream(...).pipe(res)` нет (кроме самой страницы и `entry.js`);
  • каждая дорога по адресу (`u.match(/…/)`) — из списка известных; новая дорога без правила в `render_input._URL_RULES` — красный;
  • известные адреса дампера разбираются `render_input.logical_of` (и с запросом `?v=`);
  • в сетевой ветке есть герметичный отказ (`HERMETIC`), пишется `reads.json`, таблица runtime-мешей — зафиксированная (`pinned`) в герметичном режиме.
    python3 tools/ops/render_inputs.py            # проверка
    python3 tools/ops/render_inputs.py --selftest
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DEFAULT = os.path.abspath(os.path.join(HERE, '..', '..'))
DUMPER = 'tools/scout/cycles_probe/demo_scene_dump.mjs'
# дороги дампера по адресу — как они записаны в исходнике (`u.match(/…/)`); новая запись обязана получить правило в `render_input._URL_RULES`
KNOWN_ROUTES = (
    r'/^\/(flat3d\/env|scene\/views)\/([A-Za-z0-9._-]+)$/',
    r'/^\/flat3d\/(materials|plants)\/([A-Za-z0-9._-]+)$/',
    r'/^\/demo\/(img\/[A-Za-z0-9._-]+)$/',
    r'/^\/test\/mesh-pilot10\/([^/]+)\/model\.glb$/',
)
KNOWN_URLS = ('/test/mesh-pilot10/112923_1/model.glb', '/demo/img/a.jpg', '/demo/img/a-art.jpg', '/flat3d/env/outside.webp', '/scene/views/yard.webp',
              '/flat3d/materials/finish-wall-v1-lite.webp', '/flat3d/plants/pachira-c.glb?v=6')


def check_source(src: str, logical_of=None) -> list:
    fails = []
    routes = re.findall(r'(?<![\w.])u\.match\((/[^\n]*?/)\)', src)
    for r in routes:
        if r not in KNOWN_ROUTES:
            fails.append(f'дампер: новая дорога чтения {r} — добавь правило в render_input._URL_RULES и в KNOWN_ROUTES (tools/ops/render_inputs.py)')
    for r in KNOWN_ROUTES:
        if r not in routes:
            fails.append(f'дампер: известная дорога {r} пропала или переписана — сверь render_input._URL_RULES и KNOWN_ROUTES')
    pipes = [ln for ln in src.split('\n') if 'createReadStream' in ln and '.pipe(res)' in ln]
    bad = [ln for ln in pipes if 'sendLocal' not in ln and "entry.js" not in ln]
    if bad:
        fails.append(f'дампер: отдача файла мимо sendLocal (чтение не попадёт в reads.json): {bad[0].strip()[:120]}')
    for need, why in (('const sendLocal', 'нет sendLocal'), ('reads.json', 'не пишется reads.json'), ('HERMETIC', 'нет герметичного режима'),
                      ("'pinned'", 'таблица runtime-мешей не фиксируется (pinned)'), ('VIOLATIONS', 'нет отказа при чтении из сети')):
        if need not in src:
            fails.append(f'дампер: {why}')
    if logical_of is not None:
        for u in KNOWN_URLS:
            if logical_of(u) is None:
                fails.append(f'render_input.logical_of не разбирает известный адрес дампера {u}')
    return fails


def check(root: str = ROOT_DEFAULT) -> list:
    p = os.path.join(root, DUMPER)
    try:
        src = open(p, encoding='utf-8').read()
    except OSError:
        return [f'нет {DUMPER}']
    sys.path.insert(0, os.path.join(root, 'tools', 'scout'))
    try:
        import render_input as RI
        lo = RI.logical_of
    except Exception as e:  # noqa: BLE001
        return [f'render_input не импортируется: {e!r}']
    return check_source(src, lo)


def _selftest() -> int:
    bad = 0

    def ok(c, name):
        nonlocal bad
        print(('ok   ' if c else 'FAIL ') + 'render_inputs: ' + name)
        bad += 0 if c else 1
    good = ('const sendLocal = (f) => 1;\nconst VIOLATIONS = []; let HERMETIC = false;\n'
            + '\n'.join(f"  const m{i} = u.match({r}); if (m{i}) {{ sendLocal(f); return; }}" for i, r in enumerate(KNOWN_ROUTES))
            + "\n  fs.createReadStream(path.join(bundleDir, 'entry.js')).pipe(res);\n  noteRead('pinned:x', 'pinned', 'a'); fs.writeFileSync('reads.json', 'x');\n")
    ok(check_source(good) == [], 'исходник по образцу — чисто')
    ok(any('новая дорога' in f for f in check_source(good + "  const z = u.match(/^\\/secret\\/(.*)$/);\n")), 'новая дорога чтения — красный')
    ok(any('мимо sendLocal' in f for f in check_source(good + "  if (x) { fs.createReadStream(file).pipe(res); return; }\n")), 'отдача файла мимо sendLocal — красный')
    ok(any('герметичного' in f for f in check_source(good.replace('HERMETIC', 'H'))), 'нет герметичного режима — красный')
    ok(any('reads.json' in f for f in check_source(good.replace('reads.json', 'r.json'))), 'не пишется reads.json — красный')
    ok(any('пропала' in f for f in check_source(good.replace(KNOWN_ROUTES[0], '/x/'))), 'известная дорога пропала — красный')
    ok(any('не разбирает' in f for f in check_source(good, lambda u: None)), 'адрес не разбирается правилами входа — красный')
    real = check(ROOT_DEFAULT)
    for f in real:
        print('   ', f)
    ok(real == [], 'настоящий дампер проходит сторож')
    return bad


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(1 if _selftest() else 0)
    fails = check(sys.argv[sys.argv.index('--root') + 1] if '--root' in sys.argv else ROOT_DEFAULT)
    for f in fails:
        print('FAIL ' + f)
    print(f'сторож чтений входа рендера: нарушений {len(fails)}')
    sys.exit(1 if fails else 0)
