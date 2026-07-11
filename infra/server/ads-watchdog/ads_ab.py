#!/usr/bin/env python3
"""J-ADS (1 р/сутки): группе с ≥300 показов/7дн и CTR<2.5% — сгенерировать и ДОБАВИТЬ
один A/B-вариант объявления (старые не трогаем; отключение слабых — только человек)."""
import json, time
import common as c
import decisions as d

SITELINKS_SET = 1492835596
HREF = ("https://remont-lab.online/?utm_source=yandex&utm_medium=cpc&utm_campaign=remlab_search"
        "&utm_content={gbid}_{ad_id}&utm_term={keyword}&type={source_type}")

PROMPT = """Напиши ОДНО поисковое объявление Яндекс Директа для remont-lab.online: нейросеть
делает дизайн интерьера по фото комнаты и подбирает реальную мебель; есть бесплатная версия,
результат за минуты, на русском. Группа: «{group}». Текущие объявления группы (CTR низкий,
нужен ДРУГОЙ угол подачи):
{current}

ЖЁСТКИЕ ПРАВИЛА: Title1 ≤ 56 символов; Title2 ≤ 30; Text ≤ 81. Только буквы/цифры/знаки
препинания (НЕЛЬЗЯ стрелки, эмодзи, кавычки-ёлочки можно). НЕЛЬЗЯ упоминать чужие бренды
(remplanner, planner 5d, планоплан и т.п.). Не обещать результат ремонта, не писать «гарантия».
Ответь СТРОГО JSON: {{"title1": "...", "title2": "...", "text": "..."}}"""


def main():
    if c.disabled():
        c.log("DISABLED"); return
    st = c.state_load()
    rows = c.direct_report("wd_groups7", "ADGROUP_PERFORMANCE_REPORT",
                           ["AdGroupId", "AdGroupName", "Impressions", "Clicks"],
                           date_range="LAST_7_DAYS",
                           filters=[{"Field": "CampaignId", "Operator": "EQUALS",
                                     "Values": [str(c.CAMPAIGN_ID)]}])
    if not rows:
        c.log("статистики по группам нет (кампания не крутится?)"); return

    ads = c.direct("ads", "get", {"SelectionCriteria": {"CampaignIds": [c.CAMPAIGN_ID]},
                                  "FieldNames": ["Id", "AdGroupId", "State"],
                                  "TextAdFieldNames": ["Title", "Title2", "Text"]})["Ads"]
    by_group = {}
    for a in ads:
        by_group.setdefault(a["AdGroupId"], []).append(a)

    for gid_s, gname, imps_s, clicks_s in rows:
        gid, imps, clicks = int(gid_s), int(imps_s), int(clicks_s)
        last_add = st.get("ab_last", {}).get(str(gid), 0)
        if not d.group_needs_new_ad(imps, clicks, len(by_group.get(gid, [])),
                                    (time.time() - last_add) / 86400):
            continue
        current = "\n".join(f"- {a['TextAd']['Title']} / {a['TextAd']['Title2']} / {a['TextAd']['Text']}"
                            for a in by_group.get(gid, []))
        try:
            raw = c.gemini(PROMPT.format(group=gname, current=current))
            ad = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            t1, t2, text = ad["title1"].strip(), ad["title2"].strip(), ad["text"].strip()
        except Exception as e:
            c.log(f"gemini/parse fail для {gname}: {e}"); continue
        problems = d.valid_ad_texts(t1, t2, text)
        if problems:
            c.log(f"{gname}: текст не прошёл валидацию: {problems}"); continue

        msg = (f"✍️ Группа «{gname}»: CTR {d.ctr(clicks, imps):.1%} при {imps} показах — "
               f"новый A/B-вариант:\n{t1} / {t2}\n{text}")
        if c.DRY:
            c.tg(msg + "\n(репетиция — в Директ не заливаю)")
        else:
            res = c.direct("ads", "add", {"Ads": [{"AdGroupId": gid, "TextAd": {
                "Title": t1, "Title2": t2, "Text": text, "Href": HREF,
                "Mobile": "NO", "SitelinkSetId": SITELINKS_SET}}]})
            ar = res["AddResults"][0]
            if ar.get("Errors"):
                c.log(f"ads.add errors: {ar['Errors']}"); continue
            c.direct("ads", "moderate", {"SelectionCriteria": {"Ids": [ar["Id"]]}})
            c.tg(msg + "\nЗалито и отправлено на модерацию. Старые объявления не трогал.")
            c.remember_action(st, f"A/B-текст в «{gname}»")
        st.setdefault("ab_last", {})[str(gid)] = time.time()

    c.state_save(st)
    c.log("ads_ab ok")


if __name__ == "__main__":
    main()
