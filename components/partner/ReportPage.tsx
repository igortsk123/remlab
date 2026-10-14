"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { LoadingIndicator } from "@/components/application/loading-indicator/loading-indicator";
import { ShortTable, StepList } from "@/components/partner/FunnelTable";
import type { ReportData } from "@/components/partner/types";

// Отчёт застройщику (план b2b-03, ADR-0265). Ключ — во #фрагменте адреса: на сервер уходит только
// заголовком, в журнал Caddy не пишется, Метрики на этой странице нет (`app/layout.tsx`).
const keyFromHash = () => (typeof window === "undefined" ? "" : window.location.hash.replace(/^#/, ""));
const ru = (d: string) => new Date(`${d}T00:00:00Z`).toLocaleDateString("ru-RU", { day: "numeric", month: "short", timeZone: "UTC" });

export function ReportPage() {
  const [data, setData] = useState<ReportData | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "denied" | "error">("loading");

  const load = useCallback(async () => {
    setState("loading");
    try {
      const res = await fetch("/api/partner/report", { headers: { "x-partner-key": keyFromHash() }, cache: "no-store" });
      if (res.status === 403) return setState("denied");
      const j = await res.json().catch(() => null);
      if (!res.ok || !j?.ok) return setState("error");
      setData(j as ReportData);
      setState("ready");
    } catch {
      setState("error");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (state === "loading") return <div className="stack center" style={{ padding: 48 }}><LoadingIndicator label="Собираем отчёт" /></div>;
  if (state === "denied") return <p className="note">Ссылка на отчёт неверная или отозвана. Попросите новую у remont-lab.</p>;
  if (state === "error" || !data) {
    return <div className="stack"><p className="note">Не получилось загрузить отчёт. Проверьте интернет.</p><Button onClick={() => void load()}>Повторить</Button></div>;
  }

  const apt = (id: string | null) => (id ? data.apartments[id] ?? id : "");
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="stack" style={{ gap: 4 }}>
        <h1 style={{ margin: 0 }}>{data.partner.name}: ссылки покупателям</h1>
        <p className="muted" style={{ margin: 0 }}>
          Неделя — когда менеджер отправил ссылку; результат — на сегодня. Считаем ссылки, а не людей. «Связались», «встреча»,
          «сделка», «отказ» ставят ваши менеджеры — это текущий статус ссылки. Влияние на сделки оценивайте по своей статистике.
        </p>
      </div>
      {data.total.sent === 0 ? (
        <p className="note">За последние 12 недель менеджеры ещё не отправляли ссылок.</p>
      ) : (
        <>
          <div className="stack" style={{ gap: 6 }}>
            <h2 style={{ margin: 0, fontSize: 18 }}>За 12 недель</h2>
            <StepList row={data.total} />
          </div>
          <div className="stack" style={{ gap: 6 }}>
            <h2 style={{ margin: 0, fontSize: 18 }}>По неделям отправки</h2>
            <ShortTable label="Неделя" rows={data.weeks.map((r) => ({ title: `с ${ru(r.week)}`, row: r }))} />
          </div>
          {data.byApartment.length > 1 ? (
            <div className="stack" style={{ gap: 6 }}>
              <h2 style={{ margin: 0, fontSize: 18 }}>По квартирам</h2>
              <ShortTable label="Квартира" rows={data.byApartment.map((r) => ({ title: apt(r.apartmentId), row: r }))} />
            </div>
          ) : null}
        </>
      )}
      <div className="stack" style={{ gap: 6 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>Заходы без ссылки менеджера</h2>
        <p className="muted" style={{ margin: 0 }}>Действия, а не люди: один человек может открыть страницу несколько раз.</p>
        {data.direct.length === 0 ? <p className="note">Заходов пока не было.</p> : (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {data.direct.map((r) => (
              <li key={`${r.week}|${r.apartmentId}`}>
                с {ru(r.week)}, {apt(r.apartmentId)}: открытий {r.designerOpen}, смотрели варианты {r.variantView}, замен {r.itemSwap}, передвигали {r.itemMove}, поделились {r.share}, в 3D {r.flat3dOpen}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
