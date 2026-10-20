#!/usr/bin/env python3
"""Шаг топ-вью разбора — пределы времени и честный статус (T-20261020-15). БЕЗ рендера и сети.

20.10 один проход `topview_render` завис дольше своего бюджета, общий дедлайн проверялся только
между проходами, и разбор (а с ним реестр поколений) простоял 51 минуту до таймаута шага 2700 с.
Стенд гоняет `batch_show.topview_cmd` с подставным «рендером» тем же путём, что `_run_post`
(`proc_run.run_step`), и проверяет:
  1) зависший проход снимается по своему таймауту вместе с потомками, шаг — СБОЙ с причиной;
  2) таймаут после удачных проходов — тоже СБОЙ, не «ok»;
  3) обычные проходы: «нет новых» — выход и ok; дедлайн обрывает цикл между проходами;
  4) три упавших прохода — стоп и СБОЙ (как было);
  5) боевые пределы: худший шаг укладывается в ~16 мин и много меньше таймаута шага 2700 с.

Запуск: ~/venvs/scout/bin/python tests_topview_step.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch_show as B  # noqa: E402
import proc_run as PR  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(('  ✓ ' if cond else '  ✗ ') + what)
    if not cond:
        FAILS.append(what)


def fake(tmp: str, name: str, body: str) -> str:
    p = os.path.join(tmp, name)
    with open(p, 'w', encoding='utf-8') as f:
        f.write('#!/usr/bin/env bash\n' + body + '\n')
    os.chmod(p, 0o755)
    return p


def step(render: str, deadline_s: int = 60, pass_s: int = 2, kill_s: int = 1) -> tuple:
    t0 = time.time()
    rc, out = PR.run_step(B.topview_cmd(render, deadline_s, pass_s, kill_s), 120)
    return rc, out, time.time() - t0


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        print('зависший проход')
        pidf = os.path.join(tmp, 'child.pid')
        hang = fake(tmp, 'hang.sh', f'sleep 300 & echo $! > {pidf}\necho рисую\nsleep 300')
        rc, out, sec = step(hang)
        check(rc != 0, f'шаг — СБОЙ (rc={rc})')
        check(sec < 10, f'снят по таймауту прохода 2 с, а не через 300 с ({sec:.1f} с)')
        check('проход снят по таймауту 2 с' in out and 'по таймауту 1' in out, 'причина и счётчик — в выводе шага')
        child = int(open(pidf).read().strip())
        time.sleep(0.5)
        check(not alive(child), f'потомок прохода (pid {child}) погашен вместе с ним — сирот нет')

        print('таймаут после удачного прохода')
        cnt = os.path.join(tmp, 'n')
        mixed = fake(tmp, 'mixed.sh', f'n=$(cat {cnt} 2>/dev/null || echo 0); echo $((n+1)) > {cnt}\n'
                                      f'if [ "$n" -eq 0 ]; then echo "TOPVIEW_NEW 5"; exit 0; fi\nsleep 300')
        rc, out, sec = step(mixed)
        check(rc != 0, f'один удачный + один зависший — всё равно СБОЙ, не «ok» (rc={rc})')
        check('проходов 2, с ошибкой 1, по таймауту 1' in out, 'итоговая строка честная')

        print('обычные проходы')
        rc, out, _ = step(fake(tmp, 'none.sh', 'echo "TOPVIEW_NEW 0"'))
        check(rc == 0 and 'проходов 1, с ошибкой 0, по таймауту 0' in out, 'новых нет — один проход и ok')
        # дедлайн — в /bin/sh (dash на DEV): до 20.10 часы `$SECONDS` там были пусты, и цикл не кончался
        rc, out, sec = step(fake(tmp, 'more.sh', 'echo "TOPVIEW_NEW 5"; sleep 1'), deadline_s=3, pass_s=5)
        tail = out.rsplit('проходов ', 1)[-1]
        passes = int(tail.split(',')[0]) if tail[:1].isdigit() else -1
        check(rc == 0 and 2 <= passes <= 5 and sec < 10, f'дедлайн 3 с обрывает цикл между проходами ({passes} прох., {sec:.1f} с)')
        rc, out, _ = step(fake(tmp, 'bad.sh', 'echo "TOPVIEW_NEW 5"; exit 1'))
        check(rc != 0 and 'проходов 3, с ошибкой 3, по таймауту 0' in out, 'три упавших прохода — стоп и СБОЙ')

    print('боевые пределы')
    worst = B.TOPVIEW_DEADLINE_S + B.TOPVIEW_PASS_S + B.TOPVIEW_KILL_S
    check(worst <= 16 * 60, f'худший шаг {worst} с ≤ 16 мин')
    check(worst < 2700, 'и меньше таймаута шага 2700 с в _run_post')
    check(B.TOPVIEW_PASS_S > 420, f'проход {B.TOPVIEW_PASS_S} с длиннее своего бюджета 420 с — успевает выйти сам')
    check('timeout -k' in B.TOPVIEW_CMD and 'topview_render.py' in B.TOPVIEW_CMD and '--foreground' not in B.TOPVIEW_CMD,
          'боевая команда: проход под timeout на группу процессов')

    if FAILS:
        print(f'\nПРОВАЛ: {len(FAILS)}')
        sys.exit(1)
    print('\nвсе проверки прошли')


if __name__ == '__main__':
    main()
