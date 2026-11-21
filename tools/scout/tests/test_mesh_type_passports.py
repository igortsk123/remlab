"""Паспорта типов, фаза 1 «реестр + тень» (план mesh-type-passports-01 v5, T-20261120-151/6). Без БД, без сети, без torch: `preprocess` подменяется заглушкой ВНУТРИ теста.

  python tools/scout/tests/test_mesh_type_passports.py

Что держит (буквы — из § «Автопроверки» плана):
  золото политики К1 (131) и К3 (89) — исход КАЖДОГО случая замороженной фикстуры (не счёт); цепочка: наборы ролей кода = chain_flags реестра по поведению;
  (а) сбой тени (сторож/вставка бросают, таймаут, N сбоев) → `cutout_sync.one` = 'ok', `photo_assessment` записан, FAIL_STREAK_MAX не тронут;
  (б) битый/отсутствующий реестр и нет таблицы/колонки → очередь, ключи `mesh_jobs`, экспорт без изменений, одна WARN;
  (в) `crop_box` = фактическая обрезка `trim_alpha`;  (г) поле `photo.object_xy` не меняет потребителей метрик;
  (д) `--shadow-backfill` не пишет `photo_assessment` и не трогает кэш `<sha>.png`;
  (д2) отравленные строки, `attempts` раз в ночь, карантин, продолжение после обрыва, таймаут сторожа, серия одинаковых сбоев, бюджет;
  (е) `salad/` не изменён относительно базы ветки (`git diff --stat`); таблицы случаев К1/К3 на синтетических картинках."""
import ast
import collections
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.dirname(HERE)
ROOT = os.path.abspath(os.path.join(SCOUT, '..', '..'))
sys.path.insert(0, SCOUT)
sys.path.insert(0, os.path.join(SCOUT, 'salad'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_mesh_type_passports')
import tempfile  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

FX = os.path.join(SCOUT, 'tests', 'fixtures')
BAD: list = []


def ok(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        BAD.append(msg)


# ---- заглушка preprocess (в нём torch): ASSESSOR_VERSION и `trim_alpha` — настоящий исходник, достаётся через ast (как photo_hash берёт константы)
def _stub_preprocess():
    src = open(os.path.join(SCOUT, 'salad', 'preprocess.py'), encoding='utf-8').read()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == 'trim_alpha')
    mod = types.ModuleType('preprocess')
    mod.np, mod.Image = np, Image
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'preprocess_trim_alpha', 'exec'), mod.__dict__)
    mod.ASSESSOR_VERSION = 'a-test'
    mod.mask_verdict = lambda cut: {}
    mod.defringe = lambda img, *a, **k: img
    sys.modules['preprocess'] = mod
    return mod


PRE = _stub_preprocess()
import mesh_type_passports as MTP  # noqa: E402
import cutout_guards as CG  # noqa: E402
import passport_shadow as PS  # noqa: E402
import photo_fit as PF  # noqa: E402
import cutout_sync as CS  # noqa: E402
import mesh_queue as MQ  # noqa: E402
import mesh_scheduler as MS  # noqa: E402

# БД в этом тесте ЗАКРЫТА: настоящий psql (`PS.PSQL`) заменён командой, которая всегда отказывает, — любой забытый путь к `PgStore` упадёт в fail-open,
# а не сходит в живую dev-базу (проверка Codex T-151/6: тесты не должны зависеть от того, есть ли docker). Настоящий SQL — `passport_shadow_dbtest.py`.
NO_DB = [sys.executable, '-c', 'import sys; sys.stderr.write("БД в тесте закрыта"); sys.exit(2)']
PS.PSQL = NO_DB

REG = MTP.load(force=True)
K1 = REG['types']['кровать']['cutout']['guards'][0]
K3 = REG['types']['подушка']['cutout']['guards'][0]


def use_registry(path):
    """Подставить файл реестра для боевого пути: кэш сброшен, `load` не вызываем (битый файл бросит — это ловит gate, а не тест)."""
    MTP.PATH = path
    MTP._REG = None


def quiet(fn, *a, **k):
    """→ (результат, напечатанное)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


# ------------------------------------------------------------------ золото политики
def gold():
    print('золото политики (исход каждого случая замороженной фикстуры):')
    k1 = json.load(open(os.path.join(FX, 'passport-k1.json'), encoding='utf-8'))
    k3 = json.load(open(os.path.join(FX, 'passport-k3.json'), encoding='utf-8'))
    ok(len(k1['cases']) == 131 and len(k3['cases']) == 89, f"случаев К1 {len(k1['cases'])}/131, К3 {len(k3['cases'])}/89")
    wrong = [c['id'] for c in k1['cases'] if CG.verdict('headboard_loss', c['metrics'], K1['thresholds'])[0] != c['expected']]
    ok(not wrong, 'К1: исход каждого случая равен зафиксированному' + ('' if not wrong else f': расхождения {wrong}'))
    cnt = collections.Counter(c['expected'] for c in k1['cases'])
    named = collections.Counter(c.get('named') for c in k1['cases'] if c.get('named'))
    ok(cnt == {'headboard_loss': 7, 'ambiguous': 10, 'ok': 114}, f'К1: ожидания {dict(cnt)} (7 потерь = 5 настоящих + 2 интерьерных; 10 несовмещённых; 114 ок = 112 + 2 белых на белом)')
    ok(named == {'true_loss': 5, 'interior_false_positive': 2, 'white_on_white_miss': 2}, f'К1: названные случаи {dict(named)}')
    wrong = [c['id'] for c in k3['cases'] if CG.verdict('pillow_plain', c['metrics'], K3['thresholds'])[0] != c['expected']]
    ok(not wrong, 'К3: исход каждого случая равен зафиксированному' + ('' if not wrong else f': расхождения {wrong}'))
    nd = collections.Counter(c.get('named') for c in k3['cases'] if c.get('named'))
    ok(nd == {'not_one_pillow': 6, 'weak_pattern_as_plain': 4, 'plain_as_pattern': 6}, f'К3: 16 названных расхождений с глазом {dict(nd)}')
    ok(all(c['id'].startswith(('bed-', 'pillow-')) and set(c) <= {'id', 'metrics', 'expected', 'named', 'note'} for c in k1['cases'] + k3['cases']),
       'фикстура без SKU/URL/хешей: id вида bed-NNN / pillow-NNN, только числа')
    blob = json.dumps([k1, k3], ensure_ascii=False)
    import re
    ok(not re.search(r'\d+:\d+|[0-9a-f]{16,}|https?://', blob.replace('"k1.v1"', '')), 'в фикстуре нет шаблона SKU, хеша и ссылки')


# ------------------------------------------------------------------ цепочка: наборы ролей кода = chain_flags реестра (по поведению)
def _const(path, name):
    for n in ast.parse(open(os.path.join(SCOUT, path), encoding='utf-8').read()).body:
        if isinstance(n, ast.Assign) and any(getattr(t, 'id', None) == name for t in n.targets):
            return n.value
    raise KeyError(name)


def chain_roles():
    print('цепочка вырезки: наборы ролей кода = chain_flags реестра:')
    grow = set(ast.literal_eval(_const('salad/hybrid_mask.py', 'GROW_ROLES')))
    sil = set(ast.literal_eval(_const('salad/components.py', 'SOLID_SILHOUETTE_ROLES')))
    att = set(ast.literal_eval(_const('salad/components.py', 'ATTACHED_PRUNE_ROLES')))
    body_extra = set(ast.literal_eval(_const('salad/components.py', 'SOLID_BODY_ROLES').right))   # SOLID_SILHOUETTE_ROLES | {…}
    body = sil | body_extra

    def code_flags(role):     # те же проверки, что в коде: точное `in`, первое слово, `.strip()`
        f = set()
        if role in grow:
            f.add('grow')
        if role in sil:
            f.add('solid_silhouette')
        if ((role or '').split()[0] if role else '') in att:
            f.add('attached_prune')
        if (role or '').strip() in body:
            f.add('solid_body')
        return f
    NAMED = {'ковер': 'алиас `ковёр` без «ё»: код (`role in GROW_ROLES`) его не растит — названное исключение'}
    bad = []
    for t, p in REG['types'].items():
        for name in [t] + list(p.get('aliases') or ()):
            want = set(p['cutout']['chain_flags']) if name == t else set(p['cutout']['chain_flags'])
            got = code_flags(name)
            if name in NAMED:
                got |= want & {'grow'}
            if got != want:
                bad.append((name, sorted(want), sorted(got)))
    ok(not bad, 'у каждой роли реестра (и алиаса) chain_flags = то, что делает код' + ('' if not bad else f': {bad}'))
    in_code = (grow | sil | att | body)
    uncovered = sorted(r for r in in_code if MTP.normalize(r) is None)
    ok(uncovered == ['банкетка'], f'роли из наборов кода без паспорта — только названная «банкетка» (в asset-strategies её нет): {uncovered}')
    ok(set(MTP.CHAIN_FLAGS) == {'grow', 'solid_silhouette', 'attached_prune', 'solid_body'}, 'закрытый список флагов цепочки')


# ------------------------------------------------------------------ синтетические таблицы случаев К1/К3
def synthetic():
    print('таблицы случаев на синтетических картинках:')
    import passport_measure as PM
    H, W = 300, 400

    def bed_case(head_bg=235, head=250, with_head=False, xy=True):
        src = np.full((H, W, 3), head_bg, np.uint8)
        src[60:120, 100:300] = head
        src[120:240, 80:320] = (120, 90, 60)
        top = 60 if with_head else 120
        al = np.zeros((H, W), np.uint8)
        al[top:240, 80:320] = 255
        if with_head:
            al[60:120, :100] = 0
            al[60:120, 300:] = 0
        cut = np.dstack([src[top:240, 80:320], al[top:240, 80:320]])
        return src, cut, (80, top) if xy else None
    th = K1['thresholds']

    def k1(src, cut, xy, de=None):
        m = PM.k1_measure(src, cut, xy, th['loss_de'] if de is None else de, th['register_err_max'])
        return CG.verdict('headboard_loss', m, th)[0]
    s, c, xy = bed_case()
    ok(k1(s, c, xy) == 'headboard_loss', 'К1: белое изголовье на светлом фоне потеряно — ловится при ΔE 2,5')
    ok(k1(s, c, xy, de=8.0) == 'ok', 'К1: то же при ΔE 8 — не ловится (белое на белом; названный пропуск)')
    s2, c2, xy2 = bed_case(with_head=True)
    ok(k1(s2, c2, xy2) == 'ok', 'К1: изголовье в вырезке — потери нет')
    ok(k1(s, c, None) == 'headboard_loss', 'К1: без object_xy (старая строка) — смещение находится совмещением, исход тот же')
    rng = np.random.RandomState(3)
    ok(k1(rng.randint(0, 255, (H, W, 3)).astype(np.uint8), c, None) == 'ambiguous', 'К1: несовмещённый кадр → ambiguous, не ok')
    interior = np.full((H, W, 3), 235, np.uint8)
    interior[0:80, 90:310] = (160, 170, 200)          # интерьер выше кровати: «чужое» над вырезкой при ЛЮБОМ изголовье
    interior[120:240, 80:320] = (120, 90, 60)
    al = np.zeros((H, W), np.uint8)
    al[120:240, 80:320] = 255
    ci = np.dstack([interior[120:240, 80:320], al[120:240, 80:320]])
    got_i = k1(interior, ci, (80, 120))
    ok(got_i == 'ok', f'К1: синтетический интерьерный кадр → ровно ok (ложное срабатывание на нём НЕ воспроизводится; два настоящих названных случая interior_false_positive закреплены в золоте); сейчас {got_i}')

    def pillow(kind):
        h, w = 200, 200
        px = np.full((h, w, 3), (180, 60, 70), np.uint8)
        rg = np.random.RandomState(5)
        px = np.clip(px.astype(int) + rg.randint(-3, 4, px.shape), 0, 255).astype(np.uint8)
        if kind == 'piping':        # кант по краю — срез кромки 3 % его убирает
            px[:4, :] = (240, 240, 240)
            px[-4:, :] = (240, 240, 240)
        if kind == 'dots':
            for y in range(20, 180, 40):
                for x in range(20, 180, 40):
                    px[y:y + 10, x:x + 10] = (240, 220, 40)
        al = np.zeros((h + 16, w + 16), np.uint8)
        al[8:-8, 8:-8] = 255
        full = np.zeros((h + 16, w + 16, 4), np.uint8)
        full[8:-8, 8:-8, :3] = px
        full[:, :, 3] = al
        return full
    th3 = K3['thresholds']

    def k3(kind):
        return CG.verdict('pillow_plain', PM.k3_measure(pillow(kind), th3['edge_erode']), th3)[0]
    ok(k3('plain') == 'pattern_free', 'К3: однотонная — pattern_free')
    ok(k3('piping') == 'pattern_free', 'К3: подушка с кантом — кант срезан кромкой, остаётся однотонной')
    ok(k3('dots') == 'pattern', 'К3: точечный рисунок — pattern')


# ------------------------------------------------------------------ (в) crop_box = trim_alpha
def crop_box_test():
    print('(в) crop_box = фактическая обрезка trim_alpha:')
    rng = np.random.RandomState(2)
    cases = {}
    a = np.zeros((120, 160), np.uint8)
    a[30:70, 40:100] = 255
    cases['обычный'] = a
    cases['пустая альфа → весь кадр'] = np.zeros((90, 70), np.uint8)
    b = np.zeros((100, 100), np.uint8)
    b[0:20, 0:10] = 200
    cases['у края кадра (поле обрезается кадром)'] = b
    c = np.zeros((100, 100), np.uint8)
    c[50, 50] = 255
    cases['один пиксель'] = c
    d = np.zeros((100, 100), np.uint8)
    d[40:60, 40:60] = 8
    cases['альфа ровно 8 — не считается'] = d
    e = np.zeros((100, 100), np.uint8)
    e[40:60, 40:60] = 9
    cases['альфа 9 — считается'] = e
    f = rng.randint(0, 3, (80, 80)).astype(np.uint8)
    f[10:20, 60:75] = 255
    cases['шум ≤8 вокруг предмета'] = f
    for name, alpha in cases.items():
        shape = Image.fromarray(np.dstack([rng.randint(0, 255, alpha.shape + (3,)).astype(np.uint8), alpha]), 'RGBA')
        box = CS.crop_box(shape)
        ok(shape.crop(box).tobytes() == PRE.trim_alpha(shape).tobytes() and shape.crop(box).size == PRE.trim_alpha(shape).size, name)


# ------------------------------------------------------------------ стенд для one() / прохода
class FakeStore:
    def __init__(self):
        self.rows = {}        # key → dict(status, attempts, age, verdict, metrics, err)
        self.fail_write = None
        self.missing = False

    def _chk(self):
        if self.missing:
            raise PS.TableMissing('нет таблицы')

    def write_done(self, sha, role, mv, digest, metrics, verdict):
        self._chk()
        if self.fail_write:
            raise self.fail_write
        self.rows[(sha, role, mv)] = {'status': 'done', 'attempts': 0, 'age': 0, 'verdict': verdict, 'metrics': metrics, 'err': None}

    def write_fail(self, sha, role, mv, digest, code, terminal):
        self._chk()
        r = self.rows.get((sha, role, mv))
        if r and r['status'] == 'done':
            return
        # зеркало SQL `PgStore.write_fail`: прибавка к attempts — только если прошлая запись строки старше COOLDOWN_S (проверено на настоящем Postgres: passport_shadow_dbtest.py)
        n = 1 if not r else r['attempts'] + (1 if r['age'] >= PS.COOLDOWN_S else 0)
        st = 'quarantine' if terminal or n >= PS.attempts_max() else 'retry'
        self.rows[(sha, role, mv)] = {'status': st, 'attempts': n, 'age': 0, 'verdict': None, 'metrics': None, 'err': code}

    def states(self):
        self._chk()
        return {k: (v['status'], v['attempts'], v['age']) for k, v in self.rows.items()}

    def age_all(self, secs):
        for v in self.rows.values():
            v['age'] += secs


def png_bytes(arr, mode):
    b = io.BytesIO()
    Image.fromarray(arr, mode).save(b, 'PNG')
    return b.getvalue()


def pillow_cut():
    h, w = 120, 120
    px = np.full((h, w, 3), (160, 60, 70), np.uint8)
    full = np.zeros((h + 16, w + 16, 4), np.uint8)
    full[8:-8, 8:-8, :3] = px
    full[8:-8, 8:-8, 3] = 255
    return png_bytes(full, 'RGBA')


def bed_pair():
    src = np.full((200, 260, 3), 235, np.uint8)
    src[20:70, 60:200] = 250
    src[70:170, 40:220] = (120, 90, 60)
    al = np.zeros((200, 260), np.uint8)
    al[70:170, 40:220] = 255
    cut = np.dstack([src[70:170, 40:220], al[70:170, 40:220]])
    return png_bytes(src, 'RGB'), png_bytes(cut, 'RGBA')


@contextlib.contextmanager
def shadow_env(store=None, **env):
    """Изолированное окружение тени: своя заглушка хранилища, сброшенный счётчик прогона, переменные среды, откат всего."""
    old_store, old_cmd = PS.STORE, PS.GUARD_CMD
    env = {'SHADOW_BACKFILL_LOCK': os.path.join(tempfile.mkdtemp(prefix='shadow-lock-'), 'backfill.lock'), **env}     # свой замок прохода: тесты не трогают ~/.remlab-shadow-backfill.lock
    old_env = {k: os.environ.get(k) for k in env}
    os.environ.update({k: str(v) for k, v in env.items()})
    PS.STORE = store or FakeStore()
    PS.GUARD_CMD = None
    PS.run_reset()
    MTP.reset_stats()
    try:
        yield PS.STORE
    finally:
        PS.STORE, PS.GUARD_CMD = old_store, old_cmd
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        PS.run_reset()


def one_env(td, raw, cut_img, info, role='подушка'):
    """Патчи `cutout_sync.one`: сеть, маска и цепочка — заглушки; `db` пишет SQL в журнал. → (job, sqls, restore)."""
    sha = hashlib.sha256(raw).hexdigest()
    sqls = []
    saved = (CS.CACHE, CS.fetch, CS.BACKENDS, CS.chain, CS.db)
    CS.CACHE = td
    CS.fetch = lambda url, timeout=40: raw
    CS.BACKENDS = {CS.BACKEND: lambda r: Image.new('L', Image.open(io.BytesIO(r)).size, 255)}
    CS.chain = lambda src, net, role=None: (cut_img, dict(info))
    CS.db = lambda sql, *a, **k: sqls.append(sql) or []

    def restore():
        CS.CACHE, CS.fetch, CS.BACKENDS, CS.chain, CS.db = saved
    return ('1:1', role, 'http://x/1.png', sha), sqls, restore


GOOD_INFO = {'photo': {'object_wh': [120, 120], 'object_share': 0.6, 'object_rel_side': 0.9, 'object_xy': [8, 8]}}


# ------------------------------------------------------------------ (а) сбой тени не делает вырезку fail
def test_a():
    print('(а) сбой тени не делает вырезку fail:')
    raw = png_bytes(np.full((136, 136, 3), (160, 60, 70), np.uint8), 'RGB')
    cut = Image.open(io.BytesIO(pillow_cut())).convert('RGBA')
    with tempfile.TemporaryDirectory() as td, shadow_env() as store:
        job, sqls, restore = one_env(td, raw, cut, GOOD_INFO)
        try:
            (r, _), out = quiet(lambda: (CS.one(job), None))
            ok(r == ('ok', None) and any('insert into photo_assessment' in s for s in sqls) and store.rows, 'норма: ok, оценка записана, тень записана')
            n_ok = len(store.rows)
            # сторож бросает
            orig = CG.run_guard_child
            CG.run_guard_child = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('сторож упал'))
            sqls.clear()
            (r, _), out = quiet(lambda: (CS.one(job), None))
            ok(r == ('ok', None) and any('insert into photo_assessment' in s for s in sqls), 'сторож бросил → one() = ok, photo_assessment записан')
            ok('WARN:passport_shadow' in out and PS.RUN.fail == 1, 'сбой виден: WARN:passport_shadow, shadow_fail = 1')
            CG.run_guard_child = orig
            # вставка в passport_shadow бросает
            store.fail_write = RuntimeError('вставка упала')
            sqls.clear()
            (r, _), out = quiet(lambda: (CS.one(job), None))
            ok(r == ('ok', None) and any('insert into photo_assessment' in s for s in sqls), 'вставка в passport_shadow бросила → one() = ok')
            store.fail_write = None
            # зависший сторож: таймаут 0.5 с
            PS.GUARD_CMD = [sys.executable, '-c', 'import time; time.sleep(60)']
            t0 = time.time()
            os.environ['SHADOW_GUARD_TIMEOUT_S'] = '0.5'
            sqls.clear()
            (r, _), out = quiet(lambda: (CS.one(job), None))
            ok(r == ('ok', None) and time.time() - t0 < 15 and PS.RUN.codes['guard_timeout'] == 1
               and any('insert into photo_assessment' in s for s in sqls), 'та же задержка сторожа в one(): ok, оценка на месте, код guard_timeout')
            PS.GUARD_CMD = None
            os.environ.pop('SHADOW_GUARD_TIMEOUT_S', None)
        finally:
            restore()
    # серия сбоев: FAIL_STREAK_MAX не приближен, SHADOW_FAIL_MAX выключает тень
    with tempfile.TemporaryDirectory() as td, shadow_env(SHADOW_FAIL_MAX=5):
        job, sqls, restore = one_env(td, raw, cut, GOOD_INFO)
        calls = []
        orig = CG.run_guard_child
        CG.run_guard_child = lambda *a, **k: calls.append(1) or ('guard_error', None)
        old_w = CS.WORKERS
        try:
            jobs = [(f'1:{i}', 'подушка', 'http://x', job[3]) for i in range(40)]
            st, out = quiet(CS.run_jobs, jobs)
            ok(st['ok'] == 40 and st['fail'] == 0 and not st.get('stopped'), f"40 вырезок при падающей тени: ok 40, fail 0, прогон не остановлен ({st})")
            ok(PS.RUN.off and len(calls) <= 5 + CS.WORKERS and 'WARN:passport_shadow_off' in out,
               f'SHADOW_FAIL_MAX=5 → тень выключена до конца прогона, вызовов сторожа {len(calls)}')
            ok('тень (вырезка)' in out and 'ВЫКЛЮЧЕНА' in out, 'строка тени есть в итоге прогона')
        finally:
            CG.run_guard_child = orig
            CS.WORKERS = old_w
            restore()
    # выключатель
    with tempfile.TemporaryDirectory() as td, shadow_env(PASSPORT_SHADOW=0) as store:
        job, sqls, restore = one_env(td, raw, cut, GOOD_INFO)
        try:
            (r, _), out = quiet(lambda: (CS.one(job), None))
            ok(r == ('ok', None) and not store.rows and 'passport' not in out, 'PASSPORT_SHADOW=0 — тени нет совсем, вырезка прежняя')
        finally:
            restore()
    # роль без сторожей / нет таблицы
    with tempfile.TemporaryDirectory() as td, shadow_env() as store:
        job, sqls, restore = one_env(td, raw, cut, GOOD_INFO, role='комод')
        try:
            (r, _), _o = quiet(lambda: (CS.one(job), None))
            ok(r == ('ok', None) and not store.rows, 'роль без сторожей (комод): тень ничего не делает')
        finally:
            restore()
    with tempfile.TemporaryDirectory() as td, shadow_env() as store:
        store.missing = True
        job, sqls, restore = one_env(td, raw, cut, GOOD_INFO)
        try:
            (r, _), out = quiet(lambda: (CS.one(job), CS.one(job)))
            ok(r == ('ok', None) and out.count('WARN:passport_shadow') == 1 and 'миграция' in out and PS.RUN.table_missing and PS.RUN.fail == 0,
               'нет таблицы: ровно одна WARN про миграцию 018, вырезка ok, это не «сбой тени»')
        finally:
            restore()


# ------------------------------------------------------------------ (б) реестр и таблицы: путь очереди не изменился
def test_b():
    print('(б) битый/отсутствующий реестр, нет таблицы: очередь, ключи заданий и экспорт не меняются:')
    old_path = MTP.PATH
    tmp = tempfile.mkdtemp(prefix='reg-')
    broken = os.path.join(tmp, 'broken.json')
    open(broken, 'w').write('{не json')
    wrong_schema = os.path.join(tmp, 'wrong.json')
    json.dump({'version': 1, 'types': {'x': {'sku': '1'}}}, open(wrong_schema, 'w'))
    states = {'норма': old_path, 'битый JSON': broken, 'не та схема': wrong_schema, 'файла нет': os.path.join(tmp, 'нет.json')}

    def run_queue():
        use_registry(cur[0])
        MTP.reset_stats()
        MTP._WARNED.clear() if hasattr(MTP, '_WARNED') else None
        sql_q, sql_s = [], []
        saved = (MS.db, MQ.db)

        def fq(sql, *a, **k):
            sql_s.append(sql)
            if 'from mesh_demand d' in sql and 'passport_shadow' not in sql:
                return [['1:11', 'кровать'], ['1:12', 'подушка'], ['1:13', 'комод'], ['1:14', 'диван']]
            if 'passport_shadow' in sql:
                raise RuntimeError('relation "passport_shadow" does not exist')
            return []
        MS.db = fq
        MQ.db = fq
        try:
            r, out = quiet(MS._queue)
        finally:
            MS.db, MQ.db = saved
        return r, [s for s in sql_s if 'passport' not in s], out
    results = {}
    cur = [None]
    for name, path in states.items():
        cur[0] = path
        results[name] = run_queue()
    base = results['норма']
    ok(all(v[0] == base[0] and v[1] == base[1] for v in results.values()), '_queue: тот же набор товаров и те же запросы при любом состоянии реестра')
    ok(all(v[0] == {'1:11': 'кровать', '1:12': 'подушка', '1:13': 'комод', '1:14': 'диван'} for v in results.values()), '_queue: состав очереди не зависит от реестра')
    ok(results['битый JSON'][2].count('WARN:passport_registry') + results['не та схема'][2].count('WARN:passport_registry') + results['файла нет'][2].count('WARN:passport_registry') == 3,
       'на каждое нарушение — одна WARN-строка про реестр')

    # создание заданий и колонка digest: вставка и ключ те же; хеш — отдельным update; нет колонки — WARN и дальше
    def run_main(path, column_missing=False):
        use_registry(path)
        MTP.reset_stats()
        sqls = []
        saved = (MS.db, MS.tiers, PS.STORE)
        MS._STAMP_WARNED.clear()

        def fq(sql, *a, **k):
            sqls.append(sql)
            if sql.startswith('insert into mesh_jobs'):
                return [['1:11|shaX|v']]
            if sql.startswith('select role from mesh_demand'):
                return [['кровать']]
            if 'passport_digest' in sql and column_missing:
                raise RuntimeError('column "passport_digest" of relation "mesh_jobs" does not exist')
            return []
        MS.db = fq
        MS.tiers = lambda: [(1, '1:11', 'тест')]
        PS.STORE = types.SimpleNamespace(db=lambda sql, timeout=None: fq(sql))     # _stamp_digest ходит через PS.timed_db → STORE.db (с потолком), тот же журнал SQL
        try:
            r, out = quiet(MS.main)
        finally:
            MS.db, MS.tiers, PS.STORE = saved
        return r, sqls, out
    ok_r, ok_sql, ok_out = run_main(old_path)
    br_r, br_sql, br_out = run_main(broken)
    col_r, col_sql, col_out = run_main(old_path, column_missing=True)
    ins = lambda L: [s for s in L if s.startswith('insert into mesh_jobs')]
    ok(ins(ok_sql) == ins(br_sql) == ins(col_sql) and len(ins(ok_sql)) == 1, 'вставка задания (job_key и поля) побайтно та же при норме, битом реестре и без колонки')
    ok(sum('update mesh_jobs set passport_digest' in s for s in ok_sql) == 1 and not any('passport_digest' in s for s in br_sql),
       'хеш паспорта — отдельным update (один при норме; нет при битом реестре)')
    ok(ok_r == br_r == col_r == 0 and 'поставлено заданий: 1' in col_out and col_out.count('WARN:passport_shadow') == 1, 'нет колонки: задание поставлено, одна WARN, код 0')

    # экспорт для Salad
    def run_export(path, observe=True):
        use_registry(path)
        MTP.reset_stats()
        out_path = os.path.join(tmp, 'exp.json')
        saved = (MQ.db, MQ.size_guard, MQ.passport_observe)
        MQ.size_guard = lambda: 0
        if not observe:
            MQ.passport_observe = lambda items: None

        def fq(sql, *a, **k):
            if 'from mesh_jobs j' in sql:
                return [['1:11|shaA|v', '1:11', 'кровать', 'http://x/a.png', '{}', 'Кровать', 'ok', MQ.ASSESSOR_VERSION],
                        ['1:12|shaB|v', '1:12', 'подушка', 'http://x/b.png', '{}', 'Подушка', 'ok', MQ.ASSESSOR_VERSION],
                        ['1:13|shaC|v', '1:13', 'комод', 'http://x/c.png', '{}', 'Комод', 'collage', MQ.ASSESSOR_VERSION]]
            if 'passport_shadow' in sql:
                raise RuntimeError('нет таблицы')
            return []
        MQ.db = fq
        try:
            quiet(MQ.export, out_path)
        finally:
            MQ.db, MQ.size_guard, MQ.passport_observe = saved
        return open(out_path, 'rb').read()
    base_exp = run_export(old_path, observe=False)
    ok(run_export(old_path) == base_exp and run_export(broken) == base_exp and run_export(os.path.join(tmp, 'нет.json')) == base_exp,
       'экспорт: манифест для Salad побайтно как «до плана» (без гейта) — при норме, битом и отсутствующем реестре')
    ok(b'passport' not in base_exp, 'в манифесте нет ни одного поля паспорта')
    use_registry(old_path)
    MTP.reset_stats()
    # гейт observe сам: только читает
    sql, touts = [], []
    saved = (MQ.db, PS.STORE)
    MQ.db = lambda s, *a, **k: (_ for _ in ()).throw(AssertionError('гейт очереди не должен ходить в `db` очереди (у него нет таймаута)'))
    PS.STORE = types.SimpleNamespace(db=lambda s, timeout=None: sql.append(s) or touts.append(timeout) or [])
    try:
        quiet(MQ.passport_observe, {'1:1': 'кровать', '1:2': 'ничего'})
    finally:
        MQ.db, PS.STORE = saved
    ok(len(sql) == 1 and all(s.lstrip().lower().startswith('select') for s in sql) and MTP.STATS['would_block:no_passport'] == 1,
       'гейт observe: один select; роль без паспорта — would_block:no_passport, решение pass')
    ok(touts == [PS.observe_timeout()], f'гейт observe: чтение вердиктов — с потолком SHADOW_OBSERVE_TIMEOUT_S ({touts})')
    # sg_salad: вызов в своём try
    # sg_salad: настоящая функция `_passport_observe` (достаётся из исходника через ast — модуль тянет тяжёлые зависимости), выполняется в трёх состояниях
    src = open(os.path.join(SCOUT, 'stablegen', 'sg_salad.py'), encoding='utf-8').read()
    fn_node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == '_passport_observe')
    msgs: list = []
    ns = {'sys': sys, 'os': os, 'HERE': os.path.join(SCOUT, 'stablegen'), 'say': msgs.append}
    exec(compile(ast.Module(body=[fn_node], type_ignores=[]), 'sg_salad_passport_observe', 'exec'), ns)
    obs = ns['_passport_observe']
    MTP.reset_stats()
    r1 = obs('кровать')
    ok(r1 is None and not msgs and sum(MTP.STATS.values()) == 1, f'sg_salad: гейт при норме — ничего не возвращает, ничего не печатает, ровно один счёт ({dict(MTP.STATS)})')
    use_registry(broken)
    MTP.reset_stats()
    r2 = obs('кровать')
    ok(r2 is None and sum(MTP.STATS.values()) == 1, 'sg_salad: гейт при битом реестре — не бросает, платный путь не меняется (gate ловит сам)')
    use_registry(old_path)
    saved_mod = sys.modules.get('mesh_type_passports')
    sys.modules['mesh_type_passports'] = None            # import → ImportError: поломка самого модуля, не реестра
    try:
        r3 = obs('кровать')
    finally:
        sys.modules['mesh_type_passports'] = saved_mod
    ok(r3 is None and len(msgs) == 1 and msgs[0].startswith('WARN:passport_registry'), 'sg_salad: сломанный импорт модуля — одна WARN, не исключение (свой try)')
    MTP.reset_stats()
    src = open(os.path.join(SCOUT, 'stablegen', 'sg_salad.py'), encoding='utf-8').read()
    ok("_passport_observe(cfg['cat_role'])" in src and src.count('MTP.passport_preflight(role)') == 1 and "cfg['passport" not in src,
       'sg_salad: гейт вызывается из build_cfg, в cfg ничего не добавляется')


# ------------------------------------------------------------------ (г) поле object_xy не ломает потребителей
def test_g():
    print('(г) photo.object_xy не меняет потребителей метрик:')
    base = {'photo': {'object_wh': [400, 400], 'object_share': 0.5, 'object_rel_side': 0.8}, 'verdict': 'ok'}
    withxy = json.loads(json.dumps(base))
    withxy['photo']['object_xy'] = [12, 30]
    for role in ('кровать', 'подушка', 'комод', ''):
        ok(PF.verdict_from_metrics(role, base) == PF.verdict_from_metrics(role, withxy), f'verdict_from_metrics({role!r}) тот же')
    rows = [('s', 'a-test', 'кровать', 'ok', json.dumps(base)), ('t', 'a-test', 'кровать', 'ok', json.dumps(withxy))]
    ok([x[2] for x in PF.reverdict_plan(rows[:1])] == [x[2] for x in PF.reverdict_plan(rows[1:])], 'reverdict_plan: с полем и без него — тот же пересчёт вердиктов')
    ok(PF.shadow_verdict('кровать', withxy, REG['types']['кровать'], {'headboard_loss': ('ok', None)}) == PF.shadow_verdict('кровать', base, REG['types']['кровать'], {'headboard_loss': ('ok', None)}),
       'shadow_verdict: то же')
    src = open(os.path.join(SCOUT, 'cutout_sync.py'), encoding='utf-8').read()
    ok("'object_xy': [box[0], box[1]]" in src, 'chain пишет object_xy только внутрь info["photo"]')


# ------------------------------------------------------------------ (д), (д2) проход по тёплой части
def cand(sha, role='подушка', room='living'):
    return {'sha': sha, 'role': role, 'url': f'http://x/{sha}', 'room': room}


def test_d():
    print('(д) --shadow-backfill не пишет photo_assessment и не трогает кэш:')
    cut = pillow_cut()
    with tempfile.TemporaryDirectory() as td, shadow_env() as store:
        for s in ('a1', 'a2', 'a3'):
            open(os.path.join(td, s + '.png'), 'wb').write(cut)
        before = {n: (open(os.path.join(td, n), 'rb').read(), os.stat(os.path.join(td, n)).st_mtime_ns) for n in os.listdir(td)}
        rep, out = quiet(PS.backfill, [cand('a1'), cand('a2'), cand('a3')], td, lambda u: b'', store)
        after = {n: (open(os.path.join(td, n), 'rb').read(), os.stat(os.path.join(td, n)).st_mtime_ns) for n in os.listdir(td)}
        ok(rep['done'] == 3 and len(store.rows) == 3 and all(v['verdict'] == 'ok' for v in store.rows.values()), f'К3 без сети: 3 строки done ({rep["outcomes"]})')
        ok(before == after, 'кэш вырезок: те же файлы, те же байты, те же mtime')
        ok(all(v['metrics'].get('guard_verdict') == 'pattern_free' for v in store.rows.values()), 'в метриках — метка сторожа (pattern_free)')
        calls = []
        rep2, _o = quiet(PS.backfill, [cand('a1'), cand('a2'), cand('a3')], td, lambda u: calls.append(u) or b'', store)
        ok(rep2['selected'] == 0 and not calls, 'готовое не пересчитывается (повторный проход выбрал 0)')
    # точка входа: не касается вырезки и оценок
    saved = (CS.run_jobs, CS.todo, CS.sync_photos, PS.run_backfill, sys.argv)
    called = []
    CS.run_jobs = CS.todo = CS.sync_photos = lambda *a, **k: (_ for _ in ()).throw(AssertionError('вырезка не должна идти'))
    PS.run_backfill = lambda *a, **k: called.append(a[0]) or {}
    sys.argv = ['cutout_sync.py', '--shadow-backfill']
    try:
        r, _o = quiet(CS.main)
        ok(r == 0 and called == [PRE.ASSESSOR_VERSION], '--shadow-backfill: код 0, идёт только проход, нового вырезания и хешей нет')
    finally:
        CS.run_jobs, CS.todo, CS.sync_photos, PS.run_backfill, sys.argv = saved


def test_d2():
    print('(д2) устойчивость прохода:')
    cut = pillow_cut()
    raw_bed, cut_bed = bed_pair()
    sha_bed = hashlib.sha256(raw_bed).hexdigest()
    with tempfile.TemporaryDirectory() as td, shadow_env() as store:
        good_png = os.path.join(td, 'ok1.png')
        open(good_png, 'wb').write(cut)
        open(os.path.join(td, 'broken.png'), 'wb').write(b'not a png')
        for s in ('bed_ok', 'bed_moved', 'bed_fetch'):
            open(os.path.join(td, s + '.png'), 'wb').write(cut_bed)
        # sha исходника кровати должен совпасть у bed_ok; у bed_moved — нет
        cands = [cand('miss'), cand('broken'), cand('ok1'), cand(sha_bed, 'кровать'), cand('bed_moved', 'кровать'), cand('bed_fetch', 'кровать'), cand('ok2')]
        open(os.path.join(td, sha_bed + '.png'), 'wb').write(cut_bed)
        open(os.path.join(td, 'ok2.png'), 'wb').write(cut)

        def fetch(url):
            if url.endswith('bed_fetch'):
                raise OSError('таймаут')
            return raw_bed
        rep, out = quiet(PS.backfill, cands, td, fetch, store)
        oc = rep['outcomes']
        ok(oc['missing_cache'] == 1 and oc['decode_failed'] == 1 and oc['fetch_failed'] == 1 and oc['sha_moved'] == 1,
           f'каждая отравленная строка получила свой исход: {dict(oc)}')
        ok(oc['ok'] == 4 - 0 or oc['ok'] >= 3, f'остальные посчитаны: ok {oc["ok"]} (подушки 2 + кровать с верным sha)')
        k = lambda sha, role: next(v for kk, v in store.states().items() if kk[0] == sha and kk[1] == role)
        ok(k('miss', 'подушка')[:2] == ('retry', 1) and k('broken', 'подушка')[:2] == ('quarantine', 1) and k('bed_moved', 'кровать')[:2] == ('quarantine', 1)
           and k('bed_fetch', 'кровать')[:2] == ('retry', 1), 'retry/quarantine по классу исхода, attempts = 1')
        ok(k('ok1', 'подушка')[0] == 'done' and k(sha_bed, 'кровать')[0] == 'done', 'идущие за отравленными посчитаны')
        # attempts растёт не чаще раза в ночь
        rep, _o = quiet(PS.backfill, cands, td, fetch, store)
        ok(rep['selected'] == 0 and k('miss', 'подушка')[1] == 1, 'в ту же ночь retry-строки не берутся: attempts не растёт')
        store.age_all(25 * 3600)
        quiet(PS.backfill, cands, td, fetch, store)
        ok(k('miss', 'подушка')[:2] == ('retry', 2) and k('bed_fetch', 'кровать')[:2] == ('retry', 2), 'через сутки — 2-я попытка')
        store.age_all(25 * 3600)
        quiet(PS.backfill, cands, td, fetch, store)
        ok(k('miss', 'подушка')[:2] == ('quarantine', 3), f'3-я неудача → quarantine ({k("miss", "подушка")})')
        store.age_all(25 * 3600)
        rep, _o = quiet(PS.backfill, cands, td, fetch, store)
        ok(rep['selected'] == 0, 'карантин в выборку не возвращается')
    # прерванный посреди проход продолжается, готовые не пересчитываются
    with tempfile.TemporaryDirectory() as td, shadow_env() as store:
        shas = [f'c{i:02d}' for i in range(8)]
        for s in shas:
            open(os.path.join(td, s + '.png'), 'wb').write(cut)
        cands = [cand(s) for s in shas]
        calls = collections.Counter()
        orig = CG.run_guard_child
        n = [0]

        def rg(guard, cut_path, *a, **k):
            calls[os.path.basename(cut_path)] += 1
            n[0] += 1
            if n[0] == 4:
                raise KeyboardInterrupt('убитый процесс')
            return orig(guard, cut_path, *a, **k)
        CG.run_guard_child = rg
        try:
            try:
                quiet(PS.backfill, cands, td, lambda u: b'', store)
            except KeyboardInterrupt:
                pass
            done1 = {k[0] for k, v in store.rows.items() if v['status'] == 'done'}
            ok(len(done1) == 3, f'до обрыва записано 3, состояние осталось в хранилище ({sorted(done1)})')
            CG.run_guard_child = orig
            calls.clear()
            rep, _o = quiet(PS.backfill, cands, td, lambda u: b'', store)
            ok(rep['selected'] == 5 and rep['done'] == 5 and len({k[0] for k, v in store.rows.items() if v['status'] == 'done'}) == 8,
               f'следующий запуск доделал остальные 5, готовые не пересчитал ({rep["selected"]})')
        finally:
            CG.run_guard_child = orig
    # зависший сторож
    with tempfile.TemporaryDirectory() as td, shadow_env(SHADOW_GUARD_TIMEOUT_S=0.5) as store:
        for s in ('h1', 'h2'):
            open(os.path.join(td, s + '.png'), 'wb').write(cut)
        PS.GUARD_CMD = [sys.executable, '-c', 'import time; time.sleep(60)']
        t0 = time.time()
        rep, _o = quiet(PS.backfill, [cand('h1'), cand('h2')], td, lambda u: b'', store)
        ok(rep['outcomes']['guard_timeout'] == 2 and rep['retry'] == 2 and time.time() - t0 < 20, 'зависший сторож убит по таймауту, проход пошёл дальше (guard_timeout ×2, retry)')
        PS.GUARD_CMD = None
    # серия одинаковых retry-сбоев завершает проход ночи
    with tempfile.TemporaryDirectory() as td, shadow_env() as store:
        cands = [cand(f'z{i}') for i in range(6)]       # кэша нет: missing_cache ×6
        rep, out = quiet(PS.backfill, cands, td, lambda u: b'', store, streak_max=3)
        ok(rep['stop'] and rep['outcomes']['missing_cache'] == 3 and 'WARN:passport_backfill_stop code=missing_cache' in out, f'3 подряд одинаковых → проход остановлен, остальные ждут ({rep["stop"]})')
        # разные коды сериям не мешают
        open(os.path.join(td, 'b_ok.png'), 'wb').write(cut)      # порядок прохода — по sha: a1, b_ok, c1, c2, c3
        store2 = FakeStore()
        mixed = [cand('a1'), cand('b_ok'), cand('c1'), cand('c2'), cand('c3')]
        rep, _o = quiet(PS.backfill, mixed, td, lambda u: b'', store2, streak_max=4)
        ok(rep['outcomes']['missing_cache'] == 4 and rep['done'] == 1 and rep['stop'] is None, 'удачная строка сбрасывает серию (1 + 3 подряд при пороге 4 — не стоп)')
    # бюджет времени
    with tempfile.TemporaryDirectory() as td, shadow_env() as store:
        for i in range(5):
            open(os.path.join(td, f'b{i}.png'), 'wb').write(cut)
        tick = [0.0]

        def clock():
            tick[0] += 1.0
            return tick[0]
        rep, _o = quiet(PS.backfill, [cand(f'b{i}') for i in range(5)], td, lambda u: b'', store, budget_s=3, clock=clock)
        ok(rep['stop'] == 'бюджет времени' and 0 < rep['done'] < 5, f'бюджет времени завершает проход чисто ({rep["done"]} из 5, {rep["stop"]})')
    # нет таблицы
    with tempfile.TemporaryDirectory() as td, shadow_env() as store:
        store.missing = True
        rep, out = quiet(PS.backfill, [cand('q')], td, lambda u: b'', store)
        ok(rep['stop'] and 'миграция 018' in rep['stop'] and 'WARN:passport_shadow' in out, 'нет таблицы: проход не падает, одна WARN, остановка с причиной')
    # порядок: сначала без строки, спальня раньше, внутри по sha
    jobs = PS.plan_backfill([cand('z9'), cand('b2', room='bedroom'), cand('a1'), cand('b1', room='bedroom')], {})
    ok([j['sha'] for j in jobs] == ['b1', 'b2', 'a1', 'z9'], 'порядок: спальня раньше, внутри — по sha')
    st = {('r1', 'подушка', 'k3.v1'): ('retry', 1, 26 * 3600), ('r2', 'подушка', 'k3.v1'): ('retry', 1, 30 * 3600), ('r3', 'подушка', 'k3.v1'): ('retry', 1, 3600)}
    jobs = PS.plan_backfill([cand('new'), cand('r1'), cand('r2'), cand('r3')], st)
    ok([j['sha'] for j in jobs] == ['new', 'r2', 'r1'], 'сначала без строки, потом retry по старшему updated, свежий retry (<24 ч) мимо')
    jobs = PS.plan_backfill([cand('x')], {('x', 'подушка', 'k3.v1'): ('retry', 3, 99 * 3600)})
    ok(jobs == [], 'attempts ≥ SHADOW_ATTEMPTS_MAX — мимо')


# ------------------------------------------------------------------ тень K1 в one(): боевая запись
def test_shadow_k1_in_one():
    print('тень К1 в one(): настоящий дочерний процесс, смещение вырезки из object_xy:')
    raw, cut_bytes = bed_pair()
    cut = Image.open(io.BytesIO(cut_bytes)).convert('RGBA')
    with tempfile.TemporaryDirectory() as td, shadow_env() as store:
        info = {'photo': {'object_wh': [3000, 2000], 'object_share': 0.35, 'object_rel_side': 0.7, 'object_xy': [40, 70]}}
        job, sqls, restore = one_env(td, raw, cut, info, role='кровать')
        try:
            r, _o = quiet(CS.one, job)
            rows = list(store.rows.values())
            ok(r == ('ok', None) and len(rows) == 1 and rows[0]['verdict'] == 'headboard_loss' and rows[0]['metrics']['object_xy_src'] == 'crop',
               f"кровать без изголовья в вырезке: ok, тень headboard_loss, смещение из object_xy ({rows[0]['verdict'] if rows else None})")
            ok(any('insert into photo_assessment' in s and "'ok'" in s for s in sqls), 'вердикт photo_assessment — прежний (ok), тень его не меняет')
        finally:
            restore()


# ------------------------------------------------------------------ (е) salad/ не изменён
def test_e():
    print('(е) salad/ не изменён относительно базы ветки:')
    r = subprocess.run(['git', '-C', ROOT, 'merge-base', 'HEAD', 'origin/main'], capture_output=True, text=True)
    base = r.stdout.strip()
    if r.returncode != 0 or not base:
        # в CI копия обязана быть с историей (ci.yml: fetch-depth: 0) — отсутствие базы там = красный, а не тихий пропуск (Codex T-151/7)
        ok(not os.environ.get('CI'), 'нет origin/main: в CI база обязана быть (fetch-depth: 0), локально проверка по diff пропущена — остаётся статическая')
    else:
        d = subprocess.run(['git', '-C', ROOT, 'diff', '--stat', base, '--', 'tools/scout/salad', 'tools/scout/salad/'], capture_output=True, text=True)
        ok(d.returncode == 0 and not d.stdout.strip(), 'git diff --stat по tools/scout/salad пуст' + ('' if not d.stdout.strip() else f': {d.stdout.strip()[:200]}'))
    src = open(os.path.join(SCOUT, 'passport_shadow.py'), encoding='utf-8').read() + open(os.path.join(SCOUT, 'mesh_type_passports.py'), encoding='utf-8').read()
    ok('salad/worker' not in src, 'код паспортов не обращается к salad/worker.py (фаза 2)')


def _hang_cmd():
    return [sys.executable, '-c', 'import time; time.sleep(120)']


def test_t7_timeouts():
    print('T-151/7 п.1: жёсткие потолки на каждый вызов БД, скачивание и бюджет тени:')
    # (1а) PgStore.db: потолок у подпроцесса и statement/lock_timeout в сеансе
    with tempfile.TemporaryDirectory() as td:
        dump = os.path.join(td, 'stdin.sql')
        PS.PSQL = [sys.executable, '-c', f'import sys; open({dump!r}, "w").write(sys.stdin.read())']
        try:
            PS.PgStore().db('select 1', timeout=7)
            sent = open(dump, encoding='utf-8').read()
            ok("statement_timeout = 7000" in sent and "lock_timeout = 5000" in sent and sent.rstrip().endswith('select 1'),
               f'каждый вызов начинается с set statement_timeout/lock_timeout ({sent.splitlines()[0][:80]})')
            PS.PSQL = _hang_cmd()
            t0 = time.time()
            err = None
            try:
                PS.PgStore().db('select 1', timeout=1)
            except RuntimeError as e:
                err = str(e)
            ok(err and err.startswith('db_timeout') and time.time() - t0 < 15, f'зависший psql прерван по таймауту за {time.time() - t0:.1f} с ({err})')
        finally:
            PS.PSQL = NO_DB
    # (1б) сквозной бюджет: исчерпан → к БД не идём вообще
    with tempfile.TemporaryDirectory() as td:
        touched = os.path.join(td, 'touched')
        PS.PSQL = [sys.executable, '-c', f'open({touched!r}, "w").write("x")']
        PS._DEADLINE[0] = time.monotonic() - 1
        try:
            err = None
            try:
                PS.PgStore().db('select 1')
            except RuntimeError as e:
                err = str(e)
            ok(err and err.startswith('shadow_budget') and not os.path.exists(touched), 'бюджет исчерпан → RuntimeError без обращения к БД')
        finally:
            PS._DEADLINE[0] = None
            PS.PSQL = NO_DB
    # (1в) one(): зависшая БД тени не подвешивает вырезку
    raw = png_bytes(np.full((136, 136, 3), (160, 60, 70), np.uint8), 'RGB')
    cut = Image.open(io.BytesIO(pillow_cut())).convert('RGBA')
    with tempfile.TemporaryDirectory() as td, shadow_env(PS.PgStore(), SHADOW_DB_TIMEOUT_S=1):
        job, sqls, restore = one_env(td, raw, cut, GOOD_INFO)
        PS.PSQL = _hang_cmd()
        try:
            t0 = time.time()
            (r, _), out = quiet(lambda: (CS.one(job), None))
            ok(r == ('ok', None) and any('insert into photo_assessment' in s for s in sqls) and time.time() - t0 < 25 and PS.RUN.fail == 1,
               f'БД тени зависла: one() = ok за {time.time() - t0:.1f} с, оценка записана, сбой тени посчитан ({dict(PS.RUN.codes)})')
        finally:
            PS.PSQL = NO_DB
            restore()
    # (1г) бюджет тени в one() за прогон: исчерпан → тень выключена, вырезка идёт
    with tempfile.TemporaryDirectory() as td, shadow_env(SHADOW_RUN_BUDGET_S=0.000001) as store:
        job, sqls, restore = one_env(td, raw, cut, GOOD_INFO)
        try:
            (r1, _), o1 = quiet(lambda: (CS.one(job), None))
            (r2, _), o2 = quiet(lambda: (CS.one(job), None))
            ok(r1 == ('ok', None) and r2 == ('ok', None) and PS.RUN.off and 'бюджет тени' in o2 and PS.RUN.ok == 1,
               'бюджет тени исчерпан → WARN:passport_shadow_off (бюджет), вырезка ok, вторая запись не сделана')
        finally:
            restore()
    # (1д) скачивание в проходе: «капающий»/зависший ответ не держит проход дольше потолка
    raw_bed, cut_bed = bed_pair()
    sha_bed = hashlib.sha256(raw_bed).hexdigest()
    with tempfile.TemporaryDirectory() as td, shadow_env(SHADOW_FETCH_TIMEOUT_S=1) as store:
        open(os.path.join(td, sha_bed + '.png'), 'wb').write(cut_bed)

        def slow(url):
            time.sleep(30)
            return raw_bed
        t0 = time.time()
        rep, _o = quiet(PS.backfill, [cand(sha_bed, 'кровать')], td, slow, store)
        ok(rep['outcomes']['fetch_failed'] == 1 and time.time() - t0 < 15, f'скачивание зависло: fetch_failed за {time.time() - t0:.1f} с, проход идёт дальше')
    # (1е) реальный PgStore в проходе при зависшей БД: состояние не прочитано, проход чисто остановлен и укладывается в потолок
    with tempfile.TemporaryDirectory() as td, shadow_env(PS.PgStore(), SHADOW_DB_TIMEOUT_S=1):
        PS.PSQL = _hang_cmd()
        try:
            t0 = time.time()
            rep, out = quiet(PS.backfill, [cand('a')], td, lambda u: b'', None)
            ok(rep['stop'] and 'состояние не прочитано' in rep['stop'] and time.time() - t0 < 25, f'зависшая БД: проход остановлен за {time.time() - t0:.1f} с ({rep["stop"]})')
        finally:
            PS.PSQL = NO_DB


def test_t7_claim():
    print('T-151/7 п.2: один проход за раз, attempts не удваивается:')
    cut = pillow_cut()
    with tempfile.TemporaryDirectory() as td, shadow_env() as store:
        lock = os.environ['SHADOW_BACKFILL_LOCK']
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o644)
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)      # «первый проход» держит замок
        calls = []
        try:
            rep, out = quiet(PS.backfill, [cand('l1')], td, lambda u: calls.append(u) or b'', store)
        finally:
            os.close(fd)
        ok(rep['stop'] == 'другой проход уже идёт' and rep['selected'] == 0 and not calls and not store.rows, 'замок занят: второй проход выходит, ничего не считает и не пишет')
        open(os.path.join(td, 'l1.png'), 'wb').write(cut)
        rep, _o = quiet(PS.backfill, [cand('l1')], td, lambda u: b'', store)
        ok(rep['done'] == 1, 'замок свободен (первый закончил): проход идёт')
    # без замка (параллельные процессы с одним снимком состояния): одна неудача считается один раз — зеркало SQL
    with shadow_env() as store:
        store.write_fail('m1', 'подушка', 'k3.v1', 'd', 'missing_cache', False)
        store.write_fail('m1', 'подушка', 'k3.v1', 'd', 'missing_cache', False)
        store.write_fail('m1', 'подушка', 'k3.v1', 'd', 'missing_cache', False)
        ok(store.rows[('m1', 'подушка', 'k3.v1')]['attempts'] == 1 and store.rows[('m1', 'подушка', 'k3.v1')]['status'] == 'retry',
           'три записи неудачи в одну ночь = attempts 1, не карантин')
        store.age_all(PS.COOLDOWN_S + 60)
        store.write_fail('m1', 'подушка', 'k3.v1', 'd', 'missing_cache', False)
        ok(store.rows[('m1', 'подушка', 'k3.v1')]['attempts'] == 2, 'через сутки — 2-я попытка')
    src = open(os.path.join(SCOUT, 'passport_shadow.py'), encoding='utf-8').read()
    ok("updated <= now() - interval '{COOLDOWN_S} seconds'" in src and "attempts = 0, last_error = null" in src,
       'в боевом SQL те же правила (настоящий Postgres — passport_shadow_dbtest.py, прогон на pakardev в отчёте)')


def test_t7_observe():
    print('T-151/7 п.3: observe_gate берёт только текущую роль, версию и хеш; reverdict штампует хеш:')
    cur = PS.current_policy()
    dg_k1, dg_k3 = cur[('кровать', 'k1.v1')], cur[('подушка', 'k3.v1')]

    def run(rows, items):
        MTP.reset_stats()
        PS_sql = []
        PS.observe_gate(items, lambda sql: PS_sql.append(sql) or rows)
        return dict(MTP.STATS), PS_sql[0]
    items = {'1:1': 'кровать', '1:2': 'кровать', '1:3': 'подушка', '1:4': 'кровать', '1:5': 'кровать'}
    rows = [
        ['1:1', 'кровать', 'k1.v0', dg_k1, 'headboard_loss'],      # старая версия замера — не отвечает
        ['1:2', 'подушка', 'k3.v1', dg_k3, 'headboard_loss'],      # роль строки ≠ роль товара
        ['1:3', 'подушка', 'k3.v1', 'старый-хеш', 'headboard_loss'],   # устаревший хеш политики
        ['1:4', 'кровать', 'k1.v1', dg_k1, 'headboard_loss'],      # годная
        ['1:5', 'кровать', 'k1.v1', dg_k1, 'headboard_loss'],
        ['1:5', 'кровать', 'k1.v1', dg_k1, 'ambiguous'],           # дубль того же товара — берётся первая (порядок из SQL)
    ]
    st, sql = run(rows, items)
    ok(st.get('would_block:headboard_loss') == 2 and st.get('shadow_stale_digest') == 1,
       f'годны только строки текущей роли/версии/хеша: would_block 2 (1:4, 1:5), устаревший хеш — отдельный счётчик ({st})')
    ok("('кровать', 'k1.v1')" in sql and "('подушка', 'k3.v1')" in sql and 'order by d.sku, s.normalized_role, s.measurement_version' in sql
       and "s.status = 'done'" in sql, 'запрос: фильтр по паре (роль, версия) и детерминированный порядок')
    st2, _ = run([['1:4', 'кровать', 'k1.v1', dg_k1, 'ambiguous']], {'1:4': 'кровать'})
    ok(st2.get('would_block:headboard_loss', 0) == 0 and st2.get('pass:ok') == 1, 'ambiguous блокирующим не является: pass:ok, не «заблокировал бы»')
    # reverdict: штамп хеша
    targets = PF.shadow_digest_targets(REG)
    ok(('кровать', 'k1.v1', dg_k1) in targets and ('подушка', 'k3.v1', dg_k3) in targets, 'shadow_digest_targets: текущие хеши сторожей реестра')
    sqls: list = []
    saved = PF._sdb
    PF._sdb = lambda sql, *a, **k: sqls.append(sql) or []
    try:
        quiet(PF.shadow_reverdict)
    finally:
        PF._sdb = saved
    upd = [s for s in sqls if s.startswith('update passport_shadow set policy_digest')]
    ok(len(upd) == len(targets) and all("policy_digest <> '" in s and "status = 'done'" in s for s in upd) and any(dg_k1 in s for s in upd),
       'shadow_reverdict: после пересчёта — по update штампа policy_digest на каждый сторож')


def test_t7_failopen():
    print('T-151/7 п.5: release_quarantine и импорт в _stamp_digest — fail-open:')
    saved = (CS.run_jobs, CS.todo, CS.sync_photos, PS.run_backfill, sys.argv, PS.STORE)
    CS.run_jobs = CS.todo = CS.sync_photos = lambda *a, **k: (_ for _ in ()).throw(AssertionError('вырезка не должна идти'))
    called: list = []
    PS.run_backfill = lambda *a, **k: called.append(1) or {}
    sys.argv = ['cutout_sync.py', '--shadow-backfill', '--retry-quarantine']
    try:
        for exc, mark in ((PS.TableMissing('нет таблицы'), 'миграция 018'), (RuntimeError('db_timeout'), 'db_timeout')):
            called.clear()
            PS.STORE = types.SimpleNamespace(release_quarantine=lambda e=exc: (_ for _ in ()).throw(e))
            r, out = quiet(CS.main)
            ok(r == 0 and called == [1] and 'WARN:passport_shadow' in out and mark in out, f'--retry-quarantine при {type(exc).__name__}: код 0, WARN, проход всё равно идёт')
    finally:
        CS.run_jobs, CS.todo, CS.sync_photos, PS.run_backfill, sys.argv, PS.STORE = saved
    # _stamp_digest: сломанный модуль паспортов / проход — задание не теряется, исключения нет, одна WARN
    MS._STAMP_WARNED.clear()
    saved_mods = {k: sys.modules.get(k) for k in ('mesh_type_passports', 'passport_shadow')}
    try:
        sys.modules['mesh_type_passports'] = None
        sys.modules['passport_shadow'] = None
        _r, out = quiet(lambda: [MS._stamp_digest('k|s|v', '1:1') for _ in range(3)])
        ok(out.count('WARN:passport_shadow') == 1, 'сломанный импорт: _stamp_digest не бросает; одна WARN за прогон (а не по строке на задание)')
    finally:
        for k, v in saved_mods.items():
            sys.modules[k] = v
        MS._STAMP_WARNED.clear()
    src = open(os.path.join(SCOUT, 'mesh_scheduler.py'), encoding='utf-8').read()
    body = src[src.index('def _stamp_digest'):src.index('def tiers')]
    ok(body.count('import mesh_type_passports') == 1, 'в _stamp_digest нет повторного импорта в обработчике исключения')


def test_t7_migration():
    print('T-151/7 п.6: миграция 018 с потолками ожидания:')
    sql = open(os.path.join(SCOUT, '018-passport-shadow.sql'), encoding='utf-8').read()
    code = [ln for ln in sql.splitlines() if ln.strip() and not ln.lstrip().startswith('--')]
    i_lock = next(i for i, ln in enumerate(code) if ln.startswith("set lock_timeout"))
    i_alter = next(i for i, ln in enumerate(code) if ln.startswith('alter table mesh_jobs'))
    i_create = next(i for i, ln in enumerate(code) if ln.startswith('create table'))
    ok(i_lock < i_create and i_lock < i_alter and any(ln.startswith('set statement_timeout') for ln in code[:i_create]),
       'set lock_timeout и statement_timeout стоят ДО create table и alter table mesh_jobs')
    chk = next((ln for ln in sql.splitlines() if ln.startswith('--     "(select')), '')
    need = ["table_schema='public'", 'column_default', 'is_nullable', 'data_type', 'indisprimary', "'source_sha,normalized_role,measurement_version'",
            'pg_get_constraintdef', 'passport_shadow_status_idx', 'passport_shadow_role_verdict_idx', "'passport_digest'"]
    miss = [n for n in need if n not in chk]
    ok(not miss and chk.count("table_schema='public'") >= 2 + 0, f'--check сверяет точную схему public.passport_shadow (типы, NOT NULL, defaults, PK по порядку, status, оба индекса) и mesh_jobs.passport_digest; нет: {miss}')


def test_shadow_reverdict():
    print('shadow_reverdict: смена порога пересчитывается из сохранённых чисел:')
    m = json.dumps({'registered': True, 'hb_back': 0.4, 'comps': [{'area_share': 0.05, 'width_share': 0.3}]})
    rows = [('s1', 'кровать', 'k1.v1', m, 'headboard_loss'), ('s2', 'кровать', 'k1.v1', m, 'collage')]
    ok(PF.shadow_reverdict_plan(rows, REG) == [], 'при текущих порогах вердикт тот же; чужой вердикт (размер/коллаж) не трогается')
    import copy
    r2 = copy.deepcopy(REG)
    r2['types']['кровать']['cutout']['guards'][0]['thresholds']['loss_area_share'] = 0.10
    ok(PF.shadow_reverdict_plan(rows, r2) == [('s1', 'кровать', 'k1.v1', 'ok')], 'порог площади 0,10 → тот же случай стал ok без пикселей')
    ok(MTP.digest_of(r2['types']['кровать']) != MTP.digest_of(REG['types']['кровать']), 'смена порога меняет policy_digest паспорта')


def main():
    for f in (gold, chain_roles, synthetic, crop_box_test, test_a, test_b, test_g, test_d, test_d2, test_shadow_k1_in_one, test_e, test_shadow_reverdict,
              test_t7_timeouts, test_t7_claim, test_t7_observe, test_t7_failopen, test_t7_migration):
        f()
    print(f'\ntest_mesh_type_passports: {"ОШИБОК " + str(len(BAD)) if BAD else "всё зелёное"}')
    for b in BAD:
        print('  ✗', b)
    return 1 if BAD else 0


if __name__ == '__main__':
    raise SystemExit(main())
