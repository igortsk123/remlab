import Link from "next/link";
import { notFound } from "next/navigation";
import { CalcForm } from "@/components/CalcForm";
import { CalcBuilder } from "@/components/calc/CalcBuilder";
import { createFromCalc } from "@/app/estimate-actions";
import { isCalcV2 } from "@/lib/calc/flag";
import { CALC_META, COMPANIONS, type CalcKind } from "@/lib/estimate/companions";

const KINDS: CalcKind[] = ["oboi", "plitka", "kraska", "laminat"];

export default async function CalcPage({
  params,
  searchParams,
}: {
  params: Promise<{ kind: string }>;
  searchParams: Promise<{ v2?: string }>;
}) {
  const { kind } = await params;
  if (!KINDS.includes(kind as CalcKind)) notFound();
  const k = kind as CalcKind;
  const { v2 } = await searchParams;

  return (
    <main className="container">
      <p className="eyebrow">Калькулятор материалов</p>
      <h1>Сколько нужно: {CALC_META[k].title.toLowerCase()}</h1>

      {isCalcV2(v2) ? (
        <CalcBuilder kind={k} />
      ) : (
        <>
          <CalcForm kind={k} action={createFromCalc.bind(null, k)} />
          <div className="card stack" style={{ marginTop: 24 }}>
            <p className="eyebrow">Заодно не забудьте</p>
            <div className="row">
              {COMPANIONS[k].map((c) => (
                <span key={c} className="chip" data-selected="false">{c}</span>
              ))}
            </div>
            <p className="muted" style={{ fontSize: 14, margin: 0 }}>
              Добавим в вашу смету-список автоматически — чтобы купить всё за один раз.
            </p>
          </div>
        </>
      )}

      <p style={{ marginTop: 24 }}><Link className="muted" href="/calc">← Все калькуляторы</Link></p>
    </main>
  );
}
