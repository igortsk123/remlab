"""Правки путей в копиях файлов снимка v2 (решение директора ❓13, 28.11): всё, что исполняется, берётся ИЗ СНИМКА, запасного пути наружу нет.
Общий для сборщика (snimok_iz_repo.py) и проверки (paket_zhivoe.py): сборщик применяет правки, проверка применяет те же правки к настоящему источнику
и сравнивает побайтно. Правка — (что заменить, на что, сколько раз должно встретиться); не встретилось ровно столько раз — ОШИБКА (код источника изменился —
снимок не собирается/не проходит проверку). «{S}» — абсолютный путь папки снимка. Только пути: логика кода не меняется. Исходные файлы не трогаются."""
import os


class PravkaError(Exception):
    pass


PRAVKI = {
    # --- раннер экзамена (копия t176/ekz/run_sb100.agent.py): всё из снимка; «вне снимка» в шапке хеширует файлы снимка
    'run_sb100.agent.py': [
        ("NC = W + '/nc-models'\n", "NC = '{S}/nc-models'\n", 1),
        ("UST = W + '/ustroystvo'\n", "UST = '{S}'    # снимок v2: сторож/правила/run_sb100 — из снимка, не из ustroystvo\n", 1),
        ("PW = os.path.expanduser('~/remlab-logs/planwalk-src/repo')", "PW = '{S}/planwalk-src/repo'", 1),
        ("open(os.path.expanduser('~/remlab-logs/planwalk-src/repo/docs/PROMPT.md'), encoding='utf-8')", "open('{S}/planwalk-src/repo/docs/PROMPT.md', encoding='utf-8')", 1),
        ("NC + '/vetka_a_eval.py', NC + '/vetka_a_run.py', NC + '/ru_eval.py'", "UST + '/vetka_a_eval.py', UST + '/vetka_a_run.py', UST + '/ru_eval.py'", 1),
        ("default=NC + '/vetka-a'", "default=W + '/nc-models/vetka-a'", 1),          # данные сухого прогона — живые, не из снимка
    ],
    # --- nc-models (4 модуля цепочки + fp_cmp, которого просит nc_eval): sys.path на снимок
    'nc-models/vetka_a_12d.py': [("sys.path.insert(0, N)\n", "sys.path.insert(0, '{S}/nc-models')\n", 1)],
    'nc-models/vetka_a_12.py': [
        ("sys.path.insert(0, N)\n", "sys.path.insert(0, '{S}/nc-models')\n", 2),
        ("PW = os.path.expanduser('~/remlab-logs/planwalk-src/repo')", "PW = '{S}/planwalk-src/repo'", 1),
        ("SK = os.path.expanduser('~/remlab-logs/planwalk-src/skill-2dp')", "SK = '{S}/planwalk-src/skill-2dp'", 1),
    ],
    'nc-models/fp_cmp.py': [("sys.path.insert(0, '/home/pakar/igor/remlab/tools/floorplan')", "sys.path.insert(0, '{S}/tools/floorplan')", 1)],
    'nc-models/nc_eval.py': [
        ("sys.path.insert(0, '/home/pakar/igor/remlab/tools/floorplan')", "sys.path.insert(0, '{S}/tools/floorplan')", 1),
        ("sys.path.insert(0, '/home/pakar/remlab-logs/etazhi-walls')", "sys.path.insert(0, '{S}/nc-models')", 1),
    ],
    # --- файлы корня снимка (2234 / репо): импорты nc-models и scout — из снимка; запасных путей наружу нет
    'ru_eval.py': [("sys.path.insert(0, os.path.expanduser('~/remlab-logs/etazhi-walls/nc-models'))", "sys.path.insert(0, '{S}/nc-models')", 1),
                   ("sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'ops'))", "sys.path.append('{S}/tools/ops')      # карточка прогона (П1.161): run_card/run_manifest — из снимка", 1)],
    'vetka_a_eval.py': [
        ("sys.path.insert(0, os.path.expanduser('~/remlab-logs/etazhi-walls/nc-models'))", "sys.path.insert(0, '{S}/nc-models')", 1),
        ("PW = os.path.expanduser('~/remlab-logs/planwalk-src/repo')", "PW = '{S}/planwalk-src/repo'", 1),
        ("SK = os.path.expanduser('~/remlab-logs/planwalk-src/skill-2dp')", "SK = '{S}/planwalk-src/skill-2dp'", 1),
    ],
    'vetka_a_run.py': [
        ("sys.path.insert(0, os.path.expanduser('~/igor/remlab/tools/scout'))", "sys.path.insert(0, '{S}/tools/scout')", 1),
        ("PROMPT_P = os.path.expanduser('~/remlab-logs/planwalk-src/repo/docs/PROMPT.md')", "PROMPT_P = '{S}/planwalk-src/repo/docs/PROMPT.md'", 1),
    ],
    # --- run_sb100.py (из 2105): те же правки, что у копии раннера t176
    'run_sb100.py': [
        ("NC = W + '/nc-models'\n", "NC = '{S}/nc-models'\n", 1),
        ("UST = W + '/ustroystvo'\n", "UST = '{S}'    # снимок v2: сторож/правила/run_sb100 — из снимка, не из ustroystvo\n", 1),
        ("PW = os.path.expanduser('~/remlab-logs/planwalk-src/repo')", "PW = '{S}/planwalk-src/repo'", 1),
        ("open(os.path.expanduser('~/remlab-logs/planwalk-src/repo/docs/PROMPT.md'), encoding='utf-8')", "open('{S}/planwalk-src/repo/docs/PROMPT.md', encoding='utf-8')", 1),
        ("NC + '/vetka_a_eval.py', NC + '/vetka_a_run.py', NC + '/ru_eval.py'", "UST + '/vetka_a_eval.py', UST + '/vetka_a_run.py', UST + '/ru_eval.py'", 1),
        ("default=NC + '/vetka-a'", "default=W + '/nc-models/vetka-a'", 1),
    ],
    # --- резерв 74 (rab-9, 28.11): флажок площади — справка «Пл» (исход не меняет): включён в копии правил корня снимка; модуль area_flag — tools/floorplan/area_flag.py ВНУТРИ снимка
    #     (в репо module_dir ".." — «рядом с tools/floorplan/etazhi»; в плоском снимке сторож лежит в корне). Числа границ те же (сверяет сам сторож: json ↔ модуль).
    'storozh_rules.json': [('    "enabled": false,\n    "module_dir": "..",\n', '    "enabled": true,\n    "module_dir": "tools/floorplan",\n', 1)],
    'storozh.py': [
        ("NC = os.path.expanduser('~/remlab-logs/etazhi-walls/nc-models')\n", "NC = '{S}/nc-models'\n", 1),
        ("os.environ.get('VORONKA_DIR') or os.path.expanduser('~/remlab-logs/etazhi-walls/voronka')", "os.environ.get('VORONKA_DIR') or '{S}'", 1),
        ("sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'ops'))", "sys.path.append('{S}/tools/ops')      # карточка прогона (П1.161): run_card/run_manifest — из снимка", 1),
    ],
    'overlay_status.py': [("        return '/home/pakar/igor/remlab/tools/floorplan'\n", "        return near      # снимок v2: запасного пути наружу нет — нет floorplan/ рядом → input_step не найден → отказ\n", 1)],
    'vetka_fit.py': [("os.path.expanduser('~/remlab-logs/t98-21-wt/tools/floorplan')", "'{S}/tools/floorplan'", 1)],
}


def apply(rel, text, snap):
    """Применить правки файла rel к тексту; нет файла в таблице — текст как есть. Не нашлось нужное число вхождений — PravkaError."""
    for old, new, n in PRAVKI.get(rel, []):
        if text.count(old) != n:
            raise PravkaError('%s: «%s…» встретилось %d раз, ждали %d' % (rel, old[:50].replace('\n', ' '), text.count(old), n))
        text = text.replace(old, new.replace('{S}', snap))
    return text


def externals(home=None):
    """Внешние файлы, копируемые в снимок: [(абсолютный путь источника, путь в снимке)]. skill-2dp — всё дерево."""
    home = home or os.path.expanduser('~')
    W = home + '/remlab-logs/etazhi-walls'
    out = [(W + '/nc-models/' + n, 'nc-models/' + n) for n in ('vetka_a_12d.py', 'vetka_a_12.py', 'nc_eval.py', 'vetka_a_cmp_bd.py')]
    out.append((W + '/fp_cmp.py', 'nc-models/fp_cmp.py'))
    out.append((home + '/remlab-logs/t176/ekz/run_sb100.agent.py', 'run_sb100.agent.py'))
    pw = home + '/remlab-logs/planwalk-src'
    out.append((pw + '/repo/docs/PROMPT.md', 'planwalk-src/repo/docs/PROMPT.md'))
    out.append((pw + '/repo/package.json', 'planwalk-src/repo/package.json'))      # "type": "module" — нужен для .mjs/.js из src
    for sub in ('tools', 'src'):                                                   # validate.mjs (vetka_a_eval) + src/core/validate.js, который он импортирует
        for dp, dn, fn in os.walk(pw + '/repo/' + sub):
            dn[:] = sorted(d for d in dn if d not in ('__pycache__', 'node_modules', '.git'))
            for f in sorted(fn):
                full = os.path.join(dp, f)
                out.append((full, 'planwalk-src/repo/' + os.path.relpath(full, pw + '/repo')))
    sk = pw + '/skill-2dp'
    for dp, dn, fn in os.walk(sk):
        dn[:] = sorted(d for d in dn if d not in ('__pycache__', 'node_modules', '.git'))
        for f in sorted(fn):
            full = os.path.join(dp, f)
            out.append((full, 'planwalk-src/skill-2dp/' + os.path.relpath(full, sk)))
    return out
