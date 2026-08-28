"""Идентичность задания и паспорт ассета.

Зачем не просто `sku.glb`. Очередь Salad ретраит задания, прерванная нода даёт повторную
попытку, а мы со временем меняем коммит модели, параметры и seed. Если ключ хранения не
включает всё это, то (а) повтор перезаписывает чужой результат, (б) невозможно сказать, каким
именно прогоном получен конкретный меш, (в) нельзя сравнить два прогона между собой.

Ключ = hash(sku + хеш входа + commit генератора + параметры + seed). Один и тот же вход при
той же версии конвейера даёт тот же job_id — значит повтор задания дёшево обнаруживает уже
готовый результат и не тратит GPU.
"""
import hashlib
import json
import os
import subprocess

PIPELINE_VERSION = os.environ.get('PIPELINE_VERSION', 'v1')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def generator_commit() -> str:
    """Коммит Hunyuan, зашитый в образ при сборке. Без него ассет не с чем сопоставить."""
    p = '/opt/hunyuan/.pinned_commit'
    if os.path.exists(p):
        return open(p, encoding='utf-8').read().strip()[:12]
    try:
        return subprocess.run(['git', '-C', '/opt/hunyuan', 'rev-parse', '--short', 'HEAD'],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001 — нет git: помечаем честно, не выдумываем
        return 'unknown'


def weights_digest() -> str:
    """Отпечаток весов: размеры файлов и их имена. Полный хеш 15 ГБ на каждом старте не нужен —
    задача отличить один набор весов от другого, а не защититься от подмены."""
    root = os.environ.get('WEIGHTS_DIR', '/opt/weights')
    parts = []
    for dirpath, _, files in os.walk(root):
        for f in sorted(files):
            fp = os.path.join(dirpath, f)
            try:
                parts.append(f'{os.path.relpath(fp, root)}:{os.path.getsize(fp)}')
            except OSError:
                continue
    return sha('\n'.join(sorted(parts)).encode())


def job_id(sku: str, input_hash: str, params: dict, seed: int) -> str:
    payload = json.dumps({'sku': sku, 'input': input_hash, 'commit': generator_commit(),
                          'params': params, 'seed': seed, 'pipeline': PIPELINE_VERSION},
                         sort_keys=True, ensure_ascii=False)
    return sha(payload.encode())


def prefix(sku: str, jid: str) -> str:
    """Версионный префикс: смена конвейера не смешивается со старыми результатами в одной папке."""
    return f'meshes/hunyuan21/{PIPELINE_VERSION}/{sku.replace(":", "_")}/{jid}'


def asset_manifest(job: dict, jid: str, input_hash: str, timings: dict, gpu: dict) -> dict:
    return {
        'sku': job['sku'], 'job_id': jid, 'pipeline_version': PIPELINE_VERSION,
        'role': job.get('role'), 'seed': job.get('seed', 0),
        'input': {'image_url': job.get('image_url'), 'input_hash': input_hash,
                  'dims_cm': job.get('dims_cm')},
        'generator': {'model': 'Hunyuan3D-2.1', 'commit': generator_commit(),
                      'weights_digest': weights_digest(),
                      'image_digest': os.environ.get('IMAGE_DIGEST', 'unset'),
                      'torch': os.environ.get('TORCH_VERSION', 'unset'),
                      'cuda': os.environ.get('CUDA_VERSION', 'unset')},
        'params': job.get('params', {}),
        'timings_s': timings,
        'gpu': gpu,
    }
