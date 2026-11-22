#!/usr/bin/env python3
"""Сборка образа: малые веса (LoRA и декодер UltraTex, ModelScope, без токена) одним слоем. Крупные (DiT, AE с HF) — `weights_pack.py shard` по слою на кусок.
  python bake_weights.py small            # → $ULTRATEX_ROOT/checkpoints/flux2/{lora/dit_lora.safetensors, decoder.pt}
  python bake_weights.py check            # воркер видит всё нужное БЕЗ сети: DiT/AE — куски, LoRA/декодер — файлы, пустой текст — файл; Qwen3-8B в списке нет
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import kit_worker  # noqa: F401
except ImportError:                                              # в образе набора Salad нет отдельным файлом (воркер получает его на старте); для сборки нужны только имена весов
    import types

    class _KitStub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith('__'):
                raise AttributeError(name)
            return object
    sys.modules['kit_worker'] = _KitStub('kit_worker')
import worker_ultratex as W                                      # noqa: E402

SMALL = {'ultratex_lora', 'ultratex_decoder'}


def main() -> int:
    root = os.environ.get('ULTRATEX_ROOT', '/workspace/ultratex')
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'small':
        print(W.fetch_weights(root, '', lambda n, s: print(n, s, flush=True), only=SMALL))
        return 0
    if cmd == 'check':
        plan = W.plan_weights(root)
        names = [w['name'] for w in plan]
        bad = [w['name'] for w in plan if not W._present(w)]
        srcs = {w['name']: w['src'] for w in plan}
        print('веса:', srcs)
        if 'qwen3_8b' in names:
            print('ОШИБКА: Qwen3-8B в списке весов (нет кэша пустого текста, ULTRATEX_TEXT_CACHE)')
            return 2
        if bad:
            print('ОШИБКА: нет в образе:', bad)
            return 3
        if srcs.get('flux2_klein_base_9b') != 'sharded' or srcs.get('flux2_ae') != 'sharded':
            print('ОШИБКА: DiT/AE не из кусков')
            return 4
        t = W.load_text_cache(W.text_cache_path())
        print('пустой текст:', tuple(t.shape), t.dtype)
        return 0
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main())
