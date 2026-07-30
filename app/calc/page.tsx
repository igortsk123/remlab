import Link from "next/link";
import { CALC_META, type CalcKind } from "@/lib/estimate/companions";

export const metadata = {
  title: "Калькуляторы материалов: сколько нужно обоев, плитки, краски, ламината",
  description: "Посчитайте, сколько материалов нужно на ремонт комнаты, и соберите смету со списком покупок.",
};

// Баннер бюджета скрыт до запуска входа Б (launch-p1-vitrina); включение: NEXT_PUBLIC_SHOW_WIP=1.
const SHOW_WIP = process.env.NEXT_PUBLIC_SHOW_WIP === "1";

const ORDER: CalcKind[] = ["oboi", "plitka", "kraska", "laminat"];
// Иконки владельца (единый стиль, PNG 512×512 с прозрачным фоном) — public/icons/calc/<kind>.png.

export default function CalcHub() {
  return (
    <main className="container">
      <h1>Сколько нужно материалов?</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        Введите размеры комнаты, посчитаем количество с запасом и соберём смету-список,
        чтобы ничего не забыть в магазине.
      </p>

      <div className="grid-cards" style={{ marginTop: 20 }}>
        {ORDER.map((k) => (
          <Link key={k} href={`/calc/${k}`} className="card stack" style={{ textDecoration: "none", gap: 6 }}>
            {/* Обычный <img>, НЕ next/image: standalone-прод без sharp, а 8–20 КБ PNG оптимизировать нечего. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/icons/calc/${k}.png`} alt="" width={44} height={44} style={{ display: "block" }} />

            <strong>{CALC_META[k].title}</strong>
            <span className="muted" style={{ fontSize: 14 }}>Расчёт для {CALC_META[k].verb}</span>
          </Link>
        ))}
      </div>

      {SHOW_WIP && (
        <div className="card stack" style={{ marginTop: 24 }}>
          <p className="eyebrow">Не знаете, сколько всего стоит?</p>
          <p style={{ margin: 0 }}>Прикиньте бюджет ремонта комнаты по площади: работы и материалы отдельно.</p>
          <Link className="btn btn-secondary" href="/calc/remont">Рассчитать стоимость ремонта</Link>
        </div>
      )}

      <p style={{ marginTop: 24 }}><Link className="muted" href="/">← На главную</Link></p>
    </main>
  );
}
