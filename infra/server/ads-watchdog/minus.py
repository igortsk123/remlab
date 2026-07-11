#!/usr/bin/env python3
"""J-MINUS (каждые 2 ч, 08–23 МСК): новые поисковые запросы → Gemini-судейство → ≤10 минусов.
Ядро семантики защищено стоп-листом (decisions.CORE_STOP_ROOTS) — его робот тронуть не может."""
import json
import common as c
import decisions as d

PROMPT = """Ты — специалист по Яндекс Директу. Сервис: remont-lab.online — нейросеть делает
дизайн интерьера по фото комнаты и подбирает мебель (бесплатная версия есть). Кампания — Поиск.
Ниже НОВЫЕ поисковые запросы, по которым показывалась реклама. Реши, какие мусорные.

МИНУСОВАТЬ (мусор): ванная/санузел/кухонные гарнитуры как отдельная тема; ландшафт/участок/
фасад/сад; скачать/кряк/торрент/пиратка; профессиональный САПР (автокад, 3ds max, рендер для
дизайнеров); курсы/обучение/вакансии; игры/аниме/симс; б/у и доски объявлений; чужие
бренды-магазины; запросы про найм бригады «под ключ».
НЕ МИНУСОВАТЬ (целевые): всё про дизайн/интерьер/ремонт СВОЕЙ комнаты-квартиры, нейросети/ИИ
для интерьера, по фото, онлайн, бесплатно, планировка/расстановка мебели, подбор мебели, стили.
ПРАВИЛО: сомневаешься — НЕ минусуй. Из запроса извлекай МИНИМАЛЬНЫЙ минус-корень (1-2 слова).

Запросы (показы|клики|расход ₽):
{queries}

Ответь СТРОГО JSON без пояснений: {{"minus": [{{"root": "слово", "from": "исходный запрос"}}]}}"""


def main():
    if c.disabled():
        c.log("DISABLED"); return
    st = c.state_load()
    if st.get("we_suspended"):
        c.log("кампания на стоп-кране — минусовка спит"); return

    rows = c.direct_report("wd_queries", "SEARCH_QUERY_PERFORMANCE_REPORT",
                           ["Query", "Impressions", "Clicks", "Cost"],
                           filters=[{"Field": "CampaignId", "Operator": "EQUALS",
                                     "Values": [str(c.CAMPAIGN_ID)]}])
    seen = set(st.get("seen_queries", []))
    new = [(q, i, cl, co) for q, i, cl, co in rows if q not in seen]
    if not new:
        c.log("новых запросов нет"); return

    listing = "\n".join(f"- {q} ({i}|{cl}|{co})" for q, i, cl, co in new[:120])
    try:
        raw = c.gemini(PROMPT.format(queries=listing))
        raw = raw[raw.find("{"):raw.rfind("}") + 1]
        candidates = [m["root"] for m in json.loads(raw).get("minus", [])]
    except Exception as e:  # Gemini упал — деньги защищает J-CHECK, просто пропускаем ран
        c.log(f"gemini/parse fail: {e}"); return

    existing_res = c.direct("campaigns", "get", {"SelectionCriteria": {"Ids": [c.CAMPAIGN_ID]},
                                                 "FieldNames": ["Id", "NegativeKeywords"]})
    existing = [w for w in (existing_res["Campaigns"][0].get("NegativeKeywords") or {}).get("Items", [])]
    minus = d.filter_minus_candidates(candidates, set(existing))

    st["seen_queries"] = (st.get("seen_queries", []) + [q for q, *_ in new])[-5000:]
    if not minus:
        c.log(f"новых {len(new)}, минусовать нечего")
        c.state_save(st); return

    if c.DRY:
        c.tg("🧹 Минусовка: добавил бы минусы → " + ", ".join(minus) +
             f" (новых запросов {len(new)})")
    else:
        c.direct("campaigns", "update", {"Campaigns": [{
            "Id": c.CAMPAIGN_ID, "NegativeKeywords": {"Items": existing + minus}}]})
        c.tg("🧹 Минусовка: добавлено → " + ", ".join(minus) +
             f" (всего минусов {len(existing) + len(minus)})")
        c.remember_action(st, "минусы: " + ", ".join(minus))
    c.state_save(st)


if __name__ == "__main__":
    main()
