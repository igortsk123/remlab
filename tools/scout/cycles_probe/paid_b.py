"""T-20261117-02: ОДИН дешёвый проход нынешней модели (тариф «Б», ≈3,3 ₽ за лист) поверх кадра Cycles вместо 3D-кадра.
Берёт `cheap.py` из worktree sd-probe-1116 (тот же рецепт, что у T-62, один в один) и лишь подменяет журнал расходов на свой:
  ~/venvs/scout/bin/python cycles_probe/paid_b.py --scenes <папка с <сцена>/C1.png,C2.png кадров Cycles> --scene living-scandi=0 --out <папка> [--stop 20]
Счётчик — ~/remlab-logs/t63-1117/spend.tsv; потолок задачи 200 ₽, этот скрипт останавливается на --stop (по умолчанию 20 ₽)."""
import os
import sys

SDP = '/home/pakar/igor/remlab/.claude/worktrees/sd-probe-1116/tools/scout/sd_probe'
sys.path.insert(0, SDP)
LOG = os.path.expanduser('~/remlab-logs/t63-1117')
os.makedirs(LOG, exist_ok=True)
stop = '20'
if '--stop' in sys.argv:
    i = sys.argv.index('--stop')
    stop = sys.argv[i + 1]
    del sys.argv[i:i + 2]
import cheap  # noqa: E402  (при импорте ставит журнал T-62 — переопределяем ниже)
import runner  # noqa: E402

cheap.LOGDIR = LOG
runner.LOGDIR = LOG
runner.SPEND = os.path.join(LOG, 'spend.tsv')
runner.STOP_RUB = float(stop)
os.environ['PHOTO_COST_LOG'] = os.path.join(LOG, 'photo-cost.jsonl')
os.environ['PHOTO_COST_LABEL'] = 't63'
if '--variants' not in sys.argv:
    sys.argv += ['--variants', 'B']
if '--up' not in sys.argv:
    sys.argv += ['--up', 'none']
cheap.main()
