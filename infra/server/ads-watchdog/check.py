#!/usr/bin/env python3
"""J-CHECK (каждые 30 мин): по ВСЕМ нашим кампаниям — стоп-кран (суммарный расход защищает общий
счёт, глушим виновника), события статуса, аномалии, авто-подъём потолка. Без AI. Единственный
джоб с правом suspend. Состояние — per-campaign в state.json (ключ "camp:<id>")."""
import time
import common as c
import decisions as d


def snapshot(cid):
    camp = c.direct("campaigns", "get", {
        "SelectionCriteria": {"Ids": [cid]},
        "FieldNames": ["Id", "State", "Status", "StatusPayment"],
        "TextCampaignFieldNames": ["BiddingStrategy"]})["Campaigns"][0]
    wb = camp["TextCampaign"]["BiddingStrategy"]["Search"].get("WbMaximumClicks") or {}
    return camp, (wb.get("BidCeiling", 0) / 1e6)


def today_stats(cid):
    rows = c.direct_report(f"wd_today_{cid}", "CUSTOM_REPORT",
                           ["CriterionType", "Impressions", "Clicks", "Cost"],
                           filters=[{"Field": "CampaignId", "Operator": "EQUALS", "Values": [str(cid)]}])
    imps = clicks = 0
    cost = at_cost = 0.0
    for crit, i, cl, co in rows:
        imps += int(i); clicks += int(cl); cost += float(co)
        if crit == "AUTOTARGETING":
            at_cost += float(co)
    return imps, clicks, cost, at_cost


def suspend(cid, reason: str):
    role = c.CAMPAIGNS[cid][0]
    if c.DRY:
        c.tg(f"⛔ СТОП-КРАН (репетиция, НЕ применяю): «{role}» — {reason}")
        return
    c.direct("campaigns", "suspend", {"SelectionCriteria": {"Ids": [cid]}})
    c.tg(f"⛔ СТОП-КРАН: «{role}» ПРИОСТАНОВЛЕНА — {reason}. Возобновление только вручную "
         f"(скажи Клоду «возобнови кампанию» после разбора).")


def main():
    if c.disabled():
        c.log("DISABLED — выходим"); return
    st = c.state_load()
    now = time.time()
    day = time.strftime("%Y-%m-%d")
    total_day_cost = 0.0
    per_campaign = []  # (cid, cost) для определения виновника суммарного стоп-крана

    for cid, (role, _svc) in c.CAMPAIGNS.items():
        key = f"camp:{cid}"
        cst = st.setdefault(key, {})
        camp, ceiling = snapshot(cid)
        state_now = f"{camp['State']}/{camp['Status']}/{camp['StatusPayment']}"

        # 1. События статуса
        prev = cst.get("state")
        if prev != state_now:
            c.log(f"[{role}] статус: {prev} -> {state_now}")
            if camp["Status"] == "REJECTED":
                c.tg(f"❌ «{role}»: модерация ОТКЛОНИЛА объявления — нужен разбор.")
            elif prev and camp["State"] == "ON":
                c.tg(f"🚀 «{role}» показывается! Автопилот следит: стоп-кран {d.DAY_STOP_RUB:.0f} ₽/день, {d.HOUR_STOP_RUB:.0f} ₽/час (на все кампании суммарно).")
            elif prev and camp["Status"] == "ACCEPTED" and camp["State"] == "OFF":
                c.tg(f"✅ «{role}»: модерация пройдена, ждёт денег на счёте.")
            cst["state"] = state_now
            c.remember_action(st, f"[{role}] {prev} → {state_now}")

        if camp["State"] == "SUSPENDED" and cst.get("we_suspended"):
            if cst.get("suspend_reminded_day") != day:
                c.tg(f"⏸ «{role}» стоит после стоп-крана — жду ручного решения.")
                cst["suspend_reminded_day"] = day
            continue

        if camp["State"] != "ON":
            continue

        # 2. Деньги
        imps, clicks, cost, at_cost = today_stats(cid)
        total_day_cost += cost
        per_campaign.append((cid, cost))
        pts = [p for p in cst.get("points", []) if p.get("day") == day]

        # 2a. Per-campaign стоп-кран (одна кампания сама превысила порог)
        if d.day_stop(cost):
            suspend(cid, f"расход кампании за день {cost:.0f} ₽ > {d.DAY_STOP_RUB:.0f} ₽")
            cst["we_suspended"] = not c.DRY
            c.remember_action(st, f"[{role}] стоп-кран день {cost:.0f} ₽")
        elif d.hour_stop(pts, now, cost):
            suspend(cid, f"расход кампании за час > {d.HOUR_STOP_RUB:.0f} ₽ (день {cost:.0f} ₽)")
            cst["we_suspended"] = not c.DRY
            c.remember_action(st, f"[{role}] стоп-кран час {cost:.0f} ₽")
        else:
            avg_cpc = cost / clicks if clicks else 0.0
            if avg_cpc > d.CPC_CEILING_RUB and cst.get("cpc_warned_day") != day:
                c.tg(f"⚠️ «{role}»: средний CPC {avg_cpc:.1f} ₽ выше потолка {d.CPC_CEILING_RUB:.0f} ₽.")
                cst["cpc_warned_day"] = day
            if d.at_share_alarm(at_cost, cost) and cst.get("at_warned_day") != day:
                c.tg(f"⚠️ «{role}»: автотаргетинг съел {at_cost / cost:.0%} расхода ({at_cost:.0f} ₽).")
                cst["at_warned_day"] = day
        pts.append({"ts": now, "cost": cost, "day": day})
        cst["points"] = pts[-60:]

        # 3. Мало показов 2 дня → потолок +5 ₽
        cst.setdefault("daily_imps", {})[day] = imps
        cst["daily_imps"] = dict(sorted(cst["daily_imps"].items())[-7:])
        days = sorted(cst["daily_imps"].items())
        if (len(days) >= 2 and all(v < d.LOW_IMPRESSIONS_PER_DAY for _, v in days[-2:])
                and now - cst.get("bid_raised_ts", 0) > 48 * 3600 and ceiling > 0):
            nxt = d.next_bid_ceiling(ceiling)
            if nxt is None:
                if cst.get("bid_max_warned_day") != day:
                    c.tg(f"⚠️ «{role}»: показов мало, потолок уже {ceiling:.0f} ₽ (максимум автопилота).")
                    cst["bid_max_warned_day"] = day
            elif c.DRY:
                c.tg(f"📈 «{role}»: поднял бы потолок {ceiling:.0f} → {nxt:.0f} ₽ (мало показов 2 дня).")
            else:
                wk = camp["TextCampaign"]["BiddingStrategy"]["Search"]["WbMaximumClicks"].get("WeeklySpendLimit", 3500000000)
                c.direct("campaigns", "update", {"Campaigns": [{"Id": cid, "TextCampaign": {
                    "BiddingStrategy": {"Search": {"BiddingStrategyType": "WB_MAXIMUM_CLICKS",
                        "WbMaximumClicks": {"WeeklySpendLimit": wk, "BidCeiling": int(nxt * 1e6)}},
                        "Network": {"BiddingStrategyType": "SERVING_OFF"}}}}]})
                cst["bid_raised_ts"] = now
                c.tg(f"📈 «{role}»: потолок клика поднят {ceiling:.0f} → {nxt:.0f} ₽.")
                c.remember_action(st, f"[{role}] BidCeiling {ceiling:.0f}→{nxt:.0f}")

    # 4. Суммарный стоп-кран по общему счёту (если сумма всех наших > порог) — глушим виновника
    if d.day_stop(total_day_cost) and per_campaign:
        cid, cost = max(per_campaign, key=lambda x: x[1])
        role = c.CAMPAIGNS[cid][0]
        if not st[f"camp:{cid}"].get("we_suspended"):
            suspend(cid, f"суммарный расход всех кампаний {total_day_cost:.0f} ₽ > {d.DAY_STOP_RUB:.0f} ₽; виновник «{role}» ({cost:.0f} ₽)")
            st[f"camp:{cid}"]["we_suspended"] = not c.DRY
            c.remember_action(st, f"суммарный стоп-кран {total_day_cost:.0f} ₽ → suspend {role}")

    st["total_day_cost"] = round(total_day_cost)
    c.state_save(st)
    c.log(f"check ok: {len(c.CAMPAIGNS)} кампаний, суммарный расход дня {total_day_cost:.0f} ₽")


if __name__ == "__main__":
    main()
