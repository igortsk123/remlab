"""СТОРОЖ ЧТЕНИЙ ВХОДА РЕНДЕРА (T-20261118-04/16/1, план `render-key-01` п.3; подключён в `conveyor_check.py`).

Ключ кадра комнаты (`tools/scout/render_input.py`) честен, пока ВСЁ, что страница-дампер читает, лежит в нём. Дампер (`demo_scene_dump.mjs`) пишет `dump/reads.json`, исполнитель
сверяет его с входом комнаты ПЕРЕД рендером (`render_exec.check_dump_reads`); здесь — предохранитель на САМ дампер, чтобы новая дорога чтения не прошла незамеченной в коммите:
  • каждая отдача файла страницы идёт через `sendLocal` (он пишет чтение), голых `createReadStream(...).pipe(res)` нет (кроме самой страницы и `entry.js`);
  • каждая дорога по адресу (`u.match(/…/)`) — из списка известных; новая дорога без правила в `render_input._URL_RULES` — красный;
  • известные адреса дампера разбираются `render_input.logical_of` (и с запросом `?v=`);
  • в сетевой ветке есть герметичный отказ (`HERMETIC`), пишется `reads.json`, таблица runtime-мешей — зафиксированная (`pinned`) в герметичном режиме.
Python-выгрузчик (T-20261118-04/17/1): `export_scene.main_export` включает `cycles_probe/read_guard.py` (хук аудита: чтения пишутся в `reads-py.json`, сеть запрещена), а каждое место, где
`draft_render.py` тянет файл (фото товара, фактура пола, меш, разворот), имеет герметичную ветку `HERMETIC`; исполнитель зовёт `check_export_reads`. Здесь это проверяется по исходникам.
    python3 tools/ops/render_inputs.py            # проверка
    python3 tools/ops/render_inputs.py --selftest
"""
import json
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


PY_NET_FUNCS = ('photo', '_scene3d_orient', '_scene3d_glb', '_floor_image')       # функции `draft_render.py`, что тянут файл с диска-кэша или из сети: у каждой герметичная ветка


def check_python_source(guard: str, export: str, draft: str, execs: str) -> list:
    fails = []
    for need, why in (('addaudithook', 'нет хука аудита'), ('socket.connect', 'не ловится сеть (connect)'), ('socket.getaddrinfo', 'не ловится сеть (getaddrinfo)'),
                      ('urllib.Request', 'не ловится urllib'), ('reads-py.json', 'не пишется reads-py.json'), ('def begin', 'нет begin'), ('def end', 'нет end')):
        if need not in guard:
            fails.append(f'read_guard.py: {why}')
    if not (re.search(r'RG\.begin\(', export) and re.search(r'RG\.end\(', export) and 'hermetic' in export):
        fails.append('export_scene.py: main_export не включает сторож чтений (read_guard.begin/end по data[hermetic])')
    for fn in PY_NET_FUNCS:
        m = re.search(r'^def %s\(.*?(?=^def |^class |^[A-Z_]+ *=|\Z)' % fn, draft, re.S | re.M)
        if not m:
            fails.append(f'draft_render.py: нет функции {fn} (сверь PY_NET_FUNCS в tools/ops/render_inputs.py)')
        elif 'HERMETIC' not in m.group(0):
            fails.append(f'draft_render.py: у {fn} нет герметичной ветки HERMETIC — в v2 она читала бы кэш/сеть мимо входа комнаты')
    if 'check_export_reads(job' not in execs or 'def check_export_reads' not in execs:
        fails.append('render_exec.py: исполнитель не сверяет reads-py.json (check_export_reads)')
    return fails


# ——— Blender-этап (T-20261118-04/18/1): ВСЕ чтения файлов `render_cycles.py` и того, что он импортирует. Строка кода с чтением обязана содержать одну из подстрок ниже (иначе — новое чтение без решения).
# (подстрока, что читает → путь, чем покрыто)
BLENDER_READS = {
    'tools/scout/cycles_probe/render_cycles.py': (
        ("os.path.join(a.scene_dir, 'scene.json')", 'сцена мебели → <job>/scene/scene.json', 'выгрузчик (сторож reads-py.json, герметичен)'),
        ("images.load(exr)", 'собственный выход Blender (.lin.exr)', 'не вход: пишется самим кадром'),
        ("images.load(os.path.join(a.scene_dir, tex)", 'текстуры мебели/ковров → <job>/scene/tex/*', 'выгрузчик (сторож reads-py.json)'),
        ("images.load(os.path.join(a.scene_dir, mr)", 'карты шероховатости меша → <job>/scene/tex/*', 'выгрузчик'),
        ("images.load(os.path.join(a.scene_dir, bdv['tex'])", 'текстуры вида/окна → <job>/scene/tex/*', 'выгрузчик'),
        ("images.load(os.path.join(a.scene_dir, r['tex'])", 'текстуры ковров → <job>/scene/tex/*', 'выгрузчик'),
        ("np.load(os.path.join(a.scene_dir, o['file']))", 'геометрия предметов → <job>/scene/*.npz', 'выгрузчик'),
        ("json.load(open(a.export", 'описание отделки → <job>/dump/scene-export.json', 'дампер (reads.json) + программа'),
        ("images.load(os.path.join(PUB, maps[key]", 'карты стен/пола/акцента → public/flat3d/materials/<карта>', 'актив комнаты material:<файл> + `check_blender_inputs` (maps ⊆ входа, тот же sha256)'),
        ("json.load(open(a.demo_nodes", 'узлы декора → <job>/dump/demo_nodes_uuids.json', 'дампер'),
        ("'scene_info.json'", 'снимок позиций → <job>/dump/scene_info.json', 'дампер'),
        ("import wall_art", 'правило картин: tools/scout/wall_art.py + data/flat3d/wall-art.json', 'renderer_digest (замыкание импортов, data/flat3d/*.json)'),
        ("import frame_qa", 'сторож кадров: cycles_probe/frame_qa.py + data/flat3d/frame-qa-rules.json, textile.json', 'renderer_digest'),
        ("images.load(fabric", 'флаг --fabric (в пресете нет)', 'пресет: путей-флагов нет (`PATH_FLAGS`, проверка ниже)'),
        ("json.load(open(a.live_cam", 'флаг --live-cam (в пресете нет)', 'пресет: путей-флагов нет'),
        ("images.load(a.hdri)", 'флаг --hdri (в пресете нет; небо — процедурное Nishita)', 'пресет: путей-флагов нет'),
    ),
    'tools/scout/cycles_probe/frame_qa.py': (
        ('open(path, encoding="utf-8")', 'JSON по пути вызова: jload(...) — dump/scene_info, scene.json, scene-export, demo_nodes_uuids, textile.json', 'дамп и сцена под сторожами; textile.json — renderer_digest'),
        ('open(path, "rb")', 'GLB по пути вызова (_glb) — dump/demo_nodes.glb; sha256 кадра — свой выход', 'дампер'),
        ('im["uri"]', 'картинки внутри GLB → <job>/dump/img/*', 'дампер (ximg, манифест)'),
        ('open(p, encoding="utf-8")', 'dump_keys.json (дамп) или render-preset.json (пресет)', 'дампер / preset_digest'),
        ('open(rp, encoding="utf-8")', 'отчёт `<кадр>.qa.json` — свой выход', 'не вход'),
        ('json.load(open(a.demo_nodes', 'узлы декора → dump/demo_nodes_uuids.json', 'дампер'),
        ('images.load(mp', 'маска кадра — свой выход', 'не вход'),
        ('images.load(fr["out"]', 'кадр — свой выход', 'не вход'),
        ('open(out + ".qa.json", "w"', 'запись отчёта (не чтение)', 'не вход'),
        ('"scene_info.json")', 'снимок позиций → dump/scene_info.json', 'дампер'),
        ('json.load(f)', 'разбор уже открытого файла (парное к open выше)', 'см. open выше'),
        ('import wall_art as WA', 'правило картин: wall_art.py + data/flat3d/wall-art.json', 'renderer_digest'),
    ),
    'tools/scout/wall_art.py': (
        ('json.load(f)', 'разбор уже открытого файла (парное к open выше)', 'см. open выше'),
        ("open(path, encoding='utf-8')", 'data/flat3d/wall-art.json (RULES_PATH)', 'renderer_digest'),
        ('Image.open(src)', 'исходник картины → каталог сцены/дампа (по пути вызова)', 'выгрузчик/дампер'),
        ('Image.open(buf)', 'память (буфер)', 'не файл'),
    ),
}
READ_PRIMS = re.compile(r'\bopen\(|images\.load\(|np\.load\(|Image\.open\(|json\.load\(|^\s*import (wall_art|frame_qa)\b|\bimport (wall_art|frame_qa) as')
# пути-флаги render_cycles.py: файл по флагу в пресете не хешируется — в `flags` пресета их быть не должно
PATH_FLAGS = ('--hdri', '--fabric', '--orig', '--plant-swap', '--live-cam', '--also-png', '--demo-glb', '--demo-nodes', '--export', '--public', '--scene-dir')
# файлы программы, которые Blender-этап обязан найти в renderer_digest
BLENDER_PROGRAM = ('tools/scout/cycles_probe/render_cycles.py', 'tools/scout/cycles_probe/frame_qa.py', 'tools/scout/wall_art.py', 'data/flat3d/wall-art.json',
                   'data/flat3d/frame-qa-rules.json', 'data/flat3d/textile.json')


def check_blender_source(sources: dict, flags: list, program: dict) -> list:
    """sources {путь: текст}; flags — `flags` пресета; program — `render_input.program_files()`."""
    fails = []
    for rel, rows in BLENDER_READS.items():
        text = sources.get(rel)
        if text is None:
            fails.append(f'Blender-этап: нет файла {rel}')
            continue
        for i, ln in enumerate(text.split('\n'), 1):
            st = ln.strip()
            if st.startswith('#') or 'add_argument' in st or not READ_PRIMS.search(ln):
                continue
            if not any(sn in ln for sn, _, _ in rows):
                fails.append(f'Blender-этап: новое чтение {rel}:{i} — «{st[:90]}»: внеси в BLENDER_READS (tools/ops/render_inputs.py) и во вход комнаты / renderer_digest')
        for sn, what, _ in rows:
            if sn not in text:
                fails.append(f'Blender-этап: чтение «{what}» пропало или переписано в {rel} — сверь BLENDER_READS')
    bad = [f for f in flags if f in PATH_FLAGS]
    if bad:
        fails.append(f'Blender-этап: в flags пресета флаги с путями к файлам {bad} — файл не входит в ключ')
    prog = set(program.get('py') or []) | set(program.get('js') or []) | set(program.get('rules') or [])
    for need in BLENDER_PROGRAM:
        if need not in prog:
            fails.append(f'Blender-этап: файл программы {need} не входит в renderer_digest')
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
    fails = check_source(src, lo)
    try:
        rd = lambda rel: open(os.path.join(root, rel), encoding='utf-8').read()  # noqa: E731
        fails += check_python_source(rd('tools/scout/cycles_probe/read_guard.py'), rd('tools/scout/cycles_probe/export_scene.py'), rd('tools/scout/draft_render.py'),
                                     rd('tools/scout/render_exec.py'))
    except OSError as e:
        fails.append(f'сторож выгрузчика: не прочитан {e.filename}')
    try:
        srcs = {rel: open(os.path.join(root, rel), encoding='utf-8').read() for rel in BLENDER_READS}
        flags = json.load(open(os.path.join(root, 'tools/scout/cycles_probe/render-preset.json'), encoding='utf-8')).get('flags') or []
        os.environ.setdefault('RENDER_INPUT_REPO', root)
        fails += check_blender_source(srcs, flags, RI.program_files())
    except (OSError, ValueError) as e:
        fails.append(f'сторож Blender-этапа: не прочитан файл ({e})')
    return fails


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
    g = "addaudithook socket.connect socket.getaddrinfo urllib.Request reads-py.json def begin def end"
    ex = "import read_guard as RG\non = RG.begin(out, D)  # hermetic\nRG.end(out)\n"
    dr = ''.join(f"def {f}(x):\n    if HERMETIC['on']:\n        return 1\n\n\n" for f in PY_NET_FUNCS)
    xe = "def check_export_reads(job, i):\n    pass\ncheck_export_reads(job, fi)\n"
    ok(check_python_source(g, ex, dr, xe) == [], 'Python-выгрузчик по образцу — чисто')
    ok(any('герметичной' in f for f in check_python_source(g, ex, dr.replace("HERMETIC['on']", "True", 1), xe)), 'нет герметичной ветки у функции чтения — красный')
    ok(any('сторож чтений' in f for f in check_python_source(g, "x = 1", dr, xe)), 'main_export без сторожа — красный')
    ok(any('хука' in f for f in check_python_source(g.replace('addaudithook', ''), ex, dr, xe)), 'нет хука аудита — красный')
    ok(any('check_export_reads' in f for f in check_python_source(g, ex, dr, 'x = 1')), 'исполнитель не сверяет reads-py.json — красный')
    src_ok = {rel: '\n'.join(sn for sn, _, _ in rows) for rel, rows in BLENDER_READS.items()}
    prog_ok = {'py': ['tools/scout/cycles_probe/render_cycles.py', 'tools/scout/cycles_probe/frame_qa.py', 'tools/scout/wall_art.py'],
               'js': ['data/flat3d/wall-art.json', 'data/flat3d/frame-qa-rules.json', 'data/flat3d/textile.json'], 'rules': []}
    ok(check_blender_source(src_ok, ['--view', '2'], prog_ok) == [], 'Blender-этап по образцу — чисто')
    rc = 'tools/scout/cycles_probe/render_cycles.py'
    ok(any('новое чтение' in f for f in check_blender_source({**src_ok, rc: src_ok[rc] + "\n    z = open('/etc/x').read()\n"}, [], prog_ok)), 'новое чтение в render_cycles — красный')
    ok(any('новое чтение' in f for f in check_blender_source({**src_ok, rc: src_ok[rc] + "\n    im = bpy.data.images.load(os.path.join(PUB, 'x.webp'))\n"}, [], prog_ok)),
       'новая загрузка картинки в Blender — красный')
    ok(any('пропало' in f for f in check_blender_source({**src_ok, rc: ''}, [], prog_ok)), 'известное чтение пропало — красный')
    ok(any('флаги с путями' in f for f in check_blender_source(src_ok, ['--hdri', '/x/sky.exr'], prog_ok)), 'флаг пресета с путём к файлу — красный')
    ok(any('не входит в renderer_digest' in f for f in check_blender_source(src_ok, [], {**prog_ok, 'js': []})), 'данные Blender-этапа вне renderer_digest — красный')
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
