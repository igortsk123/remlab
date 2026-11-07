#!/usr/bin/env python3
"""Спецификация банка комнаты `RoomBankSpec` — одно место для путей, правил, ключа ячейки и адаптеров цепочки банка
(план room-bank-01, этап Б; разбор Codex `.memory_bank/_intake/codex/room-bank-2026-11-06-answer.md`).

ЗАЧЕМ. Цепочка `bank_prepare → bank_pending → bank_promote → bank_refresh` писалась под гостиную: пути `sets3*.json`,
`~/scout-scenes/bank-*.json`, `bank-generations/sets3-*.json.gz`, флаги `rules/bank-candidate.json` и ключ ячейки
`(band, style, tier)` были зашиты в каждый модуль. Банк спальни — не «гостиная с другими путями»: у ячейки есть комната и
назначение, готовность — из `offer_asset_binding`, а не из `products`, экзамен и сторож демо свои. Поэтому общий движок
берёт всё комнатное отсюда, а комнаты отличаются адаптером, не `if room == 'bedroom'` по коду.

ГОСТИНАЯ (без `--room`) — ровно прежние формулы и env (`BANK_CANDIDATE`, `BANK_PREPARE_REPORT`, `BANK_PENDING`, `DEMO_DATA`,
`BANK_PROMOTE`, `BANK_PROMOTE_DIR`, `BANK_GENERATIONS`), флаги — верхний уровень `rules/bank-candidate.json` (прежний ключ —
её ключ). Вывод всех `bank_*` побайтно прежний — `tests/test_bank_spec_golden.py`.

СПАЛЬНЯ (`--room bedroom`): пути (`sets-bedroom*.json`, `~/scout-scenes/bank-bedroom-*.json`,
`bank-generations-bedroom/sets-bedroom-*.json.gz`; env с префиксом `BANK_BEDROOM_`), флаги — раздел
`rooms.bedroom` правил (нет раздела — выключено), ключ ячейки `(room_id, purpose, band, style, tier)`. С этапа Ж
(T-20261107-04/3) шаги настоящие: prepare и promote — `room_bank_chain.py`, ожидание и писатель — общие `bank_pending` /
`bank_refresh` (писатель добавляет новые ячейки в хвост, вид журнала `add`). ПРИХОЖАЯ — по-прежнему каркас (`REAL_ROOMS`):
флаг выключен — строка «выключено», включён или `--force` — отказ (код 2, «адаптер — каркас»).

  python3 room_bank_spec.py --selftest
  python3 room_bank_spec.py [--room bedroom]      # пути, флаги и адаптеры комнаты — для разбора
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
RULES_PATH = os.path.join(HERE, 'rules', 'bank-candidate.json')

LIVING = 'living'
FLAGS = ('enabled', 'prepare_enabled', 'promote_enabled', 'write_enabled')   # флаги шагов; у комнаты — свои в rooms.<комната>


@dataclasses.dataclass(frozen=True)
class RoomBankSpec:
    room: str
    live: str                 # живой банк комнаты (пишет только bank_refresh)
    candidate: str            # кандидат (bank_prepare, bank_promote; env)
    candidate_default: str    # кандидат без env — так читает bank_pending (прежнее поведение гостиной)
    prepare_report: str
    pending_state: str
    demo_data: str            # опубликованное демо: ячейки вариантов (ярус «ячейка демо»)
    promote_manifest: str
    promote_work: str
    generations: str          # снимки-поколения, журнал, запрет отката, намерение
    lock: str                 # экзамен идёт — писатель ждёт
    snap_prefix: str          # снимок поколения `<префикс>-<поколение>.json.gz`
    rules_path: str
    cell_fields: tuple
    profile: str              # rules/profiles/<профиль>.json → composer.plugin → room_profile.COMPOSERS
    compose_args: tuple       # аргументы сборщика в ночи
    catalog: str              # откуда медиа и наличие
    readiness: str            # откуда «меш готов»
    strict: str               # строгая чистота ячейки
    exam: str                 # экзамен смешанного банка
    demo: str                 # сторож демо
    skeleton: bool            # адаптер — каркас: шаги не пишут

    # ——— правила и флаги ———
    def view(self, raw: dict) -> dict:
        """Правила комнаты из общего файла. Гостиная — файл как есть (прежнее поведение); другая комната — ТОЛЬКО свой раздел
        `rooms.<комната>`, флаги шагов по умолчанию выключены (правила гостиной — диван, доли, экзамен — ей не наследуются)."""
        if self.room == LIVING:
            return raw
        return {**{f: False for f in FLAGS}, **((raw.get('rooms') or {}).get(self.room) or {})}

    def rules(self) -> dict:
        try:
            return self.view(json.load(open(self.rules_path, encoding='utf-8')))
        except (OSError, ValueError):
            return {}

    def flag_ref(self, name: str) -> str:
        """Где флаг в правилах — для строк «выключено (rules/bank-candidate.json:<ключ>=false)»."""
        return name if self.room == LIVING else f'rooms.{self.room}.{name}'

    # ——— ключ ячейки ———
    def cell(self, s: dict) -> tuple:
        if self.room == LIVING:
            import set_identity as SID
            return SID.cell(s)
        return tuple(s.get(f) for f in self.cell_fields)

    def key(self, s: dict) -> str:
        return '|'.join(str(x) for x in self.cell(s))

    # ——— писатель и откат ———
    def refresh_paths(self) -> dict:
        """Пути писателя (`bank_refresh.paths`). У гостиной — ровно прежние 7 ключей; у другой комнаты ещё `room` (manifest
        чужой комнаты — отказ) и `snap` (префикс снимка)."""
        P = {'live': self.live, 'lock': self.lock, 'manifest': self.promote_manifest, 'gen': self.generations,
             'journal': os.path.join(self.generations, 'journal.jsonl'), 'hold': os.path.join(self.generations, 'hold.json'),
             'intent': os.path.join(self.generations, 'intent.json')}
        if self.room != LIVING:
            P.update(room=self.room, snap=self.snap_prefix)
        return P

    # ——— адаптеры ———
    def composer(self) -> tuple[str, str | None]:
        """(плагин, путь к сборщику) из профиля комнаты (`room_profile.COMPOSERS`)."""
        import room_profile as RP
        plugin = (RP.raw(self.profile).get('composer') or {}).get('plugin')
        rel = RP.COMPOSERS.get(plugin)
        return plugin, (os.path.join(ROOT, rel) if rel else None)

    def load_facts(self):
        """Факты готовности. Гостиная — `bank_ready.load_facts` (products); спальня — привязки `offer_asset_binding` (этап В)."""
        if self.readiness == 'bank_ready':
            import bank_ready as BR
            return BR.load_facts()
        import room_ready as RR       # этап В (T-20261106-70): правило одно с витриной — `room_bindings.usable`
        return RR.load_facts(mode=self.rules().get('mesh_gate') or 'orient', demo_data=self.demo_data)

    def classify(self, role: str, sku: str, item, F) -> tuple:
        """Готов ли показываемый товар → (тип, причина, need). Гостиная — `bank_ready.classify`; спальня — `room_ready.classify`."""
        if self.readiness == 'bank_ready':
            import bank_ready as BR
            return BR.classify(role, sku, item, F)
        import room_ready as RR
        return RR.classify(role, sku, item, F)

    def skeleton_gate(self, step: str, R: dict, flag: str, force: bool = False) -> int | None:
        """Шаг комнаты-каркаса: None — адаптер настоящий, идти дальше; иначе код выхода (ничего не пишем).
        Флаг выключен — 0 и «выключено»; включён или --force — 2: включать нечего, адаптер — каркас этапа Б."""
        if not self.skeleton:
            return None
        if not (R.get(flag) or force):
            print(f'{step}: выключено (rules/bank-candidate.json:{self.flag_ref(flag)}=false) — {self.room}: каркас этапа Б, '
                  f'ничего не пишу', flush=True)
            return 0
        print(f'ERROR:{step}: {self.room} — адаптер каркас (room-bank-01: пути, ключ ячейки и готовность — этапы Б–В; первый живой '
              f'банк — `room_bootstrap.py`); суд и писатель — этап Г. Флаг {self.flag_ref(flag)} или --force не включают его — '
              f'отказ, ничего не пишу',
              flush=True)
        return 2


def _living(env) -> RoomBankSpec:
    """Ровно прежние формулы модулей (`bank_prepare.py:43-45`, `bank_pending.py:50-53,369`, `bank_promote.py:67-70,471`,
    `bank_refresh.py:67-72` до этапа Б): `.get(k, умолчание)` и `or` — как было у каждого."""
    gen = os.path.expanduser(env.get('BANK_GENERATIONS') or os.path.join(HERE, 'bank-generations'))
    return RoomBankSpec(
        room=LIVING, live=os.path.join(HERE, 'sets3.json'),
        candidate=os.path.abspath(env.get('BANK_CANDIDATE') or os.path.join(HERE, 'sets3.next.json')),
        candidate_default=os.path.join(HERE, 'sets3.next.json'),
        prepare_report=os.path.expanduser(env.get('BANK_PREPARE_REPORT', '~/scout-scenes/bank-prepare.json')),
        pending_state=os.path.expanduser(env.get('BANK_PENDING', '~/scout-scenes/bank-pending.json')),
        demo_data=os.path.expanduser(env.get('DEMO_DATA', '~/scout-scenes/flat215-demo/demo-data.json')),
        promote_manifest=os.path.expanduser(env.get('BANK_PROMOTE', '~/scout-scenes/bank-promote.json')),
        promote_work=os.path.expanduser(env.get('BANK_PROMOTE_DIR', '~/scout-scenes/bank-promote')),
        generations=gen, lock=os.path.join(HERE, 'exam.lock'), snap_prefix='sets3', rules_path=RULES_PATH,
        cell_fields=('band', 'style', 'tier'), profile='living', compose_args=('--style', '--bands', 'all'),
        catalog='products (catalog_media.sync_sets)', readiness='bank_ready',
        strict='bank_promote.strict (слоты, пары, роли, столовая Z4)', exam='acceptance_run.py zoned (acceptance-scenes.json)',
        demo='flat215_demo.choose_banks (6 вариантов)', skeleton=False)


def _room(room: str, env) -> RoomBankSpec:
    """Комната кроме гостиной: всё своё, ни одного общего с гостиной файла, кроме правил и замка экзамена."""
    import bank_paths as BPa
    base = BPa.ROOM_BANKS[room]                          # 'sets-bedroom'
    E = f'BANK_{room.upper()}_'
    sc = lambda var, name: os.path.expanduser(env.get(E + var) or f'~/scout-scenes/bank-{room}-{name}')  # noqa: E731
    return RoomBankSpec(
        room=room, live=os.path.join(HERE, f'{base}.json'),
        candidate=os.path.abspath(env.get(E + 'CANDIDATE') or os.path.join(HERE, f'{base}.next.json')),
        candidate_default=os.path.join(HERE, f'{base}.next.json'),
        prepare_report=sc('PREPARE_REPORT', 'prepare.json'), pending_state=sc('PENDING', 'pending.json'),
        demo_data=os.path.expanduser(env.get(E + 'DEMO_DATA') or '~/scout-scenes/flat215-demo/demo-data.json'),
        promote_manifest=sc('PROMOTE', 'promote.json'), promote_work=sc('PROMOTE_DIR', 'promote'),
        generations=os.path.expanduser(env.get(E + 'GENERATIONS') or os.path.join(HERE, f'bank-generations-{room}')),
        lock=os.path.join(HERE, 'exam.lock'),           # общий: экзамен своей комнаты появится на этапе Г — пока ждём любой
        snap_prefix=base, rules_path=RULES_PATH,
        cell_fields=('room_id', 'purpose', 'band', 'style', 'tier'), profile=room, compose_args=(),
        catalog='room_catalog (catalog_items)', readiness='offer_asset_binding',
        strict='room_guards.strict_cell (каталог сейчас)', exam='room_guards.exam_cell + bank_problems (смешанный банк)',
        demo=('room_guards.demo_problems (old/hybrid)' if room == 'bedroom' else 'нет показа — пропуск строкой'),
        # этап Ж (T-20261107-04/3): у спальни шаги настоящие (`room_bank_chain` + общие bank_pending/bank_refresh); прихожая — каркас
        skeleton=room not in REAL_ROOMS)


ROOMS = (LIVING, 'bedroom', 'hall')    # прихожая — T-20261106-89 шаг 2: каркас (свои пути, флаги rooms.hall.*)
REAL_ROOMS = ('bedroom',)              # комнаты с настоящими шагами цепочки (этап Ж); остальные — каркас `skeleton_gate`


def for_room(room: str | None = None, env=None) -> RoomBankSpec:
    """Спецификация комнаты; None/'living' — гостиная (прежнее поведение). Env читается в момент вызова."""
    env = os.environ if env is None else env
    room = room or LIVING
    if room == LIVING:
        return _living(env)
    if room not in ROOMS:
        raise SystemExit(f'--room {room}: банка такой комнаты нет (есть: {", ".join(ROOMS)})')
    return _room(room, env)


def room_arg(argv: list) -> tuple[str | None, list]:
    """`--room X` из argv → (комната или None, argv без этой пары)."""
    if '--room' not in argv:
        return None, list(argv)
    i = argv.index('--room')
    if i + 1 >= len(argv):
        raise SystemExit('--room без значения')
    return argv[i + 1], argv[:i] + argv[i + 2:]


# ——— привязка модуля к комнате ———
BIND = {      # имя глобала модуля → поле спецификации (только то, что модуль держит константой)
    'bank_prepare': {'RULES_PATH': 'rules_path', 'LIVE': 'live', 'CANDIDATE': 'candidate', 'REPORT': 'prepare_report'},
    'bank_pending': {'RULES_PATH': 'rules_path', 'STATE': 'pending_state', 'CANDIDATE': 'candidate_default', 'LIVE': 'live',
                     'DEMO_DATA': 'demo_data', 'PREPARE_REPORT': 'prepare_report'},
    'bank_promote': {'RULES_PATH': 'rules_path', 'LIVE': 'live', 'CANDIDATE': 'candidate', 'MANIFEST': 'promote_manifest',
                     'WORK': 'promote_work'},
    'bank_refresh': {'RULES_PATH': 'rules_path'},
    'bank_keep': {'RULES_PATH': 'rules_path'},
}


def bind(module, spec: RoomBankSpec, name: str | None = None) -> RoomBankSpec:
    """Переключить константы модуля на комнату (CLI с `--room`). `name` — имя модуля цепочки: запущенный скриптом модуль
    называется `__main__`. Гостиная по умолчанию задаётся при импорте теми же полями спецификации."""
    name = name or module.__name__.rsplit('.', 1)[-1]
    if name not in BIND:
        raise KeyError(f'bind: {name} — не модуль цепочки банка')
    module.SPEC = spec
    for g, f in BIND[name].items():
        setattr(module, g, getattr(spec, f))
    return spec


def describe(spec: RoomBankSpec) -> dict:
    d = dataclasses.asdict(spec)
    try:
        d['composer'] = spec.composer()
    except Exception as e:  # noqa: BLE001 — разбор, не решение
        d['composer'] = f'{type(e).__name__}: {e}'
    d['flags'] = {f: bool(spec.rules().get(f)) for f in FLAGS}
    return d


def _selftest() -> int:
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
    remlab_tmp.use('room_bank_spec-selftest')
    import tempfile
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1

    L, B = for_room(None, {}), for_room('bedroom', {})
    home = os.path.expanduser('~')
    ok('гостиная без env — прежние пути', (L.live, L.candidate, L.candidate_default, L.prepare_report, L.pending_state,
       L.promote_manifest, L.promote_work, L.generations, L.lock) == (
       os.path.join(HERE, 'sets3.json'), os.path.join(HERE, 'sets3.next.json'), os.path.join(HERE, 'sets3.next.json'),
       f'{home}/scout-scenes/bank-prepare.json', f'{home}/scout-scenes/bank-pending.json',
       f'{home}/scout-scenes/bank-promote.json', f'{home}/scout-scenes/bank-promote', os.path.join(HERE, 'bank-generations'),
       os.path.join(HERE, 'exam.lock')), L)
    env = {'BANK_CANDIDATE': 'rel.json', 'BANK_PREPARE_REPORT': '~/r.json', 'BANK_PENDING': '/p.json', 'DEMO_DATA': '/d.json',
           'BANK_PROMOTE': '/m.json', 'BANK_PROMOTE_DIR': '/w', 'BANK_GENERATIONS': '~/g'}
    E = for_room(None, env)
    ok('гостиная: env как раньше (BANK_CANDIDATE — abspath; pending читает кандидат без env)',
       E.candidate == os.path.abspath('rel.json') and E.candidate_default == L.candidate_default
       and E.prepare_report == f'{home}/r.json' and E.pending_state == '/p.json' and E.demo_data == '/d.json'
       and E.promote_manifest == '/m.json' and E.promote_work == '/w' and E.generations == f'{home}/g', E)
    E2 = for_room(None, {'BANK_PREPARE_REPORT': '', 'BANK_GENERATIONS': '', 'BANK_CANDIDATE': ''})
    ok('гостиная: пустой env — как раньше (.get → пусто; or → умолчание)', E2.prepare_report == ''
       and E2.generations == L.generations and E2.candidate == L.candidate)
    ok('гостиная: пути писателя — ровно прежние 7 ключей', list(L.refresh_paths()) ==
       ['live', 'lock', 'manifest', 'gen', 'journal', 'hold', 'intent'])
    lp = {v for k, v in L.refresh_paths().items() if k != 'lock'} | {L.candidate, L.prepare_report, L.pending_state,
                                                                      L.promote_manifest, L.promote_work}
    bp = {v for k, v in B.refresh_paths().items() if k not in ('lock', 'room', 'snap')} | {
        B.candidate, B.prepare_report, B.pending_state, B.promote_manifest, B.promote_work}
    ok('спальня: ни одного общего пути с гостиной (кроме замка экзамена)', not (lp & bp), lp & bp)
    ok('спальня: пути каркаса', B.live == os.path.join(HERE, 'sets-bedroom.json')
       and B.candidate == os.path.join(HERE, 'sets-bedroom.next.json')
       and B.prepare_report == f'{home}/scout-scenes/bank-bedroom-prepare.json'
       and B.generations == os.path.join(HERE, 'bank-generations-bedroom') and B.snap_prefix == 'sets-bedroom'
       and B.refresh_paths()['room'] == 'bedroom', B)
    ok('спальня: env свой (BANK_BEDROOM_*), env гостиной её не трогает',
       for_room('bedroom', env) == B and for_room('bedroom', {'BANK_BEDROOM_GENERATIONS': '/bg',
                                                               'BANK_BEDROOM_PROMOTE': '/bm.json'}).refresh_paths()['gen'] == '/bg')
    import bank_paths as BPa
    ok('спальня: кандидат — тот же, куда пишет сборщик комнаты (bank_paths.room_bank_output)',
       B.candidate == BPa.room_bank_output({}, 'bedroom'))
    s = {'room_id': 'r2', 'purpose': 'double', 'band': 'S', 'style': 'скандинавский', 'tier': 'эконом', 'items': {}}
    ok('ключ ячейки: гостиная band|style|tier (как bank_pending.key), спальня room_id|purpose|band|style|tier',
       L.key(s) == 'S|скандинавский|эконом' and B.key(s) == 'r2|double|S|скандинавский|эконом'
       and B.key({**s, 'purpose': 'kids'}) != B.key(s))
    raw = {'enabled': True, 'write_enabled': True, 'hidden_roles': ['диван'], 'rooms': {'bedroom': {'write_enabled': True}}}
    ok('правила: гостиная — файл как есть; спальня — только свой раздел, флаги по умолчанию выключены',
       L.view(raw) is raw and B.view(raw) == {'enabled': False, 'prepare_enabled': False, 'promote_enabled': False,
                                              'write_enabled': True} and B.view({'write_enabled': True})['write_enabled'] is False)
    ok('ссылка на флаг: гостиная — прежний ключ, спальня — rooms.bedroom.*',
       L.flag_ref('write_enabled') == 'write_enabled' and B.flag_ref('write_enabled') == 'rooms.bedroom.write_enabled')
    # флаги спальни — решение ведущего (write — T-77/2; prepare/promote — этап Ж, T-20261107-04/4): селфтест не держит их
    # значения, только форму — bool, и подмена без подготовки невозможна (promote_enabled ⇒ prepare_enabled)
    bf = B.rules()
    ok('правила в файле: флаги спальни prepare/promote/write — bool; promote только при prepare',
       all(isinstance(bf.get(k, False), bool) for k in ('prepare_enabled', 'promote_enabled', 'write_enabled'))
       and (not bf.get('promote_enabled') or bf.get('prepare_enabled') is True), bf)
    H = for_room('hall', {})
    hp = {v for k, v in H.refresh_paths().items() if k not in ('lock', 'room', 'snap')} | {
        H.candidate, H.prepare_report, H.pending_state, H.promote_manifest, H.promote_work}
    ok('прихожая (T-89): свои пути, ни одного общего с гостиной и спальней (кроме замка экзамена)',
       not (hp & lp) and not (hp & bp) and H.live == os.path.join(HERE, 'sets-hall.json')
       and H.candidate == BPa.room_bank_output({}, 'hall') and H.generations == os.path.join(HERE, 'bank-generations-hall')
       and H.prepare_report == f'{home}/scout-scenes/bank-hall-prepare.json', (hp & lp, hp & bp))
    ok('прихожая: каркас, ключ ячейки как у спальни, сборщик compose_hall.py; в файле суд, подготовка и запись выключены',
       H.skeleton and H.cell_fields == B.cell_fields and H.composer() == ('hall', os.path.join(HERE, 'compose_hall.py'))
       and not any(H.rules().get(f) for f in FLAGS if f != 'enabled')
       and H.flag_ref('prepare_enabled') == 'rooms.hall.prepare_enabled',
       (H.composer(), H.rules()))
    import io
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        g = (L.skeleton_gate('x', {}, 'write_enabled'), B.skeleton_gate('x', {}, 'write_enabled'),
             H.skeleton_gate('x', {}, 'write_enabled'), H.skeleton_gate('x', {'write_enabled': True}, 'write_enabled'),
             H.skeleton_gate('x', {}, 'write_enabled', True))
    ok('каркас: гостиная и спальня (этап Ж) идут дальше; прихожая выключена — 0, включена или --force — отказ 2',
       g == (None, None, 0, 2, 2) and not B.skeleton, g)
    ok('сборщик ночи гостиной: та же команда, что до этапа Б (compose2.py --style --bands all)',
       [L.composer()[1], *L.compose_args] == [os.path.join(HERE, 'compose2.py'), '--style', '--bands', 'all'])
    ok('сборщик из профиля: гостиная compose2.py, спальня compose_bedroom.py',
       L.composer() == ('living_legacy', os.path.join(HERE, 'compose2.py'))
       and B.composer() == ('bedroom', os.path.join(HERE, 'compose_bedroom.py')), (L.composer(), B.composer()))
    import room_ready as RR
    Fb = RR.Facts({}, '', set(), {})
    ok('готовность спальни — из привязки (`room_ready`, этап В): кровать без привязки ждёт меш, лампа готова',
       B.classify('кровать', '1:a', None, Fb) == ('wait_asset', 'привязка none: no_asset', 'mesh')
       and B.classify('лампа', '1:a', None, Fb)[0] == 'ready')
    ok('room_arg: без --room — None и argv как есть; с ним — пара вынута',
       room_arg(['list']) == (None, ['list']) and room_arg(['--room', 'bedroom', 'list', '-x']) == ('bedroom', ['list', '-x']))
    try:
        for_room('kitchen', {})
        ok('неизвестная комната — отказ', False)
    except SystemExit:
        ok('неизвестная комната — отказ', True)
    with tempfile.TemporaryDirectory() as td:
        import types
        m = types.ModuleType('bank_promote')
        bind(m, B)
        m2 = types.ModuleType('__main__')
        bind(m2, B, 'bank_pending')
        ok('bind: константы модуля — из спецификации комнаты (и у запущенного скриптом — по имени)',
           m.LIVE == B.live and m.MANIFEST == B.promote_manifest and m.CANDIDATE == B.candidate and m.SPEC is B
           and m2.STATE == B.pending_state and m2.CANDIDATE == B.candidate_default and td)
    global RULES_PATH
    with tempfile.TemporaryDirectory() as td:
        saved, RULES_PATH = RULES_PATH, os.path.join(td, 'rules.json')
        try:
            json.dump({'enabled': True, 'rooms': {'bedroom': {'enabled': True, 'publish': 'live'},
                                                  'hall': {'prepare_enabled': True, 'publish': 'next'}}}, open(RULES_PATH, 'w'))
            ok('ночь (T-89): флаги комнаты 1/0 из своего раздела; ROOM_PUBLISH из rooms.*.publish (live → комната, next → =next)',
               (night_flag('bedroom', 'enabled'), night_flag('bedroom', 'prepare_enabled'), night_flag('hall', 'enabled'),
                night_flag('hall', 'prepare_enabled')) == (1, 0, 0, 1) and room_publish() == 'bedroom,hall=next')
            json.dump({'rooms': {}}, open(RULES_PATH, 'w'))
            ok('ночь: раздела комнаты нет — всё выключено, ROOM_PUBLISH пусто (публикация только гостиной)',
               night_flag('hall', 'enabled') == 0 and room_publish() == '')
            json.dump({'publish': 'live', 'rooms': {'bedroom': {'publish': 'live'}}}, open(RULES_PATH, 'w'))
            ok('гостиная по привязке (T-20261106-77/5): ключ верхнего уровня publish=live → living первой',
               room_publish() == 'living,bedroom')
            json.dump({'publish': 'next', 'rooms': {}}, open(RULES_PATH, 'w'))
            ok('гостиная: publish=next — не публикуется (кандидат гостиной — только явным файлом)', room_publish() == '')
        finally:
            RULES_PATH = saved
    try:
        night_flag('bedroom', 'nope')
        ok('неизвестный флаг — отказ', False)
    except SystemExit:
        ok('неизвестный флаг — отказ', True)
    print(f'room_bank_spec selftest: ошибок {bad}')
    return 1 if bad else 0


# ночные флаги комнаты: шаги цепочки, репетиция записи в копию (тень, этап Е — на живое не влияет) и выкладка мешей
NIGHT_FLAGS = (*FLAGS, 'rehearse_enabled', 'publish')


def night_flag(room: str, flag: str) -> int:
    """Флаг комнаты для ночи (`refresh_daily.sh`, T-20261106-89): 1/0. Ночные флаги комнаты — `FLAGS` и `publish`; неизвестный — отказ."""
    if flag not in NIGHT_FLAGS:
        raise SystemExit(f'--flag {flag}: такого флага комнаты нет (есть: {", ".join(NIGHT_FLAGS)})')
    return 1 if for_room(room).rules().get(flag) else 0


def room_publish(rooms=None) -> str:
    """Значение `ROOM_PUBLISH` для ночного `mesh_publish` из правил: `rooms.<комната>.publish` = "live" → `<комната>`,
    "next" → `<комната>=next` (кандидат); нет/false — комната не публикуется. Пусто — публикация как прежде (только гостиная).
    Гостиная — тот же ключ верхнего уровня (`publish`: "live" → `living`, её модели ещё и ПО ПРИВЯЗКЕ, `room_publish`,
    T-20261106-77/5); кандидата у гостиной здесь нет — "next" у неё не публикуется."""
    out = []
    for r in rooms or list(ROOMS):
        p = for_room(r).rules().get('publish')
        if p in ('live', True):
            out.append(r)
        elif p == 'next' and r != LIVING:
            out.append(f'{r}=next')
    return ','.join(out)


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    r, rest = room_arg(sys.argv[1:])
    if rest[:1] == ['--flag']:          # `--room X --flag F` → 1/0 (ночь; ошибка чтения — 0, ночь как при выключенном)
        print(night_flag(r or LIVING, rest[1]) if r else 0)
        sys.exit(0)
    if rest[:1] == ['--publish']:       # значение ROOM_PUBLISH для ночного mesh_publish (пусто — только гостиная)
        print(room_publish())
        sys.exit(0)
    print(json.dumps(describe(for_room(r)), ensure_ascii=False, indent=1))
