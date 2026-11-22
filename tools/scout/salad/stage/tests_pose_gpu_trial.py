#!/usr/bin/env python3
"""Тест драйвера pose_gpu_trial.py (T-185/1) без Salad: тело группы (ресурсы РОВНО из профиля pose_camera_gpu, карта 3090, тариф low/medium), вход задания, аргументы, идемпотентный job_id, отправка и разбор результата
на поддельном шлюзе (code_sha/sha256 сверяются, «камера не прошла» ≠ отказ, результат раскладывается как у нашего прогона)."""
import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pose_gpu_trial as PT  # noqa: E402
import kit_driver as KD  # noqa: E402
import worker_stage as WS  # noqa: E402

fails = 0


def ok(cond, name, extra=''):
    global fails
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else f' — {extra}'))
    fails += 0 if cond else 1


tmp = tempfile.mkdtemp(prefix='pgt-')
glb, photo = os.path.join(tmp, 'a.glb'), os.path.join(tmp, 'a.png')
open(glb, 'wb').write(b'GLB')
open(photo, 'wb').write(b'PNG')
prof = KD.resource_profile(PT.WORK_TYPE)
ok(PT.card_name() == 'RTX 3090 (24 GB)' and prof['tier'] == 'low' and prof.get('tier_fallback') == 'medium', 'профиль pose_camera_gpu: карта 3090, тариф low → medium')
body = PT.build_body('trial-posegpu-t', 'x/y@sha256:' + 'a' * 64, 'low', 'cls', {}, 3600, 900, 4, 1, 900, worker_z='Z')
ok(body['container']['resources'] == {**KD.profile_resources(prof, ''), 'gpu_classes': ['cls']}, 'ресурсы группы — только из профиля (в build_body своих нет)', str(body['container']['resources']))
ok('KIT_WORKER_Z' in json.dumps(body) and body['container']['image'].endswith('a' * 64), 'воркер едет в env, образ — по digest')
try:
    PT.build_body('trial-posegpu-t', 'x/y@sha256:' + 'a' * 64, 'high', 'cls', {}, 3600, 900, 4, 1, 900)
    ok(False, 'тариф high — отказ')
except KD.ProfileRefused:
    ok(True, 'тариф high — отказ профиля (только low → medium, P-066)')
args = PT.pose_args('cuda')
ok(WS.check_args(args) == args and '--device' in args and args[args.index('--device') + 1] == 'cuda', 'аргументы pose_job проходят whitelist воркера')
ok(PT.input_problems({'s': {'glb': glb, 'photo': photo}}) == [] and len(PT.input_problems({'s': {'glb': '/нет', 'photo': photo}})) == 1, 'проверка входов: нет файла — причина')
z = zipfile.ZipFile(io.BytesIO(PT.input_zip({'glb': glb, 'photo': photo}, b'TAR')))
ok(sorted(z.namelist()) == ['code.tar', 'model.glb', 'photo.png'] and WS.missing_inputs('pose_job', z.namelist()) == [], 'вход задания: model.glb, photo.png, code.tar — воркер доволен')
a = argparse.Namespace(device='cuda', threads=1, out=os.path.join(tmp, 'out'), code={'sha': 'c' * 40, 'tar': b'TAR', 'tar_sha256': 'd' * 64})
d1 = PT.input_zip({'glb': glb, 'photo': photo}, b'TAR')
ok(PT.job_id('s_1', d1, a) == PT.job_id('s_1', d1, a) and PT.job_id('s_1', d1, a) != PT.job_id('s_2', d1, a) and '_' not in PT.job_id('s_1', d1, a), 'job_id идемпотентен, различает товары')
a.device = 'cpu'
ok(PT.job_id('s_1', d1, a) != PT.job_id('s_1', d1, argparse.Namespace(device='cuda', threads=1)), 'job_id различает устройство')
a.device = 'cuda'

# --- отправка и разбор на поддельном шлюзе
posted = []


class GW:
    def __init__(self, code_sha, passed):
        self.jobs, self.code_sha, self.passed, self.bad_sha = {}, code_sha, passed, False

    def call(self, method, path, timeout=30, raw=False, **kw):
        if path.endswith('/result'):
            return 200, self.jobs[path.split('/')[2]]['zip']
        jid = path.split('/')[2]
        if jid not in self.jobs:
            return 404, {}
        j = self.jobs[jid]
        return 200, {k: v for k, v in j.items() if k != 'zip'}


def make_result(passed):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zz:
        zz.writestr('pose.json', '{"camera": {}}')
        zz.writestr('04-camera/check.json', json.dumps({'passed': passed}))
        zz.writestr('check.json', json.dumps({'passed': passed}))
        zz.writestr('_code.json', '{}')
    return buf.getvalue()


def fake_post_job(gw, path, body, check_path, **kw):
    posted.append(body)
    assert body['stage'] == 'pose_job' and body['args'] == PT.pose_args('cuda') and body['code_sha'] == 'c' * 40
    data = make_result(passed=False)
    gw.jobs[body['job_id']] = {'status': 'done', 'zip': data, 'sha256': hashlib.sha256(data).hexdigest() if not gw.bad_sha else '0' * 64, 'code_sha': gw.code_sha, 'wall_s': 5.0,
                               'run_s': 4.0, 'peak_gb': 1.2, 'metrics': {'passed': False}, 'bytes': len(data), 'files': 4}
    return 202, {}, None


KD.post_job = fake_post_job
inputs = {'sku_1': {'glb': glb, 'photo': photo}}
gw = GW('c' * 40, False)
cur, why = PT.submit(gw, a, inputs, 100.0)
ok(cur and cur['ids'] and posted and posted[0]['sku'] == 'sku_1' and 'input_z' in posted[0], 'отправка: одно задание на товар, stage=pose_job, args и code_sha в теле', str(why))
st, info = PT.poll(gw, a, cur, 200.0)
ok(st == 'done' and info['ok'] == 1, '«камера не прошла» (passed=false) — результат, не отказ', f'{st} {str(info)[:200]}')
ok(os.path.isfile(os.path.join(a.out, 'sku_1', 'pose.json')) and os.path.isfile(os.path.join(a.out, 'sku_1', '04-camera', 'check.json')), 'выход разложен как у нашего прогона: <out>/<товар>/pose.json и 04-camera/check.json')
ok(os.path.isfile(os.path.join(a.out, 'items-pose.json')), 'items-pose.json записан')
gw2 = GW('e' * 40, False)
cur2, _ = PT.submit(gw2, a, inputs, 100.0)
st2, info2 = PT.poll(gw2, a, cur2, 200.0)
ok(st2 == 'failed' and 'code_sha' in json.dumps(info2, ensure_ascii=False), 'посчитано на другом коде (code_sha не тот) — отказ товара')
gw3 = GW('c' * 40, False)
gw3.bad_sha = True
cur3, _ = PT.submit(gw3, a, inputs, 100.0)
st3, info3 = PT.poll(gw3, a, cur3, 200.0)
ok(st3 == 'failed' and 'sha256' in json.dumps(info3, ensure_ascii=False), 'sha256 результата не сошёлся — отказ товара')
print('ИТОГО: ' + ('всё в норме' if not fails else f'провалов {fails}'))
sys.exit(1 if fails else 0)
