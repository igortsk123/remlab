#!/usr/bin/env python3
"""J-CHECK (каждые 30 мин): стоп-кран по деньгам, аномалии, события статуса, авто-подъём потолка.
Детерминированный — без AI. Единственный джоб с правом suspend."""
import time
import common as c
import decisions as d


def campaign_snapshot():
    camp = c.direct("campaigns", "get", {
        "SelectionCriteria": {"Ids": [c.CAMPAIGN_ID]},
        "FieldNames": ["Id", "State", "Status", "StatusPayment"],
        "TextCampaignFieldNames": ["BiddingStrategy"]})["Campaigns"][0]
    ceiling = camp["TextCampaign"]["BiddingStrategy"]["Search"]["WbMaximumClicks"]["BidCeiling"] / 1e6
    return camp, ceiling


def today_stats():
    rows = c.direct_report("wd_today", "CUSTOM_REPORT",
                           ["CriterionType", "Impressions", "Clicks", "Cost"],
                           filters=[{"Field": "CampaignId", "Operator": "EQUALS",
                                     "Values": [str(c.CAMPAIGN_ID)]}])
    imps = clicks = 0
    cost = at_cost = 0.0
    for crit, i, cl, co in rows:
        imps += int(i); clicks += int(cl); cost += float(co)
        if crit == "AUTOTARGETING":
            at_cost += float(co)
    return imps, clicks, cost, at_cost


def suspend(reason: str):
    if c.DRY:
        c.tg(f"⛔ СТОП-КРАН (репетиция, НЕ применяю): {reason}")
        return
    c.direct("campaigns", "suspend", {"SelectionCriteria": {"Ids": [c.CAMPAIGN_ID]}})
    c.tg(f"⛔ СТОП-КРАН: {reason}. Кампания ПРИОСТАНОВЛЕНА. Возобновление — только вручную "
         f"(скажи Клоду «возобнови кампанию» после разбора).")


def main():
    if c.disabled():
        c.log("DISABLED — выходим"); return
    st = c.state_load()
    now = time.time()
    camp, ceiling = campaign_snapshot()
    state_now = f"{camp['State']}/{camp['Status']}/{camp['StatusPayment']}"

    # 1. События статуса (модерация/старт/отклонение)
    prev = st.get("campaign_state")
    if prev != state_now:
        c.log(f"смена статуса: {prev} -> {state_now}")
        if camp["Status"] == "REJECTED":
            c.tg("❌ Модерация ОТКЛОНИЛА объявления — нужен разбор (скажи Клоду).")
        elif prev and camp["State"] == "ON":
            c.tg("🚀 Кампания показывается! (баланс пополнен / модерация пройдена). "
                 "Автопилот следит: стоп-кран 700 ₽/день, 300 ₽/час.")
        elif prev and camp["Status"] == "ACCEPTED" and camp["State"] == "OFF":
            c.tg("✅ Модерация пройдена. Кампания ждёт денег на счёте — включится сама.")
        st["campaign_state"] = state_now
        c.remember_action(st, f"статус {prev} → {state_now}")

    if camp["State"] == "SUSPENDED" and st.get("we_suspended"):
        if st.get("suspend_reminded_day") != time.strftime("%Y-%m-%d"):
            c.tg("⏸ Кампания стоит после стоп-крана — жду ручного решения.")
            st["suspend_reminded_day"] = time.strftime("%Y-%m-%d")
        c.state_save(st); return

    # 2. Деньги (только если крутится)
    if camp["State"] == "ON":
        imps, clicks, cost, at_cost = today_stats()
        day = time.strftime("%Y-%m-%d")
        pts = [p for p in st.get("points", []) if p.get("day") == day]
        if d.day_stop(cost):
            suspend(f"расход за день {cost:.0f} ₽ > {d.DAY_STOP_RUB:.0f} ₽")
            st["we_suspended"] = not c.DRY
            c.remember_action(st, f"стоп-кран день: {cost:.0f} ₽")
        elif d.hour_stop(pts, now, cost):
            suspend(f"расход за час > {d.HOUR_STOP_RUB:.0f} ₽ (день: {cost:.0f} ₽)")
            st["we_suspended"] = not c.DRY
            c.remember_action(st, f"стоп-кран час: {cost:.0f} ₽")
        else:
            avg_cpc = cost / clicks if clicks else 0.0
            if avg_cpc > d.CPC_CEILING_RUB and st.get("cpc_warned_day") != day:
                c.tg(f"⚠️ Средний CPC {avg_cpc:.1f} ₽ выше потолка {d.CPC_CEILING_RUB:.0f} ₽ — аномалия стратегии.")
                st["cpc_warned_day"] = day
            if d.at_share_alarm(at_cost, cost) and st.get("at_warned_day") != day:
                c.tg(f"⚠️ Автотаргетинг съел {at_cost / cost:.0%} расхода ({at_cost:.0f} ₽) — минусовка усилена.")
                st["at_warned_day"] = day
        pts.append({"ts": now, "cost": cost, "day": day})
        st["points"] = pts[-60:]

        # 3. Мало показов 2 дня подряд → потолок +5 ₽ (до 25, раз в 48ч)
        st.setdefault("daily_imps", {})[day] = imps
        st["daily_imps"] = dict(sorted(st["daily_imps"].items())[-7:])
        days = sorted(st["daily_imps"].items())
        if (len(days) >= 2 and all(v < d.LOW_IMPRESSIONS_PER_DAY for _, v in days[-2:])
                and now - st.get("bid_raised_ts", 0) > 48 * 3600):
            nxt = d.next_bid_ceiling(ceiling)
            if nxt is None:
                if st.get("bid_max_warned_day") != day:
                    c.tg(f"⚠️ Показов мало, но потолок уже {ceiling:.0f} ₽ (максимум автопилота). Выше — только человек.")
                    st["bid_max_warned_day"] = day
            elif c.DRY:
                c.tg(f"📈 Поднял бы потолок клика {ceiling:.0f} → {nxt:.0f} ₽ (мало показов 2 дня).")
            else:
                c.direct("campaigns", "update", {"Campaigns": [{"Id": c.CAMPAIGN_ID, "TextCampaign": {
                    "BiddingStrategy": {"Search": {"BiddingStrategyType": "WB_MAXIMUM_CLICKS",
                        "WbMaximumClicks": {"WeeklySpendLimit": 3500000000,
                                            "BidCeiling": int(nxt * 1e6)}},
                        "Network": {"BiddingStrategyType": "SERVING_OFF"}}}}]})
                st["bid_raised_ts"] = now
                c.tg(f"📈 Потолок клика поднят {ceiling:.0f} → {nxt:.0f} ₽ (мало показов 2 дня подряд).")
                c.remember_action(st, f"BidCeiling {ceiling:.0f}→{nxt:.0f}")

    c.state_save(st)
    c.log(f"check ok: {state_now}")


if __name__ == "__main__":
    main()
