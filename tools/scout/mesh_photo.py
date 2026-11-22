"""ВХОД МЕШЕЙ — одно правило выбора фото и сторож размера (ADR-0452, план mesh-input-hd-01, решение владельца TG 1792/1861/1864).

Правило: для меша берём САМОЕ КРУПНОЕ фото товара — `products.image_url_hd` (оригинал фото магазина), нет или пусто — `image_url` (превью 450 px).
Одно правило для всех товаров и всех моделей: SQL-места берут выражение из `photo_sql`, Python-места — `pick`. Свои `coalesce(image_url_hd, image_url)`
в коде не пишем (пустая строка в `image_url_hd` без `nullif` проглатывала бы превью: хеш и меш пошли бы по пустому адресу).

Сторож размера: меньшая (или большая — `measure` в конфиге) сторона ВЫРЕЗКИ предмета ниже порога `min_cut_side_px` → статус `photo_too_small`
(`check_size`; вердикт выносит `photo_fit.verdict_from_metrics` — через него же вердикт пишет `cutout_sync`, а `mesh_queue` пускает на ноды только `ok`).
Порог живёт в `rules/mesh-photo.json`; null — сторож выключен (замер и счётчик работают). Значение утверждает владелец по таблице `mesh_photo_survey.py`.

Без БД, сети и тяжёлых библиотек: модуль импортируется в CI и на ноде.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, 'rules', 'mesh-photo.json')
STATUS = 'photo_too_small'
MEASURES = ('min', 'long')


def photo_sql(alias: str | None = 'p', hd: str = 'image_url_hd', thumb: str = 'image_url') -> str:
    """SQL-выражение «адрес фото для меша»: HD, иначе превью; пустая строка = нет адреса."""
    a = f'{alias}.' if alias else ''
    return f"coalesce(nullif({a}{hd}, ''), nullif({a}{thumb}, ''))"


def pick(hd, thumb):
    """(адрес, поле) — `image_url_hd`, иначе `image_url`; (None, None) — адреса нет. Пробелы по краям и пустая строка = нет."""
    for field, v in (('image_url_hd', hd), ('image_url', thumb)):
        s = (v or '').strip() if isinstance(v, str) else ''
        if s:
            return s, field
    return None, None


def load_rules(path: str | None = None) -> dict:
    """Конфиг сторожа; нет файла или битый — сторож выключен (не гадаем порог)."""
    try:
        r = json.load(open(path or RULES, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return {'min_cut_side_px': None, 'measure': 'min'}
    m = r.get('measure') if r.get('measure') in MEASURES else 'min'
    t = r.get('min_cut_side_px')
    return {'min_cut_side_px': int(t) if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0 else None, 'measure': m}


def check_size(cut_wh, rules: dict | None = None):
    """(годно, причина). `cut_wh` — [ширина, высота] вырезки в пикселях. Порог не задан — всегда годно; размера нет — годно (решает другой вердикт)."""
    rules = rules if rules is not None else load_rules()
    thr = rules.get('min_cut_side_px')
    if not thr or not cut_wh or len(cut_wh) != 2:
        return True, None
    side = min(cut_wh) if rules.get('measure', 'min') == 'min' else max(cut_wh)
    if side < thr:
        which = 'меньшая' if rules.get('measure', 'min') == 'min' else 'большая'
        return False, f'вырезка {int(cut_wh[0])}×{int(cut_wh[1])} px: {which} сторона {int(side)} < порога {thr} px'
    return True, None


def hybrid_error(info) -> str | None:
    """Сбой гибридной маски (`hybrid_mask.refine` упал → вырезка осталась «голой» BiRefNet) из измерений вырезки — или None.
    Сбой НЕ должен теряться: вызывающий пишет его в свой отчёт/`inputs.json` и в журнал ночи (`WARN:hybrid_error`)."""
    e = info.get('hybrid_error') if isinstance(info, dict) else None
    return str(e) if e else None
