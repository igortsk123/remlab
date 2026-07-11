#!/usr/bin/env python3
"""J-MINUS (каждые 2 ч, 08–22 МСК): по КАЖДОЙ нашей кампании — новые поисковые запросы →
Gemini-судейство с контекстом сервиса (мусор у калькуляторов/ремонта/AI разный) → ≤10 минусов.
Ядро семантики защищено стоп-листом (decisions.CORE_STOP_ROOTS) — робот не может его тронуть."""
import json
import common as c
import decisions as d

PROMPT = """Ты — специалист по Яндекс Директу. Рекламируемый сервис (эта кампания):
{service}
Ниже НОВЫЕ поисковые запросы, по которым показывалась реклама этой кампании. Реши, какие мусорные.

МИНУСОВАТЬ (мусор для ЭТОГО сервиса): не относящееся к его теме; скачать/кряк/торрент/пиратка;
профессиональный САПР и обучение (курсы/вакансии/сметчик); игры/аниме; б/у и доски объявлений;
чужие бренды-магазины; для калькулятора — тротуарная плитка, краска для металла/труб/фасада,
наливной пол; для ремонта — купля/продажа/аренда/ипотека недвижимости.
НЕ МИНУСОВАТЬ (целевое): всё по теме сервиса — расчёт/сколько нужно/стоимость/смета/материалы
для СВОЕЙ комнаты-квартиры, онлайн, бесплатно, по площади.
ПРАВИЛО: сомневаешься — НЕ минусуй. Извлекай МИНИМАЛЬНЫЙ минус-корень (1-2 слова).

Запросы (показы|клики|расход ₽):
{queries}

Ответь СТРОГО JSON: {{"minus": [{{"root": "слово", "from": "исходный запрос"}}]}}"""


def process(cid, role, service, st):
    key = f"camp:{cid}"
    cst = st.setdefault(key, {})
    if cst.get("we_suspended"):
        c.log(f"[{role}] на стоп-кране — минусовка спит"); return
    rows = c.direct_report(f"wd_q_{cid}", "SEARCH_QUERY_PERFORMANCE_REPORT",
                           ["Query", "Impressions", "Clicks", "Cost"],
                           filters=[{"Field": "CampaignId", "Operator": "EQUALS", "Values": [str(cid)]}])
    seen = set(cst.get("seen_queries", []))
    new = [(q, i, cl, co) for q, i, cl, co in rows if q not in seen]
    if not new:
        c.log(f"[{role}] новых запросов нет"); return

    listing = "\n".join(f"- {q} ({i}|{cl}|{co})" for q, i, cl, co in new[:120])
    try:
        raw = c.gemini(PROMPT.format(service=service, queries=listing))
        raw = raw[raw.find("{"):raw.rfind("}") + 1]
        candidates = [m["root"] for m in json.loads(raw).get("minus", [])]
    except Exception as e:  # Gemini упал — деньги защищает J-CHECK, пропускаем
        c.log(f"[{role}] gemini/parse fail: {e}"); return

    existing_res = c.direct("campaigns", "get", {"SelectionCriteria": {"Ids": [cid]},
                                                 "FieldNames": ["Id", "NegativeKeywords"]})
    existing = list((existing_res["Campaigns"][0].get("NegativeKeywords") or {}).get("Items", []))
    minus = d.filter_minus_candidates(candidates, set(existing))

    cst["seen_queries"] = (cst.get("seen_queries", []) + [q for q, *_ in new])[-5000:]
    if not minus:
        c.log(f"[{role}] новых {len(new)}, минусовать нечего"); return

    if c.DRY:
        c.tg(f"🧹 «{role}»: добавил бы минусы → " + ", ".join(minus) + f" (новых запросов {len(new)})")
    else:
        c.direct("campaigns", "update", {"Campaigns": [{"Id": cid, "NegativeKeywords": {"Items": existing + minus}}]})
        c.tg(f"🧹 «{role}»: минусы добавлены → " + ", ".join(minus) + f" (всего {len(existing) + len(minus)})")
        c.remember_action(st, f"[{role}] минусы: " + ", ".join(minus))


def main():
    if c.disabled():
        c.log("DISABLED"); return
    st = c.state_load()
    for cid, (role, service) in c.CAMPAIGNS.items():
        try:
            process(cid, role, service, st)
        except Exception as e:
            c.log(f"[{role}] minus fail: {e}")
    c.state_save(st)


if __name__ == "__main__":
    main()
