#!/usr/bin/env python3
"""Сколько памяти РЕАЛЬНО ест наш воркер на ноде — замер, а не догадка.

ЗАЧЕМ. 02.09 я снизил запрос памяти с 16 до 12 ГБ, потом увидел на ноде «занято 13761 МБ»
и откатил обратно. Замер был неверный: `free -m` внутри контейнера показывает память ВСЕЙ
МАШИНЫ, а не нашу долю. При лимите 12 ГБ контейнер физически не мог занять 13.8 — я мерил
хост. Владелец поймал ошибку сразу.

ЧТО МЕРЯЕМ ПРАВИЛЬНО:
  * `/sys/fs/cgroup/memory.current` и `memory.peak` — сколько взял и сколько брал в пике
    ИМЕННО наш контейнер (если cgroup v2 доступен);
  * RSS процессов воркера — то же самое снизу, на случай если cgroup не виден;
  * `memory.max` — какой лимит нам реально выдали (может отличаться от запрошенного);
  * `free -m` тоже показываем, но ПОДПИСАННЫМ как память машины, чтобы больше не путать.

Запрос ресурсов важен не сам по себе: он отсекает машины. Машина с 14 ГБ ОЗУ при запросе
16 ГБ нам не достанется вовсе, а при 12 — достанется и, возможно, отработает.

  ~/venvs/scout/bin/python mem_probe.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ssh_run as S  # noqa: E402

REMOTE = (
    'echo "=== лимит контейнера ==="; '
    'cat /sys/fs/cgroup/memory.max 2>/dev/null || echo "cgroup v2 не виден"; '
    'echo "=== взято контейнером сейчас ==="; '
    'cat /sys/fs/cgroup/memory.current 2>/dev/null || echo нет; '
    'echo "=== пик контейнера ==="; '
    'cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo "нет (ядро старое)"; '
    'echo "=== процессы воркера, RSS в КБ ==="; '
    'ps -eo rss,comm --sort=-rss 2>/dev/null | head -6; '
    'echo "=== память ВСЕЙ МАШИНЫ (не наша доля) ==="; '
    'free -m | sed -n 1,2p; '
    'echo "=== видеопамять ==="; '
    'nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null; '
    'echo "=== диск ==="; df -BG / | tail -1'
)


def main() -> None:
    ins = S.instances()
    if not ins:
        sys.exit('нет запущенных нод — мерить не на чем')
    for i in ins[:int(sys.argv[1]) if len(sys.argv) > 1 else 1]:
        print(f'--- нода {i["id"][:8]} (порт {i["port"]}) ---')
        try:
            print(S.ssh_text(i['port'], REMOTE, timeout=150).strip()[-900:])
        except Exception as e:  # noqa: BLE001 — одна недоступная нода не рушит замер
            print(f'  не ответила: {type(e).__name__}: {str(e)[:80]}')


if __name__ == '__main__':
    main()
