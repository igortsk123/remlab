#!/usr/bin/env python3
"""J-REPORT (ежедневно 21:00 МСК): по ВСЕМ кампаниям — расход/клики/CPC + воронка сметы (Метрика)
+ действия роботов → Telegram."""
import time
import common as c


def campaign_block(cid, role):
    rows = c.direct_report(f"wd_daily_{cid}", "ADGROUP_PERFORMANCE_REPORT",
                           ["AdGroupName", "Impressions", "Clicks", "Cost"],
                           filters=[{"Field": "CampaignId", "Operator": "EQUALS", "Values": [str(cid)]}])
    if not rows:
        return None  # не крутилась сегодня — не шумим
    cost = sum(float(r[3]) for r in rows)
    clicks = sum(int(r[2]) for r in rows)
    imps = sum(int(r[0] if False else r[1]) for r in rows)
    head = f"▸ «{role}»: {cost:.0f} ₽ · {clicks} кл" + (f" · CPC {cost / clicks:.1f} ₽" if clicks else "")
    top = sorted(rows, key=lambda r: -float(r[3]))[:3]
    sub = [f"   {n}: {int(cl)} кл / {float(co):.0f} ₽" for n, i, cl, co in top if float(co) > 0]
    return "\n".join([head] + sub)


def main():
    if c.disabled():
        c.log("DISABLED"); return
    st = c.state_load()
    lines = [f"📊 remlab реклама — {time.strftime('%d.%m %H:%M')}"]

    any_spend = False
    for cid, (role, _svc) in c.CAMPAIGNS.items():
        blk = campaign_block(cid, role)
        if blk:
            lines.append(blk); any_spend = True
    if not any_spend:
        lines.append("Показов сегодня нет (кампании не крутятся / ждут баланса).")

    try:
        m = c.metrika_today()
        lines.append(f"Воронка сметы (Метрика): визиты {m['visits']} → расчёт {m['calc_started']} → "
                     f"смета {m['estimate_opened']} → сохранил {m['estimate_saved']} → "
                     f"клик по товару {m['ref_click']}")
    except Exception as e:
        c.log(f"metrika fail: {e}")

    acts = [a for a in st.get("actions", []) if a["ts"].startswith(time.strftime("%Y-%m-%d"))]
    if acts:
        lines.append("Роботы за сутки: " + "; ".join(a["what"] for a in acts))
    c.tg("\n".join(lines))
    c.log("report sent")


if __name__ == "__main__":
    main()
