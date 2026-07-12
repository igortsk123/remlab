import Link from "next/link";
import { notFound } from "next/navigation";
import { CalcBuilder } from "@/components/calc/CalcBuilder";
import { CALC_META, type CalcKind } from "@/lib/estimate/companions";

const KINDS: CalcKind[] = ["oboi", "plitka", "kraska", "laminat"];

export function generateStaticParams() {
  return KINDS.map((kind) => ({ kind }));
}

export default async function CalcPage({ params }: { params: Promise<{ kind: string }> }) {
  const { kind } = await params;
  if (!KINDS.includes(kind as CalcKind)) notFound();
  const k = kind as CalcKind;

  return (
    <main className="container">
      <p className="eyebrow">Калькулятор материалов</p>
      <h1>Сколько нужно: {CALC_META[k].title.toLowerCase()}</h1>

      <CalcBuilder kind={k} />

      <p style={{ marginTop: 24 }}><Link className="muted" href="/calc">← Все калькуляторы</Link></p>
    </main>
  );
}
