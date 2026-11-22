#!/usr/bin/env python3
"""ВОРКЕР ПРОБЫ UltraTex (вариант 8, T-20261119-90/2): «готовая форма (GLB) + ОДНО фото (RGBA) → GLB с альбедо-текстурой».
Едет в образе `Dockerfile.ultratex` на под RunPod (карта 80 ГБ: A100 sm_80 / H100 sm_90). Один GPU — одно задание за раз.

ЧТО ДЕЛАЕТ (всё — наша сборка из трёх чужих MIT-частей, см. ultratex_core/NOTICE.md):
  1. `ultratex_core.prep` (из ComfyUI-UltraTex, MIT): нормирует форму, берёт её развёртку (или xatlas), рендерит 6 канонических видов карт нормалей
     (moderngl/EGL), подгоняет фото к фронтальному виду;
  2. код АВТОРОВ UltraTex (`train_flux2.inference`, MIT; база FLUX.2-klein-base-9B + LoRA UltraTex 9B + декодер) рисует 6 видов альбедо 2×3 по нормалям и фото;
  3. `ultratex_core.bake` (из ComfyUI-UltraTex, MIT) запекает 6 видов в UV 4096² → GLB.
Форма НЕ меняется (оптимизируется только текстура; грани и их число — в метриках), ключ — только в окружении пода, не в образе.

HTTP (порт $PORT, по умолчанию 8000; на RunPod — через прокси `https://<pod>-8000.proxy.runpod.net`):
  GET  /health                 → {"phase": weights|loading|ready|busy|broken, ...} (прогрев весов и модели — минуты; ход — в `weights`)
  POST /generate               {"job_id","image_b64"(RGBA PNG),"glb_b64","resolution"(1024|2048),"steps","guidance","seed","texture_size"} → 202
  GET  /result/<job_id>        → {"status": running|done|failed, "metrics": {...}, "error": "..."}
  GET  /result/<job_id>/glb    → байты GLB (только при done)
  POST /shutdown               → процесс завершается (под RunPod после выхода контейнера — «exited», счёт за GPU прекращается)
АВТОСТОП ПОДА: выход процесса при MAX_LIFETIME_S (по умолчанию 5400 с = 90 мин от старта) ИЛИ IDLE_S без заданий после готовности (по умолчанию 900 с);
драйвер всё равно удаляет под сам и проверяет, что его нет в списке.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import sys
import threading
import time
import traceback
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import kit_worker as KW                                    # на Salad модуль набора зарегистрирован в sys.modules (KW.bundle)
except ImportError:                                            # локально (тесты, разбор): набор лежит в tools/scout/salad
    sys.path.insert(0, os.path.join(HERE, '..', '..', 'salad'))
    import kit_worker as KW

try:
    import weights_pack as WP                                  # куски весов образа (рядом с воркером)
except ImportError:
    sys.path.insert(0, os.path.join(HERE, '..', 'runpod', 'ultratex'))
    import weights_pack as WP

log = logging.getLogger('ultratex-worker')

VERSION = 'ultratex-worker-2'
ULTRATEX_COMMIT = 'a726678f3f3631fe2c5e3d1fb4597114784c7a8b'     # код авторов (MIT), клонируется в образ
GRID_ORDER = [[0, 1, 3], [2, 4, 5]]                              # раскладка 2×3 как у авторов (render.GRID_ORDER)
RESOLUTIONS = (1024, 2048)                                       # разрешение вида; LoRA обучена на 2048 (FLUX.2-ветка)
DEFAULTS = {'resolution': 2048, 'steps': 25, 'guidance': 4.0, 'seed': 42, 'texture_size': 4096}
MAX_GLB_BYTES = 120 * 2 ** 20
MAX_IMAGE_BYTES = 30 * 2 ** 20


# ---------------------------------------------------------------- веса: что и откуда
def plan_weights(root: str) -> list[dict]:
    """Список весов: куда кладём и откуда берём. Ничего не качает. `gated` — закрытые репозитории HF (нужен токен С ПРИНЯТЫМИ условиями)."""
    base = os.path.join(root, 'base', 'flux2')
    plan = _plan_weights_full(base, root)
    if text_cache_path():                                        # пустой текст из файла образа — Qwen3-8B (16,4 ГБ) не нужен ни в образе, ни на диске ноды
        plan = [w for w in plan if w['name'] != 'qwen3_8b']
    for w in plan:                                               # веса, запечённые в образ кусками (weights_pack.py): `<файл>.shards/` — каталог кусков вместо одного файла
        if w['src'] != 'hf_dir' and WP.is_sharded_dir(w['dest'] + '.shards'):
            w['dest'], w['src'] = w['dest'] + '.shards', 'sharded'
    return plan


def _plan_weights_full(base: str, root: str) -> list[dict]:
    return [
        {'name': 'ultratex_lora', 'src': 'modelscope', 'repo': 'Yibo-Zhang/UltraTex', 'file': 'flux2/lora/dit_lora.safetensors',
         'dest': os.path.join(root, 'checkpoints', 'flux2', 'lora', 'dit_lora.safetensors'), 'gated': False, 'approx_gb': 0.46},
        {'name': 'ultratex_decoder', 'src': 'modelscope', 'repo': 'Yibo-Zhang/UltraTex', 'file': 'flux2/decoder.pt',
         'dest': os.path.join(root, 'checkpoints', 'flux2', 'decoder.pt'), 'gated': False, 'approx_gb': 0.1},
        {'name': 'flux2_klein_base_9b', 'src': 'hf', 'repo': 'black-forest-labs/FLUX.2-klein-base-9B', 'file': 'flux-2-klein-base-9b.safetensors',
         'dest': os.path.join(base, 'flux-2-klein-base-9b.safetensors'), 'gated': True, 'approx_gb': 18.0, 'env': 'KLEIN_9B_BASE_MODEL_PATH'},
        {'name': 'flux2_ae', 'src': 'hf', 'repo': 'black-forest-labs/FLUX.2-dev', 'file': 'ae.safetensors',
         'dest': os.path.join(base, 'ae.safetensors'), 'gated': True, 'approx_gb': 0.34, 'env': 'AE_MODEL_PATH'},
        {'name': 'qwen3_8b', 'src': 'hf_dir', 'repo': 'Qwen/Qwen3-8B', 'file': '',
         'dest': os.path.join(base, 'qwen3-8b'), 'gated': False, 'approx_gb': 16.4, 'env': 'QWEN3_8B_PATH'},
    ]


def weights_env(root: str) -> dict:
    """Переменные окружения, по которым код авторов находит веса (без скачивания)."""
    return {w['env']: w['dest'] for w in plan_weights(root) if w.get('env')}


class WeightsDenied(RuntimeError):
    """Закрытый репозиторий не пускает токен (403/401): условия лицензии не приняты или токена нет."""
    code = 'WEIGHTS_DENIED'                                    # kit_worker.run_warm пишет в /health error «WEIGHTS_DENIED: …»


def _present(w: dict) -> bool:
    if w['src'] == 'sharded':                                    # куски целы по размерам и манифесту (sha256 проверяет сборка образа; здесь — быстро, без чтения 18 ГБ)
        WP.verify_dir(w['dest'], deep=False)
        return True
    if w['src'] == 'hf_dir':
        return os.path.isfile(os.path.join(w['dest'], 'config.json')) and os.path.isfile(os.path.join(w['dest'], '.complete'))
    return os.path.isfile(w['dest']) and os.path.getsize(w['dest']) > 0


def fetch_weights(root: str, hf_token: str, progress=None, only=None) -> dict:
    """Докачка недостающего (идемпотентно). progress(name, state) — для /health. Закрытое без допуска → WeightsDenied с именем репозитория.
    `only` — набор имён весов (сборка образа берёт малые файлы отдельным слоем: bake_weights.py small)."""
    progress = progress or (lambda name, state: None)
    done = {}
    for w in plan_weights(root):
        if only is not None and w['name'] not in only:
            continue
        if _present(w):
            progress(w['name'], 'есть')
            done[w['name']] = 'есть'
            continue
        progress(w['name'], f"качаю ~{w['approx_gb']} ГБ")
        os.makedirs(os.path.dirname(w['dest']) if w['src'] != 'hf_dir' else w['dest'], exist_ok=True)
        try:
            if w['src'] == 'modelscope':
                from modelscope import snapshot_download      # noqa: WPS433 (в образе)
                tmp = snapshot_download(w['repo'], allow_patterns=[w['file']], local_dir=os.path.join(root, '_ms'))
                os.replace(os.path.join(tmp, w['file']), w['dest'])
            elif w['src'] == 'hf':
                from huggingface_hub import hf_hub_download
                p = hf_hub_download(w['repo'], w['file'], token=hf_token or None, local_dir=os.path.join(root, '_hf', w['name']))
                os.replace(p, w['dest'])
            else:
                from huggingface_hub import snapshot_download as hf_snap
                hf_snap(w['repo'], token=hf_token or None, local_dir=w['dest'], allow_patterns=['*.json', '*.safetensors', '*.txt', 'merges.txt', 'vocab.json'])
                open(os.path.join(w['dest'], '.complete'), 'w').close()
        except Exception as exc:                               # noqa: BLE001
            msg = str(exc)
            if w['gated'] and any(t in msg for t in ('401', '403', 'gated', 'GatedRepo', 'restricted', 'Access to model')):
                raise WeightsDenied(f"нет допуска к {w['repo']} (условия лицензии не приняты в аккаунте токена или токен не передан): {msg[:200]}") from exc
            raise
        progress(w['name'], 'готово')
        done[w['name']] = 'готово'
    return done


# ---------------------------------------------------------------- вход сети: чистая арифметика
def _resize_rgba(rgba: np.ndarray, size: int):
    from PIL import Image
    return Image.fromarray(rgba).resize((size, size), Image.Resampling.BILINEAR)


def _on_white(img) -> np.ndarray:
    from PIL import Image
    bg = Image.new('RGB', img.size, (255, 255, 255))
    bg.paste(img, mask=img.getchannel('A'))
    return np.asarray(bg)


def _small_mask(rgba: np.ndarray, size: int) -> np.ndarray:
    """alpha > 0 на разрешении токенов (R/16), раздутая как cv2.dilate(ones(2,2)) у авторов."""
    m = np.asarray(_resize_rgba(rgba, size).getchannel('A')) > 0
    d = m.copy()
    d[1:] |= m[:-1]
    d[:, 1:] |= m[:, :-1]
    d[1:, 1:] |= m[:-1, :-1]
    return d


def grid(tiles) -> np.ndarray:
    """6 плиток (view-порядок 0..5) → холст 2×3: строка 1 = виды 0,1,3; строка 2 = 2,4,5 (как у TexVerse)."""
    return np.concatenate([np.concatenate([tiles[v] for v in row], axis=1) for row in GRID_ORDER], axis=0)


def tiles_from_grid(img: np.ndarray, res: int) -> np.ndarray:
    """Холст 2R×3R → (6, R, R, C) в порядке видов (обратно к `grid`)."""
    out = np.zeros((6,) + (res, res) + img.shape[2:], dtype=img.dtype)
    for r, row in enumerate(GRID_ORDER):
        for c, v in enumerate(row):
            out[v] = img[r * res:(r + 1) * res, c * res:(c + 1) * res]
    return out


def build_conditions(normal_rgba: np.ndarray, reference_rgba: np.ndarray, res: int) -> dict:
    """Картинки и маски, как их собирает датасет авторов (альфа цели = альфа нормалей). normal_rgba: (6,S,S,4) uint8; reference_rgba: (S,S,4)."""
    s = res // 16
    normal_tiles, small, full = [], [], []
    for v in range(6):
        big = _resize_rgba(normal_rgba[v], res)
        normal_tiles.append(_on_white(big))
        full.append(np.asarray(big.getchannel('A')) > 0)
        small.append(_small_mask(normal_rgba[v], s))
    return {
        'normal_grid': grid(normal_tiles),                       # (2R, 3R, 3) uint8
        'reference': _on_white(_resize_rgba(reference_rgba, res)),   # (R, R, 3) uint8
        'mask_target': grid(small).astype(bool),                 # (2s, 3s)
        'mask_normals': grid(small).astype(bool),
        'mask_reference': _small_mask(reference_rgba, s).astype(bool),   # (s, s)
        'mask_full_grid': grid(full).astype(bool),               # (2R, 3R)
    }


def validate_job(body: dict) -> tuple[dict, str | None]:
    """Разбор задания: (параметры с умолчаниями, текст ошибки). Размер/формат — до всякой работы."""
    if not isinstance(body, dict):
        return {}, 'тело задания — не объект'
    for k in ('job_id', 'image_b64', 'glb_b64'):
        if not body.get(k):
            return {}, f'нет поля {k}'
    p = dict(DEFAULTS)
    for k in DEFAULTS:
        if body.get(k) is not None:
            p[k] = body[k]
    try:
        p['resolution'], p['steps'], p['seed'], p['texture_size'] = int(p['resolution']), int(p['steps']), int(p['seed']), int(p['texture_size'])
        p['guidance'] = float(p['guidance'])
    except (TypeError, ValueError):
        return {}, 'resolution/steps/seed/texture_size — целые, guidance — число'
    if p['resolution'] not in RESOLUTIONS:
        return {}, f'resolution должен быть из {RESOLUTIONS}'
    if not 1 <= p['steps'] <= 60:
        return {}, 'steps вне 1..60'
    if not 512 <= p['texture_size'] <= 8192 or p['texture_size'] % 512:
        return {}, 'texture_size — кратно 512, 512..8192'
    p['job_id'] = str(body['job_id'])
    if not p['job_id'].replace('-', '').replace('_', '').replace('.', '').replace(':', '').isalnum() or len(p['job_id']) > 160:
        return {}, 'job_id: буквы, цифры и - _ . :, до 160 знаков'
    return p, None


# ---------------------------------------------------------------- автостоп
Watchdog = KW.Watchdog                                          # автостоп — общий набор Salad (kit_worker)


# ---------------------------------------------------------------- выгрузка по очереди (карта 32 ГБ вместо 80, T-178/1)
class Residency:
    """Кто сейчас на карте: DiT (18 ГБ), текстовый энкодер Qwen3-8B (16 ГБ) или никто; VAE (0,4 ГБ) живёт на карте всегда.
    Порядок задания у авторов: VAE-кодирование → текстовый энкодер (2 вызова) → шаги DiT → VAE-декод. Пока работает одно — второе лежит в обычной памяти.
    Модели и числа не меняются, только место. Фазовые пики VRAM пишутся в метрики (`phases`)."""

    def __init__(self, dit, te, ae, device, torch_mod=None, clock=time.time):
        self.mods = {'dit': dit, 'te': te}
        self.ae, self.device = ae, device
        self.on_gpu = {'dit': False, 'te': False}
        self.torch, self.clock = torch_mod, clock
        self.phases: dict = {}
        self.moves: list = []
        self.notes: list = []                                    # снимки памяти при OOM переноса, повтор удался (в метрики задания)
        self._phase = 'start'
        self.on_step = lambda name: None                         # ход задания в /health (kit_worker State.step): «te», «dit», «перенос dit→gpu 5с»
        self.labels: dict = {}                                   # подпись шага вместо имени фазы: {'dit': 'dit 7/25'} (ставит CfgDedup на каждом шаге DiT)
        self.track = None                                        # MemTrack: глобальные пики за задание (reset_peak по фазам иначе стирает их)

    def _cuda(self) -> bool:
        return bool(self.torch is not None and self.torch.cuda.is_available())

    def _close_phase(self, name: str) -> None:
        if self._cuda():
            if self.track is not None:
                self.track.update()
            peak = self.torch.cuda.max_memory_allocated() / 2 ** 30
            self.phases[self._phase] = max(self.phases.get(self._phase, 0.0), round(peak, 2))
            self.torch.cuda.reset_peak_memory_stats()
        self._phase = name

    def _tidy(self) -> None:
        """Перед переносом на карту: собрать мусор, дождаться ядер, вернуть драйверу кэш аллокатора. T-178/3 (22.11): контрольный Блест упал на переносе модуля при 15,7 ГиБ свободных —
        хвосты фазы VAE (6 видов 2048²) могли быть ещё живы, пауза фазы te (7+10 с) в режиме «пустой текст из файла» пропала."""
        import gc
        gc.collect()
        if self._cuda():
            self.torch.cuda.synchronize()
            self.torch.cuda.empty_cache()

    def _snap(self, name: str, exc: BaseException | None = None) -> dict:
        """Снимок памяти карты для ошибки/метрик: что выделено, что зарезервировано, сколько свободно по драйверу, сколько веса модуля уже на карте."""
        out: dict = {'module': name}
        try:
            cu = self.torch.cuda
            free, total = cu.mem_get_info()
            out.update(allocated_gb=round(cu.memory_allocated() / 2 ** 30, 2), reserved_gb=round(cu.memory_reserved() / 2 ** 30, 2),
                       driver_free_gb=round(free / 2 ** 30, 2), total_gb=round(total / 2 ** 30, 2))
            m = self.mods[name]
            out['module_on_gpu_gb'] = round(sum(p.numel() * p.element_size() for p in m.parameters() if p.is_cuda) / 2 ** 30, 2)
            out['module_total_gb'] = round(sum(p.numel() * p.element_size() for p in m.parameters()) / 2 ** 30, 2)
            out['alloc_conf'] = os.environ.get('PYTORCH_CUDA_ALLOC_CONF', '')
        except Exception as e:  # noqa: BLE001 — снимок не должен ронять разбор
            out['snapshot_error'] = f'{type(e).__name__}: {e}'
        if exc is not None:
            out['error'] = f'{type(exc).__name__}: {str(exc)[:160]}'
        return out

    def _move(self, name: str, to_gpu: bool) -> None:
        if self.on_gpu[name] == to_gpu:
            return
        t0 = self.clock()
        self.on_step(f'перенос {name}→{"gpu" if to_gpu else "cpu"}')
        dev = self.device if to_gpu else 'cpu'
        if to_gpu:
            self._tidy()
        try:
            self.mods[name].to(dev)
        except Exception as e:  # noqa: BLE001
            low = str(e).lower()
            if not (to_gpu and (type(e).__name__ == 'OutOfMemoryError' or ('out of memory' in low and 'cuda' in low))):
                raise
            first = self._snap(name, e)                              # снимок ДО очистки: что держало карту
            self._tidy()
            try:
                self.mods[name].to(dev)                              # один повтор: переносит только то, что ещё на cpu
            except Exception as e2:  # noqa: BLE001
                raise RuntimeError(f'перенос {name}→gpu: OOM и после очистки; снимок после ошибки {first}; снимок после очистки {self._snap(name, e2)}') from e2
            self.notes.append({'retry_after_oom': first, 'after_tidy': self._snap(name)})
        if not to_gpu and self._cuda():
            self.torch.cuda.empty_cache()
        self.on_gpu[name] = to_gpu
        self.moves.append((name, 'gpu' if to_gpu else 'cpu', round(self.clock() - t0, 2)))

    def use(self, name: str) -> None:
        """name = 'dit' | 'te' | 'ae' (VAE: ни DiT, ни энкодер на карте)."""
        self._close_phase(name)
        for other in ('dit', 'te'):
            if other != name:
                self._move(other, False)
        if name in self.mods:
            self._move(name, True)
        self.on_step(self.labels.get(name, name))                # после переносов: пока считает модель, в /health виден её шаг, а не последний перенос

    def release_all(self) -> None:
        for n in ('dit', 'te'):
            self._move(n, False)


class _Proxy:
    """Передаёт всё модулю, а при вызове сперва ставит его на карту."""

    def __init__(self, res: Residency, name: str):
        object.__setattr__(self, '_res', res)
        object.__setattr__(self, '_name', name)

    def __call__(self, *a, **k):
        self._res.use(self._name)
        return self._res.mods[self._name](*a, **k)

    def __getattr__(self, attr):
        return getattr(self._res.mods[self._name], attr)


class _AeProxy:
    """VAE: кодирование и декодирование — только когда ни DiT, ни энкодера на карте (иначе пик = 18 ГБ DiT + VAE-активации 2048²)."""

    def __init__(self, res: Residency):
        object.__setattr__(self, '_res', res)

    def encode(self, *a, **k):
        self._res.use('ae')
        return self._res.ae.encode(*a, **k)

    def decode(self, *a, **k):
        self._res.use('ae')
        return self._res.ae.decode(*a, **k)

    def __getattr__(self, attr):
        return getattr(self._res.ae, attr)


def wrap_offload(dit, te, ae, device, torch_mod=None):
    """→ (dit_proxy, ae_proxy, te_proxy, Residency). ae должен быть уже на карте."""
    res = Residency(dit, te, ae, device, torch_mod)
    return _Proxy(res, 'dit'), _AeProxy(res), _Proxy(res, 'te'), res


# ---------------------------------------------------------------- память карты 32 ГБ (T-178/1, 21.11): активации DiT, а не веса, не давали влезть
# Расчёт по коду авторов (80 ГБ, всё на карте, 2048, 6 видов): пик комода 62,2 ГБ при весах 35 → активации ≈ 27 ГБ на ≈70 тыс токенов, BATCH=2 из-за CFG.
# Здесь только то, что НЕ меняет результат: (1) вторая ветка CFG, когда она равна первой (пустой промпт — оба условия одинаковы); (2) пустой текст считается один раз
# за жизнь воркера; (3) позиционные операции (MLP, RoPE, RMSNorm q/k) — кусками по токенам; (4) честные пики. Все 6 видов по-прежнему в ОДНОМ проходе DiT.
MEM_CHUNK = 4096                                                 # токенов в куске; 0 — выключено (прежнее поведение)


def _chunks(n: int, size: int):
    for s in range(0, n, size):
        yield s, min(s + size, n)


class TextCache:
    """Текстовый энкодер с памятью: одинаковый список подписей считается один раз (пустая подпись `''` — у каждого задания воркера), результат ≈12 МБ.
    Со второго задания Qwen3-8B (16 ГБ) на карту не возвращается вовсе."""

    def __init__(self, te, on_step=None):
        object.__setattr__(self, '_te', te)
        object.__setattr__(self, '_cache', {})
        object.__setattr__(self, 'hits', 0)
        object.__setattr__(self, 'misses', 0)
        object.__setattr__(self, 'on_step', on_step or (lambda name: None))

    def __call__(self, texts, *a, **k):
        import torch
        key = tuple(texts) if isinstance(texts, (list, tuple)) and all(isinstance(t, str) for t in texts) and not a and not k else None
        if key is not None and key in self._cache:
            object.__setattr__(self, 'hits', self.hits + 1)
            return self._cache[key].clone()
        object.__setattr__(self, 'misses', self.misses + 1)
        out = self._te(texts, *a, **k)
        if key is not None and isinstance(out, torch.Tensor):
            self._cache[key] = out.detach().clone()
        return out

    def __getattr__(self, attr):
        return getattr(self._te, attr)


# ---------------------------------------------------------------- пустой текст из файла вместо Qwen3-8B в образе (T-178/1, 21.11; владелец TG 1143: «веса внутрь, как у мешей»)
# Воркер всегда шлёт пустую подпись, значит весь выход текстового энкодера — ОДИН тензор [1, 512, 12288] (≈12 МБ). Он считается заранее (qwen_empty_embed.py, тем же кодом авторов)
# и едет в образе файлом; 16 ГБ Qwen в образ не кладём. Любая НЕпустая подпись — громкая ошибка (не молчаливая подмена).
TEXT_CACHE_ENV = 'ULTRATEX_TEXT_CACHE'                          # путь к .pt; рядом <то же имя>.json с shape и sha256
TEXT_CACHE_SHAPE = (1, 512, 12288)


def text_cache_path() -> str:
    """Путь к файлу пустого текста, если режим включён и файл есть; пусто — обычный режим (Qwen3-8B в весах)."""
    p = os.environ.get(TEXT_CACHE_ENV, '').strip()
    return p if p and os.path.isfile(p) else ''


def load_text_cache(path: str):
    """→ тензор bf16 [1, 512, 12288] с проверкой: рядом json с формой и sha256 байт; несовпадение — RuntimeError (образ собран неверно)."""
    import hashlib
    import torch
    meta = json.load(open(os.path.splitext(path)[0] + '.json'))
    t = torch.load(path, map_location='cpu', weights_only=True)
    if tuple(t.shape) != tuple(meta['shape']) or tuple(t.shape) != TEXT_CACHE_SHAPE or t.dtype != torch.bfloat16:
        raise RuntimeError(f'кэш пустого текста: форма/тип {tuple(t.shape)} {t.dtype}, ждали {TEXT_CACHE_SHAPE} bf16')
    sha = hashlib.sha256(t.contiguous().view(torch.int16).numpy().tobytes()).hexdigest()
    if sha != meta['sha256']:
        raise RuntimeError('кэш пустого текста: sha256 не совпал с json (файл испорчен)')
    if not bool(torch.isfinite(t.float()).all()):
        raise RuntimeError('кэш пустого текста: есть NaN/inf')
    return t


def make_empty_text_encoder(tensor):
    """nn.Module вместо Qwen3Embedder: на пустую подпись отдаёт сохранённый тензор, на любую другую — ошибка."""
    import torch

    class EmptyTextEncoder(torch.nn.Module):
        def __init__(self, t):
            super().__init__()
            self.register_buffer('ctx', t.clone(), persistent=False)

        def forward(self, texts, *a, **k):
            if not isinstance(texts, (list, tuple)) or any(x != '' for x in texts) or not texts:
                raise RuntimeError('образ без Qwen3-8B: поддержана только пустая подпись (воркер шлёт её всегда); непустой текст — собрать образ с весами Qwen')
            return self.ctx.expand(len(texts), -1, -1).clone()
    return EmptyTextEncoder(tensor)


def install_sharded_loader() -> bool:
    """Код авторов читает DiT и AE через `util.load_sft(путь)`; для каталога кусков подставляем сборку словаря из кусков (тот же словарь тензоров, что из одного файла)."""
    from ultratex.backbones.flux2 import util
    if getattr(util.load_sft, '_sharded', False):
        return False
    orig = util.load_sft

    def load_sft(path, device='cpu'):
        return WP.load_sharded(str(path), device) if WP.is_sharded_dir(str(path)) else orig(path, device=device)
    load_sft._sharded = True
    util.load_sft = load_sft
    return True


def install_empty_text(path: str) -> dict:
    """Подменяет загрузчик текстового энкодера кода авторов (train_flux2.load_text_encoder) — Qwen не читается и не требуется. Вызывать ДО inf.load_inference_models."""
    import train_flux2                                           # код авторов (ULTRATEX_DIR уже в sys.path)
    t = load_text_cache(path)
    train_flux2.load_text_encoder = lambda model_name, device='cuda': make_empty_text_encoder(t)
    return {'path': path, 'shape': list(t.shape), 'dtype': str(t.dtype)}


class CfgDedup:
    """DiT с одной веткой вместо двух, когда ветки CFG РАВНЫ. Код авторов (train_flux2.inference) на каждом шаге склеивает [безусловная, условная] в batch=2: токены, опорные виды,
    нормали, фото и время одни и те же, различается только текст. Воркер шлёт пустой подпись → тексты равны → pred_uncond ≡ pred_cond, формула
    `uncond + g·(cond − uncond)` даёт то же `pred`. Равенство проверяется torch.equal НА КАЖДОМ шаге по всем входам; хоть один вход различается — считаем обычный batch=2.
    ULTRATEX_CFG=off — всегда обычный. Вдвое меньше активаций и вдвое меньше работы."""

    _NAMES = ('x', 'x_ids', 'timesteps', 'ctx', 'ctx_ids', 'guidance')

    def __init__(self, model, mode: str = 'auto', res: Residency | None = None, on_step=None):
        object.__setattr__(self, '_model', model)
        object.__setattr__(self, 'mode', mode)
        object.__setattr__(self, 'res', res)
        object.__setattr__(self, 'on_step', on_step or (lambda name: None))
        object.__setattr__(self, 'total', 0)
        object.__setattr__(self, 'stats', {'calls': 0, 'single': 0, 'batched': 0, 'differs': ''})
        object.__setattr__(self, 'after_call', None)             # хук после каждого шага (MemTrack.update)

    def begin(self, total_steps: int) -> None:
        object.__setattr__(self, 'total', int(total_steps))
        self.stats.update(calls=0, single=0, batched=0, differs='')

    def _same(self, kw: dict) -> bool:
        import torch
        x = kw.get('x')
        if self.mode == 'off' or not isinstance(x, torch.Tensor) or x.shape[0] != 2:
            return False
        for n in self._NAMES:
            v = kw.get(n)
            if v is None:
                if n == 'guidance':
                    continue
                self.stats['differs'] = f'{n} отсутствует'
                return False
            if not isinstance(v, torch.Tensor) or v.shape[0] != 2 or not torch.equal(v[0], v[1]):
                self.stats['differs'] = n
                return False
        return True

    def __call__(self, *a, **k):
        kw = dict(zip(self._NAMES, a))
        kw.update(k)
        self.stats['calls'] += 1
        label = f'dit {self.stats["calls"]}/{self.total}' if self.total else 'dit'
        if self.res is not None:
            self.res.labels['dit'] = label
        else:
            self.on_step(label)
        if self._same(kw):
            import torch
            one = {n: (v[:1] if isinstance(v, torch.Tensor) else v) for n, v in kw.items()}
            o = self._model(**one)
            out = torch.cat([o, o], dim=0)                       # снаружи ждут batch=2: pred_cfg.chunk(2) → две одинаковые половины
            self.stats['single'] += 1
        else:
            out = self._model(**kw)
            self.stats['batched'] += 1
        if self.after_call is not None:
            self.after_call()
        if self.total and self.stats['calls'] == self.total:
            if self.res is not None:
                self.res.labels.pop('dit', None)
            self.on_step('после DiT: декодирование VAE')
        return out

    def __getattr__(self, attr):
        return getattr(self._model, attr)


class MemTrack:
    """Пики памяти карты за задание: allocated/reserved (torch) и свободное по драйверу. Residency сбрасывает пики на каждой смене фазы, поэтому максимум копится здесь."""

    def __init__(self, torch_mod):
        self.t = torch_mod
        self.reset()

    def _cuda(self) -> bool:
        return bool(self.t is not None and self.t.cuda.is_available())

    def reset(self) -> None:
        self.max_alloc = self.max_reserved = 0.0
        self.min_driver_free = None
        self.marks: list = []

    def update(self, tag: str | None = None) -> None:
        if not self._cuda():
            return
        gib = 2 ** 30
        a, r = self.t.cuda.max_memory_allocated() / gib, self.t.cuda.max_memory_reserved() / gib
        free = self.t.cuda.mem_get_info()[0] / gib
        self.max_alloc, self.max_reserved = max(self.max_alloc, a), max(self.max_reserved, r)
        self.min_driver_free = free if self.min_driver_free is None else min(self.min_driver_free, free)
        if tag:
            self.marks.append((tag, round(a, 2), round(r, 2), round(free, 2)))

    def summary(self) -> dict:
        return {'peak_allocated_gb': round(self.max_alloc, 2), 'peak_reserved_gb': round(self.max_reserved, 2),
                'min_driver_free_gb': None if self.min_driver_free is None else round(self.min_driver_free, 2), 'marks': list(self.marks)}


_MEM = {'chunk': 0}                                              # текущий размер куска для RoPE/RMSNorm (глобальные подмены читают его при каждом вызове)


def _chunked_rope(orig):
    """apply_rope авторов считает в float32 целиком (≈10 копий q в 4 байтах на 70 тыс токенов). Позиционная операция → по кускам вдоль токенов, результат тот же."""
    def apply_rope(xq, xk, freqs_cis):
        chunk = _MEM['chunk']
        if chunk <= 0 or xq.ndim != 4 or freqs_cis.ndim != 6 or freqs_cis.shape[2] != xq.shape[2] or xq.shape[2] <= chunk:
            return orig(xq, xk, freqs_cis)
        oq, ok = xq.new_empty(xq.shape), xk.new_empty(xk.shape)
        for s, e in _chunks(xq.shape[2], chunk):
            q_c, k_c = orig(xq[:, :, s:e], xk[:, :, s:e], freqs_cis[:, :, s:e])
            oq[:, :, s:e], ok[:, :, s:e] = q_c, k_c
        return oq, ok
    apply_rope._mem_chunked = True
    return apply_rope


def _chunked_rms(orig_forward):
    """RMSNorm q/k авторов: x.float(), x**2, x*rrms — три копии в float32. По кускам вдоль токенов (предпоследняя ось), по каждой строке считается так же."""
    def forward(self, x):
        chunk = _MEM['chunk']
        if chunk <= 0 or x.ndim < 3 or x.shape[-2] <= chunk:
            return orig_forward(self, x)
        out = None
        for s, e in _chunks(x.shape[-2], chunk):
            part = orig_forward(self, x[..., s:e, :])
            if out is None:
                out = part.new_empty(x.shape)
            out[..., s:e, :] = part
        return out
    forward._mem_chunked = True
    return forward


def _single_qkv(self, x, mod):
    """SingleStreamBlock._qkv авторов держит весь выход linear1 (9H на токен) до конца блока. Здесь linear1 — кусками: в буфере остаются q|k|v (3H) и уже активированный MLP (3H)."""
    from einops import rearrange
    mod_shift, mod_scale, mod_gate = mod
    x_mod = (1 + mod_scale) * self.pre_norm(x) + mod_shift
    h3 = 3 * self.hidden_size
    qkv = act = None
    for s, e in _chunks(x_mod.shape[1], self._mem_chunk):
        y = self.linear1(x_mod[:, s:e])
        if qkv is None:
            qkv = y.new_empty(y.shape[0], x_mod.shape[1], h3)
            act = y.new_empty(y.shape[0], x_mod.shape[1], self.mlp_hidden_dim)
        qkv[:, s:e] = y[..., :h3]
        act[:, s:e] = self.mlp_act(y[..., h3:])
    del x_mod
    q, k, v = rearrange(qkv, "B L (K H D) -> K B H L D", K=3, H=self.num_heads)
    q, k = self.norm(q, k, v)
    return q, k, v, act, mod_gate


def _single_out(self, x, attn, act, mod_gate):
    """Вторая половина блока: mlp уже активирован в _single_qkv; linear2 + остаток — кусками."""
    import torch
    out = None
    for s, e in _chunks(x.shape[1], self._mem_chunk):
        o = self.linear2(torch.cat((attn[:, s:e], act[:, s:e]), 2))
        r = x[:, s:e] + mod_gate * o
        if out is None:
            out = r.new_empty(x.shape[0], x.shape[1], r.shape[-1])
        out[:, s:e] = r
    return out


def _double_apply_residuals(self, img, txt, img_attn, txt_attn, mods):
    """DoubleStreamBlock._apply_residuals: MLP потока картинки (6H на токен) — кусками."""
    (img_mod1_gate, img_mod2_shift, img_mod2_scale, img_mod2_gate, txt_mod1_gate, txt_mod2_shift, txt_mod2_scale, txt_mod2_gate) = mods

    def mlp_part(x, norm, shift, scale, gate, mlp):
        out = None
        for s, e in _chunks(x.shape[1], self._mem_chunk):
            r = x[:, s:e] + gate * mlp((1 + scale) * norm(x[:, s:e]) + shift)
            if out is None:
                out = r.new_empty(x.shape[0], x.shape[1], r.shape[-1])
            out[:, s:e] = r
        return out
    img = img + img_mod1_gate * self.img_attn.proj(img_attn)
    img = mlp_part(img, self.img_norm2, img_mod2_shift, img_mod2_scale, img_mod2_gate, self.img_mlp)
    txt = txt + txt_mod1_gate * self.txt_attn.proj(txt_attn)
    txt = mlp_part(txt, self.txt_norm2, txt_mod2_shift, txt_mod2_scale, txt_mod2_gate, self.txt_mlp)
    return img, txt


def apply_memory_patches(M, dit, chunk: int) -> dict:
    """Подмена позиционных операций кусками. M — модуль `ultratex.backbones.flux2.model`, dit — любая обёртка над Flux2 (peft/accelerate): блоки ищутся обходом модулей.
    chunk ≤ 0 — прежнее поведение (подмены снимаются). Повторный вызов безопасен. → {'single': n, 'double': n, 'chunk': chunk}."""
    done = {'single': 0, 'double': 0, 'chunk': chunk}
    _MEM['chunk'] = max(int(chunk), 0)
    if not getattr(M.apply_rope, '_mem_chunked', False):
        M.apply_rope = _chunked_rope(M.apply_rope)
    if not getattr(M.RMSNorm.forward, '_mem_chunked', False):
        M.RMSNorm.forward = _chunked_rms(M.RMSNorm.forward)
    for blk in dit.modules():
        kind = type(blk).__name__
        if chunk <= 0:
            for name in ('_qkv', '_out', '_apply_residuals', '_mem_chunk'):
                blk.__dict__.pop(name, None)
            continue
        if kind == 'SingleStreamBlock':
            blk._mem_chunk = chunk
            blk._qkv = types.MethodType(_single_qkv, blk)
            blk._out = types.MethodType(_single_out, blk)
            done['single'] += 1
        elif kind == 'DoubleStreamBlock':
            blk._mem_chunk = chunk
            blk._apply_residuals = types.MethodType(_double_apply_residuals, blk)
            done['double'] += 1
    return done


# ---------------------------------------------------------------- модель и задание (нужны GPU и тяжёлые пакеты — только здесь)
class Engine:
    """Загружает код авторов и модель один раз, потом принимает задания."""

    def __init__(self, root: str, upstream_dir: str):
        self.root, self.upstream = root, upstream_dir
        self.ready = False
        self.models = None
        self.on_step = lambda name: None                         # ход задания в /health (State.step): prep, conditions, te, dit i/N, декодирование, bake
        self.track = None
        self.text_source = {'path': '', 'note': 'не загружен'}
        self.gate = None                                         # итог затвора диагностики (ULTRATEX_DIAG_FIRST=1): {'verdict', 'diag'}
        self.mem = {'chunk': 0, 'cfg': os.environ.get('ULTRATEX_CFG', 'auto'), 'vram_frac': None}

    def load(self, resolution_hint: int = 2048):
        """ULTRATEX_OFFLOAD=swap — карта 32 ГБ (веса DiT/энкодера в обычной памяти ≥48 ГБ ОЗУ, на карту по очереди); none (по умолчанию) — всё на карте, 80 ГБ.
        ULTRATEX_SPARSE=1|0|auto: разреженное внимание авторов (Triton-ядро); auto — проба ядра на карте, не собралось → выключено (в /health `sparse`)."""
        env = weights_env(self.root)
        os.environ.update(env)
        os.environ.setdefault('WANDB_MODE', 'offline')
        sys.path.insert(0, self.upstream)
        os.chdir(self.upstream)
        import torch
        import inference_flux2 as inf                          # код авторов
        from accelerate import Accelerator
        self.inf = inf
        install_sharded_loader()
        tc = text_cache_path()
        self.text_source = install_empty_text(tc) if tc else {'path': '', 'note': 'Qwen3-8B из весов'}     # в /health и метрики: откуда текст
        self.accelerator = Accelerator(mixed_precision='bf16')
        ckpt = os.path.join(self.root, 'checkpoints', 'flux2', 'lora', 'dit_lora.safetensors')
        sparse_mode = os.environ.get('ULTRATEX_SPARSE', 'auto').lower()
        self.offload = os.environ.get('ULTRATEX_OFFLOAD', 'none').lower()
        self.args = inf.InferenceArgs(resolution=resolution_hint, decoder_ckpt=os.path.join(self.root, 'checkpoints', 'flux2', 'decoder.pt'),
                                      resume_from_checkpoint=ckpt, project_dir=os.path.join(self.root, 'out'), sparse_attention=sparse_mode != '0')
        self.trainer = inf.get_trainer('albedo')
        if self.offload == 'swap':
            host = types.SimpleNamespace(device=torch.device('cpu'))      # load_inference_models берёт у ускорителя только .device: всё грузим в обычную память
            model, ae, te = inf.load_inference_models(self.args, host, inf.Path(ckpt), self.trainer)
            ae.to(self.accelerator.device)
            dit_p, ae_p, te_p, self.residency = wrap_offload(model, te, ae, self.accelerator.device, torch)
            self.models = (dit_p, ae_p, te_p)
        else:
            self.residency = None
            self.models = inf.load_inference_models(self.args, self.accelerator, inf.Path(ckpt), self.trainer)
        self.setup_memory(torch)
        self.sparse = {'mode': sparse_mode, 'on': sparse_mode != '0', 'note': ''}
        if sparse_mode == 'auto':
            self.sparse_probe()
        self.ready = True

    def setup_memory(self, torch):
        """Подмены памяти (см. секцию «память карты 32 ГБ»): куски по токенам, одна ветка CFG, кэш пустого текста, потолок доли памяти карты, учёт пиков.
        ULTRATEX_MEM_CHUNK (токенов, 0 — выкл.), ULTRATEX_CFG=auto|off, ULTRATEX_VRAM_FRAC (по умолчанию 0,95 в swap-режиме; 0 — не ставить)."""
        from ultratex.backbones.flux2 import model as M
        model, ae, te = self.models
        res = getattr(self, 'residency', None)
        core = res.mods['dit'] if res is not None else model
        chunk = int(os.environ.get('ULTRATEX_MEM_CHUNK', str(MEM_CHUNK)))
        self.mem['patched'] = apply_memory_patches(M, core, chunk)
        self.mem['chunk'] = chunk
        frac = float(os.environ.get('ULTRATEX_VRAM_FRAC', '0.95' if res is not None else '0'))
        if frac > 0 and torch.cuda.is_available():
            torch.cuda.set_per_process_memory_fraction(min(frac, 1.0))   # потолок: переполнение — громкий OOM, а не тихий слив в системную память драйвером
        self.mem['vram_frac'] = frac or None
        self.track = MemTrack(torch)
        if res is not None:
            res.track = self.track
        self.dedup = CfgDedup(model, self.mem['cfg'], res, lambda n: self.on_step(n))
        self.dedup.after_call = self.track.update
        self.text_cache = TextCache(te)
        self.models = (self.dedup, ae, self.text_cache)

    def load_diag(self):
        """Режим без весов (ULTRATEX_NO_WEIGHTS=1): только код авторов и карта; готов за секунды, веса не скачиваются, задание — POST /diag."""
        os.environ.update(weights_env(self.root))
        sys.path.insert(0, self.upstream)
        os.chdir(self.upstream)
        import torch
        self.offload, self.residency = 'diag', None
        self.sparse = {'mode': 'diag', 'on': True, 'note': 'режим диагностики без весов'}
        torch.cuda.init()
        self.ready = True

    def sparse_probe(self):
        """Ядро разреженного внимания на карте: маленький вызов. Не собралось (Triton под эту архитектуру) → внимание авторов без разреженности, причина — в /health."""
        import torch
        from ultratex.backbones.flux2 import model as M
        try:
            q = torch.randn(1, 8, 1024, 128, device=self.accelerator.device, dtype=torch.bfloat16)
            out = M._SPARSE_ATTENTION(q, q, q)
            torch.cuda.synchronize()
            if not bool(torch.isfinite(out).all()):
                raise RuntimeError('ядро вернуло нечисла')
            del q, out
            self.sparse.update(on=True, note='проба ядра прошла (1024 токена)')
            length = int(os.environ.get('ULTRATEX_PROBE_L', '71000'))
            if length > 0:                                       # ядро компилируется ПОД длину (L, число блоков и topk — constexpr): проба на 1024 токенах реальную не проверяет
                real = self.sparse_real(M, length, 1 if self.mem.get('cfg') != 'off' else 2)
                self.sparse.update(real=real, note=f'ядро прошло и на {length} токенах: компиляция+запуск {real["first_s"]} с, повтор {real["again_s"]} с')
        except Exception as exc:                               # noqa: BLE001 — любой отказ ядра/компиляции = без разреженности
            M.configure_sparse_attention(enabled=False)
            self.sparse.update(on=False, note=f'ядро не собралось, выключено: {type(exc).__name__}: {str(exc)[:160]}')
            log.warning('разреженное внимание выключено: %s', self.sparse['note'])

    def sparse_real(self, M, length: int, batch: int, heads: int = 32, dim: int = 128) -> dict:
        """Разреженное внимание на форме настоящего задания (batch×heads×токены×128, настоящий topk = 0,2 от числа блоков): время первой компиляции и повтора, память."""
        import torch
        dev = getattr(getattr(self, 'accelerator', None), 'device', None) or torch.device('cuda')
        q = torch.randn(batch, heads, length, dim, device=dev, dtype=torch.bfloat16)
        torch.cuda.synchronize()
        times = []
        for _ in range(2):
            t0 = time.time()
            out = M._SPARSE_ATTENTION(q, q, q)
            torch.cuda.synchronize()
            times.append(round(time.time() - t0, 2))
            if not bool(torch.isfinite(out).all()):
                raise RuntimeError('ядро на реальной форме вернуло нечисла')
        info = {'length': length, 'shape': [batch, heads, length, dim], 'first_s': times[0], 'again_s': times[1], 'peak_gb': round(torch.cuda.max_memory_allocated() / 2 ** 30, 2)}
        del q, out
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        return info

    def _batch(self, cond: dict):
        import torch
        dev = self.accelerator.device

        def tf(arr):                                           # ToTensor + Normalize([0.5],[0.5]) как у датасета авторов
            return ((torch.from_numpy(np.ascontiguousarray(arr)).permute(2, 0, 1).float() / 255.0 - 0.5) / 0.5)[None]
        # цель (нужна только форма латента): серый холст той же формы, что холст нормалей
        target = np.zeros_like(cond['normal_grid'])
        masks = [torch.from_numpy(cond[k].astype(np.float32)) for k in ('mask_target', 'mask_normals', 'mask_reference')]
        return {'id': ['job'], 'txt': [''], 'img': tf(target), 'ref_imgs': [tf(cond['normal_grid']), tf(cond['reference'])],
                'masks': [masks], 'masks_full': [[torch.from_numpy(cond['mask_full_grid'].astype(np.float32))]]}, dev

    def run(self, p: dict, glb: bytes, png: bytes) -> tuple[bytes, dict]:
        import torch
        import trimesh
        from PIL import Image
        from ultratex_core import bake as bake_core, prep as prep_core
        m: dict = {'version': VERSION, 'params': {k: p[k] for k in DEFAULTS}}
        t0 = time.time()
        self.on_step('prep: рендер и развёртка')
        mesh = trimesh.load(io.BytesIO(glb), file_type='glb')
        ref = np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'))
        if int((ref[..., 3] > 8).sum()) < 64:
            raise ValueError('фото без маски (альфа пустая): нужен RGBA-вырез')
        prep = prep_core.run_prep(mesh, ref, p['resolution'], p['texture_size'], 'keep_existing', 'fit_front_silhouette')
        m['prep_s'] = round(time.time() - t0, 2)
        m['faces'] = int(len(prep.faces))
        m['view_coverage_pct'] = [round(float((prep.normal_rgba[v, ..., 3] > 0).mean() * 100), 2) for v in range(6)]
        t1 = time.time()
        self.on_step('conditions: VAE-кодирование')
        cond = build_conditions(prep.normal_rgba, prep.reference_rgba, p['resolution'])
        batch, dev = self._batch(cond)
        model, ae, te = self.models
        torch.cuda.reset_peak_memory_stats()
        if self.track is not None:
            self.track.reset()
        if hasattr(model, 'begin'):
            model.begin(p['steps'])
        black = Image.new('RGB', (p['resolution'], p['resolution']), (0, 0, 0))
        bt = ((torch.from_numpy(np.asarray(black)).permute(2, 0, 1).float() / 255.0 - 0.5) / 0.5)[None].to(dev)
        res = getattr(self, 'residency', None)
        try:
            with torch.no_grad():
                background = ae.encode(bt.float()).repeat(1, 1, 2, 3)
                result = self.trainer.inference(batch, model, te, ae, self.accelerator, seed=p['seed'], resolution=p['resolution'], background=background,
                                                guidance=p['guidance'], remove_background=True, drop_background_tokens=True, num_steps=p['steps'])
        except BaseException:
            if res is not None:
                res.release_all()                                    # сбой посреди DiT: не оставлять его на карте до следующего задания
            if self.track is not None:
                self.track.update('сбой')
            torch.cuda.empty_cache()
            raise
        m['sample_s'] = round(time.time() - t1, 2)
        if self.track is not None:
            self.track.update('после sample')
        m['offload'] = getattr(self, 'offload', 'none')
        m['sparse'] = getattr(self, 'sparse', {})
        if res is not None:
            res.use('ae')                                            # закрыть последнюю фазу и убрать DiT/энкодер с карты до запекания
            m['vram_phases_gb'] = dict(res.phases)
            m['offload_moves_s'] = [f'{n}→{w} {t}с' for n, w, t in res.moves]
            if res.notes:
                m['offload_oom_notes'] = list(res.notes)
                res.notes.clear()
            res.phases.clear()
            res.moves.clear()
        mem = self.track.summary() if self.track is not None else {}
        # честный пик задания: в swap-режиме torch-счётчик сбрасывается на каждой смене фазы, прежний vram_peak_gb видел только последнюю
        m['vram_peak_gb'] = mem.get('peak_allocated_gb', round(torch.cuda.max_memory_allocated() / 2 ** 30, 2))
        m['vram'] = mem
        m['mem'] = {k: v for k, v in self.mem.items()}
        if hasattr(model, 'stats'):
            m['cfg'] = dict(model.stats)
        if hasattr(te, 'hits'):
            m['text_cache'] = {'hits': te.hits, 'misses': te.misses, 'source': getattr(self, 'text_source', {}).get('path') or 'qwen3_8b'}
        self.on_step('bake: запекание текстуры')
        views = tiles_from_grid(np.asarray(result.convert('RGB'), dtype=np.float32) / 255.0, p['resolution'])
        t2 = time.time()
        masks = np.stack([np.asarray(Image.fromarray(prep.normal_rgba[v, ..., 3]).resize((p['resolution'],) * 2, Image.Resampling.BILINEAR)) > 0 for v in range(6)])
        baker = bake_core.Baker(prep, p['texture_size'])
        try:
            albedo_np, conf = baker.bake([(views, masks, None)], bake_core.BakeSettings())
            albedo = bake_core.to_pil(albedo_np)
        finally:
            baker.release()
        out = bake_core.textured_mesh(prep, albedo, None)
        buf = io.BytesIO()
        out.export(buf, file_type='glb')
        m['bake_s'] = round(time.time() - t2, 2)
        m['texel_seen_pct'] = round(float((np.asarray(conf) > 0).mean() * 100), 2)
        m['total_s'] = round(time.time() - t0, 2)
        m['faces_out'] = int(len(out.faces))
        return buf.getvalue(), m


# ---------------------------------------------------------------- сервер (скелет — общий набор Salad `kit_worker`: `::`, /health, прогрев, автостоп)
make_server, dir_gb, cuda_info, State = KW.make_server, KW.dir_gb, KW.cuda_info, KW.State        # прежние имена (тесты, вызовы)


class UltraHandler(KW.KitHandler):
    """Пути модели; `/health` и `/shutdown` — в базе. Тело `/health` дополняем метриками движка."""
    engine: Engine = None

    def handle_get(self, path: str) -> bool:
        parts = path.strip('/').split('/')
        if parts[0] == 'result' and len(parts) >= 2:
            j = self.state.jobs.get(parts[1])
            if not j:
                self.send_json(404, {'error': 'нет такого задания'})
            elif len(parts) == 3 and parts[2] == 'glb':
                if j['status'] != 'done':
                    self.send_json(409, {'error': 'ещё не готово'})
                else:
                    self.send_bytes(200, j['glb'], 'model/gltf-binary')
            else:
                self.send_json(200, {k: v for k, v in j.items() if k != 'glb'})
            return True
        return False

    def handle_post(self, path: str) -> bool:
        if path == '/diag':
            return self.handle_diag()
        if path != '/generate':
            return False
        state, engine = self.state, self.engine
        body = self.read_json(MAX_GLB_BYTES + MAX_IMAGE_BYTES)
        if body is None:
            return True
        p, err = validate_job(body)
        if err:
            self.send_json(400, {'error': err})
            return True
        if state.phase != 'ready':
            self.send_json(503, {'error': f'не готов: фаза {state.phase}'})
            return True
        with state.lock:
            if state.busy:
                self.send_json(429, {'error': 'занят другим заданием'})
                return True
            state.busy = True
        try:
            glb, png = base64.b64decode(body['glb_b64']), base64.b64decode(body['image_b64'])
        except Exception:                                      # noqa: BLE001
            state.busy = False
            self.send_json(400, {'error': 'base64 не разобран'})
            return True
        state.jobs[p['job_id']] = {'status': 'running', 'metrics': {}, 'error': ''}
        threading.Thread(target=_work, args=(state, engine, p, glb, png), daemon=True).start()
        self.send_json(202, {'job_id': p['job_id']})
        return True


def _handle_diag(self) -> bool:
    """POST /diag {job_id, lengths?, chunk?, runs?, dit_length?, …}: диагностика карты (run_diag). Только в режиме без весов (ULTRATEX_NO_WEIGHTS=1) — на живой модели занимает карту."""
    state, engine = self.state, self.engine
    body = self.read_json(1 << 20)
    if body is None:
        return True
    if getattr(engine, 'offload', '') != 'diag':
        self.send_json(403, {'error': '/diag только в режиме без весов (ULTRATEX_NO_WEIGHTS=1)'})
        return True
    jid = str(body.get('job_id') or 'diag')[:150]
    if state.phase != 'ready':
        self.send_json(503, {'error': f'не готов: фаза {state.phase}'})
        return True
    with state.lock:
        if state.busy:
            self.send_json(429, {'error': 'занят другим заданием'})
            return True
        state.busy = True
    state.jobs[jid] = {'status': 'running', 'metrics': {}, 'error': ''}
    threading.Thread(target=_work_diag, args=(state, engine, jid, body), daemon=True).start()
    self.send_json(202, {'job_id': jid})
    return True


UltraHandler.handle_diag = _handle_diag


def _work_diag(state: State, engine: Engine, jid: str, p: dict):
    j = state.jobs[jid]
    state.begin_job(jid)
    engine.on_step = state.step
    try:
        run_diag(engine, p, j['metrics'])                      # метрики наполняются по ходу: при сбое остаются результаты прошедших частей
        j.update(status='done')
    except Exception as exc:                                   # noqa: BLE001
        j.update(status='failed', error=f'{type(exc).__name__}: {exc}', trace=traceback.format_exc()[-1500:])
    finally:
        state.end_job()
        state.busy = False


def make_handler(state: State, engine: Engine, wd: Watchdog, stop: threading.Event):
    """Обработчик с привязкой к состоянию; в /health — root_gb (ход докачки), метрики движка."""
    return UltraHandler.bind(state, wd, stop, VERSION, root_dir=os.environ.get('ULTRATEX_ROOT', '/workspace/ultratex'), engine=engine,
                             health_extra=lambda: {'offload': getattr(engine, 'offload', None), 'sparse': getattr(engine, 'sparse', None), 'mem': getattr(engine, 'mem', None),
                                                       'gate': getattr(engine, 'gate', None)})


def _work(state: State, engine: Engine, p: dict, glb: bytes, png: bytes):
    j = state.jobs[p['job_id']]
    state.begin_job(p['job_id'])
    res = getattr(engine, 'residency', None)
    engine.on_step = state.step                                # prep / conditions / te / dit i/N / декодирование / bake — в /health (state.job)
    if res is not None:
        res.on_step = state.step                               # шаги DiT/энкодера/VAE и переносы — в /health (state.job)
    try:
        out, metrics = engine.run(p, glb, png)
        j.update(status='done', metrics=metrics, glb=out)
    except Exception as exc:                                   # noqa: BLE001
        j.update(status='failed', error=f'{type(exc).__name__}: {exc}', trace=traceback.format_exc()[-1500:])
        if KW.fatal_cuda(exc):
            state.phase = 'broken'                             # фатальная ошибка CUDA: нода непригодна, новые задания не берём
    finally:
        state.end_job()
        state.busy = False


# ---------------------------------------------------------------- диагностика карты БЕЗ весов (T-178/1): тихий слив в системную память, ядро на реальных длинах, пик DiT на случайных весах
DIAG_DEFAULTS = {'lengths': [46000, 71000], 'chunk': MEM_CHUNK, 'spill_over_gb': 4.0, 'runs': ['b1_chunk', 'b1_plain', 'b2_chunk'], 'ctx_len': 512}


def diag_spill(torch, over_gb: float, step_gb: float = 1.0) -> dict:
    """Выделяет по 1 ГиБ, пока не упадёт или не перевалит физический объём на over_gb. Перевалило без ошибки → драйвер тихо сливает в системную память (WDDM/sysmem fallback).
    Скорость заполнения первого и последнего блока — в ГБ/с: слив даёт ×10–50 медленнее."""
    gib = 2 ** 30
    free0, total = torch.cuda.mem_get_info()
    blocks, err = [], ''
    limit = int(total / gib + over_gb)
    t_first = t_last = None
    try:
        while len(blocks) < limit:
            b = torch.empty(int(step_gb * gib), dtype=torch.uint8, device='cuda')
            torch.cuda.synchronize()
            t0 = time.time()
            b.fill_(1)
            torch.cuda.synchronize()
            dt = time.time() - t0
            t_first = t_first or dt
            t_last = dt
            blocks.append(b)
    except Exception as exc:                                   # noqa: BLE001
        err = f'{type(exc).__name__}: {str(exc)[:120]}'
    n = len(blocks)
    out = {'total_gb': round(total / gib, 2), 'free_before_gb': round(free0 / gib, 2), 'allocated_gb': n, 'error_at_gb': n if err else None, 'error': err,
           'beyond_physical': n > total / gib, 'fill_gbps_first': round(step_gb / t_first, 1) if t_first else None, 'fill_gbps_last': round(step_gb / t_last, 1) if t_last else None}
    del blocks
    torch.cuda.empty_cache()
    return out


def diag_dit(torch, M, length: int, batch: int, chunk: int, ctx_len: int, steps: int = 2) -> dict:
    """Один-два прохода DiT Klein 9B на СЛУЧАЙНЫХ весах (время и память не зависят от значений) с токенами реальной длины. Меряет пики allocated/reserved и время 1-го (компиляция ядра) и 2-го."""
    from ultratex.backbones.flux2.model import Flux2, Klein9BParams
    dev = torch.device('cuda')
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    with torch.device('meta'):
        model = Flux2(Klein9BParams()).to(torch.bfloat16)
    model = model.to_empty(device=dev)
    g = torch.Generator(device=dev).manual_seed(0)
    for name, prm in model.named_parameters():
        if name.endswith('.scale'):
            prm.data.fill_(1.0)                                # RMSNorm-масштабы единицы, остальное — малый шум (иначе значения улетают в нечисла)
        else:
            prm.data.normal_(0.0, 0.02, generator=g)
    apply_memory_patches(M, model, chunk)
    params_gb = sum(p.numel() * p.element_size() for p in model.parameters()) / 2 ** 30
    w = int(length ** 0.5)
    idx = torch.arange(length, device=dev)
    x_ids = torch.stack([torch.zeros_like(idx), idx // w, idx % w, torch.zeros_like(idx)], dim=-1)[None].expand(batch, -1, -1).contiguous()
    c_ids = torch.stack([torch.zeros(ctx_len, device=dev, dtype=torch.long), torch.zeros(ctx_len, device=dev, dtype=torch.long),
                         torch.zeros(ctx_len, device=dev, dtype=torch.long), torch.arange(ctx_len, device=dev)], dim=-1)[None].expand(batch, -1, -1).contiguous()
    x = torch.randn(1, length, 128, device=dev, dtype=torch.bfloat16, generator=g).expand(batch, -1, -1).contiguous()
    ctx = torch.randn(1, ctx_len, 12288, device=dev, dtype=torch.bfloat16, generator=g).expand(batch, -1, -1).contiguous()
    t = torch.full((batch,), 0.5, device=dev, dtype=torch.bfloat16)
    base = torch.cuda.memory_allocated() / 2 ** 30
    torch.cuda.reset_peak_memory_stats()
    times, err = [], ''
    try:
        with torch.no_grad():
            for _ in range(steps):
                t0 = time.time()
                out = model(x=x, x_ids=x_ids, timesteps=t, ctx=ctx, ctx_ids=c_ids, guidance=None)
                torch.cuda.synchronize()
                times.append(round(time.time() - t0, 2))
                if not bool(torch.isfinite(out).all()):
                    err = 'нечисла в выходе'
                del out
    except Exception as exc:                                   # noqa: BLE001
        err = f'{type(exc).__name__}: {str(exc)[:160]}'
    gib = 2 ** 30
    info = {'length': length, 'batch': batch, 'chunk': chunk, 'weights_gb': round(params_gb, 2), 'base_gb': round(base, 2), 'times_s': times, 'error': err,
            'peak_allocated_gb': round(torch.cuda.max_memory_allocated() / gib, 2), 'peak_reserved_gb': round(torch.cuda.max_memory_reserved() / gib, 2),
            'activations_gb': round(torch.cuda.max_memory_allocated() / gib - base, 2), 'driver_free_gb': round(torch.cuda.mem_get_info()[0] / gib, 2)}
    del model, x, ctx, x_ids, c_ids
    torch.cuda.empty_cache()
    return info


def run_diag(engine, p: dict, sink: dict | None = None) -> dict:
    """Задание `/diag`: что покажет карта без скачивания весов. Каждая часть пишет шаг в /health; сбой части не обрывает остальные.
    sink — словарь результата, который наполняется по ходу (d1 21.11: сбой аллокатора в середине стёр результаты уже прошедших частей).
    Порядок: ядро → DiT → слив VRAM ПОСЛЕДНИМ (намеренный OOM слива в режиме expandable_segments мог ломать аллокатор для DiT)."""
    import torch
    from ultratex.backbones.flux2 import model as M
    out: dict = sink if sink is not None else {}
    out.update({'version': VERSION, 'torch': torch.__version__, 'cuda': torch.version.cuda, 'device': torch.cuda.get_device_name(0),
                'capability': list(torch.cuda.get_device_capability(0))})
    try:
        import triton
        out['triton'] = triton.__version__
    except Exception as exc:                                   # noqa: BLE001
        out['triton'] = f'нет: {exc}'
    frac_env = os.environ.get('ULTRATEX_VRAM_FRAC', '')
    out['alloc_conf'] = os.environ.get('PYTORCH_CUDA_ALLOC_CONF', '')
    out['sparse_real'] = []
    q_ok = True
    for length in p.get('lengths', DIAG_DEFAULTS['lengths']):
        engine.on_step(f'diag: ядро на {length} токенах')
        try:
            if getattr(M, '_SPARSE_ATTENTION', None) is None:
                M.configure_sparse_attention(enabled=True, head_dim=128, topk=0.2, blkq=128, blkk=64)
            out['sparse_real'].append(engine.sparse_real(M, int(length), 1))
        except Exception as exc:                               # noqa: BLE001
            out['sparse_real'].append({'length': length, 'error': f'{type(exc).__name__}: {str(exc)[:200]}'})
            q_ok = False
    out['dit'] = []
    cfg = {'b1_chunk': (1, int(p.get('chunk', DIAG_DEFAULTS['chunk']))), 'b1_plain': (1, 0), 'b2_chunk': (2, int(p.get('chunk', DIAG_DEFAULTS['chunk']))), 'b2_plain': (2, 0)}
    torch.cuda.set_per_process_memory_fraction(float(p.get('vram_frac', frac_env or 0.97)))   # переполнение — громкий OOM, а не тихий слив
    if q_ok or p.get('dit_even_if_kernel_failed'):
        for name in p.get('runs', DIAG_DEFAULTS['runs']):
            batch, chunk = cfg[name]
            engine.on_step(f'diag: DiT {name} L={p.get("dit_length", 71000)}')
            try:
                info = diag_dit(torch, M, int(p.get('dit_length', 71000)), batch, chunk, int(p.get('ctx_len', DIAG_DEFAULTS['ctx_len'])))
            except Exception as exc:                           # noqa: BLE001  (в т.ч. сбой аллокатора до try внутри diag_dit)
                info = {'error': f'{type(exc).__name__}: {str(exc)[:200]}', 'trace': traceback.format_exc()[-600:]}
            info['run'] = name
            out['dit'].append(info)
            if info.get('error') and 'out of memory' not in info['error'].lower():
                break                                          # не память, а что-то другое — остальные прогоны тратят деньги зря
    torch.cuda.set_per_process_memory_fraction(1.0)             # слив должен дойти до физического потолка карты, а не до 0,97
    over = float(p.get('spill_over_gb', DIAG_DEFAULTS['spill_over_gb']))
    if over > 0:                                               # 0 — без слива (затвор перед весами: намеренный OOM не должен портить аллокатор перед настоящей работой)
        engine.on_step('diag: слив VRAM')
        try:
            out['spill'] = diag_spill(torch, over)
        except Exception as exc:                               # noqa: BLE001
            out['spill'] = {'error': f'{type(exc).__name__}: {exc}'}
    return out


GATE_PEAK_GB = float(os.environ.get('ULTRATEX_GATE_PEAK_GB', '30.0'))     # DiT с кусками должен уложиться: 32 ГБ карты минус запас драйвера


def diag_gate_verdict(out: dict, limit_gb: float = GATE_PEAK_GB) -> str:
    """'' — зелёно; иначе причина красного. Зелёно: ядро на реальной длине без ошибок, DiT (1 ветка, куски) без ошибки и пик allocated < limit_gb."""
    bad = [r for r in out.get('sparse_real', []) if r.get('error')]
    if bad:
        return f'ядро разреженного внимания на {bad[0].get("length")} токенах: {bad[0]["error"]}'
    if not out.get('sparse_real'):
        return 'ядро разреженного внимания не проверено'
    runs = out.get('dit') or []
    if not runs:
        return 'DiT-прогон не выполнен'
    r = runs[0]
    if r.get('error'):
        return f'DiT на {r.get("length")} токенах: {r["error"]}'
    if r.get('peak_allocated_gb', 1e9) >= limit_gb:
        return f'пик DiT {r.get("peak_allocated_gb")} ГБ ≥ {limit_gb} ГБ — на 32 ГБ не помещается'
    return ''


def diag_gate(engine, state=None) -> None:
    """Стадия ДО докачки весов (ULTRATEX_DIAG_FIRST=1): тот же диагностический прогон на случайных весах, но один заход — ядро на 71k + DiT (1 ветка, куски), без слива.
    Красное → RuntimeError → воркер `broken` → драйвер гасит ноду сразу (P-039: не качать 35 ГБ ради заведомо проваленного прогона). Зелёное — докачка и прогрев как обычно на ТОЙ ЖЕ ноде."""
    engine.load_diag()
    engine.gate = {'verdict': 'running', 'diag': {}}
    out = engine.gate['diag']
    run_diag(engine, {'lengths': [int(os.environ.get('ULTRATEX_PROBE_L', '71000'))], 'runs': ['b1_chunk'], 'spill_over_gb': 0, 'chunk': int(os.environ.get('ULTRATEX_MEM_CHUNK', MEM_CHUNK))}, out)
    why = diag_gate_verdict(out)
    engine.gate['verdict'] = why or 'green'
    log.info(f'затвор диагностики: {"ЗЕЛЁНО" if not why else "КРАСНОЕ — " + why}')
    if why:
        raise RuntimeError(f'затвор диагностики красный: {why}')
    import torch
    torch.cuda.empty_cache()
    engine.offload, engine.sparse, engine.ready = None, None, False        # настоящая загрузка выставит своё


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    root = os.environ.get('ULTRATEX_ROOT', '/workspace/ultratex')
    upstream = os.environ.get('ULTRATEX_DIR', '/opt/UltraTex')
    os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')     # до первой инициализации CUDA: меньше фрагментации при пике у потолка карты
    wd = Watchdog(float(os.environ.get('MAX_LIFETIME_S', '5400')), float(os.environ.get('IDLE_S', '900')))
    state, stop = State(), threading.Event()
    engine = Engine(root, upstream)

    def weights():
        fetch_weights(root, os.environ.get('HF_TOKEN', ''), lambda n, s: state.weights.__setitem__(n, s))

    if os.environ.get('ULTRATEX_NO_WEIGHTS') == '1':             # диагностика карты без скачивания весов (≈35 ГБ, 26 мин прогрева)
        stages = [('loading', engine.load_diag)]
    else:
        stages = [('weights', weights), ('loading', engine.load)]
        if os.environ.get('ULTRATEX_DIAG_FIRST') == '1':         # затвор: диагностика (≈5 мин) → красное: гасим до докачки; зелёное: веса и прогрев на той же ноде
            stages.insert(0, ('diag', lambda: diag_gate(engine, state)))
    return KW.serve(make_handler(state, engine, wd, stop), state, wd, stop, stages, log=log)


if __name__ == '__main__':
    sys.exit(main())
