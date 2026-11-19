"""Хвост лога сборки образа → аннотации GitHub (читаются публично через API check-runs/<job>/annotations) и сводка шага.
Зачем: логи Actions без токена недоступны, а по аннотациям видно, на каком шаге Dockerfile упала сборка (T-20261118-91, директор 19.11).
  python3 ci_annotate.py build.log [строк=96] [в-куске=12]   — вызывать при провале сборки; в GITHUB_STEP_SUMMARY дописывает последние строки."""
import os
import sys

path = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 96
per = int(sys.argv[3]) if len(sys.argv) > 3 else 12
lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
tail = lines[-n:]
summary = os.environ.get('GITHUB_STEP_SUMMARY')
if summary:
    with open(summary, 'a', encoding='utf-8') as f:
        f.write('### Сборка упала — хвост лога\n```\n' + '\n'.join(tail) + '\n```\n')
# «ошибочные» строки выше хвоста (pip/компилятор пишут их раньше финального «did not complete»)
hits = [x for x in lines[:-n] if any(k in x for k in ('ERROR', 'error:', 'Error', 'No matching', 'conflict', 'Could not'))][-12:]
chunks = ([('ошибки выше хвоста', hits)] if hits else []) + [(f'хвост {i // per + 1}', tail[i:i + per]) for i in range(0, len(tail), per)]
for title, ch in chunks[:10]:                       # GitHub показывает не более 10 аннотаций одного уровня на шаг
    msg = '\n'.join(x[:300] for x in ch).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    print(f'::error title={title}::{msg}')
