import Link from "next/link";
import { createFromRemont } from "@/app/estimate-actions";
import { estimateRemont, DEPTH_LABEL, type Depth, type BudgetVariant } from "@/lib/pricing/works";

export const metadata = {
  title: "Сколько стоит ремонт комнаты — расчёт бюджета по площади",
  description: "Прикиньте стоимость ремонта комнаты: эконом, средний и улучшенный вариант с разбивкой на работы и материалы.",
};

const rub = (n: number) => `${n.toLocaleString("ru-RU")} ₽`;
const inputStyle = {
  padding: "12px 14px", borderRadius: 10, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 16, fontFamily: "inherit", width: "100%",
} as const;
const DEPTHS: Depth[] = ["refresh", "update", "capital"];

export default async function RemontPage({ searchParams }: { searchParams: Promise<{ area?: string; depth?: string }> }) {
  const sp = await searchParams;
  const area = Number(String(sp.area ?? "").replace(",", ".")) || 0;
  const depth = (DEPTHS.includes(sp.depth as Depth) ? sp.depth : "update") as Depth;
  const show = area > 0;
  const variants = show ? estimateRemont(area, depth) : null;

  return (
    <main className="container">
      <p className="eyebrow">Расчёт стоимости</p>
      <h1>Сколько стоит ремонт комнаты</h1>
      <p className="muted">Введите площадь — покажем вилку бюджета: работы и материалы отдельно. Сможете сделать сами — минус работа.</p>

      <form method="get" className="stack" style={{ marginTop: 8 }}>
        <div className="row" style={{ gap: 12 }}>
          <div className="stack" style={{ flex: 1, minWidth: 140 }}>
            <label className="eyebrow">Площадь комнаты, м²</label>
            <input name="area" type="number" step="0.5" min="0" defaultValue={area || ""} placeholder="напр. 18" style={inputStyle} inputMode="decimal" />
          </div>
        </div>
        <div className="stack">
          <label className="eyebrow">Глубина ремонта</label>
          <div className="row">
            {DEPTHS.map((d) => (
              <label key={d} className="chip" data-selected={d === depth}>
                <input type="radio" name="depth" value={d} defaultChecked={d === depth} style={{ display: "none" }} />
                {DEPTH_LABEL[d]}
              </label>
            ))}
          </div>
          <p className="muted" style={{ fontSize: 13, margin: 0 }}>Выберите вариант и нажмите «Показать бюджет».</p>
        </div>
        <button type="submit" className="btn btn-block">Показать бюджет</button>
      </form>

      {variants ? (
        <div className="stack" style={{ marginTop: 24 }}>
          <p className="eyebrow">Ориентир для {area} м² · {DEPTH_LABEL[depth]}</p>
          {(["eco", "mid", "high"] as const).map((key) => {
            const v: BudgetVariant = variants[key];
            return (
              <div key={key} className="card stack">
                <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
                  <strong style={{ fontSize: 17 }}>{v.label}</strong>
                  <span style={{ fontSize: 20, fontWeight: 650 }}>{rub(v.totalRub)}</span>
                </div>
                <p className="muted" style={{ margin: 0, fontSize: 14 }}>
                  Работы {rub(v.worksRub)} · материалы {rub(v.materialsRub)} · сами — от {rub(v.materialsRub)}
                </p>
                <form action={createFromRemont}>
                  <input type="hidden" name="area" value={area} />
                  <input type="hidden" name="depth" value={depth} />
                  <input type="hidden" name="variant" value={key} />
                  <button type="submit" className="btn btn-secondary btn-block">Собрать смету по этому варианту</button>
                </form>
              </div>
            );
          })}
          <p className="note">
            Оценка ориентировочная (нормативы уточняются). Точные цены материалов — в смете по вашим ссылкам.
          </p>
        </div>
      ) : null}

      <p style={{ marginTop: 24 }}><Link className="muted" href="/calc">← Калькуляторы материалов</Link></p>
    </main>
  );
}
