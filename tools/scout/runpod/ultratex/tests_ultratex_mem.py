#!/usr/bin/env python3
"""Тесты памяти воркера UltraTex (T-178/1, 21.11) БЕЗ видеокарты: одна ветка CFG при равных ветках, кэш пустого текста, куски по токенам (MLP, RoPE, RMSNorm) дают тот же результат,
подписи шагов, учёт пиков, диагностика карты на подмене torch, /diag по HTTP.
  ULTRATEX_DIR=<код авторов> python tools/scout/runpod/ultratex/tests_ultratex_mem.py          (в образе код авторов — /opt/UltraTex)
Нужен torch (CPU хватает) и einops; разделы на настоящих блоках авторов пропускаются, если код авторов не найден."""
from __future__ import annotations

import json
import os
import sys
import threading
import types
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS = []


def ok(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


try:
    import torch
except ImportError:
    print('torch не установлен — тесты памяти пропущены')
    sys.exit(0)

import worker_ultratex as W                                    # noqa: E402

# ---- кэш текстового энкодера
class _Te:
    def __init__(self):
        self.calls = 0

    def __call__(self, texts, *a, **k):
        self.calls += 1
        return torch.full((len(texts), 4, 3), float(self.calls))


te = _Te()
tc = W.TextCache(te)
a = tc([''])
b = tc([''])
ok(te.calls == 1 and tc.hits == 1 and tc.misses == 1, 'пустой текст: энкодер вызван один раз, второй раз — из памяти')
ok(torch.equal(a, b), 'из памяти — то же значение')
b += 5
ok(torch.equal(tc(['']), a), 'правка выданного тензора не портит память (отдаётся копия)')
c = tc(['диван'])
ok(te.calls == 2 and not torch.equal(c, a), 'другой текст — считается заново')
tc(('', ''))
ok(te.calls == 3, 'другой состав списка — другой ключ')
tc([1, 2])                                                     # не список строк: мимо памяти, но без падения
ok(te.calls == 4, 'не список строк — вызов насквозь, не кэшируется')

# ---- одна ветка CFG вместо двух
class _Dit:
    def __init__(self):
        self.seen = []
        self.hidden_size = 4096

    def __call__(self, x, x_ids, timesteps, ctx, ctx_ids, guidance=None):
        self.seen.append(x.shape[0])
        # по образцам (не по всему батчу): глобальный mean() по batch=2 и batch=1 суммирует в разном порядке и расходится на 1 ulp — тест был нестабилен
        return x * 2 + ctx.mean(dim=(1, 2))[:, None, None] + timesteps[:, None, None]


def cfg_inputs(diff_ctx=False, diff_x=False):
    x = torch.randn(1, 6, 4).repeat(2, 1, 1)
    ctx = torch.randn(1, 3, 4).repeat(2, 1, 1)
    if diff_ctx:
        ctx[1] += 1
    if diff_x:
        x[1] += 1
    return dict(x=x, x_ids=torch.zeros(2, 6, 4, dtype=torch.long), timesteps=torch.full((2,), 0.5), ctx=ctx, ctx_ids=torch.zeros(2, 3, 4, dtype=torch.long), guidance=None)


steps = []
dit = _Dit()
cd = W.CfgDedup(dit, 'auto', None, steps.append)
cd.begin(2)
inp = cfg_inputs()
ref = _Dit()(**inp)
out = cd(**inp)
ok(dit.seen == [1] and out.shape[0] == 2 and torch.equal(out, ref), 'равные ветки: DiT считает batch=1, на выходе batch=2 с тем же результатом')
ok(torch.equal(out[0], out[1]), 'обе половины одинаковы (pred_uncond ≡ pred_cond)')
cd(**cfg_inputs(diff_ctx=True))
ok(dit.seen == [1, 2] and cd.stats['batched'] == 1 and cd.stats['differs'] == 'ctx', 'тексты различаются: обычный batch=2, причина записана')
ok(steps[0] == 'dit 1/2' and steps[1] == 'dit 2/2' and steps[-1].startswith('после DiT'), 'ход шагов: «dit i/N» и пометка о декодировании после последнего')
dit2 = _Dit()
cd2 = W.CfgDedup(dit2, 'auto', None, None)
cd2(**cfg_inputs(diff_x=True))
ok(dit2.seen == [2] and cd2.stats['differs'] == 'x', 'различаются входы-картинки: обычный batch=2')
dit3 = _Dit()
cd3 = W.CfgDedup(dit3, 'off', None, None)
cd3(**cfg_inputs())
ok(dit3.seen == [2], 'ULTRATEX_CFG=off — всегда обычный batch=2')
dit4 = _Dit()
cd4 = W.CfgDedup(dit4, 'auto', None, None)
x1 = {k: (v[:1] if isinstance(v, torch.Tensor) else v) for k, v in cfg_inputs().items()}
cd4(**x1)
ok(dit4.seen == [1] and cd4.stats['batched'] == 1, 'batch=1 на входе — без изменений')
ok(cd.hidden_size == 4096, 'обёртка отдаёт атрибуты модели')
hooks = []
cd.after_call = lambda: hooks.append(1)
cd(**cfg_inputs())
ok(hooks == [1], 'хук после шага вызывается (учёт пиков)')

# ---- подписи шагов через Residency
class _M:
    def to(self, d):
        return self

    def __call__(self, *a, **k):
        return 1


names = []
r = W.Residency(_M(), _M(), _M(), 'cuda', None)
r.on_step = names.append
r.labels['dit'] = 'dit 3/25'
r.use('dit')
r.use('te')
ok('dit 3/25' in names and names[-1] == 'te', 'подпись шага DiT выходит в ход задания вместо голого «dit»')

# ---- T-178/3 (22.11): перенос на карту — очистка перед ним; OOM → снимок и один повтор; снова OOM — ошибка со снимками
class _OomM:
    """Модуль: первые fail_n попыток переноса на карту падают OOM (как контрольный Блест: 128 МиБ при 15,7 ГиБ свободных)."""
    def __init__(self, fail_n):
        self.fail_n, self.tries = fail_n, 0

    def to(self, d):
        if d == 'cuda':
            self.tries += 1
            if self.tries <= self.fail_n:
                raise torch.OutOfMemoryError('CUDA out of memory. Tried to allocate 128.00 MiB. GPU 0 has a total capacity of 31.82 GiB of which 15.67 GiB is free.')
        return self

    def parameters(self):
        return iter(())

    def __call__(self, *a, **k):
        return 1


_log = []
_tc = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True, synchronize=lambda: _log.append('sync'), empty_cache=lambda: _log.append('empty'),
                                                       mem_get_info=lambda: (15 * 2 ** 30, 32 * 2 ** 30), memory_allocated=lambda: 14 * 2 ** 30, memory_reserved=lambda: 15 * 2 ** 30,
                                                       max_memory_allocated=lambda: 0, reset_peak_memory_stats=lambda: None))
_r1 = W.Residency(_OomM(0), _OomM(0), _M(), 'cuda', _tc)
_r1.use('dit')
ok(_log[:2] == ['sync', 'empty'] and _r1.on_gpu['dit'] and not _r1.notes, 'перенос на карту: сперва сборка мусора + sync + empty_cache; без OOM заметок нет')
_log.clear()
_r2 = W.Residency(_OomM(1), _OomM(0), _M(), 'cuda', _tc)
_r2.use('dit')
ok(_r2.on_gpu['dit'] and _r2.mods['dit'].tries == 2 and len(_r2.notes) == 1 and _r2.notes[0]['retry_after_oom']['allocated_gb'] == 14.0
   and 'out of memory' in _r2.notes[0]['retry_after_oom']['error'].lower() and _log.count('empty') >= 2, 'OOM при переносе: снимок до очистки, очистка, один повтор удался, заметка пошла в метрики')
_r3 = W.Residency(_OomM(5), _OomM(0), _M(), 'cuda', _tc)
try:
    _r3.use('dit')
    ok(False, 'повторный OOM поднимается наверх')
except RuntimeError as _e:
    ok('OOM и после очистки' in str(_e) and 'снимок после ошибки' in str(_e) and _r3.mods['dit'].tries == 2 and not _r3.on_gpu['dit'], 'повторный OOM → ошибка со снимками, ровно два захода, модуль не помечен «на карте»')
class _NoOom:
    def to(self, d):
        raise ValueError('не OOM')
try:
    W.Residency(_NoOom(), _OomM(0), _M(), 'cuda', _tc).use('dit')
    ok(False, 'не-OOM ошибки не глотаются')
except ValueError:
    ok(True, 'не-OOM ошибка переноса идёт наверх как была (без повтора)')

# ---- учёт пиков (подмена torch.cuda)
class _Cuda:
    peak = [5 * 2 ** 30]
    free = [20 * 2 ** 30]

    @staticmethod
    def is_available():
        return True

    @classmethod
    def max_memory_allocated(cls):
        return cls.peak[0]

    @classmethod
    def max_memory_reserved(cls):
        return cls.peak[0] + 2 ** 30

    @classmethod
    def mem_get_info(cls):
        return cls.free[0], 32 * 2 ** 30


mt = W.MemTrack(types.SimpleNamespace(cuda=_Cuda))
mt.update('a')
_Cuda.peak[0], _Cuda.free[0] = 9 * 2 ** 30, 12 * 2 ** 30
mt.update('b')
_Cuda.peak[0], _Cuda.free[0] = 3 * 2 ** 30, 25 * 2 ** 30                 # счётчик torch сбросили (смена фазы) — максимум остаётся
mt.update()
s = mt.summary()
ok(s['peak_allocated_gb'] == 9.0 and s['peak_reserved_gb'] == 10.0 and s['min_driver_free_gb'] == 12.0 and [m[0] for m in s['marks']] == ['a', 'b'],
   'пики копятся за задание и переживают сброс счётчика при смене фазы; свободное по драйверу — минимум')
res_t = W.Residency(_M(), _M(), _M(), 'cuda', types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True, max_memory_allocated=lambda: 7 * 2 ** 30,
                                                                                          reset_peak_memory_stats=lambda: None, empty_cache=lambda: None, synchronize=lambda: None)))
tr = []
res_t.track = types.SimpleNamespace(update=lambda tag=None: tr.append(1))
res_t.use('dit')
res_t.use('te')
ok(len(tr) == 2 and res_t.phases.get('start') == 7.0, 'смена фазы перед сбросом счётчика отдаёт пик в общий учёт')

# ---- диагностика слива VRAM на подмене torch
GIB = 2 ** 30


def fake_torch(total_gb, oom_after=None):
    state = {'n': 0}

    def empty(n, dtype=None, device=None):
        if oom_after is not None and state['n'] >= oom_after:
            raise RuntimeError('CUDA out of memory. Tried to allocate 1.00 GiB')
        state['n'] += 1
        return types.SimpleNamespace(fill_=lambda v: None)

    cuda = types.SimpleNamespace(mem_get_info=lambda: (total_gb * GIB - GIB, total_gb * GIB), synchronize=lambda: None, empty_cache=lambda: None)
    return types.SimpleNamespace(cuda=cuda, empty=empty, uint8=None, empty_cache=lambda: None)


d = W.diag_spill(fake_torch(32, oom_after=31), 4.0)
ok(d['allocated_gb'] == 31 and d['beyond_physical'] is False and 'out of memory' in d['error'], 'слив: упало громко на 31 ГиБ — тихого слива нет')
d = W.diag_spill(fake_torch(32), 4.0)
ok(d['allocated_gb'] == 36 and d['beyond_physical'] is True and d['error'] == '', 'слив: выделилось 36 ГиБ на карте 32 — драйвер тихо сливает в системную память')

# ---- затвор диагностики перед весами (ULTRATEX_DIAG_FIRST=1): зелёно/красное по итогам прогона на случайных весах
green = {'sparse_real': [{'length': 71000, 'first_s': 20.0}], 'dit': [{'length': 71000, 'error': '', 'peak_allocated_gb': 27.4}]}
ok(W.diag_gate_verdict(green) == '', 'затвор: ядро ок, DiT 27,4 ГБ < 30 — зелёно')
ok('ядро' in W.diag_gate_verdict({'sparse_real': [{'length': 71000, 'error': 'cannot create program'}], 'dit': green['dit']}), 'затвор: ядро упало → красное')
ok('не проверено' in W.diag_gate_verdict({'sparse_real': [], 'dit': green['dit']}), 'затвор: ядро не проверено → красное (молчание не зелёное)')
ok('DiT' in W.diag_gate_verdict({'sparse_real': green['sparse_real'], 'dit': [{'length': 71000, 'error': 'OutOfMemoryError: CUDA out of memory', 'peak_allocated_gb': 31}]}), 'затвор: OOM в DiT → красное')
ok('не помещается' in W.diag_gate_verdict({'sparse_real': green['sparse_real'], 'dit': [{'length': 71000, 'error': '', 'peak_allocated_gb': 30.5}]}), 'затвор: пик 30,5 ГБ ≥ 30 → красное')
ok('не выполнен' in W.diag_gate_verdict({'sparse_real': green['sparse_real'], 'dit': []}), 'затвор: DiT не запускался → красное')

# порядок стадий в main(): при ULTRATEX_DIAG_FIRST=1 затвор — ПЕРЕД докачкой весов; без флага стадий две
_stages = {}


class _KW:
    @staticmethod
    def serve(handler, state, wd, stop, stages, log=None):
        _stages['s'] = [n for n, _ in stages]
        return 0


_kw_orig, _env_orig = W.KW, dict(os.environ)
W.KW = _KW
try:
    os.environ.pop('ULTRATEX_NO_WEIGHTS', None)
    os.environ.pop('ULTRATEX_DIAG_FIRST', None)
    W.main()
    ok(_stages['s'] == ['weights', 'loading'], 'стадии без затвора: weights → loading')
    os.environ['ULTRATEX_DIAG_FIRST'] = '1'
    W.main()
    ok(_stages['s'] == ['diag', 'weights', 'loading'], 'стадии с затвором: diag → weights → loading (красное гасит до докачки 35 ГБ)')
finally:
    W.KW = _kw_orig
    os.environ.clear()
    os.environ.update(_env_orig)

# сам затвор целиком (k1 21.11: зелёный итог, но `log(...)` вместо `log.info` уронил воркер ПОСЛЕ вердикта — путь после вердикта не был покрыт)
class _GateEngine:
    offload = sparse = None
    ready = False
    gate = None

    def load_diag(self):
        self.offload, self.sparse, self.ready = 'diag', {}, True

    def on_step(self, name):
        pass


_run_diag_keep = W.run_diag


def _gate_run(engine, p, sink=None):
    assert p['spill_over_gb'] == 0 and p['runs'] == ['b1_chunk'], 'затвор: без слива, один прогон DiT с кусками'
    sink.update(green)
    return sink


W.run_diag = _gate_run
ge = _GateEngine()
try:
    W.diag_gate(ge)
    ok(ge.gate['verdict'] == 'green' and ge.ready is False and ge.offload is None, 'diag_gate: зелёный путь доходит до конца без исключений, движок сброшен под настоящую загрузку')
    W.run_diag = lambda engine, p, sink=None: sink.update({'sparse_real': [{'length': 71000, 'error': 'boom'}]}) or sink
    ge2 = _GateEngine()
    try:
        W.diag_gate(ge2)
        ok(False, 'diag_gate: красное должно поднять RuntimeError')
    except RuntimeError as exc:
        ok('затвор диагностики красный' in str(exc) and ge2.gate['verdict'].startswith('ядро'), 'diag_gate: красное → RuntimeError с причиной, итог в engine.gate (виден в /health)')
finally:
    W.run_diag = _run_diag_keep

# ---- /diag по HTTP: только в режиме без весов
class _DiagEngine:
    offload = 'diag'
    sparse = {}
    mem = None

    def __init__(self):
        self.on_step = lambda n: None


W_run_diag = W.run_diag
def _fake_run_diag(engine, p, sink=None):
    sink = sink if sink is not None else {}
    sink.update({'ok': True, 'asked': p.get('lengths')})
    if p.get('boom'):                                          # часть упала после того, как первая уже записала результат
        raise RuntimeError('assert allocator')
    return sink


W.run_diag = _fake_run_diag
state, stop = W.State(), threading.Event()
state.phase = 'ready'
eng = _DiagEngine()
srv = ThreadingHTTPServer(('127.0.0.1', 0), W.make_handler(state, eng, W.Watchdog(1e9, 1e9), stop))
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{srv.server_address[1]}'


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as rr:
            return rr.status, json.loads(rr.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


c, rr = call('POST', '/diag', {'job_id': 'd1', 'lengths': [1000]})
ok(c == 202, '/diag в режиме без весов принят')
for _ in range(100):
    c, rr = call('GET', '/result/d1')
    if rr.get('status') != 'running':
        break
    threading.Event().wait(0.05)
ok(rr.get('status') == 'done' and rr['metrics'] == {'ok': True, 'asked': [1000]} and state.busy is False, '/diag: готово, метрики отданы, карта свободна')
c, rr = call('POST', '/diag', {'job_id': 'd3', 'lengths': [5], 'boom': True})
for _ in range(100):
    c, rr = call('GET', '/result/d3')
    if rr.get('status') != 'running':
        break
    threading.Event().wait(0.05)
ok(rr.get('status') == 'failed' and rr.get('metrics', {}).get('asked') == [5] and 'allocator' in rr.get('error', ''), '/diag: при сбое части в ответе остаются результаты прошедших частей (d1 21.11)')
eng.offload = 'swap'
c, rr = call('POST', '/diag', {'job_id': 'd2'})
ok(c == 403, '/diag при живой модели (не режим без весов) — отказ 403')
srv.shutdown()
W.run_diag = W_run_diag

# ---- куски по токенам на НАСТОЯЩИХ блоках авторов (CPU, float32): результат тот же, куски действительно дробят вход
UT = os.environ.get('ULTRATEX_DIR', '/opt/UltraTex')
if os.path.isdir(os.path.join(UT, 'ultratex')):
    sys.path.insert(0, UT)
    from ultratex.backbones.flux2 import model as M              # noqa: E402

    P = M.Flux2Params(in_channels=16, context_in_dim=24, hidden_size=64, num_heads=2, depth=2, depth_single_blocks=2, axes_dim=[8, 8, 8, 8], theta=2000, mlp_ratio=3.0,
                      use_guidance_embed=False)
    torch.manual_seed(0)
    dit_real = M.Flux2(P).eval()
    L, T = 30, 5
    xs = torch.randn(1, L, 16).repeat(2, 1, 1)
    ids = torch.stack([torch.zeros(L, dtype=torch.long), torch.arange(L) // 6, torch.arange(L) % 6, torch.zeros(L, dtype=torch.long)], -1)[None].repeat(2, 1, 1)
    ctx = torch.randn(1, T, 24).repeat(2, 1, 1)
    cids = torch.stack([torch.zeros(T, dtype=torch.long)] * 3 + [torch.arange(T)], -1)[None].repeat(2, 1, 1)
    tt = torch.full((2,), 0.5)

    def fwd(model, **over):
        kw = dict(x=xs, x_ids=ids, timesteps=tt, ctx=ctx, ctx_ids=cids, guidance=None)
        kw.update(over)
        with torch.no_grad():
            return model(**kw)

    ref = fwd(dit_real)
    seen = {'lin1': 0, 'rope': 0}
    done = W.apply_memory_patches(M, dit_real, 7)
    ok(done == {'single': 2, 'double': 2, 'chunk': 7}, 'найдены и подменены все блоки: 2 одиночных, 2 двойных')
    big = []
    for blk in dit_real.single_blocks:
        blk.linear1.register_forward_hook(lambda m, i, o: big.append(i[0].shape[1]))
    for blk in dit_real.double_blocks:
        blk.img_mlp[0].register_forward_hook(lambda m, i, o: big.append(i[0].shape[1]))
    out = fwd(dit_real)
    ok(torch.allclose(out, ref, atol=1e-5, rtol=1e-5), f'куски по 7 токенов: результат DiT тот же (макс. расхождение {float((out - ref).abs().max()):.2e})')
    ok(big and max(big) <= 7 and len(big) > 4, f'MLP реально считается кусками ≤7 токенов (вызовов {len(big)}, самый большой вход {max(big)})')
    out_odd = fwd(dit_real, x=xs[:, :29], x_ids=ids[:, :29])
    ref_odd = None
    W.apply_memory_patches(M, dit_real, 0)
    ref_odd = fwd(dit_real, x=xs[:, :29], x_ids=ids[:, :29])
    ok(torch.allclose(out_odd, ref_odd, atol=1e-5, rtol=1e-5), 'длина не кратна куску (29 при куске 7): тот же результат')
    out_off = fwd(dit_real)
    ok(torch.equal(out_off, ref), 'chunk=0: подмены сняты, результат побитно прежний')
    ok(not any(k in blk.__dict__ for blk in dit_real.single_blocks for k in ('_qkv', '_out')), 'chunk=0: методы блоков вернулись к авторским')

    # одна ветка поверх кусков на настоящей модели: равные ветки == обычный batch=2; разные — обычный путь
    W.apply_memory_patches(M, dit_real, 5)
    cdr = W.CfgDedup(dit_real, 'auto', None, None)
    kw = dict(x=xs, x_ids=ids, timesteps=tt, ctx=ctx, ctx_ids=cids, guidance=None)
    with torch.no_grad():
        o1 = cdr(**kw)
    ok(cdr.stats['single'] == 1 and torch.allclose(o1, ref, atol=1e-5, rtol=1e-5), 'настоящий DiT: одна ветка + куски = результат обычного batch=2')
    ctx2 = ctx.clone()
    ctx2[1] += 0.5
    with torch.no_grad():
        o2 = cdr(**dict(kw, ctx=ctx2))
    with torch.no_grad():
        r2 = dit_real(**dict(kw, ctx=ctx2))
    ok(cdr.stats['batched'] == 1 and torch.allclose(o2, r2, atol=1e-5, rtol=1e-5) and not torch.allclose(o2[0], o2[1]), 'разные тексты: обычный путь, ветки действительно различаются')
    W.apply_memory_patches(M, dit_real, 0)
else:
    print('(код авторов не найден — разделы на настоящих блоках пропущены; в образе он есть)')

# ---- пустой текст из файла вместо Qwen3-8B (образ без Qwen)
import hashlib                                                  # noqa: E402
import tempfile                                                 # noqa: E402

with tempfile.TemporaryDirectory() as td:
    pt = os.path.join(td, 'empty.pt')
    good = torch.randn(*W.TEXT_CACHE_SHAPE).to(torch.bfloat16)
    torch.save(good, pt)
    sha = hashlib.sha256(good.contiguous().view(torch.int16).numpy().tobytes()).hexdigest()
    json.dump({'shape': list(good.shape), 'sha256': sha}, open(os.path.join(td, 'empty.json'), 'w'))
    old_env = os.environ.get(W.TEXT_CACHE_ENV)
    os.environ[W.TEXT_CACHE_ENV] = pt
    names = [w['name'] for w in W.plan_weights('/r')]
    ok(W.text_cache_path() == pt and 'qwen3_8b' not in names and 'flux2_klein_base_9b' in names, 'режим кэша: Qwen3-8B вычеркнут из весов, DiT и AE остались')
    t = W.load_text_cache(pt)
    ok(torch.equal(t, good), 'кэш читается без искажений (bf16, проверка sha256)')
    enc = W.make_empty_text_encoder(t)
    o = enc([''])
    ok(tuple(o.shape) == W.TEXT_CACHE_SHAPE and torch.equal(o, good), 'пустая подпись → сохранённый тензор')
    o2 = enc(['', ''])
    ok(tuple(o2.shape) == (2, 512, 12288) and torch.equal(o2[1], good[0]), 'пустых подписей несколько → размножено по batch')
    o[...] = 0
    ok(torch.equal(enc(['']), good), 'выдача — копия: правка снаружи не портит кэш')
    for bad in (['стол'], ['', 'x'], [], 'text'):
        try:
            enc(bad)
            ok(False, f'непустая подпись {bad!r} должна падать')
        except RuntimeError as e:
            ok('без Qwen3-8B' in str(e), f'непустая подпись {bad!r} → громкая ошибка')
    tc = W.TextCache(enc)
    tc(['']); tc([''])
    ok((tc.hits, tc.misses) == (1, 1), 'TextCache поверх кэш-энкодера: hits 1 / misses 1')
    # порча файла
    torch.save(good + 1, os.path.join(td, 'broken.pt'))
    json.dump({'shape': list(good.shape), 'sha256': sha}, open(os.path.join(td, 'broken.json'), 'w'))
    try:
        W.load_text_cache(os.path.join(td, 'broken.pt'))
        ok(False, 'испорченный файл должен падать')
    except RuntimeError as e:
        ok('sha256' in str(e), 'испорченный файл (sha256 не совпал) → ошибка')
    torch.save(torch.zeros(1, 4, 8).to(torch.bfloat16), os.path.join(td, 'shape.pt'))
    json.dump({'shape': [1, 4, 8], 'sha256': 'x'}, open(os.path.join(td, 'shape.json'), 'w'))
    try:
        W.load_text_cache(os.path.join(td, 'shape.pt'))
        ok(False, 'чужая форма должна падать')
    except RuntimeError as e:
        ok('форма' in str(e), 'чужая форма → ошибка')
    del os.environ[W.TEXT_CACHE_ENV]
    ok(W.text_cache_path() == '' and 'qwen3_8b' in [w['name'] for w in W.plan_weights('/r')], 'без переменной: прежний режим, Qwen в списке весов')
    os.environ[W.TEXT_CACHE_ENV] = os.path.join(td, 'нет.pt')
    ok(W.text_cache_path() == '' and 'qwen3_8b' in [w['name'] for w in W.plan_weights('/r')], 'путь есть, файла нет → прежний режим (не молчаливое «без Qwen»)')
    if old_env is None:
        os.environ.pop(W.TEXT_CACHE_ENV, None)
    else:
        os.environ[W.TEXT_CACHE_ENV] = old_env

# ---- веса, запечённые кусками: список весов и загрузчик
from safetensors.torch import save_file                         # noqa: E402

with tempfile.TemporaryDirectory() as td:
    base = os.path.join(td, 'base', 'flux2')
    os.makedirs(base)
    dit = os.path.join(base, 'flux-2-klein-base-9b.safetensors')
    sd = {'x.w': torch.randn(40, 8).to(torch.bfloat16), 'y.w': torch.randn(30, 8).to(torch.bfloat16)}
    save_file(sd, dit)
    plan0 = {w['name']: w for w in W.plan_weights(td)}
    ok(plan0['flux2_klein_base_9b']['src'] == 'hf' and plan0['flux2_klein_base_9b']['dest'] == dit, 'без кусков: DiT берётся одним файлом с HF, как раньше')

    class _Src:                                                 # источник Range из локального файла
        def read(self, a, b):
            with open(dit, 'rb') as f:
                f.seek(a)
                yield f.read(b - a)

        def read_all(self, a, b):
            return b''.join(self.read(a, b))
    W.WP.shard_step(_Src(), dit + '.shards', 0, 1 << 30)
    plan1 = {w['name']: w for w in W.plan_weights(td)}
    w1 = plan1['flux2_klein_base_9b']
    ok(w1['src'] == 'sharded' and w1['dest'] == dit + '.shards' and W._present(w1), 'есть каталог кусков: DiT = sharded, считается «есть» (докачки с HF нет)')
    ok(W.weights_env(td)['KLEIN_9B_BASE_MODEL_PATH'] == dit + '.shards', 'KLEIN_9B_BASE_MODEL_PATH указывает на каталог кусков')
    done = W.fetch_weights(td, '', lambda *a: None) if False else None
    # фальшивый util кода авторов: install_sharded_loader подменяет load_sft только для каталогов кусков
    calls = []
    fake_util = types.ModuleType('ultratex.backbones.flux2.util')
    fake_util.load_sft = lambda p, device='cpu': calls.append(p) or {'orig': torch.zeros(1)}
    saved = {k: sys.modules.get(k) for k in ('ultratex', 'ultratex.backbones', 'ultratex.backbones.flux2', 'ultratex.backbones.flux2.util')}
    for k in saved:
        sys.modules[k] = types.ModuleType(k)
    sys.modules['ultratex.backbones.flux2'].util = fake_util
    sys.modules['ultratex.backbones.flux2.util'] = fake_util
    ok(W.install_sharded_loader() is True and W.install_sharded_loader() is False, 'загрузчик ставится один раз (повтор — no-op)')
    got = fake_util.load_sft(dit + '.shards', device='cpu')
    ok(set(got) == set(sd) and all(torch.equal(got[k], sd[k]) for k in sd) and not calls, 'каталог кусков → словарь тензоров из кусков, прежний load_sft не вызван')
    got2 = fake_util.load_sft(dit, device='cpu')
    ok(calls == [dit] and 'orig' in got2, 'обычный файл → прежний load_sft авторов')
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

# ---- bake_weights.py check: образ «веса внутрь, без Qwen» целиком на временной папке
import subprocess                                               # noqa: E402

with tempfile.TemporaryDirectory() as td:
    root = os.path.join(td, 'w')
    b = os.path.join(root, 'base', 'flux2')
    os.makedirs(os.path.join(root, 'checkpoints', 'flux2', 'lora'))
    open(os.path.join(root, 'checkpoints', 'flux2', 'lora', 'dit_lora.safetensors'), 'wb').write(b'x')
    open(os.path.join(root, 'checkpoints', 'flux2', 'decoder.pt'), 'wb').write(b'x')
    for fname, tensors in (('flux-2-klein-base-9b.safetensors', {'a': torch.randn(8, 8).to(torch.bfloat16)}), ('ae.safetensors', {'e': torch.randn(4, 4)})):
        os.makedirs(b, exist_ok=True)
        save_file(tensors, os.path.join(b, fname))
        class _S:                                               # noqa: E301
            def __init__(self, p):
                self.p = p

            def read(self, a, z):
                with open(self.p, 'rb') as f:
                    f.seek(a)
                    yield f.read(z - a)

            def read_all(self, a, z):
                return b''.join(self.read(a, z))
        W.WP.shard_step(_S(os.path.join(b, fname)), os.path.join(b, fname) + '.shards', 0, 1 << 30)
        os.remove(os.path.join(b, fname))                       # как в образе: одного файла нет, есть только куски
    tdir = os.path.join(td, 'tc')
    os.makedirs(tdir)
    good = torch.randn(*W.TEXT_CACHE_SHAPE).to(torch.bfloat16)
    torch.save(good, os.path.join(tdir, 'e.pt'))
    json.dump({'shape': list(good.shape), 'sha256': hashlib.sha256(good.contiguous().view(torch.int16).numpy().tobytes()).hexdigest()}, open(os.path.join(tdir, 'e.json'), 'w'))
    env = dict(os.environ, ULTRATEX_ROOT=root, ULTRATEX_TEXT_CACHE=os.path.join(tdir, 'e.pt'))
    r = subprocess.run([sys.executable, os.path.join(HERE, 'bake_weights.py'), 'check'], env=env, capture_output=True, text=True)
    ok(r.returncode == 0 and 'пустой текст' in r.stdout, f'bake_weights check: образ «веса внутрь, без Qwen» принят (rc={r.returncode})')
    env2 = {k: v for k, v in env.items() if k != 'ULTRATEX_TEXT_CACHE'}
    r2 = subprocess.run([sys.executable, os.path.join(HERE, 'bake_weights.py'), 'check'], env=env2, capture_output=True, text=True)
    ok(r2.returncode == 2 and 'Qwen3-8B в списке' in r2.stdout, 'без кэша пустого текста: check красный (Qwen в списке весов)')
    os.remove(os.path.join(b, 'ae.safetensors.shards', 'shard-00.safetensors'))
    r3 = subprocess.run([sys.executable, os.path.join(HERE, 'bake_weights.py'), 'check'], env=env, capture_output=True, text=True)
    ok(r3.returncode != 0, 'нет куска AE: check красный')

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПРОВАЛОВ: {len(FAILS)}')
sys.exit(1 if FAILS else 0)
