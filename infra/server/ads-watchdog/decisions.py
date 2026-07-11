"""Чистые решающие функции автопилота — пороги владельца (2026-07-11) и валидации.
Без сети и состояния: всё тестируется юнитами."""

DAY_STOP_RUB = 700.0          # владелец: стоп-кран при > 700 ₽/день
HOUR_STOP_RUB = 300.0         # владелец: > 300 ₽/час
CPC_CEILING_RUB = 20.0        # потолок стратегии — выше среднего = аномалия
AT_SHARE_WARN = 0.30          # автотаргетинг > 30% расхода дня
BID_MAX_RUB = 25.0            # владелец: авто-потолок ставки
BID_STEP_RUB = 5.0
LOW_IMPRESSIONS_PER_DAY = 50
MINUS_MAX_PER_RUN = 10
CTR_MIN = 0.025               # ниже при >=300 показов — группе нужен новый текст
ADS_MAX_PER_GROUP = 3  # лимит Директа (комбинаторных объявлений в группе)

# Ядро семантики: роботу ЗАПРЕЩЕНО минусовать слова, содержащие эти корни.
CORE_STOP_ROOTS = ("нейросет", "дизайн", "интерьер", "комнат", "квартир", "фото", "онлайн",
                   "бесплатн", "планировщик", "расстановк", "мебел", "ремонт", "стил", "ии")

FORBIDDEN_AD_CHARS = "→←↑↓•™®§€$#@^*_~<>{}[]|\\"


def day_stop(cost_today_rub: float) -> bool:
    return cost_today_rub > DAY_STOP_RUB


def hour_stop(points: list[dict], now_ts: float, cost_now_rub: float) -> bool:
    """points: [{"ts": unix, "cost": rub}] за сегодня. Сравниваем с точкой 45–90 мин назад."""
    past = [p for p in points if 45 * 60 <= now_ts - p["ts"] <= 90 * 60]
    if not past:
        return False
    base = min(past, key=lambda p: abs(now_ts - p["ts"] - 3600))
    return cost_now_rub - base["cost"] > HOUR_STOP_RUB


def at_share_alarm(at_cost_rub: float, total_cost_rub: float) -> bool:
    return total_cost_rub >= 100 and (at_cost_rub / total_cost_rub) > AT_SHARE_WARN


def next_bid_ceiling(current_rub: float) -> float | None:
    """Следующий шаг подъёма потолка или None, если выше нельзя (дальше — человек)."""
    if current_rub >= BID_MAX_RUB:
        return None
    return min(current_rub + BID_STEP_RUB, BID_MAX_RUB)


def is_core_word(word: str) -> bool:
    w = word.lower().strip()
    return any(root in w for root in CORE_STOP_ROOTS)


def filter_minus_candidates(candidates: list[str], existing: set[str]) -> list[str]:
    """Срезает ядро, дубли и лишнее сверх лимита. candidates — минус-корни от Gemini."""
    out = []
    for c in candidates:
        c = c.strip().lower()
        if not c or c in existing or c in out:
            continue
        if any(is_core_word(tok) for tok in c.split()):
            continue
        out.append(c)
        if len(out) >= MINUS_MAX_PER_RUN:
            break
    return out


def ctr(clicks: int, impressions: int) -> float:
    return clicks / impressions if impressions else 0.0


def group_needs_new_ad(impressions_7d: int, clicks_7d: int, ads_count: int,
                       days_since_last_add: float) -> bool:
    return (impressions_7d >= 300 and ctr(clicks_7d, impressions_7d) < CTR_MIN
            and ads_count < ADS_MAX_PER_GROUP and days_since_last_add >= 7)


def valid_ad_texts(t1: str, t2: str, text: str) -> list[str]:
    """Список проблем; пусто = ок. Правила Директа + наши (без чужих брендов)."""
    problems = []
    if not (1 <= len(t1) <= 56): problems.append(f"Title1 длина {len(t1)} (1–56)")
    if not (1 <= len(t2) <= 30): problems.append(f"Title2 длина {len(t2)} (1–30)")
    if not (1 <= len(text) <= 81): problems.append(f"Text длина {len(text)} (1–81)")
    for field, val in (("Title1", t1), ("Title2", t2), ("Text", text)):
        bad = sorted({ch for ch in val if ch in FORBIDDEN_AD_CHARS})
        if bad: problems.append(f"{field}: запрещённые символы {bad}")
    lower = f"{t1} {t2} {text}".lower()
    for brand in ("remplanner", "ремпланнер", "ремпланер", "planner 5d", "планер 5д",
                  "планоплан", "planoplan", "reroom", "flatplan", "икеа", "ikea", "леруа"):
        if brand in lower: problems.append(f"чужой бренд в тексте: {brand}")
    return problems
