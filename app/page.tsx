import Link from "next/link";
import { LabBadge } from "@/components/LabBadge";

export const metadata = {
  title: "remont-lab: посчитать материалы для ремонта и собрать смету",
  description:
    "Помощник по ремонту своими руками. Калькуляторы обоев, плитки, краски и ламината: посчитаем количество с запасом, соберём список покупок и сохраним смету по ссылке.",
};

// soon: сервис закрыт заглушкой до запуска (launch-p1-vitrina) — плитка ведёт на страницу «в разработке».
const SCENARIOS = [
  { href: "/calc", icon: "🧮", title: "Посчитать материалы", desc: "Обои, плитка, краска, ламинат: сколько нужно с запасом", soon: false },
  { href: "/calc/remont", icon: "💰", title: "Сколько стоит ремонт", desc: "Бюджет комнаты по площади: работы и материалы отдельно", soon: true },
  { href: "/start", icon: "🖼️", title: "Дизайн по фото", desc: "Загрузите фото, и ИИ покажет комнату в новом стиле", soon: true },
  { href: "/styles", icon: "🎨", title: "Узнай свой стиль", desc: "Полистайте интерьеры, подскажем, что вам ближе", soon: true },
  { href: "/sovety", icon: "🛠️", title: "Советы по ремонту", desc: "Как клеить, грунтовать и штукатурить своими руками", soon: true },
  { href: "/lab", icon: "🧪", title: "Моя лаборатория", desc: "Сохранённые расчёты и сметы всегда под рукой", soon: false },
];

export default function Home() {
  return (
    <main className="container">
      <p className="eyebrow">Ремонт своими руками</p>
      <h1>Сделайте ремонт хорошо и недорого. Сами.</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        remont-lab: помощник по ремонту. Посчитайте материалы и бюджет, соберите смету-список,
        подберите стиль и не переплатите. Смета сохраняется по ссылке, чтобы в магазине ничего не забыть.
      </p>

      <div className="row" style={{ margin: "24px 0 8px", gap: 12 }}>
        <Link className="btn" href="/calc" style={{ flex: "1 1 220px" }}>🧮 Посчитать материалы</Link>
        <Link className="btn btn-secondary" href="/calc/remont" style={{ flex: "1 1 220px" }}>
          💰 Сколько стоит ремонт<span className="soon-badge">Скоро</span>
        </Link>
      </div>

      <p className="eyebrow" style={{ marginTop: 28 }}>Что внутри</p>
      <div className="grid-cards" style={{ marginTop: 12 }}>
        {SCENARIOS.map((s) => (
          <Link key={s.href} href={s.href} className="card stack" style={{ textDecoration: "none", gap: 6 }}>
            <span style={{ fontSize: 28 }}>{s.icon}</span>
            <strong>
              {s.title}
              {s.soon && <span className="soon-badge">Скоро</span>}
              {s.href === "/lab" && <LabBadge />}
            </strong>
            <span className="muted" style={{ fontSize: 14 }}>{s.desc}</span>
          </Link>
        ))}
      </div>

      <div className="card stack" style={{ marginTop: 28 }}>
        <p className="eyebrow">Как это работает</p>
        <ol className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>Введите размеры комнаты в калькуляторе</li>
          <li>Получите количество материалов с запасом и цены</li>
          <li>Сохраните расчёт в Мою лабораторию и добавьте ссылки на товары</li>
          <li>Покупайте по списку: ничего не забудете и не переплатите</li>
        </ol>
      </div>

      <p className="muted center" style={{ marginTop: 28, fontSize: 15 }}>
        Ремонт перестаёт пугать, когда всё посчитано. Считаем и подсказываем, а делаете вы сами.
      </p>
    </main>
  );
}
