#!/usr/bin/env python3
"""Политика разворота мешей — ОДНО место для «что считается решённым» (план orient-cabinet-01, этап 1; T-20261105-56).

Авторитет фронта — `orientation_state` (ключ `sku|sha16|orient-v1`). Финальный yaw дают только решённые статусы
(`auto_resolved|human_resolved`); `vlm_pending`/`review_pending`/нет решения — НЕ финальны: вид сверху сохраняет
прежний опубликованный поворот, публикация не затирает прод. `cabinet_front` (фасад по глубине) решения больше не
перебивает: на листах T-36/5 он выбирал утопленную заднюю стенку в рамке.

Читают: `salad/topview_render.py` (поворот + подпись кэша), `salad/publish_merge.py --only-resolved` (фильтр
`orient.json`), `draft_render.py` (применять ли yaw в серверном 3D-кадре).

    python tools/scout/orient_policy.py --selftest
"""
import sys

RESOLVED = frozenset({'auto_resolved', 'human_resolved'})
# Версия правила поворота вида сверху: входит в подпись кэша (`topview_render.orient_sig`). Сменил правило — подними
# версию, иначе записи с прежней подписью возьмутся из кэша и новое правило до них не дойдёт.
#   p2 (05.11): yaw только из решённых, без перебивки cabinet_front, нерешённым — опубликованный поворот
YAW_POLICY = 'yaw-p2'
# Старые записи прода (до поля status): «уверенные» по источнику. `cabinet_` убран — фасад по глубине не судья.
_LEGACY_SURE = ('seat_agree', 'vlm_agree', 'confident', 'human')


def is_resolved(status) -> bool:
    return status in RESOLVED


def yaw_sure(oinfo: dict) -> bool:
    """Применять ли yaw записи `orient.json` в серверном 3D-кадре. Есть `status` (записи с этапа 1) — только
    решённые и не симметричные (владелец 31.08: симметричным разворот не нужен, стол «вставал криво»). Нет `status` —
    прежнее правило по строке источника, но без `cabinet_` (и `cabinet_conflict`/`cabinet_depth` не «уверенные»)."""
    oinfo = oinfo or {}
    src = str(oinfo.get('orient') or '')
    if 'status' in oinfo:
        return is_resolved(oinfo.get('status')) and 'symmetric' not in src
    return any(k in src for k in _LEGACY_SURE)


def publishable(local: dict, prod: dict | None) -> bool:
    """Идёт ли локальная запись вида сверху в прод `orient.json`. Только решённые; ручное решение прода
    (`human:*` — `/test/orient-review/`, агент-визуал) не затирается автоматическим, только `human_resolved` из БД."""
    if not is_resolved((local or {}).get('status')):
        return False
    if str((prod or {}).get('orient') or '').startswith('human:') and local.get('status') != 'human_resolved':
        return False
    return True


def selftest() -> int:
    fails = []

    def ok(cond, what):
        print(('  ✓ ' if cond else '  ✗ ') + what)
        if not cond:
            fails.append(what)

    ok(not yaw_sure({'yaw': 180, 'orient': 'orient-v1:cabinet_depth'}), 'старая запись cabinet_depth — не уверенная')
    ok(not yaw_sure({'yaw': 180, 'orient': 'orient-v1:review_pending:cabinet_conflict', 'status': 'review_pending'}),
       'cabinet_conflict со статусом review_pending — не уверенная')
    ok(not yaw_sure({'yaw': 180, 'orient': 'orient-v1:cabinet_conflict'}), 'cabinet_conflict без статуса — не уверенная')
    ok(not yaw_sure({'yaw': 90, 'orient': 'unresolved:vlm_pending', 'status': 'vlm_pending'}), 'vlm_pending — не уверенная')
    ok(yaw_sure({'yaw': 90, 'orient': 'orient-v1:auto_resolved:orienter+vlm_agree', 'status': 'auto_resolved'}),
       'auto_resolved vlm_agree — уверенная')
    ok(yaw_sure({'yaw': 90, 'orient': 'orient-v1:human_resolved:human:front_90', 'status': 'human_resolved'}),
       'human_resolved — уверенная')
    ok(not yaw_sure({'yaw': 90, 'orient': 'orient-v1:auto_resolved:symmetric_by_role', 'status': 'auto_resolved'}),
       'симметричная — не уверенная (как прежде)')
    ok(yaw_sure({'yaw': 0, 'orient': 'orient-v1:auto_resolved:orienter+seat_agree'}), 'старая seat_agree — уверенная (как прежде)')
    ok(yaw_sure({'yaw': 0, 'orient': 'human:orient-review:cur'}), 'старая human — уверенная (как прежде)')
    ok(not yaw_sure({'yaw': 90, 'orient': 'orient-v1:review_pending:vlm_disagree'}), 'старая review_pending — не уверенная')
    ok(not yaw_sure({}) and not yaw_sure(None), 'нет записи — не уверенная')
    ok(not publishable({'yaw': 0, 'status': 'vlm_pending'}, None), 'vlm_pending не публикуется')
    ok(not publishable({'yaw': 0, 'status': 'review_pending'}, {'yaw': 180}), 'review_pending не публикуется')
    ok(not publishable({'yaw': 0, 'orient': 'orient-v1:cabinet_depth'}, None), 'запись без статуса не публикуется')
    ok(publishable({'yaw': 0, 'status': 'auto_resolved'}, {'yaw': 180, 'orient': 'orient-v1:cabinet_depth'}),
       'auto_resolved заменяет прежний cabinet_depth')
    ok(not publishable({'yaw': 0, 'status': 'auto_resolved'}, {'yaw': 180, 'orient': 'human:orient-review:new'}),
       'ручное решение прода автоматическим не затирается')
    ok(publishable({'yaw': 0, 'status': 'human_resolved'}, {'yaw': 180, 'orient': 'human:orient-review:new'}),
       'human_resolved из БД заменяет ручное решение прода')
    print('политика разворота: ' + ('ВСЁ ЗЕЛЁНОЕ' if not fails else f'ПРОВАЛЫ {len(fails)}'))
    return 1 if fails else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    print(__doc__)
