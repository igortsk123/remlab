import Link from "next/link";
import { CALC_META, type CalcKind } from "@/lib/estimate/companions";

export const metadata = {
  title: "Калькуляторы материалов — сколько нужно обоев, плитки, краски, ламината",
  description: "Посчитайте, сколько материалов нужно на ремонт комнаты, и соберите смету со списком покупок.",
};

const ORDER: CalcKind[] = ["oboi", "plitka", "kraska", "laminat"];
const ICON: Record<CalcKind, string> = { oboi: "🧻", plitka: "🧱", kraska: "🎨", laminat: "🪵" };

export default function CalcHub() {
  return (
    <main className="container">
      <h1>Сколько нужно материалов?</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        Введите размеры комнаты — посчитаем количество с запасом и соберём смету-список,
        чтобы ничего не забыть в магазине.
      </p>

      <div className="grid-cards" style={{ marginTop: 20 }}>
        {ORDER.map((k) => (
          <Link key={k} href={`/calc/${k}`} className="card stack" style={{ textDecoration: "none", gap: 6 }}>
            <span style={{ fontSize: 30 }}>{ICON[k]}</span>
            <strong>{CALC_META[k].title}</strong>
            <span className="muted" style={{ fontSize: 14 }}>Расчёт для {CALC_META[k].verb}</span>
          </Link>
        ))}
      </div>

      <div className="card stack" style={{ marginTop: 24 }}>
        <p className="eyebrow">Не знаете, сколько всего стоит?</p>
        <p style={{ margin: 0 }}>Прикиньте бюджет ремонта комнаты по площади — с разбивкой на работы и материалы.</p>
        <Link className="btn btn-secondary" href="/calc/remont">Рассчитать стоимость ремонта</Link>
      </div>

      <p style={{ marginTop: 24 }}><Link className="muted" href="/">← На главную</Link></p>
    </main>
  );
}
