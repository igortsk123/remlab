import Link from "next/link";
import { createFromRemont } from "@/app/estimate-actions";
import { estimateRemont, DEPTH_LABEL, REGION_LABEL, type Depth, type Region, type BudgetVariant } from "@/lib/pricing/works";
import { ComingSoon } from "@/components/ComingSoon";
import { TrackedSubmit } from "@/components/TrackedSubmit";
import { Button } from "@/components/base/buttons/button";

// Раздел закрыт заглушкой до запуска (launch-p1-vitrina); включение старого содержимого: NEXT_PUBLIC_SHOW_WIP=1.
const SHOW_WIP = process.env.NEXT_PUBLIC_SHOW_WIP === "1";

export const metadata = {
  title: "Сколько стоит ремонт комнаты: расчёт бюджета по площади",
  description: "Прикиньте стоимость ремонта комнаты: эконом, средний и улучшенный вариант с разбивкой на работы и материалы.",
  ...(SHOW_WIP ? {} : { robots: { index: false, follow: true } }),
};

const rub = (n: number) => `${n.toLocaleString("ru-RU")} ₽`;
// Нативные поля GET-формы (страница серверная, без JS), вид — токены UUI.
const inputCls =
  "w-full appearance-none rounded-lg bg-primary px-3.5 py-2.5 text-md text-primary shadow-xs ring-1 ring-primary outline-hidden transition duration-100 ease-linear ring-inset placeholder:text-fg-quaternary focus-visible:ring-2 focus-visible:ring-brand";
// Чип-радио: скрытая радиокнопка внутри label; has-checked подсвечивает выбор сразу, без JS.
const chipCls =
  "inline-flex cursor-pointer items-center rounded-full bg-primary px-3.5 py-2 text-md text-secondary ring-1 ring-border-primary ring-inset transition duration-100 has-checked:bg-brand-solid has-checked:text-white has-checked:ring-transparent hover:bg-secondary has-checked:hover:bg-brand-solid_hover";
const DEPTHS: Depth[] = ["refresh", "update", "capital"];
const REGIONS: Region[] = ["msk", "spb", "million", "mid", "small", "far"];

export default async function RemontPage({ searchParams }: { searchParams: Promise<{ area?: string; depth?: string; region?: string }> }) {
  if (!SHOW_WIP) {
    return (
      <ComingSoon
        icon="💰"
        title="Сколько стоит ремонт"
        lead="Готовим быструю прикидку бюджета: укажете площадь и уровень ремонта, получите вилку цен на материалы и работы. Проверяем цифры, чтобы не вводить вас в заблуждение."
      />
    );
  }
  const sp = await searchParams;
  const area = Number(String(sp.area ?? "").replace(",", ".")) || 0;
  const depth = (DEPTHS.includes(sp.depth as Depth) ? sp.depth : "update") as Depth;
  const region = (REGIONS.includes(sp.region as Region) ? sp.region : "msk") as Region;
  const show = area > 0;
  const variants = show ? estimateRemont(area, depth, region) : null;

  return (
    <main className="container">
      <p className="eyebrow">Расчёт стоимости</p>
      <h1>Сколько стоит ремонт комнаты</h1>
      <p className="muted">Введите площадь — покажем вилку бюджета: работы и материалы отдельно. Сможете сделать сами — минус работа.</p>

      <form method="get" className="stack" style={{ marginTop: 8 }}>
        <div className="row" style={{ gap: 12 }}>
          <div className="stack" style={{ flex: 1, minWidth: 140 }}>
            <label className="eyebrow">Площадь комнаты, м²</label>
            <input name="area" type="number" step="0.5" min="0" defaultValue={area || ""} placeholder="напр. 18" className={inputCls} inputMode="decimal" />
          </div>
        </div>
        <div className="stack">
          <label className="eyebrow">Глубина ремонта</label>
          <div className="row">
            {DEPTHS.map((d) => (
              <label key={d} className={chipCls}>
                <input type="radio" name="depth" value={d} defaultChecked={d === depth} className="sr-only" />
                {DEPTH_LABEL[d]}
              </label>
            ))}
          </div>
          <p className="muted" style={{ fontSize: 13, margin: 0 }}>Выберите вариант и нажмите «Показать бюджет».</p>
        </div>
        <div className="stack">
          <label className="eyebrow">Регион (влияет на стоимость работ)</label>
          <select name="region" defaultValue={region} className={inputCls}>
            {REGIONS.map((r) => (
              <option key={r} value={r}>{REGION_LABEL[r]}</option>
            ))}
          </select>
        </div>
        <Button type="submit" size="lg" className="w-full">Показать бюджет</Button>
      </form>

      {variants ? (
        <div className="stack" style={{ marginTop: 24 }}>
          <p className="eyebrow">Ориентир для {area} м² · {DEPTH_LABEL[depth]} · {REGION_LABEL[region]}</p>
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
                  <input type="hidden" name="region" value={region} />
                  <input type="hidden" name="variant" value={key} />
                  <TrackedSubmit goal="estimate_saved" label="Сохранить этот вариант в Мою лабораторию" color="secondary" className="w-full" />
                </form>
              </div>
            );
          })}
          <p className="note">
            Оценка ориентировочная (нормативы уточняются). Точные цены материалов — в расчёте по вашим ссылкам.
          </p>
        </div>
      ) : null}

      <p style={{ marginTop: 24 }}><Link className="muted" href="/calc">← Калькуляторы материалов</Link></p>
    </main>
  );
}
