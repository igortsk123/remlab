#!/usr/bin/env bash
# T-93: сырые маски на HD для дивана и комода — BiRefNet (база, 1024), BEN2, BiRefNet_HR (2048). Каждая — под очередью тяжёлых.
cd /home/pakar/igor/remlab || exit 1
S="114667:11634594969038554503 112923:13224664101879413845"
PY=/home/pakar/venvs/scout/bin/python
L=/home/pakar/remlab-logs/t93-1119
for M in "birefnet stretch" "ben2 stretch" "birefnet_hr stretch"; do
  set -- $M
  tools/ops/heavy-slot.sh "t93-$1" --prio 1 --cores 4 --min-gb 6 --timeout 3000 -- $PY $L/cut_bench.py --model $1 --mode $2 --src B --cores 4 $S > $L/bench_$1_$2_B.log 2>&1
done
echo ГОТОВО > $L/bench2.done
