"""Общий кэш листов регресса (T-20261111-18): ключ меняется от любой правки входов разбора, хит — та же папка листа байт в байт."""
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import regress as rg  # noqa: E402
import regress_cache as RC  # noqa: E402

# Заглушка `pipeline.py job`: лист → sheet.png, ответ VLM из <vlm-root>/<sha листа>[:32]/raw-T-labels.txt (нет — source_gone, rc 3),
# объявление и FP_X — в результат; каждый настоящий разбор — строка в RUNS (так тест считает, сколько разобрано).
STUB = r'''
import hashlib, json, os, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scout'))
import helper_mod


class TrialError(Exception):
    def __init__(self, code, detail=''):
        self.code, self.detail = code, detail


def run(image, lt, wd, *, vlm_dir, slot=False, cache_only=True):
    """Как pipeline.run (путь regress.RUN_DIRECT): ответ VLM — из vlm_dir."""
    Path(wd).mkdir(parents=True, exist_ok=True)
    with open(os.environ['RUNS'], 'a') as f:
        f.write('direct\n')
    v = Path(vlm_dir) / 'raw-T-labels.txt'
    if not v.exists():
        raise TrialError('source_gone')
    return {'sheet': Path(image).read_text(), 'vlm': v.read_text(), 'listing': lt, 'timings': {'walls': time.time()}}


if __name__ == '__main__':
    a, i = {}, 2
    while i < len(sys.argv):
        if sys.argv[i] in ('--cache-only', '--no-slot'):
            i += 1
            continue
        a[sys.argv[i]] = sys.argv[i + 1]
        i += 2
    wd = Path(a['--workdir']); wd.mkdir(parents=True, exist_ok=True)
    with open(os.environ['RUNS'], 'a') as f:
        f.write(a['--job-id'] + '\n')
    src = Path(a['--input']).read_bytes()
    if src.startswith(b'CRASH'):
        sys.exit(1)
    (wd / 'sheet.png').write_bytes(src)
    v = Path(a['--vlm-root']) / hashlib.sha256(src).hexdigest()[:32] / 'raw-T-labels.txt'
    if not v.exists():
        (wd / 'error.json').write_text(json.dumps({'code': 'source_gone'}))
        sys.exit(3)
    lst = Path(a['--listing-file']).read_text() if '--listing-file' in a else ''
    (wd / 'bench').mkdir()
    (wd / 'bench' / 'overlay-T-0.png').write_bytes(b'png' + src)
    (wd / 'result.json').write_text(json.dumps({'sheet': src.decode(), 'vlm': v.read_text(), 'listing': lst,
                                                'x': os.environ.get('FP_X'), 'k': helper_mod.K, 'timings': {'walls': time.time()}}))
'''


def _tree(tmp: Path) -> tuple[Path, Path]:
    code = tmp / 'code'
    (code / 'tools' / 'floorplan').mkdir(parents=True)
    (code / 'tools' / 'scout').mkdir(parents=True)
    (code / 'tools' / 'floorplan' / 'pipeline.py').write_text(STUB)
    (code / 'tools' / 'floorplan' / 'bench.py').write_text('x = 1\n')
    (code / 'tools' / 'scout' / 'helper_mod.py').write_text('K = 1\n')
    (code / 'tools' / 'scout' / 'unrelated.py').write_text('Z = 1\n')
    data = tmp / 'data'
    data.mkdir()
    for n in ('a', 'b'):
        (data / f'{n}.png').write_text(f'sheet-{n}')
        vd = tmp / 'vlm' / RC._sha(f'sheet-{n}'.encode())[:32]
        vd.mkdir(parents=True)
        (vd / 'raw-T-labels.txt').write_text(f'vlm-{n}')
    (data / 'c.png').write_text('sheet-c')                         # без ответа VLM → source_gone (rc 3)
    (data / 'l.txt').write_text('объявление 1')
    cases = tmp / 'cases.tsv'
    cases.write_text(f"a\t{data / 'a.png'}\t{data / 'l.txt'}\nb\t{data / 'b.png'}\t-\nc\t{data / 'c.png'}\t-\n")
    return code, cases


class Env:
    def __init__(self, tmp, monkeypatch):
        self.tmp = tmp
        self.code, self.cases = _tree(tmp)
        self.cache = tmp / 'cache'
        self.runs = tmp / 'runs.txt'
        monkeypatch.setenv('RUNS', str(self.runs))
        monkeypatch.setattr(rg, 'VLM_CACHE', tmp / 'vlm')
        self.n = 0

    def run(self, *extra, code=None):
        self.n += 1
        out = self.tmp / f'out{self.n}'
        before = self.runs.read_text().count('\n') if self.runs.exists() else 0
        rc = rg.main(['run', str(code or self.code), str(out), '--no-trial', '--cases', str(self.cases), '-j', '2',
                      '--cache-dir', str(self.cache), *extra])
        parsed = (self.runs.read_text().count('\n') if self.runs.exists() else 0) - before
        man = json.loads((out / 'manifest.json').read_text())
        return rc, out, parsed, man


def _files(d: Path) -> dict:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob('*')) if p.is_file() and p.name != 'manifest.json'
            and not p.name.endswith('.log')}


def test_warm_run_restores_same_bytes_and_counts(tmp_path, monkeypatch, capsys):
    e = Env(tmp_path, monkeypatch)
    rc, o1, parsed, man = e.run()
    assert rc == 0 and parsed == 3 and man['cache']['hits'] == 0 and man['cache']['parsed'] == 3
    assert json.loads((o1 / 'c' / 'error.json').read_text())['code'] == 'source_gone'      # rc 3 — тоже в кэш
    rc, o2, parsed, man = e.run()
    assert rc == 0 and parsed == 0 and man['cache']['hits'] == 3
    assert _files(o1) == _files(o2)                                     # папки листов байт в байт, с bench/
    assert (o2 / 'a.log').read_text().startswith('regress-cache: из кэша')
    assert 'кэш: из кэша 3, разобрано 0' in capsys.readouterr().out


def test_same_code_in_other_folder_hits(tmp_path, monkeypatch):
    """Снимок main и рабочая копия, не трогавшая код разбора, — один ключ (путь кода в ключ не входит)."""
    e = Env(tmp_path, monkeypatch)
    e.run()
    import shutil
    other = tmp_path / 'copy'
    shutil.copytree(e.code, other)
    (other / 'tools' / 'scout' / 'unrelated.py').write_text('Z = 2\n')   # чужой разбору модуль scout
    _, _, parsed, man = e.run(code=other)
    assert parsed == 0 and man['cache']['hits'] == 3


def test_any_parse_input_change_misses(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    e.run()
    (e.code / 'tools' / 'floorplan' / 'bench.py').write_text('x = 1  # пробел\n')     # любой файл floorplan
    assert e.run()[2] == 3
    (e.code / 'tools' / 'scout' / 'helper_mod.py').write_text('K = 1\n\n')            # импортируемый из scout
    assert e.run()[2] == 3
    assert e.run()[2] == 0
    assert e.run('--env', 'FP_X=1')[2] == 3                                           # переключатель --env
    assert e.run('--env', 'FP_X=1')[2] == 0
    (tmp_path / 'data' / 'l.txt').write_text('объявление 2')                         # объявление
    assert e.run()[2] == 1
    vd = tmp_path / 'vlm' / RC._sha(b'sheet-b')[:32]
    (vd / 'labels4').mkdir()
    (vd / 'labels4' / 'raw-T-labels4.txt').write_text('новый вид ответа')            # ответ VLM появился/сменился
    assert e.run()[2] == 1
    vc = tmp_path / 'vlm' / RC._sha(b'sheet-c')[:32]
    vc.mkdir()
    (vc / 'raw-T-labels.txt').write_text('vlm-c')                                     # был source_gone, ответ появился
    rc, out, parsed, _ = e.run()
    assert parsed == 1 and json.loads((out / 'c' / 'result.json').read_text())['vlm'] == 'vlm-c'
    (tmp_path / 'data' / 'a.png').write_text('sheet-a2')                              # сам лист
    assert e.run()[2] == 1


def test_cases_vlm_dir_same_sheet_two_dirs_not_mixed(tmp_path, monkeypatch):
    """Строка `--cases` с папкой VLM (путь RUN_DIRECT): один лист, две папки с разными ответами — два разных результата;
    правка ответа в папке — новый разбор."""
    e = Env(tmp_path, monkeypatch)
    for n in ('v1', 'v2'):
        (tmp_path / n).mkdir()
        (tmp_path / n / 'raw-T-labels.txt').write_text(f'ответ {n}')
    sheet = tmp_path / 'data' / 'a.png'
    e.cases.write_text(f"d1\t{sheet}\t-\t{tmp_path / 'v1'}\nd2\t{sheet}\t-\t{tmp_path / 'v2'}\n")
    _, o1, parsed, _ = e.run()
    assert parsed == 2
    _, o2, parsed, _ = e.run()
    assert parsed == 0 and _files(o1) == _files(o2)
    assert json.loads((o2 / 'd2' / 'result.json').read_text())['vlm'] == 'ответ v2'
    (tmp_path / 'v2' / 'raw-T-labels.txt').write_text('ответ v2 новый')
    _, o3, parsed, _ = e.run()
    assert parsed == 1 and json.loads((o3 / 'd2' / 'result.json').read_text())['vlm'] == 'ответ v2 новый'


def test_no_cache_and_side_output_env_bypass(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    rc, _, parsed, man = e.run('--no-cache')
    assert parsed == 3 and man['cache'] == {'off': 'выключен (--no-cache)', 'hits': 0, 'parsed': 3} and not e.cache.exists()
    e.run()
    assert e.run('--no-cache')[2] == 3                                               # тёплый кэш не читается
    _, _, parsed, man = e.run('--env', f'FP_DUMP={tmp_path / "dump"}')
    assert parsed == 3 and man['cache']['off'] == '--env FP_DUMP'


def test_crash_is_not_cached(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    (tmp_path / 'data' / 'b.png').write_text('CRASH')
    e.run()
    assert e.run()[2] == 1                                                            # rc 1 — заново каждый раз


def test_concurrent_put_same_key_one_entry(tmp_path):
    st = RC.Store(tmp_path / 'cache')
    wd = tmp_path / 'wd'
    (wd / 'bench').mkdir(parents=True)
    (wd / 'result.json').write_text('{"a":1}')
    log = tmp_path / 'wd.log'
    log.write_text('журнал')
    res = []
    ts = [threading.Thread(target=lambda: res.append(st.put('k1' * 32, [], wd, log, {'rc': 0}))) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(set(res)) == 1 and res[0]
    assert len(list((tmp_path / 'cache' / 'obj').rglob('entry.json'))) == 1
    assert not list((tmp_path / 'cache' / 'tmp').iterdir())                           # временные копии проигравших убраны
    hit = st.get('k1' * 32)
    assert hit and (hit[1] / 'wd' / 'result.json').read_text() == '{"a":1}'


def test_real_code_fingerprint_covers_loaded_modules():
    """Что реально грузит разбор листа (замер T-18: `pipeline.py job` → sys.modules) — всё в отпечатке; шлюз VLM и его
    зависимости из scout — тоже; страница тура (trial_bundle) и конвейер мебели — нет (не разбор)."""
    fs = RC.code_files(ROOT)
    for f in ('bench', 'fpcore', 'listing', 'openroom', 'partition', 'repair', 'vlm', 'pipeline', 'redraw'):
        assert f'tools/floorplan/{f}.py' in fs
    for f in ('tools/ops/heavy_slot.py', 'tools/scout/llm_gateway.py', 'tools/scout/env_keys.py'):
        assert fs.get(f) is not None
    assert 'tools/scout/trial_bundle.py' not in fs and 'tools/scout/pipeline.py' not in fs


def test_bypass_reason():
    assert RC.bypass_reason({'FP_ARC_PURE': '0'}) is None
    assert RC.bypass_reason({'FP_REDRAW': '1'}) == '--env FP_REDRAW'
    assert RC.bypass_reason({'FP_FOO': '/tmp/x'}) == '--env FP_FOO=<путь>'
    assert os.path.basename(str(RC.CACHE_DIR)) == 'regress-cache'
