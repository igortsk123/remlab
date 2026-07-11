#!/usr/bin/env python3
"""J-REPORT (ежедневно 21:00 МСК): сводка Директ + воронка Метрики + действия роботов → Telegram."""
import time
import common as c


def main():
    if c.disabled():
        c.log("DISABLED"); return
    st = c.state_load()
    lines = [f"📊 remlab реклама — {time.strftime('%d.%m %H:%M')}"]

    rows = c.direct_report("wd_daily", "ADGROUP_PERFORMANCE_REPORT",
                           ["AdGroupName", "Impressions", "Clicks", "Cost"],
                           filters=[{"Field": "CampaignId", "Operator": "EQUALS",
                                     "Values": [str(c.CAMPAIGN_ID)]}])
    if rows:
        total_cost = sum(float(r[3]) for r in rows)
        total_clicks = sum(int(r[2]) for r in rows)
        lines.append(f"Расход {total_cost:.0f} ₽ · кликов {total_clicks} · "
                     f"CPC {total_cost / total_clicks:.1f} ₽" if total_clicks
                     else f"Расход {total_cost:.0f} ₽ · кликов 0")
        for name, imps, clicks, cost in rows:
            i, cl = int(imps), int(clicks)
            ctr = f"{cl / i:.1%}" if i else "—"
            lines.append(f"· {name}: {i} пок / {cl} кл (CTR {ctr}) / {float(cost):.0f} ₽")
    else:
        lines.append("Показов сегодня нет (кампания не крутится или день пустой).")

    try:
        m = c.metrika_today()
        lines.append(f"Метрика: визиты {m['visits']} → бриф {m['01_project_started']} → "
                     f"фото {m['02_photo_uploaded']} → превью {m['04_preview_ready']} → "
                     f"пейволл {m['05_paywall_viewed']} → оплата {m['06_pack_unlocked']}")
    except Exception as e:
        c.log(f"metrika fail: {e}")

    acts = [a for a in st.get("actions", []) if a["ts"].startswith(time.strftime("%Y-%m-%d"))]
    if acts:
        lines.append("Роботы за сутки: " + "; ".join(a["what"] for a in acts))
    c.tg("\n".join(lines))
    c.log("report sent")


if __name__ == "__main__":
    main()
