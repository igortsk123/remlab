#!/usr/bin/env python3
"""БЕСПЛАТНАЯ ПРОВЕРКА ДОСТУПА К ЗАКРЫТЫМ ВЕСАМ (T-20261118-91): HEAD-запрос к файлу репозитория Hugging Face с токеном из `~/scout-scenes/salad.env`.
Печатает ТОЛЬКО код ответа (200 — доступ есть; 401/403 — нет: условия не приняты или заявка на ручном одобрении). Токен не печатается и никуда не пишется.
Платный запуск TRELLIS.2/Pixal3D — только при 200 (решение директора 18.11).

  ~/venvs/scout/bin/python hf_access.py [repo/файл…]      # по умолчанию facebook/dinov3-vitl16-pretrain-lvd1689m/resolve/main/config.json
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
DEFAULT = ['facebook/dinov3-vitl16-pretrain-lvd1689m/resolve/main/config.json']


def head(path: str, token: str, timeout: int = 30) -> int:
    """Код HTTP на HEAD `https://huggingface.co/<path>` с токеном (редиректы файлов HF — за нас: 200/302 → доступ есть)."""
    req = urllib.request.Request(f'https://huggingface.co/{path}', method='HEAD', headers={'Authorization': f'Bearer {token}', 'User-Agent': 'remlab-mesh/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return -1


def token() -> str:
    import migrate_groups as MG
    MG.env_from_file()                       # читает файл ключей сама, значения в окружение процесса
    return os.environ.get('HF_TOKEN', '')


def main() -> int:
    tok = token()
    if not tok:
        print('HF_TOKEN в окружении нет (строка HF_TOKEN= в salad.env пуста или отсутствует)')
        return 2
    rc = 0
    for p in (sys.argv[1:] or DEFAULT):
        code = head(p, tok)
        print(f'{code} {p}')
        rc = rc or (0 if code in (200, 302) else 1)
    return rc


if __name__ == '__main__':
    sys.exit(main())
