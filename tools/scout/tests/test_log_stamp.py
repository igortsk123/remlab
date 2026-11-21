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
import post_stall
print('FILENO=' + str(sys.stdout.fileno()) + ',' + str(sys.stderr.fileno()), flush=True)
post_stall._dump_stacks('заголовок дампа стеков')
subprocess.run(['sh', '-c', 'echo вывод в stdout=sys.stdout'], stdout=sys.stdout)
subprocess.run(['sh', '-c', 'echo вывод в stderr=sys.stderr 1>&2'], stderr=sys.stderr)
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
ok(any(ln.endswith('FILENO=1,2') for ln in lines), 'sys.stdout/stderr.fileno() — настоящие 1 и 2 (при fd_capture)')
k = next((i for i, ln in enumerate(lines) if 'заголовок дампа стеков' in ln), -1)
dump = [ln for ln in lines[k + 1:] if 'Thread 0x' in ln or 'Current thread' in ln or re.search(r'\] +File "', ln)] if k >= 0 else []
ok(k >= 0 and len(dump) >= 2 and all(LS.STAMP_RE.match(ln) for ln in dump), f'post_stall._dump_stacks (faulthandler.dump_traceback в sys.stderr) проходит, строки стеков со штампом ({len(dump)})')
ok(any('[-|-] вывод в stdout=sys.stdout' in ln for ln in lines) and any('[-|-] вывод в stderr=sys.stderr' in ln for ln in lines), 'subprocess.run(…, stdout=sys.stdout / stderr=sys.stderr) работает, строки со штампом')
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
CHILD2 = r"""
import faulthandler, os, subprocess, sys
sys.path.insert(0, %(scout)r)
import log_stamp as LS
LS.install(fd_capture=False)
print('FILENO2=' + str(sys.stdout.fileno()) + ',' + str(sys.stderr.fileno()), flush=True)
faulthandler.dump_traceback(file=sys.stderr)
subprocess.run(['sh', '-c', 'echo прямой вывод ребёнка'], stdout=sys.stdout)
print('конец', flush=True)
"""
out2 = os.path.join(TMP, 'journal2.log')
with open(out2, 'wb') as f:
    subprocess.run([sys.executable, '-I', '-c', CHILD2 % {'scout': SCOUT}], stdout=f, stderr=f, timeout=60, cwd=TMP)
l2 = open(out2, encoding='utf-8').read().splitlines()
fn = next((ln for ln in l2 if 'FILENO2=' in ln), '')
ok(bool(re.search(r'FILENO2=(\d+),(\d+)$', fn)) and not fn.endswith('FILENO2=1,2'), 'без fd_capture fileno — копии исходных дескрипторов (не 1/2)')
ok(any('Thread 0x' in ln or 'Current thread' in ln for ln in l2) and any('прямой вывод ребёнка' in ln for ln in l2) and any('[-|-] конец' in ln for ln in l2), 'без fd_capture: дамп faulthandler и stdout=sys.stdout работают (сырые строки без штампа — как задокументировано), питоновые — со штампом')
# запись до конца: os.write пишет по 3 байта
_real = os.write
class _Part:
    got = b''
def _w(fd, data):
    n = min(3, len(data))
    _Part.got += bytes(data[:n])
    return n
os.write = _w
try:
    LS.write_all(99, 'проверка записи целиком\n'.encode())
finally:
    os.write = _real
ok(_Part.got == 'проверка записи целиком\n'.encode(), 'write_all дописывает хвост при неполной записи os.write')
print('ИТОГО:', 'ЧИСТО' if not BAD else f'{len(BAD)} FAIL')
sys.exit(1 if BAD else 0)
