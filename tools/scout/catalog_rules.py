#!/usr/bin/env python3
"""Правила цепочки каталога — ЧИСТЫЕ функции, пригодные к проверке без базы и сети.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ (владелец 13.10: «тесты на ожидаемую бизнес-логику»). Правила цепочки
жили внутри длинных скриптов, которые при импорте СРАЗУ начинают платный прогон — проверить их
было нечем, и за зелёными тестами месяцами пряталась неработающая ступень. Правило, вынесенное
сюда, проверяется одной строкой и ровно тем же кодом, который работает в бою.

Сюда переезжает только то, что можно посчитать БЕЗ внешнего мира: отбор, предикаты, пороги.
Всё, что требует живых данных, проверяется сторожами и шагом `tests_chain.py --live`.
"""
from __future__ import annotations

# ФОТО РЕАЛЬНО СКАЧАЛОСЬ (план conv-05, ADR-0261). Поле пишет ОДИН писатель — `img_alive.py --sync-db`;
# здесь — единственная формулировка правила для SQL всех потребителей (оценка стиля, очередь моделей,
# отбор в комплекты, пул замен). NULL = «не проверяли» — не блокирует (новинки не теряем), считается в отчёте.
PHOTO_OK_SQL = "coalesce(p.photo_alive, true)"


def availability(media: dict | None) -> str:
    """Наличие в ТРИ состояния (план conv-09, Codex 13.10) по записи `catalog_media.media()`:
    `available` · `unavailable` (нет в каталоге или снят) · `unknown` (фид магазина не приехал — «не знаю»).
    Стоящий товар при `unknown` не снимаем; новую замену при `unknown` не берём."""
    if not media:
        return 'unavailable'
    st = media.get('state')
    return 'available' if st == 'available' else 'unknown' if st == 'unknown' else 'unavailable'


def photo_ok(photo_alive: bool | None) -> bool:
    """То же правило для Python: только явный приговор «мертво» исключает товар."""
    return photo_alive is not False


def twin_scores_sql(room: str) -> str:
    """Оценки стиля, уже лежащие в базе у товаров ОДНОЙ комнаты `room_catalog` (T-20261105-34/2).

    `product_style_scores` — одна строка на товар (общая у гостиной и комнат: спальня берёт оценку гостиной у
    близнеца модели). Раньше выборка соединялась с `room_catalog` без комнаты: товар спальни и прихожей давал две
    строки, а строки чужой комнаты попадали в словарь «уже оценено». Теперь — только товары своей комнаты, без дублей
    (`exists`, а не `join` + distinct: строка оценки одна на товар, сколько бы комнат его ни показывали)."""
    if not room.isascii() or not room.replace('_', '').isalpha():
        raise ValueError(f'комната {room!r}: ожидается имя вида bedroom/hall')
    return ("select s.shop_mid, s.external_id, s.scores, s.universal, s.src from product_style_scores s"
            " where exists (select 1 from room_catalog c where c.shop_mid = s.shop_mid"
            f" and c.external_id = s.external_id and c.room = '{room}')")


def daily_todo(todo: list, limit: int | None) -> list:
    """Дневная добивка: потолок считается от НЕСОСЧИТАННЫХ, а не от начала списка.

    До 11.10 лимит резал начало пула, а начало пула давно в кэше: `--limit 300` на полном кэше
    давал «скорить 0», и дневной шаг стиль-скоринга месяцами не добивал ничего, рапортуя «ок».
    Отсюда правило: на вход подаётся УЖЕ отфильтрованный список несосчитанных, лимит только
    ограничивает его длину.
    """
    if not limit or limit <= 0 or len(todo) <= limit:
        return todo
    return todo[:limit]
