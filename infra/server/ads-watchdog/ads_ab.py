#!/usr/bin/env python3
"""J-ADS (1 р/сутки): по ВСЕМ кампаниям — группе с ≥300 показов/7дн и низким CTR сгенерировать
и ДОБАВИТЬ один A/B-вариант (старые не трогаем; отключение слабых — человек). Посадочную (Href)
берём у существующего объявления группы; промпт — с контекстом сервиса кампании."""
import json, time
import common as c
import decisions as d

PROMPT = """Напиши ОДНО поисковое объявление Яндекс Директа. Рекламируемый сервис:
{service}
Группа: «{group}» (CTR низкий — нужен ДРУГОЙ угол подачи). Текущие объявления группы:
{current}

ЖЁСТКИЕ ПРАВИЛА: Title1 ≤ 56 символов; Title2 ≤ 30; Text ≤ 81. Только буквы/цифры/знаки
препинания (НЕЛЬЗЯ стрелки, эмодзи). НЕЛЬЗЯ чужие бренды (remplanner, planner 5d, планоплан).
Фокус на пользе (число/расчёт/бюджет/смета), без обещаний результата ремонта и «гарантий».
Ответь СТРОГО JSON: {{"title1": "...", "title2": "...", "text": "..."}}"""


def process(cid, role, service, st):
    rows = c.direct_report(f"wd_g7_{cid}", "ADGROUP_PERFORMANCE_REPORT",
                           ["AdGroupId", "AdGroupName", "Impressions", "Clicks"],
                           date_range="LAST_7_DAYS",
                           filters=[{"Field": "CampaignId", "Operator": "EQUALS", "Values": [str(cid)]}])
    if not rows:
        return
    ads = c.direct("ads", "get", {"SelectionCriteria": {"CampaignIds": [cid]},
                                  "FieldNames": ["Id", "AdGroupId", "State"],
                                  "TextAdFieldNames": ["Title", "Title2", "Text", "Href"]})["Ads"]
    by_group = {}
    for a in ads:
        by_group.setdefault(a["AdGroupId"], []).append(a)

    for gid_s, gname, imps_s, clicks_s in rows:
        gid, imps, clicks = int(gid_s), int(imps_s), int(clicks_s)
        group_ads = by_group.get(gid, [])
        last_add = st.get("ab_last", {}).get(str(gid), 0)
        if not d.group_needs_new_ad(imps, clicks, len(group_ads), (time.time() - last_add) / 86400):
            continue
        if not group_ads:
            continue
        href = group_ads[0]["TextAd"]["Href"]  # та же посадочная, что у группы
        current = "\n".join(f"- {a['TextAd']['Title']} / {a['TextAd'].get('Title2','')} / {a['TextAd']['Text']}" for a in group_ads)
        try:
            raw = c.llm_for_ads(PROMPT.format(service=service, group=gname, current=current))
            ad = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            t1, t2, text = ad["title1"].strip(), ad["title2"].strip(), ad["text"].strip()
        except Exception as e:
            c.log(f"[{role}] gemini/parse fail {gname}: {e}"); continue
        problems = d.valid_ad_texts(t1, t2, text)
        if problems:
            c.log(f"[{role}] {gname}: текст невалиден: {problems}"); continue

        msg = (f"✍️ «{role}» / группа «{gname}»: CTR {d.ctr(clicks, imps):.1%} при {imps} показах — "
               f"новый A/B-вариант:\n{t1} / {t2}\n{text}")
        if c.DRY:
            c.tg(msg + "\n(репетиция — в Директ не заливаю)")
        else:
            res = c.direct("ads", "add", {"Ads": [{"AdGroupId": gid, "TextAd": {
                "Title": t1, "Title2": t2, "Text": text, "Href": href, "Mobile": "NO"}}]})
            ar = res["AddResults"][0]
            if ar.get("Errors"):
                c.log(f"[{role}] ads.add errors: {ar['Errors']}"); continue
            c.direct("ads", "moderate", {"SelectionCriteria": {"Ids": [ar["Id"]]}})
            c.tg(msg + "\nЗалито и на модерацию. Старые объявления не трогал.")
            c.remember_action(st, f"[{role}] A/B в «{gname}»")
        st.setdefault("ab_last", {})[str(gid)] = time.time()


def main():
    if c.disabled():
        c.log("DISABLED"); return
    st = c.state_load()
    for cid, (role, service) in c.CAMPAIGNS.items():
        try:
            process(cid, role, service, st)
        except Exception as e:
            c.log(f"[{role}] ads_ab fail: {e}")
    c.state_save(st)
    c.log("ads_ab ok")


if __name__ == "__main__":
    main()
