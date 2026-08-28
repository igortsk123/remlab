#!/usr/bin/env python3
"""Ворота, общие для ПЕРВИЧНОЙ сборки сетов и для лечения слотов.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Ворота подбора жили только в `sets_incremental._slot_ok`, то есть
работали при ЛЕЧЕНИИ, а первичная сборка (`compose2.pick2`) шла мимо — это прямо признано
в шапке `mesh_ready.py`. Значит любое новое правило («коллажи в сеты не пускать») включалось
бы задним числом: негодный товар сперва попадал в сет, и только ночное лечение его выносило.
Владелец просил обратного — «на этапе выбора сетов проверку добавь».

Здесь лежат ровно те ворота, которые обязаны действовать в ОБОИХ путях. Геометрия слота
(конверт, пропорции, привязка ковра) остаётся на местах: она уже дублирована сознательно и
завязана на контекст сета, а перенос её сюда — отдельная и рискованная операция.

ЭТАПНОСТЬ. Как и мешевый гейт, ворота фото вводятся постепенно (`PHOTO_FIT_PHASE`):
  off     — не режет никого (значение по умолчанию, пока пул не оценён);
  shadow  — не режет, но считает и печатает, кого бы вырезало;
  new     — режет ТОЛЬКО первичную сборку и замены; опубликованные сеты живут как жили;
  full    — режет везде.
Резкий переход в `full` на неоценённом пуле схлопнул бы банк за один вечер: неизвестное
годным не считается.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PHOTO_FIT_PHASE = os.environ.get('PHOTO_FIT_PHASE', 'off')
_SHADOW: dict[str, int] = {}


def _fit(sku: str) -> str:
    try:
        from photo_fit import photo_fit
        return photo_fit(sku)
    except Exception:  # noqa: BLE001 — нет БД/таблиц: молчим, а не выдаём «годно» за факт
        return 'unknown'


def photo_ok(sku: str, *, context: str = 'heal') -> bool:
    """Годится ли фото товара. `context`: 'new' — первичная сборка или замена, 'published' —
    проверка уже стоящего в сете."""
    v = _fit(sku)
    if v != 'ok':
        _SHADOW[v] = _SHADOW.get(v, 0) + 1
    if PHOTO_FIT_PHASE in ('off', 'shadow'):
        return True
    if PHOTO_FIT_PHASE == 'new' and context == 'published':
        return True
    # Неизвестное годным НЕ считается: иначе правило «коллажи в сеты не проходят» держится
    # только на тех товарах, до которых успел дойти preflight.
    return v == 'ok'


def mesh_ok(sku: str) -> bool:
    """Есть ли годный меш по ТЕКУЩЕМУ фото. Фазы — внутри `mesh_ready` (MESH_GATE_PHASE)."""
    try:
        from mesh_ready import gate_active, mesh_ready
        return mesh_ready(sku) if gate_active() else True
    except Exception:  # noqa: BLE001 — в жёсткой фазе сбой предиката закрывает слот
        return os.environ.get('MESH_GATE_PHASE', 'off') in ('off', 'shadow')


# Требование меша к ЗАМЕНЕ вводится этапно — как и всё остальное. Сегодня покрытие резерва 0%
# (Salad-мешей ещё нет), и жёсткое `require` молча остановило бы лечение целиком: каждый
# выбывший товар оставлял бы дыру. Поэтому по умолчанию `prefer` — сперва ищем кандидата с
# мешом, и только если такого нет, берём обычного. `require` включать, когда покрытие вырастет.
HEAL_MESH_MODE = os.environ.get('HEAL_REQUIRE_MESH', 'prefer')   # prefer|require


def substitute_ok(sku: str, *, strict: bool | None = None) -> bool:
    """Кандидат на ЗАМЕНУ. Требования строже обычных: у замены должен быть готовый меш,
    иначе смысл «заменителя с готовым мешом» теряется — подменим товар и получим дыру
    в визуализации вместо починки.

    `strict=True` — первый проход лечения (ищем именно с мешом); `strict=False` — второй,
    запасной. Без аргумента режим берётся из `HEAL_REQUIRE_MESH`.
    """
    if not photo_ok(sku, context='new'):
        return False
    want_mesh = (HEAL_MESH_MODE == 'require') if strict is None else strict
    return _mesh_ready_strict(sku) if want_mesh else True


def _mesh_ready_strict(sku: str) -> bool:
    """Готовность меша БЕЗ оглядки на фазу гейта: для замен она обязательна всегда."""
    try:
        from mesh_ready import mesh_ready
        return mesh_ready(sku)
    except Exception:  # noqa: BLE001
        return False


def shadow_report() -> dict[str, int]:
    """Кого бы вырезали ворота фото в текущем прогоне (для фазы shadow)."""
    return dict(_SHADOW)
