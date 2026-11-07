#!/usr/bin/env python3
"""Выбор классов GPU при пересоздании группы — `recreate_group.pick_gpu` (T-20261020-17). БЕЗ сети.

20.10 владелец решил: группы только на A5000 (новые 3090 умирают на первом задании). Список
`gpu_classes` задаётся один раз при создании — ошибка в нём стоит пересоздания группы, а старое
имя Salad после удаления не отдаёт. Стенд проверяет:
  1) «RTX A5000» → ровно id A5000 образца, а не «RTX 3090 Ti» и не похожие имена;
  2) регистр и пробелы не важны, повтор не дублирует id, порядок — как в запросе;
  3) класса нет у образца (в том числе есть у организации, но не у образца) — отказ;
  4) неоднозначное имя («RTX 3060» при 12 и 8 GB у образца) — отказ, а не тихий выбор;
  5) `pick_gpu_exact` (21.10, проба 3090 Ti): точное полное имя среди ВСЕХ классов организации — класс, которого
     нет у образца, берётся; неполное имя, имя без памяти, неизвестное и двойное совпадение — отказ.

Запуск: ~/venvs/scout/bin/python tests_recreate_group.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import recreate_group as R  # noqa: E402

FAILS: list[str] = []

# имена — как отдаёт GET /organizations/<org>/gpu-classes (20.10)
CLASSES = {
    'ed563892': 'RTX 4090 (24 GB)', 'a5db5c50': 'RTX 3090 (24 GB)', '6d4e9e99': 'RTX A5000 (24 GB)',
    '9998fe42': 'RTX 3090 Ti (24 GB)', 'f51baccc': 'RTX 3060 (12 GB)', '69071b6c': 'RTX 3060 (8 GB)',
    '851399fb': 'RTX 5090 (32 GB)',
}
DONOR = ['ed563892', 'a5db5c50', '6d4e9e99', '9998fe42']      # боевые группы mesh-low-6/7


def check(cond: bool, what: str) -> None:
    print(('  ✓ ' if cond else '  ✗ ') + what)
    if not cond:
        FAILS.append(what)


def refused(wanted: list[str], donor: list[str] = DONOR) -> str:
    try:
        R.pick_gpu(donor, CLASSES, wanted)
    except ValueError as e:
        return str(e)
    return ''


def main() -> None:
    check(R.pick_gpu(DONOR, CLASSES, ['RTX A5000']) == ['6d4e9e99'], 'RTX A5000 → только id A5000')
    check(R.pick_gpu(DONOR, CLASSES, ['RTX 3090']) == ['a5db5c50'], 'RTX 3090 → не цепляет 3090 Ti')
    check(R.pick_gpu(DONOR, CLASSES, [' rtx a5000 ', 'RTX 4090', 'RTX A5000']) == ['6d4e9e99', 'ed563892'],
          'регистр и пробелы не важны, повтор не дублирует, порядок как в запросе')
    check('совпадений 0' in refused(['RTX 5090']), 'класс есть у организации, но не у образца — отказ')
    check('совпадений 0' in refused(['A5000']), 'неполное имя — отказ, а не поиск подстроки')
    check('совпадений 2' in refused(['RTX 3060'], ['f51baccc', '69071b6c']), 'одноимённые классы разной памяти — отказ')
    check(bool(refused(['RTX A5000'], [])), 'у образца нет классов — отказ')

    def exact_refused(wanted: list[str], classes: dict = CLASSES) -> str:
        try:
            R.pick_gpu_exact(classes, wanted)
        except ValueError as e:
            return str(e)
        return ''
    check(R.pick_gpu_exact(CLASSES, ['RTX 3090 Ti (24 GB)']) == ['9998fe42'], 'точное имя → id 3090 Ti, не 3090')
    check(R.pick_gpu_exact(CLASSES, ['RTX 5090 (32 GB)']) == ['851399fb'], 'класс организации, которого нет у образца, — берётся')
    check(R.pick_gpu_exact(CLASSES, [' rtx 3090 ti (24 gb) ', 'RTX 3090 Ti (24 GB)']) == ['9998fe42'],
          'регистр и крайние пробелы не важны, повтор не дублирует')
    check('совпадений 0' in exact_refused(['RTX 3090 Ti']), 'имя без памяти — отказ (не подстрока)')
    check('совпадений 0' in exact_refused(['RTX 3060']), 'одноимённые классы разной памяти без памяти в имени — отказ')
    check('совпадений 0' in exact_refused(['RTX 9999 (24 GB)']), 'неизвестный класс — отказ')
    check('совпадений 2' in exact_refused(['RTX 3090 Ti (24 GB)'], dict(CLASSES, dup='RTX 3090 Ti (24 GB)')),
          'два класса с одним полным именем — отказ')

    # опытная группа (T-20261106-85): --image только наш репозиторий по digest, --env поверх образца, секреты не трогаем
    dig = 'ghcr.io/igortsk123/mesh-hunyuan@sha256:' + 'ab' * 32

    def body() -> dict:
        return {'container': {'image': 'BOEVOY', 'environment_variables': {'RECEIVER_TOKEN': 's', 'PIPELINE_VERSION': 'v2'}}}

    def ov_refused(image, env) -> str:
        try:
            R.apply_overrides(body(), image, env)
        except ValueError as e:
            return str(e)
        return ''
    b = R.apply_overrides(body(), None, [])
    check(b['container']['image'] == 'BOEVOY' and b['container']['environment_variables']['PIPELINE_VERSION'] == 'v2',
          'без --image/--env — образ и переменные образца (боевой по умолчанию)')
    b = R.apply_overrides(body(), dig, ['PIPELINE_VERSION=color03', 'DUMP_MAX=512'])
    check(b['container']['image'] == dig and b['container']['environment_variables'] ==
          {'RECEIVER_TOKEN': 's', 'PIPELINE_VERSION': 'color03', 'DUMP_MAX': '512'},
          '--image по digest и --env поверх образца, секрет образца цел')
    check(bool(ov_refused('ghcr.io/igortsk123/mesh-hunyuan:color03-x', [])), 'образ по тегу — отказ (только digest)')
    check(bool(ov_refused('ghcr.io/other/mesh-hunyuan@sha256:' + 'ab' * 32, [])), 'чужой репозиторий — отказ')
    check('секреты' in ov_refused(None, ['RECEIVER_TOKEN=x']), 'переопределить секрет — отказ')
    check(bool(ov_refused(None, ['pipeline_version=x'])) and bool(ov_refused(None, ['NOEQ'])), 'кривой ключ или без = — отказ')

    # queue_setup.build: опытный образ — только у канарейки, боевой по умолчанию; переменные поверх образца
    import migrate_groups as MG
    import queue_setup as QS
    MG.ghcr_auth = lambda: {}
    # боевая группа-очередь в проверках ниже — «выключенная, как при создании» (queue_setup.py:94), а не по живому rules:
    # `disabled` у mesh-q-low-1 снимают под волны (T-20261107-06/2), и отказ «только у канарейки» не должен от этого зависеть
    _info = QS.SG.info
    QS.SG.info = lambda g, _i=_info: {**_i(g), 'disabled': True} if g == 'mesh-q-low-1' else _i(g)
    donor = {'container': {'image': MG.IMAGE, 'resources': {'cpu': 8, 'memory': 24576, 'gpu_classes': ['x'],
                                                            'storage_amount': 1, 'shm_size': 1},
                           'environment_variables': {'RECEIVER_TOKEN': 's', 'PIPELINE_VERSION': 'v2'}, 'command': []}}

    def qs_refused(group, queue, image) -> str:
        try:
            QS.build(donor, group, queue, 1, QS.PROXY_PORT, image, ['PIPELINE_VERSION=color03'])
        except SystemExit as e:
            return str(e)
        return ''
    qb = QS.build(donor, 'mesh-q-color-canary', 'mesh-q-color', 1, QS.PROXY_PORT, dig, ['PIPELINE_VERSION=color03'])
    check(qb['container']['image'] == dig and qb['container']['environment_variables']['PIPELINE_VERSION'] == 'color03'
          and qb['container']['environment_variables']['RECEIVER_TOKEN'] == 's' and qb['autostart_policy'] is False
          and qb['queue_connection']['queue_name'] == 'mesh-q-color',
          'queue_setup: канарейка color на опытном образе, PIPELINE_VERSION=color03, остановлена, своя очередь')
    check(QS.build(donor, 'mesh-q-color-canary', 'mesh-q-color', 1)['container']['image'] == MG.IMAGE,
          'queue_setup без --image — боевой образ')
    check('только у канарейки' in qs_refused('mesh-q-low-1', 'mesh-q-low', dig), 'опытный образ у боевой группы — отказ')
    check('digest' in qs_refused('mesh-q-color-canary', 'mesh-q-color', 'ghcr.io/igortsk123/mesh-hunyuan:latest')
          or 'sha256' in qs_refused('mesh-q-color-canary', 'mesh-q-color', 'ghcr.io/igortsk123/mesh-hunyuan:latest'),
          'queue_setup: образ по тегу — отказ')

    # queue_setup --gpu-exact (T-20261106-85/3): свои классы GPU — только у канарейки
    gb = QS.build(donor, 'mesh-q-color-canary', 'mesh-q-color', 1, QS.PROXY_PORT, dig, [], ['g4060'])
    check(gb['container']['resources']['gpu_classes'] == ['g4060'], 'queue_setup: канарейка на заданном классе GPU')
    check(QS.build(donor, 'mesh-q-color-canary', 'mesh-q-color', 1)['container']['resources']['gpu_classes'] == ['x'],
          'queue_setup без --gpu-exact — классы образца')
    try:
        QS.build(donor, 'mesh-q-low-1', 'mesh-q-low', 1, QS.PROXY_PORT, None, [], ['g4060'])
        gpu_err = ''
    except SystemExit as e:
        gpu_err = str(e)
    check('только у канарейки' in gpu_err, 'queue_setup: свои классы GPU у боевой группы-очереди — отказ')
    QS.SG.info = _info

    # recreate_group.self_donor_refusal (T-20261106-85/3): группа-очередь по самой себе — отказ с подсказкой
    check('queue_setup' in R.self_donor_refusal('mesh-q-color-canary', None), 'группа-очередь без --donor (по себе) — отказ')
    check('queue_setup' in R.self_donor_refusal('mesh-q-color-canary', 'mesh-q-color-canary'), '--donor = сама группа — отказ')
    check(R.self_donor_refusal('mesh-q-color-canary', 'mesh-q-low-1') == '', 'группа-очередь по другому образцу — можно')
    check(R.self_donor_refusal('mesh-low-4', None) == '', 'обычная группа по себе — как раньше, можно')

    # recreate_group.keep_queue (T-20261106-85/3): группа-очередь пересоздаётся со своей связью, прочие — без неё
    qc = {'path': '/generate', 'port': 8001, 'queue_name': 'mesh-q-color'}

    def kq(group, donor_qc) -> str | dict:
        try:
            return R.keep_queue({'name': group, 'queue_connection': {'stale': 1}}, {'queue_connection': donor_qc}, group)
        except ValueError as e:
            return str(e)
    got = kq('mesh-q-color-canary', qc)
    check(isinstance(got, dict) and got['queue_connection'] == qc, 'канарейка-очередь: связь образца перенесена')
    check('не пересоздаю' in kq('mesh-q-color-canary', None), 'группа-очередь, у образца связи нет — отказ (не pending-сирота)')
    check('не пересоздаю' in kq('mesh-q-color-canary', dict(qc, queue_name='mesh-q-low')), 'связь на чужую очередь — отказ')
    got = kq('mesh-low-4', qc)
    check(isinstance(got, dict) and 'queue_connection' not in got, 'группа без очереди в правилах — связи нет, даже если у образца есть')

    if FAILS:
        print(f'\nПРОВАЛ: {len(FAILS)}')
        sys.exit(1)
    print('\nвсе проверки прошли')


if __name__ == '__main__':
    main()
