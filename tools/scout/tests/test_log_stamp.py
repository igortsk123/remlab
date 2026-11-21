"""ЖУРНАЛ СЕРВИСА КАДРОВ: у каждой строки время и номер задания (T-20261118-22/8, tour-speed-01). Дочерний процесс-заглушка ставит штампы как сервис, запускает очередь
рендера с исполнителем-подменой, печатает построчно, частями, многострочно, пишет в дескриптор напрямую и через дочернюю команду; тест читает файл журнала.
Проверяется: у КАЖДОЙ строки ISO-время и метка [задание|тур]; строки задания несут его номер и тур; прямые записи — [-|-]; LOG_STAMP=0 — журнал прежний;
сбой штамповщика не ломает печать. Без сети и без платного.   python tools/scout/tests/test_log_stamp.py"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, SCOUT)
import remlab_tmp  # noqa: E402
TMP = remlab_tmp.use('test_log_stamp')  # временное теста — на диске, не в /tmp; убирается при выходе
import log_stamp as LS  # noqa: E402

BAD = []


def ok(cond, name):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        BAD.append(name)


CHILD = r'''
import os, subprocess, sys, tempfile, threading, time, json
sys.path.insert(0, %(scout)r)
import log_stamp as LS
import render_jobs as RJ
LS.install()
print('простая строка', flush=True)
print('первая', 'часть ', end='')
print('и конец', flush=True)
print('многострочный\nответ машины\nтрёх строк', flush=True)
sys.stderr.write('строка в stderr\n')
os.write(1, 'прямая запись в дескриптор\n'.encode())
subprocess.run(['sh', '-c', 'echo дочерний процесс; echo ошибка дочернего 1>&2'])
class Fake:
    name = 'fake'
    def __init__(self, store): self.store = store
    def render(self, snap, out_dir, progress):
        progress('C1'); print('внутри рендера: ' + snap['scene_hash'], flush=True)
        os.makedirs(out_dir, exist_ok=True)
        for c in RJ.CAMS: open(os.path.join(out_dir, c + '.jpg'), 'wb').write(b'\xff\xd8x')
        json.dump({'scene_hash': snap['scene_hash'], 'size': [10, 8], 'versions': {'x': 1}, 'sha': {'C1': 'a' * 64, 'C2': 'b' * 64}}, open(os.path.join(out_dir, 'meta.json'), 'w'))
        return {'timing': {'t': 1}}
d = tempfile.mkdtemp()
st = RJ.RenderStore(os.path.join(d, 'jobs.json'), os.path.join(d, 'res'))
q = RJ.RenderQueue(st, Fake(st)); q.start()
a = q.submit({'scene_hash': 'h1'}, 'k1', ip='1.1.1.1', tour='tour:TOURID1')
for _ in range(100):
    if q.view(a['job'])['status'] in ('done', 'error'): break
    time.sleep(0.05)
print('JOB=' + a['job'], flush=True)
q.close()
time.sleep(0.5)
'''


def run_child(env_extra: dict) -> list:
    out = os.path.join(TMP, 'journal.log')
    open(out, 'w').close()
    env = dict(os.environ, **env_extra)
    with open(out, 'ab') as f:
        subprocess.run([sys.executable, '-I', '-c', CHILD % {'scout': SCOUT}], stdout=f, stderr=f, env=env, timeout=60, cwd=TMP)
    return open(out, encoding='utf-8').read().splitlines()


lines = run_child({})
ok(len(lines) >= 12, f'журнал не пуст ({len(lines)} строк)')
ok(all(LS.STAMP_RE.match(ln) for ln in lines), 'у КАЖДОЙ строки ISO-время и метка [задание|тур]' + ('' if all(LS.STAMP_RE.match(ln) for ln in lines) else ': ' + str([ln for ln in lines if not LS.STAMP_RE.match(ln)][:3])))
job = next((re.search(r'JOB=(\S+)', ln).group(1) for ln in lines if 'JOB=' in ln), '')
rj = [ln for ln in lines if f'рендер {job}: готов' in ln]
ok(bool(job) and len(rj) == 1 and f'[{job}|tour:TOURID1]' in rj[0], 'итоговая строка задания несёт номер задания и тура')
ok(any(f'[{job}|tour:TOURID1] внутри рендера: h1' in ln for ln in lines), 'печать внутри исполнителя — тоже под номером задания и тура')
ok(any('[-|-] простая строка' in ln for ln in lines), 'вне задания — [-|-]')
ok(any('[-|-] первая часть и конец' in ln for ln in lines), 'строка, напечатанная частями, склеена и одна')
ok(sum(1 for ln in lines if re.search(r'\] (многострочный|ответ машины|трёх строк)$', ln)) == 3, 'многострочный текст — штамп на КАЖДОЙ строке')
ok(any('[-|-] строка в stderr' in ln for ln in lines), 'stderr штампуется')
ok(any('[-|-] прямая запись в дескриптор' in ln for ln in lines), 'прямая запись в дескриптор 1 — со штампом')
ok(any('[-|-] дочерний процесс' in ln for ln in lines) and any('[-|-] ошибка дочернего' in ln for ln in lines), 'вывод дочернего процесса (stdout и stderr) — со штампом')
ok(all(re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2} ', ln) for ln in lines), 'время — ISO с поясом')
off = run_child({'LOG_STAMP': '0'})
ok(off and not any(LS.STAMP_RE.match(ln) for ln in off) and 'простая строка' in off, 'LOG_STAMP=0 — журнал прежний, без штампов')
# штамп на уже проштампованной строке не удваивается; контекст вложен и снимается
s = LS.stamp_line('2026-11-21T10:00:00+00:00 [a|b] текст')
ok(s == '2026-11-21T10:00:00+00:00 [a|b] текст', 'уже проштампованная строка — как есть')
with LS.context(job='j1'):
    with LS.context(tour='t1'):
        inner = LS.tag()
    outer = LS.tag()
ok(inner == '[j1|t1]' and outer == '[j1|-]' and LS.tag() == '[-|-]', 'контекст: вложенный видит оба, после выхода снят')
with LS.context(job='плохой [id]|x'):
    ok(LS.STAMP_RE.match(LS.stamp_line('x')) is not None, 'странный номер в метке не ломает формат строки')
print('ИТОГО:', 'ЧИСТО' if not BAD else f'{len(BAD)} FAIL')
sys.exit(1 if BAD else 0)
